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

## Instalação (no teu PC)

Requisitos: Python 3.10+, FFmpeg no PATH, Git, [Claude Code](https://code.claude.com) e uma conta OpusClip.
GPU NVIDIA é opcional (acelera muito a transcrição).

```bash
git clone <o-teu-repo> clipper-os && cd clipper-os
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.yaml config.yaml # Windows: copy config.example.yaml config.yaml
python tests/smoke_test.py
python tests/test_compare_flow.py
```

### Ligar o OpusClip (MCP oficial, OAuth)

```bash
claude mcp add --transport http opusclip https://mcp.opus.pro/mcp
```

Depois, dentro desta pasta, abre `claude`, escreve `/mcp`, escolhe **opusclip** e faz login no browser.
O token fica guardado pelo Claude Code fora do repositório. Nenhuma chave vai para o Git.

Confirmar tudo:

```bash
python -m clipper doctor
python -m clipper opusclip-tools   # lista as tools do MCP e os créditos (não consome créditos)
```

### Claude para a análise do pipeline próprio

- `analyze.backend: claude_code` (por defeito no exemplo): usa a tua subscrição do Claude Code.
- `analyze.backend: api`: usa `ANTHROPIC_API_KEY` (pago por uso).

## Uso

```bash
python -m clipper run "<URL do VOD>" --provider own --dry-run   # só lista os momentos (barato)
python -m clipper run "<URL do VOD>" --provider compare         # own + OpusClip + relatório
python -m clipper render <vod-id>                               # re-render own depois de editar highlights.json
```

- OpusClip pede confirmação antes de gastar créditos (`--yes` para confirmar sem pergunta).
- Tudo é retomável: voltar a correr o mesmo comando reutiliza download, transcrição, análise e o projeto
  OpusClip já submetido. Não paga duas vezes.

## Resultados

```
outputs/<vod-id>/
  own/        clip-01.mp4 … clip-03.mp4 + clip-NN.json + highlights.json (editável)
  opusclip/   clip-01.mp4 … clip-03.mp4 + clip-NN.json + state.json (project_id)
  comparison.json   todos os clips em formato comum + resumo + momentos partilhados
  report.md         comparação legível + tabela de avaliação manual
  costs.json        minutos transcritos, tokens/custo Claude, chamadas, créditos OpusClip, tempos (cumulativo)
```

Estado do projeto: ver [ROADMAP.md](ROADMAP.md).
