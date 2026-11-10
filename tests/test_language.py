"""Regressão: com output_language=en, nenhum texto público (hook, título, descrição, hashtags, thumbnail,
texto queimado no vídeo) pode sair em português. Sem rede, sem API, sem créditos.

    python tests/test_language.py
"""
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from smoke_test import fake_clip, fake_transcript, make_video  # noqa: E402
from test_compare_flow import FAKE_CLAUDE  # noqa: E402

# Textos reais gerados em pt-PT na primeira execução (live do Kai Cenat) e a versão inglesa que os substituiu.
PORTUGUESE = ["DISSERAM-LHE ISTO… EM PLENO DIRETO", "Disseram-lhe isto… em pleno direto", "NÃO TIREM PRINT",
              "FATO HORRÍVEL", "NÃO ENTRAS", "Ligou a pedir para entrar na festa",
              "Kai Cenat descobre em direto que andou toda a festa assim",
              "O Kai Cenat recusa a entrada de um convidado banido na festa de Halloween da AMP. Créditos: KaiCenat.",
              "kaicenat halloween streamer fail engraçado"]
ENGLISH = ["NOBODY TOLD HIM… UNTIL HE WAS LIVE", "Nobody told him… until he was live", "DON'T SCREENSHOT",
           "ZERO EFFORT", "YOU'RE NOT COMING", "He called begging to get in", '"You Wolverine?" Nah…',
           "Kai Cenat Finds Out LIVE He Had Swamp A** All Night 💀",
           "Kai Cenat shuts down a banned guest trying to sneak into the AMP Halloween party. Credit: KaiCenat.",
           "kaicenat amp halloween streamer drama"]


def unit_tests():
    from clipper import analyze as an
    from clipper.config import load_config

    for t in PORTUGUESE:
        assert an.portuguese_hits(t), f"português não detetado: {t!r}"
    for t in ENGLISH:
        assert not an.portuguese_hits(t), f"falso positivo em inglês: {t!r} -> {an.portuguese_hits(t)}"

    # o idioma vem só de output_language: nem locale/ambiente nem a chave antiga do config
    tmp = Path(tempfile.mkdtemp(prefix="clipper_lang_cfg_"))
    os.environ.update(LANG="pt_PT.UTF-8", LC_ALL="pt_PT.UTF-8", LANGUAGE="pt_PT")
    cfgp = tmp / "config.yaml"
    cfgp.write_text(f"workdir: {tmp.as_posix()}\noutput_dir: {tmp.as_posix()}\n"
                    "analyze: {metadata_language: pt-PT}\n", encoding="utf-8")
    cfg = load_config(str(cfgp))
    assert cfg["output_language"] == "en" and "metadata_language" not in cfg["analyze"], cfg["analyze"]

    rule = ("ALL PUBLIC-FACING OUTPUT MUST BE WRITTEN IN ENGLISH. NEVER GENERATE PORTUGUESE HOOKS, TITLES, "
            "DESCRIPTIONS, HASHTAGS, THUMBNAIL TEXT OR VIDEO OVERLAYS.")
    assert rule in an.system_prompt(cfg), "regra dura em falta no system prompt"
    assert "{language_rule}" not in an.system_prompt(cfg)

    bad = fake_clip(10, 30, 80, "Kai Cenat descobre em direto que andou toda a festa assim")
    bad["hook_text"] = "DISSERAM-LHE ISTO… EM PLENO DIRETO"
    assert set(an.language_problems(bad, cfg)) == {"hook_text", "title"}
    try:
        an.check_public_language(bad, cfg)
        raise AssertionError("check_public_language devia bloquear o render")
    except RuntimeError:
        pass
    assert an.language_problems(bad, dict(cfg, output_language="pt-PT")) == {}, "só se valida inglês"
    shutil.rmtree(tmp, ignore_errors=True)
    print("OK detetor, config e prompt")


