"""Profiles: one person's transactions and cash. Instruments, prices and FX stay shared.

Every per-person read and write goes through a Scope from get_scope(), the one
dependency that resolves the active profile. Its `transactions` only ever see that
profile's documents, so a route cannot query across profiles by accident.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from bson import json_util
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import backups
from app.db import get_db

PROFILE_HEADER = "X-Profile-Id"
DEFAULT_COLOUR = "#2563eb"
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")

router = APIRouter(prefix="/api/profiles")


def name_key(name: str) -> str:
    """Names are unique ignoring case and repeated spaces."""
    return " ".join(name.split()).casefold()


# Migration ----------------------------------------------------------------------------

def migrate(db, name: str = "Aditya", colour: str = DEFAULT_COLOUR) -> dict:
    """Create the default profile and tag existing per-person data with it.

    Only adds documents and fields, and only where they are missing, so running it
    again changes nothing.
    """
    created = False
    default = db.profiles.find_one({"is_default": True})
    if default is None:
        legacy = db.settings.find_one({"_id": "portfolio"}) or {}
        default = {
            "_id": str(uuid.uuid4()),
            "name": name,
            "name_key": name_key(name),
            "colour": colour,
            "is_default": True,
            "created_at": datetime.now(timezone.utc),
            "cash_inr": legacy.get("cash_inr", 0),
        }
        db.profiles.insert_one(default)
        created = True

    tagged = db.transactions.update_many(
        {"profile_id": {"$exists": False}}, {"$set": {"profile_id": default["_id"]}}
    ).modified_count
    db.transactions.create_index("profile_id")
    db.profiles.create_index("name_key", unique=True)
    return {
        "default_profile_id": default["_id"],
        "created_default_profile": created,
        "transactions_tagged": tagged,
        "transactions_without_profile": db.transactions.count_documents(
            {"profile_id": {"$exists": False}}
        ),
    }


# Active profile -----------------------------------------------------------------------

def default_profile(db) -> dict:
    profile = db.profiles.find_one({"is_default": True})
    if profile is None:
        raise HTTPException(
            503, "No default profile. Run: .venv\\Scripts\\python scripts\\migrate_profiles.py"
        )
    return profile


def resolve_profile(db, profile_id: Optional[str]) -> dict:
    """The profile with this id, or the default one when it is missing or unknown."""
    if profile_id:
        found = db.profiles.find_one({"_id": profile_id})
        if found is not None:
            return found
    return default_profile(db)


class ScopedTransactions:
    """db.transactions limited to one profile. Every filter gets profile_id added,
    and inserted or replaced documents always carry it."""

    def __init__(self, collection, profile_id: str):
        self._collection = collection
        self.profile_id = profile_id

    def _filter(self, query: Optional[dict]) -> dict:
        return {**(query or {}), "profile_id": self.profile_id}

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None):
        return self._collection.find(self._filter(query), projection)

    def find_one(self, query: Optional[dict] = None):
        return self._collection.find_one(self._filter(query))

    def count_documents(self, query: Optional[dict] = None) -> int:
        return self._collection.count_documents(self._filter(query))

    def insert_one(self, doc: dict):
        return self._collection.insert_one({**doc, "profile_id": self.profile_id})

    def replace_one(self, query: dict, doc: dict):
        return self._collection.replace_one(self._filter(query), {**doc, "profile_id": self.profile_id})

    def delete_one(self, query: dict):
        return self._collection.delete_one(self._filter(query))


@dataclass
class Scope:
    db: object
    profile: dict

    @property
    def transactions(self) -> ScopedTransactions:
        return ScopedTransactions(self.db.transactions, self.profile["_id"])

    @property
    def cash_inr(self) -> float:
        return self.profile.get("cash_inr", 0)

    def set_cash(self, value: float) -> None:
        self.db.profiles.update_one({"_id": self.profile["_id"]}, {"$set": {"cash_inr": value}})
        self.profile = {**self.profile, "cash_inr": value}


def scope_for(db, profile_id: Optional[str] = None) -> Scope:
    return Scope(db, resolve_profile(db, profile_id))


def get_scope(
    db=Depends(get_db),
    profile_id: Optional[str] = Header(default=None, alias=PROFILE_HEADER),
) -> Scope:
    """The single dependency for per-person routes. Missing or unknown id -> default."""
    return scope_for(db, profile_id)


def public(profile: dict, db=None) -> dict:
    view = {
        "id": profile["_id"],
        "name": profile["name"],
        "colour": profile["colour"],
        "is_default": profile["is_default"],
        "created_at": profile["created_at"],
    }
    if db is not None:
        view["transaction_count"] = db.transactions.count_documents({"profile_id": profile["_id"]})
    return view


# Profile API --------------------------------------------------------------------------

def _check_colour(value: Optional[str]) -> Optional[str]:
    if value is not None and not COLOUR.fullmatch(value):
        raise ValueError("colour must look like #1a2b3c")
    return value


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    colour: str = DEFAULT_COLOUR

    _colour = field_validator("colour")(_check_colour)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    colour: Optional[str] = None

    _colour = field_validator("colour")(_check_colour)


def _clean_name(db, name: str, own_id: Optional[str] = None) -> str:
    name = " ".join(name.split())
    if not name:
        raise HTTPException(422, "name cannot be blank.")
    clash = db.profiles.find_one({"name_key": name_key(name)})
    if clash is not None and clash["_id"] != own_id:
        raise HTTPException(409, f"A profile named {clash['name']} already exists.")
    return name


def _profile(db, profile_id: str) -> dict:
    profile = db.profiles.find_one({"_id": profile_id})
    if profile is None:
        raise HTTPException(404, f"Profile {profile_id} not found.")
    return profile


def _write_lock():
    from app.api import WRITE_LOCK  # shared with the other writes
    return WRITE_LOCK


@router.get("")
def list_profiles(db=Depends(get_db)):
    docs = sorted(db.profiles.find(), key=lambda p: (not p["is_default"], p["created_at"]))
    return {"profiles": [public(p, db) for p in docs]}


@router.post("", status_code=201)
def create_profile(body: ProfileCreate, db=Depends(get_db)):
    with _write_lock():
        name = _clean_name(db, body.name)
        doc = {
            "_id": str(uuid.uuid4()),
            "name": name,
            "name_key": name_key(name),
            "colour": body.colour,
            "is_default": False,
            "created_at": datetime.now(timezone.utc),
            "cash_inr": 0,
        }
        db.profiles.insert_one(doc)
        backup = backups.after_write(db)
        return {"profile": public(doc, db), "backup": backup["file"], "warnings": backup["warnings"]}


@router.patch("/{profile_id}")
def update_profile(profile_id: str, body: ProfileUpdate, db=Depends(get_db)):
    with _write_lock():
        profile = _profile(db, profile_id)
        changes = body.model_dump(exclude_unset=True)
        if not changes or any(value is None for value in changes.values()):
            raise HTTPException(422, "Send a name or a colour.")
        if "name" in changes:
            changes["name"] = _clean_name(db, changes["name"], profile_id)
            changes["name_key"] = name_key(changes["name"])
        db.profiles.update_one({"_id": profile_id}, {"$set": changes})
        backup = backups.after_write(db)
        return {"profile": public({**profile, **changes}, db),
                "backup": backup["file"], "warnings": backup["warnings"]}


@router.delete("/{profile_id}")
def delete_profile(profile_id: str, db=Depends(get_db)):
    """Saves the profile and its transactions to a JSON file first; deletes nothing if
    that file can't be written."""
    with _write_lock():
        profile = _profile(db, profile_id)
        if profile["is_default"]:
            raise HTTPException(409, "The default profile cannot be deleted.")
        transactions = list(db.transactions.find({"profile_id": profile_id}))
        text = json_util.dumps(
            {"profile": profile, "transactions": transactions},
            indent=2, json_options=json_util.CANONICAL_JSON_OPTIONS,
        )
        slug = re.sub(r"[^a-z0-9]+", "-", profile["name_key"]).strip("-") or "profile"
        try:
            path = backups.write_profile_backup(f"profile-{slug}-{datetime.now():%Y%m%d-%H%M%S}", text)
        except OSError as exc:
            raise HTTPException(500, f"Backup was not saved ({exc}). Nothing was deleted.") from exc

        removed = db.transactions.delete_many({"profile_id": profile_id}).deleted_count
        db.profiles.delete_one({"_id": profile_id})
        backup = backups.after_write(db)
        return {
            "deleted": profile_id,
            "transactions_removed": removed,
            "profile_backup": str(path),
            "backup": backup["file"],
            "warnings": backup["warnings"],
        }
