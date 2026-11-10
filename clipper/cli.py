"""CLI do Clipper OS.

  python -m clipper auto <url>                      live/VOD -> 3 Shorts finalizados (fluxo principal)
  python -m clipper doctor                          verifica dependências
  python -m clipper opusclip-tools                  lista as tools do MCP OpusClip (sem gastar créditos)
  python -m clipper run <url|ficheiro>              corre o provider do config (own | opusclip | compare)
        [--provider compare] [--yes] [--dry-run] [--reanalyze] [--force]
  python -m clipper render <vod-id>                 re-render (own) depois de editar outputs/<vod>/own/highlights.json
  python -m clipper history                         clips gerados
"""
from __future__ import annotations

import argparse
import json
import os
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


# ------------------------------------------------------------------ auto
def cmd_auto(args, cfg) -> None:
    from . import auto

    if args.layout:
        cfg["render"]["layout"] = args.layout
    if args.lang:
        cfg["output_language"] = args.lang
    auto.run(args.source, cfg, n_clips=args.clips, reanalyze=args.reanalyze, force=args.force)


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
        if not opus.state.get("fetch"):
            _require_opusclip()   # falha cedo, antes de confirmar créditos ou fazer download
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
    from . import analyze as an
    cands = json.loads(hl.read_text(encoding="utf-8"))   # editado à mão: valida o idioma antes de renderizar
    fixed = an.ensure_language({"video_summary": "", "clips": cands, "output_language": cfg["output_language"]},
                               transcript, meta, cfg)["clips"]
    if fixed != cands:
        hl.write_text(json.dumps(fixed, indent=2, ensure_ascii=False), encoding="utf-8")
    db = DB(cfg["workdir"])
    db.reset_source(meta["source_id"])
    tracker = CostTracker()
    items = own.render_items(meta, transcript, fixed, cfg, db, tracker, out / "own")
    print(f"✅ {sum(i['rendered'] for i in items)} clip(s) re-renderizados em {out / 'own'}")


# ------------------------------------------------------------------ doctor
MCP_HINTS = {
    "missing": "na pasta do projeto: claude mcp add --transport http opusclip https://mcp.opus.pro/mcp",
    "needs_auth": "abre `claude` na pasta do projeto, escreve /mcp, escolhe opusclip e faz login no browser",
    "failed": "verifica a internet/firewall; depois /mcp no Claude Code para voltar a ligar",
    "no_claude": "instala o Claude Code",
}


def cmd_doctor(args, cfg) -> None:
    from .claude_cli import mcp_status, resolve_claude

    ok = True

    def check(name, cond, hint="", required=True):
        nonlocal ok
        mark = "✅" if cond else ("❌" if required else "⚠️ ")
        print(f"{mark} {name}" + ("" if cond else f"  -> {hint}"))
        if required:
            ok &= bool(cond)

    print(f"Python {sys.version.split()[0]} · {sys.platform} · projeto em {Path(__file__).resolve().parents[1]}")
    check("Python >= 3.10", sys.version_info >= (3, 10), "instala Python 3.10+")
    check("ffmpeg", shutil.which("ffmpeg"), "Windows: winget install Gyan.FFmpeg (e reabre o terminal)")
    check("ffprobe", shutil.which("ffprobe"), "vem com o FFmpeg")
    for mod in ("yt_dlp", "faster_whisper", "anthropic", "yaml"):
        try:
            __import__(mod)
            check(mod, True)
        except ImportError:
            check(mod, False, "pip install -r requirements.txt")
    check("runtime JS para o yt-dlp (deno ou node)", shutil.which("deno") or shutil.which("node"),
          "o YouTube pode exigir um runtime JS: winget install DenoLand.Deno", required=False)

    t = cfg["transcribe"]
    gpu = shutil.which("nvidia-smi")
    if gpu:
        try:
            q = subprocess.run([gpu, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
            print(f"ℹ️  GPU: {q.stdout.strip() or 'nvidia-smi sem resposta'}")
        except (OSError, subprocess.TimeoutExpired):
            print("ℹ️  GPU: nvidia-smi falhou")
    else:
        print("ℹ️  GPU NVIDIA: não encontrada (Whisper em CPU)")
    print(f"ℹ️  Whisper: model={t['model']} device={t['device']} compute_type={t['compute_type']}")

    if cfg["analyze"]["backend"] == "api":
        check("ANTHROPIC_API_KEY definida (backend api)", os.environ.get("ANTHROPIC_API_KEY"),
              "define a variável de ambiente ou usa analyze.backend: claude_code")
    base = resolve_claude()
    check("Claude Code (claude)", base, MCP_HINTS["no_claude"])
    if base:
        print(f"ℹ️  claude: {' '.join(base)}")
        need_opus = cfg["clipping"]["provider"] != "own"
        status, line = mcp_status("opusclip")
        if status == "missing" and not need_opus:
            print("ℹ️  OpusClip (opcional, só para comparação): não configurado")
        else:
            check("MCP opusclip configurado (opcional)", status != "missing", MCP_HINTS["missing"],
                  required=need_opus)
            if status != "missing":
                check(f"MCP opusclip ligado ({line})", status == "connected", MCP_HINTS.get(status, ""),
                      required=need_opus)
    print("\nTudo pronto." if ok else "\nCorrige os ❌ acima.")
    if not ok:
        sys.exit(1)


def _require_opusclip() -> None:
    from .claude_cli import mcp_status

    status, line = mcp_status("opusclip")
    if status != "connected":
        sys.exit(f"MCP opusclip não está pronto ({status}: {line or '-'}).\n-> {MCP_HINTS.get(status, '')}")


def cmd_opusclip_tools(args, cfg) -> None:
    from .claude_cli import PROJECT_ROOT
    from .engines.opusclip import OpusClipEngine

    _require_opusclip()
    tracker = CostTracker()
    res = OpusClipEngine(cfg, tracker, Path(cfg["output_dir"]) / "_opusclip").list_tools()
    if not res["connected"] or not res["tools"]:
        sys.exit(f"O Claude não conseguiu usar as tools do OpusClip: {res['notes']}\n-> {MCP_HINTS['needs_auth']}")
    docs = PROJECT_ROOT / "docs"
    docs.mkdir(exist_ok=True)
    lines = ["# OpusClip MCP — tools disponíveis", "",
             f"Créditos restantes: {res['credits_remaining']} {res['credits_unit'] or ''}", "", res["notes"], "",
             "| Tool | Consome créditos | Descrição | Parâmetros |", "|---|---|---|---|"]
    for t in res["tools"]:
        lines.append(f"| `{t['name']}` | {'sim' if t['consumes_credits'] else 'não'} | {t['description']} | {t['parameters']} |")
    (docs / "opusclip_tools.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nGuardado em {docs / 'opusclip_tools.md'} · custo Claude ≈ {tracker.claude_cost()} USD")


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

    au = sub.add_parser("auto", help="live/VOD -> 3 Shorts finalizados (local, sem serviços pagos)")
    au.add_argument("source", help="URL da live/VOD (YouTube, Twitch, Kick...) ou ficheiro de vídeo")
    au.add_argument("--clips", type=int, default=3, help="número de Shorts (por defeito 3)")
    au.add_argument("--layout", choices=["blur", "crop", "split"])
    au.add_argument("--lang", help="substitui output_language nesta execução, ex: en, pt-PT")
    au.add_argument("--reanalyze", action="store_true", help="repete a análise do Claude (ignora cache)")
    au.add_argument("--force", action="store_true", help="ignora o limite max_vod_minutes")
    au.set_defaults(fn=cmd_auto)

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
