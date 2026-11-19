/* Klipper Farm Controller — dashboard */
let state = { printers: [], jobs: [] };
let currentPrinterId = null;

const $ = (id) => document.getElementById(id);

// ---------- helpers ----------
function toast(msg, type = "ok") {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast " + type;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 4000);
}

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

function postJSON(path, body, method = "POST") {
  return api(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtDuration(sec) {
  if (sec == null || sec < 0) return "–";
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}ชม ${m}น` : `${m}น ${sec % 60}ว`;
}

function fmtTime(ts) {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleString("th-TH", { dateStyle: "short", timeStyle: "short" });
}

// ---------- state polling ----------
async function refresh() {
  try {
    state = await api("/api/state");
    render();
  } catch (e) { /* เงียบไว้ รอบหน้าลองใหม่ */ }
}
setInterval(refresh, 2500);
refresh();

// ---------- render ----------
function printerState(p) {
  const live = p.live || {};
  if (!p.enabled) return { cls: "st-other", label: "ปิดใช้งาน" };
  if (p.waiting_clear) return { cls: "st-waiting", label: "⚠ รอเอาชิ้นงานออก" };
  if (!live.online) return { cls: "st-offline", label: "ออฟไลน์" };
  if (live.klippy_state !== "ready") return { cls: "st-error", label: "Klipper: " + live.klippy_state };
  const s = live.print_state;
  if (s === "printing") return { cls: "st-printing", label: "กำลังพิมพ์" };
  if (s === "paused") return { cls: "st-paused", label: "พักชั่วคราว" };
  if (s === "error") return { cls: "st-error", label: "พิมพ์ผิดพลาด" };
  if (s === "complete") return { cls: "st-idle", label: "ว่าง (งานเสร็จ)" };
  return { cls: "st-idle", label: "ว่าง" };
}

function render() {
  renderPrinters();
  renderJobs();
  renderSummary();
  // อัปเดตปุ่มเคลียร์ใน modal ที่เปิดค้างอยู่
  if (currentPrinterId) {
    const p = state.printers.find((x) => x.id === currentPrinterId);
    $("pp-clear").classList.toggle("hidden", !p?.waiting_clear);
  }
}

async function clearPrinter(pid) {
  const p = state.printers.find((x) => x.id === pid);
  if (!confirm(`ยืนยันว่าเอาชิ้นงานออกจากแท่นของ "${p?.name || pid}" แล้ว?\nเครื่องจะรับงานถัดไปจากคิวทันที`)) return;
  try {
    await api(`/api/printers/${pid}/clear`, { method: "POST" });
    toast("เคลียร์แท่นแล้ว — เครื่องพร้อมรับงานถัดไป");
    refresh();
  } catch (e) { toast(e.message, "err"); }
}

function ppClear() { if (currentPrinterId) clearPrinter(currentPrinterId); }

function renderSummary() {
  const ps = state.printers;
  const printing = ps.filter((p) => p.live?.online && p.live?.print_state === "printing").length;
  const idle = ps.filter((p) => !p.waiting_clear && p.live?.online && p.live?.klippy_state === "ready" &&
    ["standby", "complete", "cancelled", "error"].includes(p.live?.print_state)).length;
  const queued = state.jobs.filter((j) => j.status === "queued").length;
  const waiting = ps.filter((p) => p.waiting_clear).length;
  $("summary").textContent = `พิมพ์อยู่ ${printing} · ว่าง ${idle} · รอเคลียร์ ${waiting} · ออฟไลน์ ${ps.length - ps.filter((p) => p.live?.online).length} · คิว ${queued}`;
  $("printer-count").textContent = ps.length;
}

function renderPrinters() {
  const wrap = $("printers");
  $("no-printers").classList.toggle("hidden", state.printers.length > 0);
  wrap.innerHTML = state.printers.map((p) => {
    const st = printerState(p);
    const live = p.live || {};
    const online = live.online;
    const prog = live.progress ?? 0;
    const ex = live.extruder || {}, bed = live.heater_bed || {};
    const temp = (t) => t?.temp != null ? `${Math.round(t.temp)}°/${Math.round(t.target || 0)}°` : "–";
    const eta = live.print_state === "printing" && live.eta_seconds != null
      ? `เหลือ ~${fmtDuration(live.eta_seconds)}` : "";
    return `
    <div class="card ${p.waiting_clear ? "waiting" : ""}" onclick="openPrinter('${p.id}')">
      <div class="card-head">
        <div>
          <div class="card-name">${esc(p.name)}</div>
          <div class="card-host">${esc(p.host)}:${p.port}${p.notes ? " · " + esc(p.notes) : ""}</div>
        </div>
        <span class="state ${st.cls}">${st.label}</span>
      </div>
      ${online ? `
        <div class="card-file">${esc(live.filename || "ไม่มีงานพิมพ์")}</div>
        <div class="progress"><div style="width:${prog}%"></div></div>
        <div class="card-meta"><span>${prog.toFixed(1)}%</span><span>${eta || fmtDuration(live.print_duration)}</span></div>
        <div class="temps">
          <span>🌡 หัวฉีด <b>${temp(ex)}</b></span>
          <span>🛏 แท่น <b>${temp(bed)}</b></span>
        </div>
        ${live.klippy_state !== "ready" && live.klippy_message ? `<div class="card-msg">${esc(live.klippy_message)}</div>` : ""}
      ` : `<div class="card-msg">${esc(live.error || "เชื่อมต่อไม่ได้")}</div>`}
      ${p.waiting_clear ? `
        <div class="clear-banner">
          <button class="btn clear" onclick="event.stopPropagation();clearPrinter('${p.id}')">✔ เอาชิ้นงานออกแล้ว — รับงานต่อ</button>
        </div>` : ""}
    </div>`;
  }).join("");
}

const JOB_LABEL = {
  queued: ["st-paused", "รอคิว"],
  uploading: ["st-printing", "กำลังส่งไฟล์"],
  printing: ["st-printing", "กำลังพิมพ์"],
  done: ["st-idle", "เสร็จแล้ว"],
  failed: ["st-error", "ล้มเหลว"],
  canceled: ["st-other", "ยกเลิก"],
};

function renderJobs() {
  const nameOf = (pid) => state.printers.find((p) => p.id === pid)?.name || "–";
  $("jobs").innerHTML = state.jobs.map((j) => {
    const [cls, label] = JOB_LABEL[j.status] || ["st-other", j.status];
    const active = ["queued", "uploading", "printing"].includes(j.status);
    const finished = ["done", "failed", "canceled"].includes(j.status);
    return `<tr>
      <td title="${esc(j.error || "")}">${esc(j.filename)}</td>
      <td><span class="state ${cls}">${label}</span>${j.error ? ` <small title="${esc(j.error)}">ⓘ</small>` : ""}</td>
      <td>${esc(nameOf(j.printer_id))}</td>
      <td>${j.copies}</td>
      <td>${fmtTime(j.created_at)}</td>
      <td>
        ${active ? `<button class="btn small warn" onclick="cancelJob('${j.id}')">ยกเลิก</button>` : ""}
        ${finished ? `<button class="btn small" onclick="requeueJob('${j.id}')">↻ เข้าคิวใหม่</button>` : ""}
      </td>
    </tr>`;
  }).join("");
}

// ---------- add printer ----------
function openAddPrinter() { $("modal-add").classList.remove("hidden"); $("add-name").focus(); }
function closeModals() {
  document.querySelectorAll(".modal").forEach((m) => m.classList.add("hidden"));
  currentPrinterId = null;
}
document.querySelectorAll(".modal").forEach((m) =>
  m.addEventListener("click", (e) => { if (e.target === m) closeModals(); }));

async function addPrinter() {
  const body = {
    name: $("add-name").value.trim(),
    host: $("add-host").value.trim(),
    port: parseInt($("add-port").value) || 7125,
    api_key: $("add-key").value.trim(),
    notes: $("add-notes").value.trim(),
  };
  if (!body.name || !body.host) return toast("กรอกชื่อและ IP ก่อน", "err");
  try {
    const r = await postJSON("/api/printers", body);
    toast(`เพิ่ม ${body.name} สำเร็จ (Moonraker ${r.moonraker_version || "?"})`);
    closeModals();
    ["add-name", "add-host", "add-key", "add-notes"].forEach((id) => ($(id).value = ""));
    refresh();
  } catch (e) { toast(e.message, "err"); }
}

// ---------- discovery ----------
function openDiscover() { $("modal-discover").classList.remove("hidden"); }

async function runDiscover() {
  const btn = $("disc-btn");
  btn.disabled = true; btn.textContent = "กำลังสแกน…";
  $("disc-results").innerHTML = "";
  try {
    const r = await postJSON("/api/discover", { cidr: $("disc-cidr").value.trim() });
    if (!r.found.length) {
      $("disc-results").innerHTML = `<p class="empty">ไม่พบ Moonraker ใน subnet นี้</p>`;
    } else {
      $("disc-results").innerHTML = r.found.map((f) => `
        <div class="disc-row">
          <span><b>${esc(f.hostname || f.host)}</b> — ${f.host}:${f.port}
            <small>(Moonraker ${esc(f.moonraker_version)}, Klipper: ${esc(f.klippy_state)})</small></span>
          ${f.already_added
            ? `<span class="state st-idle">เพิ่มแล้ว</span>`
            : `<button class="btn small primary" onclick="addDiscovered('${f.host}',${f.port},'${esc(f.hostname)}')">＋ เพิ่ม</button>`}
        </div>`).join("");
    }
  } catch (e) { toast(e.message, "err"); }
  btn.disabled = false; btn.textContent = "สแกน";
}

function addDiscovered(host, port, hostname) {
  closeModals();
  openAddPrinter();
  $("add-host").value = host;
  $("add-port").value = port;
  $("add-name").value = hostname || host;
  $("add-name").focus();
}

// ---------- printer detail ----------
function openPrinter(pid) {
  currentPrinterId = pid;
  const p = state.printers.find((x) => x.id === pid);
  if (!p) return;
  $("pp-title").textContent = `${p.name} (${p.host}:${p.port})`;
  $("pp-gcode-out").classList.add("hidden");
  $("pp-clear").classList.toggle("hidden", !p.waiting_clear);
  $("modal-printer").classList.remove("hidden");
  loadPrinterFiles();
}

async function loadPrinterFiles() {
  const box = $("pp-files");
  box.textContent = "กำลังโหลด…";
  try {
    const r = await api(`/api/printers/${currentPrinterId}/files`);
    const files = (r.result || []).sort((a, b) => (b.modified || 0) - (a.modified || 0));
    if (!files.length) { box.textContent = "ไม่มีไฟล์ในเครื่อง"; return; }
    box.innerHTML = files.map((f) => `
      <div class="pp-file-row">
        <span title="${esc(f.path)}">${esc(f.path)}</span>
        <button class="btn small primary" onclick="printFile('${esc(f.path)}')">▶ พิมพ์</button>
      </div>`).join("");
  } catch (e) { box.textContent = "โหลดไม่ได้: " + e.message; }
}

async function printFile(filename) {
  if (!confirm(`สั่งพิมพ์ "${filename}" บนเครื่องนี้?`)) return;
  try {
    await postJSON(`/api/printers/${currentPrinterId}/print`, { filename });
    toast("สั่งพิมพ์แล้ว");
    closeModals();
  } catch (e) { toast(e.message, "err"); }
}

async function ppAction(action) {
  try {
    await api(`/api/printers/${currentPrinterId}/${action}`, { method: "POST" });
    toast("ส่งคำสั่งแล้ว");
  } catch (e) { toast(e.message, "err"); }
}

function ppCancel() {
  if (confirm("ยกเลิกงานพิมพ์ปัจจุบันของเครื่องนี้?")) ppAction("cancel");
}
function ppEstop() {
  if (confirm("⚠️ EMERGENCY STOP — ตัดการทำงานทันที ยืนยัน?")) ppAction("estop");
}
async function ppDelete() {
  if (!confirm("ลบเครื่องพิมพ์นี้ออกจาก farm? (ไม่กระทบตัวเครื่อง)")) return;
  try {
    await api(`/api/printers/${currentPrinterId}`, { method: "DELETE" });
    toast("ลบเครื่องแล้ว");
    closeModals();
    refresh();
  } catch (e) { toast(e.message, "err"); }
}

async function ppGcode() {
  const script = $("pp-gcode").value.trim();
  if (!script) return;
  const out = $("pp-gcode-out");
  try {
    const r = await postJSON(`/api/printers/${currentPrinterId}/gcode`, { script });
    out.textContent = `> ${script}\n${typeof r.result === "string" ? r.result : "OK"}`;
    out.classList.remove("hidden");
    $("pp-gcode").value = "";
  } catch (e) {
    out.textContent = `> ${script}\nERROR: ${e.message}`;
    out.classList.remove("hidden");
  }
}

async function ppUpload() {
  const f = $("pp-file").files[0];
  if (!f) return toast("เลือกไฟล์ G-code ก่อน", "err");
  const fd = new FormData();
  fd.append("file", f);
  fd.append("print_now", $("pp-printnow").checked ? "true" : "false");
  try {
    await api(`/api/printers/${currentPrinterId}/upload`, { method: "POST", body: fd });
    toast("อัปโหลดเข้าเครื่องแล้ว");
    $("pp-file").value = "";
    loadPrinterFiles();
  } catch (e) { toast(e.message, "err"); }
}

// ---------- jobs ----------
async function enqueueJob() {
  const f = $("job-file").files[0];
  if (!f) return toast("เลือกไฟล์ G-code ก่อน", "err");
  const fd = new FormData();
  fd.append("file", f);
  fd.append("copies", $("job-copies").value || "1");
  try {
    await api("/api/jobs", { method: "POST", body: fd });
    toast("เข้าคิวแล้ว — ระบบจะจ่ายงานให้เครื่องว่างอัตโนมัติ");
    $("job-file").value = "";
    refresh();
  } catch (e) { toast(e.message, "err"); }
}

async function cancelJob(jid) {
  if (!confirm("ยกเลิกงานนี้? (ถ้ากำลังพิมพ์จะสั่งยกเลิกที่เครื่องด้วย)")) return;
  try {
    await api(`/api/jobs/${jid}`, { method: "DELETE" });
    toast("ยกเลิกงานแล้ว");
    refresh();
  } catch (e) { toast(e.message, "err"); }
}

async function requeueJob(jid) {
  try {
    await postJSON(`/api/jobs/${jid}/requeue`, {});
    toast("นำเข้าคิวใหม่แล้ว");
    refresh();
  } catch (e) { toast(e.message, "err"); }
}
