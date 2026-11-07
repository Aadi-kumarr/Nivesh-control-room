"""Restore a snapshot into a NEW database. Never touches the live database.

Run from backend/:  .venv\\Scripts\\python scripts\\restore_backup.py <snapshot.json>
"""
import os
import sys
from datetime import datetime
from pathlib import Path

from bson import json_util
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.db  # noqa: E402,F401  (loads backend/.env)


def load_snapshot(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        snapshot = json_util.loads(file.read())
    valid = isinstance(snapshot, dict) and snapshot and all(
        isinstance(docs, list) for docs in snapshot.values()
    )
    if not valid:
        raise SystemExit(f"{path} is not a database snapshot.")
    return snapshot


def restore(client, path: Path) -> tuple:
    """Copy the snapshot into nivesh_restore_<timestamp>. Returns (name, counts)."""
    snapshot = load_snapshot(path)
    name = f"nivesh_restore_{datetime.now():%Y%m%d_%H%M%S}"
    if name in client.list_database_names():
        raise SystemExit(f"Database {name} already exists. Nothing was restored.")

    db = client[name]
    for collection, docs in snapshot.items():
        if docs:
            db[collection].insert_many(docs)
        else:
            db.create_collection(collection)

    expected = {collection: len(docs) for collection, docs in snapshot.items()}
    found = {collection: db[collection].count_documents({}) for collection in snapshot}
    if found != expected:
        raise SystemExit(f"Count check failed in {name}: expected {expected}, found {found}.")
    return name, found


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: restore_backup.py <snapshot.json>")
        return 1
    client = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=3000)
    name, counts = restore(client, Path(sys.argv[1]))
    print(f"Restored into new database '{name}'. Counts match the snapshot:")
    for collection, count in counts.items():
        print(f"  {collection}: {count}")
    print(f"\nTo use it, set this in backend/.env and restart the API:\n  DB_NAME={name}")
    print(f"The database '{os.environ['DB_NAME']}' was not changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
