import json
from datetime import datetime
from pathlib import Path

import pytest
from bson import json_util

import restore_backup
from app import backups
from conftest import trade


def auto_files(root):
    return sorted((root / "auto").glob("*.json"))


def snapshot_ids(path, collection):
    return {doc["_id"] for doc in json_util.loads(path.read_text(encoding="utf-8"))[collection]}


WRITES = {
    "transaction create": lambda c, i, t: trade(c, i, "2026-01-02", "BUY", 1),
    "transaction update": lambda c, i, t: c.patch(f"/api/transactions/{t}", json={"note": "x"}),
    "transaction delete": lambda c, i, t: c.delete(f"/api/transactions/{t}"),
    "instrument create": lambda c, i, t: c.post("/api/instruments", json={
        "asset_class": "fno", "name": "NEW", "price_source": "manual"}),
    "instrument update": lambda c, i, t: c.patch(f"/api/instruments/{i}", json={"needs_review": True}),
    "cash": lambda c, i, t: c.put("/api/cash", json={"cash_inr": 5}),
}


@pytest.mark.parametrize("name", WRITES)
def test_backup_after_every_write_type(client, root, indian, name):
    txn = trade(client, indian, "2026-01-01", "BUY", 5).json()["transaction"]["id"]
    before = len(auto_files(root))
    response = WRITES[name](client, indian, txn)
    assert response.status_code < 300
    assert len(auto_files(root)) == before + 1
    assert response.json()["backup"] in [p.name for p in auto_files(root)]
    assert response.json()["warnings"] == []


def test_backup_after_instrument_delete(client, root, indian):
    before = len(auto_files(root))
    assert client.delete(f"/api/instruments/{indian}").status_code == 200
    assert len(auto_files(root)) == before + 1


def test_snapshot_holds_the_written_data(client, root, indian):
    body = trade(client, indian, "2026-01-01", "BUY", 5).json()
    path = root / "auto" / body["backup"]
    assert body["transaction"]["id"] in snapshot_ids(path, "transactions")


def test_rejected_write_takes_no_backup(client, root, indian):
    before = len(auto_files(root))
    assert trade(client, indian, "2026-01-01", "SELL", 5).status_code == 422
    assert len(auto_files(root)) == before


def test_same_second_snapshots_do_not_collide(db, root):
    names = {backups.after_write(db)["file"] for _ in range(5)}
    assert len(names) == 5


def test_daily_snapshot_once_per_day(client, root):
    client.get("/api/backups")
    client.get("/api/backups")
    assert len(list((root / "daily").glob("*.json"))) == 1


def test_auto_retention_keeps_newest_50_and_other_files(db, root):
    auto = root / "auto"
    auto.mkdir(parents=True)
    for minute in range(55):
        (auto / f"nivesh-20200101-00{minute:02d}00.json").write_text("{}")
    (auto / "nivesh-20200101-000000-1.json").write_text("{}")
    (auto / "keep-me.json").write_text("{}")
    (auto / "notes.txt").write_text("hi")
    (root / "pre-phase2-nivesh-20200101-000000.json").write_text("{}")

    backups.after_write(db)

    numbered = [p for p in auto.glob("nivesh-*.json")]
    assert len(numbered) == 50
    assert not (auto / "nivesh-20200101-000000.json").exists()
    assert not (auto / "nivesh-20200101-000000-1.json").exists()
    assert (auto / "nivesh-20200101-005400.json").exists()
    assert (auto / "keep-me.json").exists()
    assert (auto / "notes.txt").exists()
    assert (root / "pre-phase2-nivesh-20200101-000000.json").exists()


def test_suffixed_snapshot_counts_as_newer(db, root):
    auto = root / "auto"
    auto.mkdir(parents=True)
    (auto / "nivesh-20200101-000000.json").write_text("{}")
    (auto / "nivesh-20200101-000000-1.json").write_text("{}")
    order = sorted(auto.iterdir(), key=backups._auto_order)
    assert order[-1].name == "nivesh-20200101-000000-1.json"


def test_daily_retention_keeps_365(db, root):
    daily = root / "daily"
    daily.mkdir(parents=True)
    for number in range(370):
        day = datetime.fromordinal(730000 + number)
        (daily / f"nivesh-{day:%Y%m%d}.json").write_text("{}")
    (daily / "other.json").write_text("{}")

    backups.ensure_daily(db)

    assert len(list(daily.glob("nivesh-*.json"))) == 365
    assert (daily / "other.json").exists()


def test_mirror_copies_each_snapshot(client, root, tmp_path, monkeypatch, indian):
    mirror = tmp_path / "onedrive"
    monkeypatch.setenv("BACKUP_MIRROR_DIR", str(mirror))
    body = trade(client, indian, "2026-01-01", "BUY", 1).json()
    assert (mirror / "auto" / body["backup"]).exists()


