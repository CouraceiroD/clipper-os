# Clipper OS — Roadmap

Legenda: ✅ concluído · 🔨 em desenvolvimento · ⏳ pendente · 🅿️ parado até o milestone atual estar provado

## 🎯 Milestone atual: "dou uma live → recebo 3 Shorts finalizados"
Fluxo principal 100% local: `python -m clipper auto "<URL>"` ou, no Claude Code, "Clip this live: <URL>".

### Modo auto (fluxo principal)
- ✅ `clipper auto`: yt-dlp → faster-whisper local → Claude Code escolhe os 3 momentos mais virais → FFmpeg
- ✅ Critérios virais no prompt (emoção, surpresa, conflito, humor, reação, jogadas, frases inesperadas,
  funciona isolado); evita intros, falta de contexto, silêncios e repetições
- ✅ Lives longas analisadas por partes, com deduplicação; completa até 3 clips (⚠ se abaixo do limiar)
- ✅ `outputs/<vod-id>/clip-01..03.mp4` + `report.md` com o porquê de cada escolha
- ✅ Skill `clip` + `CLAUDE.md`: o Claude Code reconhece pedidos naturais e corre tudo sozinho
- ⏳ Primeira live real no PC do utilizador e afinação do prompt com base no resultado

### Pipeline A — own
- ✅ Download (yt-dlp: YouTube, Twitch VOD, Kick…) ou ficheiro local
- ✅ Transcrição local gratuita (faster-whisper, timestamps por palavra)
- ✅ Análise Claude: momentos + scores (hook/emoção/payoff/standalone/viral); backend `claude_code` ou `api`
- ✅ Filtros: score mínimo, duração, sobreposição, histórico
- ✅ Render 9:16 numa passagem FFmpeg: layouts `blur` / `crop` / `split`, corte de silêncios, legendas
  palavra a palavra, hook no ecrã, áudio a -14 LUFS
- ✅ Metadados: título, descrição com crédito, hashtags, texto de thumbnail

### Pipeline B — OpusClip (opcional, só para comparação; MCP oficial, OAuth)
- ✅ Engine `opusclip` operado pelo Claude Code (`claude -p` + MCP): submit → estado → clips + virality → export → download
- ✅ Retomável e sem duplicar custos (`state.json` com `project_id`); confirmação antes de gastar créditos
- ✅ Integração independente dos nomes das tools (o Claude escolhe-as); checklist em `docs/OPUSCLIP_VALIDATION.md`
- ⏳ Login OAuth no PC do utilizador (`/mcp`) e `clipper opusclip-tools` para confirmar tools, créditos e export

### Comparação e custos
- ✅ `provider: own | opusclip | compare`
- ✅ `outputs/<vod>/own|opusclip/clip-NN.mp4`, `comparison.json`, `report.md` com tabela de avaliação manual
- ✅ `costs.json` cumulativo: minutos transcritos, tokens/custo Claude, chamadas externas, créditos OpusClip, tempos
- ✅ Proteções: `max_vod_minutes`, um VOD por execução, caches em todas as etapas, verificação do MCP antes de gastar
- ✅ Compatibilidade Windows 11: `claude.exe`/`claude.cmd`, UTF-8, caminhos, CUDA com fallback para CPU, passos PowerShell
- ✅ `report.md` com tabela lado a lado, edição usada, custos, tempos e secção de vencedor
- ⏳ Primeiro VOD real em modo `compare` no PC do utilizador
- ⏳ Avaliação manual dos 6 Shorts e decisão do que melhorar

## Depois do milestone (pela ordem provável)
- ⏳ Qualidade own: reframing por deteção de cara (MediaPipe), zooms nos picos, picos de chat/volume como sinal
- ⏳ Vídeo longo de highlights com capítulos
- 🅿️ Upload YouTube `private` + fila de aprovação. Quota: a YouTube Data API tem um bucket próprio para
  `videos.insert` (por defeito 100 uploads/dia), separado dos 10 000 unidades/dia das outras chamadas.
  Confirmar os valores do projeto no Google Cloud Console (IAM & Admin → Quotas). Vídeos de projetos
  não verificados ficam privados até à auditoria da API.
- 🅿️ Monitorização automática de canais (RSS YouTube / Twitch Helix) + scheduler
- 🅿️ Dashboard "Clipper OS" (Supabase + Vercel) e métricas (YouTube Analytics)
- 🅿️ TikTok, Instagram Reels, autopublicação
