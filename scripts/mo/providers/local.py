from __future__ import annotations

from ..index import Index
from ..models import EpisodeRef, MovieRef, SeriesRef
from ..state import State
from .base import Provider


class LocalProvider(Provider):
    name = "local"

    def __init__(self, state: State, index: Index | None = None):
        super().__init__(state, index)
        self.idx = index or Index(state)

    def search_series(self, query: str, year: int | None = None) -> list[SeriesRef]:
        return self.idx.search_series(query, limit=15)

    def episodes(self, series_id: str) -> list[EpisodeRef]:
        return self.idx.episodes(series_id)

    def search_movies(self, query: str, year: int | None = None) -> list[MovieRef]:
        return self.idx.search_movies(query, year=year, limit=15)
