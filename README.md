# 🖨️ Klipper Farm Controller

ระบบควบคุมฟาร์มเครื่องพิมพ์ 3D ที่ใช้ **Klipper** — รองรับเครื่อง **ต่างรุ่น/ต่างยี่ห้อคละกันได้ไม่จำกัด**
ขอแค่ทุกเครื่องรัน Klipper + Moonraker และอยู่ใน **LAN เดียวกัน** กับเซิร์ฟเวอร์นี้

## แนวคิด

เครื่องพิมพ์ Klipper ทุกเครื่อง (ไม่ว่า Ender, Voron, Prusa แปลง, CR-10, เครื่อง DIY ฯลฯ)
มี API มาตรฐานเดียวกันคือ **Moonraker** (พอร์ต 7125) ระบบนี้จึงคุยกับทุกเครื่องผ่าน Moonraker
โดยไม่ผูกกับรุ่นใดรุ่นหนึ่ง

```
                    ┌──────────────────────────┐
   เบราว์เซอร์ ────▶│  Farm Controller (:8000) │
                    │  - Dashboard ภาษาไทย     │
                    │  - คิวงาน + auto dispatch │
                    │  - SQLite เก็บข้อมูล     │
                    └───────────┬──────────────┘
                                │ LAN (Moonraker API :7125)
              ┌─────────────────┼─────────────────┐
        ┌─────▼─────┐     ┌─────▼─────┐     ┌─────▼─────┐
        │ Ender 3   │     │ Voron 2.4 │     │ เครื่องอื่น ๆ │
        │ Klipper   │     │ Klipper   │     │ Klipper   │
        └───────────┘     └───────────┘     └───────────┘
```

## ฟีเจอร์

- **ไม่จำกัดรุ่น/จำนวนเครื่อง** — เพิ่มเครื่องด้วย IP + port (ทดสอบการเชื่อมต่อก่อนบันทึก)
- **ผังฟาร์ม: ฟาร์ม → ชั้นวาง → ช่อง** — ระบุตำแหน่งจริงของเครื่องพิมพ์แต่ละตัว
  สร้างได้หลายฟาร์ม แต่ละฟาร์มมีหลายชั้นวาง แต่ละชั้นกำหนดจำนวนช่องได้
  Dashboard แสดงผังพร้อมสถานะสีแบบ real-time คลิกช่องว่างเพื่อวางเครื่อง คลิกเครื่องเพื่อควบคุม
- **ค้นหาเครื่องอัตโนมัติ** — สแกน subnet ใน LAN หา Moonraker (เช่น `192.168.1.0/24`)
- **Dashboard real-time** — สถานะ, % ความคืบหน้า, เวลาที่เหลือโดยประมาณ, อุณหภูมิหัวฉีด/แท่นพิมพ์
- **คิวงานส่วนกลาง + จ่ายงานอัตโนมัติ** — อัปโหลด G-code ครั้งเดียว ระบุจำนวนชิ้น
  ระบบส่งไฟล์ไปเครื่องที่ว่างเอง เครื่องไหนเสร็จก่อนรับงานถัดไปก่อน (คละรุ่นได้
  *ผู้ใช้ต้อง slice ไฟล์ให้เหมาะกับเครื่องในฟาร์มเอง*)
- **ควบคุมรายเครื่อง** — สั่งพิมพ์ไฟล์ในเครื่อง, พัก/พิมพ์ต่อ/ยกเลิก, ส่ง G-code,
  Emergency Stop, Firmware Restart, อัปโหลดตรงเข้าเครื่อง
- **จัดการงาน** — ยกเลิกงาน (รวมกำลังพิมพ์), requeue งานที่ล้มเหลว/เสร็จแล้ว
- **รอเอาชิ้นงานออก (part-removal hold)** — งานเสร็จ (หรือพังกลางคัน) เครื่องจะถูก hold
  ไม่รับงานใหม่จากคิว จนกว่าคนหน้างานกด **"✔ เอาชิ้นงานออกแล้ว — รับงานต่อ"** บนการ์ดเครื่อง
  (สถานะเก็บถาวร รีสตาร์ทเซิร์ฟเวอร์ก็ไม่หาย)
- รองรับ Moonraker ที่ตั้ง **API Key** (`trusted_clients` / `cors_domains` ตามปกติ)
- **AI Failure Detection ส่วนกลาง** — farm ประมวลผลภาพตรวจจับงานพิมพ์เสียให้ทุกเครื่อง
  (ใช้คู่กับปลั๊กอิน `klipper-ai-failure-detection`) รองรับ Vision LLM (OpenAI-compatible)
  หรือส่งต่อไปยัง inference server ภายนอก — เครื่องพิมพ์ไม่ต้องรัน AI เอง

