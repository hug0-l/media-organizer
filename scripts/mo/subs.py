from __future__ import annotations

import re
from pathlib import Path

from .models import MediaFile
from .providers.base import ProviderError
from .providers.opensubtitles import OpenSubtitlesProvider, SubtitleResult, movie_hash
from .state import State, envelope_hash
from .util.paths import exists_case_insensitive, unique_indexed_path

_ASS_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[.:](\d{2})")
_ASS_TAG = re.compile(r"\{[^}]*\}")
_DIALOGUE = re.compile(r"(?im)^Dialogue:\s*(.*)$")


def _ass_time_to_srt(t: str) -> str:
    m = _ASS_TIME.search(t)
    if not m:
        return "00:00:00,000"
    h, mi, s, cs = (int(x) for x in m.groups())
    ms = cs * 10
    return f"{h:02d}:{mi:02d}:{s:02d},{ms:03d}"


def ass_to_srt(text: str) -> str:
    entries = []
    for m in _DIALOGUE.finditer(text):
        parts = m.group(1).split(",", 9)
        if len(parts) < 10:
            continue
        start, end, body = parts[1], parts[2], parts[9]
        body = _ASS_TAG.sub("", body).replace("\\N", "\n").replace("\\n", "\n").strip()
        entries.append((_ass_time_to_srt(start), _ass_time_to_srt(end), body))
    out = []
    for i, (start, end, body) in enumerate(entries, 1):
        out.append(f"{i}\n{start} --> {end}\n{body}\n")
    return "\n".join(out)


def ensure_srt(data: bytes) -> bytes:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", "replace")
    if text.lstrip().lower().startswith("[script info]") or "\nDialogue:" in text or text.startswith("Dialogue:"):
        text = ass_to_srt(text)
    return text.encode("utf-8")


def build_subtitle_plan(
    files: list[MediaFile],
    lang: str,
    state: State,
    conflict: str = "skip",
    provider=None,
) -> dict:
    provider = provider or OpenSubtitlesProvider(state)
    if getattr(provider, "key", None) is None and getattr(provider, "name", "") == "opensubtitles":
        raise ProviderError("OpenSubtitles Api-Key missing; set MO_OPENSUBTITLES_KEY")
    items = []
    for mf in files:
        src = Path(mf.path)
        if mf.parsed is None or mf.parsed.kind != "tv" and mf.parsed.kind != "movie":
            continue
        parsed = mf.parsed
        query = parsed.title
        results: list[SubtitleResult] = []
        try:
            # hash lookup is exact and avoids wrong-show matches
            try:
                h = movie_hash(src)
                results = provider.search(moviehash=h, languages=lang)
            except Exception:
                results = []
            if not results:
                results = provider.search(moviehash="", query=query, languages=lang)
        except Exception as e:
            items.append({
                "src": str(src), "dst": None, "status": "error",
                "subtitle": None, "warnings": [str(e)],
            })
            continue
        if not results:
            items.append({
                "src": str(src), "dst": None, "status": "unmatched",
                "subtitle": None, "warnings": ["no subtitle results"],
            })
            continue
        results.sort(key=lambda r: (r.downloads, r.rating), reverse=True)
        best = results[0]
        dst = src.with_name(f"{src.stem}.{lang}.srt")
        status = "ok"
        if exists_case_insensitive(dst):
            if conflict in {"index", "auto"}:
                dst = unique_indexed_path(dst)
                status = "indexed"
            elif conflict == "replace":
                status = "replace"
            else:
                status = "conflict"
        items.append({
            "src": str(src), "dst": str(dst), "status": status,
            "subtitle": {
                "provider": "opensubtitles", "file_id": best.file_id,
                "language": best.language, "release": best.release,
                "downloads": best.downloads, "rating": best.rating,
            },
            "warnings": [],
        })
    summary = {
        "total": len(items),
        "matched": sum(1 for i in items if i["status"] in {"ok", "replace", "indexed"}),
        "unmatched": sum(1 for i in items if i["status"] == "unmatched"),
        "conflicts": sum(1 for i in items if i["status"] == "conflict"),
        "errors": sum(1 for i in items if i["status"] == "error"),
    }
    plan = {
        "version": 1,
        "kind": "subtitle",
        "created_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": str(Path(files[0].path).parent if files else "."),
        "options": {"action": "copy", "conflict": conflict, "language": lang},
        "items": items,
        "summary": summary,
        "notes": [],
    }
    plan["plan_id"] = envelope_hash(plan)
    return plan
