"use strict";
let TOKEN = localStorage.getItem("mes_token") || "";
let ME = null;
const $ = (id) => document.getElementById(id);
const app = () => $("app");
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  const res = await fetch("/api" + path, { headers, ...opts });
  const txt = await res.text(); const data = txt ? JSON.parse(txt) : null;
  if (!res.ok) throw new Error(data && data.detail ? data.detail : "HTTP " + res.status);
  return data;
}
const GET = (p) => api(p);
const POST = (p, b) => api(p, { method: "POST", body: JSON.stringify(b || {}) });

function setNav(loggedIn, showBack) {
  $("logout").style.display = loggedIn ? "" : "none";
  $("back").style.display = (loggedIn && showBack) ? "" : "none";
  $("who").textContent = ME ? `${ME.full_name} · ${ME.job_title}` : "";
}

// ---------- Login ----------
function showLogin(msg) {
  setNav(false, false);
  app().innerHTML = `<div class="login card">
    <h2 style="margin-top:0">Đăng nhập</h2>
    <input id="u" placeholder="Tên đăng nhập" autocomplete="username"/>
    <input id="p" type="password" placeholder="Mật khẩu" autocomplete="current-password"/>
    <button class="btn big" id="go" style="margin-top:14px">ĐĂNG NHẬP</button>
    <div class="msg" style="color:var(--err)">${esc(msg || "")}</div>
    <div style="color:#54606e;font-size:14px;margin-top:8px">vd: <b>vanhanh</b>/123456, <b>thukho</b>/123456</div>
  </div>`;
  $("go").onclick = doLogin; $("p").onkeydown = (e) => { if (e.key === "Enter") doLogin(); };
}
async function doLogin() {
  try {
    const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("u").value.trim(), password: $("p").value }) });
    const d = await r.json();
    if (!r.ok) return showLogin(d.detail || "Đăng nhập thất bại");
    TOKEN = d.token; localStorage.setItem("mes_token", TOKEN); ME = d.user; home();
  } catch (e) { showLogin("Lỗi kết nối"); }
}
$("logout").onclick = async () => {
  try { await fetch("/api/auth/logout", { method: "POST", headers: { "Authorization": "Bearer " + TOKEN } }); } catch (e) {}
  TOKEN = ""; ME = null; localStorage.removeItem("mes_token"); showLogin();
};
$("back").onclick = home;

// ---------- Home ----------
function home() {
  setNav(true, false);
  app().innerHTML = `<div class="tiles">
    <div class="tile" id="t_scan"><span class="ic">📷</span>Quét mã</div>
    <div class="tile" id="t_label"><span class="ic">🏷️</span>In tem</div>
    <div class="tile" id="t_run"><span class="ic">⚗️</span>Mẻ đang chạy</div>
    <div class="tile" id="t_web"><span class="ic">💻</span>Bản đầy đủ</div>
  </div>`;
  $("t_scan").onclick = scanView;
  $("t_label").onclick = labelView;
  $("t_run").onclick = runningView;
  $("t_web").onclick = () => location.href = "/";
}