## การติดตั้งฝั่งเครื่องพิมพ์ (แต่ละเครื่อง)

ต้องมี Klipper + Moonraker รันอยู่แล้ว (เช่นติดตั้งผ่าน KIAUH / MainsailOS / FluiddPi)
และอนุญาตให้เซิร์ฟเวอร์ farm เรียก API ได้ — ใน `moonraker.conf`:

```ini
[authorization]
trusted_clients:
    192.168.1.0/24        # subnet ของ LAN ฟาร์ม
cors_domains:
    *
```

> ถ้าเครื่องเปิดใช้ API key ให้กรอก key ตอนเพิ่มเครื่องใน dashboard

## รันเซิร์ฟเวอร์ farm

```bash
./run.sh                  # ติดตั้ง venv ให้อัตโนมัติครั้งแรก แล้วรันที่พอร์ต 8000
# เปิด http://<IP-เซิร์ฟเวอร์>:8000
```

กำหนดค่าผ่าน environment variables ได้:

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `FARM_PORT` | `8000` | พอร์ต dashboard/API |
| `FARM_DATA_DIR` | `./data` | ที่เก็บ SQLite + ไฟล์ G-code คิวงาน |
| `FARM_POLL_INTERVAL` | `2.5` | รอบดึงสถานะเครื่องพิมพ์ (วินาที) |
| `FARM_SCHED_INTERVAL` | `3` | รอบจัดคิวงาน (วินาที) |
| `FARM_HTTP_TIMEOUT` | `6` | timeout คุยกับ Moonraker |
| `FARM_AI_BACKEND` | auto | `vision` (Vision LLM) หรือ `proxy` (ส่งต่อ inference server) — ว่าง = เลือกอัตโนมัติจากค่าที่ตั้ง |
| `FARM_AI_API_URL` | `https://api.openai.com/v1/chat/completions` | endpoint Vision LLM แบบ OpenAI-compatible (OpenAI / Ollama / LM Studio / vLLM) |
| `FARM_AI_API_KEY` | – | API key ของ Vision LLM (ตั้งแล้วเปิดโหมด vision อัตโนมัติ) |
| `FARM_AI_MODEL` | `gpt-4o-mini` | ชื่อโมเดล vision เช่น `gpt-4o`, `qwen2.5vl:7b` |
| `FARM_AI_PROXY_URL` | – | URL inference server ภายนอก เช่น Obico (ตั้งแล้วเปิดโหมด proxy อัตโนมัติ) |
| `FARM_AI_TIMEOUT` | `30` | timeout การเรียก AI (วินาที) |
| `FARM_AI_TOKEN` | – | token ที่ปลั๊กอินต้องส่งมา (ว่าง = ไม่ตรวจ) |
| `FARM_AI_MAX_IMAGE_MB` | `10` | ขนาดภาพสูงสุดที่รับ (MB) |
| `FARM_AI_CAPTURE_DIR` | – | โฟลเดอร์เก็บ snapshot เมื่อตรวจพบความน่าจะเป็นสูง (ว่าง = ไม่เก็บ) |
| `FARM_AI_SAVE_THRESHOLD` | `0.6` | เกณฑ์ probability ที่บันทึก snapshot |

### รันเป็น service (systemd)

```ini
# /etc/systemd/system/farm-controller.service
[Unit]
Description=Klipper Farm Controller
After=network-online.target

[Service]
WorkingDirectory=/home/chroma/farm-controller
ExecStart=/home/chroma/farm-controller/run.sh
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now farm-controller
```

## วิธีใช้งาน

1. เปิด dashboard → **🔍 ค้นหาเครื่องใน LAN** ใส่ subnet เช่น `192.168.1.0/24` → กดเพิ่มเครื่องที่พบ
   (หรือ **＋ เพิ่มเครื่องพิมพ์** แล้วกรอก IP เอง)
2. **คิวงานส่วนกลาง**: เลือกไฟล์ `.gcode` + จำนวนชิ้น → เข้าคิว
   ระบบจ่ายงานให้เครื่องว่างอัตโนมัติ อัปโหลดไฟล์เข้าเครื่อง แล้วสั่งพิมพ์ให้
3. งานเสร็จ → การ์ดเครื่องขึ้นสีส้ม **"⚠ รอเอาชิ้นงานออก"** แม้มีคิวรออยู่เครื่องก็จะไม่รับงานใหม่
   → หยิบชิ้นงานออกจริง ๆ แล้วกด **"✔ เอาชิ้นงานออกแล้ว — รับงานต่อ"** เครื่องถึงจะรับงานถัดไป
4. คลิกการ์ดเครื่องเพื่อควบคุมรายเครื่อง (พัก/ยกเลิก/G-code/ไฟล์/STOP ฉุกเฉิน)

