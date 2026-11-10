"""Perfil de exportação para YouTube Shorts (sem rede/API): formato dos streams, timestamps a começar em 0 e
ganho de áudio constante desde o primeiro segundo (o loudnorm dinâmico fazia uma rampa de ~8 dB no arranque).

    python tests/test_render_profile.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipper.config import DEFAULTS, _merge  # noqa: E402
from clipper.render import render_clip  # noqa: E402


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def rms_db(x: np.ndarray) -> float:
    return 20 * np.log10(max(float(np.sqrt((x ** 2).mean())), 1e-9))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="clipper_profile_"))
    src = tmp / "loud.mp4"
    # fonte "quente": 3 s a 0 dBFS (tipo grito saturado) e depois 20 dB abaixo, como numa reação
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=60:duration=8",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=8:sample_rate=44100",
                    "-filter_complex", "[1:a]volume='if(lt(t,3),8,0.8)':eval=frame,aformat=channel_layouts=mono[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    str(src)], check=True)
    rcfg = _merge(DEFAULTS, {"render": {"font": "Inter"}})["render"]
    out = render_clip(str(src), {"start": 0.0, "end": 8.0, "hook_text": "TEST", "cut_silences": False}, [],
                      tmp / "r", rcfg, out_name="clip-01-youtube-safe.mp4")

    p = probe(out)
    v = next(s for s in p["streams"] if s["codec_type"] == "video")
    a = next(s for s in p["streams"] if s["codec_type"] == "audio")
    assert (v["codec_name"], v["profile"], v["pix_fmt"]) == ("h264", "High", "yuv420p"), v
    assert v["r_frame_rate"] == v["avg_frame_rate"] == "30/1", "CFR 30 fps"
    assert (a["codec_name"], a["profile"], a["sample_rate"], a["channels"], a["channel_layout"]) == \
        ("aac", "LC", "48000", 2, "stereo"), a
    assert 170_000 <= int(a["bit_rate"]) <= 200_000, a["bit_rate"]
    assert float(v["start_time"]) == 0 and float(a["start_time"]) == 0 and float(p["format"]["start_time"]) == 0, \
        (v["start_time"], a["start_time"], p["format"]["start_time"])
    assert abs(float(a["duration"]) - float(v["duration"])) < 0.1, (a["duration"], v["duration"])
    assert not p["format"].get("tags", {}).get("title"), "metadados da fonte não devem passar"

    keys = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=key_frame,pts_time",
                           "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout
    kts = [float(l.split(",")[1]) for l in keys.splitlines() if l.startswith("1,")]
    assert kts[0] == 0 and all(abs(b - a_ - 0.5) < 0.01 for a_, b in zip(kts, kts[1:])), kts[:6]

    ebu = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(out), "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    summ = ebu[ebu.rfind("Summary:"):]
    tp = float(summ.split("Peak:")[1].split("dBFS")[0])
    assert tp <= -1.0, f"true peak {tp} dBTP"

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-ac", "1", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    sr = 48000
    fade = rms_db(x[: int(0.05 * sr)])
    first, settled = rms_db(x[int(0.1 * sr): int(1.0 * sr)]), rms_db(x[int(1.5 * sr): int(2.9 * sr)])
    quiet = rms_db(x[int(4 * sr): int(7.5 * sr)])
    assert fade < first - 1, "fade-in de 50 ms em falta"
    assert abs(first - settled) < 1.0, f"ganho a variar no arranque: {first:.1f} vs {settled:.1f} dB"
    assert 17 < first - quiet < 23, f"dinâmica alterada: alto {first:.1f} / baixo {quiet:.1f} dB (devia ~20 dB)"
    print(f"OK perfil YouTube: h264/yuv420p 30fps GOP 0.5s, aac LC 48k stereo {int(a['bit_rate']) // 1000}k, "
          f"start 0, true peak {tp} dBTP, ganho constante ({first:.1f}/{settled:.1f} dB)")
    if "--keep" not in sys.argv:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
