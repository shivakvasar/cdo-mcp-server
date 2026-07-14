# src/data.py  — tiny in-memory store backed by data.json
import json, pathlib

DB_PATH = pathlib.Path(__file__).parent.parent / "data" / "db.json"

# Holds the loaded data after the first read. None means "not loaded yet".
# Using a module-level variable means all callers share the same copy in memory
# instead of each one reading from disk.
_db: dict | None = None


def _load() -> dict:
    # DB_PATH.exists() returns False if the file or its parent directory doesn't
    # exist yet, so no mkdir needed here — we just return the default structure.
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text())
    return {"customers": [], "jobs": [], "invoices": [], "tasks": []}


def _save(db: dict):
    # mkdir is only needed when we write, so we do it here instead of at
    # import time. exist_ok=True means no error if the folder already exists.
    DB_PATH.parent.mkdir(exist_ok=True)
    DB_PATH.write_text(json.dumps(db, indent=2))


def get_db() -> dict:
    # global tells Python we want to assign to the module-level _db variable,
    # not create a new local one inside this function.
    global _db
    if _db is None:
        _db = _load()
    return _db


def write_db(db: dict):
    global _db
    _db = db   # keep the in-memory cache in sync with what we're saving
    _save(db)