## ผังฟาร์ม (ระบุตำแหน่งเครื่องพิมพ์)

จัดตำแหน่งจริงของเครื่องเป็นลำดับ **ฟาร์ม → ชั้นวาง → ช่อง**:

1. ที่ส่วน **ผังฟาร์ม** กด **＋ สร้างฟาร์ม** (เช่น "โรงงาน A" / "ห้องพิมพ์ 1")
2. ในฟาร์ม กด **＋ ชั้นวาง** ตั้งชื่อ (เช่น "ชั้น 1") และจำนวนช่อง
3. คลิกช่องที่ **＋ ว่าง** แล้วเลือกเครื่องพิมพ์ที่จะวาง — หรือเปิดการ์ดเครื่อง
   แล้วเลือกชั้นวาง/ช่องในแถบ **📍 ตำแหน่ง** ก็ได้
4. ช่องในผังแสดงชื่อเครื่อง + สถานะสี (กำลังพิมพ์/ว่าง/พัก/ออฟไลน์/รอเคลียร์)
   คลิกที่เครื่องในผังเพื่อเปิดหน้าควบคุมทันที

กติกา: ช่องหนึ่งวางได้เครื่องเดียว (ชนกันจะเตือน), ลดจำนวนช่องต่ำกว่าที่มีเครื่องวางไม่ได้,
ลบชั้น/ฟาร์มแล้วเครื่องพิมพ์**ไม่ถูกลบ** — แค่หลุดจากผัง (ย้ายฟาร์มได้โดยวางใหม่)

## AI Failure Detection (farm ประมวลผลให้ทั้งฟาร์ม)

