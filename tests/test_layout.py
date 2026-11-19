"""ทดสอบผังฟาร์ม (farm -> shelf -> ตำแหน่งเครื่อง) — ไม่ต้องมีเครื่องพิมพ์จริง
รัน: .venv/bin/python tests/test_layout.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["FARM_DATA_DIR"] = tempfile.mkdtemp(prefix="farm-test-layout-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from farm import db  # noqa: E402
from farm.app import app  # noqa: E402

CHECKS = 0


def check(cond, msg):
    global CHECKS
    assert cond, msg
    CHECKS += 1
    print(f"  ✓ {msg}")


with TestClient(app) as c:
    print("farm / shelf CRUD")
    r = c.post("/api/farms", json={"name": "โรงงาน A", "notes": "อาคาร 1"})
    check(r.status_code == 200, "สร้างฟาร์มได้")
    fid = r.json()["farm"]["id"]

    r = c.post(f"/api/farms/{fid}/shelves", json={"name": "ชั้น 1", "slots": 3})
    check(r.status_code == 200, "สร้างชั้นวาง 3 ช่องได้")
    sid = r.json()["shelf"]["id"]

    r = c.post("/api/farms/none/shelves", json={"name": "x"})
    check(r.status_code == 404, "สร้างชั้นในฟาร์มที่ไม่มีจริง -> 404")

    r = c.patch(f"/api/farms/{fid}", json={"name": "โรงงาน A1"})
    check(r.status_code == 200 and r.json()["farm"]["name"] == "โรงงาน A1", "แก้ชื่อฟาร์มได้")

    # เครื่องพิมพ์ใส่ DB ตรง ๆ (ข้ามการทดสอบเชื่อมต่อ Moonraker)
    p1 = db.add_printer("P1", "127.0.0.1", 7125)
    p2 = db.add_printer("P2", "127.0.0.2", 7125)

    print("location assignment")
    r = c.put(f"/api/printers/{p1['id']}/location", json={"shelf_id": sid, "position": 2})
    check(r.status_code == 200 and r.json()["printer"]["position"] == 2, "วาง P1 ช่อง 2 ได้")

    r = c.put(f"/api/printers/{p2['id']}/location", json={"shelf_id": sid, "position": 2})
    check(r.status_code == 409, "ช่องซ้ำ -> 409")

    r = c.put(f"/api/printers/{p2['id']}/location", json={"shelf_id": sid, "position": 4})
    check(r.status_code == 400, "ช่องเกินจำนวน (4 > 3) -> 400")

    r = c.put(f"/api/printers/{p2['id']}/location", json={"shelf_id": sid})
    check(r.status_code == 400, "ไม่ระบุช่อง -> 400")

    r = c.put(f"/api/printers/{p2['id']}/location", json={"shelf_id": "none", "position": 1})
    check(r.status_code == 404, "ชั้นวางไม่มีจริง -> 404")

    r = c.put(f"/api/printers/{p1['id']}/location", json={"shelf_id": sid, "position": 3})
    check(r.status_code == 200, "ย้าย P1 ไปช่อง 3 ได้")

    r = c.put(f"/api/printers/{p2['id']}/location", json={"shelf_id": sid, "position": 2})
    check(r.status_code == 200, "P2 ใช้ช่อง 2 ที่ว่างแล้วได้")

    print("shelf constraints")
    r = c.patch(f"/api/shelves/{sid}", json={"slots": 2})
    check(r.status_code == 400, "ลดช่องต่ำกว่าที่มีเครื่องวาง (ช่อง 3) -> 400")

    r = c.patch(f"/api/shelves/{sid}", json={"slots": 5, "name": "ชั้น 1A"})
    check(r.status_code == 200 and r.json()["shelf"]["slots"] == 5, "เพิ่มช่อง + Đổiชื่อได้")

    print("state reflects layout")
    st = c.get("/api/state").json()
    farm = next(f for f in st["farms"] if f["id"] == fid)
    check(farm["shelves"][0]["slots"] == 5, "/api/state มี farms + shelves")
    sp1 = next(p for p in st["printers"] if p["id"] == p1["id"])
    check(sp1["shelf_id"] == sid and sp1["position"] == 3, "/api/state มี shelf_id/position ของเครื่อง")

    print("unassign / cascade delete")
    r = c.put(f"/api/printers/{p1['id']}/location", json={"shelf_id": None})
    check(r.status_code == 200 and r.json()["printer"]["shelf_id"] is None, "เอาเครื่องออกจากผังได้")

    r = c.delete(f"/api/shelves/{sid}")
    check(r.status_code == 200, "ลบชั้นวางได้")
    check(db.get_printer(p2["id"])["shelf_id"] is None, "เครื่องบนชั้นที่ลบ หลุดจากผังแต่ไม่ถูกลบ")
    check(db.get_printer(p2["id"]) is not None, "เครื่องพิมพ์ยังอยู่ครบ")

    # สร้างใหม่เพื่อทดสอบลบฟาร์มแบบ cascade
    sid2 = c.post(f"/api/farms/{fid}/shelves", json={"name": "ชั้น 2", "slots": 2}).json()["shelf"]["id"]
    c.put(f"/api/printers/{p1['id']}/location", json={"shelf_id": sid2, "position": 1})
    r = c.delete(f"/api/farms/{fid}")
    check(r.status_code == 200, "ลบฟาร์มได้")
    check(db.get_shelf(sid2) is None, "ชั้นวางในฟาร์มถูกลบไปด้วย")
    check(db.get_printer(p1["id"])["shelf_id"] is None, "เครื่องหลุดจากผังเมื่อฟาร์มถูกลบ")

print(f"\nPASS — {CHECKS} checks")
