"""Gera comparison.json e report.md (own vs OpusClip) para um VOD."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def probe(path: str) -> dict:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration,size,bit_rate:stream=codec_type,width,height,r_frame_rate",
             "-of", "json", path], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    d = json.loads(out)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
    f = d.get("format", {})
    return {
        "width": v.get("width"), "height": v.get("height"),
        "fps": round(int(num) / max(int(den or 1), 1), 2) if num else None,
        "duration": round(float(f.get("duration", 0)), 2),
        "size_mb": round(int(f.get("size", 0)) / 1e6, 1),
        "bitrate_kbps": round(int(f.get("bit_rate", 0)) / 1000) if f.get("bit_rate") else None,
        "has_audio": any(s.get("codec_type") == "audio" for s in d.get("streams", [])),
    }


def _iou(a: dict, b: dict) -> float:
    if None in (a.get("start_time"), a.get("end_time"), b.get("start_time"), b.get("end_time")):
        return 0.0
    inter = min(a["end_time"], b["end_time"]) - max(a["start_time"], b["start_time"])
    union = max(a["end_time"], b["end_time"]) - min(a["start_time"], b["start_time"])
    return max(0.0, inter) / union if union > 0 else 0.0


def _fmt_t(t) -> str:
    if t is None:
        return "?"
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _cell(v) -> str:
    return str(v if v is not None else "—").replace("|", "/").replace("\n", " ")


def _avg(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 1) if xs else None


def build(meta: dict, results: dict[str, list[dict]], costs: dict, out_dir: Path) -> dict:
    for clips in results.values():
        for c in clips:
            if c.get("file"):
                c["media"] = probe(c["file"])
                c["final_duration"] = c["media"].get("duration")

    overlaps = []
    own, opus = results.get("own", []), results.get("opusclip", [])
    for a in own:
        best = max(opus, key=lambda b: _iou(a, b), default=None)
        if best and _iou(a, best) > 0.2:
            overlaps.append({"own_rank": a["rank"], "opusclip_rank": best["rank"], "iou": round(_iou(a, best), 2)})

    stages = costs.get("stages_seconds", {})
    summary = {}
    for prov, clips in results.items():
        summary[prov] = {
            "candidates": len(clips),
            "rendered": sum(1 for c in clips if c.get("rendered")),
            "avg_virality_score": _avg(c.get("virality_score") for c in clips),
            "avg_engagement_score": _avg(c.get("engagement_score") for c in clips),
            "avg_duration": _avg(c.get("duration") for c in clips),
            "processing_seconds": round(sum(v for k, v in stages.items() if k.startswith(prov + ".")), 1),
            "claude_cost_usd": round(sum(x["cost_usd"] for x in costs["claude"]["calls"]
                                         if x["purpose"].startswith(prov + ".")), 4),
        }
    if "opusclip" in summary:
        summary["opusclip"]["credits_used"] = costs.get("opusclip", {}).get("credits_used")
        summary["opusclip"]["credits_unit"] = costs.get("opusclip", {}).get("credits_unit")
        summary["opusclip"]["server_processing_seconds"] = costs.get("opusclip", {}).get("processing_seconds")
    if "own" in summary:
        summary["own"]["transcription_seconds"] = stages.get("transcribe")
        summary["own"]["download_seconds"] = stages.get("download")

    comparison = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {k: meta.get(k) for k in ("source_id", "url", "title", "channel", "duration")},
        "summary": summary,
        "shared_moments": overlaps,
        "clips": [c for clips in results.values() for c in clips],
        "costs": costs,
    }
    (out_dir / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.md").write_text(_report(comparison, results), encoding="utf-8")
    return comparison


def _report(cmp: dict, results: dict[str, list[dict]]) -> str:
    s, src, costs = cmp["summary"], cmp["source"], cmp["costs"]
    L = [f"# Comparação de clipping — {src.get('title')}", "",
         f"Fonte: {src.get('url')}  ", f"Canal: {src.get('channel')} · duração {_fmt_t(src.get('duration'))}  ",
         f"Gerado: {cmp['generated_at']}", ""]

    provs = list(results)
    L += ["## Resumo", "", "| | " + " | ".join(provs) + " |", "|---|" + "---|" * len(provs)]
    rows = [("Candidatos", "candidates"), ("Shorts renderizados", "rendered"),
            ("Virality score médio", "avg_virality_score"), ("Engagement médio", "avg_engagement_score"),
            ("Duração média (s)", "avg_duration"), ("Tempo de processamento (s)", "processing_seconds"),
            ("Custo Claude (USD)", "claude_cost_usd")]
    for label, k in rows:
        L.append(f"| {label} | " + " | ".join(str(s[p].get(k, "—")) for p in provs) + " |")
    if "opusclip" in s:
        L.append("| Créditos OpusClip | " + " | ".join(
            f"{s[p].get('credits_used')} {s[p].get('credits_unit') or ''}" if p == "opusclip" else "0"
            for p in provs) + " |")
    L += ["", "> Os scores de cada engine usam escalas diferentes (Claude 0-100; OpusClip conforme a API). "
          "Compara a ordenação dentro de cada engine, não os números entre engines.", ""]

    ranks = sorted({c["rank"] for cl in results.values() for c in cl})
    if ranks:
        L += ["## Lado a lado", "",
              "| # | Provider | Início → fim | Duração (final) | Título | Hook | Engagement | Virality | "
              "Edição | Render (s) | Custo |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in ranks:
            for p in provs:
                c = next((x for x in results[p] if x["rank"] == r), None)
                if not c:
                    continue
                cost = f"{c.get('estimated_cost_usd')} USD"
                if c.get("estimated_credits") is not None:
                    cost += f" + {c['estimated_credits']} cr"
                rendered = "🎬 " if c.get("rendered") else ""
                L.append(f"| {r} | {p} | {_fmt_t(c.get('start_time'))} → {_fmt_t(c.get('end_time'))} | "
                         f"{c.get('duration')}s ({c.get('final_duration') or '—'}s) | {rendered}{_cell(c.get('title'))} | "
                         f"{_cell(c.get('hook'))} | {c.get('engagement_score')} | {c.get('virality_score')} | "
                         f"{_cell(c.get('editing'))} | {c.get('render_time')} | {cost} |")
        L += ["", "🎬 = renderizado/exportado. Motivos de seleção em detalhe mais abaixo.", ""]

    if cmp["shared_moments"]:
        L += ["## Momentos escolhidos por ambos", ""]
        for o in cmp["shared_moments"]:
            L.append(f"- own #{o['own_rank']} ≈ opusclip #{o['opusclip_rank']} (sobreposição {o['iou']:.0%})")
        L.append("")
    elif len(provs) > 1:
        L += ["## Momentos escolhidos por ambos", "", "Nenhum (ou o OpusClip não devolveu timestamps).", ""]

    for p in provs:
        L += [f"## {p}", ""]
        for c in results[p]:
            tag = "🎬" if c.get("rendered") else "📝"
            L += [f"### {tag} #{c['rank']} {c['title']}",
                  f"- Intervalo: {_fmt_t(c.get('start_time'))} → {_fmt_t(c.get('end_time'))} "
                  f"({c.get('duration')}s → final {c.get('final_duration') or '—'}s)",
                  f"- Virality: **{c.get('virality_score')}** · engagement: {c.get('engagement_score')}",
                  f"- Hook: {c.get('hook')}",
                  f"- Edição: {c.get('editing')}",
                  f"- Porquê: {c.get('reason_selected')}"]
            if c.get("file"):
                m = c.get("media", {})
                L.append(f"- Ficheiro: `{Path(c['file']).name}` · {m.get('width')}x{m.get('height')} "
                         f"@{m.get('fps')}fps · {m.get('size_mb')} MB · render {c.get('render_time')}s")
            if c.get("transcript"):
                t = c["transcript"]
                L.append(f"- Transcrição: _{t[:280]}{'…' if len(t) > 280 else ''}_")
            L.append("")

    L += ["## Avaliação manual (preenche depois de ver os vídeos)", "",
          "Nota 1-5. Vê os clips lado a lado no telemóvel, com som.", "",
          "| Critério | own | opusclip |", "|---|---|---|"]
    for crit in ["Escolha dos momentos", "Qualidade dos cortes (início/fim)", "Hook nos primeiros 3s",
                 "Legendas (precisão + estilo)", "Reframing / enquadramento", "Qualidade visual final",
                 "Publicaria sem mexer?"]:
        L.append(f"| {crit} | | |")
    L.append("| **Total** | | |")

    L += ["", "## Vencedor", ""]
    if len(provs) > 1:
        speed = {p: s[p].get("processing_seconds") or s[p].get("server_processing_seconds") for p in provs}
        speed = {p: v for p, v in speed.items() if v}
        if speed:
            fastest = min(speed, key=speed.get)
            L.append(f"- Mais rápido: **{fastest}** ({', '.join(f'{p}: {v}s' for p, v in speed.items())})")
        L.append(f"- Custo direto: own ≈ {s.get('own', {}).get('claude_cost_usd')} USD de Claude; "
                 f"opusclip = {s.get('opusclip', {}).get('credits_used')} {s.get('opusclip', {}).get('credits_unit') or 'créditos'}"
                 f" + {s.get('opusclip', {}).get('claude_cost_usd')} USD de Claude a operar o MCP")
        if cmp["shared_moments"]:
            L.append(f"- Concordância: {len(cmp['shared_moments'])} momento(s) escolhido(s) pelos dois")
        L += ["- **Vencedor em qualidade:** decide-se pela tabela de avaliação manual (maior total).",
              "- **Vencedor final:** ______  (preenche depois de ver os Shorts)"]
    else:
        L.append(f"Só correu um provider ({provs[0] if provs else '—'}). Usa `--provider compare` para comparar.")

    c = costs
    L += ["", "## Custos e tempos", "",
          f"- Execuções deste VOD: {c.get('runs', 1)} (valores cumulativos)",
          f"- Tempo total: {c['total_seconds']}s",
          f"- Etapas (s): {json.dumps(c['stages_seconds'], ensure_ascii=False)}",
          f"- Minutos transcritos (local, grátis): {c['transcribed_minutes']}",
          f"- Claude: {c['claude']['input_tokens']} tokens in / {c['claude']['output_tokens']} out "
          f"≈ {c['claude']['cost_usd']} USD (no backend claude_code com subscrição é custo equivalente, não cobrado)",
          f"- Chamadas externas: {json.dumps(c['external_calls'], ensure_ascii=False)}"]
    if c.get("opusclip"):
        L.append(f"- OpusClip: {json.dumps(c['opusclip'], ensure_ascii=False)}")
    return "\n".join(L) + "\n"
