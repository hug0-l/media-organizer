from __future__ import annotations

import re
from datetime import date

from ..models import EpisodeRef, SeriesRef
from ..state import State
from .base import Provider, ProviderError, TTL_DETAIL, TTL_SEARCH

API = "https://api4.thetvdb.com/v4"


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


def _sid(v) -> str | None:
    if v is None:
        return None
    s = str(v)
    m = re.search(r"(\d+)$", s)
    return m.group(1) if m else None


class TVDBProvider(Provider):
    name = "tvdb"

    def __init__(self, state: State, index=None):
        super().__init__(state, index)
        self.key = self.require_key("MO_TVDB_KEY", "tvdb")
        self._token: str | None = None

    def _login(self) -> str:
        if self._token:
            return self._token
        data = self.http.post_json(f"{API}/login", {"apikey": self.key})
        token = ((data or {}).get("data") or {}).get("token")
        if not token:
            raise ProviderError("TVDB login failed; check MO_TVDB_KEY")
        self._token = token
        return token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._login()}"}

    def search_series(self, query: str, year: int | None = None) -> list[SeriesRef]:
        data = self.http.get_json(
            f"{API}/search", params={"query": query, "type": "series"},
            headers=self._headers(), ttl=TTL_SEARCH,
        )
        rows = (data or {}).get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("results") or []
        out = []
        for r in rows:
            sid = _sid(r.get("tvdb_id") or r.get("objectID") or r.get("id"))
            name = r.get("name") or r.get("title") or ""
            if not sid or not name:
                continue
            aliases = r.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            out.append(SeriesRef(
                id=f"tvdb:{sid}", name=name, year=_year(r.get("first_air_time") or r.get("year")),
                aliases=[a for a in aliases if a and a != name],
                popularity=float(r.get("score") or 0), source="tvdb", tvdb_id=int(sid), raw=r,
            ))
        return out

    def episodes(self, series_id: str) -> list[EpisodeRef]:
        sid = series_id.split(":")[-1]
        show = self.http.get_json(f"{API}/series/{sid}/extended", headers=self._headers(), ttl=TTL_DETAIL)
        show_data = (show or {}).get("data") or {}
        name = show_data.get("name") or ""
        series_year = _year(show_data.get("firstAired") or show_data.get("first_air_time"))
        out: list[EpisodeRef] = []
        url = f"{API}/series/{sid}/episodes/default"
        page = 0
        while page < 30:
            data = self.http.get_json(
                url, params={"page": page}, headers=self._headers(), ttl=TTL_DETAIL,
            )
            payload = (data or {}).get("data") or {}
            episodes = payload.get("episodes", []) or []
            for ep in episodes:
                if ep.get("number") is None:
                    continue
                out.append(EpisodeRef(
                    series_id=series_id, series_name=name,
                    season=ep.get("seasonNumber"), episode=ep.get("number"),
                    title=ep.get("name") or "", airdate=_date(ep.get("aired")),
                    absolute=ep.get("absoluteNumber"), series_year=series_year,
                    source="tvdb", raw=ep,
                ))
            links = ((data or {}).get("links") or {})
            if not links.get("next") or not episodes:
                break
            page += 1
        return out
