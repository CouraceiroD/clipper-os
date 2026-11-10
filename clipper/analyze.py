"""O "cérebro": o Claude lê a transcrição inteira e escolhe/pontua os melhores momentos.

Dois backends:
  - api          -> Anthropic API (paga por uso, ~0,2-0,5 € por VOD de 3h). Mais estável para automação.
  - claude_code  -> `claude -p` com a tua subscrição Claude (sem custo extra por chamada).
"""
from __future__ import annotations

import json
import re

from .transcribe import all_words

CATEGORIES = ["funny", "rage", "clutch", "fail", "wholesome", "story", "hot_take",
              "reaction", "skill", "drama", "educational", "other"]

CLIP_SCHEMA = {
    "type": "object",
    "properties": {
        "start": {"type": "number", "description": "seconds in the original video"},
        "end": {"type": "number"},
        "title": {"type": "string"},
        "hook_text": {"type": "string", "description": "short on-screen text for the first seconds"},
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

SYSTEM = """You are a senior short-form editor (YouTube Shorts, TikTok, Reels) specialised in clips from livestreams and long videos.
Your job is to find the moments with the HIGHEST VIRAL POTENTIAL in a timestamped transcript, and reject everything weak.

Look for (in order of value):
- strong emotion: humour, laughter, anger, shock, hype, genuine frustration;
- surprise: something unexpected, a twist, a line nobody saw coming;
- conflict: arguments, provocation, hot takes, roasts;
- strong reactions (win, loss, jump scare, reveal);
- impressive plays/feats (clutch, epic fail) when the speech makes it clear what happened;
- quotable lines, short stories with a strong ending.

Every clip must:
- hook in the first 1-3 s (strong line, reaction, conflict, question, something unexpected) - if the best hook
  is in the middle, start later;
- have a complete arc: setup -> tension -> payoff; start just before the setup and end right after the payoff;
- work STANDALONE, without knowing the rest of the stream (or with one short line of context in hook_text).

Always reject:
- intros and "starting soon", greeting chat, technical setup, goodbyes;
- logistics, unfunny donation/sub reading, ads;
- long pauses and dead air;
- moments that depend on visuals the transcript doesn't convey;
- repeats: if two moments are about the same thing, keep only the best one. Prefer variety.

Scoring (be strict and honest; most moments of a stream do NOT deserve a clip):
- hook_score, emotion_score, payoff_score, standalone_score: 0-10.
- viral_score: 0-100, your overall estimate. 80+ = excellent, 65-79 = good, <65 = weak.

Rules:
- start/end in seconds of the original video, aligned with the given timestamps.
- Clips must not overlap.
- cut_silences=false when the moment depends on action/dramatic silence (e.g. a play with no talking); true when it is mostly speech.
- why_viral: 1-2 concrete sentences on why this moment grabs attention (the hook, the emotion, the payoff).

Language (very important):
{language_rule}
- ALL text fields (title, hook_text, description, hashtags, thumbnail_text, summary, why_viral, video_summary)
  are written in the output language above, whatever language is spoken in the video.
- Write like a native creator in that language posting to YouTube Shorts/TikTok: natural, punchy, idiomatic.
  Never a literal translation. Quotes from the stream may stay in the original wording when they are the joke.
- Title <= 70 characters, curiosity without fake clickbait.
- hook_text: short and strong, max 8 words, shown on screen in the first seconds. thumbnail_text: 2-4 words.
- description: 1-2 sentences + credit to the original creator (channel name).
- hashtags: 3-6, without the # symbol, the ones people actually search in that language.
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


LANG_NAMES = {"en": "English", "pt-PT": "European Portuguese (pt-PT)", "pt-BR": "Brazilian Portuguese (pt-BR)",
              "pt": "Portuguese", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian"}
LEGACY_LANGUAGE = "pt-PT"   # análises em cache sem etiqueta de idioma foram geradas em pt-PT


def lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)


def _is_english(code: str) -> bool:
    return code.lower().split("-")[0] == "en"


def language_rule(cfg: dict) -> str:
    """Regra dura no system prompt. O idioma vem só de cfg["output_language"]."""
    lang = cfg["output_language"]
    if _is_english(lang):
        return ("ALL PUBLIC-FACING OUTPUT MUST BE WRITTEN IN ENGLISH. NEVER GENERATE PORTUGUESE HOOKS, TITLES, "
                "DESCRIPTIONS, HASHTAGS, THUMBNAIL TEXT OR VIDEO OVERLAYS.")
    return f"ALL PUBLIC-FACING OUTPUT MUST BE WRITTEN IN {lang_name(lang).upper()}."


def system_prompt(cfg: dict) -> str:
    return SYSTEM.replace("{language_rule}", language_rule(cfg))


def _language_line(cfg: dict) -> str:
    name = lang_name(cfg["output_language"])
    return (f"Output language for ALL text fields: {name}. Natural, native-sounding {name} for YouTube Shorts/TikTok, "
            f"even if the stream is in another language.")


def _user_prompt(segments: list[dict], meta: dict, cfg: dict, part: str = "") -> str:
    a = cfg["analyze"]
    return f"""Source: "{meta.get('title')}" from the channel "{meta.get('channel')}" (duration {meta.get('duration') or 0:.0f}s).{part}
Channel/streamer context: {a['channel_context'] or 'n/a'}
{_language_line(cfg)}
Length of each clip: between {a['min_duration']} and {a['max_duration']} seconds.
Return up to {a['max_clips'] * 2} candidates sorted by viral_score (include a few average ones so I can filter).

Transcript ([start-end in seconds] text):
{_format_segments(segments)}
"""


def _call_api(system: str, user: str, cfg: dict, tracker=None, schema: dict = SCHEMA) -> dict:
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
                       "format": {"type": "json_schema", "schema": schema}},
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


def _call_claude_code(system: str, user: str, cfg: dict, tracker=None, schema: dict = SCHEMA) -> dict:
    from . import claude_cli

    model = cfg["analyze"]["model"]
    out, info = claude_cli.run(user, schema, model=model, system=system,
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
            part = (f"\nNOTE: this is part {k} of {len(parts)} of the transcript "
                    f"({segs[0]['start']:.0f}s to {segs[-1]['end']:.0f}s). Analyse only this part.")
        user = _user_prompt(segs, meta, cfg, part)
        print(f"[analyze] backend={backend} parte {k}/{len(parts)} (~{len(user) // 4} tokens)")
        res = call(system_prompt(cfg), user, cfg, tracker)
        summ = res.get("video_summary", "").strip()
        if summ and summ not in merged["video_summary"]:
            merged["video_summary"] += (" " if merged["video_summary"] else "") + summ
        merged["clips"] += res.get("clips", [])
    if len(parts) > 1:
        merged["clips"] = _dedupe(merged["clips"])
    merged["output_language"] = cfg["output_language"]
    return merged


# ---------------------------------------------------------------- tradução de uma análise em cache
TEXT_FIELDS = ["title", "hook_text", "summary", "why_viral", "description", "hashtags", "thumbnail_text"]

LOCALIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "video_summary": {"type": "string"},
        "localized": {"type": "array", "items": {
            "type": "object",
            "properties": {"index": {"type": "integer"},
                           **{k: CLIP_SCHEMA["properties"][k] for k in TEXT_FIELDS}},
            "required": ["index", *TEXT_FIELDS],
            "additionalProperties": False,
        }},
    },
    "required": ["video_summary", "localized"],
    "additionalProperties": False,
}

LOCALIZE_SYSTEM = """You are a senior short-form editor (YouTube Shorts, TikTok, Reels).
{language_rule}
The clips below were already chosen and scored. Do NOT change which moments they are.
Rewrite ONLY their text fields (title, hook_text, summary, why_viral, description, hashtags, thumbnail_text)
and the video_summary in the requested output language, as a native creator would write them:
natural, punchy, idiomatic - never a literal translation. Use the transcript of each clip to get the meaning right.
Same limits: title <= 70 characters; hook_text max 8 words; thumbnail_text 2-4 words;
description 1-2 sentences + credit to the original creator (channel name); hashtags 3-6 without the # symbol.
Return one entry per clip with the same index.
"""


def localize(raw: dict, transcript: dict, meta: dict, cfg: dict, tracker=None,
             only: list[int] | None = None, feedback: str = "") -> dict:
    """Reescreve os textos de uma análise no idioma configurado, sem mudar momentos nem scores.
    only: índices dos candidatos a reescrever (por defeito todos)."""
    backend = cfg["analyze"]["backend"]
    call = _call_claude_code if backend == "claude_code" else _call_api
    words = all_words(transcript)
    todo = list(range(len(raw["clips"]))) if only is None else only
    items = []
    for i in todo:
        c = raw["clips"][i]
        text = " ".join(w["word"] for w in words if w["start"] >= c["start"] - 0.5 and w["end"] <= c["end"] + 0.5)
        items.append({"index": i, "category": c["category"], **{k: c[k] for k in TEXT_FIELDS},
                      "transcript": text[:3000]})
    user = (f'Source: "{meta.get("title")}" from the channel "{meta.get("channel")}".\n'
            f"{_language_line(cfg)}\n\n"
            f"video_summary: {raw.get('video_summary', '')}\n\n"
            + (f"REJECTED PREVIOUS ATTEMPT: {feedback}\n\n" if feedback else "")
            + f"Clips (JSON):\n{json.dumps(items, ensure_ascii=False, indent=1)}\n")
    print(f"[analyze] a reescrever os textos de {len(items)} candidato(s) em {cfg['output_language']}")
    res = call(LOCALIZE_SYSTEM.replace("{language_rule}", language_rule(cfg)), user, cfg, tracker, LOCALIZE_SCHEMA)
    out = json.loads(json.dumps(raw))
    by_index = {x["index"]: x for x in res.get("localized", [])}
    missing = [i for i in todo if i not in by_index]
    if missing:
        raise RuntimeError(f"Tradução incompleta: faltam os candidatos {missing}")
    for i in todo:
        out["clips"][i].update({k: by_index[i][k] for k in TEXT_FIELDS})
    out["video_summary"] = res.get("video_summary") or out.get("video_summary", "")
    out["output_language"] = cfg["output_language"]
    return out


# ---------------------------------------------------------------- validação do idioma (não confiar só no prompt)
PUBLIC_FIELDS = ["hook_text", "title", "description", "thumbnail_text", "hashtags"]
MAX_LANGUAGE_RETRIES = 2

# Palavras que só aparecem em português (evita colisões com inglês: "a", "e", "o", "do", "no", "em", "um", "de"...).
PT_WORDS = set("""
não nao isto isso esse essa este esta está estão estás você vocês voce ele eles elas lhe lhes uma umas uns
para pra mas porque quando muito muita muitos depois já também só então aqui agora nunca sempre pelo pela
pelos pelas nos ao aos foi ficou fica disseram disse direto pleno sem ninguém alguém tudo nada mais fato festa
quem onde como ficar vai vou têm são seu sua meu minha nosso nossa coisa gente mano vez ainda pode sobre que
olha olhem tirem leva levou entrar entra ligam ligou ligar descobre pagou partiram regras convidaram casa
cabem vinga percebe ninguem engraçado melhor pior hoje ontem amanhã contra até
""".split())
PT_STRONG_CHARS = set("ãõç")
ACCENTED = set("àáâéêíóôú")


def portuguese_hits(text: str) -> list[str]:
    """Indícios de português num texto ([] = parece não ser português)."""
    low = text.lower()
    tokens = re.findall(r"[^\W\d_]+", low)
    words = [t for t in tokens if t in PT_WORDS]
    strong = sorted({ch for ch in low if ch in PT_STRONG_CHARS})
    accents = any(ch in ACCENTED for ch in low)
    short = len(tokens) <= 4                    # hooks curtos / thumbnails: basta uma palavra portuguesa
    if strong or len(words) >= 2 or (words and (accents or short)):
        return words + strong
    return []


def language_problems(clip: dict, cfg: dict) -> dict[str, list[str]]:
    """Campos públicos de um clip que não estão no output_language (só verificado para inglês)."""
    if not _is_english(cfg["output_language"]):
        return {}
    probs = {}
    for f in PUBLIC_FIELDS:
        v = clip.get(f, "")
        hits = portuguese_hits(" ".join(v) if isinstance(v, list) else str(v))
        if hits:
            probs[f] = hits
    return probs


def check_public_language(clip: dict, cfg: dict) -> None:
    """Última barreira antes de queimar texto no vídeo."""
    probs = language_problems(clip, cfg)
    if probs:
        raise RuntimeError(f"Texto público fora de {cfg['output_language']} em {clip.get('title')!r}: {probs}. "
                           "Não vou renderizar.")


def text_language(raw: dict) -> str:
    return raw.get("output_language") or raw.get("metadata_language") or LEGACY_LANGUAGE


def ensure_language(raw: dict, transcript: dict, meta: dict, cfg: dict, tracker=None) -> dict:
    """Garante que todos os textos públicos estão no output_language:
    1) análise noutro idioma (ex.: cache antiga em pt-PT) -> textos regenerados, momentos mantidos;
    2) validação em código; candidatos com português são regenerados (até MAX_LANGUAGE_RETRIES vezes);
    3) se continuar a falhar, pára em vez de renderizar texto no idioma errado."""
    lang = cfg["output_language"]
    if text_language(raw) != lang:
        print(f"[analyze] textos em cache em {text_language(raw)} != output_language {lang}: a regenerar")
        raw = localize(raw, transcript, meta, cfg, tracker)
    for attempt in range(MAX_LANGUAGE_RETRIES + 1):
        bad = {i: p for i, c in enumerate(raw["clips"]) if (p := language_problems(c, cfg))}
        if not bad:
            return raw
        print(f"[analyze] ⚠ português detetado em {len(bad)} candidato(s) com output_language={lang}: {bad}")
        if attempt == MAX_LANGUAGE_RETRIES:
            break
        fb = "; ".join(f"index {i}: " + ", ".join(f"{f} contains Portuguese ({h})" for f, h in p.items())
                       for i, p in bad.items())
        raw = localize(raw, transcript, meta, cfg, tracker, only=list(bad), feedback=fb)
    raise RuntimeError(f"O Claude continuou a devolver português em vez de {lang_name(lang)} depois de "
                       f"{MAX_LANGUAGE_RETRIES} tentativas: {bad}. Nada foi renderizado.")


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
