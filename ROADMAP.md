# Clipper OS — Roadmap

Legenda: ✅ concluído · 🔨 em desenvolvimento · ⏳ pendente

## Fase 1 — MVP local: 1 vídeo → Shorts prontos (🔨)
- ✅ Download de URL (YouTube, Twitch VOD, Kick… via yt-dlp) ou ficheiro local
- ✅ Transcrição local gratuita (faster-whisper, timestamps por palavra)
- ✅ Análise com Claude: deteção de momentos, scores (hook/emoção/payoff/standalone/viral)
- ✅ Filtro: score mínimo, duração, sobreposição, histórico (sem duplicados)
- ✅ Render 9:16 numa passagem FFmpeg: layouts `blur` / `crop` / `split` (facecam + jogo)
- ✅ Corte de silêncios (o Claude decide por clip se deve cortar)
- ✅ Legendas dinâmicas palavra a palavra + hook no ecrã nos primeiros 3s
- ✅ Áudio normalizado (-14 LUFS)
- ✅ Título, descrição, hashtags, texto de thumbnail por clip + `report.md`
- ✅ Histórico SQLite
- ⏳ Primeiro teste real no teu PC com um VOD do streamer escolhido
- ⏳ Afinar o prompt/score com base nos primeiros resultados

## Fase 2 — Qualidade de edição
- ⏳ Reframing automático com deteção de cara (MediaPipe) para o layout `crop`
- ⏳ Zooms/punch-ins nos picos de emoção (volume + palavras-chave)
- ⏳ Sinal extra: picos de chat (Twitch/YouTube chat replay) e de volume
- ⏳ Linha de contexto/narrativa (texto ou voz) para mais transformação
- ⏳ Compilação longa (melhores momentos + transições + capítulos automáticos)
- ⏳ Thumbnail gerada (frame + texto)

## Fase 3 — Publicação no YouTube
- ⏳ OAuth YouTube Data API + upload como `private`/`unlisted` com metadados
- ⏳ Pedir auditoria da API à Google (necessário para vídeos poderem ficar públicos)
- ⏳ Fila de aprovação (aprovar/rejeitar → atualiza histórico)

## Fase 4 — Monitorização automática
- ⏳ Lista de canais (`channels.yaml`) + deteção de novos vídeos/VODs (RSS YouTube, Twitch Helix)
- ⏳ Scheduler no PC (Task Scheduler / cron) → pipeline automático
- ⏳ Vários canais em paralelo, limites de quota

## Fase 5 — Dashboard "Clipper OS"
- ⏳ Migrar histórico para Supabase
- ⏳ Dashboard Next.js na Vercel (canais, fila, clips, scores)
- ⏳ Métricas via YouTube Analytics API (views, CTR, retenção, subs por vídeo)
- ⏳ Análise de que categorias/hooks funcionam melhor → realimenta o prompt

## Fase 6 — Multi-plataforma e autopiloto
- ⏳ TikTok (Content Posting API, requer aprovação da app) e Instagram Reels (Graph API, conta Business)
- ⏳ Publicação 100% automática com regras (score mínimo, horários)
