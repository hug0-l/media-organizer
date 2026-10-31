from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

APP_NAME = "media-organizer"


def _state_base(root: str | Path | None) -> Path:
    if root:
        r = Path(root).expanduser()
        if r.is_file():
            r = r.parent
        try:
            probe = r / ".media-organizer"
            probe.mkdir(parents=True, exist_ok=True)
            test = probe / ".write-test"
            test.write_text("ok", encoding="utf-8")
            test.unlink(missing_ok=True)
            return probe
        except OSError:
            pass
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    if base:
        p = Path(base) / APP_NAME
    else:
        p = Path.home() / f".{APP_NAME}"
    p.mkdir(parents=True, exist_ok=True)
    return p


class State:
    def __init__(self, root: str | Path | None = None, state_dir: str | Path | None = None):
        self.base = Path(state_dir).expanduser() if state_dir else _state_base(root)
        self.base.mkdir(parents=True, exist_ok=True)
        self.plans = self.base / "plans"
        self.journals = self.base / "journals"
        self.backups = self.base / "backups"
        self.cache = self.base / "cache"
        for d in (self.plans, self.journals, self.backups, self.cache):
            d.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base / "mo.sqlite"
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        self.config = self._load_config()

    def _init_db(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS series (
                id TEXT PRIMARY KEY,
                tmdb_id INTEGER,
                tvdb_id INTEGER,
                imdb_id TEXT,
                name TEXT NOT NULL,
                name_norm TEXT NOT NULL,
                year INTEGER,
                popularity REAL DEFAULT 0,
                source TEXT DEFAULT 'local',
                raw TEXT
            );
            CREATE TABLE IF NOT EXISTS series_alias (
                series_id TEXT NOT NULL,
                alias TEXT NOT NULL,
                alias_norm TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_series_alias ON series_alias(series_id);
            CREATE TABLE IF NOT EXISTS episode (
                series_id TEXT NOT NULL,
                season INTEGER,
                episode INTEGER,
                title TEXT,
                airdate TEXT,
                absolute INTEGER,
                special INTEGER,
                raw TEXT,
                PRIMARY KEY (series_id, season, episode)
            );
            CREATE TABLE IF NOT EXISTS movie (
                id TEXT PRIMARY KEY,
                tmdb_id INTEGER,
                imdb_id TEXT,
                name TEXT NOT NULL,
                name_norm TEXT NOT NULL,
                year INTEGER,
                popularity REAL DEFAULT 0,
                source TEXT DEFAULT 'local',
                raw TEXT
            );
            CREATE TABLE IF NOT EXISTS movie_alias (
                movie_id TEXT NOT NULL,
                alias TEXT NOT NULL,
                alias_norm TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_movie_alias ON movie_alias(movie_id);
            CREATE TABLE IF NOT EXISTS provider_cache (
                key TEXT PRIMARY KEY,
                fetched_at REAL NOT NULL,
                etag TEXT,
                payload TEXT
            );
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                plan_id TEXT,
                src TEXT,
                dst TEXT,
                op TEXT,
                result TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        self.conn.commit()

    def _load_config(self) -> dict[str, Any]:
        for name in ("config.json", "config.toml"):
            p = self.base / name
            if not p.exists():
                continue
            try:
                if p.suffix == ".json":
                    return json.loads(p.read_text(encoding="utf-8"))
                import tomllib
                return tomllib.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def write_plan(self, plan: dict[str, Any]) -> Path:
        pid = plan["plan_id"].replace(":", "-")
        path = self.plans / f"{pid}.json"
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_plan(self, path: str | Path) -> dict[str, Any]:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def journal_path(self, stamp: str | None = None) -> Path:
        stamp = stamp or time.strftime("%Y-%m-%dT%H-%M-%S")
        return self.journals / f"{stamp}.jsonl"

    def backup_dir(self, plan_id: str) -> Path:
        d = self.backups / plan_id.replace(":", "-")
        d.mkdir(parents=True, exist_ok=True)
        return d


def plan_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def envelope_hash(plan: dict[str, Any]) -> str:
    payload = {
        "root": plan.get("root"),
        "kind": plan.get("kind"),
        "options": plan.get("options"),
        "items": [
            {k: i.get(k) for k in ("src", "dst", "status", "candidate", "sidecars", "subtitle")}
            for i in plan.get("items", [])
        ],
    }
    return plan_hash(payload)
