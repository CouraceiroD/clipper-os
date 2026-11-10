# Clipper OS — instruções para o Claude Code

Sistema de clipping automático: VOD/vídeo longo → Shorts/Reels/TikToks 9:16 editados.
O utilizador fala português de Portugal. Responde em pt-PT.

## Como correr
- Ambiente: `.venv` na raiz. Ativar: `source .venv/bin/activate` (Windows: `.venv\Scripts\activate`).
- Pipeline completo: `python -m clipper run "<url ou ficheiro>"`
  - `--dry-run` só analisa e lista os momentos (barato, sem render)
  - `--max-clips N`, `--layout blur|crop|split`, `--reanalyze`
- Re-render depois de editar `data/sources/<pasta>/highlights.json`: `python -m clipper render <pasta>`
- Histórico: `python -m clipper history`
- Teste sem rede/API: `python tests/smoke_test.py`

## Estrutura
- `clipper/download.py` yt-dlp / ficheiro local → `data/sources/<id>/source.json`
- `clipper/transcribe.py` faster-whisper → `transcript.json` (cache)
- `clipper/analyze.py` prompt + JSON schema; backend `api` ou `claude_code` → `analysis_raw.json`, `highlights.json`
- `clipper/render.py` FFmpeg numa passagem: cortes, silêncios, layout, legendas ASS, loudnorm
- `clipper/db.py` SQLite `data/clipper.db` (fontes, clips, estado)
- `config.yaml` (cópia de `config.example.yaml`) — nunca commitar
- `ROADMAP.md` — manter sempre atualizado (✅ 🔨 ⏳) quando uma tarefa muda de estado

## Regras
- Nunca publicar vídeos como públicos sem pedido explícito; uploads começam `private`.
- Respeitar copyright: só clipar canais com autorização; dar sempre crédito ao criador na descrição.
- Preferir ferramentas gratuitas/locais; avisar antes de adicionar algo pago.
- Ao alterar `render.py` ou `analyze.py`, correr `python tests/smoke_test.py` antes de commitar.
- Não commitar `data/`, `config.yaml`, `.env` nem chaves.

## Rever resultados
Depois de um `run`, ler `data/sources/<pasta>/report.md`. Para ajustar um clip, editar `start`/`end`/`hook_text`
no `highlights.json` e correr `render`.
