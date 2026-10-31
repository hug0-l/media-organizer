from __future__ import annotations

import os
import re
from pathlib import Path

WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

_INVALID_WINDOWS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TRAILING = re.compile(r"[ .]+$")


def is_windows() -> bool:
    return os.name == "nt"


def canonical(p: str | Path) -> Path:
    try:
        return Path(p).expanduser().resolve(strict=False)
    except Exception:
        return Path(os.path.abspath(os.path.expanduser(str(p))))


def is_relative_to(child: str | Path, parent: str | Path) -> bool:
    try:
        canonical(child).relative_to(canonical(parent))
        return True
    except ValueError:
        return False


def dangerous_root(p: str | Path) -> bool:
    """Reject filesystem roots, home roots and OS-owned trees."""
    path = canonical(p)
    s = str(path)
    if path.anchor and s.rstrip("\\/").lower() == path.anchor.rstrip("\\/").lower():
        return True
    home = Path.home().resolve()
    if path == home:
        return True
    if is_windows():
        low = s.lower()
        windows = os.environ.get("WINDIR", r"C:\Windows").lower()
        if low == windows or low.startswith(windows + "\\"):
            return True
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            base = os.environ.get(env)
            if base and (low == base.lower() or low.startswith(base.lower() + "\\")):
                return True
        if low.startswith("c:\\$recycle.bin") or low.startswith("c:\\system volume information"):
            return True
    return False


def sanitize_component(name: str, unixfs: bool = False) -> str:
    s = str(name or "").strip()
    if not unixfs:
        s = s.replace(":", " - ")
        s = _INVALID_WINDOWS.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _TRAILING.sub("", s)
    if not s:
        s = "_"
    stem = s.split(".")[0].upper()
    if not unixfs and stem in {x.upper() for x in WINDOWS_RESERVED}:
        s = "_" + s
    if is_windows() and not unixfs:
        if len(s) > 200:
            s = s[:200].rstrip(" .")
    return s


def sanitize_relpath(rel: str | Path, unixfs: bool = False) -> str:
    raw = str(rel).replace("\\", "/")
    parts = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("path traversal is not allowed")
        parts.append(sanitize_component(part, unixfs=unixfs))
    if not parts:
        raise ValueError("empty destination path")
    return "/".join(parts)


def resolve_destination(
    rendered: str,
    root: str | Path,
    output: str | Path | None = None,
    unixfs: bool = False,
    allow_absolute: bool = False,
) -> Path:
    """Turn a rendered format result into a safe absolute destination."""
    rendered = str(rendered or "").strip()
    if not rendered:
        raise ValueError("format expression produced an empty path")
    if "\x00" in rendered:
        raise ValueError("NUL byte in destination")

    p = Path(rendered)
    if p.is_absolute():
        dest = canonical(p)
        allowed = [canonical(root)]
        if output:
            allowed.append(canonical(output))
        if not allow_absolute and not any(is_relative_to(dest, a) for a in allowed):
            raise ValueError(f"absolute destination outside allowed roots: {dest}")
        return dest

    base = canonical(output) if output else canonical(root)
    rel = sanitize_relpath(rendered, unixfs=unixfs)
    dest = canonical(base / rel)
    if not is_relative_to(dest, base):
        raise ValueError(f"destination escapes base: {dest}")
    return dest


def case_key(p: str | Path) -> str:
    return os.path.normcase(str(canonical(p)))


def exists_case_insensitive(p: str | Path) -> bool:
    path = canonical(p)
    if path.exists():
        return True
    if not is_windows():
        return False
    parent = path.parent
    if not parent.exists():
        return False
    target = path.name.casefold()
    try:
        return any(c.name.casefold() == target for c in parent.iterdir())
    except OSError:
        return False


def unique_indexed_path(dest: str | Path, limit: int = 100) -> Path:
    path = canonical(dest)
    if not exists_case_insensitive(path):
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, limit + 1):
        cand = path.with_name(f"{stem}.{i}{suffix}")
        if not exists_case_insensitive(cand):
            return cand
    raise FileExistsError(f"no available index name for {path}")


def ensure_parent(p: str | Path) -> None:
    canonical(p).parent.mkdir(parents=True, exist_ok=True)
