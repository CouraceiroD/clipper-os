"""Modo automático: um URL de live/VOD -> 3 Shorts finalizados, tudo local, sem serviços pagos extra.

    python -m clipper auto "<URL>"

VOD -> yt-dlp -> faster-whisper (local) -> Claude Code (`claude -p`, a tua subscrição) escolhe os momentos
-> FFmpeg: corte, silêncios, 9:16, hook, legendas, áudio normalizado -> outputs/<vod-id>/clip-NN.mp4 + report.md

Caches (download, transcrição, análise) ficam em data/sources/<vod-id>/; voltar a correr é quase instantâneo.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from . import analyze as an
from .costs import CostTracker
from .db import DB
from .download import fetch, probe_meta, safe_id, source_dir
from .render import render_clip
from .transcribe import all_words, caption_transcript, transcribe

FILL_MIN_SCORE = 50   # se não houver 3 momentos >= min_score, completa com os melhores >= 50 (assinalados)


def _fmt(t: float | None) -> str:
    if t is None:
        return "?"
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def timestamp_link(url: str, t: float) -> str | None:
    if not url.startswith("http"):
        return None
    sec = int(t)
    if "twitch.tv" in url:
        h, r = divmod(sec, 3600)
        m, s = divmod(r, 60)
        return f"{url}{'&' if '?' in url else '?'}t={h}h{m}m{s}s"
    if "youtube.com" in url or "youtu.be" in url:
        return f"{url}{'&' if '?' in url else '?'}t={sec}s"
    return None


def run(source: str, cfg: dict, n_clips: int = 3, reanalyze: bool = False, force: bool = False) -> Path:
    t0 = time.time()
    tracker = CostTracker()
    db = DB(cfg["workdir"])
    a = cfg["analyze"]
    a["max_clips"] = n_clips

    print("[1/5] a verificar o vídeo")
    meta = probe_meta(source)
    minutes = (meta.get("duration") or 0) / 60
    print(f"      {meta.get('title')} · {meta.get('channel')} · {minutes:.0f} min")
    if meta.get("is_live"):
        sys.exit("Esta live ainda está a decorrer. Corre outra vez quando o VOD estiver disponível.")
    if minutes > cfg["clipping"]["max_vod_minutes"] and not force:
        sys.exit(f"Vídeo com {minutes:.0f} min > max_vod_minutes={cfg['clipping']['max_vod_minutes']}. "
                 "Usa --force se for mesmo este.")

    print("[2/5] download (yt-dlp)")
    with tracker.stage("download"):
        meta = fetch(source, cfg)
    db.upsert_source(meta, "downloaded")
    cache = source_dir(cfg["workdir"], meta["source_id"])

    print("[3/5] transcrição local (faster-whisper)")
    tpath = cache / "transcript.json"
    fresh = not tpath.exists()
    with tracker.stage("transcribe"):
        transcript = transcribe(meta["video_path"], tpath, cfg)
        captions = caption_transcript(meta["video_path"], transcript, cache, cfg)
    if fresh:
        tracker.transcribed_minutes = transcript["duration"] / 60
    db.upsert_source(meta, "transcribed")

    print("[4/5] Claude a escolher os momentos com mais potencial viral")
    raw_path = cache / "analysis.json"
    archive_lang = None
    with tracker.stage("analyze"):
        if raw_path.exists() and not reanalyze:
            print("      (análise em cache; --reanalyze para repetir)")
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            old_lang = raw.get("metadata_language", an.LEGACY_LANGUAGE)
            if old_lang != a["metadata_language"]:
                # mesmos momentos e scores; só os textos mudam de idioma. A versão anterior fica guardada.
                shutil.copyfile(raw_path, cache / f"analysis.{safe_id(old_lang)}.json")
                raw = an.localize(raw, transcript, meta, cfg, tracker)
                raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
                archive_lang = old_lang
        else:
            raw = an.analyze(transcript, meta, cfg, tracker)
            raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    db.reset_source(meta["source_id"])
    rejected: list[dict] = []
    chosen = an.select(copy.deepcopy(raw), transcript, cfg, db, meta["source_id"],
                       rejected=rejected, fill_min_score=FILL_MIN_SCORE)
    if not chosen:
        sys.exit("O Claude não encontrou nenhum momento com potencial suficiente neste vídeo. "
                 f"Vê os candidatos em {raw_path}")
    print(f"      {len(chosen)} momento(s) escolhido(s) de {len(raw['clips'])} candidatos")

    print("[5/5] a montar os Shorts (FFmpeg)")
    out = Path(cfg["output_dir"]) / safe_id(meta["source_id"])
    out.mkdir(parents=True, exist_ok=True)
    if archive_lang:   # Shorts anteriores noutro idioma: guardados em <out>/<idioma>/ em vez de apagados
        keep = out / safe_id(archive_lang)
        keep.mkdir(exist_ok=True)
        for old in [*out.glob("clip-*.mp4"), *out.glob("report.md")]:
            shutil.move(str(old), keep / old.name)
        print(f"      versão anterior ({archive_lang}) guardada em {keep}")
    for old in out.glob("clip-*.mp4"):
        old.unlink()
    words = all_words(transcript)
    cap_words = all_words(captions) if captions else None
    for i, h in enumerate(chosen, 1):
        t = time.time()
        with tracker.stage("render"):
            clip = render_clip(meta["video_path"], h, words, cache / "render" / f"clip-{i:02d}", cfg["render"],
                               caption_words=cap_words)
        final = out / f"clip-{i:02d}.mp4"
        shutil.move(str(clip), final)
        h["file"] = final.name
        h["render_seconds"] = round(time.time() - t, 1)
        h["transcript"] = " ".join(w["word"] for w in words
                                   if w["start"] >= h["start"] - 0.05 and w["end"] <= h["end"] + 0.05)
        db.add_clip(meta["source_id"], h, str(final))

    from .compare import probe
    for h in chosen:
        h["media"] = probe(str(out / h["file"]))
    costs = tracker.to_dict()
    (out / "report.md").write_text(report(meta, chosen, rejected, raw, costs, cfg, time.time() - t0),
                                   encoding="utf-8")
    db.upsert_source(meta, "done")
    print(f"\n✅ {len(chosen)} Short(s) prontos em {out}")
    for h in chosen:
        print(f"   {h['file']}  [{h['viral_score']}]  {h['title']}")
    print(f"   Relatório: {out / 'report.md'}")
    return out


def report(meta: dict, chosen: list[dict], rejected: list[dict], raw: dict, costs: dict, cfg: dict,
           seconds: float) -> str:
    url = meta.get("url", "")
    L = [f"# Shorts — {meta.get('title')}", "",
         f"- Fonte: {url}",
         f"- Canal: {meta.get('channel')} · duração {_fmt(meta.get('duration'))}",
         f"- Gerado: {datetime.now().strftime('%Y-%m-%d %H:%M')} · layout `{cfg['render']['layout']}` · "
         f"Whisper `{cfg['transcribe']['model']}` · textos em `{raw.get('metadata_language', an.LEGACY_LANGUAGE)}`", ""]
    if raw.get("video_summary"):
        L += ["## Resumo do vídeo", "", raw["video_summary"], ""]

    L += ["## Shorts", "", "| Ficheiro | Score | Momento original | Duração final | Título |", "|---|---|---|---|---|"]
    for h in chosen:
        L.append(f"| `{h['file']}` | {h['viral_score']}{' ⚠' if h.get('below_threshold') else ''} | "
                 f"{_fmt(h['start'])} → {_fmt(h['end'])} | {h['media'].get('duration')}s | {h['title']} |")
    L.append("")

    for h in chosen:
        link = timestamp_link(url, h["start"])
        L += [f"### {h['file']} — {h['title']}", "",
              f"**Porque foi escolhido:** {h['why_viral']}", "",
              f"- Hook no ecrã: **{h['hook_text']}**",
              f"- Momento original: {_fmt(h['start'])} → {_fmt(h['end'])}" + (f" ([ver na fonte]({link}))" if link else ""),
              f"- Categoria: `{h['category']}` · viral score **{h['viral_score']}**/100 "
              f"(gancho {h['hook_score']}, emoção {h['emotion_score']}, payoff {h['payoff_score']}, "
              f"funciona isolado {h['standalone_score']} — escala 0-10)",
              f"- Resumo: {h['summary']}"]
        if h.get("below_threshold"):
            L.append(f"- ⚠ Abaixo do limiar ({cfg['analyze']['min_score']}): incluído para completar os "
                     f"{len(chosen)} Shorts. Revê antes de publicar.")
        L += [f"- Título: {h['title']}",
              f"- Descrição: {h['description']}",
              f"- Hashtags: {' '.join('#' + x.lstrip('#') for x in h['hashtags'])}",
              f"- Texto para thumbnail: **{h['thumbnail_text']}**",
              f"- Transcrição: _{h['transcript'][:400]}{'…' if len(h['transcript']) > 400 else ''}_", ""]

    if rejected:
        L += ["## Momentos considerados e rejeitados", ""]
        for r in sorted(rejected, key=lambda x: x["viral_score"], reverse=True)[:10]:
            L.append(f"- {_fmt(r['start'])} [{r['viral_score']}] {r['title']} — {r['reject_reason']}")
        L.append("")

    c = costs
    L += ["## Processamento", "",
          f"- Tempo total: {seconds / 60:.1f} min · etapas (s): {json.dumps(c['stages_seconds'], ensure_ascii=False)}",
          f"- Minutos transcritos agora: {c['transcribed_minutes']} (Whisper local, grátis; 0 = cache)",
          (f"- Claude: {c['claude']['input_tokens']} tokens in / {c['claude']['output_tokens']} out "
           f"(via Claude Code; com subscrição não há custo extra)" if c["claude"]["calls"]
           else "- Claude: análise reutilizada da cache (0 tokens nesta execução)"),
          "- Serviços pagos adicionais: nenhum. Nada foi publicado nem carregado.", ""]
    return "\n".join(L) + "\n"
