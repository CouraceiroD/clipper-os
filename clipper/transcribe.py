"""Transcrição local e gratuita com faster-whisper (timestamps por palavra).

GPU NVIDIA: precisa de cuBLAS 12 + cuDNN 9. No Windows, os pacotes pip `nvidia-cublas-cu12` e
`nvidia-cudnn-cu12` instalam as DLLs em site-packages/nvidia/*/bin, que acrescentamos ao caminho de DLLs.
Se a GPU falhar (DLL em falta, sem VRAM...), cai automaticamente para CPU (int8) e avisa.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_CUDA_HINTS = ("cuda", "cudnn", "cublas", "dll", "libcu", "out of memory", "gpu")


def _add_nvidia_dll_dirs() -> None:
    if os.name != "nt":
        return
    for base in map(Path, sys.path):
        nv = base / "nvidia"
        if not nv.is_dir():
            continue
        for bin_dir in nv.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except (OSError, AttributeError):
                pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def _run(video_path: str, model_name: str, device: str, compute_type: str, language) -> dict:
    from faster_whisper import WhisperModel

    print(f"[transcribe] modelo={model_name} device={device} compute_type={compute_type} (pode demorar)")
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        video_path,
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    t0 = time.time()
    out = {"language": info.language, "duration": info.duration, "segments": [],
           "whisper": {"model": model_name, "device": device, "compute_type": compute_type}}
    for seg in segments:  # o gerador é preguiçoso: erros de GPU podem surgir aqui
        out["segments"].append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "words": [{"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()}
                      for w in (seg.words or [])],
        })
        if len(out["segments"]) % 50 == 0:
            pct = 100 * seg.end / max(info.duration, 1)
            print(f"[transcribe] {pct:5.1f}%  ({time.time() - t0:.0f}s)")
    return out


def transcribe(video_path: str, out_path: Path, cfg: dict) -> dict:
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))

    t = cfg["transcribe"]
    if t["device"] in ("auto", "cuda"):
        _add_nvidia_dll_dirs()
    try:
        out = _run(video_path, t["model"], t["device"], t["compute_type"], t["language"])
    except (RuntimeError, OSError, ValueError) as e:
        if t["device"] == "cpu" or not any(h in str(e).lower() for h in _CUDA_HINTS):
            raise
        print(f"[transcribe] ⚠ GPU falhou ({str(e)[:160]}). A repetir em CPU (int8)...")
        out = _run(video_path, t["model"], "cpu", "int8", t["language"])
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def all_words(transcript: dict) -> list[dict]:
    return [w for s in transcript["segments"] for w in s["words"] if w["word"]]
