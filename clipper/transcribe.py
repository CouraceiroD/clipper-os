"""Transcrição local e gratuita com faster-whisper (timestamps por palavra)."""
from __future__ import annotations

import json
import time
from pathlib import Path


def transcribe(video_path: str, out_path: Path, cfg: dict) -> dict:
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))

    from faster_whisper import WhisperModel

    t = cfg["transcribe"]
    print(f"[transcribe] modelo={t['model']} device={t['device']} (pode demorar)")
    model = WhisperModel(t["model"], device=t["device"], compute_type=t["compute_type"])
    segments, info = model.transcribe(
        video_path,
        language=t["language"],
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    t0 = time.time()
    out = {"language": info.language, "duration": info.duration, "segments": []}
    for seg in segments:
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
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def all_words(transcript: dict) -> list[dict]:
    return [w for s in transcript["segments"] for w in s["words"] if w["word"]]
