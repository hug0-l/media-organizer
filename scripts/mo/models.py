from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class SeriesRef:
    id: str
    name: str
    year: int | None = None
    aliases: list[str] = field(default_factory=list)
    popularity: float = 0.0
    source: str = "local"
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ids(self) -> dict[str, Any]:
        return {
            "tmdb": self.tmdb_id,
            "tvdb": self.tvdb_id,
            "imdb": self.imdb_id,
        }


@dataclass
class EpisodeRef:
    series_id: str
    series_name: str
    season: int | None
    episode: int | None
    title: str = ""
    airdate: date | None = None
    absolute: int | None = None
    special: int | None = None
    series_year: int | None = None
    source: str = "local"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MovieRef:
    id: str
    name: str
    year: int | None = None
    aliases: list[str] = field(default_factory=list)
    popularity: float = 0.0
    source: str = "local"
    tmdb_id: int | None = None
    imdb_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MusicRef:
    id: str
    artist: str = ""
    album_artist: str = ""
    album: str = ""
    title: str = ""
    track: int | None = None
    year: int | None = None
    source: str = "tags"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchResult:
    file: Any
    candidate: Any
    confidence: float
    reasons: list[str] = field(default_factory=list)
    kind: str = "tv"


@dataclass
class MediaFile:
    path: str
    size: int = 0
    mtime: float = 0.0
    media_kind: str = "video"
    parsed: Any = None
    sidecars: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "media_kind": self.media_kind,
            "sidecars": self.sidecars,
            "warnings": self.warnings,
            "parsed": self.parsed.to_dict() if self.parsed else None,
        }
