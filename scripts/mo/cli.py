from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .apply import ApplyError, apply_plan, revert_journal
from .classify import detect_kind
from .index import Index
from .match import MatchOutput, match_files, match_music
from .models import MediaFile
from .parse import parse_media
from .plan import DEFAULT_FORMATS, PlanOptions, build_plan
from .providers import get_provider
from .providers.base import ProviderError
from .scan import scan_paths, scan_summary
from .state import State, envelope_hash, plan_hash
from .subs import build_subtitle_plan
from .util.paths import dangerous_root


def eprint(*a):
    print(*a, file=sys.stderr)


def emit_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _find_library_state(root: str | Path | None) -> Path | None:
    if not root:
        return None
    p = Path(root).expanduser()
    try:
        p = p.resolve()
    except OSError:
        return None
    if p.is_file():
        p = p.parent
    for q in [p, *p.parents]:
        marker = q / ".media-organizer"
        if marker.is_dir():
            return marker
    return None


def _state(args, root=None) -> State:
    if getattr(args, "state_dir", None):
        return State(state_dir=args.state_dir)
    marker = _find_library_state(root)
    if marker:
        return State(state_dir=marker)
    # default: one global state directory, so indexes/plans work across subfolders
    return State()


def _has_key(state: State, name: str) -> bool:
    env = {
        "tmdb": "MO_TMDB_KEY",
        "tvdb": "MO_TVDB_KEY",
        "omdb": "MO_OMDB_KEY",
        "opensubtitles": "MO_OPENSUBTITLES_KEY",
    }.get(name)
    if env and os.environ.get(env):
        return True
    keys = state.config.get("keys") or {}
    return bool(keys.get(name))


def _common_root(paths: list[str]) -> Path:
    ps = [Path(p).expanduser().resolve() for p in paths]
    bases = [p if p.is_dir() else p.parent for p in ps]
    if len(bases) == 1:
        return bases[0]
    try:
        common = Path(os.path.commonpath([str(b) for b in bases]))
    except ValueError:
        return bases[0]
    if dangerous_root(common):
        return bases[0]
    return common


def _provider_for(args, state: State, kind: str):
    name = (getattr(args, "db", None) or "auto").strip().lower()
    if name == "auto":
        if kind in {"tv", "anime", "movie"} and _has_key(state, "tmdb"):
            name = "tmdb"
        else:
            name = "local"
    return get_provider(name, state, Index(state)), name


def _print_plan(plan: dict, plan_path: Path | None = None) -> None:
    s = plan["summary"]
    print(f"plan: {plan['plan_id']}")
    print(f"kind: {plan['kind']}  root: {plan['root']}")
    print(
        f"total {s['total']}  matched {s['matched']}  unmatched {s['unmatched']}  "
        f"conflicts {s['conflicts']}  errors {s['errors']}  sidecars {s.get('sidecars', 0)}"
    )
    root = Path(plan["root"])
    rows = []
    for i in plan["items"][:30]:
        src = Path(i["src"])
        try:
            rel = str(src.relative_to(root))
        except ValueError:
            rel = str(src)
        dst = i.get("dst")
        if dst:
            try:
                dst = str(Path(dst).relative_to(root))
            except ValueError:
                dst = str(dst)
        conf = f"{i.get('confidence', 0):.2f}"
        rows.append((i["status"], conf, rel, dst or "-"))
    if rows:
        w0 = max(len(r[0]) for r in rows)
        w1 = 4
        w2 = min(60, max(len(r[2]) for r in rows))
        print(f"{'STATUS'.ljust(w0)}  CONF  {'SOURCE'.ljust(w2)}  DESTINATION")
        for st, conf, src, dst in rows:
            print(f"{st.ljust(w0)}  {conf}  {src[:w2].ljust(w2)}  {dst}")
        if len(plan["items"]) > 30:
            print(f"... {len(plan['items']) - 30} more items")
    if plan.get("notes"):
        print("notes:")
        for n in plan["notes"][:10]:
            print("  -", n)
    if plan_path:
        print(f"plan file: {plan_path}")
    print("dry-run only; run `apply --plan <file> --yes` to execute")


