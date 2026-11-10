"""Carrega config.yaml com valores por defeito."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "workdir": "./data",           # cache: downloads, transcrições, histórico SQLite
    "output_dir": "./outputs",     # resultados por VOD: own/, opusclip/, comparison.json, report.md
    "clipping": {
        "provider": "own",         # own | opusclip | compare
        "max_candidates": 5,
        "max_renders": 3,
        "max_vod_minutes": 240,    # proteção de custos: recusa VODs maiores sem --force
    },
    "opusclip": {
        "operator_model": "claude-opus-5-5",  # modelo do `claude -p` que opera o MCP
        "poll_seconds": 120,
        "max_wait_minutes": 90,
    },
    "download": {"max_height": 1080},
    "transcribe": {
        "model": "small",          # tiny | base | small | medium | large-v3
        "device": "auto",          # auto | cpu | cuda
        "compute_type": "default", # default | int8 | float16
        "language": None,          # None = auto
    },
    "analyze": {
        "backend": "api",          # api | claude_code
        "model": "claude-opus-5-5",
        "effort": "medium",
        "max_clips": 8,
        "min_score": 65,
        "min_duration": 20,
        "max_duration": 75,
        "metadata_language": "pt-PT",
        "channel_context": "",
    },
    "render": {
        "layout": "blur",          # blur | crop | split
        "crop_x": 0.5,
        "split": {
            "facecam": [0.0, 0.0, 0.25, 0.25],   # x, y, w, h (fração do vídeo original)
            "gameplay": [0.125, 0.0, 0.75, 1.0],
            "facecam_height": 640,
        },
        "silence_gap": 1.0,        # pausas maiores que isto (s) são cortadas; 0 desliga
        "captions": True,
        "words_per_caption": 3,
        "font": "Arial",
        "font_size": 82,
        "highlight_color": "&H0000FFFF",  # ASS &HAABBGGRR -> amarelo
        "hook_seconds": 3.0,
        "crf": 20,
        "preset": "veryfast",
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None = None) -> dict:
    candidates = [path] if path else ["config.yaml"]
    user = {}
    for c in candidates:
        if c and Path(c).exists():
            user = yaml.safe_load(Path(c).read_text(encoding="utf-8")) or {}
            break
    cfg = _merge(DEFAULTS, user)
    for k in ("workdir", "output_dir"):
        cfg[k] = str(Path(cfg[k]).expanduser().resolve())
        Path(cfg[k]).mkdir(parents=True, exist_ok=True)
    return cfg
