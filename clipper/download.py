"""Obter o vídeo: URL (YouTube, Twitch, Kick... via yt-dlp) ou ficheiro local."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def safe_id(source_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", source_id)


def source_dir(workdir: str, source_id: str) -> Path:
    d = Path(workdir) / "sources" / safe_id(source_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch(url_or_path: str, cfg: dict) -> dict:
    """Devolve metadados da fonte + caminho do vídeo. Reaproveita downloads anteriores."""
    p = Path(url_or_path).expanduser()
    if p.exists():
        p = p.resolve()
        sid = "local:" + hashlib.sha1(str(p).encode()).hexdigest()[:12]
        meta = {"source_id": sid, "url": str(p), "title": p.stem, "channel": "local",
                "duration": _probe_duration(p), "video_path": str(p)}
        _save(cfg, meta)
        return meta

    import yt_dlp  # import tardio: não é preciso para ficheiros locais

    # 1) só metadados, para saber o id e evitar descarregar duas vezes
    info = _info(url_or_path)
    sid = f"{info['extractor_key'].lower()}:{info['id']}"
    d = source_dir(cfg["workdir"], sid)
    cached = d / "source.json"
    if cached.exists():
        meta = json.loads(cached.read_text(encoding="utf-8"))
        if Path(meta["video_path"]).exists():
            return meta

    h = cfg["download"]["max_height"]
    opts = {
        "format": f"bv*[height<={h}]+ba/b[height<={h}]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(d / "video.%(ext)s"),
        "quiet": False,
        "noprogress": False,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url_or_path, download=True)
    reqs = info.get("requested_downloads") or []
    video_path = reqs[0]["filepath"] if reqs else str(next(d.glob("video.*")))
    meta = {
        "source_id": sid,
        "url": url_or_path,
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "duration": info.get("duration") or _probe_duration(Path(video_path)),
        "upload_date": info.get("upload_date"),
        "video_path": video_path,
    }
    _save(cfg, meta)
    return meta


def _info(url: str) -> dict:
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
        return ydl.extract_info(url, download=False)


def probe_meta(url_or_path: str) -> dict:
    """Metadados sem descarregar (id, título, duração). Para ficheiros locais usa ffprobe."""
    p = Path(url_or_path).expanduser()
    if p.exists():
        p = p.resolve()
        return {"source_id": "local:" + hashlib.sha1(str(p).encode()).hexdigest()[:12], "url": str(p),
                "title": p.stem, "channel": "local", "duration": _probe_duration(p)}
    info = _info(url_or_path)
    return {"source_id": f"{info['extractor_key'].lower()}:{info['id']}", "url": url_or_path,
            "title": info.get("title"), "channel": info.get("channel") or info.get("uploader"),
            "duration": info.get("duration"), "is_live": info.get("is_live")}


def _save(cfg: dict, meta: dict) -> None:
    d = source_dir(cfg["workdir"], meta["source_id"])
    (d / "source.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def _probe_duration(p: Path) -> float:
    import subprocess
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
    return float(out)
