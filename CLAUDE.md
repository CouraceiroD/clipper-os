# Clipper OS — instruções para o Claude Code

Sistema de clipping: VOD/vídeo longo → Shorts 9:16. O utilizador fala português de Portugal. Responde em pt-PT.

## Milestone atual (não sair daqui sem o utilizador pedir)
1 VOD real → até 5 candidatos → até 3 Shorts por engine → comparar `own` vs `opusclip`.
NÃO trabalhar ainda em: dashboard, Supabase, Vercel, TikTok, Instagram, monitorização automática,
autopublicação, analytics.

## Como correr
- Ativar o ambiente: `source .venv/bin/activate` (Windows: `.venv\Scripts\activate`)
- Diagnóstico: `python -m clipper doctor`
- Tools do OpusClip (sem créditos): `python -m clipper opusclip-tools`
- Pipeline: `python -m clipper run "<url>" --provider own|opusclip|compare [--dry-run] [--yes]`
- Re-render own: `python -m clipper render <vod-id>` (depois de editar `outputs/<vod-id>/own/highlights.json`)
- Testes (sem rede/API/créditos): `python tests/test_windows_compat.py`, `python tests/smoke_test.py`, `python tests/test_compare_flow.py`
- Validação OpusClip depois do OAuth: `docs/OPUSCLIP_VALIDATION.md`
- Utilizador em Windows 11 / PowerShell: comandos para ele em PowerShell (ver README)

## Escolha do modelo Whisper (`transcribe` no config.yaml)
Verificar a GPU com `nvidia-smi`. Não escolher um modelo acima do que a VRAM aguenta.

| Hardware | model | device | compute_type |
|---|---|---|---|
| Sem GPU NVIDIA | small | cpu | int8 |
| NVIDIA < 4 GB VRAM | small | cuda | int8_float16 |
| NVIDIA 4–6 GB | medium | cuda | int8_float16 |
| NVIDIA 6–8 GB | large-v3-turbo | cuda | int8_float16 |
| NVIDIA ≥ 8 GB | large-v3-turbo | cuda | float16 |

Para CUDA o faster-whisper precisa de cuBLAS 12 e cuDNN 9 (`pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"`).
Se der erro de DLL/biblioteca CUDA em falta e não se resolver sem instalar software pago, voltar a `cpu` e avisar.
Validar com uma transcrição curta (ex.: 10 s de áudio gerado com FFmpeg), nunca com um VOD.

## Estrutura
- `clipper/cli.py` orquestração (submete OpusClip primeiro, corre own em paralelo, depois compara)
- `clipper/engines/own.py` análise Claude + render FFmpeg → formato comum
- `clipper/engines/opusclip.py` opera o MCP `opusclip` via `claude -p` (submit/wait/fetch/download, retomável por `state.json`)
- `clipper/claude_cli.py` wrapper do `claude -p --json-schema`
- `clipper/analyze.py` prompt + schema dos momentos; `clipper/render.py` FFmpeg (silêncios, layouts, legendas ASS, hook)
- `clipper/compare.py` comparison.json + report.md; `clipper/costs.py` custos cumulativos por VOD
- `clipper/db.py` SQLite em `data/clipper.db`; `config.yaml` local (nunca commitar)
- `ROADMAP.md` — manter atualizado (✅ 🔨 ⏳)

## Regras de custo (obrigatórias)
- Processar um VOD de cada vez. Nunca correr vários VODs nem `--reanalyze` sem o utilizador pedir.
- Nunca passar `--yes` (créditos OpusClip) sem confirmação explícita do utilizador nessa conversa.
- Nunca submeter um segundo projeto OpusClip para o mesmo VOD: o `state.json` guarda o `project_id`.
- Preferir `--dry-run` para iterar no prompt de análise.

## Regras gerais
- Nunca publicar/agendar nada (nem pelo MCP OpusClip). Uploads futuros começam `private`.
- Respeitar copyright: só clipar canais com autorização; crédito ao criador na descrição.
- Não commitar `data/`, `outputs/`, vídeos, `config.yaml`, `.env`, cookies, tokens ou credenciais OAuth.
- Ao alterar código em `clipper/`, correr os três testes antes de commitar. Commits pequenos e claros.
