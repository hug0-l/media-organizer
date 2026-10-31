from __future__ import annotations

import re

from ..models import MovieRef
from ..state import State
from .base import Provider, TTL_SEARCH

API = "https://www.omdbapi.com/"


def _year(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"((?:19|20)\d{2})", str(s))
    return int(m.group(1)) if m else None


class OMDbProvider(Provider):
    name = "omdb"

    def __init__(self, state: State, index=None):
        super().__init__(state, index)
        self.key = self.require_key("MO_OMDB_KEY", "omdb")

    def search_movies(self, query: str, year: int | None = None) -> list[MovieRef]:
        params = {"apikey": self.key, "s": query, "type": "movie"}
        if year:
            params["y"] = year
        data = self.http.get_json(API, params=params, ttl=TTL_SEARCH) or {}
        out = []
        for r in data.get("Search", []) or []:
            imdb = r.get("imdbID")
            if not imdb:
                continue
            out.append(MovieRef(
                id=imdb, name=r.get("Title") or "", year=_year(r.get("Year")),
                aliases=[], popularity=0.0, source="omdb", imdb_id=imdb, raw=r,
            ))
        if not out:
            # exact-title fallback
            exact = self.http.get_json(
                API, params={"apikey": self.key, "t": query, "y": year, "type": "movie"},
                ttl=TTL_SEARCH,
            ) or {}
            if exact.get("imdbID"):
                out.append(MovieRef(
                    id=exact["imdbID"], name=exact.get("Title") or "",
                    year=_year(exact.get("Year")), source="omdb",
                    imdb_id=exact["imdbID"], raw=exact,
                ))
        return out
