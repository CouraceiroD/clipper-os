# Clipper OS

Dás uma live ou VOD → recebes 3 Shorts verticais finalizados (9:16, hook, legendas, áudio normalizado).
Tudo corre no teu PC com o Claude Code que já tens. Sem serviços pagos adicionais, sem uploads.

```
URL ─► yt-dlp ─► faster-whisper (local) ─► Claude escolhe os momentos mais virais ─► FFmpeg
        └─► outputs/<vod-id>/clip-01.mp4 · clip-02.mp4 · clip-03.mp4 · report.md
```

## Como usar

Abre o Claude Code na pasta do projeto e escreve:

> Clip this live: https://www.twitch.tv/videos/1234567890. Find the moments with the highest viral potential and create the finished Shorts.

O Claude reconhece o pedido (skill `clip`), corre o pipeline e no fim mostra os 3 Shorts e porque foi
escolhido cada momento. Também funciona com "make the best 3 shorts from this stream", "find the most viral
moments", "clip the best moments from <streamer>" ou "faz clips desta live".

Ou diretamente no terminal:

```powershell
.\.venv\Scripts\python.exe -m clipper auto "URL_DA_LIVE"
```

Opções: `--clips 5`, `--lang pt-PT`, `--layout split` (facecam em cima + jogo em baixo), `--reanalyze`.

Títulos, hooks, descrições, hashtags, thumbnails e resumos saem em inglês (`analyze.metadata_language: en`).
As legendas mantêm as palavras faladas; fala noutra língua só é traduzida para inglês com
`transcribe.translate_captions: true`. Mudar o idioma de um VOD já analisado traduz só os textos (mesmos
momentos) e guarda a versão anterior em `outputs/<vod-id>/<idioma>/`.

## O que o sistema faz

- Escolhe os 3 momentos com mais potencial viral: emoção, surpresa, conflito, humor, reações fortes,
  jogadas impressionantes, frases inesperadas e momentos que funcionam isolados.
- Evita intros, momentos sem contexto, silêncios e clips repetidos (histórico em `data/clipper.db`).
- Lives longas são analisadas por partes. Download, transcrição e análise ficam em cache.
- `report.md` explica porque cada momento foi escolhido, com hook, link para o momento na fonte, título,
  descrição, hashtags, texto para thumbnail e os momentos rejeitados.

## Instalação no Windows 11 (uma vez)

PowerShell, uma linha de cada vez (fecha e reabre o PowerShell no fim):

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Gyan.FFmpeg
winget install -e --id Git.Git
winget install -e --id DenoLand.Deno
irm https://claude.ai/install.ps1 | iex
```

Projeto:

```powershell
git clone https://github.com/CouraceiroD/clipper-os.git
cd clipper-os
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml
.\.venv\Scripts\python.exe -m clipper doctor
```

GPU NVIDIA (opcional, transcrição muito mais rápida):

```powershell
.\.venv\Scripts\python.exe -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
```

Depois ajusta `transcribe` no `config.yaml` pela tabela de VRAM em `CLAUDE.md`.
Se a GPU falhar, o sistema usa CPU automaticamente.

## Testes (sem rede, sem custos)

```powershell
.\.venv\Scripts\python.exe tests/test_windows_compat.py
.\.venv\Scripts\python.exe tests/smoke_test.py
.\.venv\Scripts\python.exe tests/test_auto_flow.py
.\.venv\Scripts\python.exe tests/test_compare_flow.py
```

## Opcional: comparar com o OpusClip

Não é necessário para o fluxo normal. Só se quiseres comparar resultados (gasta créditos OpusClip e pede
confirmação): ver `docs/OPUSCLIP_VALIDATION.md` e `python -m clipper run "<URL>" --provider compare`.

Estado do projeto: [ROADMAP.md](ROADMAP.md).
