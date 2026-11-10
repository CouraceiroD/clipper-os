"""Chamar o Claude Code em modo headless (`claude -p`) e obter saída estruturada.

Usa a autenticação do teu Claude Code (subscrição ou API key) e os MCP servers configurados
no Claude Code (ex.: opusclip). Nenhum segredo passa por este projeto.

Notas Windows:
- Se o Claude Code foi instalado via npm, o executável é `claude.cmd`. Argumentos de um .cmd passam pelo
  cmd.exe, que estraga quebras de linha e acentos. Por isso: o system prompt vai num ficheiro
  (`--append-system-prompt-file`), o prompt vai por stdin e o schema vai em JSON compacto só-ASCII.
  Quando possível chamamos diretamente `node cli.js`, sem passar pelo .cmd.
- Corremos sempre com cwd = raiz do projeto, para o Claude Code encontrar o MCP `opusclip` adicionado
  nesta pasta (scope local).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ClaudeCLIError(RuntimeError):
    pass


# Quando o Clipper é lançado de dentro de uma sessão do Claude Code, o `claude -p` filho deve arrancar
# como uma sessão nova e independente (mesma conta/autenticação), não como parte da sessão pai.
_SESSION_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_PID",
                 "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_AFTER_LAST_COMPACT",
                 "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN")


def _child_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _SESSION_VARS}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def resolve_claude() -> list[str] | None:
    """Comando base para invocar o Claude Code, ou None se não estiver instalado."""
    exe = shutil.which("claude")
    if not exe:
        return None
    if exe.lower().endswith((".cmd", ".bat")):
        cli_js = Path(exe).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
        node = shutil.which("node")
        if cli_js.exists() and node:
            return [node, str(cli_js)]
    return [exe]


def run_plain(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    """Corre `claude <args>` (ex.: mcp list) com UTF-8 e cwd na raiz do projeto."""
    base = resolve_claude()
    if not base:
        raise ClaudeCLIError("Comando `claude` não encontrado no PATH. Instala o Claude Code.")
    return subprocess.run(base + args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=PROJECT_ROOT, timeout=timeout, env=_child_env())


def mcp_status(name: str = "opusclip") -> tuple[str, str]:
    """('connected'|'needs_auth'|'failed'|'missing'|'no_claude', linha original)."""
    if not resolve_claude():
        return "no_claude", ""
    try:
        res = run_plain(["mcp", "list"])
    except subprocess.TimeoutExpired:
        return "failed", "timeout em `claude mcp list`"
    line = next((l.strip() for l in res.stdout.splitlines() if l.strip().lower().startswith(name + ":")), "")
    low = line.lower()
    if not line:
        return "missing", ""
    if "needs auth" in low or "authenticat" in low:
        return "needs_auth", line
    if "connected" in low and "not connected" not in low and "failed" not in low:
        return "connected", line
    return "failed", line


def run(prompt: str, schema: dict, *, model: str, system: str | None = None,
        allowed_tools: list[str] | None = None, disallowed_tools: list[str] | None = None,
        timeout: int = 1800) -> tuple[dict, dict]:
    """Devolve (structured_output, info) onde info tem usage/custo/turnos."""
    base = resolve_claude()
    if not base:
        raise ClaudeCLIError("Comando `claude` não encontrado no PATH. Instala o Claude Code.")
    cmd = base + ["-p", "--output-format", "json",
                  "--json-schema", json.dumps(schema, ensure_ascii=True, separators=(",", ":")),
                  "--model", model]
    sys_file = None
    if system:
        fd, sys_file = tempfile.mkstemp(prefix="clipper_sys_", suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(system)
        cmd += ["--append-system-prompt-file", sys_file]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]
    if disallowed_tools:
        cmd += ["--disallowedTools", ",".join(disallowed_tools)]
    try:
        res = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", cwd=PROJECT_ROOT, timeout=timeout, env=_child_env())
    except subprocess.TimeoutExpired as e:
        raise ClaudeCLIError(f"claude -p excedeu {timeout}s") from e
    finally:
        if sys_file:
            try:
                os.unlink(sys_file)
            except OSError:
                pass
    if res.returncode != 0:
        raise ClaudeCLIError(f"claude -p falhou (código {res.returncode}): {(res.stderr or res.stdout)[-2000:]}")
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise ClaudeCLIError(f"Saída inesperada do claude -p: {res.stdout[-1000:]}") from e
    if data.get("is_error"):
        raise ClaudeCLIError(f"claude -p devolveu erro: {data.get('result')}")

    out = data.get("structured_output")
    if not isinstance(out, dict):
        text = data.get("result", "") or ""
        try:
            out = json.loads(text[text.find("{"): text.rfind("}") + 1])
        except json.JSONDecodeError as e:
            raise ClaudeCLIError(f"Sem JSON na resposta: {text[-1000:]}") from e

    usage = data.get("usage") or {}
    info = {
        "input_tokens": int(usage.get("input_tokens", 0)) + int(usage.get("cache_creation_input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "cache_read": int(usage.get("cache_read_input_tokens", 0)),
        "cost_usd": data.get("total_cost_usd"),
        "num_turns": data.get("num_turns"),
    }
    return out, info
