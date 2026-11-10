"""CLI do Clipper OS.

  python -m clipper doctor                          verifica dependências e o MCP do OpusClip
  python -m clipper opusclip-tools                  lista as tools do MCP OpusClip (sem gastar créditos)
  python -m clipper run <url|ficheiro>              corre o provider do config (own | opusclip | compare)
        [--provider compare] [--yes] [--dry-run] [--reanalyze] [--force]
  python -m clipper render <vod-id>                 re-render (own) depois de editar outputs/<vod>/own/highlights.json
  python -m clipper history                         clips gerados
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .config import load_config
from .costs import CostTracker
from .db import DB
from .download import fetch, probe_meta, safe_id, source_dir


def _out_dir(cfg: dict, source_id: str) -> Path:
    d = Path(cfg["output_dir"]) / safe_id(source_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _confirm(msg: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        print(f"{msg}\n-> sem terminal interativo: usa --yes para confirmar.")
        return False
    return input(f"{msg} [s/N] ").strip().lower() in ("s", "sim", "y", "yes")


# ------------------------------------------------------------------ run
def cmd_run(args, cfg) -> None:
    c = cfg["clipping"]
    provider = args.provider or c["provider"]
    if args.max_candidates:
        c["max_candidates"] = args.max_candidates
    if args.max_renders:
        c["max_renders"] = args.max_renders
    if args.layout:
        cfg["render"]["layout"] = args.layout
    providers = ["own", "opusclip"] if provider == "compare" else [provider]

    tracker = CostTracker()
    db = DB(cfg["workdir"])

    with tracker.stage("probe"):
        meta = probe_meta(args.source)
    tracker.call("yt_dlp_metadata")
    minutes = (meta.get("duration") or 0) / 60
    print(f"VOD: {meta.get('title')} · {meta.get('channel')} · {minutes:.0f} min · providers={providers}")
    if meta.get("is_live"):
        sys.exit("Este vídeo ainda está em direto. Espera pelo VOD.")
    if minutes > c["max_vod_minutes"] and not args.force:
        sys.exit(f"VOD com {minutes:.0f} min > max_vod_minutes={c['max_vod_minutes']}. Usa --force se for mesmo isto.")

    out = _out_dir(cfg, meta["source_id"])
    tracker.resume(out / "costs.json")
    results: dict[str, list[dict]] = {}

    # 1) OpusClip primeiro: processa na nuvem enquanto o pipeline próprio corre localmente
    opus = None
    if "opusclip" in providers and not args.dry_run:
        from .engines.opusclip import OpusClipEngine
        opus = OpusClipEngine(cfg, tracker, out / "opusclip")
        if not opus.state.get("project_id"):
            if not _confirm(f"OpusClip vai processar ~{minutes:.0f} min de vídeo e consumir créditos. Continuar?",
                            args.yes):
                print("OpusClip ignorado.")
                opus = None
                providers.remove("opusclip")
        if opus:
            opus.submit(meta)

    # 2) Pipeline próprio
    transcript = None
    if "own" in providers:
        from .engines import own
        from .transcribe import transcribe

        with tracker.stage("download"):
            meta = fetch(args.source, cfg)
        tracker.call("yt_dlp_download")
        db.upsert_source(meta, "downloaded")
        tpath = source_dir(cfg["workdir"], meta["source_id"]) / "transcript.json"
        cached = tpath.exists()
        with tracker.stage("transcribe"):
            transcript = transcribe(meta["video_path"], tpath, cfg)
        if not cached:
            tracker.transcribed_minutes = transcript["duration"] / 60
        db.upsert_source(meta, "transcribed")
        results["own"] = own.run(meta, transcript, cfg, db, tracker, out / "own",
                                 reanalyze=args.reanalyze, dry_run=args.dry_run)
        if args.dry_run:
            tracker.save(out / "costs.json")
            print(f"\n(dry-run) candidatos em {out / 'own' / 'highlights.json'}")
            return
    else:
        db.upsert_source(meta, "submitted")

    # 3) OpusClip: esperar, obter e descarregar
    if opus:
        try:
            opus.wait()
            results["opusclip"] = opus.download(opus.fetch())
        except (TimeoutError, RuntimeError) as e:
            print(f"[opusclip] ⚠ {e}")
            tracker.opusclip["error"] = str(e)
        if transcript and results.get("opusclip"):  # transcrição comparável com a mesma fonte (Whisper)
            from .engines.own import transcript_between
            for item in results["opusclip"]:
                if not item.get("transcript") and item["start_time"] is not None and item["end_time"] is not None:
                    item["transcript"] = transcript_between(transcript, item["start_time"], item["end_time"])

    # 4) Relatório
    from . import compare
    tracker.save(out / "costs.json")
    compare.build(meta, results, tracker.to_dict(), out)
    db.upsert_source(meta, "done")
    print(f"\n✅ Feito. Relatório: {out / 'report.md'}\n   Dados: {out / 'comparison.json'}")


# ------------------------------------------------------------------ render (own)
def cmd_render(args, cfg) -> None:
    from .engines import own

    out = Path(cfg["output_dir"]) / args.vod_id
    hl = out / "own" / "highlights.json"
    if not hl.exists():
        sys.exit(f"Não encontrei {hl}")
    if args.layout:
        cfg["render"]["layout"] = args.layout
    src = next((Path(cfg["workdir"]) / "sources").glob(args.vod_id), None)
    if not src:
        sys.exit("Não encontrei o download/transcrição em data/sources/ para este VOD.")
    meta = json.loads((src / "source.json").read_text(encoding="utf-8"))
    transcript = json.loads((src / "transcript.json").read_text(encoding="utf-8"))
    db = DB(cfg["workdir"])
    db.reset_source(meta["source_id"])
    tracker = CostTracker()
    items = own.render_items(meta, transcript, json.loads(hl.read_text(encoding="utf-8")), cfg, db, tracker,
                             out / "own")
    print(f"✅ {sum(i['rendered'] for i in items)} clip(s) re-renderizados em {out / 'own'}")


# ------------------------------------------------------------------ doctor
def cmd_doctor(args, cfg) -> None:
    ok = True

    def check(name, cond, hint=""):
        nonlocal ok
        print(f"{'✅' if cond else '❌'} {name}" + ("" if cond else f"  -> {hint}"))
        ok &= bool(cond)

    check("ffmpeg", shutil.which("ffmpeg"), "instala o FFmpeg e põe-no no PATH")
    check("ffprobe", shutil.which("ffprobe"), "vem com o FFmpeg")
    for mod, hint in [("yt_dlp", "pip install -r requirements.txt"), ("faster_whisper", "pip install -r requirements.txt"),
                      ("anthropic", "pip install -r requirements.txt")]:
        try:
            __import__(mod)
            check(mod, True)
        except ImportError:
            check(mod, False, hint)
    if cfg["analyze"]["backend"] == "api":
        import os
        check("ANTHROPIC_API_KEY definida (backend api)", os.environ.get("ANTHROPIC_API_KEY"),
              "define a variável de ambiente ou usa analyze.backend: claude_code")
    has_claude = shutil.which("claude")
    check("Claude Code (claude)", has_claude, "instala o Claude Code")
    if has_claude:
        res = subprocess.run([has_claude, "mcp", "list"], capture_output=True, text=True, timeout=120)
        line = next((l for l in res.stdout.splitlines() if l.lower().startswith("opusclip")), "")
        check("MCP opusclip configurado", line,
              "claude mcp add --transport http opusclip https://mcp.opus.pro/mcp")
        if line:
            connected = "connected" in line.lower() and "not connected" not in line.lower()
            check(f"MCP opusclip ligado ({line.split(' - ')[-1].strip()})", connected,
                  "abre `claude` nesta pasta, escreve /mcp, escolhe opusclip e faz login (OAuth)")
    print("\nTudo pronto." if ok else "\nCorrige os ❌ acima.")


def cmd_opusclip_tools(args, cfg) -> None:
    from .engines.opusclip import OpusClipEngine
    tracker = CostTracker()
    res = OpusClipEngine(cfg, tracker, Path(cfg["output_dir"]) / "_opusclip").list_tools()
    Path("docs").mkdir(exist_ok=True)
    lines = ["# OpusClip MCP — tools disponíveis", "",
             f"Créditos restantes: {res['credits_remaining']} {res['credits_unit'] or ''}", "", res["notes"], "",
             "| Tool | Consome créditos | Descrição | Parâmetros |", "|---|---|---|---|"]
    for t in res["tools"]:
        lines.append(f"| `{t['name']}` | {'sim' if t['consumes_credits'] else 'não'} | {t['description']} | {t['parameters']} |")
    Path("docs/opusclip_tools.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nGuardado em docs/opusclip_tools.md · custo Claude ≈ {tracker.claude_cost()} USD")


def cmd_history(args, cfg) -> None:
    for r in DB(cfg["workdir"]).list_clips(args.limit):
        print(f"#{r['id']:<4} {r['viral_score']:>3}  {r['status']:<9} {r['title']}  ({r['source_title']})")


def main(argv=None) -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows: evita erros de encoding com emojis/acentos em pipes
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="clipper")
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="processa UM VOD (URL ou ficheiro)")
    r.add_argument("source")
    r.add_argument("--provider", choices=["own", "opusclip", "compare"])
    r.add_argument("--max-candidates", type=int)
    r.add_argument("--max-renders", type=int)
    r.add_argument("--layout", choices=["blur", "crop", "split"])
    r.add_argument("--dry-run", action="store_true", help="own: só analisa e lista candidatos; não usa OpusClip")
    r.add_argument("--reanalyze", action="store_true", help="ignora a análise Claude em cache")
    r.add_argument("--yes", action="store_true", help="confirma o consumo de créditos OpusClip")
    r.add_argument("--force", action="store_true", help="ignora o limite max_vod_minutes")
    r.set_defaults(fn=cmd_run)

    rr = sub.add_parser("render", help="re-render own a partir de outputs/<vod-id>/own/highlights.json")
    rr.add_argument("vod_id", help="pasta em outputs/, ex: youtube_abc123")
    rr.add_argument("--layout", choices=["blur", "crop", "split"])
    rr.set_defaults(fn=cmd_render)

    sub.add_parser("doctor", help="verifica dependências e MCP").set_defaults(fn=cmd_doctor)
    sub.add_parser("opusclip-tools", help="lista tools do MCP OpusClip").set_defaults(fn=cmd_opusclip_tools)

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
