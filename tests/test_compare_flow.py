"""Teste end-to-end do modo `compare` SEM rede, SEM API e SEM créditos:
- vídeo sintético + transcrição em cache (não corre o Whisper)
- um `claude` falso no PATH que imita o Claude (análise) e o MCP OpusClip (submit/status/fetch)

    python tests/test_compare_flow.py
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from smoke_test import fake_clip, fake_transcript, make_video  # noqa: E402

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
schema = json.loads(args[args.index("--json-schema") + 1])
props = schema.get("properties", {})
prompt = sys.stdin.read()
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as f:
    f.write(json.dumps({"args": args, "prompt": prompt[:200]}) + "\n")
mp4 = os.environ["FAKE_OPUS_MP4"]
if "video_summary" in props:
    out = json.loads(os.environ["FAKE_ANALYSIS"])
elif "project_id" in props:
    out = {"project_id": "proj_123", "credits_before": 900, "credits_unit": "credits", "plan": "Pro",
           "options_applied": "9:16, captions, reframe", "notes": "ok"}
elif "progress_percent" in props:
    out = {"status": "done", "progress_percent": 100, "notes": "ready"}
elif "total_clips_in_project" in props:
    def c(rank, s, e, exp):
        return {"rank": rank, "clip_id": f"c{rank}", "title": f"Opus clip {rank}", "start_time": s, "end_time": e,
                "duration": e - s, "virality_score": 99 - rank, "hook_score": 9, "coherence_score": 8,
                "connection_score": 7, "trend_score": None, "reason_selected": "strong hook", "hook": "wow",
                "transcript": None, "description": "d", "hashtags": ["x"], "exported": exp,
                "download_url": ("file://" + mp4) if exp else None, "preview_url": None}
    out = {"clips": [c(1, 12, 38, True), c(2, 40, 58, True), c(3, 1, 9, False)],
           "total_clips_in_project": 7, "credits_after": 870, "credits_unit": "credits", "notes": "ok"}
else:
    out = {"connected": True, "tools": [], "credits_remaining": 900, "credits_unit": "credits", "notes": ""}
print(json.dumps({"type": "result", "is_error": False, "result": "", "structured_output": out,
                  "usage": {"input_tokens": 1000, "output_tokens": 200}, "total_cost_usd": 0.01, "num_turns": 2}))
'''


def main():
    tmp = Path(tempfile.mkdtemp(prefix="clipper_cmp_"))
    video = tmp / "vod.mp4"
    make_video(video)
    opus_mp4 = tmp / "opus_sample.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=duration=3", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", str(opus_mp4)], check=True)

    bindir = tmp / "bin"
    bindir.mkdir()
    fc = bindir / "claude"
    fc.write_text(FAKE_CLAUDE)
    fc.chmod(fc.stat().st_mode | stat.S_IEXEC)
    log = tmp / "claude_calls.jsonl"
    analysis = {"video_summary": "x", "clips": [fake_clip(10, 40, 88, "Momento A"), fake_clip(41, 58, 75, "Momento B"),
                                                fake_clip(0, 9, 30, "Fraco")]}
    os.environ.update(PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", FAKE_CLAUDE_LOG=str(log),
                      FAKE_OPUS_MP4=str(opus_mp4), FAKE_ANALYSIS=json.dumps(analysis))

    cfgp = tmp / "config.yaml"
    cfgp.write_text(f"""workdir: {tmp / 'data'}
output_dir: {tmp / 'outputs'}
clipping: {{provider: compare, max_candidates: 5, max_renders: 3}}
opusclip: {{poll_seconds: 0, max_wait_minutes: 1}}
analyze: {{backend: claude_code, min_duration: 10, max_duration: 40}}
render: {{font: Inter}}
""")

    from clipper import cli
    from clipper.download import source_dir

    url = "https://www.youtube.com/watch?v=TEST123"
    meta = {"source_id": "youtube:TEST123", "url": url, "title": "VOD teste", "channel": "Canal X",
            "duration": 60.0, "video_path": str(video)}
    cli.probe_meta = lambda s: {k: v for k, v in meta.items() if k != "video_path"}
    cli.fetch = lambda s, cfg: meta
    from clipper.config import load_config
    cfg = load_config(str(cfgp))
    (source_dir(cfg["workdir"], meta["source_id"]) / "transcript.json").write_text(json.dumps(fake_transcript()))

    cli.main(["--config", str(cfgp), "run", url, "--yes"])

    out = tmp / "outputs" / "youtube_TEST123"
    cmp = json.loads((out / "comparison.json").read_text())
    own = [c for c in cmp["clips"] if c["provider"] == "own"]
    opus = [c for c in cmp["clips"] if c["provider"] == "opusclip"]
    assert len(own) == 2 and all(c["rendered"] for c in own), own        # "Fraco" filtrado por score
    assert (out / "own" / "clip-01.mp4").exists() and (out / "own" / "clip-02.mp4").exists()
    assert len(opus) == 3 and sum(c["rendered"] for c in opus) == 2
    assert (out / "opusclip" / "clip-01.mp4").exists() and not (out / "opusclip" / "clip-03.mp4").exists()
    assert opus[0]["transcript"], "transcrição do OpusClip devia vir do Whisper"
    required = ["start_time", "end_time", "duration", "hook", "title", "reason_selected", "engagement_score",
                "virality_score", "transcript", "provider", "render_time", "estimated_cost_usd"]
    for c in cmp["clips"]:
        missing = [k for k in required if k not in c]
        assert not missing, missing
    assert cmp["costs"]["opusclip"]["credits_used"] == 30
    assert cmp["shared_moments"] and cmp["shared_moments"][0]["own_rank"] == 1
    assert own[0]["media"]["height"] == 1920
    report = (out / "report.md").read_text()
    assert "Avaliação manual" in report and "Créditos OpusClip" in report

    calls = [json.loads(l) for l in log.read_text().splitlines()]
    opus_calls = [c for c in calls if "mcp__opusclip" in " ".join(c["args"])]
    assert len(opus_calls) == 3, len(opus_calls)                         # submit, status, fetch
    assert sum("proj_" not in c["prompt"] and "criar UM projeto" in c["prompt"] for c in opus_calls) == 1

    # Segunda execução: tudo em cache -> não volta a submeter nem a analisar
    n_before = len(calls)
    cli.main(["--config", str(cfgp), "run", url, "--yes"])
    calls2 = [json.loads(l) for l in log.read_text().splitlines()]
    assert len(calls2) == n_before, "re-execução não devia chamar o Claude/OpusClip outra vez"
    costs2 = json.loads((out / "costs.json").read_text())
    assert costs2["runs"] == 2 and costs2["claude"]["cost_usd"] > 0, "custos da 1.ª execução perdidos"
    assert costs2["opusclip"]["credits_used"] == 30

    print("OK compare flow:", out)
    if "--keep" not in sys.argv:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
