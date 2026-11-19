"""AI failure detection service — ประมวลผลภาพจากปลั๊กอิน klipper-ai-failure-detection

ปลั๊กอินบนเครื่องพิมพ์แต่ละตัวส่งภาพ (multipart field "image") มาที่
POST /api/ai/detect แล้วรับ JSON {"probability": 0..1} กลับไป
เครื่องพิมพ์จึงไม่ต้องรัน AI เอง — farm เป็นคนประมวลผลให้ทั้งฟาร์ม

Backend รองรับ 2 แบบ (ตั้งผ่าน environment variables):
  - vision : ส่งภาพให้ Vision LLM ผ่าน OpenAI-compatible API
             (OpenAI, Ollama, LM Studio, vLLM ฯลฯ) แล้วอ่านค่า
             failure probability จากคำตอบ JSON ของโมเดล
  - proxy  : ส่งต่อภาพไปยัง inference server ภายนอก (เช่น Obico /
             ML server ของตัวเอง) แล้ว normalize คำตอบให้เป็น probability
"""
import base64
import json
import logging
import re
import time
from pathlib import Path

import httpx

from .config import (
    AI_BACKEND, AI_API_URL, AI_API_KEY, AI_MODEL, AI_PROXY_URL,
    AI_TIMEOUT, AI_CAPTURE_DIR, AI_SAVE_THRESHOLD,
)

log = logging.getLogger("farm.ai")

SYSTEM_PROMPT = (
    "You are an automated 3D-print failure detection system. You analyze "
    "camera frames of FDM 3D printers and estimate the probability that the "
    "print is currently failing: spaghetti / loose filament, detached print, "
    "layer shift, blob buildup on the nozzle, or printing in mid-air. "
    "A clean, normally progressing print must get a low probability. "
    "Respond with strict JSON only, no prose."
)
USER_PROMPT = (
    "Estimate the probability that the 3D print in this camera frame is "
    "currently failing. Reply with ONLY a JSON object of the form: "
    '{"failure_probability": <number between 0.0 and 1.0>, '
    '"reason": "<one short sentence>"}'
)


class AIError(Exception):
    """Backend ยังไม่พร้อม / ตอบกลับใช้ไม่ได้"""


def resolve_backend() -> str:
    """เลือก backend: ค่าที่ตั้งชัดเจน > proxy (ถ้ามี URL) > vision (ถ้ามี key)"""
    if AI_BACKEND in ("vision", "proxy"):
        return AI_BACKEND
    if AI_PROXY_URL:
        return "proxy"
    if AI_API_KEY:
        return "vision"
    return ""


def parse_probability(data) -> float | None:
    """อ่าน failure probability จาก payload — รองรับรูปแบบเดียวกับปลั๊กอิน:
    probability | failure_probability | confidence | result.probability
    """
    if not isinstance(data, dict):
        return None
    probability = None
    for key in ("probability", "failure_probability", "confidence"):
        if data.get(key) is not None:
            probability = data[key]
            break
    if probability is None:
        result = data.get("result")
        if isinstance(result, dict):
            probability = result.get("probability")
    if probability is None:
        return None
    try:
        probability = float(probability)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, probability))


def extract_json(text: str) -> dict | None:
    """ดึง JSON object จากคำตอบของ LLM (กัน code fence / ข้อความแถม)"""
    if not isinstance(text, str):
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    embedded = re.search(r"\{.*\}", text, re.S)
    if embedded:
        try:
            data = json.loads(embedded.group(0))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return None


