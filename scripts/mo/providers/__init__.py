from __future__ import annotations

from ..state import State
from .base import Provider, ProviderError
from .local import LocalProvider


def get_provider(name: str, state: State, index=None) -> Provider:
    name = (name or "local").strip().lower()
    if name in {"local", "anidb", "xattr", "file", "exif"}:
        return LocalProvider(state, index)
    if name in {"tmdb", "themoviedb", "themoviedb::tv"}:
        from .tmdb import TMDbProvider
        return TMDbProvider(state, index)
    if name in {"tvdb", "thetvdb"}:
        from .tvdb import TVDBProvider
        return TVDBProvider(state, index)
    if name in {"tvmaze"}:
        from .tvmaze import TVmazeProvider
        return TVmazeProvider(state, index)
    if name in {"omdb"}:
        from .omdb import OMDbProvider
        return OMDbProvider(state, index)
    raise ProviderError(f"unknown provider: {name}")


__all__ = ["Provider", "ProviderError", "get_provider", "LocalProvider"]
