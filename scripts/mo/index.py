from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import EpisodeRef, MovieRef, SeriesRef
from .state import State
from .util.text import normalize_name, similarity


def _norm(s: str) -> str:
    return normalize_name(s or "")


class Index:
    def __init__(self, state: State):
        self.state = state
        self.conn: sqlite3.Connection = state.conn

    # ------------------------------------------------------------------ build
    def build_from(self, path: str | Path, replace: bool = False) -> dict[str, int]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"index source not found: {p}")
        if replace:
            cur = self.conn.cursor()
            for table in ("episode", "series_alias", "series", "movie_alias", "movie"):
                cur.execute(f"DELETE FROM {table}")
            self.conn.commit()
        if p.suffix.lower() == ".json":
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        elif p.suffix.lower() == ".csv":
            data = self._parse_csv(p)
        else:
            raise ValueError("index source must be .json or .csv")
        return self.build_from_data(data)

    def build_from_data(self, data: dict) -> dict[str, int]:
        counts = {"series": 0, "episodes": 0, "movies": 0}
        for s in data.get("series", []):
            self.upsert_series(s)
            counts["series"] += 1
            counts["episodes"] += len(s.get("episodes", []) or [])
        for m in data.get("movies", []):
            self.upsert_movie(m)
            counts["movies"] += 1
        self.conn.commit()
        return counts

    def _parse_csv(self, p: Path) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {"series": [], "movies": []}
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                typ = (row.get("type") or "series").strip().lower()
                aliases = [a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()]
                if typ == "movie":
                    out["movies"].append({
                        "name": row.get("name"),
                        "year": int(row["year"]) if row.get("year") else None,
                        "tmdb_id": int(row["tmdb_id"]) if row.get("tmdb_id") else None,
                        "imdb_id": row.get("imdb_id") or None,
                        "aliases": aliases,
                        "popularity": float(row.get("popularity") or 0),
                    })
                else:
                    eps = []
                    if row.get("episodes"):
                        try:
                            eps = json.loads(row["episodes"])
                        except Exception:
                            eps = []
                    out["series"].append({
                        "name": row.get("name"),
                        "year": int(row["year"]) if row.get("year") else None,
                        "tmdb_id": int(row["tmdb_id"]) if row.get("tmdb_id") else None,
                        "tvdb_id": int(row["tvdb_id"]) if row.get("tvdb_id") else None,
                        "imdb_id": row.get("imdb_id") or None,
                        "aliases": aliases,
                        "popularity": float(row.get("popularity") or 0),
                        "episodes": eps,
                    })
        return out

    # ------------------------------------------------------------------ upsert
    def upsert_series(self, s: dict) -> str:
        name = s.get("name") or s.get("title") or ""
        if not name:
            raise ValueError("series entry missing name")
        tmdb = s.get("tmdb_id")
        sid = str(s.get("id") or (f"tmdb:{tmdb}" if tmdb else f"local:{_norm(name)}:{s.get('year') or ''}"))
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO series(id,tmdb_id,tvdb_id,imdb_id,name,name_norm,year,popularity,source,raw)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET tmdb_id=excluded.tmdb_id,tvdb_id=excluded.tvdb_id,
               imdb_id=excluded.imdb_id,name=excluded.name,name_norm=excluded.name_norm,
               year=excluded.year,popularity=excluded.popularity,source=excluded.source,raw=excluded.raw""",
            (sid, tmdb, s.get("tvdb_id"), s.get("imdb_id"), name, _norm(name),
             s.get("year"), float(s.get("popularity") or 0), s.get("source") or "local",
             json.dumps(s, ensure_ascii=False)),
        )
        cur.execute("DELETE FROM series_alias WHERE series_id=?", (sid,))
        aliases = [a for a in (s.get("aliases") or []) if a and a != name]
        for a in aliases:
            cur.execute("INSERT INTO series_alias(series_id,alias,alias_norm) VALUES(?,?,?)", (sid, a, _norm(a)))
        for ep in s.get("episodes", []) or []:
            cur.execute(
                """INSERT INTO episode(series_id,season,episode,title,airdate,absolute,special,raw)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(series_id,season,episode) DO UPDATE SET title=excluded.title,
                   airdate=excluded.airdate,absolute=excluded.absolute,special=excluded.special,raw=excluded.raw""",
                (sid, ep.get("season"), ep.get("episode"), ep.get("title") or "",
                 ep.get("airdate") or "", ep.get("absolute"), ep.get("special"),
                 json.dumps(ep, ensure_ascii=False)),
            )
        return sid

    def upsert_movie(self, m: dict) -> str:
        name = m.get("name") or m.get("title") or ""
        if not name:
            raise ValueError("movie entry missing name")
        tmdb = m.get("tmdb_id")
        mid = str(m.get("id") or (f"tmdb:{tmdb}" if tmdb else f"local:{_norm(name)}:{m.get('year') or ''}"))
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO movie(id,tmdb_id,imdb_id,name,name_norm,year,popularity,source,raw)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET tmdb_id=excluded.tmdb_id,imdb_id=excluded.imdb_id,
               name=excluded.name,name_norm=excluded.name_norm,year=excluded.year,
               popularity=excluded.popularity,source=excluded.source,raw=excluded.raw""",
            (mid, tmdb, m.get("imdb_id"), name, _norm(name), m.get("year"),
             float(m.get("popularity") or 0), m.get("source") or "local",
             json.dumps(m, ensure_ascii=False)),
        )
        cur.execute("DELETE FROM movie_alias WHERE movie_id=?", (mid,))
        for a in [a for a in (m.get("aliases") or []) if a and a != name]:
            cur.execute("INSERT INTO movie_alias(movie_id,alias,alias_norm) VALUES(?,?,?)", (mid, a, _norm(a)))
        return mid

    # ------------------------------------------------------------------ search
    def search_series(self, query: str, limit: int = 10) -> list[SeriesRef]:
        q = _norm(query)
        if not q:
            return []
        cur = self.conn.cursor()
        ids = {r[0] for r in cur.execute(
            "SELECT id FROM series WHERE name_norm LIKE ? OR name_norm LIKE ?",
            (f"%{q}%", f"%{q.replace(' ', '%')}%"),
        )}
        if not ids:
            ids = {r[0] for r in cur.execute(
                "SELECT series_id FROM series_alias WHERE alias_norm LIKE ?", (f"%{q}%",)
            )}
        if not ids:
            # token OR fallback over all rows
            tokens = q.split()
            if tokens:
                where = " OR ".join("name_norm LIKE ?" for _ in tokens)
                ids = {r[0] for r in cur.execute(f"SELECT id FROM series WHERE {where}", [f"%{t}%" for t in tokens])}
        out: list[tuple[float, SeriesRef]] = []
        for sid in ids:
            row = cur.execute("SELECT * FROM series WHERE id=?", (sid,)).fetchone()
            if not row:
                continue
            aliases = [r[0] for r in cur.execute("SELECT alias FROM series_alias WHERE series_id=?", (sid,))]
            names = [row["name"], *aliases]
            score = max(similarity(query, n) for n in names)
            if q in row["name_norm"]:
                score = max(score, 0.85)
            out.append((score, SeriesRef(
                id=row["id"], name=row["name"], year=row["year"], aliases=aliases,
                popularity=row["popularity"] or 0, source=row["source"] or "local",
                tmdb_id=row["tmdb_id"], tvdb_id=row["tvdb_id"], imdb_id=row["imdb_id"],
            )))
        out.sort(key=lambda x: (x[0], x[1].popularity, x[1].year or 0), reverse=True)
        return [s for _, s in out[:limit]]

    def search_movies(self, query: str, year: int | None = None, limit: int = 10) -> list[MovieRef]:
        q = _norm(query)
        if not q:
            return []
        cur = self.conn.cursor()
        ids = {r[0] for r in cur.execute(
            "SELECT id FROM movie WHERE name_norm LIKE ? OR name_norm LIKE ?",
            (f"%{q}%", f"%{q.replace(' ', '%')}%"),
        )}
        if not ids:
            ids = {r[0] for r in cur.execute(
                "SELECT movie_id FROM movie_alias WHERE alias_norm LIKE ?", (f"%{q}%",)
            )}
        out: list[tuple[float, MovieRef]] = []
        for mid in ids:
            row = cur.execute("SELECT * FROM movie WHERE id=?", (mid,)).fetchone()
            if not row:
                continue
            aliases = [r[0] for r in cur.execute("SELECT alias FROM movie_alias WHERE movie_id=?", (mid,))]
            names = [row["name"], *aliases]
            score = max(similarity(query, n) for n in names)
            if q in row["name_norm"]:
                score = max(score, 0.85)
            if year and row["year"] == year:
                score += 0.15
            out.append((score, MovieRef(
                id=row["id"], name=row["name"], year=row["year"], aliases=aliases,
                popularity=row["popularity"] or 0, source=row["source"] or "local",
                tmdb_id=row["tmdb_id"], imdb_id=row["imdb_id"],
            )))
        out.sort(key=lambda x: (x[0], x[1].popularity, x[1].year or 0), reverse=True)
        return [m for _, m in out[:limit]]

    def episodes(self, series_id: str) -> list[EpisodeRef]:
        cur = self.conn.cursor()
        row = cur.execute("SELECT name,year FROM series WHERE id=?", (series_id,)).fetchone()
        series_name = row["name"] if row else series_id
        series_year = row["year"] if row else None
        out = []
        for r in cur.execute(
            "SELECT season,episode,title,airdate,absolute,special FROM episode WHERE series_id=? ORDER BY season,episode",
            (series_id,),
        ):
            out.append(EpisodeRef(
                series_id=series_id, series_name=series_name, season=r["season"],
                episode=r["episode"], title=r["title"] or "",
                airdate=_parse_date(r["airdate"]), absolute=r["absolute"],
                special=r["special"], series_year=series_year, source="local",
            ))
        return out

    def stats(self) -> dict:
        cur = self.conn.cursor()
        def one(q):
            r = cur.execute(q).fetchone()
            return r[0] if r else 0
        return {
            "series": one("SELECT COUNT(*) FROM series"),
            "episodes": one("SELECT COUNT(*) FROM episode"),
            "movies": one("SELECT COUNT(*) FROM movie"),
            "aliases": one("SELECT COUNT(*) FROM series_alias") + one("SELECT COUNT(*) FROM movie_alias"),
        }


def _parse_date(s: str | None):
    if not s:
        return None
    from datetime import date
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            from datetime import datetime
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None