def test_mirror_retention_only_touches_our_names(db, root, tmp_path, monkeypatch):
    mirror = tmp_path / "onedrive"
    auto = mirror / "auto"
    auto.mkdir(parents=True)
    for minute in range(55):
        (auto / f"nivesh-20200101-00{minute:02d}00.json").write_text("{}")
    (auto / "holiday.json").write_text("{}")
    (auto / "nivesh-notes.json").write_text("{}")
    (mirror / "nivesh-20200101-000000.json").write_text("{}")  # outside auto/
    monkeypatch.setenv("BACKUP_MIRROR_DIR", str(mirror))

    backups.after_write(db)

    assert len([p for p in auto.iterdir() if backups.AUTO_NAME.match(p.name)]) == 50
    assert not (auto / "nivesh-20200101-000000.json").exists()
    assert (auto / "holiday.json").exists()
    assert (auto / "nivesh-notes.json").exists()
    assert (mirror / "nivesh-20200101-000000.json").exists()


def test_mirror_daily_retention(db, root, tmp_path, monkeypatch):
    mirror = tmp_path / "onedrive"
    daily = mirror / "daily"
    daily.mkdir(parents=True)
    for number in range(370):
        (daily / f"nivesh-{datetime.fromordinal(730000 + number):%Y%m%d}.json").write_text("{}")
    (daily / "mine.txt").write_text("hi")
    monkeypatch.setenv("BACKUP_MIRROR_DIR", str(mirror))

    backups.ensure_daily(db)

    assert len(list(daily.glob("nivesh-*.json"))) == 365
    assert (daily / "mine.txt").exists()


def test_mirror_failure_is_a_warning(client, root, tmp_path, monkeypatch, indian):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("BACKUP_MIRROR_DIR", str(blocker))
    response = trade(client, indian, "2026-01-01", "BUY", 1)
    assert response.status_code == 201
    assert response.json()["backup"]
    assert "mirror failed" in response.json()["warnings"][0]


def test_backup_failure_keeps_the_write_and_warns(client, db, root, monkeypatch, indian):
    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(backups, "_write_new", fail)
    response = trade(client, indian, "2026-01-01", "BUY", 1)
    assert response.status_code == 201
    assert db.transactions.count_documents({}) == 1
    assert response.json()["backup"] is None
    assert "Backup failed" in response.json()["warnings"][0]
    assert "disk full" in response.json()["warnings"][0]


def test_failed_write_leaves_no_partial_file(root, monkeypatch):
    folder = root / "auto"

    def fail(self, target):
        raise OSError("rename failed")

    monkeypatch.setattr(type(folder), "rename", fail)
    with pytest.raises(OSError):
        backups._write_new(folder, "nivesh-20200101-000000", "{}")
    assert list(folder.iterdir()) == []


def test_export_saves_full_snapshot_in_exports_folder(client, root, indian):
    response = client.post("/api/export")
    assert response.status_code == 200
    path = Path(response.json()["path"])
    assert path.parent == root / "exports"
    assert snapshot_ids(path, "instruments") == {indian}
    assert [f["name"] for f in client.get("/api/backups").json()["exports"]] == [path.name]


def test_exports_in_the_same_second_are_all_kept(client, root, indian):
    paths = {client.post("/api/export").json()["path"] for _ in range(3)}
    assert len(paths) == 3
    assert len(list((root / "exports").glob("*.json"))) == 3


def test_failed_export_reports_the_error(client, indian, monkeypatch):
    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(backups, "_write_new", fail)
    response = client.post("/api/export")
    assert response.status_code == 500
    assert "disk full" in response.json()["detail"]


def test_backups_endpoint_lists_snapshots(client, root, indian):
    (root / "pre-phase2-x.json").write_text("{}")
    body = client.get("/api/backups").json()
    assert len(body["auto"]) == 1
    assert len(body["daily"]) == 1
    assert [f["name"] for f in body["manual"]] == ["pre-phase2-x.json"]


def test_restore_into_new_database(client, mongo, db, root, indian):
    path = root / "auto" / trade(client, indian, "2026-01-01", "BUY", 3).json()["backup"]
    before = list(db.transactions.find())

    name, counts = restore_backup.restore(mongo, path)

    assert name.startswith("nivesh_restore_")
    assert counts == {"instruments": 1, "profiles": 1, "settings": 1, "transactions": 1}
    restored = mongo[name]
    assert list(restored.transactions.find()) == before
    assert restored.transactions.find_one()["quantity"] == 3
    assert list(db.transactions.find()) == before  # source database untouched


def test_restore_never_reuses_an_existing_database(mongo, db, root, tmp_path, monkeypatch):
    snapshot = tmp_path / "s.json"
    snapshot.write_text(backups.snapshot_text(db), encoding="utf-8")

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 0, 0, 0)

    monkeypatch.setattr(restore_backup, "datetime", Frozen)
    restore_backup.restore(mongo, snapshot)
    with pytest.raises(SystemExit, match="already exists"):
        restore_backup.restore(mongo, snapshot)


def test_restore_rejects_non_snapshot(mongo, tmp_path):
    master_shape = tmp_path / "x.json"
    master_shape.write_text(json.dumps({"cash": 0, "assetClasses": []}))
    with pytest.raises(SystemExit, match="not a database snapshot"):
        restore_backup.restore(mongo, master_shape)
