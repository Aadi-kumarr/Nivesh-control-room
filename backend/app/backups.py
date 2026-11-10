"""Automatic JSON snapshots of the whole database.

Snapshot failures never raise: the caller gets warnings instead, so a failed backup
can't undo or block a write that already succeeded.
"""
import logging
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

from bson import json_util

BACKUP_ROOT = Path(__file__).resolve().parents[2] / "data" / "backups"
AUTO_KEEP = 50
DAILY_KEEP = 365

# Retention only ever touches files matching these names, inside auto/ and daily/
# (here and in the mirror).
AUTO_NAME = re.compile(r"^nivesh-(\d{8})-(\d{6})(?:-(\d+))?\.json$")
DAILY_NAME = re.compile(r"^nivesh-(\d{8})\.json$")

_lock = threading.Lock()

# Caches of Yahoo data that are fetched again when needed, so snapshots leave them out.
# daily_closes is rebuilt when a time frame is picked (see periods.load_daily).
NOT_BACKED_UP = {"daily_closes"}


def snapshot_text(db) -> str:
    """The whole database, minus re-fetchable caches, as JSON. Canonical form keeps
    int/float/date types for restore."""
    dump = {
        name: list(db[name].find())
        for name in sorted(db.list_collection_names()) if name not in NOT_BACKED_UP
    }
    return json_util.dumps(dump, indent=2, json_options=json_util.CANONICAL_JSON_OPTIONS)


def _write_new(folder: Path, stem: str, text: str) -> Path:
    """Write to a new file, never replacing one. A second snapshot in the same second
    gets a -1, -2... suffix. Goes through a temp file so a failed write leaves no partial."""
    folder.mkdir(parents=True, exist_ok=True)
    target, suffix = folder / f"{stem}.json", 0
    while target.exists():
        suffix += 1
        target = folder / f"{stem}-{suffix}.json"
    temp = folder / f"{target.stem}.tmp"
    try:
        temp.write_text(text, encoding="utf-8")
        temp.rename(target)
    finally:
        temp.unlink(missing_ok=True)
    return target


def _auto_order(path: Path) -> tuple:
    day, time, suffix = AUTO_NAME.match(path.name).groups()
    return day, time, int(suffix or 0)


def _prune(folder: Path, pattern: re.Pattern, keep: int, order) -> None:
    matching = sorted((p for p in folder.iterdir() if pattern.match(p.name)), key=order)
    for path in matching[:-keep]:
        path.unlink()


def _mirror(path: Path, kind: str, pattern: re.Pattern, keep: int, order) -> None:
    """Copy to BACKUP_MIRROR_DIR/<kind>, with the same limits as the local folder.
    As locally, only files with our snapshot names are ever deleted."""
    mirror_dir = os.environ.get("BACKUP_MIRROR_DIR", "").strip()
    if mirror_dir:
        folder = Path(mirror_dir) / kind
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, folder / path.name)
        _prune(folder, pattern, keep, order)


def _take(db, kind: str, stem: str, pattern: re.Pattern, keep: int, order) -> tuple:
    """Write one snapshot, then prune and mirror. Returns (file name or None, warnings)."""
    folder = BACKUP_ROOT / kind
    try:
        path = _write_new(folder, stem, snapshot_text(db))
    except Exception as exc:  # disk, permission or database errors must not reach the caller
        logging.exception("%s snapshot failed", kind)
        return None, [f"Backup failed: {kind} snapshot was not written ({exc})."]

    warnings = []
    try:
        _prune(folder, pattern, keep, order)
    except OSError as exc:
        warnings.append(f"Backup retention failed for {kind} ({exc}). Snapshot was written.")
    try:
        _mirror(path, kind, pattern, keep, order)
    except OSError as exc:
        warnings.append(f"Backup mirror failed for {path.name} ({exc}). Local copy was written.")
    return path.name, warnings


def ensure_daily(db) -> list:
    """Take today's daily snapshot if there isn't one yet. Returns warnings."""
    stem = f"nivesh-{datetime.now():%Y%m%d}"
    with _lock:
        if (BACKUP_ROOT / "daily" / f"{stem}.json").exists():
            return []
        _, warnings = _take(db, "daily", stem, DAILY_NAME, DAILY_KEEP, lambda p: p.name)
    return warnings


def after_write(db) -> dict:
    """Snapshot after a successful API write. Returns {"file", "warnings"}."""
    with _lock:
        name, warnings = _take(
            db, "auto", f"nivesh-{datetime.now():%Y%m%d-%H%M%S}", AUTO_NAME, AUTO_KEEP, _auto_order
        )
    return {"file": name, "warnings": warnings + ensure_daily(db)}


def export(db) -> Path:
    """Save a snapshot on request, to exports/. These are never pruned or mirrored.
    Unlike the automatic snapshots this raises, so the person who asked sees the failure."""
    with _lock:
        return _write_new(
            BACKUP_ROOT / "exports", f"nivesh-export-{datetime.now():%Y%m%d-%H%M%S}", snapshot_text(db)
        )


def write_profile_backup(stem: str, text: str) -> Path:
    """A deleted profile's data, to profiles/. Never pruned or mirrored. Raises on failure,
    so the profile is only deleted once its backup is on disk."""
    with _lock:
        return _write_new(BACKUP_ROOT / "profiles", stem, text)


def list_backups() -> dict:
    """Snapshots by folder, newest first. "manual" is the JSON directly in data/backups/."""

    def describe(folder: Path) -> list:
        if not folder.is_dir():
            return []
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix == ".json"]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
            for path in files
        ]

    return {
        "auto": describe(BACKUP_ROOT / "auto"),
        "daily": describe(BACKUP_ROOT / "daily"),
        "exports": describe(BACKUP_ROOT / "exports"),
        "profiles": describe(BACKUP_ROOT / "profiles"),
        "manual": describe(BACKUP_ROOT),
    }
