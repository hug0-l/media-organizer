from __future__ import annotations

from pathlib import Path

from .models import MediaFile
from .parse import ParsedMedia, is_anime_path, media_type


VIDEO_EXT = {
    ".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
    ".mpg", ".mpeg", ".webm", ".vob", ".iso", ".3gp",
}
AUDIO_EXT = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".alac", ".ape", ".dsf", ".dff"}
SUB_EXT = {".srt", ".ass", ".ssa", ".sub", ".vtt", ".smi", ".sami", ".idx", ".sup"}
META_EXT = {".nfo", ".txt", ".xml", ".json"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tbn"}

IGNORE_DIRS = {
    "$recycle.bin", "system volume information", "node_modules", ".git", ".svn",
    ".media-organizer", "@eadir", "#recycle", "lost+found", "windows", "program files",
    "program files (x86)", "programdata", "appdata",
}
CLUTTER_DIRS = {
    "sample", "samples", "extras", "extra", "featurettes", "behind the scenes",
    "behindthescenes", "trailers", "subs", "subtitles", "proof", "screens",
}
CLUTTER_WORDS = {"sample", "trailer", "featurette", "proof", "screenshot"}


def is_video(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXT


def is_audio(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXT


def is_subtitle(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUB_EXT


def is_metadata(path: str | Path) -> bool:
    return Path(path).suffix.lower() in META_EXT


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXT


def should_ignore_dir(path: Path) -> bool:
    name = path.name.lower()
    if name in IGNORE_DIRS:
        return True
    if name.startswith(".") and name not in {".", ".."}:
        return True
    return False


def is_clutter_dir(path: Path) -> bool:
    return path.name.lower() in CLUTTER_DIRS


def is_clutter_file(path: Path) -> bool:
    low = path.stem.lower()
    return any(w in low for w in CLUTTER_WORDS)


def detect_kind(mf: MediaFile, mode_hint: str | None = None) -> str:
    """Return tv | anime | movie | music | unknown."""
    if mode_hint and mode_hint != "auto":
        return mode_hint
    mt = media_type(mf.path)
    if mt == "audio":
        return "music"
    parsed: ParsedMedia | None = mf.parsed
    if parsed is None:
        return "unknown"
    if parsed.kind == "tv":
        return "anime" if is_anime_path(mf.path, parsed) else "tv"
    if parsed.kind == "movie":
        return "movie"
    if parsed.kind == "music":
        return "music"
    return "unknown"