def e2e_tests():
    tmp = Path(tempfile.mkdtemp(prefix="clipper_lang_"))
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

    # O Claude devolve um hook e um thumbnail em português apesar de output_language=en
    pt_clip = fake_clip(15, 30, 88, "Epic reaction")
    pt_clip.update(hook_text="DISSERAM-LHE ISTO… EM PLENO DIRETO", thumbnail_text="NÃO TIREM PRINT")
    analysis = {"video_summary": "Test stream.", "clips": [pt_clip, fake_clip(31, 45, 75, "Arguing with chat")]}
    os.environ.update(PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", FAKE_CLAUDE_LOG=str(log),
                      FAKE_OPUS_MP4=str(video), FAKE_ANALYSIS=json.dumps(analysis, ensure_ascii=False))
    os.environ.pop("FAKE_LOCALIZE_PT", None)

    cfgp = tmp / "config.yaml"
    cfgp.write_text(f"""workdir: {(tmp / 'data').as_posix()}
output_dir: {(tmp / 'outputs').as_posix()}
analyze: {{min_duration: 10, max_duration: 40}}
render: {{font: Inter}}
""", encoding="utf-8")

    from clipper import auto as auto_mod
    from clipper import cli
    from clipper.config import load_config
    from clipper.download import source_dir

    url = "https://www.youtube.com/watch?v=LANG123"
    meta = {"source_id": "youtube:LANG123", "url": url, "title": "Live", "channel": "Streamer X",
            "duration": 60.0, "video_path": str(video)}
    auto_mod.probe_meta = lambda s: {k: v for k, v in meta.items() if k != "video_path"}
    auto_mod.fetch = lambda s, cfg: meta
    cfg = load_config(str(cfgp))
    cache = source_dir(cfg["workdir"], meta["source_id"])
    (cache / "transcript.json").write_text(json.dumps(fake_transcript()), encoding="utf-8")
    out = tmp / "outputs" / "youtube_LANG123"

    def calls():
        return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    def assert_english_outputs():
        rep = (out / "report.md").read_text(encoding="utf-8")
        assert "DISSERAM" not in rep and "NÃO TIREM" not in rep, "texto português no report"
        for ass in (cache / "render").glob("clip-*/captions.ass"):
            overlay = ass.read_text(encoding="utf-8")
            assert "DISSERAM" not in overlay and "NÃO" not in overlay, f"texto português no vídeo: {ass}"
        assert "LOCALIZED HOOK" in (cache / "render" / "clip-01" / "captions.ass").read_text(encoding="utf-8")

    # 1) resposta nova do Claude com português -> rejeitada e regenerada em inglês antes do render
    cli.main(["--config", str(cfgp), "auto", url, "--clips", "1"])
    c = calls()
    assert len(c) == 2 and not c[0]["localize"] and c[1]["localize"], c
    assert "REJECTED PREVIOUS ATTEMPT" in c[1]["prompt"] or "Portuguese" in json.dumps(c[1]), c[1]
    assert_english_outputs()
    saved = json.loads((cache / "analysis.json").read_text(encoding="utf-8"))
    assert saved["output_language"] == "en" and saved["clips"][0]["hook_text"] == "Localized hook"
    print("OK resposta em português regenerada em inglês")

    # 2) cache antiga (sem etiqueta de idioma = pt-PT) com hook português -> não é reutilizada
    shutil.rmtree(out)
    legacy = {"video_summary": "Live de teste.", "clips": [pt_clip, fake_clip(31, 45, 75, "Arguing with chat")]}
    (cache / "analysis.json").write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    n = len(calls())
    cli.main(["--config", str(cfgp), "auto", url, "--clips", "1"])
    c = calls()[n:]
    assert len(c) == 1 and c[0]["localize"], "cache noutro idioma devia regenerar os textos, sem reanalisar"
    assert_english_outputs()
    assert (cache / "analysis.pt-PT.json").exists()
    print("OK cache em português invalidada")

    # 3) cache marcada "en" mas com português lá dentro -> também é apanhada
    shutil.rmtree(out)
    (cache / "analysis.json").write_text(json.dumps(dict(legacy, output_language="en"), ensure_ascii=False),
                                         encoding="utf-8")
    cli.main(["--config", str(cfgp), "auto", url, "--clips", "1"])
    assert_english_outputs()
    print("OK cache 'en' contaminada corrigida")

    # 4) o modelo insiste em português -> pára sem renderizar nada
    shutil.rmtree(out)
    (cache / "analysis.json").write_text(json.dumps(dict(legacy, output_language="en"), ensure_ascii=False),
                                         encoding="utf-8")
    shutil.rmtree(cache / "render", ignore_errors=True)
    os.environ["FAKE_LOCALIZE_PT"] = "1"
    n = len(calls())
    try:
        cli.main(["--config", str(cfgp), "auto", url, "--clips", "1"])
        raise AssertionError("devia falhar em vez de renderizar português")
    except RuntimeError as e:
        assert "português" in str(e), e
    finally:
        os.environ.pop("FAKE_LOCALIZE_PT", None)
    assert len(calls()) - n == 2, "devia tentar regenerar 2 vezes"
    assert not list(out.glob("clip-*.mp4")) if out.exists() else True, "não devia haver clips"
    assert not (cache / "render").exists(), "não devia ter renderizado nada"
    print("OK português persistente bloqueia o render")

    if "--keep" not in sys.argv:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unit_tests()
    e2e_tests()
