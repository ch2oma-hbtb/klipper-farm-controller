"""FastAPI app: REST API + static dashboard"""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .config import BASE_DIR, UPLOAD_DIR, DEFAULT_MOONRAKER_PORT
from .discovery import scan_network
from .manager import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("farm.api")

STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await manager.start()
    yield
    await manager.stop()


app = FastAPI(title="Klipper Farm Controller", lifespan=lifespan)


# ---------------- schemas ----------------

class PrinterIn(BaseModel):
    name: str
    host: str
    port: int = DEFAULT_MOONRAKER_PORT
    api_key: str = ""
    notes: str = ""


class PrinterPatch(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    api_key: str | None = None
    notes: str | None = None
    enabled: bool | None = None


class GcodeIn(BaseModel):
    script: str = Field(min_length=1)


class PrintIn(BaseModel):
    filename: str


class DiscoverIn(BaseModel):
    cidr: str = "192.168.1.0/24"
    port: int = DEFAULT_MOONRAKER_PORT


def _printer_or_404(pid: str) -> dict:
    p = db.get_printer(pid)
    if not p:
        raise HTTPException(404, "ไม่พบเครื่องพิมพ์")
    return p


async def _mr_action(pid: str, action: str, *args):
    p = _printer_or_404(pid)
    client = manager.client_for(p)
    try:
        result = await getattr(client, action)(*args)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(502, f"ติดต่อเครื่องพิมพ์ไม่สำเร็จ: {e}")


def _safe_gcode_name(name: str) -> str:
    name = Path(name).name  # ตัด path ทิ้ง กัน traversal
    if not name.lower().endswith((".gcode", ".gco", ".g")):
        raise HTTPException(400, "รับเฉพาะไฟล์ .gcode / .gco / .g")
    return name


# ---------------- state ----------------

@app.get("/api/state")
async def get_state():
    printers = []
    for p in db.list_printers():
        pub = {k: v for k, v in p.items() if k != "api_key"}
        pub["has_api_key"] = bool(p.get("api_key"))
        pub["live"] = manager.live.get(p["id"], {"online": False})
        printers.append(pub)
    jobs = db.list_jobs()
    for j in jobs:
        j.pop("stored_path", None)
    return {"printers": printers, "jobs": jobs, "server_time": time.time()}


# ---------------- printers ----------------

@app.post("/api/printers")
async def add_printer(body: PrinterIn):
    # ทดสอบการเชื่อมต่อก่อนบันทึก
    tmp = {"host": body.host, "port": body.port, "api_key": body.api_key}
    try:
        info = await manager.client_for(tmp).server_info()
    except Exception as e:
        raise HTTPException(502, f"เชื่อมต่อ Moonraker ที่ {body.host}:{body.port} ไม่ได้: {e}")
    p = db.add_printer(body.name, body.host, body.port, body.api_key, body.notes)
    return {"ok": True, "printer": p, "moonraker_version": info.get("moonraker_version")}


@app.patch("/api/printers/{pid}")
async def patch_printer(pid: str, body: PrinterPatch):
    _printer_or_404(pid)
    db.update_printer(pid, **body.model_dump(exclude_none=True))
    return {"ok": True, "printer": db.get_printer(pid)}


@app.delete("/api/printers/{pid}")
async def remove_printer(pid: str):
    _printer_or_404(pid)
    db.delete_printer(pid)
    return {"ok": True}


@app.post("/api/printers/{pid}/clear")
async def printer_clear(pid: str):
    """ยืนยันว่าเอาชิ้นงานออกจากแท่นแล้ว — ปลดล็อกให้รับงานถัดไปจากคิว"""
    _printer_or_404(pid)
    db.update_printer(pid, waiting_clear=0)
    log.info("printer %s cleared — ready for next job", pid)
    return {"ok": True}


@app.get("/api/printers/{pid}/files")
async def printer_files(pid: str):
    return await _mr_action(pid, "list_files")


@app.post("/api/printers/{pid}/print")
async def printer_print(pid: str, body: PrintIn):
    return await _mr_action(pid, "start_print", body.filename)


@app.post("/api/printers/{pid}/pause")
async def printer_pause(pid: str):
    return await _mr_action(pid, "pause")


@app.post("/api/printers/{pid}/resume")
async def printer_resume(pid: str):
    return await _mr_action(pid, "resume")


@app.post("/api/printers/{pid}/cancel")
async def printer_cancel(pid: str):
    return await _mr_action(pid, "cancel")


@app.post("/api/printers/{pid}/estop")
async def printer_estop(pid: str):
    return await _mr_action(pid, "emergency_stop")


@app.post("/api/printers/{pid}/firmware_restart")
async def printer_fw_restart(pid: str):
    return await _mr_action(pid, "firmware_restart")


@app.post("/api/printers/{pid}/gcode")
async def printer_gcode(pid: str, body: GcodeIn):
    return await _mr_action(pid, "gcode", body.script)


@app.post("/api/printers/{pid}/upload")
async def printer_upload(pid: str, file: UploadFile = File(...), print_now: bool = Form(False)):
    """อัปโหลดตรงเข้าเครื่องเดียว (ไม่ผ่านคิว) แล้วสั่งพิมพ์ได้เลย"""
    p = _printer_or_404(pid)
    name = _safe_gcode_name(file.filename or "upload.gcode")
    tmp = UPLOAD_DIR / f"direct_{uuid.uuid4().hex[:8]}_{name}"
    try:
        tmp.write_bytes(await file.read())
        client = manager.client_for(p)
        await client.upload(tmp, name, start_print=False)
        if print_now:
            await client.start_print(name)
        return {"ok": True, "filename": name, "printing": print_now}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"อัปโหลดไม่สำเร็จ: {e}")
    finally:
        tmp.unlink(missing_ok=True)


