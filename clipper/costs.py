"""Registo de custos e tempos de uma execução (um VOD). Gravado em outputs/<vod>/costs.json."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

# USD por milhão de tokens (input, output). Atualizar se os preços mudarem.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


class CostTracker:
    def __init__(self):
        self.t0 = time.time()
        self.stages: dict[str, float] = {}
        self.transcribed_minutes = 0.0
        self.claude_calls: list[dict] = []
        self.external_calls: dict[str, int] = {}
        self.opusclip: dict = {}
        self.prev_seconds = 0.0
        self.runs = 1

    def resume(self, path: Path) -> None:
        """Acumula os custos de execuções anteriores do mesmo VOD (re-execuções em cache não apagam o histórico)."""
        if not path.exists():
            return
        prev = json.loads(path.read_text(encoding="utf-8"))
        self.prev_seconds = prev.get("total_seconds", 0)
        self.runs = prev.get("runs", 1) + 1
        for k, v in prev.get("stages_seconds", {}).items():
            self.stages[k] = round(self.stages.get(k, 0) + v, 1)
        self.transcribed_minutes += prev.get("transcribed_minutes", 0)
        self.claude_calls = prev.get("claude", {}).get("calls", []) + self.claude_calls
        for k, v in prev.get("external_calls", {}).items():
            self.external_calls[k] = self.external_calls.get(k, 0) + v
        self.opusclip = {**prev.get("opusclip", {}), **self.opusclip}

    @contextmanager
    def stage(self, name: str):
        t = time.time()
        try:
            yield
        finally:
            self.stages[name] = round(self.stages.get(name, 0) + time.time() - t, 1)

    def call(self, service: str, n: int = 1) -> None:
        self.external_calls[service] = self.external_calls.get(service, 0) + n

    def claude(self, purpose: str, model: str, input_tokens: int = 0, output_tokens: int = 0,
               cache_read: int = 0, cost_usd: float | None = None, backend: str = "api") -> None:
        if cost_usd is None and model in PRICES:
            pin, pout = PRICES[model]
            cost_usd = (input_tokens * pin + cache_read * pin * 0.1 + output_tokens * pout) / 1e6
        self.claude_calls.append({
            "purpose": purpose, "backend": backend, "model": model,
            "input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_tokens": cache_read,
            # backend claude_code: é o custo equivalente reportado pelo CLI; com subscrição não é cobrado à parte
            "cost_usd": round(cost_usd or 0.0, 4),
        })
        self.call(f"claude_{backend}")

    def claude_cost(self, purpose_prefix: str = "") -> float:
        return round(sum(c["cost_usd"] for c in self.claude_calls if c["purpose"].startswith(purpose_prefix)), 4)

    def to_dict(self) -> dict:
        return {
            "runs": self.runs,
            "total_seconds": round(self.prev_seconds + time.time() - self.t0, 1),
            "stages_seconds": self.stages,
            "transcribed_minutes": round(self.transcribed_minutes, 1),
            "claude": {
                "calls": self.claude_calls,
                "input_tokens": sum(c["input_tokens"] for c in self.claude_calls),
                "output_tokens": sum(c["output_tokens"] for c in self.claude_calls),
                "cost_usd": self.claude_cost(),
            },
            "external_calls": self.external_calls,
            "opusclip": self.opusclip,
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
