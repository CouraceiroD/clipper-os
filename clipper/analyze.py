"""O "cérebro": o Claude lê a transcrição inteira e escolhe/pontua os melhores momentos.

Dois backends:
  - api          -> Anthropic API (paga por uso, ~0,2-0,5 € por VOD de 3h). Mais estável para automação.
  - claude_code  -> `claude -p` com a tua subscrição Claude (sem custo extra por chamada).
"""
from __future__ import annotations

import json

from .transcribe import all_words

CATEGORIES = ["funny", "rage", "clutch", "fail", "wholesome", "story", "hot_take",
              "reaction", "skill", "drama", "educational", "other"]

CLIP_SCHEMA = {
    "type": "object",
    "properties": {
        "start": {"type": "number", "description": "segundos no vídeo original"},
        "end": {"type": "number"},
        "title": {"type": "string"},
        "hook_text": {"type": "string", "description": "texto curto no ecrã nos primeiros segundos"},
        "summary": {"type": "string"},
        "why_viral": {"type": "string"},
        "category": {"type": "string", "enum": CATEGORIES},
        "hook_score": {"type": "integer"},
        "emotion_score": {"type": "integer"},
        "payoff_score": {"type": "integer"},
        "standalone_score": {"type": "integer"},
        "viral_score": {"type": "integer"},
        "cut_silences": {"type": "boolean"},
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "thumbnail_text": {"type": "string"},
    },
    "required": ["start", "end", "title", "hook_text", "summary", "why_viral", "category",
                 "hook_score", "emotion_score", "payoff_score", "standalone_score",
                 "viral_score", "cut_silences", "description", "hashtags", "thumbnail_text"],
    "additionalProperties": False,
}

SCHEMA = {
    "type": "object",
    "properties": {
        "video_summary": {"type": "string"},
        "clips": {"type": "array", "items": CLIP_SCHEMA},
    },
    "required": ["video_summary", "clips"],
    "additionalProperties": False,
}

SYSTEM = """És um editor sénior de short-form (YouTube Shorts, TikTok, Reels) especializado em clips de lives e vídeos longos.
A tua tarefa é encontrar os momentos com MAIOR POTENCIAL VIRAL numa transcrição com timestamps, e rejeitar tudo o que é fraco.

Procura (por ordem de valor):
- emoção forte: humor, riso, raiva, choque, euforia, frustração genuína;
- surpresa: algo inesperado, reviravolta, frase que ninguém esperava;
- conflito: discussão, provocação, opinião polémica, "roast";
- reação forte a algo (vitória, derrota, susto, revelação);
- jogadas/feitos impressionantes (clutch, fail épico) quando a fala deixa perceber o que aconteceu;
- frases citáveis, histórias curtas com final forte.

Cada clip tem de:
- ter gancho nos primeiros 1-3 s (frase forte, reação, conflito, pergunta, algo inesperado) — se o melhor gancho
  está a meio, começa mais tarde;
- ter arco completo: setup -> tensão -> payoff; começa pouco antes do setup e termina logo depois do payoff;
- funcionar ISOLADO, sem conhecer o resto da live (ou com uma linha curta de contexto no hook_text).

Rejeita sempre:
- intros e "starting soon", cumprimentos ao chat, setup técnico, despedidas;
- logística, leitura de donates/subs sem graça, publicidade;
- pausas longas e momentos mortos;
- momentos que dependem de algo visual que a transcrição não deixa perceber;
- momentos repetidos: se dois momentos são sobre a mesma coisa, escolhe só o melhor. Prefere variedade.

Pontuação (sê exigente e honesto; a maioria dos momentos de uma live NÃO merece clip):
- hook_score, emotion_score, payoff_score, standalone_score: 0-10.
- viral_score: 0-100, a tua estimativa global. 80+ = excelente, 65-79 = bom, <65 = fraco.

Regras:
- start/end em segundos do vídeo original, alinhados com os timestamps fornecidos.
- Clips não se sobrepõem.
- cut_silences=false quando o momento depende de ação/silêncio dramático (ex.: jogada sem fala); true quando é sobretudo fala.
- why_viral: explica em 1-2 frases concretas porque este momento prende (o gancho, a emoção, o payoff).
- Metadados (title, hook_text, description, hashtags, thumbnail_text) no idioma pedido. Título <= 70 caracteres, curiosidade sem clickbait falso.
- hook_text: curto e forte, no máximo 8 palavras, aparece no ecrã nos primeiros segundos. thumbnail_text: 2-4 palavras.
- description: 1-2 frases + crédito ao criador original (nome do canal).
- hashtags: 3-6, sem o símbolo #.
"""

