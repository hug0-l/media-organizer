from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from .meta import apply_postprocess
from .providers.opensubtitles import OpenSubtitlesProvider
from .state import State, envelope_hash
from .subs import ensure_srt
from .util.paths import (
    canonical,
    exists_case_insensitive,
    is_relative_to,
    unique_indexed_path,
)


class ApplyError(RuntimeError):
    pass


def _journal(state: State, path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _allowed(dest: Path, plan: dict) -> bool:
    if plan.get("options", {}).get("allow_absolute"):
        return True
    allowed = [plan.get("root")]
    out = plan.get("options", {}).get("output")
    if out:
        allowed.append(out)
    return any(a and is_relative_to(dest, a) for a in allowed)


def _backup(state: State, plan: dict, dest: Path) -> Path:
    bdir = state.backup_dir(plan["plan_id"])
    target = bdir / dest.name
    if exists_case_insensitive(target):
        target = unique_indexed_path(target)
    shutil.move(str(dest), str(target))
    return target


def _do_action(action: str, src: Path, dst: Path) -> None:
    if action == "test":
        return
    if action == "move":
        shutil.move(str(src), str(dst))
        return
    if action == "copy":
        shutil.copy2(str(src), str(dst))
        return
    if action == "hardlink":
        os.link(str(src), str(dst))
        return
    if action == "symlink":
        os.symlink(str(src), str(dst))
        return
    raise ApplyError(f"unknown action: {action}")


def _verify_source(item: dict, force: bool) -> str | None:
    src = Path(item["src"])
    if not src.exists():
        return "source missing"
    if force:
        return None
    size = item.get("src_size")
    mtime = item.get("src_mtime")
    try:
        st = src.stat()
    except OSError as e:
        return f"cannot stat source: {e}"
    if size and st.st_size != size:
        return f"source size changed ({st.st_size} != {size})"
    if mtime and abs(st.st_mtime - float(mtime)) > 2:
        return "source mtime changed"
    return None


def _apply_rename_item(
    state: State, plan: dict, item: dict, journal: Path,
    force: bool, dry_run: bool, results: dict,
) -> None:
    src = Path(item["src"])
    status = item.get("status")
    if status == "fail":
        results["failed"] += 1
        results["errors"].append(f"{src}: plan marked {status}")
        return
    if status in {"unmatched", "error", "conflict"}:
        results["skipped"] += 1
        return
    if status == "noop":
        results["skipped"] += 1
        return
    why = _verify_source(item, force)
    if why:
        results["failed"] += 1
        results["errors"].append(f"{src}: {why}")
        return

    dst = Path(item["dst"]) if item.get("dst") else None
    if not dst:
        results["failed"] += 1
        results["errors"].append(f"{src}: no destination")
        return
    if not _allowed(dst, plan):
        results["failed"] += 1
        results["errors"].append(f"{dst}: outside allowed roots")
        return

    action = plan["options"]["action"]
    conflict = plan["options"]["conflict"]
    dst = canonical(dst)
    backup = None
    if exists_case_insensitive(dst) and canonical(dst) != canonical(src):
        if conflict in {"index", "auto"}:
            dst = unique_indexed_path(dst)
        elif conflict == "replace":
            if dry_run:
                pass
            else:
                backup = _backup(state, plan, dst)
        else:
            results["skipped"] += 1
            return

    dst.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.time(), "plan_id": plan.get("plan_id"), "op": action,
        "src": str(src), "dst": str(dst), "role": "primary",
        "result": "dry-run" if dry_run else "ok", "backup": str(backup) if backup else None,
    }
    if dry_run:
        _journal(state, journal, record)
        results["applied"] += 1
        return
    try:
        _do_action(action, src, dst)
    except Exception as e:
        record["result"] = "error"
        record["error"] = str(e)
        _journal(state, journal, record)
        results["failed"] += 1
        results["errors"].append(f"{src} -> {dst}: {e}")
        if backup and Path(backup).exists():
            try:
                shutil.move(str(backup), str(dst))
            except Exception:
                pass
        return
    _journal(state, journal, record)
    results["applied"] += 1
    state.conn.execute(
        "INSERT INTO history(ts,plan_id,src,dst,op,result) VALUES(?,?,?,?,?,?)",
        (time.time(), plan.get("plan_id"), str(src), str(dst), action, "ok"),
    )
    state.conn.commit()

    actions = (plan.get("options") or {}).get("apply") or []
    if actions and item.get("candidate"):
        try:
            apply_postprocess(dst, item["candidate"], list(actions))
        except Exception as e:
            results["errors"].append(f"{dst}: postprocess failed: {e}")

    for side in item.get("sidecars", []) or []:
        s_src = Path(side["src"])
        if not s_src.exists():
            continue
        s_dst = Path(side["dst"])
        if not _allowed(s_dst, plan):
            results["errors"].append(f"{s_src}: sidecar outside allowed roots")
            continue
        s_dst = canonical(s_dst)
        s_backup = None
        if exists_case_insensitive(s_dst):
            if conflict in {"index", "auto"}:
                s_dst = unique_indexed_path(s_dst)
            elif conflict == "replace":
                s_backup = _backup(state, plan, s_dst)
            else:
                continue
        s_dst.parent.mkdir(parents=True, exist_ok=True)
        srec = {
            "ts": time.time(), "plan_id": plan.get("plan_id"), "op": action,
            "src": str(s_src), "dst": str(s_dst), "role": "sidecar",
            "result": "ok", "backup": str(s_backup) if s_backup else None,
        }
        try:
            _do_action(action, s_src, s_dst)
            _journal(state, journal, srec)
            state.conn.execute(
                "INSERT INTO history(ts,plan_id,src,dst,op,result) VALUES(?,?,?,?,?,?)",
                (time.time(), plan.get("plan_id"), str(s_src), str(s_dst), action, "ok"),
            )
            state.conn.commit()
        except Exception as e:
            srec["result"] = "error"
            srec["error"] = str(e)
            _journal(state, journal, srec)
            if s_backup and Path(s_backup).exists():
                try:
                    shutil.move(str(s_backup), str(s_dst))
                except Exception:
                    pass
            results["errors"].append(f"{s_src} -> {s_dst}: {e}")


