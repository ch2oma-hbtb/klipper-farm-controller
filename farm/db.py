"""SQLite persistence: printers + job queue"""
import sqlite3
import time
import uuid
from typing import Optional

from .config import DB_PATH

_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS printers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        host TEXT NOT NULL,
        port INTEGER NOT NULL DEFAULT 7125,
        api_key TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        waiting_clear INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        stored_path TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        printer_id TEXT,
        copies INTEGER NOT NULL DEFAULT 1,
        created_at REAL NOT NULL,
        started_at REAL,
        finished_at REAL,
        error TEXT DEFAULT ''
    );
    """
)
# migration: เพิ่มคอลัมน์ waiting_clear สำหรับ DB เดิม
_cols = {r[1] for r in _conn.execute("PRAGMA table_info(printers)")}
if "waiting_clear" not in _cols:
    _conn.execute("ALTER TABLE printers ADD COLUMN waiting_clear INTEGER NOT NULL DEFAULT 0")
_conn.commit()


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ---------- printers ----------

def add_printer(name: str, host: str, port: int, api_key: str = "", notes: str = "") -> dict:
    pid = uuid.uuid4().hex[:12]
    _conn.execute(
        "INSERT INTO printers (id,name,host,port,api_key,notes,created_at) VALUES (?,?,?,?,?,?,?)",
        (pid, name, host, port, api_key, notes, time.time()),
    )
    _conn.commit()
    return get_printer(pid)


def get_printer(pid: str) -> Optional[dict]:
    cur = _conn.execute("SELECT * FROM printers WHERE id=?", (pid,))
    row = cur.fetchone()
    return dict(row) if row else None


def list_printers() -> list[dict]:
    return _rows(_conn.execute("SELECT * FROM printers ORDER BY created_at"))


def update_printer(pid: str, **fields):
    allowed = {"name", "host", "port", "api_key", "notes", "enabled", "waiting_clear"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sql = "UPDATE printers SET " + ",".join(f"{k}=?" for k in sets) + " WHERE id=?"
    _conn.execute(sql, (*sets.values(), pid))
    _conn.commit()


def delete_printer(pid: str):
    _conn.execute("DELETE FROM printers WHERE id=?", (pid,))
    _conn.commit()


# ---------- jobs ----------

def add_job(filename: str, stored_path: str, copies: int = 1) -> dict:
    jid = uuid.uuid4().hex[:12]
    _conn.execute(
        "INSERT INTO jobs (id,filename,stored_path,copies,created_at) VALUES (?,?,?,?,?)",
        (jid, filename, stored_path, copies, time.time()),
    )
    _conn.commit()
    return get_job(jid)


def get_job(jid: str) -> Optional[dict]:
    row = _conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 200) -> list[dict]:
    return _rows(
        _conn.execute(
            "SELECT * FROM jobs ORDER BY (status IN ('queued','uploading','printing')) DESC, created_at DESC LIMIT ?",
            (limit,),
        )
    )


def update_job(jid: str, **fields):
    allowed = {"status", "printer_id", "started_at", "finished_at", "error", "copies"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sql = "UPDATE jobs SET " + ",".join(f"{k}=?" for k in sets) + " WHERE id=?"
    _conn.execute(sql, (*sets.values(), jid))
    _conn.commit()


def queued_jobs() -> list[dict]:
    return _rows(
        _conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at")
    )


def active_jobs() -> list[dict]:
    return _rows(
        _conn.execute("SELECT * FROM jobs WHERE status IN ('uploading','printing')")
    )
