"""Moonraker API client — ใช้ได้กับ Klipper ทุกเครื่อง/ทุกรุ่นที่รัน Moonraker บน LAN"""
from pathlib import Path

import httpx

from .config import HTTP_TIMEOUT

# query objects มาตรฐานที่มีใน Klipper ทุกเครื่อง
STATUS_QUERY = {
    "print_stats": None,
    "display_status": None,
    "virtual_sdcard": None,
    "extruder": ["temperature", "target"],
    "heater_bed": ["temperature", "target"],
    "toolhead": ["position", "homed_axes"],
    "idle_timeout": ["state"],
}


class MoonrakerError(Exception):
    pass


class MoonrakerClient:
    def __init__(self, http: httpx.AsyncClient, host: str, port: int = 7125, api_key: str = ""):
        self.base = f"http://{host}:{port}"
        self.headers = {"X-Api-Key": api_key} if api_key else {}

        self.http = http

    async def _get(self, path: str, params: dict | None = None):
        r = await self.http.get(self.base + path, params=params, headers=self.headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json().get("result", {})

    async def _post(self, path: str, params: dict | None = None, json: dict | None = None):
        r = await self.http.post(self.base + path, params=params, json=json, headers=self.headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json().get("result", {})

    # ---------- info / status ----------

    async def server_info(self) -> dict:
        return await self._get("/server/info")

    async def printer_info(self) -> dict:
        return await self._get("/printer/info")

    async def status(self) -> dict:
        """รวม printer/info + objects ที่จำเป็น เป็น snapshot เดียว"""
        info, objs = await self._gather_info()
        return {"info": info, "objects": objs}

    async def _gather_info(self):
        import asyncio

        params = "&".join(
            k if v is None else f"{k}={','.join(v)}" for k, v in STATUS_QUERY.items()
        )
        info, objs = await asyncio.gather(
            self._get("/printer/info"),
            self._get("/printer/objects/query?" + params),
        )
        return info, objs.get("status", {})

    # ---------- files ----------

    async def list_files(self) -> list[dict]:
        return await self._get("/server/files/list", {"root": "gcodes"})

    async def upload(self, filepath: str | Path, filename: str | None = None, start_print: bool = False) -> dict:
        filepath = Path(filepath)
        filename = filename or filepath.name
        with open(filepath, "rb") as f:
            r = await self.http.post(
                self.base + "/server/files/upload",
                headers=self.headers,
                files={"file": (filename, f, "application/octet-stream")},
                data={"root": "gcodes", "print": "true" if start_print else "false"},
                timeout=httpx.Timeout(HTTP_TIMEOUT, read=120, write=300),
            )
        r.raise_for_status()
        return r.json().get("result", {})

    async def delete_file(self, filename: str):
        r = await self.http.delete(
            self.base + f"/server/files/gcodes/{filename}", headers=self.headers, timeout=HTTP_TIMEOUT
        )
        r.raise_for_status()

    # ---------- print control ----------

    async def start_print(self, filename: str):
        return await self._post("/printer/print/start", {"filename": filename})

    async def pause(self):
        return await self._post("/printer/print/pause")

    async def resume(self):
        return await self._post("/printer/print/resume")

    async def cancel(self):
        return await self._post("/printer/print/cancel")

    async def gcode(self, script: str):
        return await self._post("/printer/gcode/script", {"script": script})

    async def emergency_stop(self):
        return await self._post("/printer/emergency_stop")

    async def firmware_restart(self):
        return await self._post("/printer/firmware_restart")

    async def restart_klippy(self):
        return await self._post("/printer/restart")


def build_client(http: httpx.AsyncClient, printer: dict) -> MoonrakerClient:
    return MoonrakerClient(http, printer["host"], printer["port"], printer.get("api_key") or "")


def snapshot_from_status(raw: dict) -> dict:
    """แปลงผล query ของ Moonraker เป็น snapshot ที่ dashboard ใช้ (เข้าได้กับ Klipper ทุกเครื่อง)"""
    info = raw.get("info", {})
    objs = raw.get("objects", {})
    ps = objs.get("print_stats", {}) or {}
    vs = objs.get("virtual_sdcard", {}) or {}
    ex = objs.get("extruder", {}) or {}
    bed = objs.get("heater_bed", {}) or {}

    progress = vs.get("progress") or 0.0
    duration = ps.get("print_duration") or 0.0
    eta = None
    if 0.01 < progress < 1 and duration > 0:
        eta = duration / progress - duration

    return {
        "klippy_state": info.get("state", "unknown"),
        "klippy_message": info.get("state_message", ""),
        "print_state": ps.get("state", "standby"),
        "filename": ps.get("filename", ""),
        "progress": round(progress * 100, 1),
        "print_duration": duration,
        "total_duration": ps.get("total_duration") or 0.0,
        "filament_used": ps.get("filament_used") or 0.0,
        "message": ps.get("message", ""),
        "eta_seconds": eta,
        "extruder": {"temp": ex.get("temperature"), "target": ex.get("target")},
        "heater_bed": {"temp": bed.get("temperature"), "target": bed.get("target")},
        "homed_axes": (objs.get("toolhead", {}) or {}).get("homed_axes", ""),
    }


def is_idle(snap: dict) -> bool:
    """เครื่องว่างพร้อมรับงาน: klippy ready และไม่ได้พิมพ์/หยุดพักอยู่"""
    return snap.get("klippy_state") == "ready" and snap.get("print_state") in (
        "standby",
        "complete",
        "cancelled",
        "error",
    )
