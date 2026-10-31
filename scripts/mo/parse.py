from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

from .util.text import (
    RELEASE_WORDS,
    clean_release_words,
    extract_year,
    find_years,
    has_subtitle_tag,
    normalize_name,
    similarity,
    subtitle_language_tag,
)

# Ordered: specific -> generic. Each returns (season, [episodes], absolute, span).
_SXXEYY = re.compile(
    r"(?i)(?<![\w])s(\d{1,4})[ ._-]*e(\d{2,3})(?:(?:-+[ ._-]*e?|e)(\d{2,4}))?"
)
_SXX_EYY = re.compile(r"(?i)(?<![\w])s(\d{1,4})[ ._-]+e(\d{2,3})")
_NXNN = re.compile(r"(?<![\w])(\d{1,2})x(\d{2,3})(?:-(\d{1,2})x(\d{2,3}))?")
_SEASON_EPISODE = re.compile(
    r"(?i)(?<![\w])season[ ._-]?(\d{1,2})[ ._-]*(?:episode|ep|e)[ ._-]?(\d{1,4})"
)
_EPISODE_ONLY = re.compile(
    r"(?i)(?<![\w])(?:episode|ep)[ ._-]?(\d{1,4})(?![\w])"
)
_E_ONLY = re.compile(r"(?<![\w])e(\d{1,3})(?:v\d)?(?![\w])")
_NN_DOT_NN = re.compile(r"(?<![\w])(\d{1,2})[ .](\d{2})(?![\w])")
_DASH_ABSOLUTE = re.compile(r"(?<![\w])[-–—]\s*(\d{1,3})(?:v\d)?(?=[\s\[\]\(]|$)")
_BRACKET_ABSOLUTE = re.compile(r"[\[\(](\d{1,3})(?:v\d)?[\])]")
_DATE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-. _](\d{1,2})[-. _](\d{1,2})(?!\d)"
)
_MOVIE_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_LEADING_GROUP = re.compile(r"^\s*\[([^\]]{2,40})\]\s*")
_TRAILING_GROUP = re.compile(r"[- .]([A-Z0-9][A-Z0-9._-]{1,24})\s*$")
_BRACKETS = re.compile(r"[\[\(\{][^\]\)\}]*[\]\)\}]")
_CLEAN_SEP = re.compile(r"[._]+")
_SPACES = re.compile(r"\s+")

_VIDEO_EXT = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".flv", ".ts", ".m2ts", ".mpg", ".mpeg", ".webm", ".vob", ".iso", ".3gp"}
_AUDIO_EXT = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".alac", ".ape", ".dsf", ".dff"}
_SUB_EXT = {".srt", ".ass", ".ssa", ".sub", ".vtt", ".smi", ".sami", ".idx", ".sup"}
_META_EXT = {".nfo", ".txt", ".xml", ".json"}
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tbn"}

_TAG_RES = {
    "resolution": re.compile(r"(?i)(?<![\w])(2160p|1080p|1080i|720p|576p|480p|4k|uhd|8k)(?![\w])"),
    "source": re.compile(r"(?i)(?<![\w])(bluray|blu-ray|bdrip|brrip|bdremux|remux|webrip|web-dl|webdl|web|hdtv|pdtv|dvdrip|dvd|dvdscr|hdcam|cam|ts|tc|r5|screener|scr|hdrip)(?![\w])"),
    "codec": re.compile(r"(?i)(?<![\w])(x264|x265|h264|h265|hevc|avc|xvid|divx|vp9|av1)(?![\w])"),
    "audio": re.compile(r"(?i)(?<![\w])(aac|ac3|eac3|dts(?:-hd)?|truehd|atmos|ddp?5[ .]?1|dd5[ .]?1|flac|mp3|opus)(?![\w])"),
    "hdr": re.compile(r"(?i)(?<![\w])(hdr10\+?|hdr|dolby[ .]?vision|dv)(?![\w])"),
    "bit_depth": re.compile(r"(?i)(?<![\w])(8bit|10bit|12bit)(?![\w])"),
}
_EDITION = re.compile(r"(?i)(?<![\w])(extended|uncut|remastered|director'?s cut|theatrical|imax)(?![\w])")
_YEAR_PAREN = re.compile(r"[\[\(]((?:19|20)\d{2})[\]\)]")
_YEAR_ANY = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


@dataclass
class ParsedMedia:
    kind: str = "unknown"  # tv | movie | music | unknown
    is_anime: bool = False
    title: str = ""
    year: int | None = None
    season: int | None = None
    episodes: list[int] = field(default_factory=list)
    absolute: int | None = None
    air_date: date | None = None
    group: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    edition: str | None = None
    raw: str = ""
    confidence: float = 0.0
    pattern: str | None = None

    @property
    def is_multi(self) -> bool:
        return len(self.episodes) > 1

    @property
    def season_episode(self) -> tuple[int, int] | None:
        if self.season is not None and self.episodes:
            return self.season, self.episodes[0]
        return None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "is_anime": self.is_anime,
            "title": self.title,
            "year": self.year,
            "season": self.season,
            "episodes": self.episodes,
            "absolute": self.absolute,
            "air_date": self.air_date.isoformat() if self.air_date else None,
            "group": self.group,
            "tags": self.tags,
            "edition": self.edition,
            "confidence": round(self.confidence, 3),
            "pattern": self.pattern,
        }


