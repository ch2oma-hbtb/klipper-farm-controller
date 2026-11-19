"""ค่าคอนฟิกกลางของระบบ (แก้ผ่าน environment variables ได้)"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("FARM_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "farm.db"

# รอบดึงสถานะเครื่องพิมพ์ (วินาที)
POLL_INTERVAL = float(os.environ.get("FARM_POLL_INTERVAL", "2.5"))
# รอบจัดคิวงาน (วินาที)
SCHED_INTERVAL = float(os.environ.get("FARM_SCHED_INTERVAL", "3"))
# timeout การคุยกับ Moonraker (วินาที)
HTTP_TIMEOUT = float(os.environ.get("FARM_HTTP_TIMEOUT", "6"))
# port เริ่มต้นของ Moonraker
DEFAULT_MOONRAKER_PORT = int(os.environ.get("FARM_MOONRAKER_PORT", "7125"))

# ── AI failure detection (ประมวลผลให้ปลั๊กอิน klipper-ai-failure-detection) ──
# backend: "vision" (Vision LLM ผ่าน OpenAI-compatible API) | "proxy" (ส่งต่อ inference server)
# ว่าง = auto: ใช้ proxy ถ้าตั้ง FARM_AI_PROXY_URL, ใช้ vision ถ้าตั้ง FARM_AI_API_KEY
AI_BACKEND = os.environ.get("FARM_AI_BACKEND", "").strip().lower()
AI_API_URL = os.environ.get("FARM_AI_API_URL", "https://api.openai.com/v1/chat/completions")
AI_API_KEY = os.environ.get("FARM_AI_API_KEY", "")
AI_MODEL = os.environ.get("FARM_AI_MODEL", "gpt-4o-mini")
AI_PROXY_URL = os.environ.get("FARM_AI_PROXY_URL", "")
# timeout การเรียก AI (วินาที)
AI_TIMEOUT = float(os.environ.get("FARM_AI_TIMEOUT", "30"))
# token ที่ปลั๊กอินต้องส่งมา (Authorization: Bearer ...) — ว่าง = ไม่ตรวจ
AI_TOKEN = os.environ.get("FARM_AI_TOKEN", "")
# ขนาดภาพสูงสุดที่รับ (MB)
AI_MAX_IMAGE_MB = float(os.environ.get("FARM_AI_MAX_IMAGE_MB", "10"))
# โฟลเดอร์เก็บ snapshot เมื่อ probability >= เกณฑ์ (ว่าง = ไม่เก็บ)
AI_CAPTURE_DIR = os.environ.get("FARM_AI_CAPTURE_DIR", "")
AI_SAVE_THRESHOLD = float(os.environ.get("FARM_AI_SAVE_THRESHOLD", "0.6"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
