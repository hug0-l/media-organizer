from __future__ import annotations

from datetime import date

from ..models import EpisodeRef, MovieRef, SeriesRef
from ..state import State
from .base import Provider, ProviderError, TTL_DETAIL, TTL_SEARCH

API = "https://api.themoviedb.org/3"


def _year(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(str(s)[:4])
    except ValueError:
        return None


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


class TMDbProvider(Provider):
    name = "tmdb"

    def __init__(self, state: State, index=None):
        super().__init__(state, index)
        self.key = self.require_key("MO_TMDB_KEY", "tmdb")
        self.lang = str(state.config.get("language", "en-US"))

    def _params(self, **kw):
        p = {"api_key": self.key, "language": self.lang}
        p.update({k: v for k, v in kw.items() if v is not None})
        return p

    def search_series(self, query: str, year: int | None = None) -> list[SeriesRef]:
        data = self.http.get_json(
            f"{API}/search/tv",
            params=self._params(query=query, first_air_date_year=year),
            ttl=TTL_SEARCH,
        )
        out = []
        for r in (data or {}).get("results", []) or []:
            sid = r.get("id")
            if not sid:
                continue
            out.append(SeriesRef(
                id=f"tmdb:{sid}", name=r.get("name") or r.get("original_name") or "",
                year=_year(r.get("first_air_date")),
                aliases=[a for a in [r.get("original_name")] if a and a != r.get("name")],
                popularity=float(r.get("popularity") or 0), source="tmdb", tmdb_id=sid,
                raw=r,
            ))
        return out

    def episodes(self, series_id: str) -> list[EpisodeRef]:
        sid = series_id.split(":")[-1]
        show = self.http.get_json(f"{API}/tv/{sid}", params=self._params(), ttl=TTL_DETAIL)
        if not show:
            return []
        name = show.get("name") or ""
        series_year = _year(show.get("first_air_date"))
        out: list[EpisodeRef] = []
        for season in show.get("seasons", []) or []:
            sn = season.get("season_number")
            if sn is None or int(season.get("episode_count") or 0) <= 0:
                continue
            detail = self.http.get_json(
                f"{API}/tv/{sid}/season/{sn}", params=self._params(), ttl=TTL_DETAIL
            )
            for ep in (detail or {}).get("episodes", []) or []:
                out.append(EpisodeRef(
                    series_id=series_id, series_name=name, season=ep.get("season_number", sn),
                    episode=ep.get("episode_number"), title=ep.get("name") or "",
                    airdate=_date(ep.get("air_date")), series_year=series_year,
                    source="tmdb", raw=ep,
                ))
        return out

    def search_movies(self, query: str, year: int | None = None) -> list[MovieRef]:
        data = self.http.get_json(
            f"{API}/search/movie",
            params=self._params(query=query, year=year),
            ttl=TTL_SEARCH,
        )
        out = []
        for r in (data or {}).get("results", []) or []:
            mid = r.get("id")
            if not mid:
                continue
            out.append(MovieRef(
                id=f"tmdb:{mid}", name=r.get("title") or r.get("original_title") or "",
                year=_year(r.get("release_date")),
                aliases=[a for a in [r.get("original_title")] if a and a != r.get("title")],
                popularity=float(r.get("popularity") or 0), source="tmdb", tmdb_id=mid, raw=r,
            ))
        return out