# Lives longas são analisadas por partes (~4 h de fala por chamada) para caberem no contexto.
MAX_CHARS_PER_CALL = 400_000
OVERLAP_SECONDS = 120


def _format_segments(segments: list[dict]) -> str:
    return "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments)


def _format_transcript(transcript: dict) -> str:
    return _format_segments(transcript["segments"])


def _chunks(segments: list[dict], max_chars: int) -> list[list[dict]]:
    chunks, cur, size = [], [], 0
    for seg in segments:
        line = len(seg["text"]) + 20
        if cur and size + line > max_chars:
            chunks.append(cur)
            tail = [x for x in cur if x["start"] >= cur[-1]["end"] - OVERLAP_SECONDS]
            cur, size = list(tail), sum(len(x["text"]) + 20 for x in tail)
        cur.append(seg)
        size += line
    if cur:
        chunks.append(cur)
    return chunks


def _user_prompt(segments: list[dict], meta: dict, cfg: dict, part: str = "") -> str:
    a = cfg["analyze"]
    return f"""Fonte: "{meta.get('title')}" do canal "{meta.get('channel')}" (duração {meta.get('duration') or 0:.0f}s).{part}
Contexto do canal/streamer: {a['channel_context'] or 'n/d'}
Idioma dos metadados: {a['metadata_language']}
Duração de cada clip: entre {a['min_duration']} e {a['max_duration']} segundos.
Devolve até {a['max_clips'] * 2} candidatos ordenados por viral_score (inclui alguns médios para eu poder filtrar).

Transcrição ([início-fim em segundos] texto):
{_format_segments(segments)}
"""


def _call_api(system: str, user: str, cfg: dict, tracker=None) -> dict:
    import anthropic

    a = cfg["analyze"]
    client = anthropic.Anthropic()
    # Streaming evita timeouts com transcrições longas. `fallbacks="default"` faz o
    # servidor repetir o pedido noutro modelo se o principal recusar (falso positivo de segurança).
    with client.beta.messages.stream(
        model=a["model"],
        max_tokens=32000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system,
        output_config={"effort": a["effort"],
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": user}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"Claude recusou a análise: {msg.stop_details}")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Resposta truncada (max_tokens). Reduz max_clips.")
    u = msg.usage
    print(f"[analyze] tokens in={u.input_tokens} out={u.output_tokens} modelo={msg.model}")
    if tracker:
        tracker.claude("own.analyze", msg.model, u.input_tokens, u.output_tokens,
                       getattr(u, "cache_read_input_tokens", 0) or 0, backend="api")
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text)


def _call_claude_code(system: str, user: str, cfg: dict, tracker=None) -> dict:
    from . import claude_cli

    model = cfg["analyze"]["model"]
    out, info = claude_cli.run(user, SCHEMA, model=model, system=system,
                               disallowed_tools=["Bash", "Edit", "Write", "WebFetch", "WebSearch"])
    print(f"[analyze] tokens in={info['input_tokens']} out={info['output_tokens']} (claude -p)")
    if tracker:
        tracker.claude("own.analyze", model, info["input_tokens"], info["output_tokens"],
                       info["cache_read"], info["cost_usd"], backend="claude_code")
    return out


def _snap(h: dict, words: list[dict]) -> None:
    """Alinha início/fim aos limites de palavras para não cortar a meio de uma palavra."""
    inside = [w for w in words if w["end"] > h["start"] - 0.5 and w["start"] < h["end"] + 0.5]
    if inside:
        h["start"] = round(max(0.0, inside[0]["start"] - 0.2), 2)
        h["end"] = round(inside[-1]["end"] + 0.35, 2)


