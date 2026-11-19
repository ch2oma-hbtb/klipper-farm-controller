"""ทดสอบ AI failure detection service — ไม่ต้องมี backend จริง (ใช้ MockTransport)
รัน: .venv/bin/python tests/test_ai.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["FARM_DATA_DIR"] = tempfile.mkdtemp(prefix="farm-test-ai-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from farm import ai  # noqa: E402
import farm.app as appmod  # noqa: E402

CHECKS = 0


def check(cond, msg):
    global CHECKS
    assert cond, msg
    CHECKS += 1
    print(f"  ✓ {msg}")


print("parse_probability / extract_json")
check(ai.parse_probability({"probability": 0.85}) == 0.85, "รูปแบบ probability")
check(ai.parse_probability({"failure_probability": 0.2}) == 0.2, "รูปแบบ failure_probability")
check(ai.parse_probability({"confidence": 0.0}) == 0.0, "ค่า 0.0 ไม่ถูกข้าม")
check(ai.parse_probability({"result": {"probability": 0.7}}) == 0.7, "รูปแบบ result.probability")
check(ai.parse_probability({"probability": 5}) == 1.0, "clamp ค่าเกิน 1")
check(ai.parse_probability({"probability": -3}) == 0.0, "clamp ค่าติดลบ")
check(ai.parse_probability({"probability": "abc"}) is None, "ค่าไม่ใช่ตัวเลข -> None")
check(ai.parse_probability({}) is None, "ไม่มีฟิลด์ -> None")
check(ai.extract_json('```json\n{"failure_probability": 0.9}\n```') == {"failure_probability": 0.9},
      "JSON ใน code fence")
check(ai.extract_json('ผลคือ {"failure_probability": 0.1} ครับ') == {"failure_probability": 0.1},
      "JSON แฝงในข้อความ")
check(ai.extract_json("ไม่มี json") is None, "ไม่มี JSON -> None")

print("vision backend (OpenAI-compatible)")
ai.AI_BACKEND = "vision"
ai.AI_API_KEY = "test-key"
ai.AI_MODEL = "test-model"
capture_dir = tempfile.mkdtemp(prefix="farm-ai-caps-")
ai.AI_CAPTURE_DIR = capture_dir
ai.AI_SAVE_THRESHOLD = 0.6


def vision_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer test-key"
    payload = json.loads(request.content)
    assert payload["model"] == "test-model"
    url = payload["messages"][1]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    return httpx.Response(200, json={"choices": [{"message": {"content":
        '```json\n{"failure_probability": 0.87, "reason": "spaghetti"}\n```'}}]})


async def t_vision():
    async with httpx.AsyncClient(transport=httpx.MockTransport(vision_handler)) as http:
        d = ai.AIDetector(http)
        r = await d.detect(b"fakejpeg")
        check(r["probability"] == 0.87 and r["backend"] == "vision", "vision -> probability 0.87")
        check(r["reason"] == "spaghetti", "ได้ reason จากโมเดล")
        check(d.stats["total_requests"] == 1, "นับสถิติ request")
        check(len(list(Path(capture_dir).glob("failure_*.jpg"))) == 1, "บันทึก snapshot เมื่อ p >= เกณฑ์")


asyncio.run(t_vision())

print("proxy backend")
ai.AI_BACKEND = "proxy"
ai.AI_PROXY_URL = "http://ml.local/detect"


def proxy_handler(request: httpx.Request) -> httpx.Response:
    assert b"fakejpeg" in request.content  # multipart มีภาพส่งต่อจริง
    return httpx.Response(200, json={"result": {"probability": 0.4}})


async def t_proxy():
    async with httpx.AsyncClient(transport=httpx.MockTransport(proxy_handler)) as http:
        d = ai.AIDetector(http)
        r = await d.detect(b"fakejpeg")
        check(r["probability"] == 0.4 and r["backend"] == "proxy", "proxy -> normalize probability 0.4")


asyncio.run(t_proxy())

print("unconfigured backend")
ai.AI_BACKEND = ""
ai.AI_API_KEY = ""
ai.AI_PROXY_URL = ""


async def t_unconfigured():
    async with httpx.AsyncClient(transport=httpx.MockTransport(proxy_handler)) as http:
        d = ai.AIDetector(http)
        try:
            await d.detect(b"x")
            check(False, "ต้อง raise AIError")
        except ai.AIError:
            check(True, "ยังไม่ตั้ง backend -> AIError (503)")
        check(d.stats["total_errors"] == 1, "นับสถิติ error")


asyncio.run(t_unconfigured())

print("HTTP endpoint /api/ai/detect")
ai.AI_BACKEND = "proxy"
ai.AI_PROXY_URL = "http://ml.local/detect"
appmod.AI_TOKEN = "secret"

with TestClient(appmod.app) as c:
    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(proxy_handler))
    ai.detector = ai.AIDetector(mock_http)

    r = c.post("/api/ai/detect", files={"image": ("x.jpg", b"fakejpeg", "image/jpeg")})
    check(r.status_code == 401, "ไม่มี token -> 401")

    r = c.post("/api/ai/detect", files={"image": ("x.jpg", b"fakejpeg", "image/jpeg")},
               headers={"Authorization": "Bearer secret"})
    check(r.status_code == 200 and r.json()["probability"] == 0.4, "token ถูก -> 200 + probability")

    r = c.post("/api/ai/detect", files={"image": ("x.jpg", b"", "image/jpeg")},
               headers={"Authorization": "Bearer secret"})
    check(r.status_code == 400, "ภาพว่าง -> 400")

    r = c.get("/api/ai/status")
    body = r.json()
    check(r.status_code == 200 and body["configured"] and body["token_required"], "status บอก configured/token")
    check(body["stats"]["total_requests"] == 1, "status มีสถิติ")

    asyncio.run(mock_http.aclose())

print(f"\nPASS — {CHECKS} checks")