def _merge_plans(plans: list[dict]) -> dict:
    if len(plans) == 1:
        return plans[0]
    items = []
    notes = []
    kinds = {}
    for p in plans:
        items.extend(p["items"])
        notes.extend(p.get("notes", []))
        kinds[p["kind"]] = p["options"]["format"]
    summary = {
        "total": len(items),
        "matched": sum(1 for i in items if i["status"] in {"ok", "replace", "indexed", "noop"}),
        "unmatched": sum(1 for i in items if i["status"] == "unmatched"),
        "conflicts": sum(1 for i in items if i["status"] in {"conflict", "fail"}),
        "errors": sum(1 for i in items if i["status"] == "error"),
        "sidecars": sum(len(i.get("sidecars", [])) for i in items),
    }
    merged = {
        "version": 1,
        "kind": "mixed",
        "created_at": plans[0]["created_at"],
        "root": plans[0]["root"],
        "options": {**plans[0]["options"], "formats": kinds},
        "items": items,
        "summary": summary,
        "notes": notes,
    }
    merged["plan_id"] = envelope_hash(merged)
    return merged


# --------------------------------------------------------------------------- commands

def cmd_doctor(args) -> int:
    root = getattr(args, "path", None)
    try:
        state = _state(args, root)
        writable = os.access(state.base, os.W_OK)
        stats = Index(state).stats()
        checks = {
            "version": __version__,
            "python": sys.version.split()[0],
            "python_ok": sys.version_info >= (3, 11),
            "sqlite": __import__("sqlite3").sqlite_version,
            "state_dir": str(state.base),
            "state_writable": writable,
            "index": stats,
            "keys": {
                "tmdb": _has_key(state, "tmdb"),
                "tvdb": _has_key(state, "tvdb"),
                "omdb": _has_key(state, "omdb"),
                "opensubtitles": _has_key(state, "opensubtitles"),
            },
            "tools": {
                "fpcalc": shutil.which(os.environ.get("MO_FPCALC", "fpcalc")),
                "ffprobe": shutil.which("ffprobe"),
            },
        }
        if args.json:
            emit_json(checks)
        else:
            print(f"media-organizer {checks['version']}")
            print(f"[{'ok' if checks['python_ok'] else '!!'}] python {checks['python']}")
            print(f"[ok] sqlite {checks['sqlite']}")
            print(f"[{'ok' if writable else '!!'}] state {checks['state_dir']}")
            print(f"[ok] index series={stats['series']} episodes={stats['episodes']} movies={stats['movies']}")
            for k, v in checks["keys"].items():
                print(f"[{'ok' if v else '--'}] {k} key")
            for k, v in checks["tools"].items():
                print(f"[{'ok' if v else '--'}] {k}: {v or 'not found'}")
        return 0 if checks["python_ok"] and writable else 1
    except Exception as e:
        if getattr(args, "json", False):
            emit_json({"error": str(e)})
        else:
            eprint("doctor failed:", e)
        return 2


def cmd_scan(args) -> int:
    try:
        files = scan_paths(args.paths, recursive=args.recursive)
    except Exception as e:
        eprint("scan failed:", e)
        return 1
    for mf in files:
        mf_kind = detect_kind(mf, args.mode if args.mode != "auto" else None)
        mf.media_kind = mf_kind
    summary = scan_summary(files)
    summary["by_kind"] = {}
    for f in files:
        k = getattr(f, "media_kind", "unknown")
        summary["by_kind"][k] = summary["by_kind"].get(k, 0) + 1
    if args.json:
        emit_json({"summary": summary, "files": [f.to_dict() | {"detected_kind": getattr(f, "media_kind", "unknown")} for f in files]})
    else:
        print(f"files {summary['files']}  sidecars {summary['sidecars']}  warnings {summary['warnings']}")
        for f in files:
            p = f.parsed
            ident = ""
            if p and p.kind == "tv":
                ident = f"S{p.season if p.season is not None else '?'}E{p.episodes[0] if p.episodes else '?'}"
                ident += f"  {p.title}"
            elif p and p.kind == "movie":
                ident = f"{p.title} ({p.year})"
            elif p:
                ident = p.title
            print(f"{getattr(f, 'media_kind', 'unknown'):7} {ident[:80]:80} {f.path}")
    return 0


