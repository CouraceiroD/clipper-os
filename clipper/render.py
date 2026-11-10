"""Montagem do clip vertical 9:16 com FFmpeg, numa só passagem:
corte do intervalo -> remoção de silêncios -> layout vertical -> legendas dinâmicas + hook -> áudio normalizado.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

W, H = 1080, 1920


# ---------------------------------------------------------------- silêncios
def keep_segments(words: list[dict], start: float, end: float, gap: float) -> list[tuple[float, float]]:
    """Intervalos (relativos ao início do clip) a manter. Remove pausas > gap segundos."""
    total = end - start
    if gap <= 0 or not words:
        return [(0.0, total)]
    pad = 0.15
    spans = [(max(0.0, w["start"] - start - pad), min(total, w["end"] - start + pad)) for w in words]
    merged = [list(spans[0])]
    for a, b in spans[1:]:
        if a - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    merged[0][0] = 0.0                       # mantém o arranque
    merged[-1][1] = total                    # e o final (reação depois da última palavra)
    return [(round(a, 3), round(b, 3)) for a, b in merged if b - a > 0.05]


def remap(t_rel: float, segs: list[tuple[float, float]]) -> float | None:
    """Converte tempo relativo ao clip para o tempo após os cortes."""
    acc = 0.0
    for a, b in segs:
        if a <= t_rel <= b:
            return acc + (t_rel - a)
        acc += b - a
    return None


# ---------------------------------------------------------------- legendas
def _ts(t: float) -> str:
    t = max(t, 0)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(word: str) -> str:
    return re.sub(r"[{}\\]", "", word).upper()


def build_ass(words: list[dict], hook_text: str, rcfg: dict, caption_y: int) -> str:
    font, size, hl = rcfg["font"], rcfg["font_size"], rcfg["highlight_color"]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,3,5,60,60,0,1
Style: Hook,{font},{int(size * 0.8)},&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    if hook_text:
        ev.append(f"Dialogue: 1,{_ts(0)},{_ts(rcfg['hook_seconds'])},Hook,,0,0,0,,"
                  f"{{\\fad(150,200)}}{_clean(hook_text)}")
    if rcfg["captions"] and words:
        n = max(1, rcfg["words_per_caption"])
        chunks, cur = [], []
        for w in words:
            cur.append(w)
            if len(cur) >= n or w["word"].endswith((".", "?", "!", ",")):
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)
        pos = f"{{\\an5\\pos({W // 2},{caption_y})}}"
        for ci, ch in enumerate(chunks):
            chunk_end = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else ch[-1]["end"] + 0.4
            chunk_end = min(chunk_end, ch[-1]["end"] + 0.6)
            for i, w in enumerate(ch):
                s = w["start"]
                e = ch[i + 1]["start"] if i + 1 < len(ch) else chunk_end
                if e <= s:
                    continue
                parts = []
                for j, ww in enumerate(ch):
                    txt = _clean(ww["word"])
                    if j == i:
                        parts.append(f"{{\\c{hl}\\fscx112\\fscy112}}{txt}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}")
                    else:
                        parts.append(txt)
                ev.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{pos}{' '.join(parts)}")
    return header + "\n".join(ev) + "\n"


# ---------------------------------------------------------------- layout
def layout_filter(rcfg: dict, src_w: int, src_h: int) -> tuple[str, int]:
    """Filtro [vc] -> [vl] e posição Y das legendas."""
    mode = rcfg["layout"]
    if mode == "crop":
        x = rcfg["crop_x"]
        f = (f"[vc]scale=-2:{H},crop={W}:{H}:'max(0,min(iw-{W},iw*{x}-{W}/2))':0,setsar=1[vl]")
        return f, int(H * 0.68)
    if mode == "split":
        sp = rcfg["split"]
        fh = sp["facecam_height"]
        gh = H - fh

        def crop(r):
            x, y, w, h = r
            return f"crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}"

        f = (f"[vc]split=2[c1][c2];"
             f"[c1]{crop(sp['facecam'])},scale={W}:{fh}:force_original_aspect_ratio=increase,crop={W}:{fh}[cam];"
             f"[c2]{crop(sp['gameplay'])},scale={W}:{gh}:force_original_aspect_ratio=increase,crop={W}:{gh}[game];"
             f"[cam][game]vstack=inputs=2,setsar=1[vl]")
        return f, fh
    # blur (por defeito): vídeo inteiro ao centro, fundo desfocado
    f = (f"[vc]split=2[b1][b2];"
         f"[b1]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=30,eq=brightness=-0.08[bg];"
         f"[b2]scale={W}:-2[fg];"
         f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[vl]")
    fg_h = int(W * src_h / src_w)
    return f, min(H - 260, (H + fg_h) // 2 + 170)


def _probe_size(path: str) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0:s=x", path],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)


# ---------------------------------------------------------------- render
def render_clip(video_path: str, h: dict, words: list[dict], out_dir: Path, rcfg: dict,
                caption_words: list[dict] | None = None) -> Path:
    """caption_words: palavras das legendas, se diferentes das faladas (ex.: tradução para inglês).
    Os cortes de silêncio usam sempre as palavras faladas."""
    out_dir.mkdir(parents=True, exist_ok=True)
    start, end = h["start"], h["end"]
    clip_words = [w for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]

    gap = rcfg["silence_gap"] if h.get("cut_silences", True) else 0
    segs = keep_segments(clip_words, start, end, gap)

    cap_words = clip_words if caption_words is None else [
        w for w in caption_words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]
    mapped = []
    for w in cap_words:
        s, e = remap(w["start"] - start, segs), remap(w["end"] - start, segs)
        if s is not None and e is not None and e > s:
            mapped.append({"start": s, "end": e, "word": w["word"]})

    src_w, src_h = _probe_size(video_path)
    lay, cap_y = layout_filter(rcfg, src_w, src_h)
    (out_dir / "captions.ass").write_text(build_ass(mapped, h.get("hook_text", ""), rcfg, cap_y),
                                          encoding="utf-8")

    n = len(segs)
    fc = []
    if n == 1:
        fc.append("[0:v]setpts=PTS-STARTPTS[vc];[0:a]asetpts=PTS-STARTPTS[ac]")
    else:
        fc.append(f"[0:v]split={n}" + "".join(f"[vs{i}]" for i in range(n)))
        fc.append(f"[0:a]asplit={n}" + "".join(f"[as{i}]" for i in range(n)))
        for i, (a, b) in enumerate(segs):
            fc.append(f"[vs{i}]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]")
            fc.append(f"[as{i}]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}]")
        fc.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
    fc.append(lay)
    fc.append("[vl]fps=30,subtitles=captions.ass[vout]")
    fc.append("[ac]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")

    out = out_dir / "clip.mp4"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(Path(video_path).resolve()),
           "-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", rcfg["preset"], "-crf", str(rcfg["crf"]),
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
           "clip.mp4"]
    res = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou:\n{res.stderr[-3000:]}")
    kept = sum(b - a for a, b in segs)
    print(f"[render] {out}  ({end - start:.1f}s -> {kept:.1f}s, {n} segmento(s))")
    return out
