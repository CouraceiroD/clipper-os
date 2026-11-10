"""Teste de fumo sem rede nem API: gera um vídeo sintético, uma transcrição falsa e uma
análise simulada, e corre select() + render nos 3 layouts.

    python tests/smoke_test.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipper import analyze as an  # noqa: E402
from clipper.config import DEFAULTS, _merge  # noqa: E402
from clipper.db import DB  # noqa: E402
from clipper.render import render_clip  # noqa: E402
from clipper.transcribe import all_words  # noqa: E402


def make_video(path: Path, seconds: int = 60) -> None:
    # 16:9 com "facecam" (canto sup. esq.) e som com 4s de silêncio entre 20s e 24s
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"color=c=red:size=480x270:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-filter_complex", "[0:v][1:v]overlay=0:0[v];[2:a]volume='if(between(t,20,24),0,1)':eval=frame[a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        str(path)], check=True)


def fake_transcript(seconds: int = 60) -> dict:
    segs, t = [], 0.0
    vocab = "isto foi completamente inacreditável mano olha para isto agora sim".split()
    while t < seconds - 1:
        if 20 <= t < 24:          # silêncio
            t = 24.0
            continue
        words = []
        for i in range(6):
            words.append({"start": round(t, 2), "end": round(t + 0.35, 2), "word": vocab[(int(t * 3) + i) % len(vocab)]})
            t += 0.42
        segs.append({"start": words[0]["start"], "end": words[-1]["end"],
                     "text": " ".join(w["word"] for w in words), "words": words})
        t += 0.3
    return {"language": "pt", "duration": seconds, "segments": segs}


def fake_clip(start, end, score, title):
    return {"start": start, "end": end, "title": title, "hook_text": "Ele não esperava isto",
            "summary": "s", "why_viral": "w", "category": "funny", "hook_score": 8,
            "emotion_score": 8, "payoff_score": 8, "standalone_score": 8, "viral_score": score,
            "cut_silences": True, "description": "d", "hashtags": ["gaming", "clips"],
            "thumbnail_text": "NÃO ACREDITO"}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="clipper_smoke_"))
    video = tmp / "src.mp4"
    make_video(video)
    tr = fake_transcript()
    cfg = _merge(DEFAULTS, {"workdir": str(tmp), "render": {"font": "Inter"}})
    db = DB(str(tmp))

    raw = {"video_summary": "x", "clips": [
        fake_clip(10, 40, 88, "Bom"),
        fake_clip(15, 35, 80, "Sobreposto"),      # deve ser rejeitado (sobreposição)
        fake_clip(41, 58, 40, "Fraco"),           # deve ser rejeitado (score)
    ]}
    chosen = an.select(raw, tr, cfg, db, "local:test")
    assert [c["title"] for c in chosen] == ["Bom"], chosen

    words = all_words(tr)
    for layout in ["blur", "crop", "split"]:
        rc = dict(cfg["render"], layout=layout)
        out = render_clip(str(video), chosen[0], words, tmp / layout, rc)
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout)
        size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=width,height", "-of", "csv=p=0:s=x", str(out)],
                              capture_output=True, text=True).stdout.strip()
        assert size == "1080x1920", size
        orig = chosen[0]["end"] - chosen[0]["start"]
        assert dur < orig - 1.0, f"silêncio não foi cortado: {dur} vs {orig}"
        print(f"OK {layout}: {size} {dur:.1f}s")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(out),
                        "-frames:v", "1", str(tmp / f"frame_{layout}.jpg")], check=True)

    db.add_clip("local:test", chosen[0], "x")
    assert db.overlaps_existing("local:test", 12, 38)
    print(json.dumps({"tmp": str(tmp)}))
    if "--keep" not in sys.argv:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
