# Clipper OS

Transforma lives e vídeos longos em Shorts / Reels / TikToks verticais, com o Claude como "cérebro".
Tem dois engines de clipping que podem correr lado a lado para comparar resultados:

```
                       ┌─ A · own ──────► yt-dlp ► faster-whisper ► Claude (momentos + score) ► FFmpeg 9:16
VOD (URL) ─► clipper ──┤
                       └─ B · opusclip ─► Claude Code ► MCP OpusClip (submit ► estado ► clips + virality ► export)
                                                     │
                     outputs/<vod>/ own/ · opusclip/ · comparison.json · report.md · costs.json
```

**Objetivo atual:** 1 VOD → até 5 candidatos → até 3 Shorts por engine → comparar own vs OpusClip.
Nada é publicado nem carregado para nenhuma plataforma.

## Instalação no Windows 11 (PowerShell)

Uma vez só (depois fecha e reabre o PowerShell para o PATH atualizar):

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Gyan.FFmpeg
winget install -e --id Git.Git
winget install -e --id DenoLand.Deno
irm https://claude.ai/install.ps1 | iex
```

O Deno é usado pelo yt-dlp para o YouTube. O último comando instala o Claude Code (`claude.exe`).
Se já tens o Claude Code via npm (`claude.cmd`) também funciona.

Projeto:

```powershell
git clone https://github.com/CouraceiroD/clipper-os.git
cd clipper-os
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml
```

Se o `Activate.ps1` for bloqueado: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e repete.

### GPU NVIDIA (opcional)

```powershell
nvidia-smi
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
```

Escolhe o modelo no `config.yaml` (secção `transcribe`) pela VRAM: ver a tabela em `CLAUDE.md`.
Sem GPU: `model: small`, `device: cpu`, `compute_type: int8`. Se a GPU falhar, o sistema cai para CPU sozinho.

### Ligar o OpusClip (MCP oficial, OAuth)

Na pasta do projeto:

```powershell
claude mcp add --transport http opusclip https://mcp.opus.pro/mcp
claude
```

Dentro do Claude Code: `/mcp` → **opusclip** → login no browser → sai com `/exit`.
O token fica guardado pelo Claude Code fora do repositório.

### Verificar

```powershell
python tests/test_windows_compat.py
python tests/smoke_test.py
python tests/test_compare_flow.py
python -m clipper doctor
python -m clipper opusclip-tools
```

`opusclip-tools` não gasta créditos: grava as tools e o saldo em `docs/opusclip_tools.md`.
Depois segue `docs/OPUSCLIP_VALIDATION.md`.

## Uso (um VOD de cada vez)

```powershell
python -m clipper run "URL_DO_VOD" --provider own --dry-run   # só lista os momentos
python -m clipper run "URL_DO_VOD" --provider compare         # own + OpusClip + relatório
python -m clipper render <vod-id>                             # re-render own após editar highlights.json
```

- O OpusClip pede confirmação antes de gastar créditos (`--yes` confirma sem pergunta).
- Tudo é retomável e em cache: download, transcrição, análise e o projeto OpusClip já submetido.
  Voltar a correr o mesmo comando nunca paga duas vezes.
- Limites: `max_candidates: 5`, `max_renders: 3`, `max_vod_minutes: 240` (no `config.yaml`).

## Resultados

```
outputs/<vod-id>/
  own/        clip-01.mp4 … clip-03.mp4 + clip-NN.json + highlights.json (editável)
  opusclip/   clip-01.mp4 … clip-03.mp4 + clip-NN.json + state.json (project_id)
  comparison.json   todos os clips em formato comum + resumo + momentos partilhados
  report.md         lado a lado, detalhe, avaliação manual, vencedor, custos
  costs.json        minutos transcritos, tokens/custo Claude, chamadas, créditos OpusClip, tempos (cumulativo)
```

Estado do projeto: ver [ROADMAP.md](ROADMAP.md).