def media_type(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _AUDIO_EXT:
        return "audio"
    if ext in _SUB_EXT:
        return "subtitle"
    if ext in _META_EXT:
        return "metadata"
    if ext in _IMAGE_EXT:
        return "image"
    return "other"


def _expand_range(start: int, end: int) -> list[int]:
    if end <= start:
        return [start, end]
    if end - start <= 20:
        return list(range(start, end + 1))
    return [start, end]


def _find_date(s: str) -> date | None:
    for m in _DATE.finditer(s):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if 1900 <= d.year <= 2100:
            return d
    return None


def _find_episode(s: str) -> tuple[int | None, list[int], int | None, str, int, int] | None:
    """Return (season, episodes, absolute, pattern, start, end)."""
    m = _SXXEYY.search(s)
    if m:
        season = int(m.group(1))
        e1 = int(m.group(2))
        eps = [e1]
        if m.group(3):
            e2 = int(m.group(3))
            eps = _expand_range(e1, e2)
        if 0 <= season <= 300 and all(0 < e <= 3000 for e in eps):
            return season, eps, None, "sxxeyy", m.start(), m.end()

    m = _NXNN.search(s)
    if m:
        season, e1 = int(m.group(1)), int(m.group(2))
        eps = [e1]
        if m.group(3) and m.group(4):
            eps = _expand_range(e1, int(m.group(4)))
        if 0 < season <= 30 and all(0 < e <= 3000 for e in eps):
            return season, eps, None, "nxnn", m.start(), m.end()

    m = _SEASON_EPISODE.search(s)
    if m:
        season, ep = int(m.group(1)), int(m.group(2))
        if 0 <= season <= 300 and 0 < ep <= 3000:
            return season, [ep], None, "season-episode", m.start(), m.end()

    m = _SXX_EYY.search(s)
    if m:
        season, ep = int(m.group(1)), int(m.group(2))
        if 0 <= season <= 300 and 0 < ep <= 3000:
            return season, [ep], None, "sxx-eyy", m.start(), m.end()

    m = _EPISODE_ONLY.search(s)
    if m:
        ep = int(m.group(1))
        if 0 < ep <= 3000:
            return None, [ep], ep, "episode", m.start(), m.end()

    m = _E_ONLY.search(s)
    if m:
        ep = int(m.group(1))
        if 0 < ep <= 3000:
            return None, [ep], ep, "e-only", m.start(), m.end()

    m = _DASH_ABSOLUTE.search(s)
    if m:
        ep = int(m.group(1))
        if 0 < ep <= 3000:
            return None, [ep], ep, "dash-absolute", m.start(), m.end()

    m = _BRACKET_ABSOLUTE.search(s)
    if m:
        ep = int(m.group(1))
        if 0 < ep <= 3000:
            return None, [ep], ep, "bracket-absolute", m.start(), m.end()

    m = _NN_DOT_NN.search(s)
    if m:
        season, ep = int(m.group(1)), int(m.group(2))
        # avoid quality/audio false positives
        if 0 < season <= 30 and 0 < ep <= 99 and not re.search(r"(?i)(?:2160|1080|720|480)p", m.group(0)):
            return season, [ep], None, "nn.nn", m.start(), m.end()

    return None


def _extract_tags(s: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for key, rx in _TAG_RES.items():
        m = rx.search(s)
        if m:
            tags[key] = m.group(1).lower()
    m = _EDITION.search(s)
    if m:
        tags["edition"] = m.group(1).lower()
    return tags


def _extract_group(base: str) -> tuple[str | None, str]:
    m = _LEADING_GROUP.match(base)
    if m:
        return m.group(1).strip(), base[m.end():]
    m = _TRAILING_GROUP.search(base)
    if m:
        token = m.group(1)
        low = token.lower()
        prefix = base[: m.start()].lower()
        # release groups are usually uppercase / mixed alnum and not a year,
        # and not the tail of a known source token such as WEB-DL / Blu-Ray
        source_tail = (
            (prefix.endswith("web") and low in {"dl", "rip"})
            or (prefix.endswith("blu") and low in {"ray", "rip"})
        )
        if (
            not re.fullmatch(r"(?:19|20)\d{2}", token)
            and any(c.isalpha() for c in token)
            and not source_tail
            and low not in {"dl", "ray", "rip", "hd", "uhd"}
            and low not in RELEASE_WORDS
        ):
            return token, base[: m.start()]
    return None, base


def _clean_title(s: str, strip_year: bool = False) -> str:
    s = _BRACKETS.sub(" ", s)
    s = _CLEAN_SEP.sub(" ", s)
    s = _SPACES.sub(" ", s).strip(" -_")
    if strip_year:
        s = re.sub(r"(?<!\d)(?:19|20)\d{2}\s*$", "", s).strip(" -_")
    s = re.sub(r"\s+", " ", s).strip(" -_")
    return s


def _folder_hint(path: Path) -> str:
    parent = path.parent.name
    if re.fullmatch(r"(?i)(season|series|staffel|saison|temporada)[ ._-]?\d{0,2}", parent):
        return path.parent.parent.name if path.parent.parent != path.parent else ""
    if re.fullmatch(r"(?i)(tv shows|tv series|series|shows|anime|movies|films|downloads|complete)", parent):
        return ""
    return parent


def parse_media(path: str | Path, folder_hint: bool = True) -> ParsedMedia:
    p = Path(path)
    base = p.stem
    raw = base
    group, base_no_group = _extract_group(base)
    work = _CLEAN_SEP.sub(" ", base_no_group)
    work = _SPACES.sub(" ", work).strip()

    info = _find_episode(work)
    air = _find_date(work)
    tags = _extract_tags(work)
    edition = tags.get("edition")

    parsed = ParsedMedia(
        raw=raw,
        group=group,
        tags=tags,
        edition=edition,
        air_date=air,
    )

    if info is not None:
        season, eps, absolute, pattern, start, end = info
        title = _clean_title(work[:start], strip_year=True)
        if not title or len(normalize_name(title)) < 2:
            hint = _folder_hint(p) if folder_hint else ""
            title = _clean_title(hint, strip_year=True)
        if season is None:
            sm = re.fullmatch(
                r"(?i)(?:season|series|staffel|saison|temporada|s)[ ._-]?(\d{1,2})",
                p.parent.name,
            )
            if sm:
                season = int(sm.group(1))
                pattern = f"{pattern}+folder-season"
        parsed.kind = "tv"
        parsed.title = title
        parsed.season = season
        parsed.episodes = eps
        parsed.absolute = absolute
        parsed.pattern = pattern
        parsed.confidence = 0.9 if pattern in {"sxxeyy", "nxnn", "season-episode", "sxx-eyy"} else 0.75
        if air and pattern in {"dash-absolute", "episode", "e-only", "bracket-absolute"}:
            parsed.air_date = air
        # year in title context (e.g. Show 2019 S01E02)
        ys = find_years(work[:start])
        if ys:
            parsed.year = ys[-1]
        return parsed

    # bare episode number inside a Season folder: Series/Season 02/02.mkv
    sm = re.fullmatch(
        r"(?i)(?:season|series|staffel|saison|temporada|s)[ ._-]?(\d{1,2})",
        p.parent.name,
    )
    if sm and re.fullmatch(r"\d{1,4}(?:v\d)?", work):
        ep = int(re.sub(r"(?i)v\d+$", "", work))
        if 0 < ep <= 3000:
            parsed.kind = "tv"
            parsed.season = int(sm.group(1))
            parsed.episodes = [ep]
            parsed.absolute = ep
            parsed.title = _clean_title(p.parent.parent.name, strip_year=True)
            parsed.pattern = "folder-season"
            parsed.confidence = 0.72
            return parsed

    # date-based episodes (daily shows)
    if air is not None and ("daily" in work.lower() or re.search(r"(?i)\b(show|news|talk)\b", work)):
        parsed.kind = "tv"
        parsed.title = _clean_title(work[: _DATE.search(work).start()])
        parsed.air_date = air
        parsed.pattern = "date"
        parsed.confidence = 0.75
        return parsed

    # movie: Name (Year) or Name.Year
    m = _YEAR_PAREN.search(work) or _MOVIE_YEAR.search(work)
    if m:
        year = int(m.group(1))
        if 1888 <= year <= 2100:
            title = _clean_title(work[: m.start()])
            if not title:
                hint = _folder_hint(p) if folder_hint else ""
                title = _clean_title(hint)
            if title:
                parsed.kind = "movie"
                parsed.title = title
                parsed.year = year
                parsed.confidence = 0.75
                return parsed

    # folder (Year) hint
    if folder_hint:
        pm = _YEAR_PAREN.search(p.parent.name)
        if pm and 1888 <= int(pm.group(1)) <= 2100:
            parsed.kind = "movie"
            parsed.title = _clean_title(p.parent.name[: pm.start()])
            parsed.year = int(pm.group(1))
            parsed.confidence = 0.65
            return parsed

    # music
    if media_type(p) == "audio":
        parsed.kind = "music"
        parsed.title = _clean_title(work)
        parsed.confidence = 0.5
        return parsed

    parsed.title = _clean_title(work)
    return parsed


def is_anime_path(path: str | Path, parsed: ParsedMedia) -> bool:
    if parsed.kind != "tv":
        return False
    low = str(path).lower()
    if any(x in low for x in ("/anime/", "\\anime\\", "[subsplease]", "[horriblesubs]", "[erai-raws]")):
        return True
    if re.match(r"^\s*\[[^\]]+\]", Path(path).stem):
        return True
    # absolute-only numbering alone is not enough: talk shows use it too.
    return False


def parse_episode_identifier(name: str) -> tuple[int | None, list[int], int | None] | None:
    work = _CLEAN_SEP.sub(" ", name)
    info = _find_episode(work)
    if not info:
        return None
    season, eps, absolute, _pattern, _start, _end = info
    return season, eps, absolute
