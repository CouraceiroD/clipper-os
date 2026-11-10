# Clipper OS — Roadmap

Legenda: ✅ concluído · 🔨 em desenvolvimento · ⏳ pendente · 🅿️ parado até o milestone atual estar provado

## 🎯 Milestone atual: "dou um VOD e recebo 3 Shorts bons"
1 VOD real → detetar momentos → máx. 5 candidatos → máx. 3 Shorts por engine → comparar own vs OpusClip.

### Pipeline A — own
- ✅ Download (yt-dlp: YouTube, Twitch VOD, Kick…) ou ficheiro local
- ✅ Transcrição local gratuita (faster-whisper, timestamps por palavra)
- ✅ Análise Claude: momentos + scores (hook/emoção/payoff/standalone/viral); backend `claude_code` ou `api`
- ✅ Filtros: score mínimo, duração, sobreposição, histórico
- ✅ Render 9:16 numa passagem FFmpeg: layouts `blur` / `crop` / `split`, corte de silêncios, legendas
  palavra a palavra, hook no ecrã, áudio a -14 LUFS
- ✅ Metadados: título, descrição com crédito, hashtags, texto de thumbnail

### Pipeline B — OpusClip (MCP oficial `https://mcp.opus.pro/mcp`, OAuth)
- ✅ Engine `opusclip` operado pelo Claude Code (`claude -p` + MCP): submit → estado → clips + virality → export → download
- ✅ Retomável e sem duplicar custos (`state.json` com `project_id`); confirmação antes de gastar créditos
- ⏳ Login OAuth no PC do utilizador (`/mcp`) e `clipper opusclip-tools` para fixar os nomes reais das tools

### Comparação e custos
- ✅ `provider: own | opusclip | compare`
- ✅ `outputs/<vod>/own|opusclip/clip-NN.mp4`, `comparison.json`, `report.md` com tabela de avaliação manual
- ✅ `costs.json` cumulativo: minutos transcritos, tokens/custo Claude, chamadas externas, créditos OpusClip, tempos
- ✅ Proteções: `max_vod_minutes`, um VOD por execução, caches em todas as etapas
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
