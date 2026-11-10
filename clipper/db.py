"""Histórico local (SQLite) de fontes e clips, para evitar duplicados.

Na fase do dashboard migramos estas tabelas para Supabase.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,           -- ex: youtube:abc123, twitch:v123, local:...
    url TEXT, title TEXT, channel TEXT, duration REAL,
    status TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id),
    start REAL NOT NULL, "end" REAL NOT NULL,
    title TEXT, viral_score INTEGER, category TEXT,
    file TEXT, status TEXT DEFAULT 'rendered',  -- rendered | approved | uploaded | rejected
    youtube_id TEXT, created_at TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, workdir: str):
        self.conn = sqlite3.connect(Path(workdir) / "clipper.db")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def upsert_source(self, src: dict, status: str) -> None:
        self.conn.execute(
            """INSERT INTO sources (id, url, title, channel, duration, status, created_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status""",
            (src["source_id"], src.get("url"), src.get("title"), src.get("channel"),
             src.get("duration"), status, _now()),
        )
        self.conn.commit()

    def overlaps_existing(self, source_id: str, start: float, end: float,
                          min_overlap: float = 0.4) -> bool:
        """True se já existe um clip desta fonte que cobre >= min_overlap deste intervalo."""
        rows = self.conn.execute(
            'SELECT start, "end" FROM clips WHERE source_id=? AND status != "rejected"',
            (source_id,),
        ).fetchall()
        length = max(end - start, 1e-6)
        for r in rows:
            inter = min(end, r["end"]) - max(start, r["start"])
            if inter > 0 and inter / length >= min_overlap:
                return True
        return False

    def add_clip(self, source_id: str, h: dict, file: str) -> int:
        cur = self.conn.execute(
            """INSERT INTO clips (source_id, start, "end", title, viral_score, category, file, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (source_id, h["start"], h["end"], h["title"], h["viral_score"],
             h.get("category"), file, _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_clips(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT c.*, s.title AS source_title FROM clips c JOIN sources s ON s.id=c.source_id
               ORDER BY c.id DESC LIMIT ?""", (limit,)).fetchall()