def _apply_subtitle_item(
    state: State, plan: dict, item: dict, journal: Path,
    dry_run: bool, results: dict,
) -> None:
    src = Path(item["src"])
    dst = Path(item["dst"])
    if not src.exists():
        results["failed"] += 1
        results["errors"].append(f"{src}: source missing")
        return
    # subtitles belong next to the video; allow multi-root scans
    if not is_relative_to(dst, src.parent):
        results["failed"] += 1
        results["errors"].append(f"{dst}: subtitle must stay beside the video")
        return
    sub = item.get("subtitle") or {}
    conflict = plan["options"]["conflict"]
    backup = None
    if exists_case_insensitive(dst):
        if conflict in {"index", "auto"}:
            dst = unique_indexed_path(dst)
        elif conflict != "replace":
            results["skipped"] += 1
            return
        elif not dry_run:
            # download first; only then displace the existing file
            backup = None
    record = {
        "ts": time.time(), "plan_id": plan.get("plan_id"), "op": "subtitle",
        "src": str(src), "dst": str(dst), "role": "subtitle",
        "result": "dry-run" if dry_run else "ok",
        "file_id": sub.get("file_id"), "language": sub.get("language"),
        "backup": None,
    }
    if dry_run:
        _journal(state, journal, record)
        results["applied"] += 1
        return
    try:
        provider = OpenSubtitlesProvider(state)
        data = ensure_srt(provider.download(int(sub["file_id"])))
    except Exception as e:
        record["result"] = "error"
        record["error"] = str(e)
        _journal(state, journal, record)
        results["failed"] += 1
        results["errors"].append(f"{src}: subtitle download failed: {e}")
        return
    if exists_case_insensitive(dst) and conflict == "replace":
        backup = _backup(state, plan, dst)
        record["backup"] = str(backup)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        _journal(state, journal, record)
        results["applied"] += 1
    except Exception as e:
        if backup and Path(backup).exists():
            try:
                shutil.move(str(backup), str(dst))
            except Exception:
                pass
        record["result"] = "error"
        record["error"] = str(e)
        _journal(state, journal, record)
        results["failed"] += 1
        results["errors"].append(f"{src}: subtitle write failed: {e}")


def apply_plan(
    state: State,
    plan: dict,
    dry_run: bool = False,
    force: bool = False,
    plan_path: Path | None = None,
) -> dict:
    expected = plan.get("plan_id")
    actual = envelope_hash(plan)
    if expected and expected != actual:
        raise ApplyError("plan hash mismatch; regenerate the plan")

    journal = state.journal_path()
    results = {"applied": 0, "skipped": 0, "failed": 0, "errors": [], "journal": str(journal)}
    if plan.get("kind") == "subtitle":
        for item in plan.get("items", []):
            _apply_subtitle_item(state, plan, item, journal, dry_run, results)
    else:
        for item in plan.get("items", []):
            _apply_rename_item(state, plan, item, journal, force, dry_run, results)
    results["journal"] = str(journal) if journal.exists() else None
    return results


def revert_journal(state: State, journal_path: str | Path) -> dict:
    path = Path(journal_path)
    if not path.exists():
        raise ApplyError(f"journal not found: {path}")
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    results = {"reverted": 0, "skipped": 0, "failed": 0, "errors": []}
    new_journal = state.journal_path()
    for rec in reversed(lines):
        if rec.get("result") not in {"ok", "dry-run"}:
            continue
        op = rec.get("op")
        src = Path(rec.get("src") or "")
        dst = Path(rec.get("dst") or "")
        if not str(src) or not str(dst):
            continue
        if not dst.exists():
            results["skipped"] += 1
            continue
        try:
            if op == "move":
                if src.exists():
                    results["skipped"] += 1
                    continue
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(src))
            elif op in {"copy", "subtitle"}:
                if src.exists():
                    try:
                        if dst.stat().st_size != src.stat().st_size:
                            results["skipped"] += 1
                            continue
                    except OSError:
                        pass
                dst.unlink()
            elif op in {"hardlink", "symlink"}:
                dst.unlink()
            else:
                results["skipped"] += 1
                continue
            backup = rec.get("backup")
            if backup and Path(backup).exists():
                Path(backup).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(backup), str(dst))
            results["reverted"] += 1
            _journal(state, new_journal, {
                "ts": time.time(), "op": "revert", "reverted_op": op,
                "src": str(src), "dst": str(dst), "result": "ok",
            })
        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"{dst} -> {src}: {e}")
    return results
