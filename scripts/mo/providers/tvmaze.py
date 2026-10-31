from __future__ import annotations

import re
from datetime import date

from ..models import EpisodeRef, SeriesRef
from ..state import State
from .base import Provider, TTL_DETAIL, TTL_SEARCH

API = "https://api.tvmaze.com"


def _year(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"((?:19|20)\d{2})", str(s))
    return int(m.group(1)) if m else None


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


class TVmazeProvider(Provider):
    name = "tvmaze"

    def search_series(self, query: str, year: int | None = None) -> list[SeriesRef]:
        data = self.http.get_json(f"{API}/search/shows", params={"q": query}, ttl=TTL_SEARCH) or []
        out = []
        for row in data:
            show = row.get("show") or {}
            sid = show.get("id")
            if not sid:
                continue
            out.append(SeriesRef(
                id=f"tvmaze:{sid}", name=show.get("name") or "",
                year=_year(show.get("premiered")),
                aliases=[],
                popularity=float(row.get("score") or 0), source="tvmaze", raw=show,
            ))
        return out

    def episodes(self, series_id: str) -> list[EpisodeRef]:
        sid = series_id.split(":")[-1]
        show = self.http.get_json(f"{API}/shows/{sid}", ttl=TTL_DETAIL) or {}
        name = show.get("name") or ""
        series_year = _year(show.get("premiered"))
        data = self.http.get_json(f"{API}/shows/{sid}/episodes", ttl=TTL_DETAIL) or []
        out = []
        for ep in data:
            if ep.get("number") is None:
                continue
            out.append(EpisodeRef(
                series_id=series_id, series_name=name, season=ep.get("season"),
                episode=ep.get("number"), title=ep.get("name") or "",
                airdate=_date(ep.get("airdate")), series_year=series_year,
                source="tvmaze", raw=ep,
            ))
        return out
