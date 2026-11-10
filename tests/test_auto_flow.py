"""Teste end-to-end do modo `auto` SEM rede, SEM API e SEM créditos:
vídeo sintético + transcrição em cache + `claude` falso no PATH.

    python tests/test_auto_flow.py
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
from test_compare_flow import FAKE_CLAUDE  # noqa: E402


def main():
    tmp = Path(tempfile.mkdtemp(prefix="clipper_auto_"))
    video = tmp / "vod.mp4"
    make_video(video)
    bindir = tmp / "bin"
    bindir.mkdir()
    fc = bindir / "claude"
    fc.write_text(FAKE_CLAUDE, encoding="utf-8")
    fc.chmod(fc.stat().st_mode | stat.S_IEXEC)
    if os.name == "nt":
        (bindir / "claude.cmd").write_text(f'@"{sys.executable}" "%~dp0claude" %*\n')
    log = tmp / "claude_calls.jsonl"
    analysis = {"video_summary": "Live de teste.", "clips": [
        fake_clip(15, 30, 88, "Reação épica"),
        fake_clip(31, 45, 75, "Discussão com o chat"),
        fake_clip(2, 14, 55, "Momento médio"),        # abaixo de 65: só entra para completar 3
        fake_clip(46, 58, 30, "Intro aborrecida"),    # rejeitado (score < 50)
    ]}
    os.environ.update(PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", FAKE_CLAUDE_LOG=str(log),
                      FAKE_OPUS_MP4=str(video), FAKE_ANALYSIS=json.dumps(analysis),
                      CLAUDECODE="1")  # simula correr de dentro de uma sessão do Claude Code

    cfgp = tmp / "config.yaml"
    cfgp.write_text(f"""workdir: {(tmp / 'data').as_posix()}
output_dir: {(tmp / 'outputs').as_posix()}
analyze: {{min_duration: 10, max_duration: 40}}
render: {{font: Inter}}
""", encoding="utf-8")

    from clipper import analyze, cli
    from clipper import auto as auto_mod
    from clipper.config import load_config
    from clipper.download import source_dir

    url = "https://www.youtube.com/watch?v=AUTO123"
    meta = {"source_id": "youtube:AUTO123", "url": url, "title": "Live teste", "channel": "Streamer X",
            "duration": 60.0, "video_path": str(video)}
    auto_mod.probe_meta = lambda s: {k: v for k, v in meta.items() if k != "video_path"}
    auto_mod.fetch = lambda s, cfg: meta
    cfg = load_config(str(cfgp))
    (source_dir(cfg["workdir"], meta["source_id"]) / "transcript.json").write_text(
        json.dumps(fake_transcript()), encoding="utf-8")
    analyze.MAX_CHARS_PER_CALL = 300   # força a análise por partes (como numa live longa)

    cli.main(["--config", str(cfgp), "auto", url])

    out = tmp / "outputs" / "youtube_AUTO123"
    files = sorted(p.name for p in out.iterdir())
    assert files == ["clip-01.mp4", "clip-02.mp4", "clip-03.mp4", "report.md"], files
    for f in ("clip-01.mp4", "clip-02.mp4", "clip-03.mp4"):
        size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=width,height", "-of", "csv=p=0:s=x", str(out / f)],
                              capture_output=True, text=True).stdout.strip()
        assert size == "1080x1920", (f, size)
    rep = (out / "report.md").read_text(encoding="utf-8")
    assert rep.count("**Porque foi escolhido:**") == 3
    assert "Reação épica" in rep.split("### clip-01.mp4")[1].split("###")[0], "clip-01 deve ser o de score mais alto"
    assert "⚠ Abaixo do limiar" in rep and "Intro aborrecida" in rep.split("rejeitados")[1]
    assert "&t=15s" in rep or "&t=14s" in rep, "link para o momento na fonte"

    calls = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert len(calls) >= 2, "devia analisar por partes"
    assert all(c["claudecode"] is None for c in calls), "variáveis da sessão pai passaram para o claude -p"
    assert not any("mcp__opusclip" in " ".join(c["args"]) for c in calls), "auto não pode usar OpusClip"

    n = len(calls)
    cli.main(["--config", str(cfgp), "auto", url])      # 2.ª vez: tudo em cache, mesmos 3 clips
    assert len(log.read_text(encoding="utf-8").splitlines()) == n, "re-execução não devia chamar o Claude"
    assert sorted(p.name for p in out.iterdir()) == files

    print("OK auto flow:", out)
    if "--keep" not in sys.argv:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
