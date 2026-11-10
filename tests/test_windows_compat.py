"""Verificações de compatibilidade Windows que podem correr em qualquer SO (sem rede, sem API).

    python tests/test_windows_compat.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clipper import analyze, claude_cli  # noqa: E402
from clipper.engines import opusclip  # noqa: E402

CMD_SPECIAL = set('&|<>^%!"\n\r')


def test_schemas_safe_for_cmd_exe():
    """O schema vai na linha de comando. Via claude.cmd passa pelo cmd.exe: tem de ser ASCII,
    sem caracteres especiais do cmd (fora as aspas JSON, que o Python escapa) e curto (< 8191)."""
    for name, schema in [("analyze", analyze.SCHEMA), ("submit", opusclip.SUBMIT_SCHEMA),
                         ("status", opusclip.STATUS_SCHEMA), ("fetch", opusclip.FETCH_SCHEMA),
                         ("tools", opusclip.TOOLS_SCHEMA)]:
        arg = json.dumps(schema, ensure_ascii=True, separators=(",", ":"))
        assert arg.isascii(), name
        bad = (CMD_SPECIAL - {'"'}) & set(arg)
        assert not bad, f"{name}: {bad}"
        assert len(arg) < 4000, f"{name}: {len(arg)}"
    print("OK schemas seguros para cmd.exe")


def test_resolve_claude_cmd_prefers_node_cli():
    tmp = Path(tempfile.mkdtemp())
    try:
        cmd = tmp / "claude.cmd"
        cmd.write_text("@echo off\n")
        cli_js = tmp / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
        cli_js.parent.mkdir(parents=True)
        cli_js.write_text("")
        orig = shutil.which
        claude_cli.shutil.which = lambda name: str(cmd) if name == "claude" else ("/usr/bin/node" if name == "node" else None)
        try:
            assert claude_cli.resolve_claude() == ["/usr/bin/node", str(cli_js)]
            cli_js.unlink()  # sem cli.js -> usa o .cmd
            assert claude_cli.resolve_claude() == [str(cmd)]
            claude_cli.shutil.which = lambda name: "C:/x/claude.exe" if name == "claude" else None
            assert claude_cli.resolve_claude() == ["C:/x/claude.exe"]
            claude_cli.shutil.which = lambda name: None
            assert claude_cli.resolve_claude() is None
        finally:
            claude_cli.shutil.which = orig
    finally:
        shutil.rmtree(tmp)
    print("OK resolução do claude / claude.cmd / claude.exe")


def test_mcp_status_parsing():
    cases = {
        "opusclip: https://mcp.opus.pro/mcp (HTTP) - ✓ Connected": "connected",
        "opusclip: https://mcp.opus.pro/mcp (HTTP) - ! Needs authentication": "needs_auth",
        "opusclip: https://mcp.opus.pro/mcp (HTTP) - ✗ Failed to connect": "failed",
        "other: x - ✓ Connected": "missing",
    }
    orig_run, orig_resolve = claude_cli.run_plain, claude_cli.resolve_claude
    claude_cli.resolve_claude = lambda: ["claude"]
    try:
        for line, expected in cases.items():
            claude_cli.run_plain = lambda args, timeout=120, line=line: type("R", (), {"stdout": f"Checking...\n\n{line}\n"})()
            got = claude_cli.mcp_status("opusclip")[0]
            assert got == expected, (line, got)
    finally:
        claude_cli.run_plain, claude_cli.resolve_claude = orig_run, orig_resolve
    print("OK leitura do estado do MCP")


def test_file_uri_download():
    tmp = Path(tempfile.mkdtemp(prefix="clipper ç "))  # espaço + acento no caminho
    try:
        src = tmp / "origem vídeo.bin"
        src.write_bytes(b"x" * 1000)
        dest = tmp / "clip-01.mp4"
        opusclip._download(src.as_uri(), dest)
        assert dest.read_bytes() == src.read_bytes()
    finally:
        shutil.rmtree(tmp)
    print("OK download por URI com espaços/acentos")


if __name__ == "__main__":
    test_schemas_safe_for_cmd_exe()
    test_resolve_claude_cmd_prefers_node_cli()
    test_mcp_status_parsing()
    test_file_uri_download()