def _reject_reason(h: dict, chosen: list[dict], cfg: dict, db, source_id: str, min_score: int) -> str | None:
    a = cfg["analyze"]
    dur = h["end"] - h["start"]
    if h["viral_score"] < min_score:
        return f"score {h['viral_score']} < {min_score}"
    if dur < a["min_duration"] * 0.7 or dur > a["max_duration"] * 1.5:
        return f"duração {dur:.0f}s fora do intervalo"
    if any(min(h["end"], c["end"]) - max(h["start"], c["start"]) > 1.5 for c in chosen):
        return "sobrepõe-se a outro clip escolhido"
    if db.overlaps_existing(source_id, h["start"], h["end"]):
        return "já existe no histórico"
    if len(chosen) >= a["max_clips"]:
        return "já há clips suficientes com score mais alto"
    return None


def select(raw: dict, transcript: dict, cfg: dict, db, source_id: str,
           rejected: list | None = None, fill_min_score: int | None = None) -> list[dict]:
    """Escolhe até max_clips candidatos. Com fill_min_score, se faltarem clips acima de min_score,
    completa com os melhores restantes acima desse limiar (marcados com below_threshold=True)."""
    words = all_words(transcript)
    cands = sorted(raw["clips"], key=lambda c: c["viral_score"], reverse=True)
    for h in cands:
        _snap(h, words)
    chosen: list[dict] = []
    reasons: dict[int, str] = {}
    for i, h in enumerate(cands):
        r = _reject_reason(h, chosen, cfg, db, source_id, cfg["analyze"]["min_score"])
        if r:
            reasons[i] = r
        else:
            chosen.append(h)
    if fill_min_score is not None and len(chosen) < cfg["analyze"]["max_clips"]:
        for i, h in enumerate(cands):
            if i in reasons and reasons[i].startswith("score"):
                if not _reject_reason(h, chosen, cfg, db, source_id, fill_min_score):
                    h["below_threshold"] = True
                    chosen.append(h)
                    del reasons[i]
    chosen.sort(key=lambda c: c["viral_score"], reverse=True)
    for i, r in reasons.items():
        print(f"[analyze] rejeitado: {cands[i]['title']!r} -> {r}")
        if rejected is not None:
            rejected.append({**cands[i], "reject_reason": r})
    return chosen


def analyze(transcript: dict, meta: dict, cfg: dict, tracker=None) -> dict:
    backend = cfg["analyze"]["backend"]
    call = _call_claude_code if backend == "claude_code" else _call_api
    parts = _chunks(transcript["segments"], MAX_CHARS_PER_CALL)
    merged = {"video_summary": "", "clips": []}
    for k, segs in enumerate(parts, 1):
        part = ""
        if len(parts) > 1:
            part = (f"\nATENÇÃO: esta é a parte {k} de {len(parts)} da transcrição "
                    f"({segs[0]['start']:.0f}s a {segs[-1]['end']:.0f}s). Analisa só esta parte.")
        user = _user_prompt(segs, meta, cfg, part)
        print(f"[analyze] backend={backend} parte {k}/{len(parts)} (~{len(user) // 4} tokens)")
        res = call(SYSTEM, user, cfg, tracker)
        summ = res.get("video_summary", "").strip()
        if summ and summ not in merged["video_summary"]:
            merged["video_summary"] += (" " if merged["video_summary"] else "") + summ
        merged["clips"] += res.get("clips", [])
    if len(parts) > 1:
        merged["clips"] = _dedupe(merged["clips"])
    return merged


def _dedupe(clips: list[dict]) -> list[dict]:
    """Partes sobrepostas podem propor o mesmo momento: fica o de score mais alto."""
    kept: list[dict] = []
    for c in sorted(clips, key=lambda x: x["viral_score"], reverse=True):
        dup = False
        for k in kept:
            inter = min(c["end"], k["end"]) - max(c["start"], k["start"])
            union = max(c["end"], k["end"]) - min(c["start"], k["start"])
            if union > 0 and inter / union > 0.5:
                dup = True
                break
        if not dup:
            kept.append(c)
    return kept
