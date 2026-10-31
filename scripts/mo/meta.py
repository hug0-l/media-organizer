from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

META_KEY = "media-organizer.metadata"
NAME_KEY = "media-organizer.filename"


def _ads_write(path: Path, key: str, value: str) -> bool:
    if os.name != "nt":
        return False
    try:
        with open(f"{path}:{key}", "w", encoding="utf-8") as f:
            f.write(value)
        return True
    except OSError:
        return False


def _ads_read(path: Path, key: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        with open(f"{path}:{key}", "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def write_metadata(path: str | Path, data: dict, original_name: str | None = None) -> str:
    """Write metadata as xattr/ADS; fall back to a .mo.json sidecar."""
    p = Path(path)
    payload = json.dumps(data, ensure_ascii=False)
    if hasattr(os, "setxattr"):
        try:
            os.setxattr(p, f"user.{META_KEY}", payload.encode("utf-8"))
            if original_name:
                os.setxattr(p, f"user.{NAME_KEY}", original_name.encode("utf-8"))
            return "xattr"
        except OSError:
            pass
    if _ads_write(p, META_KEY, payload):
        if original_name:
            _ads_write(p, NAME_KEY, original_name)
        return "ads"
    side = p.with_suffix(p.suffix + ".mo.json")
    side.write_text(payload, encoding="utf-8")
    return "sidecar"


def read_metadata(path: str | Path) -> dict | None:
    p = Path(path)
    if hasattr(os, "getxattr"):
        try:
            return json.loads(os.getxattr(p, f"user.{META_KEY}").decode("utf-8"))
        except OSError:
            pass
    raw = _ads_read(p, META_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return None
    side = p.with_suffix(p.suffix + ".mo.json")
    if side.exists():
        try:
            return json.loads(side.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def write_nfo(path: str | Path, candidate: dict) -> Path:
    p = Path(path)
    nfo = p.with_suffix(".nfo")
    if candidate.get("type") == "episode":
        root = ET.Element("episodedetails")
        fields = {
            "title": candidate.get("title") or "",
            "season": candidate.get("season"),
            "episode": candidate.get("episode"),
            "plot": "",
            "aired": candidate.get("airdate") or "",
            "showtitle": candidate.get("series_name") or candidate.get("name") or "",
        }
    else:
        root = ET.Element("movie")
        fields = {
            "title": candidate.get("name") or "",
            "year": candidate.get("year"),
            "tmdbid": candidate.get("tmdb_id"),
            "imdbid": candidate.get("imdb_id"),
        }
    for k, v in fields.items():
        if v is None or v == "":
            continue
        el = ET.SubElement(root, k)
        el.text = str(v)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(nfo, encoding="utf-8", xml_declaration=True)
    return nfo


def download_artwork(dest: str | Path, candidate: dict) -> list[str]:
    """Best-effort poster/fanart download for TMDb movie results."""
    import urllib.request

    p = Path(dest)
    out = []
    base = "https://image.tmdb.org/t/p/original"
    for key, name in (("poster_path", "poster.jpg"), ("backdrop_path", "fanart.jpg")):
        rel = candidate.get(key)
        if not rel:
            continue
        try:
            req = urllib.request.Request(
                base + rel,
                headers={"User-Agent": "media-organizer/0.1"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            target = p.parent / name
            target.write_bytes(data)
            out.append(name)
        except Exception:
            continue
    return out


def apply_postprocess(dest: str | Path, candidate: dict, actions: list[str]) -> list[str]:
    done = []
    p = Path(dest)
    if not p.exists():
        return done
    if "nfo" in actions:
        try:
            write_nfo(p, candidate)
            done.append("nfo")
        except Exception:
            pass
    if "metadata" in actions:
        try:
            write_metadata(p, candidate, p.name)
            done.append("metadata")
        except Exception:
            pass
    if "artwork" in actions:
        try:
            done.extend(download_artwork(p, candidate))
        except Exception:
            pass
    return done
