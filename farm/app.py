"""FastAPI app: REST API + static dashboard"""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, db
from .config import BASE_DIR, UPLOAD_DIR, DEFAULT_MOONRAKER_PORT, AI_TOKEN, AI_MAX_IMAGE_MB
from .discovery import scan_network
from .manager import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("farm.api")

STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await manager.start()
    ai.detector = ai.AIDetector(manager.http)
    yield
    ai.detector = None
    await manager.stop()


app = FastAPI(title="Klipper Farm Controller", lifespan=lifespan)


# ---------------- schemas ----------------

class PrinterIn(BaseModel):
    name: str
    host: str
    port: int = DEFAULT_MOONRAKER_PORT
    api_key: str = ""
    notes: str = ""
    shelf_id: str | None = None
    position: int | None = None


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


class FarmIn(BaseModel):
    name: str = Field(min_length=1)
    notes: str = ""


class FarmPatch(BaseModel):
    name: str | None = None
    notes: str | None = None


class ShelfIn(BaseModel):
    name: str = Field(min_length=1)
    slots: int = Field(default=4, ge=1, le=200)


class ShelfPatch(BaseModel):
    name: str | None = None
    slots: int | None = Field(default=None, ge=1, le=200)
    farm_id: str | None = None


class LocationIn(BaseModel):
    shelf_id: str | None = None
    position: int | None = None


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


def _validate_location(shelf_id: str | None, position: int | None, pid: str | None = None):
    """ตรวจตำแหน่งที่จะวางเครื่อง: ชั้นมีจริง, ช่องในช่วง, ไม่ซ้ำกับเครื่องอื่น"""
    if shelf_id is None:
        return None, None
    shelf = db.get_shelf(shelf_id)
    if not shelf:
        raise HTTPException(404, "ไม่พบชั้นวางนี้")
    if position is None:
        raise HTTPException(400, "ระบุหมายเลขช่องบนชั้นวางด้วย")
    if not 1 <= position <= shelf["slots"]:
        raise HTTPException(400, f"ชั้นวางนี้มี {shelf['slots']} ช่อง (ระบุได้ 1-{shelf['slots']})")
    occupant = db.printer_at(shelf_id, position)
    if occupant and occupant["id"] != pid:
        raise HTTPException(409, f"ช่อง {position} ถูกใช้โดย \"{occupant['name']}\" อยู่แล้ว")
    return shelf_id, position


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
    farms = db.list_farms()
    for f in farms:
        f["shelves"] = db.list_shelves(f["id"])
    return {"printers": printers, "jobs": jobs, "farms": farms, "server_time": time.time()}


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
    if body.shelf_id is not None:
        shelf_id, position = _validate_location(body.shelf_id, body.position, p["id"])
        db.set_printer_location(p["id"], shelf_id, position)
        p = db.get_printer(p["id"])
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


@app.put("/api/printers/{pid}/location")
async def printer_location(pid: str, body: LocationIn):
    """วางเครื่องลงช่องบนชั้นวาง (shelf_id=null = เอาออกจากผัง)"""
    _printer_or_404(pid)
    shelf_id, position = _validate_location(body.shelf_id, body.position, pid)
    db.set_printer_location(pid, shelf_id, position)
    return {"ok": True, "printer": db.get_printer(pid)}


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


# ---------------- farm layout (farm -> shelf -> ตำแหน่งเครื่อง) ----------------

@app.post("/api/farms")
async def add_farm(body: FarmIn):
    return {"ok": True, "farm": db.add_farm(body.name.strip(), body.notes)}


@app.patch("/api/farms/{fid}")
async def patch_farm(fid: str, body: FarmPatch):
    if not db.get_farm(fid):
        raise HTTPException(404, "ไม่พบฟาร์มนี้")
    db.update_farm(fid, **body.model_dump(exclude_none=True))
    return {"ok": True, "farm": db.get_farm(fid)}


@app.delete("/api/farms/{fid}")
async def remove_farm(fid: str):
    if not db.get_farm(fid):
        raise HTTPException(404, "ไม่พบฟาร์มนี้")
    db.delete_farm(fid)  # ชั้นวางถูกลบ, เครื่องพิมพ์แค่หลุดจากผัง
    return {"ok": True}


@app.post("/api/farms/{fid}/shelves")
async def add_shelf(fid: str, body: ShelfIn):
    if not db.get_farm(fid):
        raise HTTPException(404, "ไม่พบฟาร์มนี้")
    return {"ok": True, "shelf": db.add_shelf(fid, body.name.strip(), body.slots)}


@app.patch("/api/shelves/{sid}")
async def patch_shelf(sid: str, body: ShelfPatch):
    shelf = db.get_shelf(sid)
    if not shelf:
        raise HTTPException(404, "ไม่พบชั้นวางนี้")
    fields = body.model_dump(exclude_none=True)
    if "farm_id" in fields and not db.get_farm(fields["farm_id"]):
        raise HTTPException(404, "ไม่พบฟาร์มปลายทาง")
    if "slots" in fields:
        occupied = db.max_occupied_position(sid)
        if fields["slots"] < occupied:
            raise HTTPException(400, f"ลดจำนวนช่องไม่ได้ — มีเครื่องวางอยู่ถึงช่อง {occupied}")
    db.update_shelf(sid, **fields)
    return {"ok": True, "shelf": db.get_shelf(sid)}


@app.delete("/api/shelves/{sid}")
async def remove_shelf(sid: str):
    if not db.get_shelf(sid):
        raise HTTPException(404, "ไม่พบชั้นวางนี้")
    db.delete_shelf(sid)  # เครื่องบนชั้นแค่หลุดจากผัง ไม่ถูกลบ
    return {"ok": True}


# ---------------- AI failure detection ----------------

@app.post("/api/ai/detect")
async def ai_detect(request: Request, image: UploadFile = File(...)):
    """รับภาพจากปลั๊กอิน klipper-ai-failure-detection -> คืน failure probability

    ปลั๊กอินตั้ง api_url มาที่นี่ เช่น http://<farm-server>:8000/api/ai/detect
    """
    if AI_TOKEN and request.headers.get("authorization", "") != f"Bearer {AI_TOKEN}":
        raise HTTPException(401, "token ไม่ถูกต้อง (ตั้ง api_key ในปลั๊กอินให้ตรงกัน)")
    data = await image.read()
    if not data:
        raise HTTPException(400, "ไม่พบข้อมูลภาพ")
    if len(data) > AI_MAX_IMAGE_MB * 1024 * 1024:
        raise HTTPException(413, f"ภาพใหญ่เกิน {AI_MAX_IMAGE_MB:.0f} MB")
    if ai.detector is None:
        raise HTTPException(503, "AI service ยังไม่พร้อม")
    try:
        result = await ai.detector.detect(data, image.content_type or "image/jpeg")
    except ai.AIError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(502, f"เรียก AI backend ไม่สำเร็จ: {e}")
    return {"ok": True, **result}


@app.get("/api/ai/status")
async def ai_status():
    s = ai.status()
    s["token_required"] = bool(AI_TOKEN)
    s["stats"] = ai.detector.stats if ai.detector else None
    return s


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
