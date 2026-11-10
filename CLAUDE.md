# Clipper OS — instruções para o Claude Code

Transforma lives e VODs em Shorts verticais finalizados, localmente. O utilizador fala português de Portugal
(responde em pt-PT) e usa Windows 11.

## Fluxo principal (o que o utilizador vai pedir)

Quando o utilizador pedir clips/Shorts de uma live, stream, VOD ou vídeo — por exemplo
"clip this live: <URL>", "make the best 3 shorts from this stream", "find the most viral moments",
"clip the best moments from X", "make shorts from this VOD", "faz clips desta live" —
**usa a skill `clip` (`.claude/skills/clip/SKILL.md`)**. Resumo:

```
<python do .venv> -m clipper auto "<URL>"        # em background; demora 10 min a 1 h+
```

- Python do venv: Windows `.venv/Scripts/python.exe`, Linux/macOS `.venv/bin/python`.
- Opções só se pedidas: `--clips N`, `--lang pt-PT`, `--layout split|crop|blur`, `--reanalyze`.
- Texto público (título, hook, descrição, hashtags, thumbnail, texto no vídeo) no idioma de `output_language`
  (config.yaml, por defeito `en`), validado em código. Legendas com as palavras faladas (tradução para inglês
  só com `transcribe.translate_captions: true`).
- No fim lê `outputs/<vod-id>/report.md` e responde com os ficheiros, títulos, scores, hooks e porquê.
- Resultado: `outputs/<vod-id>/clip-01.mp4`, `clip-02.mp4`, `clip-03.mp4`, `report.md`.
- Tudo local: yt-dlp, faster-whisper, FFmpeg e o Claude Code do utilizador (`claude -p`). Sem serviços pagos extra.

## Regras

- Nunca publicar, agendar nem fazer upload de nada.
- OpusClip é **opcional** e só para comparação: nunca o usar sem o utilizador pedir explicitamente
  (`python -m clipper run "<url>" --provider compare`, gasta créditos e pede confirmação).
- Um VOD de cada vez. Não repetir análises (`--reanalyze`) nem processar VODs extra sem pedido.
- Respeitar copyright: só clipar criadores que o permitem; a descrição já dá crédito ao canal.
- Não commitar `data/`, `outputs/`, vídeos, `config.yaml`, `.env`, cookies, tokens ou credenciais.
- Não trabalhar em dashboard, Supabase, Vercel, uploads, TikTok/Instagram ou monitorização sem pedido.

## Outros comandos

- Diagnóstico: `python -m clipper doctor`
- Re-render manual (comando `run`): `python -m clipper render <vod-id>`
- Comparação opcional com OpusClip: `python -m clipper opusclip-tools`, `python -m clipper run "<url>" --provider compare`
- Testes (sem rede/API/créditos):
  `python tests/test_windows_compat.py`, `python tests/smoke_test.py`, `python tests/test_auto_flow.py`,
  `python tests/test_compare_flow.py`, `python tests/test_language.py`,
  `python tests/test_render_profile.py` — correr todos antes de commitar alterações em `clipper/`.

## Escolha do modelo Whisper (`transcribe` no config.yaml)

Verificar a GPU com `nvidia-smi`. Não escolher um modelo acima do que a VRAM aguenta.

| Hardware | model | device | compute_type |
|---|---|---|---|
| Sem GPU NVIDIA | small | cpu | int8 |
| NVIDIA < 4 GB VRAM | small | cuda | int8_float16 |
| NVIDIA 4–6 GB | medium | cuda | int8_float16 |
| NVIDIA 6–8 GB | large-v3-turbo | cuda | int8_float16 |
| NVIDIA ≥ 8 GB | large-v3-turbo | cuda | float16 |

CUDA precisa de `pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"`. Se a GPU falhar, o sistema cai
sozinho para CPU.

## Estrutura

- `clipper/auto.py` modo automático (fluxo principal) + `report.md`
- `clipper/analyze.py` prompt de seleção viral, schema, análise por partes em lives longas, seleção
- `clipper/render.py` FFmpeg: cortes, silêncios, 9:16 (blur/crop/split), hook, legendas, loudness (ganho constante
  + limitador) e perfil de exportação para YouTube Shorts (H.264 CFR 30, AAC-LC 48 kHz estéreo 192k)
- `clipper/transcribe.py` faster-whisper com fallback CPU; `clipper/download.py` yt-dlp
- `clipper/claude_cli.py` `claude -p --json-schema` (compatível com claude.exe/claude.cmd)
- `clipper/cli.py` comandos; `clipper/db.py` histórico SQLite (evita clips repetidos)
- Opcional (comparação): `clipper/engines/`, `clipper/compare.py`, `clipper/costs.py`, `docs/OPUSCLIP_VALIDATION.md`