ใช้คู่กับปลั๊กอิน [klipper-ai-failure-detection](https://github.com/ch2oma-hbtb/klipper-ai-failure-detection)
— ปลั๊กอินบนเครื่องพิมพ์ถ่ายภาพจากกล้องแล้วส่งมาที่ farm เพื่อประมวลผล
เมื่อ probability ถึงเกณฑ์ ปลั๊กอินจะสั่ง `PAUSE` ที่เครื่องเองอัตโนมัติ

**ตั้งค่าฝั่ง farm** (เลือกอย่างใดอย่างหนึ่ง):

```bash
# แบบที่ 1: Vision LLM (OpenAI / Ollama / LM Studio / vLLM ที่รองรับภาพ)
export FARM_AI_API_KEY="sk-..."
export FARM_AI_MODEL="gpt-4o-mini"
# ใช้ Ollama ในเครื่อง: FARM_AI_API_URL=http://localhost:11434/v1/chat/completions FARM_AI_MODEL=qwen2.5vl:7b FARM_AI_API_KEY=ollama

# แบบที่ 2: ส่งต่อไป inference server ภายนอก (เช่น Obico / ML server เอง)
export FARM_AI_PROXY_URL="http://ml-server:5000/api/detect"

# แนะนำ: ตั้ง token กันคนนอกส่งภาพมา
export FARM_AI_TOKEN="random-secret"
./run.sh
```

**ตั้งค่าฝั่งเครื่องพิมพ์** (`printer.cfg` ของแต่ละเครื่อง):

```ini
[ai_failure_detection]
api_url: http://<IP-เซิร์ฟเวอร์-farm>:8000/api/ai/detect
api_key: random-secret          # ให้ตรงกับ FARM_AI_TOKEN (ถ้าตั้ง)
camera_url: http://localhost:8080/?action=snapshot
confidence_threshold: 0.60
pause_on_failure: True
```

ตรวจสถานะ AI ได้ที่ `GET /api/ai/status` (backend, สถิติ, snapshot ที่บันทึก)

## REST API (ย่อ)

| Method | Path | หน้าที่ |
|---|---|---|
| GET | `/api/state` | สถานะทุกเครื่อง + คิวงานทั้งหมด |
| POST | `/api/printers` | เพิ่มเครื่อง `{name, host, port, api_key, notes}` |
| PATCH / DELETE | `/api/printers/{id}` | แก้ไข / ลบเครื่อง |
| POST | `/api/printers/{id}/print` | สั่งพิมพ์ไฟล์ในเครื่อง `{filename}` |
| POST | `/api/printers/{id}/pause\|resume\|cancel\|estop\|firmware_restart` | ควบคุม |
| POST | `/api/printers/{id}/clear` | ยืนยันเอาชิ้นงานออกแล้ว ปลดล็อกให้รับงานถัดไป |
| POST | `/api/printers/{id}/gcode` | ส่ง G-code `{script}` |
| GET | `/api/printers/{id}/files` | รายการไฟล์ในเครื่อง |
| POST | `/api/printers/{id}/upload` | อัปโหลดตรงเข้าเครื่อง (multipart, `print_now`) |
| POST | `/api/jobs` | เข้าคิวงาน (multipart: `file`, `copies`) |
| DELETE | `/api/jobs/{id}` | ยกเลิกงาน |
| POST | `/api/jobs/{id}/requeue` | นำงานที่จบแล้วกลับเข้าคิว |
| POST | `/api/discover` | สแกน LAN `{cidr, port}` |
| POST | `/api/farms` | สร้างฟาร์ม `{name, notes}` |
| PATCH / DELETE | `/api/farms/{id}` | แก้ไข / ลบฟาร์ม (ชั้นวางถูกลบ, เครื่องหลุดจากผัง) |
| POST | `/api/farms/{id}/shelves` | เพิ่มชั้นวาง `{name, slots}` |
| PATCH / DELETE | `/api/shelves/{id}` | แก้ไข (ชื่อ/จำนวนช่อง/ย้ายฟาร์ม) / ลบชั้นวาง |
| PUT | `/api/printers/{id}/location` | วางเครื่องลงช่อง `{shelf_id, position}` (`shelf_id=null` = เอาออก) |
| POST | `/api/ai/detect` | รับภาพ (multipart `image`) → `{probability}` สำหรับปลั๊กอิน AI |
| GET | `/api/ai/status` | สถานะ/สถิติระบบ AI |

API docs แบบโต้ตอบ: `http://<server>:8000/docs`

## การทดสอบ (ไม่ต้องมีเครื่องจริง)

มี mock Moonraker จำลองเครื่องพิมพ์ให้:

```bash
.venv/bin/python tests/mock_moonraker.py 7125 --print-secs 10 &
.venv/bin/python tests/mock_moonraker.py 7126 --print-secs 10 &
./run.sh
# เพิ่มเครื่อง 127.0.0.1:7125 และ 127.0.0.1:7126 แล้วลองเข้าคิวงาน
```

มี unit test สำเร็จรูป (ไม่ต้องรันเซิร์ฟเวอร์/ไม่มีเครื่องจริง):

```bash
.venv/bin/python tests/test_layout.py   # ผังฟาร์ม: farm/shelf/ช่อง + กติกาต่าง ๆ
.venv/bin/python tests/test_ai.py       # AI: parsing, vision/proxy backend, endpoint + token
```

## โครงสร้าง

```
farm/
  app.py        # FastAPI: REST API + เสิร์ฟ dashboard
  manager.py    # poll สถานะทุกเครื่อง + scheduler จ่ายงานอัตโนมัติ
  moonraker.py  # client คุยกับ Moonraker (ใช้ได้กับ Klipper ทุกรุ่น)
  discovery.py  # สแกนหา Moonraker ใน LAN
  ai.py         # AI failure detection (Vision LLM / proxy) ให้ปลั๊กอินบนเครื่องพิมพ์
  db.py         # SQLite: printers + jobs + farms/shelves (ผังตำแหน่ง)
  config.py     # ค่าคอนฟิก
static/         # dashboard (HTML/CSS/JS ภาษาไทย)
tests/          # mock Moonraker + unit tests (layout / AI)
```

## ข้อควรรู้ / ข้อจำกัด

- การจ่ายงานอัตโนมัติเลือก "เครื่องว่างเครื่องแรก" — ควร slice G-code ให้เข้าได้กับ
  ทุกเครื่องที่จะรับงานนั้น (กลุ่มเครื่องสเปกเดียวกัน) ถ้าฟาร์มคละสเปกมาก
  แนะนำแยกคิวโดยอัปโหลดตรงเข้าเครื่อง หรือแยกเป็นหลาย farm instance
- ระบบไม่ลบชิ้นงานจากแท่นพิมพ์ให้ — เมื่องานจบ เครื่องจะขึ้นสถานะ **รอเอาชิ้นงานออก**
  และหยุดรับงานจากคิวจนกว่าจะกดปุ่มเคลียร์บน dashboard (กดทั้งที่ยังไม่หยิบงานออก
  = ชิ้นงานใหม่จะพิมพ์ทับชิ้นเดิม ผู้กดต้องรับผิดชอบเอง)
- งานที่สั่งพิมพ์เองนอกคิว (ผ่านหน้าเครื่อง/Mainsail) ระบบไม่ได้ track การจบงาน
  จึงไม่เข้าโหมดรอเคลียร์ — โหมดนี้ครอบคลุมเฉพาะงานที่จ่ายผ่านคิวของ farm
- Discovery สแกนพอร์ตเดียวต่อรอบ (ค่าเริ่มต้น 7125) ถ้าเครื่องใช้พอร์ตอื่นให้ระบุพอร์ตตอนสแกน/เพิ่มเครื่อง
