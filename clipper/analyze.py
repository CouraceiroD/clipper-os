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
A tua tarefa é encontrar os momentos com maior potencial de retenção e partilha numa transcrição com timestamps, e rejeitar tudo o que é fraco.

Critérios de um bom clip:
- Gancho nos primeiros 1-3 s (frase forte, reação, conflito, pergunta, algo inesperado).
- Arco completo: setup -> tensão -> payoff. Começa um pouco antes do setup e termina logo depois do payoff (sem cauda morta).
- Compreensível sem contexto do resto da live (ou com uma linha curta de contexto no hook_text).
- Emoção forte (humor, raiva, surpresa, vitória/derrota, história pessoal, opinião polémica).
- Evita: conversa de logística, ler donates sem graça, pausas longas, momentos que dependem de algo visual que a transcrição não deixa perceber.

Pontuação (seja exigente e honesto; a maioria dos momentos de uma live NÃO merece clip):
- hook_score, emotion_score, payoff_score, standalone_score: 0-10.
- viral_score: 0-100, a tua estimativa global. 80+ = excelente, 65-79 = bom, <65 = fraco.

Regras:
- start/end em segundos do vídeo original, alinhados com os timestamps fornecidos.
- Clips não se sobrepõem.
- cut_silences=false quando o momento depende de ação/silêncio dramático (ex.: jogada sem fala); true quando é sobretudo fala.
- Metadados (title, hook_text, description, hashtags, thumbnail_text) no idioma pedido. Título <= 70 caracteres, curiosidade sem clickbait falso.
- hook_text: no máximo 8 palavras. thumbnail_text: 2-4 palavras.
- description: 1-2 frases + crédito ao criador original (nome do canal).
- hashtags: 3-6, sem o símbolo #.
"""


def _format_transcript(transcript: dict) -> str:
    lines = []
    for s in transcript["segments"]:
        lines.append(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}")
    return "\n".join(lines)


def _user_prompt(transcript: dict, meta: dict, cfg: dict) -> str:
    a = cfg["analyze"]
    return f"""Fonte: "{meta.get('title')}" do canal "{meta.get('channel')}" (duração {meta.get('duration', 0):.0f}s).
Contexto do canal/streamer: {a['channel_context'] or 'n/d'}
Idioma dos metadados: {a['metadata_language']}
Duração de cada clip: entre {a['min_duration']} e {a['max_duration']} segundos.
Devolve até {a['max_clips'] * 2} candidatos ordenados por viral_score (inclui alguns médios para eu poder filtrar).

Transcrição ([início-fim em segundos] texto):
{_format_transcript(transcript)}
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


def select(raw: dict, transcript: dict, cfg: dict, db, source_id: str) -> list[dict]:
    a = cfg["analyze"]
    words = all_words(transcript)
    chosen: list[dict] = []
    rejected = []
    for h in sorted(raw["clips"], key=lambda c: c["viral_score"], reverse=True):
        _snap(h, words)
        dur = h["end"] - h["start"]
        reason = None
        if h["viral_score"] < a["min_score"]:
            reason = f"score {h['viral_score']} < {a['min_score']}"
        elif dur < a["min_duration"] * 0.7 or dur > a["max_duration"] * 1.5:
            reason = f"duração {dur:.0f}s fora do intervalo"
        elif any(min(h["end"], c["end"]) - max(h["start"], c["start"]) > 1.5 for c in chosen):
            reason = "sobrepõe-se a outro clip escolhido"
        elif db.overlaps_existing(source_id, h["start"], h["end"]):
            reason = "já existe no histórico"
        elif len(chosen) >= a["max_clips"]:
            reason = "limite max_clips"
        if reason:
            rejected.append((h["title"], reason))
        else:
            chosen.append(h)
    for t, r in rejected:
        print(f"[analyze] rejeitado: {t!r} -> {r}")
    return chosen


def analyze(transcript: dict, meta: dict, cfg: dict, tracker=None) -> dict:
    user = _user_prompt(transcript, meta, cfg)
    backend = cfg["analyze"]["backend"]
    print(f"[analyze] backend={backend} ({len(user) // 4} tokens aprox.)")
    if backend == "claude_code":
        return _call_claude_code(SYSTEM, user, cfg, tracker)
    return _call_api(SYSTEM, user, cfg, tracker)