def cmd_plan(args) -> int:
    files = scan_paths(args.paths, recursive=args.recursive)
    root = _common_root(args.paths)
    state = _state(args, root)
    mode = args.mode
    groups: dict[str, list[MediaFile]] = {}
    unknown: list[MediaFile] = []
    for mf in files:
        kind = detect_kind(mf, mode if mode != "auto" else None)
        mf.media_kind = kind
        if kind == "unknown":
            unknown.append(mf)
        else:
            groups.setdefault(kind, []).append(mf)

    plans: list[dict] = []
    errors: list[str] = []
    for kind, group in groups.items():
        try:
            if kind == "music":
                matches = match_music(group, state)
            else:
                provider, pname = _provider_for(args, state, kind)
                if getattr(args, "lang", None) and hasattr(provider, "lang"):
                    provider.lang = args.lang
                if pname == "local":
                    stats = Index(state).stats()
                    if kind in {"tv", "anime"} and stats["series"] == 0:
                        raise ProviderError("local TV index is empty; run `index build --from <file>` or set MO_TMDB_KEY")
                    if kind == "movie" and stats["movies"] == 0:
                        raise ProviderError("local movie index is empty; run `index build --from <file>` or set MO_TMDB_KEY")
                matches = match_files(
                    group, provider, kind,
                    query=args.q if kind in {"tv", "anime", "movie"} else None,
                    strict=not args.non_strict,
                )
        except ProviderError as e:
            errors.append(f"{kind}: {e}")
            matches = MatchOutput(unmatched=list(group), notes=[str(e)])
        fmt = args.format or DEFAULT_FORMATS.get(kind, "{n}")
        options = PlanOptions(
            action=args.action, conflict=args.conflict, format=fmt,
            output=args.output, unixfs=args.unixfs, allow_absolute=args.allow_absolute,
            apply=(args.apply or []), kind=kind,
        )
        plans.append(build_plan(group, matches, options, root))

    if unknown:
        options = PlanOptions(
            action=args.action, conflict=args.conflict, format=args.format or "{n}",
            output=args.output, unixfs=args.unixfs, allow_absolute=args.allow_absolute,
            apply=(args.apply or []), kind="unknown",
        )
        plans.append(build_plan(unknown, MatchOutput(unmatched=list(unknown)), options, root))

    if not plans:
        eprint("no media files found")
        return 1
    plan = _merge_plans(plans)
    plan["state_dir"] = str(state.base)
    if errors:
        plan.setdefault("notes", []).extend(errors)
    path = Path(args.plan_out) if args.plan_out else state.write_plan(plan)
    if args.plan_out:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        emit_json({"plan": plan, "plan_file": str(path)})
    else:
        _print_plan(plan, path)
    s = plan["summary"]
    # partial success is still exit 0 if a plan was produced
    return 0 if (s["matched"] or s["unmatched"]) else 1


def cmd_apply(args) -> int:
    plan_path = Path(args.plan)
    if not plan_path.exists():
        eprint("plan not found:", plan_path)
        return 2
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as e:
        eprint("cannot read plan:", e)
        return 2
    root = plan.get("root")
    if plan.get("state_dir") and not getattr(args, "state_dir", None):
        state = State(state_dir=plan["state_dir"])
    else:
        state = _state(args, root)
    if not args.yes and not args.dry_run:
        _print_plan(plan, plan_path)
        eprint("refusing to mutate without --yes")
        return 3
    try:
        results = apply_plan(state, plan, dry_run=args.dry_run, force=args.force, plan_path=plan_path)
    except ApplyError as e:
        eprint("apply refused:", e)
        return 3
    except Exception as e:
        eprint("apply failed:", e)
        return 1
    if args.json:
        emit_json(results)
    else:
        print(f"applied {results['applied']}  skipped {results['skipped']}  failed {results['failed']}")
        if results.get("journal"):
            print("journal:", results["journal"])
        for e in results.get("errors", [])[:20]:
            print("  !", e)
    return 0 if results["failed"] == 0 else 1


