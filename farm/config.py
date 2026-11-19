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

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
