"""MongoDB connection, configured from backend/.env."""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.database import Database

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@lru_cache(maxsize=1)
def _client() -> MongoClient:
    return MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=3000)


def get_db() -> Database:
    return _client()[os.environ["DB_NAME"]]
