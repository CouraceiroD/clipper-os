# Clipper OS

Transforma lives e vídeos longos em Shorts / Reels / TikToks verticais editados, com o Claude como "cérebro".

```
URL/VOD ─► yt-dlp ─► faster-whisper ─► Claude (momentos + viral score) ─► FFmpeg 9:16
                                                                     (silêncios, layout, legendas, hook)
                                                                          └─► clips + títulos/descrições/hashtags
```

## Instalação (no teu PC)

Requisitos: Python 3.10+, FFmpeg, Git. GPU NVIDIA é opcional (acelera muito a transcrição).

```bash
git clone <o-teu-repo> clipper-os && cd clipper-os
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
python tests/smoke_test.py       # deve terminar com "OK split"
```

Para a análise com a API: define `ANTHROPIC_API_KEY`. Em alternativa, põe `analyze.backend: claude_code`
para usar a tua subscrição do Claude Code (`claude -p`).

## Uso

```bash
python -m clipper run "https://www.youtube.com/watch?v=..." --dry-run   # só ver os momentos
python -m clipper run "https://www.youtube.com/watch?v=..."             # gerar os clips
python -m clipper run "https://www.twitch.tv/videos/..." --layout split
```

Resultados em `data/sources/<id>/clips/` + `report.md`.

Estado do projeto: ver [ROADMAP.md](ROADMAP.md).
