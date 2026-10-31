from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .format import FormatError, build_bindings, render
from .match import MatchOutput
from .models import EpisodeRef, MatchResult, MediaFile, MovieRef, MusicRef
from .state import envelope_hash, plan_hash
from .util.paths import (
    canonical,
    exists_case_insensitive,
    resolve_destination,
    unique_indexed_path,
)

DEFAULT_FORMATS = {
    "tv": "{n} - {s00e00} - {t}",
    "anime": "{n} - {s00e00} - {t}",
    "movie": "{n} ({y})",
    "music": "{albumArtist}/{album}/{track} - {t}",
}


@dataclass
class PlanOptions:
    action: str = "move"
    conflict: str = "skip"
    format: str = ""
    output: str | None = None
    unixfs: bool = False
    allow_absolute: bool = False
    apply: list[str] = field(default_factory=list)
    kind: str = "tv"


def candidate_to_dict(c) -> dict:
    if isinstance(c, EpisodeRef):
        eps = c.raw.get("episodes") if isinstance(c.raw, dict) else None
        return {
            "type": "episode",
            "db": c.source,
            "id": c.series_id,
            "series_id": c.series_id,
            "name": c.series_name,
            "series_name": c.series_name,
            "year": c.series_year,
            "season": c.season,
            "episode": c.episode,
            "episodes": eps or ([c.episode] if c.episode is not None else []),
            "title": c.title,
            "airdate": c.airdate.isoformat() if c.airdate else None,
            "absolute": c.absolute,
            "special": c.special,
            "still_path": (c.raw or {}).get("still_path") if isinstance(c.raw, dict) else None,
        }
    if isinstance(c, MovieRef):
        return {
            "type": "movie",
            "db": c.source,
            "id": c.id,
            "name": c.name,
            "year": c.year,
            "tmdb_id": c.tmdb_id,
            "imdb_id": c.imdb_id,
            "poster_path": (c.raw or {}).get("poster_path") if isinstance(c.raw, dict) else None,
            "backdrop_path": (c.raw or {}).get("backdrop_path") if isinstance(c.raw, dict) else None,
        }
    if isinstance(c, MusicRef):
        return {
            "type": "music",
            "db": c.source,
            "id": c.id,
            "artist": c.artist,
            "album_artist": c.album_artist,
            "album": c.album,
            "title": c.title,
            "track": c.track,
            "year": c.year,
        }
    return {"type": "unknown", "value": str(c)}


def _sidecar_dest(primary_src: Path, primary_dst: Path, sidecar: Path) -> Path:
    src_stem = primary_src.stem
    side_stem = sidecar.stem
    if not side_stem.lower().startswith(src_stem.lower()):
        suffix = ""
    else:
        suffix = side_stem[len(src_stem):]
    new_name = primary_dst.stem + suffix + sidecar.suffix
    return primary_dst.with_name(new_name)


def _conflict(dest: Path, mode: str) -> tuple[Path, str]:
    if not exists_case_insensitive(dest):
        return dest, "ok"
    if mode == "skip":
        return dest, "conflict"
    if mode == "replace":
        return dest, "replace"
    if mode == "index" or mode == "auto":
        return unique_indexed_path(dest), "indexed"
    if mode == "fail":
        return dest, "fail"
    return dest, "conflict"


def build_plan(
    files: list[MediaFile],
    matches: MatchOutput,
    options: PlanOptions,
    root: str | Path,
) -> dict:
    root = canonical(root)
    fmt = options.format or DEFAULT_FORMATS.get(options.kind, "{n}")
    items: list[dict] = []
    warnings: list[str] = []

    by_file = {m.file.path: m for m in matches.matches}

    for mf in files:
        parsed = mf.parsed
        match: MatchResult | None = by_file.get(mf.path)
        if match is None:
            items.append({
                "src": mf.path,
                "dst": None,
                "status": "unmatched",
                "confidence": 0.0,
                "candidate": None,
                "reasons": [],
                "warnings": mf.warnings,
                "src_size": mf.size,
                "src_mtime": mf.mtime,
                "sidecars": [],
            })
            continue

        try:
            bindings = build_bindings(
                match.candidate, mf.path, parsed, output=options.output,
                kind=options.kind, is_anime=options.kind == "anime",
            )
            rendered = render(fmt, bindings)
            ext = Path(mf.path).suffix
            if ext and not rendered.lower().endswith(ext.lower()):
                rendered = rendered + ext.lower()
            dest = resolve_destination(
                rendered, root, output=options.output, unixfs=options.unixfs,
                allow_absolute=options.allow_absolute,
            )
        except (FormatError, ValueError, OSError) as e:
            items.append({
                "src": mf.path, "dst": None, "status": "error", "confidence": match.confidence,
                "candidate": candidate_to_dict(match.candidate), "reasons": match.reasons,
                "warnings": [*mf.warnings, str(e)], "src_size": mf.size, "src_mtime": mf.mtime,
                "sidecars": [],
            })
            continue

        if canonical(dest) == canonical(mf.path):
            dest, status = dest, "noop"
        else:
            dest, status = _conflict(dest, options.conflict)

        sidecars = []
        for s in mf.sidecars:
            sp = Path(s)
            sd = _sidecar_dest(Path(mf.path), dest, sp)
            sd, sstatus = _conflict(sd, options.conflict)
            sidecars.append({
                "src": s, "dst": str(sd), "status": sstatus,
            })

        item = {
            "src": mf.path,
            "dst": str(dest),
            "status": status,
            "confidence": round(match.confidence, 3),
            "candidate": candidate_to_dict(match.candidate),
            "reasons": match.reasons,
            "warnings": mf.warnings,
            "src_size": mf.size,
            "src_mtime": mf.mtime,
            "sidecars": sidecars,
        }
        items.append(item)

    summary = {
        "total": len(items),
        "matched": sum(1 for i in items if i["status"] in {"ok", "replace", "indexed", "noop"}),
        "unmatched": sum(1 for i in items if i["status"] == "unmatched"),
        "conflicts": sum(1 for i in items if i["status"] in {"conflict", "fail"}),
        "errors": sum(1 for i in items if i["status"] == "error"),
        "sidecars": sum(len(i["sidecars"]) for i in items),
    }

    plan = {
        "version": 1,
        "kind": options.kind,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": str(root),
        "options": {
            "action": options.action,
            "conflict": options.conflict,
            "format": fmt,
            "output": options.output,
            "unixfs": options.unixfs,
            "allow_absolute": options.allow_absolute,
            "apply": options.apply,
        },
        "items": items,
        "summary": summary,
        "notes": matches.notes + [f"unresolved: {x}" for x in matches.unresolved_series],
    }
    plan["plan_id"] = envelope_hash(plan)
    return plan
