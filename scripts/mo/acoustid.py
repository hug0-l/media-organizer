from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.acoustid.org/v2/lookup"


def fpcalc_path() -> str | None:
    exe = os.environ.get("MO_FPCALC") or "fpcalc"
    return shutil.which(exe)


def fingerprint(path: str | Path) -> dict | None:
    exe = fpcalc_path()
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except Exception:
        return None


def lookup(fp: str, duration: float, key: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "client": key, "meta": "recordings+releases+releasegroups",
        "duration": int(duration), "fingerprint": fp,
    })
    req = urllib.request.Request(
        f"{API}?{params}",
        headers={"User-Agent": "media-organizer/0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    if data.get("status") != "ok":
        return []
    return data.get("results") or []


def enrich_tags(tags: dict[str, str], path: str | Path, state) -> dict[str, str]:
    """Optionally fill missing music tags using AcoustID + fpcalc."""
    key = os.environ.get("MO_ACOUSTID_KEY") or (state.config.get("keys", {}) or {}).get("acoustid")
    if not key or tags.get("artist") and tags.get("title"):
        return tags
    fp = fingerprint(path)
    if not fp or not fp.get("fingerprint"):
        return tags
    results = lookup(fp["fingerprint"], fp.get("duration", 0), key)
    if not results:
        return tags
    recs = (results[0].get("recordings") or [])
    if not recs:
        return tags
    rec = recs[0]
    out = dict(tags)
    if not out.get("title") and rec.get("title"):
        out["title"] = rec["title"]
    artists = rec.get("artists") or []
    if not out.get("artist") and artists:
        out["artist"] = artists[0].get("name", "")
    releases = rec.get("releases") or []
    if releases:
        if not out.get("album") and releases[0].get("title"):
            out["album"] = releases[0]["title"]
    return out
