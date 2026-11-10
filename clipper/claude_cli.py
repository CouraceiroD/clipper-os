"""Chamar o Claude Code em modo headless (`claude -p`) e obter saída estruturada.

Usa a autenticação do teu Claude Code (subscrição ou API key) e os MCP servers configurados
no Claude Code (ex.: opusclip). Nenhum segredo passa por este projeto.
"""
from __future__ import annotations

import json
import shutil
import subprocess


class ClaudeCLIError(RuntimeError):
    pass


def run(prompt: str, schema: dict, *, model: str, system: str | None = None,
        allowed_tools: list[str] | None = None, disallowed_tools: list[str] | None = None,
        cwd: str | None = None, timeout: int = 1800) -> tuple[dict, dict]:
    """Devolve (structured_output, info) onde info tem usage/custo/turnos."""
    if not shutil.which("claude"):
        raise ClaudeCLIError("Comando `claude` não encontrado no PATH. Instala o Claude Code.")
    cmd = ["claude", "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
           "--model", model]
    if system:
        cmd += ["--append-system-prompt", system]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]
    if disallowed_tools:
        cmd += ["--disallowedTools", ",".join(disallowed_tools)]
    try:
        res = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                             cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise ClaudeCLIError(f"claude -p excedeu {timeout}s") from e
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
        text = data.get("result", "")
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