class AIDetector:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http
        self.stats = {
            "total_requests": 0,
            "total_errors": 0,
            "total_saved": 0,
            "last_probability": None,
            "last_reason": "",
            "last_check_time": None,
        }

    async def detect(self, image: bytes, content_type: str = "image/jpeg") -> dict:
        """ประมวลผลภาพ 1 เฟรม -> {"probability": float, ...}"""
        backend = resolve_backend()
        try:
            if backend == "vision":
                result = await self._detect_vision(image, content_type)
            elif backend == "proxy":
                result = await self._detect_proxy(image, content_type)
            else:
                raise AIError(
                    "ยังไม่ได้ตั้งค่า AI backend — ตั้ง FARM_AI_API_KEY (+ FARM_AI_MODEL) "
                    "สำหรับ Vision LLM หรือ FARM_AI_PROXY_URL สำหรับ inference server ภายนอก"
                )
        except Exception:
            self.stats["total_errors"] += 1
            raise
        p = result["probability"]
        self.stats["total_requests"] += 1
        self.stats["last_probability"] = p
        self.stats["last_reason"] = result.get("reason", "")
        self.stats["last_check_time"] = time.time()
        self._maybe_save_snapshot(image, p)
        return result

    # ---------------- vision (OpenAI-compatible Vision LLM) ----------------

    async def _detect_vision(self, image: bytes, content_type: str) -> dict:
        b64 = base64.b64encode(image).decode("ascii")
        payload = {
            "model": AI_MODEL,
            "temperature": 0,
            "max_tokens": 200,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": USER_PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{content_type};base64,{b64}"}},
                ]},
            ],
        }
        headers = {"Authorization": f"Bearer {AI_API_KEY}"} if AI_API_KEY else {}
        r = await self.http.post(AI_API_URL, json=payload, headers=headers, timeout=AI_TIMEOUT)
        r.raise_for_status()
        try:
            content = r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise AIError(f"คำตอบจาก Vision LLM ผิดรูปแบบ: {e}")
        # บาง provider ส่ง content เป็น list ของ parts
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        data = extract_json(content)
        p = parse_probability(data)
        if p is None:
            raise AIError(f"อ่าน probability จากคำตอบโมเดลไม่ได้: {content!r}")
        return {
            "probability": p,
            "reason": str(data.get("reason", "")),
            "backend": "vision",
            "model": AI_MODEL,
        }

    # ---------------- proxy (inference server ภายนอก) ----------------

    async def _detect_proxy(self, image: bytes, content_type: str) -> dict:
        r = await self.http.post(
            AI_PROXY_URL,
            files={"image": ("capture.jpg", image, content_type)},
            headers={"Accept": "application/json"},
            timeout=AI_TIMEOUT,
        )
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            raise AIError("inference server ตอบกลับไม่ใช่ JSON")
        p = parse_probability(data)
        if p is None:
            raise AIError(f"ไม่มีฟิลด์ probability ในคำตอบ: {data!r}")
        return {"probability": p, "backend": "proxy", "model": AI_PROXY_URL}

    # ---------------- snapshot storage ----------------

    def _maybe_save_snapshot(self, image: bytes, probability: float):
        if not AI_CAPTURE_DIR or probability < AI_SAVE_THRESHOLD:
            return
        try:
            capture_dir = Path(AI_CAPTURE_DIR).expanduser()
            capture_dir.mkdir(parents=True, exist_ok=True)
            now = time.time()
            stamp = "%s_%03d" % (time.strftime("%Y%m%d_%H%M%S"), int(now * 1000) % 1000)
            path = capture_dir / f"failure_{stamp}_p{probability * 100:.0f}.jpg"
            path.write_bytes(image)
            self.stats["total_saved"] += 1
            log.info("ai snapshot saved: %s (p=%.3f)", path, probability)
        except Exception:
            log.exception("error saving ai snapshot")


def status() -> dict:
    backend = resolve_backend()
    return {
        "configured": bool(backend),
        "backend": backend or None,
        "model": AI_MODEL if backend == "vision" else (AI_PROXY_URL if backend == "proxy" else None),
        "api_url": AI_API_URL if backend == "vision" else None,
        "has_api_key": bool(AI_API_KEY),
        "token_required": False,  # app เติมค่าจริงจาก config
        "capture_dir": AI_CAPTURE_DIR or None,
        "save_threshold": AI_SAVE_THRESHOLD,
    }


# ถูกสร้างใน app lifespan (ใช้ httpx client ร่วมกับ manager)
detector: AIDetector | None = None
