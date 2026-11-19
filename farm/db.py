"""SQLite persistence: printers + job queue + farm/shelf layout"""
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
    CREATE TABLE IF NOT EXISTS farms (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        notes TEXT DEFAULT '',
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS shelves (
        id TEXT PRIMARY KEY,
        farm_id TEXT NOT NULL,
        name TEXT NOT NULL,
        slots INTEGER NOT NULL DEFAULT 4,
        created_at REAL NOT NULL
    );
    """
)
# migration: เพิ่มคอลัมน์ใหม่สำหรับ DB เดิม
_cols = {r[1] for r in _conn.execute("PRAGMA table_info(printers)")}
if "waiting_clear" not in _cols:
    _conn.execute("ALTER TABLE printers ADD COLUMN waiting_clear INTEGER NOT NULL DEFAULT 0")
if "shelf_id" not in _cols:
    _conn.execute("ALTER TABLE printers ADD COLUMN shelf_id TEXT")
if "position" not in _cols:
    _conn.execute("ALTER TABLE printers ADD COLUMN position INTEGER")
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


def set_printer_location(pid: str, shelf_id: Optional[str], position: Optional[int]):
    """กำหนด/ยกเลิกตำแหน่งเครื่องบนชั้นวาง (validation ทำที่ชั้น API)"""
    _conn.execute("UPDATE printers SET shelf_id=?, position=? WHERE id=?", (shelf_id, position, pid))
    _conn.commit()


def printer_at(shelf_id: str, position: int) -> Optional[dict]:
    row = _conn.execute(
        "SELECT * FROM printers WHERE shelf_id=? AND position=?", (shelf_id, position)
    ).fetchone()
    return dict(row) if row else None


# ---------- farms / shelves (ผังตำแหน่งเครื่อง) ----------

def add_farm(name: str, notes: str = "") -> dict:
    fid = uuid.uuid4().hex[:12]
    _conn.execute(
        "INSERT INTO farms (id,name,notes,created_at) VALUES (?,?,?,?)",
        (fid, name, notes, time.time()),
    )
    _conn.commit()
    return get_farm(fid)


def get_farm(fid: str) -> Optional[dict]:
    row = _conn.execute("SELECT * FROM farms WHERE id=?", (fid,)).fetchone()
    return dict(row) if row else None


def list_farms() -> list[dict]:
    return _rows(_conn.execute("SELECT * FROM farms ORDER BY created_at"))


def update_farm(fid: str, **fields):
    allowed = {"name", "notes"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sql = "UPDATE farms SET " + ",".join(f"{k}=?" for k in sets) + " WHERE id=?"
    _conn.execute(sql, (*sets.values(), fid))
    _conn.commit()


def delete_farm(fid: str):
    """ลบฟาร์มพร้อมชั้นวางทั้งหมด — เครื่องพิมพ์ถูกเอาออกจากผัง (ไม่ถูกลบ)"""
    for shelf in list_shelves(fid):
        delete_shelf(shelf["id"])
    _conn.execute("DELETE FROM farms WHERE id=?", (fid,))
    _conn.commit()


def add_shelf(farm_id: str, name: str, slots: int = 4) -> dict:
    sid = uuid.uuid4().hex[:12]
    _conn.execute(
        "INSERT INTO shelves (id,farm_id,name,slots,created_at) VALUES (?,?,?,?,?)",
        (sid, farm_id, name, slots, time.time()),
    )
    _conn.commit()
    return get_shelf(sid)


def get_shelf(sid: str) -> Optional[dict]:
    row = _conn.execute("SELECT * FROM shelves WHERE id=?", (sid,)).fetchone()
    return dict(row) if row else None


def list_shelves(farm_id: Optional[str] = None) -> list[dict]:
    if farm_id is None:
        return _rows(_conn.execute("SELECT * FROM shelves ORDER BY created_at"))
    return _rows(
        _conn.execute("SELECT * FROM shelves WHERE farm_id=? ORDER BY created_at", (farm_id,))
    )


def update_shelf(sid: str, **fields):
    allowed = {"name", "slots", "farm_id"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sql = "UPDATE shelves SET " + ",".join(f"{k}=?" for k in sets) + " WHERE id=?"
    _conn.execute(sql, (*sets.values(), sid))
    _conn.commit()


def delete_shelf(sid: str):
    """ลบชั้นวาง — เครื่องที่อยู่บนชั้นถูกเอาออกจากผัง (ไม่ถูกลบ)"""
    _conn.execute("UPDATE printers SET shelf_id=NULL, position=NULL WHERE shelf_id=?", (sid,))
    _conn.execute("DELETE FROM shelves WHERE id=?", (sid,))
    _conn.commit()


def max_occupied_position(sid: str) -> int:
    row = _conn.execute(
        "SELECT MAX(position) FROM printers WHERE shelf_id=?", (sid,)
    ).fetchone()
    return row[0] or 0


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
