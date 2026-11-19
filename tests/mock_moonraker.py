"""Mock Moonraker — จำลองเครื่องพิมพ์ Klipper สำหรับทดสอบ (ไม่ใช่ส่วนหนึ่งของระบบจริง)
รัน: python tests/mock_moonraker.py <port> [--print-secs N]
"""
import sys
import time

from fastapi import FastAPI, UploadFile, File, Form, Request
import uvicorn

app = FastAPI()
S = {
    "state": "ready",
    "print_state": "standby",
    "filename": "",
    "progress": 0.0,
    "started": None,
    "print_secs": 8.0,
    "files": [],
}


@app.get("/server/info")
def server_info():
    return {"result": {"moonraker_version": "v0.9.3-mock", "klippy_connected": True, "klippy_state": S["state"]}}


@app.get("/machine/system_info")
def system_info():
    return {"result": {"system_info": {"cpu_info": {"hostname": f"mock-printer"}}}}


@app.get("/printer/info")
def printer_info():
    return {"result": {"state": S["state"], "state_message": "Printer is ready"}}


def _tick():
    if S["print_state"] == "printing" and S["started"]:
        el = time.time() - S["started"]
        S["progress"] = min(1.0, el / S["print_secs"])
        if S["progress"] >= 1.0:
            S["print_state"] = "complete"
            S["started"] = None


@app.get("/printer/objects/query")
def query(request: Request):
    _tick()
    dur = (time.time() - S["started"]) if S["started"] else 0
    return {"result": {"status": {
        "print_stats": {"state": S["print_state"], "filename": S["filename"],
                        "print_duration": dur, "total_duration": dur,
                        "filament_used": dur * 10, "message": ""},
        "display_status": {"progress": S["progress"]},
        "virtual_sdcard": {"progress": S["progress"], "is_active": S["print_state"] == "printing"},
        "extruder": {"temperature": 210.5 if S["print_state"] == "printing" else 25.0,
                     "target": 210 if S["print_state"] == "printing" else 0},
        "heater_bed": {"temperature": 60.2 if S["print_state"] == "printing" else 24.0,
                       "target": 60 if S["print_state"] == "printing" else 0},
        "toolhead": {"position": [0, 0, 0, 0], "homed_axes": "xyz"},
        "idle_timeout": {"state": "Idle"},
    }}}


@app.get("/server/files/list")
def files_list(root: str = "gcodes"):
    return {"result": S["files"]}


@app.post("/server/files/upload")
async def upload(file: UploadFile = File(...), root: str = Form("gcodes"), print: str = Form("false")):
    data = await file.read()
    S["files"].append({"path": file.filename, "size": len(data), "modified": time.time()})
    if print == "true":
        _start(file.filename)
    return {"result": {"item": {"path": file.filename}}}


def _start(filename):
    S["print_state"] = "printing"
    S["filename"] = filename
    S["started"] = time.time()
    S["progress"] = 0.0


@app.post("/printer/print/start")
def start(filename: str):
    _start(filename)
    return {"result": "ok"}


@app.post("/printer/print/pause")
def pause():
    S["print_state"] = "paused"
    return {"result": "ok"}


@app.post("/printer/print/resume")
def resume():
    S["print_state"] = "printing"
    return {"result": "ok"}


@app.post("/printer/print/cancel")
def cancel():
    S["print_state"] = "cancelled"
    S["started"] = None
    return {"result": "ok"}


@app.post("/printer/gcode/script")
def gcode(script: str):
    return {"result": "ok"}


@app.post("/printer/emergency_stop")
def estop():
    S["state"] = "shutdown"
    S["print_state"] = "error"
    return {"result": "ok"}


@app.post("/printer/firmware_restart")
def fw():
    S["state"] = "ready"
    return {"result": "ok"}


if __name__ == "__main__":
    port = int(sys.argv[1])
    if "--print-secs" in sys.argv:
        S["print_secs"] = float(sys.argv[sys.argv.index("--print-secs") + 1])
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
