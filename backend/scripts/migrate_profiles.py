"""Add profiles: create the default profile and tag existing transactions with it.

Run from backend/:  .venv\\Scripts\\python scripts\\migrate_profiles.py

It first takes a full mongodump into data/backups/pre-profiles-<timestamp>/ and stops
if that fails. The migration only adds documents and fields where they are missing,
so running it twice is safe.
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import app.db  # noqa: E402,F401  (loads backend/.env)
from app.profiles import migrate  # noqa: E402

BACKUP_ROOT = BACKEND.parent / "data" / "backups"
DEFAULT_MONGODUMP = Path(r"C:\Program Files\MongoDB\Tools\100\bin\mongodump.exe")


def mongodump(url: str, db_name: str) -> Path:
    exe = shutil.which("mongodump") or (str(DEFAULT_MONGODUMP) if DEFAULT_MONGODUMP.exists() else None)
    if exe is None:
        raise SystemExit("mongodump not found. Nothing was changed.")
    out = BACKUP_ROOT / f"pre-profiles-{datetime.now():%Y%m%d-%H%M%S}"
    result = subprocess.run(
        [exe, f"--uri={url}", f"--db={db_name}", f"--out={out}"], capture_output=True, text=True
    )
    files = sorted(p for p in out.rglob("*") if p.is_file()) if out.exists() else []
    if result.returncode != 0 or not files:
        raise SystemExit(f"mongodump failed. Nothing was changed.\n{result.stderr}")
    print(f"Backup: {out}")
    for path in files:
        print(f"  {path.relative_to(out)}  {path.stat().st_size} bytes")
    return out


def main() -> int:
    url, db_name = os.environ["MONGO_URL"], os.environ["DB_NAME"]
    mongodump(url, db_name)
    db = MongoClient(url, serverSelectionTimeoutMS=3000)[db_name]
    before = {name: db[name].count_documents({}) for name in sorted(db.list_collection_names())}
    report = migrate(db)
    after = {name: db[name].count_documents({}) for name in sorted(db.list_collection_names())}
    print("\nCounts before:", before)
    print("Counts after: ", after)
    for key, value in report.items():
        print(f"{key}: {value}")
    if report["transactions_without_profile"]:
        print("ERROR: some transactions have no profile_id.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
