"""Farm manager: poll สถานะทุกเครื่อง + scheduler จัดคิวงานไปเครื่องว่างอัตโนมัติ"""
import asyncio
import logging
import time

import httpx

from . import db
from .config import POLL_INTERVAL, SCHED_INTERVAL, UPLOAD_DIR
from .moonraker import build_client, snapshot_from_status, is_idle

log = logging.getLogger("farm")


class FarmManager:
    def __init__(self):
        self.http: httpx.AsyncClient | None = None
        # printer_id -> snapshot ล่าสุด
        self.live: dict[str, dict] = {}
        # printer_id ที่กำลังถูกจองเพื่อส่งงาน (กันassignซ้ำระหว่างอัปโหลด)
        self.reserved: set[str] = set()
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        self.http = httpx.AsyncClient(limits=httpx.Limits(max_connections=100))
        self._tasks = [
            asyncio.create_task(self._poll_loop()),
            asyncio.create_task(self._sched_loop()),
        ]

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        if self.http:
            await self.http.aclose()

    def client_for(self, printer: dict):
        return build_client(self.http, printer)

    # ---------------- polling ----------------

    async def _poll_loop(self):
        while True:
            try:
                printers = db.list_printers()
                await asyncio.gather(*(self._poll_one(p) for p in printers))
                # ลบ snapshot ของเครื่องที่ถูกลบไปแล้ว
                ids = {p["id"] for p in printers}
                for pid in list(self.live):
                    if pid not in ids:
                        self.live.pop(pid, None)
            except Exception:
                log.exception("poll loop error")
            await asyncio.sleep(POLL_INTERVAL)

    async def _poll_one(self, p: dict):
        pid = p["id"]
        if not p["enabled"]:
            self.live[pid] = {"online": False, "disabled": True}
            return
        try:
            raw = await self.client_for(p).status()
            snap = snapshot_from_status(raw)
            snap["online"] = True
            snap["updated_at"] = time.time()
            self.live[pid] = snap
        except Exception as e:
            prev = self.live.get(pid, {})
            self.live[pid] = {
                **prev,
                "online": False,
                "error": str(e),
                "updated_at": time.time(),
            }

    # ---------------- scheduler ----------------

    async def _sched_loop(self):
        while True:
            try:
                await self._track_active_jobs()
                await self._dispatch()
            except Exception:
                log.exception("scheduler loop error")
            await asyncio.sleep(SCHED_INTERVAL)

    async def _track_active_jobs(self):
        """ติดตามงานที่กำลังพิมพ์: complete -> done, error/cancelled -> failed"""
        for job in db.active_jobs():
            pid = job["printer_id"]
            snap = self.live.get(pid)
            if not snap or not snap.get("online"):
                continue
            state = snap.get("print_state")
            # ต้องเป็นไฟล์ของงานนี้จริง ๆ (กันชนกับงานที่สั่งพิมพ์เอง)
            same_file = (snap.get("filename") or "") == job["filename"]
            if job["status"] == "printing" and same_file:
                if state == "complete":
                    db.update_job(job["id"], status="done", finished_at=time.time())
                    # มีชิ้นงานบนแท่น — hold เครื่องไว้ รอคนกดเคลียร์ก่อนรับงานถัดไป
                    db.update_printer(pid, waiting_clear=1)
                    log.info("job %s done on %s — waiting for part removal", job["id"], pid)
                elif state in ("error", "cancelled", "standby"):
                    db.update_job(
                        job["id"], status="failed", finished_at=time.time(),
                        error=snap.get("message") or f"print stopped ({state})",
                    )
                    # งานพัง/หยุดกลางคัน ก็มีเศษงานบนแท่น ต้องเคลียร์ก่อนเช่นกัน
                    db.update_printer(pid, waiting_clear=1)

    async def _dispatch(self):
        jobs = db.queued_jobs()
        if not jobs:
            return
        busy = {j["printer_id"] for j in db.active_jobs()}
        for p in db.list_printers():
            if not jobs:
                break
            pid = p["id"]
            if not p["enabled"] or pid in busy or pid in self.reserved:
                continue
            if p.get("waiting_clear"):
                # งานเสร็จแล้วรอคนเอาชิ้นงานออก — ยังไม่จ่ายงานใหม่ให้
                continue
            snap = self.live.get(pid)
            if not snap or not snap.get("online") or not is_idle(snap):
                continue

            job = jobs.pop(0)
            self.reserved.add(pid)
            db.update_job(job["id"], status="uploading", printer_id=pid)
            asyncio.create_task(self._run_job(p, job))
            busy.add(pid)

    async def _run_job(self, printer: dict, job: dict):
        pid = printer["id"]
        client = self.client_for(printer)
        try:
            path = UPLOAD_DIR / job["stored_path"]
            if not path.exists():
                raise FileNotFoundError(f"ไม่พบไฟล์ {job['filename']} ในคลัง")
            log.info("dispatch job %s (%s) -> %s", job["id"], job["filename"], printer["name"])
            await client.upload(path, job["filename"], start_print=False)
            await client.start_print(job["filename"])
            db.update_job(job["id"], status="printing", started_at=time.time())
            # copies > 1: ลดจำนวนแล้วสร้างงานใหม่ต่อคิว
            if job["copies"] > 1:
                db.update_job(job["id"], copies=1)
                db.add_job(job["filename"], job["stored_path"], copies=job["copies"] - 1)
        except Exception as e:
            log.exception("job %s failed to dispatch", job["id"])
            db.update_job(job["id"], status="failed", finished_at=time.time(), error=str(e))
        finally:
            # หน่วงก่อนปลดจอง กันสถานะ Klipper ยังไม่ทันเปลี่ยนเป็น printing
            await asyncio.sleep(5)
            self.reserved.discard(pid)


manager = FarmManager()