// ---------- Quét mã ----------
function scanView() {
  setNav(true, true);
  app().innerHTML = `<div class="card">
    <h2 style="margin-top:0">📷 Quét / nhập mã</h2>
    <input class="scanbox" id="code" placeholder="Quét hoặc gõ mã rồi Enter" autocomplete="off"/>
    <div class="msg" id="scanmsg"></div>
    <div id="scanres"></div></div>`;
  const inp = $("code"); inp.focus();
  inp.onkeydown = (e) => { if (e.key === "Enter") doScan(inp.value.trim()); };
}
async function doScan(code) {
  if (!code) return;
  $("scanmsg").textContent = "Đang tra cứu…"; $("scanres").innerHTML = "";
  try {
    const r = await GET("/scan?code=" + encodeURIComponent(code));
    $("scanmsg").textContent = "";
    if (r.type === "unknown") {
      $("scanres").innerHTML = `<div class="card"><b>Không tìm thấy mã ${esc(code)}</b>
        ${r.suggestions && r.suggestions.length ? "<div style='margin-top:8px'>Gợi ý: " + r.suggestions.map(esc).join(", ") + "</div>" : ""}</div>`;
      return;
    }
    renderScanResult(r);
  } catch (e) { $("scanmsg").innerHTML = `<span style="color:var(--err)">${esc(e.message)}</span>`; }
}
function kv(k, v) { return `<div class="kv"><b>${esc(k)}</b><span>${v}</span></div>`; }
async function renderScanResult(r) {
  const d = r.data;
  if (r.type === "lot") {
    const running = await GET("/scan/running-batches");
    const opts = running.map(b => `<option value="${b.batch_id}">${esc(b.batch_code)}</option>`).join("");
    $("scanres").innerHTML = `<div class="card">
      <h3>📦 Lô vật tư <code>${esc(d.lot_code)}</code> <span class="badge ${d.status === "available" ? "b-ok" : "b-warn"}">${esc(d.status)}</span></h3>
      ${kv("Loại", esc(d.lot_type))}${kv("Tồn", `<b>${d.quantity} ${esc(d.uom)}</b>`)}${kv("Vị trí", esc(d.location || "—"))}
      ${running.length ? `<h3 style="margin-top:16px">Cấp vào mẻ đang chạy</h3>
        <select class="scanbox" id="rb" style="font-size:20px;padding:12px">${opts}</select>
        <div class="qtybtns">
          ${[10, 50, 100, 500].map(q => `<button class="btn ok" data-q="${q}">${q} ${esc(d.uom)}</button>`).join("")}
        </div>
        <input class="scanbox" id="cq" type="number" placeholder="Số lượng khác" style="margin-top:10px;font-size:20px;padding:12px"/>
        <button class="btn ok" id="cgo" style="width:100%;margin-top:8px">Cấp số lượng đã nhập</button>`
        : `<div class="badge b-warn" style="margin-top:12px">Không có mẻ đang chạy để cấp liệu</div>`}
    </div>`;
    const consume = (q) => guardK(async () => {
      const bid = $("rb").value;
      try { await POST(`/batches/${bid}/consume`, { lot_id: d.lot_id, quantity: q }); toastK("Đã cấp " + q + " " + d.uom); }
      catch (e) {
        if (/Vượt định mức/.test(e.message)) { if (!confirm(e.message + "\nVẫn cấp?")) return;
          await POST(`/batches/${bid}/consume`, { lot_id: d.lot_id, quantity: q, allow_over: true }); toastK("Đã cấp (vượt định mức)"); }
        else throw e;
      }
      doScan(d.lot_code);
    });
    document.querySelectorAll("[data-q]").forEach(b => b.onclick = () => consume(parseFloat(b.dataset.q)));
    if ($("cgo")) $("cgo").onclick = () => { const q = parseFloat($("cq").value); if (q > 0) consume(q); };
  } else if (r.type === "batch") {
    $("scanres").innerHTML = `<div class="card">
      <h3>⚗️ Mẻ <code>${esc(d.batch_code)}</code> <span class="badge b-info">${esc(d.state)}</span> <span class="badge ${d.quality_status === "released" ? "b-ok" : "b-warn"}">${esc(d.quality_status)}</span></h3>
      ${kv("SL kế hoạch/thực tế", `${d.planned_qty} / ${d.actual_qty ?? "—"} ${esc(d.uom)}`)}
      ${kv("Hồ sơ EBR", d.ebr_locked ? '<span class="badge b-ok">đã khóa</span>' : '<span class="badge b-warn">chưa khóa</span>')}
      <button class="btn sec" style="width:100%;margin-top:12px" onclick="location.href='/'">Mở bản đầy đủ để thao tác</button></div>`;
  } else if (r.type === "work_order") {
    $("scanres").innerHTML = `<div class="card">
      <h3>📋 Lệnh SX <code>${esc(d.wo_code)}</code> <span class="badge b-info">${esc(d.status)}</span></h3>
      ${kv("Line/Ca", `${esc(d.line || "—")} / ${esc(d.shift || "—")}`)}${kv("SL kế hoạch", `${d.planned_qty} ${esc(d.uom)}`)}</div>`;
  } else if (r.type === "production_order") {
    $("scanres").innerHTML = `<div class="card"><h3>🧾 Lệnh ERP <code>${esc(d.order_code)}</code> <span class="badge b-info">${esc(d.status)}</span></h3>
      ${kv("SL", `${d.planned_qty} ${esc(d.uom)}`)}</div>`;
  }
}

// ---------- Mẻ đang chạy ----------
async function runningView() {
  setNav(true, true);
  const rb = await GET("/scan/running-batches");
  app().innerHTML = `<div class="card"><h2 style="margin-top:0">⚗️ Mẻ đang chạy (${rb.length})</h2>
    ${rb.map(b => `<div class="kv"><b>${esc(b.batch_code)}</b><span>KH ${b.planned_qty}</span></div>`).join("") || '<div>Không có mẻ đang chạy.</div>'}</div>`;
}

// ---------- In tem (barcode) ----------
function labelView() {
  setNav(true, true);
  app().innerHTML = `<div class="card noprint">
    <h2 style="margin-top:0">🏷️ In tem mã vạch (Code 39)</h2>
    <input class="scanbox" id="lcode" placeholder="Nhập/quét mã cần in tem" autocomplete="off"/>
    <button class="btn" id="lgen" style="width:100%;margin-top:10px">Tạo tem</button></div>
    <div id="label"></div>`;
  $("lcode").focus();
  const gen = () => {
    const code = $("lcode").value.trim().toUpperCase(); if (!code) return;
    $("label").innerHTML = `<div class="card" style="text-align:center">
      <div style="font-size:13px;color:#54606e">NHÀ MÁY BIA — TEM NHẬN DIỆN</div>
      ${code39SVG(code, { height: 80 })}
      <button class="btn warn noprint" style="width:100%;margin-top:14px" onclick="window.print()">🖨️ IN TEM</button></div>`;
  };
  $("lgen").onclick = gen; $("lcode").onkeydown = (e) => { if (e.key === "Enter") gen(); };
}

// ---------- helpers ----------
function toastK(m) { const el = document.createElement("div"); el.textContent = m;
  el.style.cssText = "position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1f9d55;color:#fff;padding:14px 24px;border-radius:12px;font-weight:700;z-index:99;font-size:18px";
  document.body.appendChild(el); setTimeout(() => el.remove(), 2500); }
async function guardK(fn) { try { await fn(); } catch (e) { alert(e.message); } }

// ---------- boot ----------
(async () => {
  if (TOKEN) { try { ME = await GET("/auth/me"); home(); return; } catch (e) { TOKEN = ""; localStorage.removeItem("mes_token"); } }
  showLogin();
})();
