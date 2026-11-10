"""Pipeline A — próprio: transcrição (já feita) -> Claude -> FFmpeg."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .. import analyze as an
from ..render import render_clip
from ..transcribe import all_words


def transcript_between(transcript: dict, start: float, end: float) -> str:
    return " ".join(w["word"] for w in all_words(transcript)
                    if w["start"] >= start - 0.05 and w["end"] <= end + 0.05)


def run(meta: dict, transcript: dict, cfg: dict, db, tracker, out_dir: Path,
        reanalyze: bool = False, dry_run: bool = False) -> list[dict]:
    c = cfg["clipping"]
    cfg["analyze"]["max_clips"] = c["max_candidates"]
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path = out_dir / "analysis_raw.json"
    with tracker.stage("own.analyze"):
        if raw_path.exists() and not reanalyze:
            print("[own] a usar análise em cache (sem custo). --reanalyze para repetir.")
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            raw = an.analyze(transcript, meta, cfg, tracker)
            raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    db.reset_source(meta["source_id"])
    candidates = an.select(raw, transcript, cfg, db, meta["source_id"])
    print(f"[own] {len(candidates)} candidato(s) de {len(raw['clips'])} propostos")
    (out_dir / "highlights.json").write_text(json.dumps(candidates, indent=2, ensure_ascii=False),
                                             encoding="utf-8")
    if dry_run:
        for h in candidates:
            print(f"  {h['viral_score']:3d}  {h['start']:8.1f}-{h['end']:8.1f}  {h['title']}")
        return []
    return render_items(meta, transcript, candidates, cfg, db, tracker, out_dir)


def render_items(meta: dict, transcript: dict, candidates: list[dict], cfg: dict, db, tracker,
                 out_dir: Path) -> list[dict]:
    """Renderiza os primeiros max_renders candidatos. Usado também por `clipper render` após edição manual."""
    c = cfg["clipping"]
    analyze_cost = tracker.claude_cost("own.analyze")
    words = all_words(transcript)
    results = []
    for i, h in enumerate(candidates, 1):
        item = {
            "provider": "own",
            "rank": i,
            "start_time": h["start"],
            "end_time": h["end"],
            "duration": round(h["end"] - h["start"], 2),
            "title": h["title"],
            "hook": h["hook_text"],
            "reason_selected": h["why_viral"],
            "category": h["category"],
            "engagement_score": round(10 * (h["hook_score"] + h["emotion_score"] + h["payoff_score"]
                                            + h["standalone_score"]) / 4),
            "virality_score": h["viral_score"],
            "transcript": transcript_between(transcript, h["start"], h["end"]),
            "description": h["description"],
            "hashtags": h["hashtags"],
            "thumbnail_text": h["thumbnail_text"],
            "editing": (f"layout {cfg['render']['layout']}, legendas palavra a palavra (Whisper), hook no ecrã"
                        + (", corte de silêncios" if h.get("cut_silences", True) and cfg["render"]["silence_gap"] > 0
                           else "")),
            "rendered": False,
            "file": None,
            "final_duration": None,
            "render_time": None,
            "estimated_cost_usd": round(analyze_cost / max(len(candidates), 1), 4),
        }
        if i <= c["max_renders"]:
            work = out_dir / "_work" / f"clip-{i:02d}"
            t = time.time()
            with tracker.stage("own.render"):
                clip = render_clip(meta["video_path"], h, words, work, cfg["render"])
            final = out_dir / f"clip-{i:02d}.mp4"
            shutil.move(str(clip), final)
            item.update(rendered=True, file=str(final), render_time=round(time.time() - t, 1))
            db.add_clip(meta["source_id"], h, str(final))
        (out_dir / f"clip-{i:02d}.json").write_text(json.dumps(item, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
        results.append(item)
    return results
