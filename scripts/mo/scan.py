from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .classify import (
    is_audio,
    is_clutter_dir,
    is_clutter_file,
    is_image,
    is_metadata,
    is_subtitle,
    is_video,
    should_ignore_dir,
)
from .models import MediaFile
from .parse import parse_media


def _iter_files(root: Path, recursive: bool) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            d = Path(dirpath)
            dirnames[:] = [n for n in dirnames if not should_ignore_dir(d / n) and not is_clutter_dir(d / n)]
            for name in filenames:
                yield d / name
    else:
        for p in root.iterdir():
            if p.is_file():
                yield p


def _derived(primary: Path, other: Path) -> bool:
    if other == primary or other.parent != primary.parent:
        return False
    a = primary.stem.lower()
    b = other.stem.lower()
    if len(b) < len(a) or not b.startswith(a):
        return False
    return len(b) == len(a) or not b[len(a)].isalnum()


def scan_paths(paths: Iterable[str | Path], recursive: bool = True) -> list[MediaFile]:
    roots = [Path(p).expanduser() for p in paths]
    for r in roots:
        if not r.exists():
            raise FileNotFoundError(f"path does not exist: {r}")

    files: list[Path] = []
    for r in roots:
        files.extend(_iter_files(r, recursive))
    # de-dupe
    seen: set[str] = set()
    unique: list[Path] = []
    for f in files:
        key = os.path.normcase(os.path.abspath(str(f)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)

    videos = [p for p in unique if is_video(p)]
    by_dir: dict[Path, list[Path]] = {}
    for v in videos:
        by_dir.setdefault(v.parent, []).append(v)

    result: list[MediaFile] = []
    for parent, vids in by_dir.items():
        siblings = [p for p in unique if p.parent == parent]
        for v in vids:
            sidecars = [
                str(s) for s in siblings
                if s != v and _derived(v, s) and (is_subtitle(s) or is_metadata(s) or is_image(s))
            ]
            try:
                st = v.stat()
                size, mtime = st.st_size, st.st_mtime
            except OSError:
                size, mtime = 0, 0.0
            mf = MediaFile(path=str(v), size=size, mtime=mtime, sidecars=sorted(sidecars))
            mf.parsed = parse_media(v)
            if is_clutter_file(v):
                mf.warnings.append("clutter/sample name")
            if mf.parsed.kind == "unknown":
                mf.warnings.append("could not parse media identity")
            result.append(mf)

    # standalone audio (music libraries)
    audio_files = [p for p in unique if is_audio(p)]
    for a in audio_files:
        try:
            st = a.stat()
            size, mtime = st.st_size, st.st_mtime
        except OSError:
            size, mtime = 0, 0.0
        mf = MediaFile(path=str(a), size=size, mtime=mtime, media_kind="audio")
        mf.parsed = parse_media(a)
        result.append(mf)

    result.sort(key=lambda m: m.path.lower())
    return result


def scan_summary(files: list[MediaFile]) -> dict:
    by_kind: dict[str, int] = {}
    warnings = 0
    sidecars = 0
    for f in files:
        k = f.parsed.kind if f.parsed else "unknown"
        by_kind[k] = by_kind.get(k, 0) + 1
        warnings += len(f.warnings)
        sidecars += len(f.sidecars)
    return {
        "files": len(files),
        "by_kind": by_kind,
        "sidecars": sidecars,
        "warnings": warnings,
    }