def cmd_revert(args) -> int:
    journal = Path(args.journal) if args.journal else None
    if journal is not None and not args.root:
        # infer the per-library state dir from <root>/.media-organizer/journals
        state = State(state_dir=journal.parent.parent)
    else:
        state = _state(args, args.root)
    if journal is None:
        logs = sorted(state.journals.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            eprint("no journals found")
            return 1
        journal = logs[0]
    try:
        results = revert_journal(state, journal)
    except Exception as e:
        eprint("revert failed:", e)
        return 1
    if args.json:
        emit_json(results | {"journal": str(journal)})
    else:
        print(f"reverted {results['reverted']}  skipped {results['skipped']}  failed {results['failed']}")
        print("journal:", journal)
        for e in results.get("errors", [])[:20]:
            print("  !", e)
    return 0 if results["failed"] == 0 else 1


def cmd_subs(args) -> int:
    files = scan_paths(args.paths, recursive=args.recursive)
    root = _common_root(args.paths)
    state = _state(args, root)
    videos = [f for f in files if f.parsed and f.parsed.kind in {"tv", "movie"}]
    if not videos:
        eprint("no video files found")
        return 1
    try:
        plan = build_subtitle_plan(videos, args.lang, state, conflict=args.conflict)
    except ProviderError as e:
        eprint("subtitles unavailable:", e)
        return 2
    plan["state_dir"] = str(state.base)
    path = Path(args.plan_out) if args.plan_out else state.write_plan(plan)
    if args.plan_out:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        emit_json({"plan": plan, "plan_file": str(path)})
    else:
        print(f"subtitle plan: {plan['plan_id']}")
        print(f"total {plan['summary']['total']}  matched {plan['summary']['matched']}  "
              f"unmatched {plan['summary']['unmatched']}  errors {plan['summary']['errors']}")
        for item in plan["items"][:20]:
            print(f"{item['status']:9} {Path(item['src']).name} -> {Path(item['dst']).name if item.get('dst') else '-'}")
        print("plan file:", path)
    return 0


def cmd_index(args) -> int:
    state = _state(args, args.root)
    idx = Index(state)
    if args.index_command == "build":
        if not args.from_path:
            eprint("index build requires --from <file.json|file.csv>")
            return 2
        try:
            counts = idx.build_from(args.from_path, replace=args.replace)
        except Exception as e:
            eprint("index build failed:", e)
            return 1
        if args.json:
            emit_json(counts | idx.stats())
        else:
            print("index built:", counts)
            print("totals:", idx.stats())
        return 0
    if args.index_command == "stats":
        stats = idx.stats()
        if args.json:
            emit_json(stats)
        else:
            print(json.dumps(stats, indent=2))
        return 0
    if args.index_command == "search":
        if args.movie:
            rows = idx.search_movies(args.query, year=args.year)
        else:
            rows = idx.search_series(args.query)
        if args.json:
            emit_json([r.__dict__ for r in rows])
        else:
            for r in rows:
                extra = f" ({r.year})" if getattr(r, "year", None) else ""
                print(f"{r.id}\t{r.name}{extra}")
        return 0
    return 2


def cmd_explain(args) -> int:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    items = plan.get("items", [])
    if args.item < 1 or args.item > len(items):
        eprint(f"item out of range 1..{len(items)}")
        return 2
    item = items[args.item - 1]
    if args.json:
        emit_json(item)
    else:
        print(json.dumps(item, ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mo", description="media-organizer: pure-Python media library organizer")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        sp.add_argument("--state-dir", help="state directory (default: <root>/.media-organizer)")

    d = sub.add_parser("doctor", help="check environment and configuration")
    d.add_argument("path", nargs="?", help="optional media root for per-library state")
    common(d)
    d.set_defaults(func=cmd_doctor)

    s = sub.add_parser("scan", help="inventory media files (read-only)")
    s.add_argument("paths", nargs="+")
    s.add_argument("--mode", choices=["auto", "tv", "movie", "anime", "music"], default="auto")
    s.add_argument("--no-recursive", dest="recursive", action="store_false", default=True)
    s.add_argument("--recursive", dest="recursive", action="store_true")
    common(s)
    s.set_defaults(func=cmd_scan)

    pl = sub.add_parser("plan", help="build a rename plan (dry-run)")
    pl.add_argument("paths", nargs="+")
    pl.add_argument("--mode", choices=["auto", "tv", "movie", "anime", "music"], default="auto")
    pl.add_argument("--db", default="auto", help="local | tmdb | tvdb | tvmaze | omdb")
    pl.add_argument("--format", help="format expression, e.g. '{n} - S{s00e00} - {t}' or '{plex}'")
    pl.add_argument("--action", choices=["move", "copy", "hardlink", "symlink", "test"], default="move")
    pl.add_argument("--conflict", choices=["skip", "replace", "index", "auto", "fail"], default="skip")
    pl.add_argument("--output", help="output directory")
    pl.add_argument("--q", help="force a query/title")
    pl.add_argument("--non-strict", action="store_true")
    pl.add_argument("--lang", default="en")
    pl.add_argument("--apply", action="append", default=[], help="post-process: nfo, metadata, artwork")
    pl.add_argument("--unixfs", action="store_true")
    pl.add_argument("--allow-absolute", action="store_true")
    pl.add_argument("--plan-out", help="write plan to this path")
    pl.add_argument("--no-recursive", dest="recursive", action="store_false", default=True)
    pl.add_argument("--recursive", dest="recursive", action="store_true")
    common(pl)
    pl.set_defaults(func=cmd_plan)

    a = sub.add_parser("apply", help="execute a saved plan")
    a.add_argument("--plan", required=True)
    a.add_argument("--yes", action="store_true", help="confirm mutations")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--force", action="store_true", help="ignore size/mtime changes")
    common(a)
    a.set_defaults(func=cmd_apply)

    r = sub.add_parser("revert", help="undo a journal")
    r.add_argument("--journal")
    r.add_argument("--root", help="media root for state lookup")
    common(r)
    r.set_defaults(func=cmd_revert)

    su = sub.add_parser("subs", help="build a subtitle download plan")
    su.add_argument("paths", nargs="+")
    su.add_argument("--lang", default="en")
    su.add_argument("--conflict", choices=["skip", "replace", "index", "auto"], default="skip")
    su.add_argument("--plan-out")
    su.add_argument("--no-recursive", dest="recursive", action="store_false", default=True)
    su.add_argument("--recursive", dest="recursive", action="store_true")
    common(su)
    su.set_defaults(func=cmd_subs)

    ix = sub.add_parser("index", help="local index management")
    ix.add_argument("index_command", choices=["build", "stats", "search"])
    ix.add_argument("--from", dest="from_path", help="JSON or CSV index file")
    ix.add_argument("--replace", action="store_true")
    ix.add_argument("--query", "-q")
    ix.add_argument("--movie", action="store_true")
    ix.add_argument("--year", type=int)
    ix.add_argument("--root", help="media root for per-library state")
    common(ix)
    ix.set_defaults(func=cmd_index)

    e = sub.add_parser("explain", help="show one plan item")
    e.add_argument("--plan", required=True)
    e.add_argument("--item", type=int, required=True)
    common(e)
    e.set_defaults(func=cmd_explain)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        eprint("interrupted")
        return 130
    except Exception as e:
        eprint(f"{type(e).__name__}: {e}")
        return 1