# ---------------- job queue ----------------

@app.post("/api/jobs")
async def enqueue_job(file: UploadFile = File(...), copies: int = Form(1)):
    """อัปโหลด G-code เข้าคิวกลาง — ระบบจะส่งไปเครื่องว่างเองอัตโนมัติ"""
    name = _safe_gcode_name(file.filename or "upload.gcode")
    if copies < 1 or copies > 500:
        raise HTTPException(400, "copies ต้องอยู่ระหว่าง 1-500")
    stored = f"{uuid.uuid4().hex[:10]}_{name}"
    (UPLOAD_DIR / stored).write_bytes(await file.read())
    job = db.add_job(name, stored, copies)
    return {"ok": True, "job": job}


@app.delete("/api/jobs/{jid}")
async def cancel_job(jid: str):
    job = db.get_job(jid)
    if not job:
        raise HTTPException(404, "ไม่พบงาน")
    if job["status"] == "queued":
        db.update_job(jid, status="canceled", finished_at=time.time())
    elif job["status"] in ("uploading", "printing") and job["printer_id"]:
        p = db.get_printer(job["printer_id"])
        if p:
            try:
                await manager.client_for(p).cancel()
            except Exception as e:
                raise HTTPException(502, f"สั่งยกเลิกที่เครื่องพิมพ์ไม่สำเร็จ: {e}")
        db.update_job(jid, status="canceled", finished_at=time.time())
    else:
        raise HTTPException(400, f"งานสถานะ {job['status']} ยกเลิกไม่ได้")
    return {"ok": True}


@app.post("/api/jobs/{jid}/requeue")
async def requeue_job(jid: str):
    job = db.get_job(jid)
    if not job:
        raise HTTPException(404, "ไม่พบงาน")
    if job["status"] not in ("failed", "canceled", "done"):
        raise HTTPException(400, "requeue ได้เฉพาะงานที่จบแล้ว (done/failed/canceled)")
    db.update_job(jid, status="queued", printer_id=None, error="", started_at=None, finished_at=None)
    return {"ok": True}


# ---------------- discovery ----------------

@app.post("/api/discover")
async def discover(body: DiscoverIn):
    try:
        found = await scan_network(body.cidr, body.port)
    except ValueError as e:
        raise HTTPException(400, str(e))
    known = {(p["host"], p["port"]) for p in db.list_printers()}
    for f in found:
        f["already_added"] = (f["host"], f["port"]) in known
    return {"ok": True, "found": found}


# ---------------- dashboard ----------------

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
