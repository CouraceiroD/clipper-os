"""CLI do Clipper OS.

  python -m clipper run <url|ficheiro>      pipeline completo
  python -m clipper render <source_id>      re-render a partir do highlights.json (depois de editares)
  python -m clipper history                 clips gerados
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import analyze as an
from .config import load_config
from .db import DB
from .download import fetch, source_dir
from .render import render_clip
from .transcribe import all_words, transcribe


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_-]+", "-", s)[:50] or "clip"


def _render_all(meta: dict, transcript: dict, highlights: list[dict], cfg: dict, db: DB) -> None:
    d = source_dir(cfg["workdir"], meta["source_id"])
    words = all_words(transcript)
    lines = [f"# {meta.get('title')}\n", f"Fonte: {meta.get('url')}  \nCanal: {meta.get('channel')}\n"]
    for i, h in enumerate(highlights, 1):
        out_dir = d / "clips" / f"{i:02d}_{_slug(h['title'])}"
        clip = render_clip(meta["video_path"], h, words, out_dir, cfg["render"])
        h["file"] = str(clip)
        (out_dir / "meta.json").write_text(json.dumps(h, indent=2, ensure_ascii=False), encoding="utf-8")
        db.add_clip(meta["source_id"], h, str(clip))
        lines += [
            f"\n## {i}. {h['title']}  — score {h['viral_score']}",
            f"- Ficheiro: `{clip}`",
            f"- Original: {h['start']:.1f}s → {h['end']:.1f}s · categoria `{h['category']}`",
            f"- Hook: **{h['hook_text']}** · Thumbnail: **{h['thumbnail_text']}**",
            f"- Porquê: {h['why_viral']}",
            f"- Descrição: {h['description']}",
            f"- Hashtags: {' '.join('#' + t.lstrip('#') for t in h['hashtags'])}",
        ]
    (d / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    db.upsert_source(meta, "rendered")
    print(f"\n✅ {len(highlights)} clip(s). Relatório: {d / 'report.md'}")


def cmd_run(args, cfg) -> None:
    db = DB(cfg["workdir"])
    if args.max_clips:
        cfg["analyze"]["max_clips"] = args.max_clips
    if args.layout:
        cfg["render"]["layout"] = args.layout

    print("[1/4] download")
    meta = fetch(args.source, cfg)
    db.upsert_source(meta, "downloaded")
    d = source_dir(cfg["workdir"], meta["source_id"])

    print("[2/4] transcrição")
    transcript = transcribe(meta["video_path"], d / "transcript.json", cfg)
    db.upsert_source(meta, "transcribed")

    print("[3/4] análise")
    raw_path = d / "analysis_raw.json"
    if raw_path.exists() and not args.reanalyze:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    else:
        raw = an.analyze(transcript, meta, cfg)
        raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    highlights = an.select(raw, transcript, cfg, db, meta["source_id"])
    (d / "highlights.json").write_text(json.dumps(highlights, indent=2, ensure_ascii=False), encoding="utf-8")
    db.upsert_source(meta, "analyzed")
    print(f"[analyze] {len(highlights)} clip(s) selecionado(s) de {len(raw['clips'])} candidatos")
    if args.dry_run:
        for h in highlights:
            print(f"  {h['viral_score']:3d}  {h['start']:8.1f}-{h['end']:8.1f}  {h['title']}")
        return

    print("[4/4] render")
    _render_all(meta, transcript, highlights, cfg, db)


def cmd_render(args, cfg) -> None:
    db = DB(cfg["workdir"])
    d = Path(cfg["workdir"]) / "sources" / args.source_dir
    meta = json.loads((d / "source.json").read_text(encoding="utf-8"))
    transcript = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    highlights = json.loads((d / "highlights.json").read_text(encoding="utf-8"))
    if args.layout:
        cfg["render"]["layout"] = args.layout
    _render_all(meta, transcript, highlights, cfg, db)


def cmd_history(args, cfg) -> None:
    for r in DB(cfg["workdir"]).list_clips(args.limit):
        print(f"#{r['id']:<4} {r['viral_score']:>3}  {r['status']:<9} {r['title']}  ({r['source_title']})")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="clipper")
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="pipeline completo para um URL ou ficheiro")
    r.add_argument("source")
    r.add_argument("--max-clips", type=int)
    r.add_argument("--layout", choices=["blur", "crop", "split"])
    r.add_argument("--dry-run", action="store_true", help="só analisa, não renderiza")
    r.add_argument("--reanalyze", action="store_true", help="ignora a análise em cache")
    r.set_defaults(fn=cmd_run)

    rr = sub.add_parser("render", help="re-render a partir de data/sources/<pasta>/highlights.json")
    rr.add_argument("source_dir", help="nome da pasta em data/sources/, ex: youtube_abc123")
    rr.add_argument("--layout", choices=["blur", "crop", "split"])
    rr.set_defaults(fn=cmd_render)

    h = sub.add_parser("history", help="lista clips gerados")
    h.add_argument("--limit", type=int, default=30)
    h.set_defaults(fn=cmd_history)

    args = p.parse_args(argv)
    cfg = load_config(args.config)
    try:
        args.fn(args, cfg)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
