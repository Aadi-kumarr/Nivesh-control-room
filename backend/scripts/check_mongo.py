"""Used by start.bat: exit 1 with a clear message if MongoDB can't be reached."""
import sys
from pathlib import Path

from pymongo.errors import PyMongoError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import get_db  # noqa: E402


def main() -> int:
    db = get_db()
    try:
        db.command("ping")
    except PyMongoError:
        print("MongoDB is not reachable at the MONGO_URL in backend\\.env.")
        print("Start it, then try again:")
        print("  - Open Services and start 'MongoDB', or")
        print("  - In an admin terminal, run: net start MongoDB")
        return 1
    print(f"MongoDB is running. Database: {db.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
