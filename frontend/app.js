"use strict";

// ---------- Auth + API helper ----------
let TOKEN = localStorage.getItem("mes_token") || "";
let CURRENT_USER = null;  // {username, full_name, job_title, role, views}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  const res = await fetch("/api" + path, { headers, ...opts });
  if (res.status === 403 && CURRENT_USER && path !== "/auth/me") {
    // có thể phiên hết hạn → kiểm tra lại
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error(data && data.detail ? data.detail : "HTTP " + res.status);
  return data;
}
const GET = (p) => api(p);
const POST = (p, body) => api(p, { method: "POST", body: JSON.stringify(body || {}) });
const PUT = (p, body) => api(p, { method: "PUT", body: JSON.stringify(body || {}) });
const DELETE = (p) => api(p, { method: "DELETE" });
async function POST_FILES(path, files) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const headers = {};
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  const res = await fetch("/api" + path, { method: "POST", headers, body: fd });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error(data && data.detail ? data.detail : "HTTP " + res.status);
  return data;
}

// ---------- utils ----------
const $ = (id) => document.getElementById(id);
const el = (html) => { const d = document.createElement("div"); d.innerHTML = html.trim(); return d.firstChild; };
const badge = (s) => `<span class="badge ${s}">${s}</span>`;
const scopeBadge = (raw) => (raw === "*" || raw == null || raw === "")
  ? '<span class="badge available">Toàn nhà máy</span>'
  : String(raw).split(",").map(s => `<span class="badge planned" style="margin:2px">${esc(s.trim())}</span>`).join(" ");
const fmt = (t) => t ? new Date(t).toLocaleString("vi-VN") : "—";
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));
// Định dạng Date thành chuỗi cho input datetime-local — PHẢI dùng giờ LOCAL của máy (getHours...),
// không phải toISOString() (chuyển sang UTC trước khi cắt chuỗi, làm giá trị hiển thị lệch đúng
// bằng múi giờ của người dùng, VD lệch 7 tiếng ở VN — vì input datetime-local hiểu value là giờ
// địa phương, không tự quy đổi).
const toDTLocal = (d) => {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};
// Tương tự toDTLocal nhưng chỉ lấy phần ngày (cho input type="date") — cùng lý do phải dùng
// giờ LOCAL: gần nửa đêm, toISOString() có thể lệch sang NGÀY KHÁC do quy đổi UTC.
const toISODateLocal = (d) => toDTLocal(d).slice(0, 10);
function toast(msg, kind = "ok") {
  const t = el(`<div class="toast ${kind}">${esc(msg)}</div>`);
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3800);
}
async function guard(fn) { try { await fn(); } catch (e) { toast(e.message, "err"); } }

// Chính sách mật khẩu mạnh (khớp backend security.validate_password_strength).
// Trả null nếu hợp lệ, hoặc thông báo lỗi tiếng Việt nếu yếu.
function passwordPolicyMsg(pw, username) {
  pw = pw || "";
  if (pw.length < 8) return "Mật khẩu phải có tối thiểu 8 ký tự.";
  if (!/[a-zA-ZÀ-ỹ]/.test(pw)) return "Mật khẩu phải có ít nhất một chữ cái.";
  if (!/[0-9]/.test(pw)) return "Mật khẩu phải có ít nhất một chữ số.";
  if (username && username.length >= 3 && pw.toLowerCase().includes(username.toLowerCase()))
    return "Mật khẩu không được chứa tên đăng nhập.";
  return null;
}

function modal(html) {
  closeModal();
  const bg = el(`<div class="modal-bg" id="modalbg"><div class="modal"><span class="modal-x" title="Đóng">✕</span>${html}</div></div>`);
  bg.onclick = (e) => { if (e.target === bg) closeModal(); };
  bg.querySelector(".modal-x").onclick = () => closeModal();
  document.body.appendChild(bg);
}
function closeModal() { const m = $("modalbg"); if (m) m.remove(); }

// ---- Dropdown chọn nhiều bằng tick (thay <select multiple> giữ Ctrl) ----
// container: phần tử DOM đã có trong trang để chèn nút trigger vào.
// items: [{value, label}]. initialSelected: mảng value đã chọn sẵn.
// Trả về {getSelected(): string[]} để lấy lựa chọn hiện tại lúc submit.
// Cửa sổ nổi tự do (không phải overlay như modal()), kéo được bằng thanh tiêu đề, CHỈ đóng
// bằng nút X đỏ — không tự đóng khi rê chuột qua các dòng tick (tránh mất cửa sổ ngoài ý muốn).
function initCheckboxMultiSelect(container, items, initialSelected) {
  const selected = new Set(initialSelected || []);
  const trigger = el(`<button type="button" class="btn sec" style="width:100%;text-align:left"></button>`);
  container.appendChild(trigger);
  const summary = () => {
    const chosen = items.filter(i => selected.has(i.value));
    return chosen.length ? chosen.map(i => i.label).join(", ") : "— (chọn dây chuyền)";
  };
  const renderTrigger = () => { trigger.textContent = summary(); };
  renderTrigger();

  let panel = null;
  let closePanel = () => {};
  trigger.onclick = (e) => {
    e.preventDefault();
    if (panel) { closePanel(); return; }
    const rect = trigger.getBoundingClientRect();
    panel = el(`<div class="msdd-panel" style="top:${rect.bottom + window.scrollY + 4}px; left:${rect.left + window.scrollX}px">
      <div class="msdd-head"><span>Chọn dây chuyền</span><span class="msdd-x" title="Đóng">✕</span></div>
      <div class="msdd-body">${items.map(i => `<label class="msdd-item"><input type="checkbox" value="${esc(i.value)}" ${selected.has(i.value) ? "checked" : ""}/> ${esc(i.label)}</label>`).join("") ||
        '<div class="muted">Không có mục nào.</div>'}</div>
    </div>`);
    document.body.appendChild(panel);
    panel.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.onchange = () => { if (cb.checked) selected.add(cb.value); else selected.delete(cb.value); renderTrigger(); };
    });
    const head = panel.querySelector(".msdd-head");
    let dragging = false, offX = 0, offY = 0;
    const onDown = (ev) => { dragging = true; offX = ev.clientX - panel.offsetLeft; offY = ev.clientY - panel.offsetTop; ev.preventDefault(); };
    const onMove = (ev) => { if (dragging) { panel.style.left = (ev.clientX - offX) + "px"; panel.style.top = (ev.clientY - offY) + "px"; } };
    const onUp = () => { dragging = false; };
    head.addEventListener("mousedown", onDown);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    closePanel = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      panel.remove(); panel = null;
    };
    panel.querySelector(".msdd-x").onclick = () => closePanel();
  };
  return { getSelected: () => [...selected] };
}

// Ô nhập gõ-để-tìm thay cho <select> khi danh sách dài (VD nguyên liệu trong Nhập kho) —
// txtId: input text hiển thị nhãn đã chọn; hiddenId: input hidden giữ giá trị thật (id) để
// code đọc giá trị ở nơi khác ($(hiddenId).value) không phải đổi gì. items: [{value, label}].
function wireSearchableSelect(txtId, hiddenId, items, onSelect) {
  const txt = $(txtId), hidden = $(hiddenId);
  if (!txt || !hidden) return;
  let panel = null;
  const closePanel = () => { if (panel) { panel.remove(); panel = null; } };
  const openPanel = (query) => {
    closePanel();
    const q = (query || "").trim().toLowerCase();
    const matches = (q ? items.filter(i => i.label.toLowerCase().includes(q)) : items).slice(0, 50);
    const rect = txt.getBoundingClientRect();
    panel = el(`<div class="ss-dd" style="top:${rect.bottom + window.scrollY + 2}px; left:${rect.left + window.scrollX}px; width:${rect.width}px">
      ${matches.map(i => `<div class="ss-item" data-v="${esc(i.value)}">${esc(i.label)}</div>`).join("") ||
        '<div class="ss-empty">Không tìm thấy.</div>'}</div>`);
    document.body.appendChild(panel);
    // mousedown (không phải click) để chạy trước sự kiện blur của ô nhập — input không kịp
    // mất focus/đóng panel trước khi bấm chọn dòng ăn được.
    panel.querySelectorAll(".ss-item").forEach(row => {
      row.onmousedown = (e) => {
        e.preventDefault();
        const item = items.find(i => i.value === row.dataset.v);
        if (item) { hidden.value = item.value; txt.value = item.label; if (onSelect) onSelect(item); }
        closePanel();
      };
    });
  };
  txt.addEventListener("focus", () => { txt.select(); openPanel(""); });
  txt.addEventListener("input", () => openPanel(txt.value));
  txt.addEventListener("blur", () => setTimeout(closePanel, 150));
}

// Hộp thoại chọn giờ kết thúc (mẻ nấu/lọc/chiết) — KHÔNG tự động lấy giờ hiện tại khi bấm
// "Kết thúc": vận hành có thể bấm nhầm thời điểm nên luôn cho chọn/sửa giờ (mặc định giờ
// hiện tại, hoặc giờ đã lưu nếu sửa lại lần sau) trước khi xác nhận.
function openFinishTimeModal(title, currentEndedAt, onSubmit) {
  const defaultVal = toDTLocal(currentEndedAt ? new Date(currentEndedAt) : new Date());
  modal(`<h3>${esc(title)}</h3>
    <div class="field"><label>Giờ kết thúc</label><input id="fin_time" type="datetime-local" value="${defaultVal}"/></div>
    <button class="btn" id="fin_ok" style="margin-top:12px">Xác nhận</button>`);
  $("fin_ok").onclick = () => guard(async () => {
    const raw = $("fin_time").value;
    if (!raw) throw new Error("Chọn giờ kết thúc.");
    await onSubmit(new Date(raw).toISOString());
  });
}

// Kết thúc lọc CHO 1 TANK (lọc phối kết thúc riêng từng tank rồi cộng dồn) — Dịch nha
// lọc/Sản lượng lọc không bắt buộc lúc tạo, điền ở đây kèm Nước bài khí; Sản lượng lọc
// (V Bia/hl) tự tính = Dịch nha lọc + Nước bài khí (không nhập tay).
function openFinishFilterModal(title, currentEndedAt, currentVDich, currentBaiKhi, onSubmit) {
  const defaultVal = toDTLocal(currentEndedAt ? new Date(currentEndedAt) : new Date());
  modal(`<h3>${esc(title)}</h3>
    <div class="field"><label>Giờ kết thúc</label><input id="ff_time" type="datetime-local" value="${defaultVal}"/></div>
    <div class="row" style="margin-top:8px">
      <div class="field"><label>Dịch nha lọc (hl)</label><input id="ff_dich" type="number" value="${currentVDich || 0}"/></div>
      <div class="field"><label>Nước bài khí (hl)</label><input id="ff_baikhi" type="number" value="${currentBaiKhi || 0}"/></div>
    </div>
    <div class="muted" style="margin-top:8px">Tổng tank này (hl) = Dịch nha lọc + Nước bài khí = <b id="ff_total">${((currentVDich || 0) + (currentBaiKhi || 0)).toFixed(1)}</b></div>
    <button class="btn" id="ff_ok" style="margin-top:12px">Xác nhận</button>`);
  const recalc = () => {
    const d = parseFloat($("ff_dich").value) || 0;
    const k = parseFloat($("ff_baikhi").value) || 0;
    $("ff_total").textContent = (d + k).toFixed(1);
  };
  $("ff_dich").oninput = recalc; $("ff_baikhi").oninput = recalc;
  $("ff_ok").onclick = () => guard(async () => {
    const raw = $("ff_time").value;
    if (!raw) throw new Error("Chọn giờ kết thúc.");
    await onSubmit({
      ended_at: new Date(raw).toISOString(),
      v_dich_hl: parseFloat($("ff_dich").value) || 0,
      nuoc_bai_khi_hl: parseFloat($("ff_baikhi").value) || 0,
    });
  });
}

// Kết thúc chiết — V cấp chiết/hl + Ca 1/2/3 không bắt buộc lúc tạo, điền ở đây (mirror
// openFinishFilterModal cho Lọc).
function openFinishBottleModal(title, currentEndedAt, currentVCap, currentCa1, currentCa2, currentCa3, onSubmit) {
  const defaultVal = toDTLocal(currentEndedAt ? new Date(currentEndedAt) : new Date());
  modal(`<h3>${esc(title)}</h3>
    <div class="field"><label>Giờ kết thúc</label><input id="fb_time" type="datetime-local" value="${defaultVal}"/></div>
    <div class="row" style="margin-top:8px">
      <div class="field"><label>V cấp chiết/hl</label><input id="fb_vcap" type="number" value="${currentVCap || 0}"/></div>
      <div class="field"><label>Ca 1/két,thùng</label><input id="fb_ca1" type="number" value="${currentCa1 || 0}"/></div>
      <div class="field"><label>Ca 2/két,thùng</label><input id="fb_ca2" type="number" value="${currentCa2 || 0}"/></div>
      <div class="field"><label>Ca 3/két,thùng</label><input id="fb_ca3" type="number" value="${currentCa3 || 0}"/></div>
    </div>
    <button class="btn" id="fb_ok" style="margin-top:12px">Xác nhận</button>`);
  $("fb_ok").onclick = () => guard(async () => {
    const raw = $("fb_time").value;
    if (!raw) throw new Error("Chọn giờ kết thúc.");
    await onSubmit({
      ended_at: new Date(raw).toISOString(),
      v_cap_chiet_hl: parseFloat($("fb_vcap").value) || 0,
      ca1: parseFloat($("fb_ca1").value) || 0,
      ca2: parseFloat($("fb_ca2").value) || 0,
      ca3: parseFloat($("fb_ca3").value) || 0,
    });
  });
}

// ---- Modal: các tank lên men thuộc 1 bản ghi lọc — mirror openBrewBatchesModal, mỗi tank
// kết thúc RIÊNG (đặc biệt cần cho lọc phối, nhiều tank cùng lọc vào 1 BBT) ----
async function openFilterTanksModal(filterId, onHandBbt) {
  const tanks = await GET(`/brewing/filters/${filterId}/tanks`);
  const bbtSection = (onHandBbt || 0) > 0 ? `
    <div class="panel" style="margin-bottom:12px">
      <h3 style="font-size:14px">🛢️ Tank thành phẩm (BBT đích) — đang tồn <b>${onHandBbt}</b> hl</h3>
      <div class="muted" style="font-size:12px;margin-bottom:6px">Dùng khi tank BBT vật lý đã chiết cạn thật, nhưng số liệu còn lệch một
        khoảng nhỏ (hao hụt) khiến không bao giờ rút hết theo số liệu — buộc tồn về 0. Chỉ cho phép khi phần lệch còn lại không vượt
        ngưỡng cấu hình ở Danh mục.</div>
      <button class="btn sec" id="emptybbt_do">Làm rỗng tank thành phẩm</button>
    </div>` : "";
  modal(`<h3>Các tank lên men thuộc bản ghi lọc</h3>
    ${bbtSection}
    <div class="tablewrap"><table>
      <thead><tr><th>Tank LM</th><th>Lô LM</th><th>Kết thúc</th><th>Trạng thái</th><th>Dịch nha lọc (hl)</th><th>Nước bài khí (hl)</th><th></th><th></th></tr></thead>
      <tbody>${tanks.map(t => `<tr>
        <td>${esc(t.tank_lm || "—")}</td><td class="muted">${esc(t.lm_code || "—")}</td>
        <td>${fmt(t.ended_at)}</td>
        <td>${badge(t.exec_status === "hoan_thanh" ? "completed" : "in_progress")}${esc(t.exec_status_label)}</td>
        <td>${t.v_dich_hl ?? "—"}</td><td>${t.nuoc_bai_khi_hl ?? "—"}</td>
        <td><button class="btn sm ${t.exec_status === "hoan_thanh" ? "sec" : ""}" data-finishtank="${esc(t.line_id)}"
          data-endedat="${esc(t.ended_at || "")}" data-vdich="${t.v_dich_hl || 0}" data-baikhi="${t.nuoc_bai_khi_hl || 0}">
          ${t.exec_status === "hoan_thanh" ? "Sửa giờ KT" : "Kết thúc"}</button></td>
        <td>${t.tank_type === "cct" && t.ferment_id ? `<button class="btn sm sec" data-emptycct="${esc(t.ferment_id)}"
          title="Buộc tồn CCT nguồn về 0 khi tank vật lý đã cạn thật nhưng số liệu còn lệch">Làm rỗng lên men</button>` : ""}</td></tr>`).join("") ||
        `<tr><td colspan=8 class="muted">Không có tank nào.</td></tr>`}</tbody>
    </table></div>`);
  document.querySelectorAll("[data-finishtank]").forEach(b => b.onclick = () => {
    const lineId = b.dataset.finishtank;
    openFinishFilterModal("Kết thúc tank " + b.closest("tr").querySelector("td").textContent,
      b.dataset.endedat || null, parseFloat(b.dataset.vdich) || 0, parseFloat(b.dataset.baikhi) || 0,
      async (payload) => {
        await POST(`/brewing/filters/${filterId}/tanks/${lineId}/finish`, payload);
        toast("Đã lưu kết quả lọc"); openFilterTanksModal(filterId, onHandBbt); render("process");
      });
  });
  document.querySelectorAll("[data-emptycct]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Buộc tồn CCT của tank lên men nguồn về 0? Chỉ dùng khi tank vật lý đã cạn thật. Không thể hoàn tác.")) return;
    const res = await POST(`/brewing/ferments/${b.dataset.emptycct}/empty-cct`, {});
    toast(`Đã làm rỗng — tồn CCT: ${res.on_hand_cct} hl`); openFilterTanksModal(filterId, onHandBbt); render("process");
  }));
  if ($("emptybbt_do")) $("emptybbt_do").onclick = () => guard(async () => {
    if (!confirm("Buộc tồn tank thành phẩm (BBT) của lô lọc này về 0? Chỉ dùng khi tank vật lý đã chiết cạn thật. Không thể hoàn tác.")) return;
    const res = await POST(`/brewing/filters/${filterId}/empty-bbt`, {});
    toast(`Đã làm rỗng — tồn BBT: ${res.on_hand_bbt} hl`); openFilterTanksModal(filterId, 0); render("process");
  });
}

// ---------- SVG charts (CH): đã tách sang charts.js (nạp trước app.js) ----------

// caches for dropdowns
let CACHE = { products: [], orders: [], recipes: [] };

// ---------- navigation ----------
const VIEWS = {};
document.querySelectorAll("#nav button").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("#nav button").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".view").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    $("view-" + b.dataset.view).classList.add("active");
    render(b.dataset.view);
  };
});
function render(view) {
  if (window.__rt) { clearInterval(window.__rt); window.__rt = null; }  // dừng auto-refresh realtime
  if (window.__rt30k) { clearInterval(window.__rt30k); window.__rt30k = null; }
  if (window.__scRetry) { clearInterval(window.__scRetry); window.__scRetry = null; }
  guard(VIEWS[view]);
}
// Chuyển hẳn sang view cấp cao nhất khác (VD từ "Chất lượng" nhảy sang "Nấu-Lọc-Chiết") từ code,
// không phải do bấm nút #nav — phải tự làm lại đúng 4 bước mà #nav button onclick vẫn làm
// (render() một mình không bật lại class "active" cho nút/khung view tương ứng).
function switchView(view) {
  document.querySelectorAll("#nav button").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".view").forEach(x => x.classList.remove("active"));
  const navBtn = document.querySelector(`#nav button[data-view="${view}"]`);
  if (navBtn) navBtn.classList.add("active");
  const viewEl = $("view-" + view);
  if (viewEl) viewEl.classList.add("active");
  render(view);
}

// ================= DASHBOARD =================
VIEWS.dashboard = async function () {
  const safe = async (p) => { try { return await GET(p); } catch (e) { return null; } };
  const [batches, audit, prodSummary, agingRows, expiryRows, agingOpsRaw, alerts, fermentsRaw] = await Promise.all([
    GET("/batches"), GET("/audit?limit=10"), safe("/reports/dashboard-summary"),
    safe("/reports/inventory-aging"), safe("/warehouse/expiry?warn_days=14"), safe("/ops-settings"),
    safe("/reports/qc-attention-alerts"), safe("/brewing/ferments"),
  ]);
  const agingOps = agingOpsRaw || { aging_caution_days: 30, aging_warning_days: 60, aging_critical_days: 90 };

  // Chỉ đưa lên dashboard các lô THÀNH PHẨM từ mức "Chú ý" trở lên (ẩn "Bình thường") — xem
  // đầy đủ mọi lô tại Kho TP (WMS) › Tồn kho theo tuổi. Sắp theo số ngày tồn giảm dần (đã sort
  // sẵn từ backend) để lô cần đẩy bán gấp nhất lên đầu.
  const AGING_BUCKET_COLOR = { critical: "#d03b3b", warning: "#ec835a", caution: "#fab219" };
  const AGING_UNIT_LABEL = { vi: "vỉ", keg: "keg", lon: "lon" };
  const AGING_BUCKET_ORDER = ["caution", "warning", "critical"];
  const AGING_BUCKET_META = {
    caution: { label: "Chú ý", threshold: agingOps.aging_caution_days },
    warning: { label: "Cảnh báo", threshold: agingOps.aging_warning_days },
    critical: { label: "Nghiêm trọng", threshold: agingOps.aging_critical_days },
  };
  const agingChartItems = (agingRows || [])
    .filter(r => r.age_bucket && r.age_bucket !== "ok")
    .map(r => ({
      label: `${r.product_display_name || r.product_name || "—"} · lô ${r.lot_code || "—"}`,
      value: r.age_days || 0,
      color: AGING_BUCKET_COLOR[r.age_bucket] || "#8aa0b2",
      disp: `${(r.count || 0).toLocaleString("vi-VN")} ${AGING_UNIT_LABEL[r.unit_type] || r.unit_type} · ${r.age_days} ngày`,
    }));
  // Khi không có lô nào cần chú ý, vẫn hiện biểu đồ (không thay bằng câu chữ) — 3 mức luôn có
  // mặt, giá trị 0 nếu không có lô nào ở mức đó.
  const agingChartDisplay = agingChartItems.length ? agingChartItems : AGING_BUCKET_ORDER.map(b => ({
    label: AGING_BUCKET_META[b].label, value: 0, color: AGING_BUCKET_COLOR[b], disp: "0",
  }));
  // Trục X dùng chung 1 thang đo cố định (không co giãn theo lô dài nhất) để so trực quan với
  // ngưỡng cảnh báo — làm tròn lên bội số 10 gần nhất, luôn phủ hết ngưỡng "nghiêm trọng".
  const agingAxisMax = Math.ceil(Math.max(agingOps.aging_critical_days * 1.1,
    ...agingChartDisplay.map(i => i.value || 0), 10) / 10) * 10;
  // Tổng số lượng theo từng mức (gộp theo loại đơn vị vỉ/keg/lon nếu 1 mức có lẫn nhiều loại)
  // — hiển thị làm 3 ô KPI phía trên biểu đồ.
  const agingKpiTotal = (bucket) => {
    const byUnit = {};
    (agingRows || []).filter(r => r.age_bucket === bucket).forEach(r => {
      const u = AGING_UNIT_LABEL[r.unit_type] || r.unit_type;
      byUnit[u] = (byUnit[u] || 0) + (r.count || 0);
    });
    const parts = Object.entries(byUnit).map(([u, n]) => `${n.toLocaleString("vi-VN")} ${u}`);
    return parts.length ? parts.join(" + ") : "0";
  };
  const agingKpiHtml = AGING_BUCKET_ORDER.map(b => `
    <div style="flex:1;min-width:110px;display:flex;align-items:center;gap:8px">
      <span style="width:12px;height:12px;border-radius:50%;background:${AGING_BUCKET_COLOR[b]};flex:none"></span>
      <div><div class="muted" style="font-size:11px">${AGING_BUCKET_META[b].label}</div>
        <div style="font-size:18px;font-weight:700">${agingKpiTotal(b)}</div></div>
    </div>`).join("");
  const agingLegendHtml = AGING_BUCKET_ORDER.map(b => `
    <span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px;font-size:11px;color:#8aa0b2">
      <span style="width:9px;height:9px;border-radius:2px;background:${AGING_BUCKET_COLOR[b]};display:inline-block"></span>
      ${AGING_BUCKET_META[b].label} (≥${AGING_BUCKET_META[b].threshold} ngày)</span>`).join("");

  // NVL đã hết hạn (số ngày âm, thanh lệch trái) hoặc sắp hết hạn (≤14 ngày, thanh lệch phải;
  // ẩn các lô còn hạn xa) — xem đầy đủ tại Kho NVL › Hạn sử dụng.
  const EXPIRY_WARN_DAYS = 14;
  const EXPIRY_COLOR = { expired: "#d03b3b", near: "#fab219" };
  const expiryChartItems = (expiryRows || [])
    .filter(e => e.status && e.status !== "ok")
    .sort((a, b) => a.days_left - b.days_left)
    .map(e => ({
      label: `${e.material_code ? e.material_code + " — " : ""}${e.material_name || ""}${e.material_name || e.material_code ? " · " : ""}lô ${e.lot_code}`,
      value: e.days_left,
      color: EXPIRY_COLOR[e.status] || "#8aa0b2",
      disp: `${e.status === "expired" ? `Quá hạn ${Math.abs(e.days_left)} ngày` : `Còn ${e.days_left} ngày`} · ${e.quantity.toLocaleString("vi-VN")} ${e.uom}`,
    }));
  // Tương tự — vẫn hiện biểu đồ khi không có lô NVL nào sắp/đã hết hạn.
  const expiryChartDisplay = expiryChartItems.length ? expiryChartItems : [
    { label: "Đã hết hạn", value: 0, color: EXPIRY_COLOR.expired, disp: "0" },
    { label: "Sắp hết hạn", value: 0, color: EXPIRY_COLOR.near, disp: "0" },
  ];
  // Tổng số lô + số lượng theo trạng thái (gộp theo ĐVT nếu lẫn nhiều loại) — 2 ô KPI phía
  // trên biểu đồ, giống cách làm với báo cáo tuổi lô thành phẩm.
  const expiryKpiTotal = (status) => {
    const byUom = {};
    (expiryRows || []).filter(e => e.status === status).forEach(e => {
      byUom[e.uom] = (byUom[e.uom] || 0) + (e.quantity || 0);
    });
    const parts = Object.entries(byUom).map(([u, n]) => `${n.toLocaleString("vi-VN")} ${u}`);
    return parts.length ? parts.join(" + ") : "0";
  };
  const EXPIRY_STATUS_ORDER = ["expired", "near"];
  const EXPIRY_STATUS_LABEL = { expired: "Đã hết hạn", near: `Sắp hết hạn (≤${EXPIRY_WARN_DAYS} ngày)` };
  const expiryKpiHtml = EXPIRY_STATUS_ORDER.map(s => `
    <div style="flex:1;min-width:130px;display:flex;align-items:center;gap:8px">
      <span style="width:12px;height:12px;border-radius:50%;background:${EXPIRY_COLOR[s]};flex:none"></span>
      <div><div class="muted" style="font-size:11px">${EXPIRY_STATUS_LABEL[s]}</div>
        <div style="font-size:18px;font-weight:700">${expiryKpiTotal(s)}</div></div>
    </div>`).join("");
  const expiryLegendHtml = EXPIRY_STATUS_ORDER.map(s => `
    <span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px;font-size:11px;color:#8aa0b2">
      <span style="width:9px;height:9px;border-radius:2px;background:${EXPIRY_COLOR[s]};display:inline-block"></span>
      ${EXPIRY_STATUS_LABEL[s]}</span>`).join("");

  const stageStatCard = (icon, title, s, view, subKey) => `
    <div class="card" style="cursor:pointer;text-align:left" data-goto="${esc(view)}" data-gotosub="${esc(subKey || "")}" tabindex="0" role="button">
      <div class="n">${icon} ${s ? s.total : "–"}</div><div class="l">${esc(title)}</div>
      ${s ? `<div class="muted" style="font-size:11px;margin-top:4px;line-height:1.6">
        ${s.hoan_thanh_hom_nay ? `<span style="color:var(--green)">${s.hoan_thanh_hom_nay} xong hôm nay</span> · ` : ""}
        <span style="color:var(--green)">${s.hoan_thanh}</span> hoàn thành ·
        <span style="color:var(--orange)">${s.dang_thuc_hien}</span> đang thực hiện
        ${s.chua_thuc_hien != null ? ` · <span class="muted">${s.chua_thuc_hien}</span> chưa thực hiện` : ""}
      </div>` : ""}
    </div>`;
  const tankStatCard = (s, view, subKey) => `
    <div class="card" style="cursor:pointer;text-align:left" data-goto="${esc(view)}" data-gotosub="${esc(subKey || "")}" tabindex="0" role="button">
      <div class="n">🛢️ ${s ? `${s.dang_su_dung}/${s.total}` : "–"}</div><div class="l">Tank đang lên men</div>
      ${s ? `<div class="muted" style="font-size:11px;margin-top:4px">${s.trong} tank trống</div>` : ""}
    </div>`;
  // Ô "Cảnh báo QC" trước đây gộp chung 1 bảng — nay tách thành 3 panel riêng theo đúng yêu cầu,
  // mỗi panel lọc từ CÙNG 1 nguồn dữ liệu alerts.items (BE không đổi): (1) Cảnh báo QC = lô có
  // chỉ tiêu đang fail, (2) Hold/Release = lô đang giữ MaterialLot.status=on_hold, (3) Deviation =
  // scope đang có deviation mở. 1 lô có thể xuất hiện ở nhiều panel nếu thoả nhiều điều kiện.
  const REASON_LABEL = { on_hold: "Đang giữ", deviation: "Deviation mở" };
  const qcFailItems = alerts ? alerts.items.filter(it => it.fail_param_count > 0) : [];
  const holdItems = alerts ? alerts.items.filter(it => it.reasons.includes("on_hold")) : [];
  const devItems = alerts ? alerts.items.filter(it => it.reasons.includes("deviation")) : [];
  const miniAlertPanel = (title, icon, items, emptyText, extraCol) => `
    <div class="panel" style="flex:1;min-width:280px;margin-bottom:0">
      <h2>${icon} ${title} ${items.length ? `<span class="muted">(${items.length})</span>` : ""}</h2>
      ${items.length ? `<div class="tablewrap" style="max-height:240px;overflow:auto"><table>
        <thead><tr><th>Lô/Phạm vi</th><th>Vật tư</th><th>SL</th><th>${extraCol.label}</th></tr></thead>
        <tbody>${items.map(it => `<tr style="cursor:pointer" data-goto="flowmap" tabindex="0" role="button">
          <td>${esc(it.lot_code || it.scope_id)}</td>
          <td class="muted">${esc(it.material_code || "—")}</td>
          <td>${it.quantity != null ? it.quantity.toLocaleString("vi-VN") + " " + esc(it.uom || "") : "—"}</td>
          <td>${extraCol.render(it)}</td>
        </tr>`).join("")}</tbody></table></div>`
        : `<div class="muted">${emptyText}</div>`}
    </div>`;
  const alertsHtml = alerts ? `
    <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:stretch;margin-bottom:16px">
      ${miniAlertPanel("Cảnh báo QC", "🚨", qcFailItems, "Không có chỉ tiêu QC nào đang fail.",
        { label: "Chỉ tiêu fail", render: it => `<b style="color:var(--red)">${it.fail_param_count}</b>` })}
      ${miniAlertPanel("Hold / Release", "🔒", holdItems, "Không có lô nào đang giữ.",
        { label: "Trạng thái", render: () => `<span class="badge on_hold">${REASON_LABEL.on_hold}</span>` })}
      ${miniAlertPanel("Deviation", "📋", devItems, "Không có deviation nào đang mở.",
        { label: "Số lượng mở", render: it => `<span class="badge on_hold">${it.deviation_count}</span>` })}
    </div>` : "";
  // Tank đang lên men theo số ngày lên men so ngày quy định — 2 dạng xem (thanh liên tục + lưới ô
  // màu), nhóm theo loại dịch bia rồi sắp theo số ngày quá hạn giảm dần trong từng nhóm. Chỉ lấy
  // tank đang thật sự lên men (status="len_men", xem services/derived.py::ferment_status) và có
  // khai báo ngày lên men chuẩn (ferment_days_std) — thiếu 1 trong 2 thì không xét được quá/còn hạn.
  const FERMENT_STAGE_BG = { accent: "#2c3e50", success: "#14402a", warning: "#4a3410", danger: "#4a1d18" };
  const FERMENT_STAGE_FG = { accent: "var(--blue)", success: "var(--green)", warning: "var(--orange)", danger: "var(--red)" };
  const FERMENT_STAGE_LABEL = { accent: "Đang lên men", success: "Sắp đủ ngày", warning: "Đã đủ ngày", danger: "Quá hạn" };
  const FERMENT_STAGE_ORDER = ["accent", "success", "warning", "danger"];
  const fermentTankItems = ((fermentsRaw && fermentsRaw.items) || [])
    .filter(r => r.status === "len_men" && r.kt_date && r.ferment_days_std)
    .map(r => {
      const days = Math.floor(Math.max(0, new Date() - new Date(r.kt_date)) / 86400000);
      const std = r.ferment_days_std;
      const over = days - std;
      const ratio = days / std;
      const stage = over > 2 ? "danger" : over >= 0 ? "warning" : ratio >= 0.8 ? "success" : "accent";
      return { tank: r.tank_lm, product: r.wort_type || "—", days, std, over, stage, qcFail: r.qc_fail_count || 0,
               lmCode: r.lm_code, productId: r.product_id };
    })
    .sort((a, b) => {
      const p = a.product.localeCompare(b.product, "vi");
      return p !== 0 ? p : b.over - a.over;
    });
  const fermentQcBadge = (n, extraStyle = "", lmCode = null, productId = null) => n > 0
    ? `<span ${lmCode ? `data-fermqc="${esc(lmCode)}|${esc(productId || "")}"` : ""}
        title="${n} chỉ tiêu CT chính/phụ đang fail${lmCode ? " — bấm để xem chi tiết" : ""}"
        style="display:inline-flex;align-items:center;justify-content:center;
        width:15px;height:15px;border-radius:50%;background:var(--red);color:#fff;font-size:9px;font-weight:700;
        ${lmCode ? "cursor:pointer" : ""};${extraStyle}">${n}</span>`
    : "";
  // Chèn tiêu đề nhóm (tên loại dịch) mỗi khi đổi sang dịch bia khác trong danh sách đã sắp xếp.
  const fermentGroupHead = (product, isFirst) => `<div style="font-size:12px;font-weight:700;color:#cdd9e3;
    margin:${isFirst ? "0" : "12px"} 0 6px;padding-top:${isFirst ? "0" : "8px"};${isFirst ? "" : "border-top:1px solid #2b3a47"}">${esc(product)}</div>`;
  const fermentBarScaleMax = Math.max(1, ...fermentTankItems.map(it => Math.max(it.days, it.std)));
  let fermentBarHtml = "", fermentGridHtml = "", lastFermentProduct = null, gridOpen = false;
  fermentTankItems.forEach(it => {
    if (it.product !== lastFermentProduct) {
      fermentBarHtml += fermentGroupHead(it.product, lastFermentProduct === null);
      if (gridOpen) fermentGridHtml += `</div>`;
      fermentGridHtml += fermentGroupHead(it.product, lastFermentProduct === null)
        + `<div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(84px, 1fr));gap:8px">`;
      gridOpen = true;
      lastFermentProduct = it.product;
    }
    const basePct = Math.min(it.days, it.std) / fermentBarScaleMax * 100;
    const overPct = Math.max(it.over, 0) / fermentBarScaleMax * 100;
    const label = it.over > 0 ? `Quá ${it.over} ngày` : `Còn ${Math.abs(it.over)} ngày`;
    fermentBarHtml += `<div style="display:grid;grid-template-columns:82px 1fr 88px;align-items:center;gap:10px;padding:5px 0">
      <div style="font-size:13px;font-weight:700">${esc(it.tank)}${fermentQcBadge(it.qcFail, "margin-left:5px;vertical-align:2px", it.lmCode, it.productId)}</div>
      <div style="position:relative;height:20px;background:#1e2a36;border-radius:3px;overflow:hidden;display:flex">
        <div style="width:${basePct}%;height:100%;background:var(--blue)"></div>
        <div style="width:${overPct}%;height:100%;background:var(--red)"></div>
        <div style="position:absolute;inset:0;display:flex;align-items:center;padding-left:8px;font-size:11px;color:#fff;font-weight:700">${it.days}/${it.std} ngày</div>
      </div>
      <div style="font-size:12px;font-weight:700;color:${it.over > 0 ? "var(--red)" : "#8aa0b2"}">${label}</div>
    </div>`;
    fermentGridHtml += `<div style="position:relative;background:${FERMENT_STAGE_BG[it.stage]};border-radius:6px;padding:6px 8px;text-align:center">
      ${fermentQcBadge(it.qcFail, "position:absolute;top:-6px;right:-6px", it.lmCode, it.productId)}
      <div style="font-size:12px;font-weight:700;color:${FERMENT_STAGE_FG[it.stage]}">${esc(it.tank)}</div>
      <div style="font-size:10px;color:#8aa0b2">${it.days}/${it.std} ngày</div>
    </div>`;
  });
  if (gridOpen) fermentGridHtml += `</div>`;
  if (!fermentTankItems.length) {
    fermentBarHtml = '<div class="muted">Không có tank nào đang lên men.</div>';
    fermentGridHtml = fermentBarHtml;
  }
  const fermentLegendHtml = FERMENT_STAGE_ORDER.map(s => `
    <span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px;font-size:11px;color:#8aa0b2">
      <span style="width:9px;height:9px;border-radius:2px;background:${FERMENT_STAGE_FG[s]};display:inline-block"></span>${FERMENT_STAGE_LABEL[s]}</span>`).join("")
    + `<span style="display:inline-flex;align-items:center;gap:6px;font-size:11px;color:#8aa0b2">${fermentQcBadge(1)} Số chỉ tiêu CT chính/phụ đang fail</span>`;

  // Mặc định NGÀY HÔM QUA (giờ máy client) — giống hệt quy ước ở Báo cáo > Chiết (lon)/(keg):
  // hôm nay chưa qua hết ca 3 nên chưa có đủ dữ liệu để tính trọn 3 ca.
  const dbYesterday = new Date(); dbYesterday.setDate(dbYesterday.getDate() - 1);
  const dbChietDate = SUB.dashboard_chiet_date || toISODateLocal(dbYesterday);
  SUB.dashboard_chiet_date = dbChietDate;
  const dbDienDate = SUB.dashboard_dien_date || toISODateLocal(dbYesterday);
  SUB.dashboard_dien_date = dbDienDate;

  $("view-dashboard").innerHTML = `
    ${alertsHtml}
    <h3 style="color:var(--muted);text-transform:uppercase;letter-spacing:.5px;font-size:12px;margin:4px 2px 10px">Lệnh &amp; mẻ sản xuất (Nấu · Lọc · Chiết)</h3>
    <div class="cards">
      ${stageStatCard("🍺", "Lệnh nấu", prodSummary && prodSummary.lenh_nau, "orders", "lenhnau")}
      ${stageStatCard("🧪", "Lệnh lọc", prodSummary && prodSummary.lenh_loc, "orders", "lenhloc")}
      ${stageStatCard("🔥", "Mẻ nấu", prodSummary && prodSummary.me_nau, "process", "nau")}
      ${tankStatCard(prodSummary && prodSummary.tank_len_men, "process", "lenmen")}
      ${stageStatCard("🧊", "Mẻ lọc", prodSummary && prodSummary.me_loc, "process", "loc")}
      ${stageStatCard("🥤", "Mẻ chiết", prodSummary && prodSummary.me_chiet, "process", "chiet")}
    </div>
    <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:stretch;margin-bottom:16px">
      <div class="panel" style="flex:1;min-width:320px;margin-bottom:0">
        <h2>📦 Tồn kho thành phẩm cần chú ý (theo tuổi lô)</h2>
        <div class="muted" style="margin-bottom:8px">Các lô từ mức 🟡 Chú ý trở lên — xem đầy đủ tại <button class="btn sm sec" data-goto="wms" data-gotosub="aging" style="padding:1px 8px">Kho TP › Tồn kho theo tuổi</button></div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;padding:10px 12px;background:var(--panel2);border:1px solid var(--border);border-radius:10px">${agingKpiHtml}</div>
        <div style="margin-bottom:8px">${agingLegendHtml}</div>
        ${CH.agingBars(agingChartDisplay, { max: agingAxisMax, axisLabel: "Số ngày tồn kho" })}
      </div>
      <div class="panel" style="flex:1;min-width:320px;margin-bottom:0">
        <h2>⏰ Nguyên vật liệu sắp/đã hết hạn</h2>
        <div class="muted" style="margin-bottom:8px">Lô còn tồn kho, đã hết hạn hoặc còn ≤14 ngày — xem đầy đủ tại <button class="btn sm sec" data-goto="warehouse_kc" data-gotosub="han" style="padding:1px 8px">Kho công ty › Hạn sử dụng</button></div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;padding:10px 12px;background:var(--panel2);border:1px solid var(--border);border-radius:10px">${expiryKpiHtml}</div>
        <div style="margin-bottom:8px">${expiryLegendHtml}</div>
        ${CH.hbarsDiverge(expiryChartDisplay, { axisLabel: "← Số ngày quá hạn · Số ngày còn lại →" })}
      </div>
    </div>
    <div class="panel">
      <h2>🍺 Sản lượng chiết 5 ngày gần nhất · theo ca (dữ liệu SCADA thật)</h2>
      <div class="muted" style="margin-bottom:8px">Bia lon: Nhà máy Đông Mai (nguồn 30K_Report) · Bia keg: Nhà máy Hạ Long (nguồn Donggoi). Mỗi ngày có 3 cột Ca 1/Ca 2/Ca 3 — chọn ngày cuối để xem 5 ngày gần nhất tính tới ngày đó.</div>
      <div class="row" style="align-items:flex-end;margin-bottom:12px">
        <div class="field"><label>Ngày cuối (5 ngày gần nhất)</label><input id="db_chiet_date" type="date" value="${dbChietDate}"/></div>
        <button class="btn" id="db_chiet_apply">Xem</button>
      </div>
      <div id="db_chiet_data"><div class="muted">⏳ Đang tải dữ liệu SCADA...</div></div>
    </div>
    <div class="panel">
      <h2>⚡ Điện tiêu thụ 5 ngày gần nhất · theo ca — Nhà máy Hạ Long (dữ liệu SCADA thật)</h2>
      <div class="muted" style="margin-bottom:8px">Nguồn: bảng Energy/NameSys qua kết nối CSDL gán "Dùng cho: Năng lượng — Hạ Long". Mỗi ngày có 3 cột Ca 1/Ca 2/Ca 3 — chọn ngày cuối để xem 5 ngày gần nhất tính tới ngày đó.</div>
      <div class="row" style="align-items:flex-end;margin-bottom:12px">
        <div class="field"><label>Ngày cuối (5 ngày gần nhất)</label><input id="db_dien_date" type="date" value="${dbDienDate}"/></div>
        <button class="btn" id="db_dien_apply">Xem</button>
      </div>
      <div id="db_dien_data"><div class="muted">⏳ Đang tải dữ liệu SCADA...</div></div>
    </div>
    <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:stretch;margin-bottom:16px">
      <div class="panel" style="flex:1;min-width:320px;margin-bottom:0">
        <h2>🍺 Tank đang lên men theo số ngày (so ngày quy định)</h2>
        <div class="muted" style="margin-bottom:8px">Nhóm theo dịch bia, sắp theo số ngày quá hạn — xem đầy đủ tại <button class="btn sm sec" data-goto="process" data-gotosub="lenmen" style="padding:1px 8px">Nấu-Lọc-Chiết › Lên men</button></div>
        <div style="margin-bottom:8px">${fermentLegendHtml}</div>
        ${fermentBarHtml}
      </div>
      <div class="panel" style="flex:1;min-width:320px;margin-bottom:0">
        <h2>🧊 Tank đang lên men theo giai đoạn (lưới)</h2>
        <div class="muted" style="margin-bottom:8px">Mỗi ô = 1 tank, tô màu theo giai đoạn số ngày lên men so ngày quy định.</div>
        <div style="margin-bottom:8px">${fermentLegendHtml}</div>
        ${fermentGridHtml}
      </div>
    </div>
    <div class="panel"><h2>Audit gần đây</h2>${tableAudit(audit)}</div>
    <div class="panel"><h2>Mẻ gần đây</h2>${tableBatches(batches.slice(0, 8))}</div>`;

  document.querySelectorAll("#view-dashboard [data-goto]").forEach(el => {
    el.onclick = () => gotoView(el.dataset.goto, el.dataset.gotosub || null);
  });
  document.querySelectorAll("#view-dashboard [data-fermqc]").forEach(el => {
    el.onclick = () => {
      const [lm, pid] = el.dataset.fermqc.split("|");
      openFermentQcFailModal(lm, pid || null);
    };
  });
  $("db_chiet_apply").onclick = () => {
    SUB.dashboard_chiet_date = $("db_chiet_date").value;
    loadDashboardChiet();
  };
  loadDashboardChiet();
  $("db_dien_apply").onclick = () => {
    SUB.dashboard_dien_date = $("db_dien_date").value;
    loadDashboardDienHL();
  };
  loadDashboardDienHL();
};

// Trả về mảng n ngày (ISO yyyy-mm-dd) tăng dần, kết thúc đúng endDateStr — dùng để dựng
// trục ngày cho biểu đồ 5-ngày ở dashboard (chiết lon/keg, điện tiêu thụ theo ca).
function lastNDates(endDateStr, n) {
  const end = new Date(endDateStr + "T00:00:00");
  const out = [];
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(end); d.setDate(d.getDate() - i);
    out.push(toISODateLocal(d));
  }
  return out;
}

// Tải sản lượng chiết lon (NM Đông Mai) + keg (NM Hạ Long) cho 5 ngày gần nhất (kết thúc tại
// ngày chọn) trên dashboard — dùng đúng /reports/filling-report và /reports/keg-report (CSDL
// SCADA thật) như tab Báo cáo > Chiết (lon)/(keg), KHÔNG dùng số liệu MES nội bộ (BottleRecord)
// nữa. Mỗi ngày gọi riêng 1 request (API chỉ trả theo 1 khung 24h/3 ca) rồi gộp thành biểu đồ
// cột nhóm 3 series (Ca 1/2/3) x 5 ngày bằng CH.groupedN. Tải SAU khi khung màn hình đã hiện
// — tự thoát nếu người dùng đã chuyển tab trước khi tải xong.
async function loadDashboardChiet() {
  const stillHere = () => $("view-dashboard").classList.contains("active") && $("db_chiet_data");
  const days = lastNDates(SUB.dashboard_chiet_date, 5);
  const caColors = ["#3498db", "#f5a623", "#9b59b6"];

  const fetchDay = async (path, dateStr) => {
    const start = new Date(dateStr + "T06:00:00");
    const end = new Date(start); end.setDate(end.getDate() + 1);
    const dateFrom = toDTLocal(start), dateTo = toDTLocal(end);
    try {
      const rpt = await GET(`/reports/${path}?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}`);
      return { ok: true, rpt };
    } catch (e) { return { ok: false, error: e.message }; }
  };
  const [lonDays, kegDays] = await Promise.all([
    Promise.all(days.map(d => fetchDay("filling-report", d))),
    Promise.all(days.map(d => fetchDay("keg-report", d))),
  ]);
  if (!stillHere()) return;

  const dayLabels = days.map(d => new Date(d + "T00:00:00").toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" }));

  const frameStyle = "background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:12px 14px";
  const block = (title, plantNote, unit, results) => {
    if (results.every(r => !r.ok)) {
      const lastErr = results.find(r => !r.ok);
      return `<div style="${frameStyle}">
        <div style="font-size:16px;font-weight:700;margin-bottom:8px">${title}</div>
        <div class="muted">Chưa xem được: ${esc(lastErr.error)} <button class="btn sm sec" data-goto-intg="1">Đi tới Tích hợp › Kết nối CSDL</button></div>
      </div>`;
    }
    const anyGap = results.some(r => r.ok && r.rpt.has_gap);
    const series = [1, 2, 3].map((ca, i) => ({
      label: `Ca ${ca}`, color: caColors[i],
      values: results.map(r => r.ok ? ((r.rpt.by_ca.find(c => c.ca === ca) || {}).value || 0) : 0),
    }));
    const grandTotal = series.reduce((s, ser) => s + ser.values.reduce((a, b) => a + b, 0), 0);
    return `<div style="${frameStyle}">
      <div style="font-size:16px;font-weight:700;margin-bottom:2px">${title}</div>
      <div class="muted" style="font-size:12px;margin-bottom:6px">${esc(plantNote)}</div>
      ${anyGap ? `<div style="color:var(--orange,#f5a623);font-size:12px;margin-bottom:6px">⚠ Có khoảng trống dữ liệu trong CSDL nguồn ở 1+ ngày/ca.</div>` : ""}
      <div class="muted" style="font-size:12px;margin-bottom:4px">Tổng 5 ngày: <b style="color:#2ecc71">${grandTotal.toLocaleString("vi-VN")} ${esc(unit)}</b></div>
      ${CH.groupedN(dayLabels, series, { unit, height: 130 })}
    </div>`;
  };

  $("db_chiet_data").innerHTML = `<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:stretch">
    <div style="flex:1;min-width:280px">${block("🥫 Dây chuyền 30.000 lon/giờ", "NM Đông Mai", "lon", lonDays)}</div>
    <div style="flex:1;min-width:280px">${block("🛢️ Dây chuyền 400 keg/giờ", "NM Hạ Long", "keg", kegDays)}</div>
  </div>`;
  document.querySelectorAll("#db_chiet_data [data-goto-intg]").forEach(b => b.onclick = () => gotoView("integration", "dbconn"));
}

// Tải điện tiêu thụ theo ca (Ca1/Ca2/Ca3) cho Nhà máy Hạ Long trên dashboard, 5 ngày gần nhất
// — dùng đúng /energy/external-ca-report?site=hl (CSDL SCADA thật) như tab Năng lượng > Báo
// cáo NL - Hạ Long. CHỈ Hạ Long — chưa đưa dữ liệu Đông Mai (site=dm) ra dashboard theo yêu
// cầu. Tải SAU khi khung màn hình đã hiện — tự thoát nếu người dùng đã chuyển tab trước khi
// tải xong.
async function loadDashboardDienHL() {
  const stillHere = () => $("view-dashboard").classList.contains("active") && $("db_dien_data");
  const days = lastNDates(SUB.dashboard_dien_date, 5);
  const caColors = ["#3498db", "#f5a623", "#9b59b6"];

  const fetchDay = async (dateStr) => {
    const start = new Date(dateStr + "T06:00:00");
    const end = new Date(start); end.setDate(end.getDate() + 1);
    const dateFrom = toDTLocal(start), dateTo = toDTLocal(end);
    try {
      const rpt = await GET(`/energy/external-ca-report?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}&site=hl`);
      return { ok: true, rpt };
    } catch (e) { return { ok: false, error: e.message }; }
  };

  const results = await Promise.all(days.map(fetchDay));
  if (!stillHere()) return;

  const frameStyle = "background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:12px 14px";
  const reservedBox = `<div style="${frameStyle};display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;min-height:130px">
    <div style="font-size:16px;font-weight:700;margin-bottom:6px">🏭 Nhà máy Đông Mai</div>
    <div class="muted" style="font-size:12px">Dự phòng cho báo cáo năng lượng Nhà máy Đông Mai — sẽ bổ sung sau.</div>
  </div>`;

  if (results.every(r => !r.ok)) {
    const lastErr = results.find(r => !r.ok);
    $("db_dien_data").innerHTML = `<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:stretch">
      <div style="flex:1;min-width:280px">
        <div style="${frameStyle}">
          <div style="font-size:16px;font-weight:700;margin-bottom:8px">⚡ Nhà máy Hạ Long</div>
          <div class="muted">Chưa xem được: ${esc(lastErr.error)} <button class="btn sm sec" id="db_dien_goto_intg">Đi tới Tích hợp › Kết nối CSDL</button></div>
        </div>
      </div>
      <div style="flex:1;min-width:280px">${reservedBox}</div>
    </div>`;
    $("db_dien_goto_intg").onclick = () => gotoView("integration", "dbconn");
    return;
  }

  const dayLabels = days.map(d => new Date(d + "T00:00:00").toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" }));
  const anyGap = results.some(r => r.ok && r.rpt.has_gap);
  const series = [1, 2, 3].map((ca, i) => ({
    label: `Ca ${ca}`, color: caColors[i],
    values: results.map(r => r.ok ? ((r.rpt.by_ca.find(c => c.ca === ca) || {}).value || 0) : 0),
  }));
  const grandTotal = series.reduce((s, ser) => s + ser.values.reduce((a, b) => a + b, 0), 0);
  $("db_dien_data").innerHTML = `<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:stretch">
    <div style="flex:1;min-width:280px">
      <div style="${frameStyle}">
        <div style="font-size:16px;font-weight:700;margin-bottom:6px">⚡ Nhà máy Hạ Long</div>
        ${anyGap ? `<div style="color:var(--orange,#f5a623);font-size:12px;margin-bottom:6px">⚠ Có 1+ hệ thống bị khoảng trống dữ liệu lớn trong 1+ ngày/ca.</div>` : ""}
        <div class="muted" style="font-size:12px;margin-bottom:4px">Tổng 5 ngày: <b style="color:#2ecc71">${grandTotal.toLocaleString("vi-VN")} kWh</b></div>
        ${CH.groupedN(dayLabels, series, { unit: "kWh", height: 130 })}
      </div>
    </div>
    <div style="flex:1;min-width:280px">${reservedBox}</div>
  </div>`;
}

// ================= SƠ ĐỒ QUY TRÌNH (flowmap) =================
function gotoView(view, subKey) {
  const btn = document.querySelector(`#nav button[data-view="${view}"]`);
  if (!btn) return;
  if (btn.style.display === "none") { toast("Bạn không có quyền truy cập mục này.", "err"); return; }
  if (subKey) SUB[view] = subKey;
  btn.click();
}
function flowNode(view, step, name, desc, count, subKey, opts) {
  const unused = opts && opts.unused;
  return `<div class="flownode${unused ? " unused" : ""}" data-goto="${esc(view)}" data-gotosub="${esc(subKey || "")}" tabindex="0" role="button">
    <div class="step">${esc(step)}</div>
    <div class="name">${esc(name)}</div>
    <div class="desc">${esc(desc)}</div>
    ${count != null ? `<div class="count">${esc(count)}</div>` : ""}
    ${unused ? `<div class="unused-badge">Tạm thời chưa dùng</div>` : ""}
  </div>`;
}
function flowArrow() { return `<div class="flowarrow">→</div>`; }
function flowChip(view, label, subKey) {
  return `<div class="flowchip" data-goto="${esc(view)}" data-gotosub="${esc(subKey || "")}" tabindex="0" role="button"><span class="dot"></span>${esc(label)}</div>`;
}

VIEWS.flowmap = async function () {
  const safe = async (p) => { try { return await GET(p); } catch (e) { return null; } };
  const [brewOrders, filterOrders, lots] = await Promise.all([
    safe("/brewing/brew-master-orders"), safe("/brewing/filter-master-orders"), safe("/lots"),
  ]);
  const onHoldLots = (lots || []).filter(l => l.status === "on_hold").length;
  const lenhCount = (brewOrders && filterOrders) ? `${brewOrders.length} lệnh nấu · ${filterOrders.length} lệnh lọc` : null;

  $("view-flowmap").innerHTML = `
    <div class="panel">
      <h2>🗺️ Sơ đồ quy trình sản xuất</h2>
      <div class="muted" style="margin-bottom:14px">Toàn bộ đường đi của nguyên liệu — từ lúc nhập kho đến khi sản phẩm xuất khỏi nhà máy. Bấm vào một bước để mở đúng tab nghiệp vụ tương ứng.</div>

      <h3>Chuỗi chính (theo thứ tự thực hiện)</h3>
      <div class="flowlane">
        ${flowNode("warehouse_kc", "Bước 1", "Kho NVL", "Nhập nguyên liệu, quản lý lô, khai báo/duyệt chỉ tiêu chất lượng.")}
        ${flowArrow()}
        ${flowNode("orders", "Bước 2", "Lệnh SX", "Số lượng lấy trực tiếp theo Lệnh nấu/Lệnh lọc — tạm thời bỏ qua tích hợp ERP.", lenhCount)}
        ${flowArrow()}
        ${flowNode("dispatch", "Bước 3", "Điều độ", "Lập work order theo dây chuyền/ca/ngày, “Phát mẻ” để tạo mẻ sản xuất.", null, null, { unused: true })}
        ${flowArrow()}
        ${flowNode("batches", "Bước 4", "Mẻ sản xuất", "Theo dõi các mẻ đã tạo, đối chiếu định mức BOM với tồn kho.", null, null, { unused: true })}
        ${flowArrow()}
        ${flowNode("dispense", "Bước 5", "Cấp liệu", "Xuất nguyên liệu cho mẻ — chọn lô theo FEFO hoặc backflush tự động.", null, null, { unused: true })}
        ${flowArrow()}
        ${flowNode("process", "Bước 6", "Mẻ nấu", "Ghi thông tin nấu + khai báo chỉ tiêu riêng cho từng mẻ (giống cơ chế chỉ tiêu NVL).", null, "nau")}
        ${flowArrow()}
        ${flowNode("process", "Bước 7", "Lên men chính", "1 tank lên men nhận nhiều mẻ nấu (liên kết thật, chọn ở mục Lên men) — khai báo chỉ tiêu lên men chính.", null, "lenmen")}
        ${flowArrow()}
        ${flowNode("process", "Bước 8", "Lên men phụ", "Cùng lô LM ở trên — khai báo tiếp chỉ tiêu lên men phụ.", null, "lenmen")}
        ${flowArrow()}
        ${flowNode("process", "Bước 9", "Lọc", "Chuyển dịch từ tank LM vào tank BBT — khai báo chỉ tiêu sau lọc.", null, "loc")}
        ${flowArrow()}
        ${flowNode("process", "Bước 10", "Chiết", "Chiết từ tank BBT ra dây chuyền — chỉ tiêu khai báo chung với Thành phẩm ở bước sau.", null, "chiet")}
        ${flowArrow()}
        ${flowNode("process", "Bước 11", "Thành phẩm", "Chỉ tiêu release cuối cùng của lô bia (cùng mã chiết) trước khi nhập kho theo vỉ/keg.", null, "chiet")}
        ${flowArrow()}
        ${flowNode("quality", "Bước 12", "Chất lượng", "Ghi kết quả QC, hold/release mẻ & lô — cổng chặn trước khi qua kho TP.", onHoldLots ? onHoldLots + " lô đang HOLD" : null)}
        ${flowArrow()}
        ${flowNode("wms", "Bước 13", "Kho TP (WMS)", "Nhập kho thành phẩm theo vỉ/keg, xuất kho (đổi trạng thái đã xuất).")}
      </div>
      <div class="muted" style="font-size:12px;margin-top:-6px;margin-bottom:18px">⚠ "Xuất kho" ở bước cuối hiện chỉ đổi trạng thái vỉ/keg thành đã xuất — hệ thống chưa có module khách hàng/đơn hàng bán để theo dõi tiếp việc giao ra thị trường.</div>

      <div class="flowtrace" data-goto="trace" data-gotosub="" tabindex="0" role="button">
        <div class="flowtrace-ico">🔎</div>
        <div>
          <div class="flowtrace-title">Truy xuất nguồn gốc</div>
          <div class="flowtrace-desc">Không phải 1 bước tuần tự — áp dụng cho <b>toàn bộ chuỗi</b> ở trên: lần xuôi (nguyên liệu → sản phẩm) hoặc lần ngược (sản phẩm → nguyên liệu/mẻ liên quan) và mô phỏng thu hồi. Bấm để mở.</div>
        </div>
      </div>

      <h3 style="margin-top:20px">Dữ liệu nền & công cụ hỗ trợ</h3>
      <div class="flowchips">
        ${flowChip("recipes", "Công thức — BOM & quy trình chuẩn")}
        ${flowChip("recipeadv", "Công thức+ — hiệu suất & đổi công thức có kiểm soát")}
        ${flowChip("isa88", "ISA-88 — trạng thái công đoạn/pha")}
        ${flowChip("schedule", "Lập lịch — xếp tank/CIP, phát hiện xung đột")}
        ${flowChip("packaging", "Bao bì — vỏ/chai/keg tuần hoàn")}
      </div>
    </div>`;

  document.querySelectorAll("[data-goto]").forEach(el => {
    el.onclick = () => gotoView(el.dataset.goto, el.dataset.gotosub || null);
    el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); gotoView(el.dataset.goto, el.dataset.gotosub || null); } };
  });
};

// ================= ORDERS (Lệnh sản xuất) =================
// Khu vực tập trung các loại lệnh sản xuất: Lệnh SX (ERP) hiện có, Lệnh nấu (đã chuyển từ
// tab Nấu-Lọc-Chiết sang đây), và sau này sẽ thêm Lệnh lọc / Lệnh chiết vào cùng subnav này.
VIEWS.orders = async function () {
  const sec = SUB.orders || "lenhnau";
  const sections = [
    { key: "lenhnau", label: "Lệnh nấu" }, { key: "lenhloc", label: "Lệnh lọc" },
    { key: "po", label: "Lệnh SX (ERP)" },
  ];
  let body = "";
  let approvedTanksLf = [];
  let availableBbtTanksLf = [];

  if (sec === "po") {
    const [orders, products] = await Promise.all([GET("/orders"), GET("/products")]);
    CACHE.products = products;
    const opts = products.map(p => `<option value="${p.product_id}">${esc(p.code)} — ${esc(p.name)}</option>`).join("");
    body = `<div class="panel">
      <h2>Tạo lệnh sản xuất (ERP)</h2>
      <div class="row">
        <div class="field"><label>Mã lệnh</label><input id="o_code" placeholder="PO-..." /></div>
        <div class="field"><label>Sản phẩm</label><select id="o_prod">${opts}</select></div>
        <div class="field"><label>SL kế hoạch</label><input id="o_qty" type="number" value="50000" /></div>
        <div class="field"><label>ĐVT</label><input id="o_uom" value="L" size="4" /></div>
        <div class="field"><label>Ưu tiên</label><input id="o_pri" type="number" value="5" size="3" /></div>
        <button class="btn" id="o_save">Tạo lệnh</button>
      </div>
    </div>
    <div class="panel"><h2>Danh sách lệnh</h2>
      <input class="searchbox" data-tbl="t_po" placeholder="Tìm theo mã lệnh, sản phẩm, trạng thái..."/>
      <div class="tablewrap"><table id="t_po"><thead><tr><th>Mã</th><th>Sản phẩm</th><th>SL</th><th>Ưu tiên</th><th>Trạng thái</th><th>Tạo lúc</th></tr></thead>
      <tbody>${orders.map(o => `<tr><td><code class="k">${esc(o.order_code)}</code></td>
        <td>${esc(prodName(o.product_id))}</td><td>${o.planned_qty} ${o.uom}</td>
        <td>${o.priority}</td><td>${badge(o.status)}</td><td class="muted">${fmt(o.created_at)}</td></tr>`).join("")}</tbody></table></div>
    </div>`;
  }

  else if (sec === "lenhnau") {
    const [masters, products] = await Promise.all([GET("/brewing/brew-master-orders"), GET("/products").catch(() => [])]);
    CACHE.productsLn = products;
    body = `<div class="panel"><h2 id="lo_form_title">Tạo Lệnh nấu</h2>
      <div class="muted" style="margin-bottom:6px">1 Lệnh nấu (số lệnh) có thể chứa nhiều "Lệnh nấu nhỏ" bên trong — mỗi lệnh nhỏ ứng với đúng
        1 dịch bia, tự có sản lượng kế hoạch/sai số riêng. Mỗi mã nấu (tạo ở tab "Nấu-Lọc-Chiết → Nấu") bắt buộc chọn đúng 1 lệnh nhỏ CHƯA
        hoàn thành — sản lượng thực tế cộng dồn qua các mã nấu tới khi đạt kế hoạch (±sai số) thì lệnh nhỏ đó hoàn thành, không chọn được nữa.
        Định mức NVL của mỗi lệnh nhỏ luôn tự nạp từ Công thức (BOM) hiệu lực của dịch bia đã chọn. Khi in sẽ in chung 1 tờ gồm tất cả lệnh
        nhỏ bên trong.</div>
      <div class="row">
        <div class="field"><label>Số lệnh</label><input id="lo_code" placeholder="VD: 36/PXSXBĐM-T6/2026"/></div>
        <div class="field"><label>Người ra lệnh</label><input id="lo_issuedby" placeholder="(tuỳ chọn)"/></div>
        <div class="field"><label>Đơn vị thực hiện</label><input id="lo_exec" value="Phân xưởng bia Đông Mai"/></div>
        <div class="field"><label>Thủ kho</label><input id="lo_kho" value="Thủ kho"/></div>
      </div>
      <div class="row">
        <div class="field" style="flex:1"><label>Căn cứ</label><input id="lo_refnote" placeholder="VD: Căn cứ theo kế hoạch sản xuất..."/></div>
        <div class="field"><label>Thời gian bắt đầu</label><input id="lo_start" type="datetime-local"/></div>
        <div class="field"><label>Thời gian kết thúc</label><input id="lo_end" type="datetime-local"/></div>
      </div>
      <div class="row">
        <div class="field" style="flex:1"><label>Biện pháp an toàn</label><input id="lo_safety" placeholder="(tuỳ chọn)"/></div>
      </div>
      <div id="lo_children"></div>
      <div class="row"><button class="btn sec" id="lo_addchild">+ Thêm lệnh nấu nhỏ</button></div>
      <div class="row"><button class="btn" id="lo_add" style="align-self:flex-end">Tạo lệnh nấu</button>
        <span id="lo_cancel_wrap"></span></div></div>
      <div class="panel"><h2>Danh sách Lệnh nấu <span class="muted">(${masters.length})</span></h2>
      <input class="searchbox" data-tbl="t_lenhnau" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_lenhnau"><thead><tr><th>Số lệnh</th><th>Lệnh nhỏ</th>
        <th>Thực tế/KH (hl)</th><th>Ngày lập</th><th>Trạng thái</th><th></th></tr></thead>
      <tbody>${masters.map(m => `<tr>
        <td class="code">${esc(m.order_code)}</td>
        <td class="muted">${m.children.map((c, i) => `#${i + 1} ${esc(c.product_code || c.product_desc || "—")}
          (${c.actual_volume_hl}/${c.planned_volume_hl}hl${c.tank_lm ? " · tank dự kiến " + esc(c.tank_lm) : ""})${c.is_complete ? " ✓" : ""}`).join("; ")}</td>
        <td class="muted">${m.actual_total_hl}/${m.planned_total_hl}</td>
        <td class="muted">${fmt(m.created_at)}</td>
        <td>${m.is_complete_all
          ? `<span style="color:var(--green)">✓ Hoàn thành</span>`
          : (m.is_executed_any
              ? `<span class="muted">Đang nấu</span>`
              : `<span class="muted">Chưa thực hiện</span>`)}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-viewlo="${esc(m.brew_master_order_id)}">Xem</button>
          <button class="btn sm sec" data-printlo="${esc(m.brew_master_order_id)}">🖨️ In</button>
          ${!m.is_executed_any ? `<button class="btn sm sec" data-editlo="${esc(m.brew_master_order_id)}">Sửa</button>
          <button class="btn sm sec" data-dello="${esc(m.brew_master_order_id)}">Xóa</button>` : ""}</td></tr>`).join("") ||
        `<tr><td colspan=6 class="muted">Chưa có lệnh nấu nào.</td></tr>`}</tbody></table></div></div>`;
  }

  else if (sec === "lenhloc") {
    const [masters, fermentsData, materialsLf, bbtTanksLf, finishedProductsLf] = await Promise.all([
      GET("/brewing/filter-master-orders"), GET("/brewing/ferments"), GET("/materials"),
      GET("/brewing/bbt-tanks").catch(() => []), GET("/finished-products")]);
    // Tank đã lọc hết (on_hand_cct về 0 hoặc âm — derived.ferment_status trả "da_loc_het")
    // không còn dịch để lọc thêm nữa, dù đã KCS duyệt cũng không hiện ra để chọn lại.
    approvedTanksLf = fermentsData.items.filter(f => f.qc_approved && f.status !== "da_loc_het");
    // Tank thành phẩm (BBT) đủ điều kiện làm NGUỒN lọc lại — đã lọc xong + KCS duyệt hết
    // (xem services/filter_order.py::available_bbt_tanks); còn khả dụng bao nhiêu (sau khi
    // trừ phần đã bị lệnh khác giữ chỗ) hiện ở remaining_hl.
    availableBbtTanksLf = bbtTanksLf.filter(t => t.eligible_for_refilter_source);
    CACHE.materialsLf = materialsLf;
    CACHE.finishedProductsLf = finishedProductsLf;
    body = `<div class="panel"><h2>Tạo Lệnh lọc</h2>
      <div class="muted" style="margin-bottom:6px">1 Lệnh lọc (số lệnh) có thể chứa nhiều "Lệnh lọc nhỏ" bên trong — mỗi lệnh nhỏ tự chọn
        <b>Không phối</b> (1 tank lên men) hoặc <b>Phối</b> (2+ tank, phải cùng 1 dịch bia), tự có vật tư riêng, tự khai báo thể tích dịch kế hoạch
        riêng. Khi in sẽ in chung 1 tờ gồm tất cả lệnh nhỏ. Mỗi bản ghi lọc thật (ở tab "Nấu-Lọc-Chiết → Lọc") chọn đúng 1 lệnh nhỏ CHƯA hoàn thành
        để thực hiện — sản lượng cộng dồn tới khi đạt thể tích kế hoạch (±sai số) của lệnh nhỏ đó thì không chọn được nữa.</div>
      <div class="row">
        <div class="field"><label>Số lệnh</label><input id="lf_code" placeholder="VD: LOC-0715"/></div>
        <div class="field" style="flex:1"><label>Ghi chú</label><input id="lf_note" placeholder="(tuỳ chọn)"/></div>
      </div>
      <div id="lf_children"></div>
      <div class="row"><button class="btn sec" id="lf_addchild">+ Thêm lệnh lọc nhỏ</button></div>
      <div class="row"><button class="btn" id="lf_add" style="align-self:flex-end">Tạo lệnh lọc</button>
        <span id="lf_cancel_wrap"></span></div></div>
      <div class="panel"><h2>Danh sách Lệnh lọc <span class="muted">(${masters.length})</span></h2>
      <input class="searchbox" data-tbl="t_lenhloc" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_lenhloc"><thead><tr><th>Số lệnh</th><th>Lệnh nhỏ</th>
        <th>Thể tích (hl)</th><th>Ngày lập</th><th>Trạng thái</th><th></th></tr></thead>
      <tbody>${masters.map(m => `<tr>
        <td class="code">${esc(m.order_code)}</td>
        <td class="muted">${m.children.map((c, i) => `#${i + 1} ${c.blend_mode === "phoi" ? "Phối" : "Không phối"}
          (${c.tanks.map(t => esc(t.tank_type === "bbt" ? `BBT ${t.source_bbt_code} (lọc lại)` : t.tank_lm)).join(", ") || "—"})
          ${c.finished_product_code ? ` · SP: ${esc(c.finished_product_code)}` : ""}${c.is_complete ? " ✓" : ""}`).join("; ")}</td>
        <td class="muted">${m.actual_total_hl}/${m.planned_total_hl}</td>
        <td class="muted">${fmt(m.created_at)}</td>
        <td>${m.is_complete_all
          ? `<span style="color:var(--green)">✓ Hoàn thành</span>`
          : (m.is_executed_any
              ? `<span class="muted">Đang lọc</span>`
              : `<span class="muted">Chưa thực hiện</span>`)}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-viewlf="${esc(m.filter_master_order_id)}">Xem</button>
          <button class="btn sm sec" data-printlf="${esc(m.filter_master_order_id)}">🖨️ In</button>
          ${!m.is_executed_any ? `<button class="btn sm sec" data-editlf="${esc(m.filter_master_order_id)}">Sửa</button>
          <button class="btn sm sec" data-dellf="${esc(m.filter_master_order_id)}">Xóa</button>` : ""}</td></tr>`).join("") ||
        `<tr><td colspan=6 class="muted">Chưa có lệnh lọc nào.</td></tr>`}</tbody></table></div></div>`;
  }

  $("view-orders").innerHTML = subnav("orders", sections, sec) + body;
  wireSubnav("orders"); wireSearch();
  wirePaginate("t_po", 10); wirePaginate("t_lenhnau", 10); wirePaginate("t_lenhloc", 10);

  if (sec === "po") $("o_save").onclick = () => guard(async () => {
    await POST("/orders", { order_code: $("o_code").value, product_id: $("o_prod").value,
      planned_qty: parseFloat($("o_qty").value), uom: $("o_uom").value, priority: parseInt($("o_pri").value) });
    toast("Đã tạo lệnh sản xuất"); render("orders");
  });

  if (sec === "lenhnau") {
    let editingMasterId = null;
    function setLoFormMode(editing) {
      $("lo_form_title").textContent = editing ? "Sửa Lệnh nấu" : "Tạo Lệnh nấu";
      $("lo_add").textContent = editing ? "Lưu chỉnh sửa lệnh nấu" : "Tạo lệnh nấu";
      $("lo_cancel_wrap").innerHTML = editing ? `<button class="btn sm sec" id="lo_canceledit" style="align-self:flex-end">Hủy sửa</button>` : "";
      if (editing) $("lo_canceledit").onclick = () => render("orders");
    }
    const newLnChild = () => ({ productId: "", batchCount: 1, plannedVol: "", tolerance: 0,
      bxMin: "", bxMax: "", tankLm: "", batchFrom: "", batchTo: "" });
    let lnChildren = [newLnChild()];

    function fetchLnBomPreview(ci) {
      const c = lnChildren[ci];
      if (!c.productId) throw new Error(`Lệnh nấu nhỏ #${ci + 1}: Chọn Dịch bia để xem định mức NVL theo Công thức.`);
      const volHl = parseFloat(c.plannedVol) || 0;
      if (!volHl) throw new Error(`Lệnh nấu nhỏ #${ci + 1}: Nhập Sản lượng nấu kế hoạch (hl) trước.`);
      const batches = parseInt(c.batchCount, 10) || 1;
      const qs = `product_id=${encodeURIComponent(c.productId)}&planned_batch_count=${batches}&planned_volume_hl=${volHl}`;
      return GET(`/brewing/orders/bom-preview?${qs}`);
    }

    function renderLnChildren() {
      $("lo_children").innerHTML = lnChildren.map((c, ci) => `
        <div class="panel" style="margin-top:8px;border:1px solid var(--border)">
          <div class="row" style="align-items:center">
            <h3 style="font-size:14px;margin:0;flex:1">Lệnh nấu nhỏ #${ci + 1}</h3>
            ${lnChildren.length > 1 ? `<button class="btn sm sec" data-lnchildrm="${ci}">Xóa lệnh nhỏ</button>` : ""}
          </div>
          <div class="row">
            <div class="field"><label>Dịch bia</label><select class="lnc_wort" data-ci="${ci}">
              <option value="">(chọn Dịch bia — bắt buộc)</option>${(CACHE.productsLn || []).map(p =>
                `<option value="${esc(p.product_id)}" ${p.product_id === c.productId ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></div>
            <div class="field"><label>Số mẻ kế hoạch</label><input class="lnc_batches" data-ci="${ci}" type="number" min="1" value="${c.batchCount}"/></div>
            <div class="field"><label>Sản lượng nấu kế hoạch (hl)</label><input class="lnc_volplan" data-ci="${ci}" type="number" value="${c.plannedVol}" placeholder="VD: 100"/></div>
            <div class="field"><label>Sai số cho phép (±hl)</label><input class="lnc_voltol" data-ci="${ci}" type="number" value="${c.tolerance}"/></div>
          </div>
          <div class="row"><button class="btn sec" data-lnc-preview="${ci}" style="align-self:flex-end">📋 Xem NVL (đủ/thiếu tồn)</button></div>
          <div class="lnc_preview" data-ci="${ci}"></div>
        </div>`).join("");

      document.querySelectorAll(".lnc_wort").forEach(sel => sel.onchange = () => { lnChildren[parseInt(sel.dataset.ci, 10)].productId = sel.value; });
      document.querySelectorAll(".lnc_batches").forEach(inp => inp.onchange = () => { lnChildren[parseInt(inp.dataset.ci, 10)].batchCount = inp.value; });
      document.querySelectorAll(".lnc_volplan").forEach(inp => inp.onchange = () => { lnChildren[parseInt(inp.dataset.ci, 10)].plannedVol = inp.value; });
      document.querySelectorAll(".lnc_voltol").forEach(inp => inp.onchange = () => { lnChildren[parseInt(inp.dataset.ci, 10)].tolerance = inp.value; });
      document.querySelectorAll("[data-lnc-preview]").forEach(b => b.onclick = () => guard(async () => {
        const ci = parseInt(b.dataset.lncPreview, 10);
        const lines = await fetchLnBomPreview(ci);
        const box = document.querySelector(`.lnc_preview[data-ci="${ci}"]`);
        if (!lines.length) {
          box.innerHTML = `<div class="muted" style="margin-top:8px">Dịch bia này chưa có Công thức (BOM) hiệu lực — không có định mức để xem.</div>`;
          return;
        }
        const shortageCount = lines.filter(l => l.shortage).length;
        box.innerHTML = `<div class="panel" style="margin-top:8px">
          <h3 style="font-size:14px">Xem trước định mức NVL ${shortageCount
            ? `<span style="color:var(--red)">— ⚠ ${shortageCount} dòng thiếu tồn</span>`
            : `<span style="color:var(--green)">— ✓ đủ tồn tất cả</span>`}</h3>
          <div class="tablewrap"><table><thead><tr><th>STT</th><th>Tên NVL</th><th>ĐVT</th><th>Nhu cầu 1 mẻ</th>
            <th>Nhu cầu Tổng mẻ</th><th>Tồn Kho công ty</th><th>Tồn Kho phân xưởng</th><th>Trạng thái</th></tr></thead>
          <tbody>${lines.map(l => `<tr class="${l.shortage ? "row-red" : ""}">
            <td>${esc(l.stt_label || "")}</td><td>${esc(l.material_name || "—")}</td><td>${esc(l.uom || "")}</td>
            <td>${l.qty_per_batch ?? "—"}</td><td>${l.qty_total ?? "—"}</td>
            <td>${l.stock_company_snapshot ?? "—"}</td><td>${l.stock_workshop_snapshot ?? "—"}</td>
            <td>${l.material_id
              ? (l.shortage ? '<span class="badge on_hold">⚠ Thiếu</span>' : '<span class="badge available">✓ Đủ</span>')
              : '<span class="muted">—</span>'}</td></tr>`).join("")}</tbody></table></div></div>`;
      }));
      document.querySelectorAll("[data-lnchildrm]").forEach(b => b.onclick = () => {
        lnChildren.splice(parseInt(b.dataset.lnchildrm, 10), 1); renderLnChildren();
      });
    }
    renderLnChildren();
    $("lo_addchild").onclick = () => { lnChildren.push(newLnChild()); renderLnChildren(); };

    $("lo_add").onclick = () => guard(async () => {
      const code = $("lo_code").value.trim();
      if (!code) throw new Error("Nhập Số lệnh.");
      const children = lnChildren.map((c, ci) => {
        const volHl = parseFloat(c.plannedVol) || 0;
        if (!(volHl > 0)) throw new Error(`Lệnh nấu nhỏ #${ci + 1}: Nhập Sản lượng nấu kế hoạch (hl) (phải lớn hơn 0).`);
        return {
          product_id: c.productId || null,
          planned_batch_count: parseInt(c.batchCount, 10) || 1,
          planned_volume_hl: volHl,
          volume_tolerance_hl: parseFloat(c.tolerance) || 0,
          bx_min: c.bxMin === "" ? null : parseFloat(c.bxMin),
          bx_max: c.bxMax === "" ? null : parseFloat(c.bxMax),
          tank_lm: (c.tankLm || "").trim() || null,
          batch_range_from: c.batchFrom === "" ? null : parseInt(c.batchFrom, 10),
          batch_range_to: c.batchTo === "" ? null : parseInt(c.batchTo, 10),
          auto_from_bom: true, lines: [],
        };
      });
      const payload = {
        order_code: code,
        issued_by: $("lo_issuedby").value.trim() || null,
        executor_unit: $("lo_exec").value.trim() || null,
        warehouse_keeper: $("lo_kho").value.trim() || null,
        reference_note: $("lo_refnote").value.trim() || null,
        start_date: $("lo_start").value || null,
        end_date: $("lo_end").value || null,
        safety_note: $("lo_safety").value.trim() || null,
        children,
      };
      if (editingMasterId) {
        await PUT(`/brewing/brew-master-orders/${editingMasterId}`, payload);
        toast("Đã lưu lệnh nấu");
      } else {
        await POST("/brewing/brew-master-orders", payload);
        toast("Đã tạo lệnh nấu");
      }
      render("orders");
    });

    document.querySelectorAll("[data-viewlo]").forEach(b => b.onclick = () => openBrewMasterOrderModal(b.dataset.viewlo));
    document.querySelectorAll("[data-printlo]").forEach(b => b.onclick = () => guard(async () => {
      printBrewOrder(await GET(`/brewing/brew-master-orders/${b.dataset.printlo}`));
    }));
    document.querySelectorAll("[data-editlo]").forEach(b => b.onclick = () => guard(async () => {
      const m = await GET(`/brewing/brew-master-orders/${b.dataset.editlo}`);
      editingMasterId = m.brew_master_order_id;
      $("lo_code").value = m.order_code;
      $("lo_issuedby").value = m.issued_by || "";
      $("lo_exec").value = m.executor_unit || "";
      $("lo_kho").value = m.warehouse_keeper || "";
      $("lo_refnote").value = m.reference_note || "";
      $("lo_start").value = m.start_date ? m.start_date.slice(0, 16) : "";
      $("lo_end").value = m.end_date ? m.end_date.slice(0, 16) : "";
      $("lo_safety").value = m.safety_note || "";
      lnChildren = m.children.map(c => ({
        productId: c.product_id || "", batchCount: c.planned_batch_count || 1,
        plannedVol: c.planned_volume_hl || "", tolerance: c.volume_tolerance_hl || 0,
        bxMin: c.bx_min ?? "", bxMax: c.bx_max ?? "", tankLm: c.tank_lm || "",
        batchFrom: c.batch_range_from ?? "", batchTo: c.batch_range_to ?? "",
      }));
      renderLnChildren();
      setLoFormMode(true);
      $("lo_code").scrollIntoView({ behavior: "smooth", block: "center" });
      toast(`Đang sửa lệnh ${m.order_code} — thay đổi rồi bấm "Lưu chỉnh sửa lệnh nấu"`);
    }));
    document.querySelectorAll("[data-dello]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa lệnh nấu này (cả các lệnh nhỏ bên trong)? Không thể hoàn tác.")) return;
      await DELETE(`/brewing/brew-master-orders/${b.dataset.dello}`);
      toast("Đã xóa lệnh nấu"); render("orders");
    }));
  }

  if (sec === "lenhloc") {
    let editingMasterId = null;
    function setLfFormMode(editing) {
      $("lf_add").textContent = editing ? "Lưu chỉnh sửa lệnh lọc" : "Tạo lệnh lọc";
      $("lf_cancel_wrap").innerHTML = editing ? `<button class="btn sm sec" id="lf_canceledit" style="align-self:flex-end">Hủy sửa</button>` : "";
      if (editing) $("lf_canceledit").onclick = () => render("orders");
    }
    const newLfChild = () => ({ blendMode: "khong_phoi", tanks: [{ tankType: "cct", fermentId: "", sourceBbtCode: "", reason: "", vol: "" }], materialLines: [], tolerance: 0, kcsLotNo: "", beerTypeId: "", finishedProductId: "" });
    let lfChildren = [newLfChild()];

    // Loại bia của lệnh nhỏ = suy từ Dịch bia của các tank đã chọn (qua approvedTanksLf.beer_type_id/
    // beer_type_name cho tank_type="cct", hoặc availableBbtTanksLf.beer_type_id/beer_type cho
    // tank_type="bbt" — xem GET /brewing/ferments, GET /brewing/bbt-tanks) — 1 Loại bia -> tự gán;
    // nhiều Loại bia khác nhau -> bắt buộc người lập tự chọn (xem services/filter_order.py::_validate_tanks
    // phía server).
    const lfChildBeerTypeCandidates = (ci) => {
      const byId = new Map();
      let missing = false;
      for (const t of lfChildren[ci].tanks) {
        if (t.tankType === "bbt") {
          if (!t.sourceBbtCode) continue;
          const bt = availableBbtTanksLf.find(x => x.to_bbt === t.sourceBbtCode);
          if (bt && bt.beer_type_id) byId.set(bt.beer_type_id, bt.beer_type || bt.beer_type_id);
          else missing = true;
        } else {
          if (!t.fermentId) continue;
          const f = approvedTanksLf.find(x => x.ferment_id === t.fermentId);
          if (f && f.beer_type_id) byId.set(f.beer_type_id, f.beer_type_name || f.beer_type_id);
          else missing = true;
        }
      }
      return { list: [...byId.entries()].map(([beer_type_id, name]) => ({ beer_type_id, name })), missing };
    };

    // Lượng CCT đã bị các lệnh nhỏ PHÍA TRÊN (ci' < ci) đặt trước cho cùng 1 tank — để lệnh
    // nhỏ phía dưới thấy đúng phần còn lại thật sự có thể lấy, không bị trùng lắp.
    const reservedByEarlierLf = (ci, fermentId) => {
      if (!fermentId) return 0;
      let sum = 0;
      for (let k = 0; k < ci; k++) {
        for (const t of lfChildren[k].tanks) {
          if (t.fermentId === fermentId) sum += parseFloat(t.vol) || 0;
        }
      }
      return sum;
    };
    const lfChildTotalVol = (ci) => lfChildren[ci].tanks.reduce((s, t) => s + (parseFloat(t.vol) || 0), 0);

    const tankOptsLf = (ci, selected) => `<option value="">(chọn tank)</option>` + approvedTanksLf.map(f => {
      const remaining = f.on_hand_cct - reservedByEarlierLf(ci, f.ferment_id);
      return `<option value="${esc(f.ferment_id)}" ${f.ferment_id === selected ? "selected" : ""}>${esc(f.tank_lm)} — lô LM ${esc(f.lm_code)} (${esc(f.product_code || "")}) — còn ${remaining.toLocaleString("vi-VN")} hl</option>`;
    }).join("");

    // Lượng khả dụng của tank BBT (thành phẩm) đã bị các lệnh nhỏ PHÍA TRÊN (ci' < ci) đặt
    // trước làm nguồn lọc lại — mirror reservedByEarlierLf nhưng theo mã tank BBT.
    const reservedByEarlierLfBbt = (ci, code) => {
      if (!code) return 0;
      let sum = 0;
      for (let k = 0; k < ci; k++) {
        for (const t of lfChildren[k].tanks) {
          if (t.tankType === "bbt" && t.sourceBbtCode === code) sum += parseFloat(t.vol) || 0;
        }
      }
      return sum;
    };
    const bbtOptsLf = (ci, selected) => `<option value="">(chọn tank BBT)</option>` + availableBbtTanksLf.map(t => {
      const remaining = t.remaining_hl - reservedByEarlierLfBbt(ci, t.to_bbt);
      return `<option value="${esc(t.to_bbt)}" ${t.to_bbt === selected ? "selected" : ""}>${esc(t.to_bbt)} (${esc(t.beer_type || "")}) — còn ${remaining.toLocaleString("vi-VN")} hl</option>`;
    }).join("");
    const bbtInfoLf = (ci, code) => {
      const t = availableBbtTanksLf.find(x => x.to_bbt === code);
      if (!t) return "";
      const reserved = reservedByEarlierLfBbt(ci, code);
      const remaining = t.remaining_hl - reserved;
      if (reserved > 0) {
        return `Còn khả dụng để lọc lại: <b>${t.remaining_hl.toLocaleString("vi-VN")} hl</b> — lệnh nhỏ phía trên đã đặt: <b>${reserved.toLocaleString("vi-VN")} hl</b> — còn lại: <b>${remaining.toLocaleString("vi-VN")} hl</b>`;
      }
      return `Còn khả dụng để lọc lại: <b>${t.remaining_hl.toLocaleString("vi-VN")} hl</b>`;
    };
    const materialOptsLf = (selected) => `<option value="">(chọn vật tư)</option>` + (CACHE.materialsLf || []).map(m =>
      `<option value="${esc(m.material_id)}" ${m.material_id === selected ? "selected" : ""}>${esc(m.code)} — ${esc(m.name)}</option>`).join("");
    // Nhắc lại rõ tồn CCT còn lại của tank vừa chọn (sau khi trừ phần các lệnh nhỏ phía trên
    // đã đặt) — để người dùng nhập đúng thể tích dịch lọc kế hoạch, không vượt quá số thật sự
    // còn lại của tank.
    const tankCctInfo = (ci, fermentId) => {
      const f = approvedTanksLf.find(x => x.ferment_id === fermentId);
      if (!f) return "";
      const reserved = reservedByEarlierLf(ci, fermentId);
      const remaining = f.on_hand_cct - reserved;
      if (reserved > 0) {
        return `Đang tồn CCT: <b>${f.on_hand_cct.toLocaleString("vi-VN")} hl</b> — lệnh nhỏ phía trên đã đặt: <b>${reserved.toLocaleString("vi-VN")} hl</b> — còn lại: <b>${remaining.toLocaleString("vi-VN")} hl</b>`;
      }
      return `Đang tồn CCT: <b>${f.on_hand_cct.toLocaleString("vi-VN")} hl</b>`;
    };

    function renderLfChildTanks(ci) {
      const c = lfChildren[ci];
      const box = document.querySelector(`.lfc_tanks[data-ci="${ci}"]`);
      if (!box) return;
      const mode = c.blendMode;
      box.innerHTML = `<h4 style="font-size:13px;margin:8px 0 4px">${mode === "phoi" ? "Chọn các tank nguồn (2+)" : "Chọn tank nguồn"}</h4>
        <div class="row" style="flex-wrap:wrap">${c.tanks.map((t, ti) => `
          <div class="field"><label>Tank ${ti + 1} — nguồn</label><select class="lfc_tanktype" data-ci="${ci}" data-ti="${ti}">
            <option value="cct" ${t.tankType !== "bbt" ? "selected" : ""}>Tank lên men</option>
            <option value="bbt" ${t.tankType === "bbt" ? "selected" : ""}>Tank thành phẩm (BBT) — lọc lại</option></select></div>
          ${t.tankType === "bbt" ? `
            <div class="field"><label>Tank BBT</label><select class="lfc_bbtsel" data-ci="${ci}" data-ti="${ti}">${bbtOptsLf(ci, t.sourceBbtCode)}</select>
              <div class="muted lfc_tankcct" data-ci="${ci}" data-ti="${ti}" style="font-size:12px;margin-top:2px">${bbtInfoLf(ci, t.sourceBbtCode)}</div></div>
            <div class="field" style="flex:1;min-width:220px"><label>Lý do lọc lại</label><input class="lfc_reason" data-ci="${ci}" data-ti="${ti}" value="${esc(t.reason || "")}" placeholder="Bắt buộc — VD: chưa đạt độ đục"/></div>
          ` : `
            <div class="field"><label>Tank lên men</label><select class="lfc_tanksel" data-ci="${ci}" data-ti="${ti}">${tankOptsLf(ci, t.fermentId)}</select>
              <div class="muted lfc_tankcct" data-ci="${ci}" data-ti="${ti}" style="font-size:12px;margin-top:2px">${tankCctInfo(ci, t.fermentId)}</div></div>
          `}
          <div class="field"><label>Thể tích dịch lọc KH (hl)</label><input class="lfc_tankvol" data-ci="${ci}" data-ti="${ti}" type="number" value="${t.vol}" style="width:110px"/></div>
          ${mode === "phoi" && c.tanks.length > 2 ? `<button class="btn sm sec" data-lfc-tankrm data-ci="${ci}" data-ti="${ti}" style="align-self:flex-end">Xóa dòng</button>` : ""}
        `).join("")}
        ${mode === "phoi" ? `<button class="btn sec" data-lfc-tankadd data-ci="${ci}" style="align-self:flex-end">+ Thêm tank</button>` : ""}</div>
        <div class="muted" style="margin-top:4px">Tổng thể tích dịch lọc kế hoạch của lệnh nhỏ này: <b>${lfChildTotalVol(ci).toLocaleString("vi-VN")} hl</b></div>
        <div class="lfc_beertype" data-ci="${ci}" style="margin-top:6px"></div>`;
      box.querySelectorAll(".lfc_tanktype").forEach(sel => sel.onchange = () => {
        const ti = parseInt(sel.dataset.ti, 10);
        const t = lfChildren[ci].tanks[ti];
        t.tankType = sel.value; t.fermentId = ""; t.sourceBbtCode = ""; t.reason = ""; t.vol = "";
        renderLfChildTanks(ci);
        renderLaterLfChildTanks(ci);
      });
      box.querySelectorAll(".lfc_tanksel").forEach(sel => sel.onchange = () => {
        const ti = parseInt(sel.dataset.ti, 10);
        lfChildren[ci].tanks[ti].fermentId = sel.value;
        renderLfChildTanks(ci);
        renderLaterLfChildTanks(ci);
      });
      box.querySelectorAll(".lfc_bbtsel").forEach(sel => sel.onchange = () => {
        const ti = parseInt(sel.dataset.ti, 10);
        const t = lfChildren[ci].tanks[ti];
        t.sourceBbtCode = sel.value;
        if (!t.vol) {
          // Tự tính thể tích lọc lại = phần còn khả dụng của tank BBT đó — vẫn cho sửa tay
          // sau khi điền (chỉ auto-fill khi ô đang trống).
          const bt = availableBbtTanksLf.find(x => x.to_bbt === sel.value);
          if (bt) t.vol = Math.max(0, bt.remaining_hl - reservedByEarlierLfBbt(ci, sel.value));
        }
        renderLfChildTanks(ci);
        renderLaterLfChildTanks(ci);
      });
      box.querySelectorAll(".lfc_reason").forEach(inp => inp.onchange = () => {
        const ti = parseInt(inp.dataset.ti, 10);
        lfChildren[ci].tanks[ti].reason = inp.value;
      });
      box.querySelectorAll(".lfc_tankvol").forEach(inp => inp.onchange = () => {
        const ti = parseInt(inp.dataset.ti, 10);
        lfChildren[ci].tanks[ti].vol = inp.value;
        renderLfChildTanks(ci);
        renderLaterLfChildTanks(ci);
      });
      const addBtn = box.querySelector("[data-lfc-tankadd]");
      if (addBtn) addBtn.onclick = () => { lfChildren[ci].tanks.push({ tankType: "cct", fermentId: "", sourceBbtCode: "", reason: "", vol: "" }); renderLfChildTanks(ci); };
      box.querySelectorAll("[data-lfc-tankrm]").forEach(b => b.onclick = () => {
        lfChildren[ci].tanks.splice(parseInt(b.dataset.ti, 10), 1); renderLfChildTanks(ci); renderLaterLfChildTanks(ci);
      });
      renderLfChildBeerType(ci);
    }

    function renderLfChildBeerType(ci) {
      const box = document.querySelector(`.lfc_beertype[data-ci="${ci}"]`);
      if (!box) return;
      const { list, missing } = lfChildBeerTypeCandidates(ci);
      if (missing) {
        lfChildren[ci].beerTypeId = "";
        box.innerHTML = `<div class="muted" style="color:var(--red)">⚠ Có tank chưa được gán Loại bia — vào Danh mục Dịch bia để gán trước khi tạo lệnh.</div>`;
      } else if (list.length === 1) {
        lfChildren[ci].beerTypeId = list[0].beer_type_id;
        box.innerHTML = `<span class="muted">Loại bia: <b>${esc(list[0].name)}</b></span>`;
      } else if (list.length > 1) {
        if (!list.some(x => x.beer_type_id === lfChildren[ci].beerTypeId)) lfChildren[ci].beerTypeId = "";
        box.innerHTML = `<div class="field"><label>Các tank thuộc nhiều Loại bia khác nhau — chọn 1 Loại bia cho lệnh nhỏ này</label>
          <select class="lfc_beertypesel" data-ci="${ci}"><option value="">(chọn Loại bia)</option>${list.map(x =>
            `<option value="${x.beer_type_id}" ${x.beer_type_id === lfChildren[ci].beerTypeId ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></div>`;
        box.querySelector(".lfc_beertypesel").onchange = (e) => { lfChildren[ci].beerTypeId = e.target.value; };
      } else {
        lfChildren[ci].beerTypeId = "";
        box.innerHTML = "";
      }
    }
    function renderLaterLfChildTanks(fromCi) {
      for (let k = fromCi + 1; k < lfChildren.length; k++) renderLfChildTanks(k);
    }

    function renderLfChildMaterials(ci) {
      const c = lfChildren[ci];
      const box = document.querySelector(`.lfc_materials[data-ci="${ci}"]`);
      if (!box) return;
      box.innerHTML = `<div class="panel" style="margin-top:6px"><h4 style="font-size:13px">Vật tư sử dụng (tuỳ chọn)</h4>
        ${c.materialLines.map((l, li) => {
          const fifo = l.fifo;
          const showFifo = fifo && l.quantity;
          const short = showFifo && fifo.stock_total < parseFloat(l.quantity);
          return `<div class="row" style="align-items:flex-end;flex-wrap:wrap;border-bottom:1px solid var(--border);padding-bottom:8px;margin-bottom:8px">
            <div class="field"><label>Vật tư</label><select class="lfc_mat" data-ci="${ci}" data-li="${li}">${materialOptsLf(l.material_id)}</select></div>
            <div class="field"><label>Số lượng cần</label><input class="lfc_matqty" data-ci="${ci}" data-li="${li}" type="number" value="${l.quantity ?? ""}" style="width:110px"/></div>
            <button class="btn sm sec" data-lfc-matrm data-ci="${ci}" data-li="${li}">Xóa dòng</button>
            ${!showFifo && l.material_id ? `<div class="muted" style="flex-basis:100%;font-size:13px;margin-top:4px">Nhập số lượng cần để xem tồn kho + lô FIFO.</div>` : ""}
            ${showFifo ? `<div style="flex-basis:100%;font-size:13px;margin-top:4px">
              Kho công ty: <b>${fifo.stock_company}</b> · Kho phân xưởng: <b>${fifo.stock_workshop}</b> ·
              Tổng: <b>${fifo.stock_total}</b>
              ${short ? `<span style="color:var(--red)"> — ⚠ Thiếu (cần ${l.quantity})</span>` : `<span style="color:var(--green)"> — Đủ</span>`}
              ${fifo.lots.length ? `<div class="tablewrap" style="margin-top:4px"><table><thead><tr><th>Lô (FIFO)</th><th>Kho</th><th>SL</th><th>Ngày nhập</th></tr></thead>
                <tbody>${fifo.lots.map(lo => `<tr><td class="code">${esc(lo.lot_code)}</td><td class="muted">${esc(lo.location || "—")}</td>
                  <td>${lo.quantity}</td><td class="muted">${fmt(lo.received_at)}</td></tr>`).join("")}</tbody></table></div>`
                : `<div class="muted">Không còn lô nào.</div>`}
            </div>` : ""}
          </div>`;
        }).join("") || `<div class="muted">Chưa có dòng vật tư nào.</div>`}
        <button class="btn sec" data-lfc-mataddrow data-ci="${ci}">+ Thêm vật tư</button></div>`;
      box.querySelector("[data-lfc-mataddrow]").onclick = () => {
        lfChildren[ci].materialLines.push({ material_id: "", quantity: "", fifo: null }); renderLfChildMaterials(ci);
      };
      box.querySelectorAll("[data-lfc-matrm]").forEach(b => b.onclick = () => {
        lfChildren[ci].materialLines.splice(parseInt(b.dataset.li, 10), 1); renderLfChildMaterials(ci);
      });
      const refreshFifo = async (li) => {
        const l = lfChildren[ci].materialLines[li];
        if (!l.material_id) { l.fifo = null; renderLfChildMaterials(ci); return; }
        l.fifo = await GET(`/warehouse/materials/${l.material_id}/fifo`);
        renderLfChildMaterials(ci);
      };
      box.querySelectorAll(".lfc_mat").forEach(sel => sel.onchange = () => {
        const li = parseInt(sel.dataset.li, 10);
        lfChildren[ci].materialLines[li].material_id = sel.value;
        refreshFifo(li);
      });
      box.querySelectorAll(".lfc_matqty").forEach(inp => inp.onchange = () => {
        const li = parseInt(inp.dataset.li, 10);
        lfChildren[ci].materialLines[li].quantity = inp.value === "" ? "" : parseFloat(inp.value);
        renderLfChildMaterials(ci);
      });
    }

    function renderLfChildren() {
      $("lf_children").innerHTML = lfChildren.map((c, ci) => `
        <div class="panel" style="margin-top:8px;border:1px solid var(--border)">
          <div class="row" style="align-items:center">
            <h3 style="font-size:14px;margin:0;flex:1">Lệnh lọc nhỏ #${ci + 1}</h3>
            ${lfChildren.length > 1 ? `<button class="btn sm sec" data-lfchildrm="${ci}">Xóa lệnh nhỏ</button>` : ""}
          </div>
          <div class="row">
            <div class="field"><label>Loại lọc</label><select class="lfc_mode" data-ci="${ci}">
              <option value="khong_phoi" ${c.blendMode === "khong_phoi" ? "selected" : ""}>Không phối</option>
              <option value="phoi" ${c.blendMode === "phoi" ? "selected" : ""}>Phối</option></select></div>
          </div>
          <div class="lfc_tanks" data-ci="${ci}"></div>
          <div class="lfc_materials" data-ci="${ci}"></div>
          <div class="row">
            <div class="field"><label>Sai số cho phép (±hl)</label><input class="lfc_voltol" data-ci="${ci}" type="number" value="${c.tolerance}"/></div>
            <div class="field"><label>Số lô KCS</label><input class="lfc_kcslot" data-ci="${ci}" value="${esc(c.kcsLotNo || "")}" placeholder="Người lập tự đánh số"/></div>
            <div class="field"><label>Sản phẩm (tuỳ chọn)</label><select class="lfc_fproduct" data-ci="${ci}">
              <option value="">(Mọi sản phẩm)</option>${(CACHE.finishedProductsLf || []).map(fp =>
                `<option value="${fp.finished_product_id}" ${fp.finished_product_id === c.finishedProductId ? "selected" : ""}>${esc(fp.code)} — ${esc(fp.name)}</option>`).join("")}</select>
              <div class="muted" style="font-size:12px">Chỉ cần chọn nếu Lọc cần chỉ tiêu khác nhau theo hình thức đóng gói (VD chai/tươi).</div></div>
          </div>
        </div>`).join("");

      lfChildren.forEach((c, ci) => { renderLfChildTanks(ci); renderLfChildMaterials(ci); });

      document.querySelectorAll(".lfc_mode").forEach(sel => sel.onchange = () => {
        const ci = parseInt(sel.dataset.ci, 10);
        lfChildren[ci].blendMode = sel.value;
        const tanks = lfChildren[ci].tanks;
        const blankTank = () => ({ tankType: "cct", fermentId: "", sourceBbtCode: "", reason: "", vol: "" });
        if (sel.value === "khong_phoi" && tanks.length > 1) lfChildren[ci].tanks = [tanks[0] || blankTank()];
        if (sel.value === "phoi" && tanks.length < 2) lfChildren[ci].tanks = [tanks[0] || blankTank(), blankTank()];
        renderLfChildTanks(ci);
        renderLaterLfChildTanks(ci);
      });
      document.querySelectorAll(".lfc_voltol").forEach(inp => inp.onchange = () => { lfChildren[parseInt(inp.dataset.ci, 10)].tolerance = inp.value; });
      document.querySelectorAll(".lfc_kcslot").forEach(inp => inp.onchange = () => { lfChildren[parseInt(inp.dataset.ci, 10)].kcsLotNo = inp.value; });
      document.querySelectorAll(".lfc_fproduct").forEach(sel => sel.onchange = () => { lfChildren[parseInt(sel.dataset.ci, 10)].finishedProductId = sel.value; });
      document.querySelectorAll("[data-lfchildrm]").forEach(b => b.onclick = () => {
        lfChildren.splice(parseInt(b.dataset.lfchildrm, 10), 1); renderLfChildren();
      });
    }
    renderLfChildren();
    $("lf_addchild").onclick = () => { lfChildren.push(newLfChild()); renderLfChildren(); };

    $("lf_add").onclick = () => guard(async () => {
      const code = $("lf_code").value.trim();
      if (!code) throw new Error("Nhập Số lệnh.");
      const children = lfChildren.map((c, ci) => {
        const tanks = c.tanks.filter(t => t.tankType === "bbt" ? t.sourceBbtCode : t.fermentId);
        if (c.blendMode === "khong_phoi" && tanks.length !== 1) throw new Error(`Lệnh lọc nhỏ #${ci + 1}: Không phối phải chọn đúng 1 tank nguồn.`);
        if (c.blendMode === "phoi" && tanks.length < 2) throw new Error(`Lệnh lọc nhỏ #${ci + 1}: Phối phải chọn từ 2 tank nguồn trở lên.`);
        for (const t of tanks) {
          if (!(parseFloat(t.vol) > 0)) throw new Error(`Lệnh lọc nhỏ #${ci + 1}: Nhập thể tích dịch lọc kế hoạch cho từng tank.`);
          if (t.tankType === "bbt" && !(t.reason || "").trim()) throw new Error(`Lệnh lọc nhỏ #${ci + 1}: Tank BBT ${t.sourceBbtCode} phải nhập lý do lọc lại.`);
        }
        const { list: btCandidates, missing: btMissing } = lfChildBeerTypeCandidates(ci);
        if (btMissing) throw new Error(`Lệnh lọc nhỏ #${ci + 1}: có tank chưa được gán Loại bia — vào Danh mục Dịch bia để gán trước.`);
        if (btCandidates.length > 1 && !c.beerTypeId) throw new Error(`Lệnh lọc nhỏ #${ci + 1}: các tank thuộc nhiều Loại bia khác nhau — chọn 1 Loại bia.`);
        const lines = c.materialLines.filter(l => l.material_id && l.quantity)
          .map(l => ({ material_id: l.material_id, quantity: l.quantity }));
        return {
          blend_mode: c.blendMode,
          tanks: tanks.map(t => t.tankType === "bbt"
            ? { tank_type: "bbt", source_bbt_code: t.sourceBbtCode, reason: (t.reason || "").trim(), planned_v_dich_hl: parseFloat(t.vol) || 0 }
            : { tank_type: "cct", ferment_id: t.fermentId, planned_v_dich_hl: parseFloat(t.vol) || 0 }),
          lines,
          kcs_lot_no: (c.kcsLotNo || "").trim() || null,
          volume_tolerance_hl: parseFloat(c.tolerance) || 0,
          beer_type_id: c.beerTypeId || null,
          finished_product_id: c.finishedProductId || null,
        };
      });
      const payload = { order_code: code, note: $("lf_note").value.trim() || null, children };
      if (editingMasterId) {
        await PUT(`/brewing/filter-master-orders/${editingMasterId}`, payload);
        toast("Đã lưu chỉnh sửa lệnh lọc");
      } else {
        await POST("/brewing/filter-master-orders", payload);
        toast("Đã tạo lệnh lọc");
      }
      render("orders");
    });

    document.querySelectorAll("[data-viewlf]").forEach(b => b.onclick = () => openFilterMasterOrderModal(b.dataset.viewlf));
    document.querySelectorAll("[data-printlf]").forEach(b => b.onclick = () => guard(async () => {
      printFilterMasterOrder(await GET(`/brewing/filter-master-orders/${b.dataset.printlf}`));
    }));
    document.querySelectorAll("[data-editlf]").forEach(b => b.onclick = () => guard(async () => {
      const m = await GET(`/brewing/filter-master-orders/${b.dataset.editlf}`);
      editingMasterId = m.filter_master_order_id;
      $("lf_code").value = m.order_code;
      $("lf_note").value = m.note || "";
      lfChildren = m.children.map(c => ({
        blendMode: c.blend_mode,
        tanks: c.tanks.map(t => ({
          tankType: t.tank_type || "cct", fermentId: t.ferment_id || "",
          sourceBbtCode: t.source_bbt_code || "", reason: t.reason || "",
          vol: t.planned_v_dich_hl || "",
        })),
        materialLines: c.lines.map(l => ({ material_id: l.material_id, quantity: l.quantity, fifo: null })),
        tolerance: c.volume_tolerance_hl || 0, kcsLotNo: c.kcs_lot_no || "",
        beerTypeId: c.beer_type_id || "", finishedProductId: c.finished_product_id || "",
      }));
      renderLfChildren();
      setLfFormMode(true);
      $("lf_code").scrollIntoView({ behavior: "smooth", block: "center" });
      toast(`Đang sửa lệnh ${m.order_code} — thay đổi rồi bấm "Lưu chỉnh sửa lệnh lọc"`);
    }));
    document.querySelectorAll("[data-dellf]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa lệnh lọc này (cả các lệnh nhỏ bên trong)? Không thể hoàn tác.")) return;
      await DELETE(`/brewing/filter-master-orders/${b.dataset.dellf}`);
      toast("Đã xóa lệnh lọc"); render("orders");
    }));
  }
};
const prodName = (id) => { const p = CACHE.products.find(x => x.product_id === id); return p ? p.code : id; };

// ================= ĐIỀU ĐỘ (Work Orders) =================
const WO_STATUS = { planned: ["planned", "Lập KH"], released: ["ready", "Đã phát hành"],
  in_progress: ["running", "Đang chạy"], completed: ["completed", "Hoàn thành"],
  closed: ["closed", "Đã chốt"], cancelled: ["cancelled", "Đã hủy"] };
const WO_NEXT = { planned: ["released", "cancelled"], released: ["cancelled"],
  in_progress: ["completed", "cancelled"], completed: ["closed"], closed: [], cancelled: [] };
const WO_LABEL = { released: "Phát hành", completed: "Hoàn thành", closed: "Chốt", cancelled: "Hủy" };
VIEWS.dispatch = async function () {
  const [board, orders, products, recipes] = await Promise.all([
    GET("/workorders"), GET("/orders"), GET("/products"), GET("/recipes")]);
  CACHE.products = products;
  // recipe versions effective theo product
  const verByProduct = {};
  for (const r of recipes) {
    const vs = await GET(`/recipes/${r.recipe_id}/versions`);
    vs.filter(v => v.state === "effective").forEach(v =>
      (verByProduct[r.product_id] = verByProduct[r.product_id] || []).push({ id: v.version_id, label: `${r.code} v${v.version_no}` }));
  }
  const oOpts = orders.map(o => `<option value="${o.order_id}" data-prod="${o.product_id}">${esc(o.order_code)} (${esc(prodName(o.product_id))})</option>`).join("");
  const today = toISODateLocal(new Date());
  $("view-dispatch").innerHTML = `
    <div class="panel"><h2>Lập lệnh sản xuất (điều độ)</h2>
      <div class="row">
        <div class="field"><label>Lệnh ERP (PO)</label><select id="wo_po">${oOpts}</select></div>
        <div class="field"><label>Recipe version</label><select id="wo_rv"></select></div>
        <div class="field"><label>SL kế hoạch</label><input id="wo_qty" type="number" placeholder="theo PO"/></div>
        <div class="field"><label>Dây chuyền</label><input id="wo_line" value="Nấu A" size="8"/></div>
        <div class="field"><label>Ca</label><select id="wo_shift"><option>A</option><option>B</option><option>C</option></select></div>
        <div class="field"><label>Ngày</label><input id="wo_date" type="date" value="${today}"/></div>
        <div class="field"><label>Ưu tiên</label><input id="wo_pri" type="number" value="5" size="3"/></div>
        <button class="btn" id="wo_add">Tạo lệnh (wo.manage)</button>
      </div>
      <div class="muted">PO (từ ERP) → Work Order (điều độ theo ngày/ca/line) → dispatch phát mẻ. Quyền: <code class="k">wo.manage</code> lập, <code class="k">wo.dispatch</code> phát mẻ.</div>
    </div>
    <div class="panel"><h2>Bảng điều độ <span class="muted">(${board.length} lệnh)</span></h2>
      <input class="searchbox" data-tbl="t_workorders" placeholder="Tìm theo mã WO, line, sản phẩm, trạng thái..."/>
      <div class="tablewrap"><table id="t_workorders"><thead><tr><th>Mã WO</th><th>Ngày</th><th>Ca</th><th>Line</th><th>Sản phẩm</th><th>KH</th><th>Thực tế</th><th>% HT</th><th>Mẻ</th><th>Ưu tiên</th><th>Trạng thái</th><th>Hành động</th></tr></thead>
      <tbody>${board.map(woRow).join("") || '<tr><td colspan=12 class="muted">Chưa có lệnh.</td></tr>'}</tbody></table></div>
      <div class="legend">% hoàn thành = tổng SL thực tế các mẻ thuộc lệnh / SL kế hoạch (planned vs actual).</div>
    </div>`;
  const loadRv = () => {
    const opt = $("wo_po").options[$("wo_po").selectedIndex];
    const prod = opt ? opt.dataset.prod : null;
    const vers = verByProduct[prod] || [];
    $("wo_rv").innerHTML = vers.map(v => `<option value="${v.id}">${esc(v.label)}</option>`).join("") || "<option value=''>(chưa có version effective)</option>";
  };
  if ($("wo_po")) { $("wo_po").onchange = loadRv; loadRv(); }
  wirePaginate("t_workorders", 10);
  $("wo_add").onclick = () => guard(async () => {
    await POST("/workorders", { production_order_id: $("wo_po").value, recipe_version_id: $("wo_rv").value || null,
      planned_qty: $("wo_qty").value ? parseFloat($("wo_qty").value) : null, line: $("wo_line").value,
      shift: $("wo_shift").value, scheduled_date: $("wo_date").value, priority: parseInt($("wo_pri").value) });
    toast("Đã tạo lệnh sản xuất"); render("dispatch");
  });
  document.querySelectorAll("[data-wotrans]").forEach(b => b.onclick = () => guard(async () => {
    await POST(`/workorders/${b.dataset.wo}/transition`, { target: b.dataset.wotrans });
    toast("Lệnh → " + (WO_LABEL[b.dataset.wotrans] || b.dataset.wotrans)); render("dispatch");
  }));
  document.querySelectorAll("[data-wodispatch]").forEach(b => b.onclick = () => guard(async () => {
    try {
      const r = await POST(`/workorders/${b.dataset.wodispatch}/dispatch`, {});
      toast("Đã phát mẻ " + r.batch_code);
    } catch (e) {
      if (/Không đủ tồn kho/.test(e.message)) {
        if (!confirm(e.message + "\n\nVẫn phát mẻ (ghi nhận thiếu)?")) return;
        const r = await POST(`/workorders/${b.dataset.wodispatch}/dispatch`, { allow_shortage: true });
        toast("Đã phát mẻ " + r.batch_code);
      } else { throw e; }
    }
    render("dispatch");
  }));
};
function woRow(w) {
  const st = WO_STATUS[w.status] || ["planned", w.status];
  const trans = (WO_NEXT[w.status] || []).map(t => `<button class="btn sm sec" data-wotrans="${t}" data-wo="${w.wo_id}">${WO_LABEL[t] || t}</button>`).join(" ");
  const disp = (w.status === "released" || w.status === "in_progress")
    ? `<button class="btn sm" data-wodispatch="${w.wo_id}">⮞ Phát mẻ</button>` : "";
  const pct = w.completion_pct || 0;
  const pctColor = pct >= 100 ? "var(--green)" : pct > 0 ? "var(--accent)" : "var(--muted)";
  return `<tr><td><code class="k">${esc(w.wo_code)}</code></td><td>${fmt(w.scheduled_date)}</td><td>${esc(w.shift || "")}</td>
    <td>${esc(w.line || "")}</td><td>${esc(prodName(w.product_id))}</td><td>${w.planned_qty.toLocaleString("vi-VN")} ${esc(w.uom)}</td>
    <td>${(w.actual_qty || 0).toLocaleString("vi-VN")}</td><td style="color:${pctColor};font-weight:600">${pct}%</td>
    <td>${w.batches}</td><td>${w.priority}</td><td>${badge(st[0])}${st[1]}</td><td>${disp} ${trans}</td></tr>`;
}

// ================= RECIPES + BOM =================
VIEWS.recipes = async function () {
  const [recipes, products, materials] = await Promise.all([GET("/recipes"), GET("/products"), GET("/materials")]);
  CACHE.products = products; CACHE.recipes = recipes; CACHE.materials = materials;
  const popts = products.map(p => `<option value="${p.product_id}">${esc(p.code)}</option>`).join("");
  let versionsHtml = "";
  for (const r of recipes) {
    const vs = await GET(`/recipes/${r.recipe_id}/versions`);
    versionsHtml += `<div class="panel"><h2>${esc(r.code)} — ${esc(r.name)} ${badge(prodName(r.product_id))}</h2>
      <button class="btn sm" data-newver="${r.recipe_id}">+ Tạo version (BOM)</button>
      <div class="tablewrap"><table><thead><tr><th>Ver</th><th>Trạng thái</th><th>Quy mô chuẩn</th><th>Dòng BOM</th><th>Tham số</th><th>QC</th><th>Soạn</th><th>Duyệt</th><th>Hành động</th></tr></thead>
      <tbody>${vs.map(v => recipeVerRow(r, v)).join("")}</tbody></table></div></div>`;
  }
  $("view-recipes").innerHTML = `
    <div class="panel"><h2>Tạo công thức</h2>
      <div class="row">
        <div class="field"><label>Mã</label><input id="r_code" placeholder="REC-..." /></div>
        <div class="field"><label>Tên</label><input id="r_name" /></div>
        <div class="field"><label>Sản phẩm</label><select id="r_prod">${popts}</select></div>
        <button class="btn" id="r_save">Tạo</button>
      </div></div>
    <div id="rv_detail"></div>
    ${versionsHtml || '<div class="panel muted">Chưa có công thức.</div>'}`;
  $("r_save").onclick = () => guard(async () => {
    await POST("/recipes", { code: $("r_code").value, name: $("r_name").value, product_id: $("r_prod").value });
    toast("Đã tạo công thức"); render("recipes");
  });
  document.querySelectorAll("[data-newver]").forEach(b => b.onclick = () => newVersionForm(b.dataset.newver));
  document.querySelectorAll("[data-vdetail]").forEach(b => b.onclick = () => showVersion(b.dataset.vdetail));
  document.querySelectorAll("[data-vtrans]").forEach(b => b.onclick = () => {
    const t = b.dataset.vtrans, vid = b.dataset.vid;
    const doIt = (reason) => guard(async () => {
      await POST(`/recipes/versions/${vid}/transition`, { target: t, reason: reason || null });
      toast(`Chuyển version → ${t}`); render("recipes");
    });
    if (t === "suspended" || t === "obsolete") {     // bắt buộc lý do
      modal(`<h3>${t === "suspended" ? "Tạm ngưng" : "Ngừng dùng"} công thức</h3>
        <div class="field"><label>Lý do (bắt buộc)</label><input id="rs_reason" style="width:100%" placeholder="vd: phát hiện lệch chỉ tiêu / đổi nhà cung cấp NVL"/></div>
        <button class="btn" id="rs_go" style="margin-top:12px">Xác nhận</button>`);
      $("rs_go").onclick = () => { const r = $("rs_reason").value.trim(); if (!r) { toast("Nhập lý do", "err"); return; } closeModal(); doIt(r); };
    } else { doIt(); }
  });
};
function recipeVerRow(r, v) {
  const next = { draft: ["review"], review: ["approved"], approved: ["effective"],
    effective: ["suspended", "obsolete"], suspended: ["effective", "obsolete"], obsolete: [] }[v.state] || [];
  const btns = next.map(n => {
    const lab = { review: "→ review", approved: "→ duyệt",
      effective: v.state === "suspended" ? "▶ Kích hoạt lại" : "→ hiệu lực",
      suspended: "⏸ Tạm ngưng", obsolete: "⏹ Ngừng dùng" }[n] || ("→ " + n);
    return `<button class="btn sm sec" data-vtrans="${n}" data-vid="${v.version_id}">${lab}</button>`;
  }).join(" ");
  return `<tr><td>v${v.version_no}</td><td>${badge(v.state)}</td>
    <td>${v.base_qty ? v.base_qty.toLocaleString("vi-VN") + " " + esc(v.base_uom) : "—"}</td>
    <td><b>${(v.materials || []).length}</b></td><td>${v.parameters.length}</td>
    <td>${v.quality_checks.length}</td><td class="muted">${esc(v.created_by || "—")}</td>
    <td class="muted">${esc(v.approved_by || "—")}</td>
    <td><a href="#" data-vdetail="${v.version_id}" style="color:var(--accent2);margin-right:8px">Xem BOM</a>${btns}</td></tr>`;
}

async function showVersion(versionId) {
  const v = await GET("/recipes/versions/" + versionId);
  const bom = (v.materials || []).map(m => `<tr><td><code class="k">${esc(m.material_code)}</code></td>
    <td>${m.qty}</td><td>${esc(m.uom || "")}</td><td>±${m.tol_pct || 0}%</td></tr>`).join("");
  const params = (v.parameters || []).map(p => `<tr><td>${esc(p.name)}</td><td>${p.target ?? ""}</td>
    <td class="muted">${p.lower ?? "−∞"} … ${p.upper ?? "+∞"}</td><td>${esc(p.unit || "")}</td></tr>`).join("");
  const qc = (v.quality_checks || []).map(c => `<tr><td>${esc(c.parameter)}</td>
    <td class="muted">${c.lower ?? "−∞"} … ${c.upper ?? "+∞"} ${esc(c.unit || "")}</td>
    <td>${c.mandatory ? badge("critical") + "bắt buộc" : "tùy chọn"}</td></tr>`).join("");
  $("rv_detail").innerHTML = `<div class="panel"><h2>Chi tiết version v${v.version_no} ${badge(v.state)}
      <span class="muted">· quy mô chuẩn ${v.base_qty ? v.base_qty.toLocaleString("vi-VN") + " " + esc(v.base_uom) : "—"}</span></h2>
    <div class="split">
      <div><h3>📋 BOM — Định mức nguyên vật liệu</h3>
        <table><thead><tr><th>Vật tư</th><th>Định mức</th><th>ĐVT</th><th>Dung sai</th></tr></thead>
        <tbody>${bom || '<tr><td colspan=4 class="muted">Chưa khai báo BOM.</td></tr>'}</tbody></table></div>
      <div><h3>Tham số quy trình</h3>
        <table><thead><tr><th>Tham số</th><th>Mục tiêu</th><th>Giới hạn</th><th>ĐVT</th></tr></thead>
        <tbody>${params || '<tr><td colspan=4 class="muted">—</td></tr>'}</tbody></table>
        <h3>Chỉ tiêu QC</h3>
        <table><thead><tr><th>Chỉ tiêu</th><th>Giới hạn</th><th>Loại</th></tr></thead>
        <tbody>${qc || '<tr><td colspan=3 class="muted">—</td></tr>'}</tbody></table></div>
    </div>
    ${v.state === "draft" ? `<button class="btn sm" data-editver="${v.version_id}" style="margin-top:10px">Sửa version (draft)</button>` : ""}
    </div>`;
  document.querySelectorAll("[data-editver]").forEach(b => b.onclick = () => editVersionForm(v));
  $("rv_detail").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---- Form tạo/sửa version với editor BOM ----
function matOptions(sel) {
  const opts = (CACHE.materials || []).map(m =>
    `<option value="${esc(m.code)}" data-uom="${esc(m.uom)}" ${m.code === sel ? "selected" : ""}>${esc(m.code)} — ${esc(m.name)}</option>`).join("");
  return `<option value="" ${sel ? "" : "selected"}>(chọn vật tư)</option>` + opts;
}
function bomRowHTML(line) {
  line = line || {};
  return `<tr class="bomrow">
    <td><select class="bm-mat" style="min-width:200px">${matOptions(line.material_code)}</select></td>
    <td><input class="bm-qty" type="number" step="any" value="${line.qty ?? ""}" style="width:110px"/></td>
    <td><input class="bm-uom" value="${esc(line.uom || "")}" size="5"/></td>
    <td><input class="bm-tol" type="number" value="${line.tol_pct ?? 0}" size="4"/> %</td>
    <td><button class="btn sm sec bm-del" type="button">×</button></td></tr>`;
}
function wireBomEditor() {
  $("bm_add").onclick = () => { $("bm_body").insertAdjacentHTML("beforeend", bomRowHTML()); wireBomRows(); };
  wireBomRows();
}
function wireBomRows() {
  document.querySelectorAll(".bm-del").forEach(b => b.onclick = () => { b.closest("tr").remove(); });
  document.querySelectorAll(".bm-mat").forEach(s => s.onchange = () => {
    const uom = s.options[s.selectedIndex].dataset.uom || "";
    s.closest("tr").querySelector(".bm-uom").value = uom;
  });
}
function collectBom() {
  return [...document.querySelectorAll(".bomrow")].map(tr => ({
    material_code: tr.querySelector(".bm-mat").value,
    qty: parseFloat(tr.querySelector(".bm-qty").value) || 0,
    uom: tr.querySelector(".bm-uom").value,
    tol_pct: parseFloat(tr.querySelector(".bm-tol").value) || 0,
  })).filter(l => l.material_code && l.qty > 0);
}
function versionFormHTML(v) {
  v = v || {};
  const rows = (v.materials && v.materials.length ? v.materials : [{}]).map(bomRowHTML).join("");
  return `<div class="panel"><h2>${v.version_id ? "Sửa" : "Tạo"} version công thức ${v.version_id ? "v" + v.version_no : ""}</h2>
    <div class="row">
      <div class="field"><label>Quy mô mẻ chuẩn</label><input id="vf_base" type="number" value="${v.base_qty || 50000}" style="width:140px"/></div>
      <div class="field"><label>ĐVT</label><input id="vf_baseu" value="${esc(v.base_uom || "L")}" size="5"/></div>
      <span class="muted" style="align-self:center">BOM bên dưới tính cho quy mô này; khi chạy mẻ sẽ tự scale theo SL kế hoạch.</span>
    </div>
    <h3>📋 BOM — Định mức nguyên vật liệu</h3>
    <table><thead><tr><th>Vật tư</th><th>Định mức</th><th>ĐVT</th><th>Dung sai</th><th></th></tr></thead>
      <tbody id="bm_body">${rows}</tbody></table>
    <button class="btn sm sec" id="bm_add" type="button" style="margin-top:6px">+ Thêm dòng BOM</button>
    <div class="split" style="margin-top:14px">
      <div><h3>Tham số quy trình (JSON)</h3>
        <textarea id="vf_params" style="width:100%;height:120px;font-family:monospace">${esc(JSON.stringify(v.parameters || [{name:"Nhiệt độ đường hóa",target:65,lower:63,upper:67,unit:"°C"}], null, 1))}</textarea></div>
      <div><h3>Chỉ tiêu QC (JSON)</h3>
        <textarea id="vf_qc" style="width:100%;height:120px;font-family:monospace">${esc(JSON.stringify(v.quality_checks || [{parameter:"pH",lower:4.2,upper:4.6,unit:"",mandatory:true}], null, 1))}</textarea></div>
    </div>
    <div class="row" style="margin-top:14px;align-items:center">
      <h3 style="margin:0">🏭 Quy trình ISA-88</h3>
      <button class="btn sm sec" id="proc_tpl" type="button">Nạp mẫu quy trình bia</button>
    </div>
    <div class="muted" style="font-size:12px;margin-bottom:6px">Khai báo <b>Công đoạn → Operation → Phase</b> (kèm setpoint, thời lượng). Mẻ tạo từ công thức này sẽ hiện bảng điều khiển nấu/lên men ở tab <b>ISA-88</b>. Để trống nếu chưa dùng.</div>
    <div id="vf_proc"></div>
    <div class="row" style="margin-top:12px">
      <button class="btn" id="vf_save">${v.version_id ? "Lưu version" : "Tạo version (draft)"}</button>
      <button class="btn sec" id="vf_cancel">Hủy</button>
    </div></div>`;
}
function newVersionForm(recipeId) {
  $("rv_detail").innerHTML = versionFormHTML(null);
  wireBomEditor();
  PROC_MODEL = []; _FORM_YIELD = null; procRender();
  $("proc_tpl").onclick = () => { PROC_MODEL = procTemplate(); procRender(); };
  $("vf_cancel").onclick = () => { $("rv_detail").innerHTML = ""; };
  $("vf_save").onclick = () => guard(async () => {
    await POST(`/recipes/${recipeId}/versions`, _versionPayload());
    toast("Đã tạo version + BOM (draft)"); render("recipes");
  });
}
function editVersionForm(v) {
  $("rv_detail").innerHTML = versionFormHTML(v);
  wireBomEditor();
  PROC_MODEL = v.procedure ? JSON.parse(JSON.stringify(v.procedure)) : [];
  _FORM_YIELD = v.yield_steps && v.yield_steps.length ? v.yield_steps : null;  // giữ yield_steps, không ghi đè rỗng
  procRender();
  $("proc_tpl").onclick = () => { PROC_MODEL = procTemplate(); procRender(); };
  $("vf_cancel").onclick = () => showVersion(v.version_id);
  $("vf_save").onclick = () => guard(async () => {
    await PUT(`/recipes/versions/${v.version_id}`, _versionPayload());
    toast("Đã lưu version + BOM"); render("recipes");
  });
}
function _versionPayload() {
  const p = {
    base_qty: parseFloat($("vf_base").value) || 0,
    base_uom: $("vf_baseu").value,
    materials: collectBom(),
    parameters: JSON.parse($("vf_params").value || "[]"),
    quality_checks: JSON.parse($("vf_qc").value || "[]"),
    procedure: procHarvest().filter(up => up.name),   // bỏ công đoạn chưa đặt tên
  };
  if (_FORM_YIELD) p.yield_steps = _FORM_YIELD;        // giữ hiệu suất công đoạn khi sửa
  return p;
}

// ============ Trình soạn quy trình ISA-88 (Unit Procedure → Operation → Phase) ============
const UNIT_CLASSES = [
  { v: "brewhouse", t: "Nhà nấu (brewhouse)" },
  { v: "fv", t: "Lên men (FV)" },
  { v: "filter", t: "Lọc (filter)" },
  { v: "bbt", t: "Tàng trữ (BBT)" },
  { v: "packaging", t: "Đóng gói" },
  { v: "cip", t: "CIP (vệ sinh)" },
];
let PROC_MODEL = [];     // [{name, unit_class, operations:[{name, phases:[{name,duration_min,params:[{name,setpoint,unit}]}]}]}]
let _FORM_YIELD = null;  // giữ yield_steps khi sửa version (tránh ghi đè rỗng)

function procTemplate() {
  return [
    { name: "Nấu", unit_class: "brewhouse", operations: [
      { name: "Đường hóa", phases: [
        { name: "Vào liệu", params: [{ name: "Nhiệt độ", setpoint: 52, unit: "°C" }] },
        { name: "Giữ 65°C", duration_min: 30, params: [{ name: "Nhiệt độ", setpoint: 65, unit: "°C" }] },
        { name: "Nâng 76°C", duration_min: 10, params: [{ name: "Nhiệt độ", setpoint: 76, unit: "°C" }] }] },
      { name: "Lọc bã", phases: [{ name: "Lọc bã", duration_min: 60, params: [] }] },
      { name: "Sôi hoa", phases: [
        { name: "Thêm hoa", params: [{ name: "Hoa", setpoint: 15, unit: "kg" }] },
        { name: "Sôi", duration_min: 60, params: [] }] }] },
    { name: "Lên men", unit_class: "fv", operations: [
      { name: "Cấy men", phases: [{ name: "Bơm men", params: [{ name: "Men", setpoint: 50, unit: "L" }] }] },
      { name: "Lên men chính", phases: [{ name: "Giữ 12°C", duration_min: 10080, params: [{ name: "Nhiệt độ", setpoint: 12, unit: "°C" }] }] },
      { name: "Hạ nhiệt", phases: [{ name: "Hạ 2°C", params: [{ name: "Nhiệt độ", setpoint: 2, unit: "°C" }] }] }] },
    { name: "Lọc", unit_class: "filter", operations: [
      { name: "Lọc nến", phases: [{ name: "Lọc", duration_min: 120, params: [] }] }] },
    { name: "CIP Nồi nấu", unit_class: "cip", operations: [
      { name: "CIP", phases: [
        { name: "Tiền rửa", duration_min: 10, params: [] },
        { name: "Xút 2%", duration_min: 20, params: [{ name: "NaOH", setpoint: 2, unit: "%" }] },
        { name: "Tráng nước", duration_min: 10, params: [] }] }] },
  ];
}

function procHarvest() {
  const box = $("vf_proc");
  if (!box) return PROC_MODEL;
  const ups = [];
  box.querySelectorAll(":scope > .proc-up").forEach(upEl => {
    const up = { name: upEl.querySelector(".pu-name").value.trim(),
                 unit_class: upEl.querySelector(".pu-class").value, operations: [] };
    upEl.querySelectorAll(":scope > .proc-op").forEach(opEl => {
      const op = { name: opEl.querySelector(".po-name").value.trim(), phases: [] };
      opEl.querySelectorAll(":scope > .proc-ph").forEach(phEl => {
        const ph = { name: phEl.querySelector(".pp-name").value.trim() };
        const dur = phEl.querySelector(".pp-dur").value.trim();
        if (dur !== "") ph.duration_min = parseFloat(dur);
        const pn = phEl.querySelector(".pp-pn").value.trim();
        if (pn) {
          const pv = phEl.querySelector(".pp-pv").value.trim();
          const num = parseFloat(pv);
          ph.params = [{ name: pn, setpoint: (pv !== "" && !isNaN(num)) ? num : pv,
                         unit: phEl.querySelector(".pp-pu").value.trim() }];
        } else {
          ph.params = [];
        }
        op.phases.push(ph);
      });
      up.operations.push(op);
    });
    ups.push(up);
  });
  PROC_MODEL = ups;
  return ups;
}

function procRender() {
  const box = $("vf_proc");
  if (!box) return;
  const p0 = (ph) => (ph.params && ph.params[0]) || {};
  box.innerHTML = PROC_MODEL.map((up, ui) => `
    <div class="proc-up" style="border:1px solid var(--border);border-radius:8px;padding:8px;margin-bottom:8px;background:var(--panel2)">
      <div class="row">
        <div class="field"><label>Công đoạn (Unit Procedure)</label><input class="pu-name" value="${esc(up.name || "")}" placeholder="Nấu / Lên men..."/></div>
        <div class="field"><label>Loại unit</label><select class="pu-class">${UNIT_CLASSES.map(c => `<option value="${c.v}" ${up.unit_class === c.v ? "selected" : ""}>${esc(c.t)}</option>`).join("")}</select></div>
        <div class="field" style="align-self:flex-end">
          <button class="btn sm sec" type="button" data-add-op="${ui}">+ Operation</button>
          <button class="btn sm sec" type="button" data-del-up="${ui}">✕ Xóa</button></div>
      </div>
      ${(up.operations || []).map((op, oi) => `
        <div class="proc-op" style="margin-left:14px;border-left:2px solid var(--border);padding-left:10px;margin-top:6px">
          <div class="row">
            <div class="field"><label>Operation</label><input class="po-name" value="${esc(op.name || "")}" placeholder="Đường hóa..."/></div>
            <div class="field" style="align-self:flex-end">
              <button class="btn sm sec" type="button" data-add-ph="${ui}.${oi}">+ Phase</button>
              <button class="btn sm sec" type="button" data-del-op="${ui}.${oi}">✕</button></div>
          </div>
          ${(op.phases || []).map((ph, pi) => `
            <div class="proc-ph" style="margin-left:14px;margin-top:4px">
              <div class="row">
                <div class="field"><label>Phase</label><input class="pp-name" value="${esc(ph.name || "")}"/></div>
                <div class="field"><label>Phút</label><input class="pp-dur" type="number" value="${ph.duration_min ?? ""}" style="width:90px"/></div>
                <div class="field"><label>Setpoint</label><input class="pp-pn" value="${esc(p0(ph).name || "")}" placeholder="Nhiệt độ" style="width:120px"/></div>
                <div class="field"><label>Giá trị</label><input class="pp-pv" value="${p0(ph).setpoint ?? ""}" style="width:80px"/></div>
                <div class="field"><label>ĐVT</label><input class="pp-pu" value="${esc(p0(ph).unit || "")}" size="4"/></div>
                <div class="field" style="align-self:flex-end"><button class="btn sm sec" type="button" data-del-ph="${ui}.${oi}.${pi}">✕</button></div>
              </div>
            </div>`).join("")}
        </div>`).join("")}
    </div>`).join("") +
    `<button class="btn sm" type="button" id="proc_add_up">+ Thêm công đoạn</button>`;

  $("proc_add_up").onclick = () => { procHarvest(); PROC_MODEL.push({ name: "", unit_class: "brewhouse", operations: [] }); procRender(); };
  box.querySelectorAll("[data-del-up]").forEach(b => b.onclick = () => { procHarvest(); PROC_MODEL.splice(+b.dataset.delUp, 1); procRender(); });
  box.querySelectorAll("[data-add-op]").forEach(b => b.onclick = () => { procHarvest(); PROC_MODEL[+b.dataset.addOp].operations.push({ name: "", phases: [] }); procRender(); });
  box.querySelectorAll("[data-del-op]").forEach(b => b.onclick = () => { procHarvest(); const [u, o] = b.dataset.delOp.split(".").map(Number); PROC_MODEL[u].operations.splice(o, 1); procRender(); });
  box.querySelectorAll("[data-add-ph]").forEach(b => b.onclick = () => { procHarvest(); const [u, o] = b.dataset.addPh.split(".").map(Number); PROC_MODEL[u].operations[o].phases.push({ name: "", params: [] }); procRender(); });
  box.querySelectorAll("[data-del-ph]").forEach(b => b.onclick = () => { procHarvest(); const [u, o, p] = b.dataset.delPh.split(".").map(Number); PROC_MODEL[u].operations[o].phases.splice(p, 1); procRender(); });
}

// ================= BATCHES =================
let SELECTED_BATCH = null;
VIEWS.batches = async function () {
  const [batches, orders] = await Promise.all([GET("/batches"), GET("/orders")]);
  CACHE.orders = orders;
  const oopts = orders.filter(o => o.status !== "completed" && o.status !== "cancelled")
    .map(o => `<option value="${o.order_id}">${esc(o.order_code)}</option>`).join("");
  $("view-batches").innerHTML = `
    <div class="panel"><h2>Tạo mẻ (từ lệnh + recipe version 'effective')</h2>
      <div class="row">
        <div class="field"><label>Lệnh SX</label><select id="b_order">${oopts}</select></div>
        <div class="field"><label>Recipe version</label><select id="b_ver"><option>— chọn lệnh trước —</option></select></div>
        <div class="field"><label>SL kế hoạch</label><input id="b_qty" type="number" placeholder="theo lệnh nếu trống" style="width:140px"/></div>
        <div class="field"><label>Mã mẻ (tùy chọn)</label><input id="b_code" placeholder="tự sinh nếu trống" /></div>
        <button class="btn sec" id="b_check">Kiểm tra tồn</button>
        <button class="btn" id="b_create">Tạo mẻ</button>
      </div>
      <div id="b_avail" class="muted" style="margin-top:6px">Chỉ recipe version đã <code class="k">effective</code> mới được dùng. Hệ thống kiểm tra tồn theo BOM trước khi tạo.</div>
    </div>
    <div class="split">
      <div class="panel"><h2>Danh sách mẻ</h2>${tableBatches(batches, true)}</div>
      <div class="panel" id="b_detail"><h2>Chi tiết mẻ</h2><div class="muted">Chọn một mẻ để xem.</div></div>
    </div>`;
  // load effective versions for selected order's product
  const loadVers = () => guard(async () => {
    const order = orders.find(o => o.order_id === $("b_order").value);
    if (!order) return;
    const recs = await GET("/recipes");
    let opts = "";
    for (const r of recs.filter(r => r.product_id === order.product_id)) {
      const vs = await GET(`/recipes/${r.recipe_id}/versions`);
      vs.filter(v => v.state === "effective").forEach(v =>
        opts += `<option value="${v.version_id}">${esc(r.code)} v${v.version_no}</option>`);
    }
    $("b_ver").innerHTML = opts || "<option>(không có version effective)</option>";
  });
  if ($("b_order")) { $("b_order").onchange = loadVers; loadVers(); }
  const plannedQty = () => {
    const v = parseFloat($("b_qty").value);
    if (Number.isFinite(v) && v > 0) return v;
    const o = orders.find(x => x.order_id === $("b_order").value);
    return o ? o.planned_qty : 0;
  };
  const checkAvail = async () => {
    const vid = $("b_ver").value; if (!vid || vid.startsWith("(") || vid.startsWith("—")) return null;
    const a = await GET(`/batches/availability?recipe_version_id=${vid}&planned_qty=${plannedQty()}`);
    $("b_avail").innerHTML = `Nhu cầu BOM (hệ số ${a.factor}×): ` + a.rows.map(r =>
      `<span class="badge ${r.ok ? "available" : "overdue"}" style="margin:2px">${esc(r.material_code)}: cần ${r.required} / tồn ${r.available}${r.ok ? "" : " ✗thiếu " + r.short}</span>`).join(" ")
      + (a.shortage ? ' <b style="color:var(--red)">— THIẾU TỒN</b>' : ' <b style="color:var(--green)">— đủ tồn</b>');
    return a;
  };
  $("b_check").onclick = () => guard(checkAvail);
  $("b_create").onclick = () => guard(async () => {
    const a = await checkAvail();
    let allow = false;
    if (a && a.shortage) {
      if (!confirm("Không đủ tồn kho theo định mức BOM. Vẫn tạo mẻ (ghi nhận thiếu)?")) return;
      allow = true;
    }
    const b = await POST("/batches", { order_id: $("b_order").value, recipe_version_id: $("b_ver").value,
      planned_qty: $("b_qty").value ? parseFloat($("b_qty").value) : null,
      batch_code: $("b_code").value || null, allow_shortage: allow });
    toast("Đã tạo mẻ " + b.batch_code); render("batches");
  });
  document.querySelectorAll("[data-batch]").forEach(tr => tr.onclick = () => showBatch(tr.dataset.batch));
  if (SELECTED_BATCH) showBatch(SELECTED_BATCH);
};
function tableBatches(batches, clickable) {
  return `<table><thead><tr><th>Mã mẻ</th><th>Trạng thái</th><th>Chất lượng</th><th>KH</th><th>Thực tế</th></tr></thead>
    <tbody>${batches.map(b => `<tr ${clickable ? `data-batch="${b.batch_id}" style="cursor:pointer"` : ""}>
      <td><code class="k">${esc(b.batch_code)}</code></td><td>${badge(b.state)}</td>
      <td>${badge(b.quality_status)}</td><td>${b.planned_qty}</td><td>${b.actual_qty ?? "—"}</td></tr>`).join("")}</tbody></table>`;
}
async function showBatch(id) {
  SELECTED_BATCH = id;
  const b = await GET("/batches/" + id);
  const lots = await GET("/lots");
  const results = await GET("/quality/results?scope_id=" + id);
  const readings = await GET("/batches/" + id + "/readings");
  const bom = await GET("/batches/" + id + "/bom");
  const next = { planned: ["ready", "cancelled"], ready: ["running", "cancelled"],
    running: ["held", "completed", "cancelled"], held: ["running", "cancelled"],
    completed: ["closed"], closed: [], cancelled: [] }[b.state] || [];
  const transBtns = next.map(n => `<button class="btn sm sec" data-bt="${n}">→ ${n}</button>`).join(" ");
  const avail = lots.filter(l => l.status === "available");
  const lotOpts = avail.map(l => `<option value="${l.lot_id}">${esc(l.lot_code)} (${l.quantity}${l.uom})</option>`).join("");
  const snap = b.recipe_snapshot || {};
  // Nhóm readings theo tham số cho đường cong lên men.
  const byParam = {};
  readings.forEach(r => { (byParam[r.parameter] = byParam[r.parameter] || []).push(r); });
  const curveColors = { gravity: "#f5a623", temperature: "#e74c3c", pH: "#3498db" };
  const curveLabels = { gravity: "Độ đường", temperature: "Nhiệt độ", pH: "pH" };
  const curves = Object.keys(byParam).map(p => {
    const pts = byParam[p];
    return `<div style="margin-bottom:8px">${CH.line(pts, {
      color: curveColors[p] || "#17a2b8", unit: pts[0].unit || "",
      label: curveLabels[p] || p, height: 110 })}</div>`;
  }).join("");

  $("b_detail").innerHTML = `<h2>Mẻ ${esc(b.batch_code)}</h2>
    <dl class="detail">
      <dt>Trạng thái</dt><dd>${badge(b.state)} ${transBtns}</dd>
      <dt>Chất lượng</dt><dd>${badge(b.quality_status)}</dd>
      <dt>Recipe snapshot</dt><dd>v${snap.version_no ?? "?"} (bất biến) · ${(snap.parameters || []).length} tham số · ${(snap.quality_checks || []).length} QC</dd>
      <dt>SL kế hoạch/thực tế</dt><dd>${b.planned_qty} / ${b.actual_qty ?? "—"} ${b.uom}</dd>
      <dt>Bắt đầu / Kết thúc</dt><dd class="muted">${fmt(b.start_at)} → ${fmt(b.end_at)}</dd>
    </dl>
    ${curves ? `<h3>Đường cong lên men</h3>${curves}` : ""}
    <h3>Tiêu thụ nguyên liệu (genealogy)</h3>
    <div class="row">
      <div class="field"><label>Lô khả dụng</label><select id="c_lot">${lotOpts || "<option>(hết lô available)</option>"}</select></div>
      <div class="field"><label>Số lượng</label><input id="c_qty" type="number" value="100" /></div>
      <button class="btn sm" id="c_do">Consume</button>
    </div>
    <h3>📋 Định mức (BOM) ↔ Thực tế tiêu thụ <span class="muted">· quy mô chuẩn ${bom.base_qty ? bom.base_qty.toLocaleString("vi-VN") + " " + esc(bom.base_uom || "") : "—"} · hệ số ${bom.factor}×</span></h3>
    ${(bom.lines && bom.lines.length) ? `<table><thead><tr><th>Vật tư</th><th>Định mức</th><th>Thực tế</th><th>Chênh</th><th>%</th><th>Trạng thái</th></tr></thead>
      <tbody>${bom.lines.map(l => `<tr class="row-${{dat:"blue",vuot:"red",thieu:"green",chua_dung:""}[l.status] || ""}">
        <td><code class="k">${esc(l.material_code)}</code></td><td>${l.planned} ${esc(l.uom || "")}</td>
        <td>${l.actual}</td><td style="color:${l.diff > 0 ? "var(--red)" : l.diff < 0 ? "var(--orange)" : "var(--muted)"}">${l.diff > 0 ? "+" : ""}${l.diff}</td>
        <td>${l.pct}%</td><td>${badge({dat:"available",vuot:"critical",thieu:"due",chua_dung:"planned"}[l.status] || "planned")}${{dat:"đạt",vuot:"vượt định mức",thieu:"thiếu",chua_dung:"chưa dùng"}[l.status] || l.status}</td></tr>`).join("")}
      ${(bom.extras || []).map(e => `<tr><td><code class="k">${esc(e.material_code)}</code></td><td class="muted">(ngoài BOM)</td><td>${e.actual}</td><td colspan=3>${badge("obsolete")}ngoài định mức</td></tr>`).join("")}</tbody></table>`
      : '<div class="muted">Công thức của mẻ chưa khai báo BOM.</div>'}
    <h3>Tạo lô output</h3>
    <div class="row">
      <div class="field"><label>Mã lô</label><input id="p_code" placeholder="BRIGHT-..." /></div>
      <div class="field"><label>Loại</label><select id="p_type"><option value="brew">brew</option><option value="bright">bright</option><option value="package">package</option></select></div>
      <div class="field"><label>SL</label><input id="p_qty" type="number" value="48000" /></div>
      <button class="btn sm" id="p_do">Produce</button>
    </div>
    <h3>Ghi actual</h3>
    <div class="row">
      <div class="field"><label>Tham số</label><input id="a_name" placeholder="Nhiệt độ" /></div>
      <div class="field"><label>Giá trị</label><input id="a_val" type="number" /></div>
      <div class="field"><label>ĐVT</label><input id="a_unit" size="5" /></div>
      <button class="btn sm" id="a_do">Ghi</button>
    </div>
    <h3>Kết quả QC của mẻ</h3>
    <table><thead><tr><th>Tham số</th><th>Giá trị</th><th>Giới hạn</th><th>KQ</th></tr></thead>
      <tbody>${results.map(r => `<tr><td>${esc(r.parameter)}</td><td>${r.value ?? "—"} ${esc(r.unit || "")}</td>
        <td class="muted">${r.lower_limit ?? "−∞"} … ${r.upper_limit ?? "+∞"}</td><td>${badge(r.status)}</td></tr>`).join("") || '<tr><td colspan=4 class="muted">Chưa có</td></tr>'}</tbody></table>
    <div class="row" style="margin-top:10px">
      <button class="btn sm" id="b_ebr">📄 Hồ sơ mẻ (EBR)</button>
      <a class="btn sm sec" href="#" id="b_audit">Xem audit mẻ này</a>
    </div>`;
  document.querySelectorAll("[data-bt]").forEach(x => x.onclick = () => guard(async () => {
    await POST(`/batches/${id}/transition`, { target: x.dataset.bt }); toast("→ " + x.dataset.bt); render("batches");
  }));
  $("c_do").onclick = () => guard(async () => {
    const q = parseFloat($("c_qty").value);
    if (!Number.isFinite(q) || q <= 0) { toast("Số lượng tiêu thụ không hợp lệ", "err"); return; }
    const body = { lot_id: $("c_lot").value, quantity: q };
    try {
      await POST(`/batches/${id}/consume`, body);
    } catch (e) {
      if (/Vượt định mức BOM/.test(e.message)) {
        if (!confirm(e.message + "\n\nVẫn tiêu thụ vượt định mức (cần phê duyệt)?")) return;
        await POST(`/batches/${id}/consume`, { ...body, allow_over: true });
      } else { throw e; }
    }
    toast("Đã consume lô"); showBatch(id);
  });
  $("p_do").onclick = () => guard(async () => {
    await POST(`/batches/${id}/produce`, { lot_code: $("p_code").value, quantity: parseFloat($("p_qty").value), lot_type: $("p_type").value });
    toast("Đã tạo lô output (mặc định ON HOLD)"); showBatch(id);
  });
  $("a_do").onclick = () => guard(async () => {
    await POST(`/batches/${id}/actuals`, { name: $("a_name").value, actual: parseFloat($("a_val").value), unit: $("a_unit").value });
    toast("Đã ghi actual"); showBatch(id);
  });
  $("b_audit").onclick = (e) => { e.preventDefault(); document.querySelector('[data-view="audit"]').click(); setTimeout(() => { $("au_entity").value = id; $("au_load").click(); }, 50); };
  $("b_ebr").onclick = () => openEBR(id);
}

// ================= EBR — Hồ sơ mẻ điện tử =================
async function openEBR(batchId) {
  const e = await GET("/batches/" + batchId + "/ebr");
  const c = e.core;
  const steps = (c.steps || []).map(s => `<div class="ev"><b>${esc(s.action)}</b>
    <span class="muted">· ${esc(s.by)}${s.role ? " (" + esc(s.role) + ")" : ""} · ${fmt(s.time)}</span>
    ${s.reason ? `<div class="muted">Lý do: ${esc(s.reason)}</div>` : ""}
    ${s.detail ? `<div class="muted" style="font-size:12px">${esc(JSON.stringify(s.detail))}</div>` : ""}</div>`).join("");
  const matRows = (c.materials.lines || []).map(l => `<tr class="row-${{dat:"blue",vuot:"red",thieu:"green",chua_dung:""}[l.status] || ""}">
    <td><code class="k">${esc(l.material_code)}</code></td><td>${l.planned} ${esc(l.uom || "")}</td><td>${l.actual}</td>
    <td>${badge({dat:"available",vuot:"critical",thieu:"due",chua_dung:"planned"}[l.status] || "planned")}${l.status}</td></tr>`).join("");
  const qc = (c.quality || []).map(q => `<tr><td>${esc(q.parameter)}</td><td>${q.value ?? "—"} ${esc(q.unit || "")}</td><td>${badge(q.status)}</td></tr>`).join("");
  const devs = (c.deviations || []).map(d => `<tr><td><code class="k">${esc(d.code)}</code></td><td>${esc(d.severity)}</td><td>${esc(d.reason)}</td><td>${badge(d.state)}</td></tr>`).join("");
  const chems = (c.chemicals || []).map(x => `<tr><td>${esc(x.stage)}</td><td>${esc(x.chemical)}</td><td>${x.quantity} ${esc(x.uom)}</td></tr>`).join("");
  const sigs = (e.signatures || []).map(s => `<tr><td>${esc(s.meaning)}</td><td>${esc(s.by)} ${s.role ? "(" + esc(s.role) + ")" : ""}</td>
    <td class="muted">${fmt(s.time)}</td><td class="muted">${esc(s.reason || "")}</td><td class="hashbox" style="max-width:120px">${esc((s.hash || "").slice(0, 16))}…</td></tr>`).join("");
  const lockBadge = e.locked ? `${badge("closed")}ĐÃ KHÓA (v${e.snapshot ? e.snapshot.version : "?"})` : `${badge("planned")}chưa khóa`;
  modal(`<h2>📄 Hồ sơ mẻ điện tử (EBR) — ${esc(c.batch_code)} ${lockBadge}</h2>
    <dl class="detail">
      <dt>Lệnh ERP / WO</dt><dd>${esc(c.order_code || "—")} / ${esc(c.work_order_id || "—")}</dd>
      <dt>Công thức</dt><dd>v${c.recipe.version_no ?? "?"} · quy mô chuẩn ${c.recipe.base_qty ? c.recipe.base_qty.toLocaleString("vi-VN") + " " + esc(c.recipe.base_uom) : "—"}</dd>
      <dt>SL kế hoạch/thực tế</dt><dd>${c.planned_qty} / ${c.actual_qty ?? "—"} ${esc(c.uom)}</dd>
      <dt>Trạng thái</dt><dd>${badge(c.state)} · QC ${badge(c.quality_status)}</dd>
      <dt>Bắt đầu/Kết thúc</dt><dd class="muted">${fmt(c.start_at)} → ${fmt(c.end_at)}</dd>
    </dl>
    <h3>Các bước thực thi (step-by-step)</h3>
    <div class="timeline" style="max-height:220px;overflow-y:auto">${steps || '<div class="muted">—</div>'}</div>
    <div class="split">
      <div><h3>Định mức ↔ Thực tế (BOM)</h3><table><thead><tr><th>Vật tư</th><th>ĐM</th><th>TT</th><th>TT</th></tr></thead><tbody>${matRows || '<tr><td colspan=4 class="muted">—</td></tr>'}</tbody></table>
        <h3>Kết quả QC</h3><table><thead><tr><th>Chỉ tiêu</th><th>Giá trị</th><th>KQ</th></tr></thead><tbody>${qc || '<tr><td colspan=3 class="muted">—</td></tr>'}</tbody></table></div>
      <div><h3>Deviation</h3><table><thead><tr><th>Mã</th><th>Mức</th><th>Lý do</th><th>TT</th></tr></thead><tbody>${devs || '<tr><td colspan=4 class="muted">—</td></tr>'}</tbody></table>
        <h3>Hóa chất</h3><table><thead><tr><th>Công đoạn</th><th>Hóa chất</th><th>SL</th></tr></thead><tbody>${chems || '<tr><td colspan=3 class="muted">—</td></tr>'}</tbody></table></div>
    </div>
    <h3>Chữ ký điện tử</h3>
    <table><thead><tr><th>Ý nghĩa</th><th>Người ký</th><th>Thời gian</th><th>Lý do</th><th>Hash</th></tr></thead>
      <tbody>${sigs || '<tr><td colspan=5 class="muted">Chưa có chữ ký.</td></tr>'}</tbody></table>
    <h3>Toàn vẹn</h3>
    <div class="hashbox">Hash hiện tại: ${esc(e.current_hash)}</div>
    ${e.snapshot ? `<div class="hashbox" style="margin-top:4px">Hash đã khóa (v${e.snapshot.version}, ${esc(e.snapshot.locked_by)}): ${esc(e.snapshot.hash)} ${e.snapshot.hash === e.current_hash ? '<span style="color:var(--green)">✓ khớp</span>' : '<span style="color:var(--red)">✗ KHÁC (đã chỉnh sau khóa?)</span>'}</div>` : ""}
    <div class="row" style="margin-top:14px">
      ${e.locked ? '<span class="muted">Hồ sơ đã khóa — bất biến (chỉ amendment).</span>' : `
      <button class="btn sec" id="ebr_sign">✍ Ký điện tử</button>
      <button class="btn" id="ebr_lock">🔒 Phê duyệt & khóa hồ sơ</button>`}
    </div>`);
  if (!e.locked) {
    $("ebr_sign").onclick = () => guard(async () => {
      const meaning = prompt("Ý nghĩa chữ ký (vd: Xác nhận thực thi / Duyệt QC):", "Xác nhận thực thi");
      if (meaning === null) return;
      const reason = prompt("Lý do (tùy chọn):", "") || "";
      const password = prompt("Nhập lại MẬT KHẨU để ký điện tử (xác thực lại):");
      if (!password) return;
      await POST(`/batches/${batchId}/ebr/sign`, { password, meaning, reason });
      toast("Đã ký điện tử"); openEBR(batchId);
    });
    $("ebr_lock").onclick = () => guard(async () => {
      const reason = prompt("Lý do phê duyệt & khóa hồ sơ:", "Hồ sơ hoàn tất, phê duyệt release") || "";
      const password = prompt("Nhập lại MẬT KHẨU để khóa (cần quyền ebr.approve):");
      if (!password) return;
      await POST(`/batches/${batchId}/ebr/lock`, { password, reason });
      toast("Đã khóa hồ sơ mẻ"); closeModal(); render("batches");
    });
  }
}

// ================= QUALITY =================
VIEWS.quality = async function () {
  const [results, devs, batches, lots, qcParams, brewBatches, fermentsData, filtersData, bottlesData, holdHistory, pendingStageQc] = await Promise.all([
    GET("/quality/results"), GET("/quality/deviations"), GET("/batches"), GET("/lots"),
    GET("/qc/parameters?active_only=false").catch(() => []),
    GET("/brewing/brew-batches").catch(() => []),
    GET("/brewing/ferments").catch(() => ({ items: [] })),
    GET("/brewing/filters").catch(() => []),
    GET("/brewing/bottles").catch(() => []),
    GET("/audit?action=hold,release&limit=100").catch(() => []),
    GET("/quality/pending-stage-qc").catch(() => [])]);
  const ferments = fermentsData.items || [];
  // Hold/Release + Mở deviation tách riêng theo công đoạn sản xuất (Nấu/Lên men/Lọc/Chiết),
  // ngoài Mẻ SX (ISA-88)/Lô NVL đã có — mỗi <optgroup> 1 công đoạn, nhãn kèm trạng thái hiện
  // tại để thấy ngay công đoạn nào đang bị giữ. Xem services/quality.py::_STAGE_MODELS.
  const hqLabel = (q) => q === "on_hold" ? " — ĐANG HOLD" : "";
  const hdScopeOpts = `<optgroup label="Mẻ SX (ISA-88)">${
      batches.map(b => `<option value="batch:${b.batch_id}">mẻ ${esc(b.batch_code)}</option>`).join("")}</optgroup>
    <optgroup label="Nấu (mẻ nấu)">${
      brewBatches.map(b => `<option value="brew_batch:${b.batch_id}">mẻ ${esc(b.batch_code)} (mã nấu ${esc(b.brew_code || "?")})${hqLabel(b.quality_status)}</option>`).join("")}</optgroup>
    <optgroup label="Lên men">${
      ferments.map(f => `<option value="ferment:${f.ferment_id}">lô LM ${esc(f.lm_code)}${hqLabel(f.quality_status)}</option>`).join("")}</optgroup>
    <optgroup label="Lọc">${
      filtersData.map(f => `<option value="filter:${f.filter_id}">mẻ lọc ${esc(f.filter_code)}${hqLabel(f.quality_status)}</option>`).join("")}</optgroup>
    <optgroup label="Chiết">${
      bottlesData.map(b => `<option value="bottle:${b.bottle_id}">mã chiết ${esc(b.bottle_code)}${hqLabel(b.quality_status)}</option>`).join("")}</optgroup>
    <optgroup label="Nguyên vật liệu (lô NVL)">${
      lots.map(l => `<option value="lot:${l.lot_id}">lô ${esc(l.lot_code)}</option>`).join("")}</optgroup>`;
  const batchById = Object.fromEntries(batches.map(b => [b.batch_id, b]));
  const lotById = Object.fromEntries(lots.map(l => [l.lot_id, l]));
  const paramByCode = Object.fromEntries(qcParams.map(p => [p.code, p]));
  const fermentByLm = Object.fromEntries(ferments.map(f => [f.lm_code, f]));
  const filterByCode = Object.fromEntries(filtersData.map(f => [f.filter_code, f]));
  const bottleByCode = Object.fromEntries(bottlesData.map(b => [b.bottle_code, b]));
  const brewBatchByKey = {};
  brewBatches.forEach(r => {
    const info = { batch_code: r.batch_code, brew_id: r.brew_id, brew_code: r.brew_code };
    brewBatchByKey[r.batch_id] = info;
    brewBatchByKey[r.batch_code] = info;
  });
  const fermentById = Object.fromEntries(ferments.map(f => [f.ferment_id, f]));
  const filterById = Object.fromEntries(filtersData.map(f => [f.filter_id, f]));
  const bottleById = Object.fromEntries(bottlesData.map(b => [b.bottle_id, b]));
  // Nhãn hiển thị cho lịch sử Hold/Release — scope_id ở đây LUÔN là PK thật (khác quy ước
  // scope_id ghép chuỗi của qc_catalog dùng cho khai báo chỉ tiêu), xem services/quality.py.
  const holdScopeLabel = (scopeType, scopeId) => {
    if (scopeType === "batch") return `Mẻ SX ${batchById[scopeId] ? esc(batchById[scopeId].batch_code) : scopeId}`;
    if (scopeType === "lot") return `Lô NVL ${lotById[scopeId] ? esc(lotById[scopeId].lot_code) : scopeId}`;
    if (scopeType === "brew_batch") { const b = brewBatchByKey[scopeId];
      return b ? `Mẻ nấu ${esc(b.batch_code)} (mã nấu ${esc(b.brew_code || "?")})` : `Mẻ nấu ${scopeId}`; }
    if (scopeType === "ferment") return `Lô LM ${fermentById[scopeId] ? esc(fermentById[scopeId].lm_code) : scopeId}`;
    if (scopeType === "filter") return `Mẻ lọc ${filterById[scopeId] ? esc(filterById[scopeId].filter_code) : scopeId}`;
    if (scopeType === "bottle") return `Mã chiết ${bottleById[scopeId] ? esc(bottleById[scopeId].bottle_code) : scopeId}`;
    return `${esc(scopeType)} ${scopeId}`;
  };
  const pendingQc = lots.filter(l => l.status === "on_hold");
  $("view-quality").innerHTML = `
    <div class="panel"><h2>🔬 Lô NVL chờ khai báo/duyệt chỉ tiêu chất lượng <span class="muted">(${pendingQc.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Nguyên liệu nhập kho có gán nhóm chỉ tiêu bắt buộc sẽ nằm ở đây cho tới khi KCS khai báo đủ &amp; duyệt.</div>
      <div class="tablewrap"><table>
        <thead><tr><th>Lô</th><th>SL</th><th>Vị trí</th><th></th></tr></thead>
        <tbody>${pendingQc.map(l => `<tr>
          <td><code class="k">${esc(l.lot_code)}</code>${badge("on_hold")}</td>
          <td>${l.quantity} ${l.uom}</td><td class="muted">${esc(l.location || "")}</td>
          <td><button class="btn sm" data-qclot="${esc(l.lot_id)}">Khai báo / Duyệt</button></td></tr>`).join("") ||
          '<tr><td colspan=4 class="muted">Không có lô nào đang chờ.</td></tr>'}</tbody>
      </table></div>
    </div>
    <div class="panel"><h2>🧪 Công đoạn chờ khai báo chỉ tiêu chất lượng <span class="muted">(${pendingStageQc.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Mẻ nấu/lô lên men/mẻ lọc/mã chiết có gán nhóm chỉ tiêu bắt buộc nhưng chưa khai báo đủ sẽ nằm ở đây — bấm "Khai báo" để chuyển tới đúng công đoạn.</div>
      <div class="tablewrap"><table>
        <thead><tr><th>Công đoạn</th><th>Mẻ/lô</th><th>Chỉ tiêu còn thiếu</th><th></th></tr></thead>
        <tbody>${pendingStageQc.map(p => `<tr>
          <td>${esc(p.stage_label)}</td>
          <td>${esc(p.label)}</td>
          <td class="muted">${p.pending.map(c => esc(paramByCode[c] ? paramByCode[c].name : c)).join(", ")}</td>
          <td><button class="btn sm" data-navscope="${esc(p.scope_type)}|${esc(p.scope_id)}">Khai báo</button></td></tr>`).join("") ||
          '<tr><td colspan=4 class="muted">Không có công đoạn nào đang chờ.</td></tr>'}</tbody>
      </table></div>
    </div>
    <div class="panel"><h2>Hold / Release</h2>
        <div class="row">
          <div class="field"><label>Phạm vi (theo công đoạn)</label>
            <input id="h_scope_q" placeholder="Tìm nhanh (gõ mã lô/mẻ)..." style="margin-bottom:2px"/>
            <select id="h_scope">${hdScopeOpts}</select></div>
        </div>
        <div class="row">
          <div class="field" style="flex:1"><label>Lý do HOLD <span style="color:var(--red)">*</span></label><input id="h_hold_reason" placeholder="Bắt buộc — VD: nghi ngờ nhiễm khuẩn, chờ kiểm tra lại..."/></div>
          <button class="btn sec" id="h_hold" style="align-self:flex-end">HOLD (qa/supervisor)</button>
        </div>
        <div class="row">
          <div class="field" style="flex:1"><label>Lý do RELEASE <span style="color:var(--red)">*</span></label><input id="h_release_reason" placeholder="Bắt buộc — VD: đã kiểm tra lại, đạt chất lượng..."/></div>
          <button class="btn" id="h_rel" style="align-self:flex-end">RELEASE (qa)</button>
        </div>
        <div class="muted">HOLD 1 mẻ nấu/lô LM/mẻ lọc/mã chiết sẽ chặn sửa/xóa/chuyển bước công đoạn đó cho tới khi RELEASE (cũng hiện badge "⛔ HOLD" ngay trên dòng công đoạn đó). Release bị chặn nếu còn FAIL chưa đóng deviation. Bắt buộc nhập lý do cho cả 2 thao tác — lưu vào Lịch sử Hold/Release bên dưới.</div>
        <h3>Mở deviation</h3>
        <div class="row">
          <div class="field"><label>Phạm vi (theo công đoạn)</label>
            <input id="d_scope_q" placeholder="Tìm nhanh (gõ mã lô/mẻ)..." style="margin-bottom:2px"/>
            <select id="d_scope">${hdScopeOpts}</select></div>
          <div class="field"><label>Mức</label><select id="d_sev"><option>minor</option><option>major</option><option>critical</option></select></div>
          <div class="field"><label>Lý do</label><input id="d_reason" /></div>
          <button class="btn sec" id="d_open">Mở</button>
        </div>
        <h3>Lịch sử Hold/Release <span class="muted">(${holdHistory.length})</span></h3>
        <input class="searchbox" data-tbl="t_holdrelease" placeholder="Tìm theo phạm vi, hành động, lý do, người thực hiện..."/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_holdrelease">
          <thead><tr><th>Lúc</th><th>Phạm vi</th><th>Hành động</th><th>Lý do</th><th>Người thực hiện</th></tr></thead>
          <tbody>${holdHistory.map(h => `<tr>
            <td class="muted">${fmt(h.ts)}</td>
            <td>${holdScopeLabel(h.entity_type, h.entity_id)}</td>
            <td>${h.action === "hold" ? badge("on_hold") + "HOLD" : badge("available") + "RELEASE"}</td>
            <td class="muted">${esc(h.reason || "—")}</td>
            <td class="muted">${esc(h.actor || "")}</td></tr>`).join("") ||
            '<tr><td colspan=5 class="muted">Chưa có lượt Hold/Release nào.</td></tr>'}</tbody>
        </table></div>
    </div>
    <div class="panel"><h2>Kết quả QC gần đây</h2>
      <div class="muted" style="margin-bottom:6px">Gộp theo mẻ/lô nguồn — mỗi công đoạn (mẻ nấu, lô LM, lô lọc, mã chiết, lô NVL...) là 1 nhóm riêng. Bấm vào tên mẻ/lô để chuyển tới đúng khu vực.</div>
      <input class="searchbox" data-tbl="t_qcresults" placeholder="Tìm theo mẻ/lô, chỉ tiêu, người ghi..."/>
      <div class="tablewrap" style="margin-top:6px"><table id="t_qcresults">
      <thead><tr><th>Mẻ/lô nguồn</th><th>Tham số</th><th>Giá trị</th><th>Giới hạn</th><th>KQ</th><th>Người ghi</th><th>Lúc</th></tr></thead>
      <tbody>${qcResultsWithGroupLabel(results, { batchById, lotById, brewBatchByKey, fermentByLm, filterByCode, bottleByCode, paramByCode }).map(r => `<tr>
        <td class="muted">${r.navigable ? `<button type="button" class="btn sm sec" data-navscope="${esc(r.scope_type)}|${esc(r.scope_id)}">${esc(r.groupLabel)}</button>` : esc(r.groupLabel)}</td>
        <td>${esc(r.paramLabel)}</td><td>${r.value ?? "—"} ${esc(r.unit || "")}</td>
        <td class="muted">${r.lower_limit ?? "−∞"} … ${r.upper_limit ?? "+∞"}</td><td>${badge(r.status)}</td>
        <td class="muted">${esc(r.recorded_by || "")}</td><td class="muted">${fmt(r.recorded_at)}</td></tr>`).join("") ||
        '<tr><td colspan=7 class="muted">Chưa có kết quả QC nào.</td></tr>'}</tbody></table></div></div>
    <div class="panel"><h2>Deviations</h2>
      <table><thead><tr><th>Mã</th><th>Mức</th><th>Lý do</th><th>Trạng thái</th><th>Hành động</th></tr></thead>
      <tbody>${devs.map(devRow).join("") || '<tr><td colspan=5 class="muted">Chưa có</td></tr>'}</tbody></table></div>`;
  const parseScope = (v) => { const [t, i] = v.split(":"); return { scope_type: t, scope_id: i }; };
  $("h_hold").onclick = () => guard(async () => {
    const reason = $("h_hold_reason").value.trim();
    if (!reason) throw new Error("Bắt buộc nhập Lý do HOLD.");
    await POST("/quality/hold", { ...parseScope($("h_scope").value), on_hold: true, reason });
    toast("Đã HOLD"); render("quality");
  });
  $("h_rel").onclick = () => guard(async () => {
    const reason = $("h_release_reason").value.trim();
    if (!reason) throw new Error("Bắt buộc nhập Lý do RELEASE.");
    await POST("/quality/hold", { ...parseScope($("h_scope").value), on_hold: false, reason });
    toast("Đã RELEASE"); render("quality");
  });
  wireSelectSearch("h_scope", "h_scope_q");
  wireSelectSearch("d_scope", "d_scope_q");
  $("d_open").onclick = () => guard(async () => {
    await POST("/quality/deviations", { ...parseScope($("d_scope").value), severity: $("d_sev").value, reason: $("d_reason").value });
    toast("Đã mở deviation"); render("quality");
  });
  document.querySelectorAll("[data-dt]").forEach(b => b.onclick = () => guard(async () => {
    const payload = { target: b.dataset.dt };
    if (b.dataset.devfield) {
      const input = b.parentElement.querySelector(`input[data-devfield="${b.dataset.devfield}"]`);
      const val = (input?.value || "").trim();
      if (!val) throw new Error(`Nhập ${DEV_TEXT_FIELD[b.dataset.dt].label.toLowerCase()} trước khi chuyển bước.`);
      payload[b.dataset.devfield] = val;
    }
    await POST(`/quality/deviations/${b.dataset.did}/transition`, payload);
    toast("Deviation → " + b.dataset.dt); render("quality");
  }));
  document.querySelectorAll("[data-qclot]").forEach(b => b.onclick = () => openLotQcModal(b.dataset.qclot, { editable: true }));
  document.querySelectorAll("[data-navscope]").forEach(b => b.onclick = () => {
    const [scopeType, scopeId] = b.dataset.navscope.split("|");
    if (scopeType === "lot") return openLotQcModal(scopeId, { editable: true });
    if (scopeType === "batch") return switchView("batches");
    if (scopeType === "brew_batch" || scopeType === "brew") { SUB.process = "nau"; return switchView("process"); }
    if (scopeType === "ferment") { SUB.process = "lenmen"; return switchView("process"); }
    if (scopeType === "filter") { SUB.process = "loc"; return switchView("process"); }
    if (scopeType === "bottle") { SUB.process = "chiet"; return switchView("process"); }
  });
  wirePaginate("t_qcresults", 10);
  wirePaginate("t_holdrelease", 10);
};
// Gộp kết quả QC theo mẻ/lô nguồn (scope_type/scope_id) — sắp theo nhóm để các dòng cùng
// 1 mẻ/lô đứng cạnh nhau thay vì xen lẫn theo thời gian ghi như trước. Đồng thời dịch mã
// tham số (QCParameter.code, VD "6245") sang tên thật, và đánh dấu dòng nào bấm được để
// nhảy về đúng khu vực (Nấu/Lên men/Lọc/Chiết/Mẻ sản xuất) đang chứa mẻ/lô đó.
function qcResultsWithGroupLabel(results, ctx) {
  const { batchById, lotById, brewBatchByKey, fermentByLm, filterByCode, bottleByCode, paramByCode } = ctx;
  const labelFor = (r) => {
    if (r.scope_type === "batch") {
      const b = batchById[r.scope_id];
      return { label: b ? `Mẻ SX ${b.batch_code}` : `Mẻ SX ${r.scope_id}`, navigable: true };
    }
    if (r.scope_type === "lot") {
      const l = lotById[r.scope_id];
      return { label: l ? `Lô NVL ${l.lot_code}` : `Lô NVL ${r.scope_id}`, navigable: true };
    }
    if (r.scope_type === "brew_batch" || r.scope_type === "brew") {
      const b = brewBatchByKey[r.scope_id];
      return { label: b ? `Mẻ nấu ${b.batch_code} (mã nấu ${b.brew_code})` : `Mẻ nấu ${r.scope_id} (không còn tồn tại)`, navigable: !!b };
    }
    if (r.scope_type === "ferment") {
      const [lmCode, part] = r.scope_id.split("__");
      const f = fermentByLm[lmCode];
      const partLabel = part === "len_men_phu" ? " — CT phụ" : part === "len_men_chinh" ? " — CT chính" : "";
      return { label: `Lô lên men ${lmCode}${partLabel}`, navigable: !!f };
    }
    if (r.scope_type === "filter") {
      const f = filterByCode[r.scope_id];
      return { label: `Mẻ lọc ${r.scope_id}`, navigable: !!f };
    }
    if (r.scope_type === "bottle") {
      const [bottleCode] = r.scope_id.split("__");
      const b = bottleByCode[bottleCode];
      return { label: `Mã chiết ${bottleCode}`, navigable: !!b };
    }
    return { label: `${r.scope_type} ${r.scope_id}`, navigable: false };
  };
  return results.map(r => {
    const { label, navigable } = labelFor(r);
    const p = paramByCode[r.parameter];
    const paramLabel = p ? `${p.name}${p.unit && !p.name.includes(p.unit) ? ` (${p.unit})` : ""}` : r.parameter;
    return { ...r, groupLabel: label, navigable, paramLabel };
  }).sort((a, b) => a.groupLabel.localeCompare(b.groupLabel) || new Date(b.recorded_at) - new Date(a.recorded_at));
}
// Chuyển sang "investigation" cần ghi Nội dung điều tra; chuyển sang "disposition" cần ghi
// Hướng xử lý — 2 trường CAPA này backend đã hỗ trợ (DeviationTransitionIn.investigation/
// disposition) nhưng trước đây UI không có ô nhập, nút chỉ đổi trạng thái suông.
const DEV_TEXT_FIELD = {
  investigation: { field: "investigation", label: "Nội dung điều tra" },
  disposition: { field: "disposition", label: "Hướng xử lý" },
};
function devRow(d) {
  const next = { open: ["triage"], triage: ["investigation"], investigation: ["disposition"],
    disposition: ["approval"], approval: ["closed"], closed: [] }[d.state] || [];
  const actions = next.map(n => {
    const t = DEV_TEXT_FIELD[n];
    if (!t) return `<button class="btn sm sec" data-dt="${n}" data-did="${d.deviation_id}">→ ${n}</button>`;
    return `<span style="display:inline-flex;gap:4px;align-items:center">
      <input class="dv-text" data-devfield="${t.field}" placeholder="${esc(t.label)}..." style="width:150px"/>
      <button class="btn sm sec" data-dt="${n}" data-did="${d.deviation_id}" data-devfield="${t.field}">→ ${n}</button>
    </span>`;
  }).join(" ");
  const notes = [d.investigation ? `<div class="muted">Điều tra: ${esc(d.investigation)}</div>` : "",
    d.disposition ? `<div class="muted">Xử lý: ${esc(d.disposition)}</div>` : ""].join("");
  return `<tr><td><code class="k">${esc(d.deviation_code)}</code></td><td>${badge(d.severity)}</td>
    <td>${esc(d.reason)}${notes}</td><td>${badge(d.state)}</td><td style="white-space:nowrap">${actions || "—"}</td></tr>`;
}

// ================= TRACEABILITY =================
VIEWS.trace = async function () {
  const brews = await GET("/brewing/brews").catch(() => []);
  const brewOpts = `<option value="">(chọn lô nấu)</option>` + brews.map(b =>
    `<option value="${esc(b.brew_id)}">${esc(b.brew_code)}${b.product_code ? " — " + esc(b.product_code) : ""}</option>`).join("");
  $("view-trace").innerHTML = `
    <div class="panel"><h2>Truy xuất nguồn gốc & Recall</h2>
      <div class="row">
        <div class="field"><label>Mã lô / mã mẻ</label><input id="t_code" placeholder="PKG-2406-0001" /></div>
        <button class="btn" id="t_back">Truy ngược ↑</button>
        <button class="btn sec" id="t_fwd">Truy xuôi xuất ↓</button>
        <button class="btn sec" id="t_recall">Recall simulation</button>
        <button class="btn sec" id="t_record_btn">📄 Hồ sơ điện tử</button>
      </div>
      <div class="row" style="margin-top:8px">
        <div class="field"><label>Truy xuôi theo nấu — chọn lô nấu</label><select id="t_brew_sel">${brewOpts}</select></div>
        <button class="btn sec" id="t_fwd_brew">Truy xuôi theo nấu ↓</button>
      </div>
      <div class="muted">Truy ngược: thành phẩm → nguyên liệu. Truy xuôi xuất/Recall: nguyên liệu → các lô bị ảnh hưởng, đi tới tận nơi xuất (pallet/xuất kho). Truy xuôi theo nấu: chọn 1 lô nấu, xem xuôi chiều mẻ/lên men/lọc/chiết liên quan — DỪNG Ở CHIẾT, không ra thành phẩm/xuất kho bên ngoài. Hồ sơ điện tử: toàn bộ NVL→Nấu→Lên men→Lọc→Chiết của 1 lô trong 1 màn hình.</div>
    </div>
    <div class="panel" id="t_out"><div class="muted">Nhập mã và chọn hướng truy xuất.</div></div>
    <div id="t_record"></div>`;
  const code = () => $("t_code").value.trim();
  // Nút nào vừa bấm hiện màu chính (bỏ "sec"), các nút còn lại chuyển màu phụ — để luôn biết
  // rõ đang xem kết quả của thao tác truy xuất nào (trước đây màu nút cố định, gây nhầm lẫn).
  const TRACE_BTN_IDS = ["t_back", "t_fwd", "t_fwd_brew", "t_recall", "t_record_btn"];
  const setActiveTraceBtn = (activeId) => TRACE_BTN_IDS.forEach(id => $(id).classList.toggle("sec", id !== activeId));
  const traceGuard = async (fn) => {
    if (!code()) { $("t_out").innerHTML = `<div class="muted">⚠ Chưa nhập mã lô/mã mẻ.</div>`; return; }
    try { await fn(); }
    catch (e) { $("t_out").innerHTML = `<div class="muted">⚠ Không truy xuất được: ${esc(e.message)}</div>`; }
  };
  $("t_back").onclick = () => { setActiveTraceBtn("t_back"); $("t_record").innerHTML = "";
    return traceGuard(async () => renderTree(await GET("/trace/backward?code=" + encodeURIComponent(code())), "Truy ngược")); };
  $("t_fwd").onclick = () => { setActiveTraceBtn("t_fwd"); $("t_record").innerHTML = "";
    return traceGuard(async () => renderTree(await GET("/trace/forward?code=" + encodeURIComponent(code())), "Truy xuôi xuất")); };
  $("t_recall").onclick = () => { setActiveTraceBtn("t_recall"); $("t_record").innerHTML = "";
    return traceGuard(async () => {
    const r = await GET("/trace/recall?code=" + encodeURIComponent(code()));
    $("t_out").innerHTML = `<h2>Recall: ${r.affected_count} lô/mẻ bị ảnh hưởng <span class="muted">(${r.elapsed_ms} ms)</span></h2>
      <table><thead><tr><th>Loại</th><th>Mã</th></tr></thead><tbody>${r.affected.map(a => `<tr><td>${a.type}</td><td><code class="k">${esc(a.code)}</code></td></tr>`).join("") ||
      '<tr><td colspan=2 class="muted">Không có lô nào bị ảnh hưởng.</td></tr>'}</tbody></table>`;
  }); };
  $("t_record_btn").onclick = () => {
    setActiveTraceBtn("t_record_btn");
    $("t_record").innerHTML = "";
    return traceGuard(async () => renderLotRecord(await GET("/brewing/lot-record?code=" + encodeURIComponent(code()))));
  };
  $("t_fwd_brew").onclick = () => guard(async () => {
    setActiveTraceBtn("t_fwd_brew");
    const brewId = $("t_brew_sel").value;
    if (!brewId) { $("t_out").innerHTML = `<div class="muted">⚠ Chưa chọn lô nấu.</div>`; return; }
    $("t_record").innerHTML = "";
    try {
      const data = await GET("/brewing/brew-forward-record?brew_id=" + encodeURIComponent(brewId));
      renderTree(data.tree, `Truy xuôi theo nấu — ${esc(data.root.code)}`);
      renderLotRecord(data, { title: `🍺 Truy xuôi theo nấu — ${esc(data.root.code)}`, showLots: false });
    } catch (e) { $("t_out").innerHTML = `<div class="muted">⚠ Không truy xuất được: ${esc(e.message)}</div>`; }
  });
};

function qcStatusTable(status) {
  if (!status || !status.required.length) return `<div class="muted">Không có chỉ tiêu.</div>`;
  const byCode = Object.fromEntries(status.recorded.map(r => [r.parameter, r]));
  const rows = status.required.map(p => {
    const r = byCode[p.code];
    const spec = (p.lsl != null || p.usl != null) ? `${p.lsl ?? ""}–${p.usl ?? ""}` : (p.target ?? "—");
    const result = !r ? '<span class="qc-pill muted">Chưa ghi</span>'
      : (r.status === "fail" ? '<span class="qc-pill err">Không đạt</span>' : '<span class="qc-pill ok">Đạt</span>');
    return `<tr><td>${esc(p.name)}</td><td>${esc(p.unit || "")}</td><td>${esc(String(spec))}</td>
      <td>${r ? r.value : "—"}</td><td>${result}</td></tr>`;
  }).join("");
  return `<table><thead><tr><th>Chỉ tiêu</th><th>ĐVT</th><th>Giới hạn</th><th>Giá trị</th><th>Kết quả</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <div class="muted" style="font-size:12px">${status.can_release ? "✅ Đạt đủ chỉ tiêu bắt buộc" :
      status.pending.length ? `⚠ còn thiếu ${status.pending.length} chỉ tiêu` : "❌ có chỉ tiêu FAIL"}</div>`;
}

const periodLine = (start, end) => `<div class="muted" style="font-size:12px">🕒 Bắt đầu: ${start ? fmt(start) : "—"} — Kết thúc: ${end ? fmt(end) : "đang thực hiện"}</div>`;
function renderLotRecord(data, opts = {}) {
  const title = opts.title || `📄 Hồ sơ điện tử — ${esc(data.root.code)}`;
  const showLots = opts.showLots !== false;
  const nvlRows = (data.lots || []).map(l => `<tr><td class="code">${esc(l.lot_code)}</td>
    <td>${esc(l.material_name || l.material_code || "")}</td><td>${l.quantity} ${esc(l.uom)}</td>
    <td>${badge(l.status)}</td>
    <td>${l.qc.required.length ? (l.qc.can_release ? '<span class="qc-pill ok">Đạt</span>' : '<span class="qc-pill err">⚠ thiếu/fail</span>')
      : '<span class="qc-pill muted">Không có chỉ tiêu</span>'}</td></tr>`).join("")
    || `<tr><td colspan=5 class="muted">Không có lô NVL nào trong chuỗi này.</td></tr>`;

  const nauBlock = data.brew_batches.map(b => `
    <div class="panel" style="margin-top:8px">
      <h3>Mẻ ${esc(b.batch_code)} <span class="muted">(mã nấu ${esc(b.brew_code || "—")} · Lệnh nấu ${esc(b.brew_order_code || "—")})</span></h3>
      ${periodLine(b.started_at, b.ended_at)}
      <h4>Nguyên vật liệu dùng cho mẻ</h4>
      <table><thead><tr><th>Vật tư</th><th>Lô PM</th><th>Ngày lô</th><th>FIFO</th><th>SL</th><th>ĐVT</th></tr></thead>
        <tbody>${b.materials.map(m => `<tr><td>${esc(m.material_name)}</td><td>${esc(m.lot_pm || "")}</td>
          <td class="muted">${m.lot_date ? fmt(m.lot_date) : "—"}</td><td>${fifoBadgeHtml(m.fifo_ok)}</td>
          <td>${m.quantity}</td><td>${esc(m.uom)}</td></tr>`).join("") ||
          '<tr><td colspan=6 class="muted">Chưa khai báo NVL.</td></tr>'}</tbody></table>
      <h4>Chỉ tiêu Nấu</h4>${qcStatusTable(b.qc)}
      <h4>Ghi chép nấu (đầy đủ)</h4>
      ${BF_SECTIONS.map(sec => `<div style="margin-bottom:10px"><b>${esc(sec.title)}</b>
        ${_bfPrintSectionBody(sec, b.process_log)}</div>`).join("")}
    </div>`).join("") || `<div class="muted">Không có mẻ nấu nào trong chuỗi này.</div>`;

  const lenmenBlock = data.ferments.map(f => `
    <div class="panel" style="margin-top:8px">
      <h3>Lô LM ${esc(f.lm_code)} <span class="muted">(tank ${esc(f.tank_lm)})</span></h3>
      ${periodLine(f.started_at, f.ended_at)}
      <h4>Lên men chính</h4>${qcStatusTable(f.qc.len_men_chinh)}
      <h4>Lên men phụ</h4>${qcStatusTable(f.qc.len_men_phu)}
      <h4>Biểu đồ theo dõi lên men</h4>
      ${(f.readings && f.readings.length) ? _flChartHtml(f.readings) : '<div class="muted">Chưa có số liệu ghi chép hàng ngày.</div>'}
    </div>`).join("") || `<div class="muted">Không có lô lên men nào trong chuỗi này.</div>`;

  const locBlock = data.filters.map(f => `
    <div class="panel" style="margin-top:8px">
      <h3>Mã lọc ${esc(f.filter_code)} <span class="muted">(mã nấu ${esc(f.brew_code || "—")} · Lệnh lọc ${esc(f.filter_master_order_code || f.filter_order_code || "—")})</span></h3>
      ${periodLine(f.started_at, f.ended_at)}
      ${f.is_refilter ? `<div class="muted" style="color:var(--red)">⚠ Lọc lại từ tank BBT <b>${esc(f.refilter_source_bbt_code)}</b> — lý do: ${esc(f.refilter_reason || "—")}</div>` : ""}
      ${qcStatusTable(f.qc)}
      <h4>Nguyên vật liệu lọc</h4>
      <table><thead><tr><th>Nguyên liệu</th><th>Lô PM</th><th>Ngày lô</th><th>FIFO</th><th>SL</th><th>ĐVT</th></tr></thead>
        <tbody>${(f.materials || []).map(m => `<tr><td>${esc(m.material_name)}</td><td>${esc(m.lot_pm || "")}</td>
          <td class="muted">${m.lot_date ? fmt(m.lot_date) : "—"}</td><td>${fifoBadgeHtml(m.fifo_ok)}</td>
          <td>${m.quantity}</td><td>${esc(m.uom)}</td></tr>`).join("") ||
          '<tr><td colspan=6 class="muted">Chưa ghi nguyên liệu nào.</td></tr>'}</tbody></table>
    </div>`).join("") || `<div class="muted">Không có bản ghi lọc nào trong chuỗi này.</div>`;

  const chietBlock = data.bottles.map(b => `
    <div class="panel" style="margin-top:8px">
      <h3>Mã chiết ${esc(b.bottle_code)} <span class="muted">(số lô bia ${esc(b.lot_no || "—")})</span></h3>
      ${periodLine(b.started_at, b.ended_at)}
      <h4>Nguyên vật liệu chiết</h4>
      <table><thead><tr><th>Nguyên liệu</th><th>Lô PM</th><th>Ngày lô</th><th>FIFO</th><th>SL</th><th>ĐVT</th></tr></thead>
        <tbody>${(b.materials || []).map(m => `<tr><td>${esc(m.material_name)}</td><td>${esc(m.lot_pm || "")}</td>
          <td class="muted">${m.lot_date ? fmt(m.lot_date) : "—"}</td><td>${fifoBadgeHtml(m.fifo_ok)}</td>
          <td>${m.quantity}</td><td>${esc(m.uom)}</td></tr>`).join("") ||
          '<tr><td colspan=6 class="muted">Chưa ghi nguyên liệu nào.</td></tr>'}</tbody></table>
      <h4>Thành phẩm</h4>${qcStatusTable(b.qc.thanh_pham)}
    </div>`).join("") || `<div class="muted">Không có bản ghi chiết nào trong chuỗi này.</div>`;

  let n = 1;
  const lotsSection = showLots ? `<div class="panel"><h3>${n++}. Nguyên vật liệu</h3>
      <table><thead><tr><th>Mã lô</th><th>Vật tư</th><th>SL</th><th>Trạng thái</th><th>Chỉ tiêu</th></tr></thead>
      <tbody>${nvlRows}</tbody></table></div>` : "";
  $("t_record").innerHTML = `
    <div class="panel"><h2>${title}</h2></div>
    ${lotsSection}
    <div class="panel"><h3>${n++}. Mẻ nấu</h3>${nauBlock}</div>
    <div class="panel"><h3>${n++}. Lên men</h3>${lenmenBlock}</div>
    <div class="panel"><h3>${n++}. Lọc</h3>${locBlock}</div>
    <div class="panel"><h3>${n++}. Chiết</h3>${chietBlock}</div>`;
}
const TRACE_NODE_ICON = {
  lot: "📦", batch: "🍺", brew_batch: "🍺", brew: "🍺",
  ferment: "🛢️", filter: "🧪", bottle: "🥫", finished_goods_unit: "📦", ship_to: "🏬",
  shipment_group: "🚚", stock_group: "🏠",
};
// Nhãn LOẠI của node (khác với n.relation — xem renderTree bên dưới).
const TRACE_NODE_LABEL = {
  lot: "Lô NVL", batch: "Mẻ", brew_batch: "Mẻ nấu", brew: "Mã nấu",
  ferment: "Lô lên men", filter: "Mã lọc", bottle: "Mã chiết",
  finished_goods_unit: "Đơn vị TP", ship_to: "Nơi xuất",
  shipment_group: "Đã xuất", stock_group: "Còn tồn kho",
};
const SHIPMENT_TYPE_LABEL = { promo: "Khuyến mại", return: "Đổi trả", normal: "Thường" };
function qcPill(q) {
  let text, cls;
  if (q.required_count === 0) { text = "không có chỉ tiêu"; cls = "muted"; }
  else if (q.can_release) { text = `✅ đạt (${q.recorded_count}/${q.required_count})`; cls = "ok"; }
  else if (q.pending.length) { text = `⚠ thiếu ${q.pending.length} chỉ tiêu`; cls = "err"; }
  else { text = "❌ có chỉ tiêu FAIL"; cls = "err"; }
  return `<span class="qc-pill ${cls}" title="${esc(q.pending.join(", "))}">${esc(q.label)}: ${text}</span>`;
}
function renderTree(tree, title) {
  // n.relation là bước SINH RA NODE CHA từ node này (VD FL-20601 [Mã lọc] → chiết nghĩa là
  // FL-20601 được dùng ở bước "chiết" để tạo ra bản ghi chiết cha) — KHÔNG PHẢI loại của
  // chính node này (loại thật xem TRACE_NODE_LABEL[n.type]/icon), nên hiển thị tách riêng
  // kèm mũi tên "→" để khỏi nhầm là nhãn loại node.
  // Con kiểu "lot" (NVL tiêu thụ) không có con riêng và thường có RẤT NHIỀU dòng lặp lại
  // (1 dòng/lần cấp liệu) — hiện dạng cây từng node như trước sẽ rất dài, nên gộp thành 1
  // bảng compact (mã NVL/số lượng/chỉ tiêu) thay vì đệ quy từng box; các loại con khác (ferment,
  // filter, bottle...) vẫn hiện đệ quy như cũ.
  const lotTable = (lots) => `<table class="nvl-table"><thead><tr>
      <th>Mã nguyên vật liệu</th><th>Số lượng</th><th>Chỉ tiêu</th></tr></thead>
    <tbody>${lots.map(l => `<tr><td>${esc(l.material_label || "")}
        <span class="muted" style="font-size:11px">(lô ${esc(l.code)})</span></td>
      <td>${l.quantity != null ? l.quantity : ""} ${esc(l.uom || "")}</td>
      <td>${(l.qc || []).map(qcPill).join("") || '<span class="muted">—</span>'}</td></tr>`).join("")}</tbody></table>`;
  const node = (n) => {
    if (n.type === "shipment_group" || n.type === "stock_group") {
      return `<div class="node">${TRACE_NODE_ICON[n.type]}
      <span class="muted" style="font-size:11px">${esc(TRACE_NODE_LABEL[n.type])}</span>
      <b>${n.count} ${n.unit_type === "keg" ? "keg" : n.unit_type === "lon" ? "lon" : "vỉ"}</b>
      <span class="muted">(tổng ${n.quantity})</span>
      ${n.type === "shipment_group" ? `
        <div class="muted" style="font-size:12px;margin-top:2px">
          🏬 ${esc(n.ship_to_name || n.ship_to_code || "—")} (${esc(n.ship_to_code || "")})
          · 📄 ${esc(n.shipment_code)} · ${SHIPMENT_TYPE_LABEL[n.shipment_type] || n.shipment_type}
          · 🚚 ${esc(n.driver_name || "—")}${n.vehicle_plate ? " — " + esc(n.vehicle_plate) : ""}
          · 🕒 ${n.shipped_at ? fmt(n.shipped_at) : "—"}
          ${n.from_location ? " · từ " + esc(n.from_location) : ""}
        </div>` : `<div class="muted" style="font-size:12px;margin-top:2px">Chưa xuất kho — vẫn còn tại kho thành phẩm.</div>`}
      </div>`;
    }
    const kids = n.children || [];
    const lotKids = kids.filter(c => c.type === "lot");
    const otherKids = kids.filter(c => c.type !== "lot");
    return `<div class="node">${TRACE_NODE_ICON[n.type] || "📦"}
    <span class="muted" style="font-size:11px">${esc(TRACE_NODE_LABEL[n.type] || "")}</span>
    <code class="k">${esc(n.code)}</code>
    ${n.relation ? `<span class="rel" title="Dùng ở bước &quot;${esc(n.relation)}&quot; để tạo ra bản ghi cha bên trên">→ ${esc(n.relation)}${n.quantity ? " " + n.quantity + (n.uom || "") : ""}</span>` : ""}
    ${n.period ? periodLine(n.period.start, n.period.end) : ""}
    ${(n.qc || []).length ? `<div class="qc-pills">${n.qc.map(qcPill).join("")}</div>` : ""}
    ${lotKids.length ? lotTable(lotKids) : ""}
    ${otherKids.map(node).join("")}</div>`;
  };
  $("t_out").innerHTML = `<h2>${title}</h2><div class="tree">${node(tree)}</div>`;
}

// ================= AUDIT =================
VIEWS.audit = async function () {
  $("view-audit").innerHTML = `
    <div class="panel"><h2>Audit trail (append-only)</h2>
      <div class="row">
        <div class="field"><label>Lọc theo entity_id (tùy chọn)</label><input id="au_entity" size="40" /></div>
        <button class="btn sec" id="au_load">Tải</button>
      </div>
      <input class="searchbox" data-tbl="t_audit" placeholder="Tìm theo đối tượng, hành động, người, vai trò..."/>
      <div id="au_table" style="margin-top:6px"></div>
    </div>`;
  const load = () => guard(async () => {
    const q = $("au_entity").value ? "?entity_id=" + encodeURIComponent($("au_entity").value) : "?limit=200";
    $("au_table").innerHTML = tableAudit(await GET("/audit" + q), "t_audit");
    wireSearch(); wirePaginate("t_audit", 10);
  });
  $("au_load").onclick = load; load();
};
function tableAudit(rows, tableId) {
  return `<table${tableId ? ` id="${tableId}"` : ""}><thead><tr><th>#</th><th>Đối tượng</th><th>Hành động</th><th>Người</th><th>Vai trò</th><th>Lúc</th></tr></thead>
    <tbody>${rows.map(r => `<tr><td class="muted">${r.seq}</td><td>${esc(r.entity_type)}</td>
      <td>${esc(r.action)}</td><td>${esc(r.actor)}</td><td class="muted">${esc(r.actor_role || "")}</td>
      <td class="muted">${fmt(r.ts)}</td></tr>`).join("") || '<tr><td colspan=6 class="muted">Trống</td></tr>'}</tbody></table>`;
}

// ================= helpers cho module mới =================
const SUB = {};  // sub-section đang chọn theo view
function subnav(view, sections, current) {
  return `<div class="subnav">${sections.map(s =>
    `<button class="${s.key === current ? "active" : ""}" data-sub="${view}:${s.key}">${esc(s.label)}</button>`
  ).join("")}</div>`;
}
function wireSubnav(view) {
  document.querySelectorAll(`[data-sub^="${view}:"]`).forEach(b => b.onclick = () => {
    SUB[view] = b.dataset.sub.split(":")[1]; render(view);
  });
}
async function lotOptions(db, onlyAvailable) {
  const lots = await GET("/lots");
  return lots.filter(l => !onlyAvailable || l.status === "available")
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))   // FIFO: nhập trước hiện trước
    .map(l => `<option value="${l.lot_id}">${esc(l.lot_code)} (${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})${l.status === "on_hold" ? " — CHỜ DUYỆT QC" : ""}</option>`).join("");
}

// ================= KHO NVL =================
// Modal xem TOÀN BỘ mã lô của 1 vật tư — tách khỏi bảng Xem tồn kho vì hiển thị thẳng
// trong ô "Mã lô" không chịu được khi vật tư có hàng trăm/nghìn lô (xem "+N lô khác").
function openMaterialLotsModal(matLabel, lots) {
  const sorted = lots.slice().sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  modal(`<h3>Toàn bộ lô — <code class="k">${esc(matLabel)}</code> <span class="muted">(${sorted.length} lô)</span></h3>
    <input class="searchbox" data-tbl="t_matlots" placeholder="Tìm mã lô/vị trí..." style="margin-bottom:8px"/>
    <div class="tablewrap"><table id="t_matlots"><thead><tr><th>Mã lô</th><th>Số lượng</th><th>ĐVT</th><th>Trạng thái</th><th>Vị trí</th><th>Ngày nhập</th></tr></thead>
      <tbody>${sorted.map(l => `<tr><td><code class="k">${esc(l.lot_code)}</code></td><td>${l.quantity}</td><td>${esc(l.uom)}</td>
        <td>${l.status === "on_hold" ? badge("on_hold") + "Chờ QC" : badge("available") + "Sẵn có"}</td>
        <td class="muted">${esc(l.location || "")}</td><td class="muted">${fmt(l.created_at)}</td></tr>`).join("") ||
        '<tr><td colspan=6 class="muted">Không có lô nào.</td></tr>'}</tbody></table></div>`);
  delete _pagerState["t_matlots"];
  wireSearch();
  wirePaginate("t_matlots", 10);
}

// Kho NVL tách thành 2 module riêng theo đúng người quản lý thực tế: Kho công ty (thủ kho
// công ty — nhập NVL, xuất/hoàn/chuyển kho, xuất cho phân xưởng theo đề nghị, báo cáo/kiểm kê)
// và Kho phân xưởng (chỉ xem tồn của mình + gửi đề nghị nhận thêm khi cần) — mỗi module có
// view/permission riêng (xem seed.py: thukho -> warehouse_kc, truongca/vanhanh -> warehouse_px)
// nên phân quyền vào chỉ thấy đúng module của vai trò mình, không thấy module còn lại.
VIEWS.warehouse_kc = async function () {
  const sec = SUB.warehouse_kc || "ton";
  const sections = [
    { key: "ton", label: "Xem tồn kho" }, { key: "the", label: "Thẻ kho" },
    { key: "han", label: "Hạn sử dụng" }, { key: "bc", label: "BC nhập-xuất-tồn" },
    { key: "giao", label: "Nhập / Xuất / Hoàn / Sang ngang" },
    { key: "kc", label: "Danh sách lô (FIFO)" },
    { key: "kk", label: "Kiểm kê định kỳ" }, { key: "min", label: "📉 Tồn tối thiểu" },
  ];
  let body = "";
  let lotsByMaterial = {};
  const LOT_CELL_MAX = 3;
  const lotChip = (l) => `<code class="k">${esc(l.lot_code)}</code> (${l.quantity}${l.uom}${l.status === "on_hold" ? ", CHỜ QC" : ""})`;
  if (sec === "ton") {
    const [stock, allLots] = await Promise.all([
      GET("/warehouse/stock?location=" + encodeURIComponent("Kho công ty")), GET("/lots")]);
    allLots.filter(l => l.quantity > 0 && !/phân xưởng/i.test(l.location || "")).forEach(l => {
      (lotsByMaterial[l.material_id] = lotsByMaterial[l.material_id] || []).push(l);
    });
    const lowCount = stock.filter(s => s.low_stock).length;
    body = `<div class="panel"><h2>Tồn kho hiện tại — Kho công ty</h2>
      ${lowCount ? `<div class="muted" style="color:var(--red);margin-bottom:8px">⚠ ${lowCount} vật tư đang dưới tồn tối thiểu.</div>` : ""}
      <input class="searchbox" data-tbl="t_ton" placeholder="Tìm mã/tên vật tư..." style="margin-bottom:8px"/>
      <div class="tablewrap"><table id="t_ton"><thead><tr><th>Mã VT</th><th>Tên</th><th>Nhóm</th><th>Mã lô</th><th>Tồn</th><th>ĐVT</th><th>Tồn tối thiểu</th></tr></thead>
      <tbody>${stock.map(s => { const matLots = (lotsByMaterial[s.material_id] || [])
          .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
        const shown = matLots.slice(0, LOT_CELL_MAX);
        const rest = matLots.length - shown.length;
        const lotCell = shown.map(lotChip).join(", ") +
          (rest > 0 ? ` <button type="button" class="btn sm sec" data-viewlots="${esc(s.material_id)}" data-matlabel="${esc(s.material_code)} — ${esc(s.material_name)}">+${rest} lô khác</button>` : "");
        return `<tr${s.low_stock ? ' style="background:color-mix(in srgb, var(--red) 10%, transparent)"' : ""}><td><code class="k">${esc(s.material_code)}</code></td><td>${esc(s.material_name)}</td>
        <td class="muted">${esc(s.category || "")}</td>
        <td class="muted">${lotCell || "—"}</td>
        <td>${s.on_hand}${s.low_stock ? ' <span style="color:var(--red)" title="Dưới tồn tối thiểu">⚠</span>' : ""}</td><td>${s.uom}</td>
        <td class="muted">${s.stock_min ?? "—"}</td></tr>`; }).join("") ||
        '<tr><td colspan=7 class="muted">Không có tồn kho.</td></tr>'}</tbody></table></div></div>`;
  } else if (sec === "the") {
    const mats = await GET("/materials");
    const opts = mats.map(m => `<option value="${m.material_id}">${esc(m.code)} — ${esc(m.name)}</option>`).join("");
    body = `<div class="panel"><h2>Thẻ kho</h2>
      <div class="row"><div class="field"><label>Vật tư</label><select id="wc_mat">${opts}</select></div>
        <button class="btn" id="wc_load">Xem thẻ</button></div>
      <div id="wc_table"><div class="muted">Chọn vật tư.</div></div></div>`;
  } else if (sec === "han") {
    const exp = await GET("/warehouse/expiry");
    body = `<div class="panel"><h2>Hạn sử dụng</h2>
      <table><thead><tr><th>Vật tư</th><th>Lô</th><th>SL</th><th>Hạn</th><th>Còn (ngày)</th><th>Trạng thái</th><th>Vị trí</th></tr></thead>
      <tbody>${exp.map(e => `<tr><td>${e.material_code ? `<code class="k">${esc(e.material_code)}</code> ${esc(e.material_name || "")}` : "—"}</td>
        <td><code class="k">${esc(e.lot_code)}</code></td><td>${e.quantity} ${e.uom}</td>
        <td class="muted">${fmt(e.expiry)}</td><td>${e.days_left}</td><td>${badge(e.status)}</td><td class="muted">${esc(e.location || "")}</td></tr>`).join("") || '<tr><td colspan=7 class="muted">Không có lô có hạn dùng.</td></tr>'}</tbody></table></div>`;
  } else if (sec === "bc") {
    const rep = await GET("/warehouse/report?days=60&location=" + encodeURIComponent("Kho công ty"));
    body = `<div class="panel"><h2>Báo cáo nhập-xuất-tồn (60 ngày) — Kho công ty</h2>
      <table><thead><tr><th>Mã VT</th><th>Tên</th><th>Nhập</th><th>Xuất</th><th>Tồn cuối</th><th>ĐVT</th></tr></thead>
      <tbody>${rep.map(r => `<tr><td><code class="k">${esc(r.material_code)}</code></td><td>${esc(r.material_name)}</td>
        <td style="color:var(--green)">${r.received}</td><td style="color:var(--orange)">${r.issued}</td>
        <td>${r.on_hand}</td><td>${r.uom}</td></tr>`).join("") || '<tr><td colspan=6 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div>`;
  } else if (sec === "giao") {
    const [lotsAvail, mats, allLots, allRequestsFull, freeIssues, transfers, supplierReturns, suppliers, receipts] = await Promise.all([
      lotOptions(null, false), GET("/materials"), GET("/lots"), GET("/warehouse/requests"),
      GET("/warehouse/movements?movement_type=issue&mode=tu_do"),
      GET("/warehouse/movements?movement_type=transfer&mode=dieu_chuyen"),
      GET("/warehouse/movements?movement_type=issue&mode=tra_ncc"),
      GET("/suppliers"), GET("/warehouse/movements?movement_type=receipt"),
    ]);
    // Giống hệt cách "Đề nghị nhận kho" tách pending/done: 1 phiếu còn dòng pending nào thì vẫn
    // nằm ở khối "đang chờ" (dù có dòng đã xuất khác) — chỉ rơi xuống "Sổ xuất theo đề nghị" khi
    // MỌI dòng đã được xử lý xong (fulfilled/rejected/cancelled), tránh phiếu xuất hiện 2 nơi.
    const allRequests = allRequestsFull.filter(r => r.lines.some(l => l.status === "pending"));
    const doneRequests = allRequestsFull.filter(r => !r.lines.some(l => l.status === "pending"));
    // Xuất tự do có thể thực hiện ở cả kho công ty lẫn kho phân xưởng (mode="tu_do" dùng chung) —
    // tách theo location_from để mỗi nơi chỉ thấy đúng lịch sử của mình.
    const freeIssuesKc = freeIssues.filter(m => !/phân xưởng/i.test(m.location_from || ""));
    const matItemsGiao = mats.map(m => ({ value: m.material_id, label: `${m.code} — ${m.name}`, uom: m.uom }));
    const matByIdGiao = Object.fromEntries(mats.map(m => [m.material_id, m]));
    const lotByIdGiao = Object.fromEntries(allLots.map(l => [l.lot_id, l]));
    const supplierByIdGiao = Object.fromEntries(suppliers.map(s => [s.supplier_id, s]));
    const supplierOpts = `<option value="">(không chọn)</option>` +
      suppliers.map(s => `<option value="${s.supplier_id}">${esc(s.code)} — ${esc(s.name)}</option>`).join("");
    const pending = allLots.filter(l => l.status === "on_hold");
    const canFulfillGiao = _hasPerm("warehouse.issue");
    const isAdminGiao = CURRENT_USER && CURRENT_USER.role === "admin";
    // Mỗi lần vào lại tab "giao" (kể cả sau 1 thao tác) là 1 lượt xem mới — reset về trang đầu
    // (10 dòng) cho gọn; dữ liệu mới nhất (nếu vừa thao tác) luôn nằm trong 10 dòng đầu.
    WH_CACHE.matById = matByIdGiao;
    WH_CACHE.matItems = matItemsGiao;
    WH_CACHE.tu_do = freeIssuesKc;
    WH_CACHE.dieu_chuyen = transfers;
    WH_CACHE.tra_ncc = supplierReturns;
    WH_CACHE.xuat_theo_de_nghi = doneRequests;
    WH_CACHE.lotById = lotByIdGiao;
    WH_CACHE.allLots = allLots;
    WH_CACHE.canFulfill = canFulfillGiao;
    Object.keys(WH_HIST_VISIBLE).forEach(k => { WH_HIST_VISIBLE[k] = WH_HIST_PAGE; });
    const workshopLotOpts = allLots.filter(l => l.quantity > 0 && /phân xưởng/i.test(l.location || ""))
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
      .map(l => `<option value="${l.lot_id}">${esc(l.lot_code)} (${l.quantity}${l.uom}, tại ${esc(l.location)})</option>`).join("") ||
      `<option value="">(không có lô nào ở kho phân xưởng)</option>`;
    const receiptRows = receipts.slice().sort((a, b) => new Date(b.ts) - new Date(a.ts)).map(m => {
      const mat = m.material_id ? matByIdGiao[m.material_id] : null;
      const lot = m.lot_id ? lotByIdGiao[m.lot_id] : null;
      const sup = lot && lot.supplier_id ? supplierByIdGiao[lot.supplier_id] : null;
      return `<tr>
        <td class="muted">${fmt(m.ts)}</td>
        <td><code class="k">${esc(m.lot_code || "")}</code></td>
        <td class="muted">${esc(lot ? lot.kcs_lot_no || "" : "")}</td>
        <td>${esc(mat ? mat.code : m.material_id || "—")}</td>
        <td>${m.quantity} ${esc(m.uom)}</td>
        <td class="muted">${esc(sup ? sup.name : "")}</td>
        <td class="muted">${esc(m.reason || "")}</td>
        <td class="muted">${esc(m.actor || "")}</td></tr>`;
    }).join("") || `<tr><td colspan="8" class="muted">Chưa có phiếu nhập kho nào.</td></tr>`;
    body = `<div class="split">
      <div class="panel"><h2>Nhập kho</h2>
        <div class="row"><div class="field"><label>Ngày nhập</label><input id="rc_dt" type="datetime-local" value="${toDTLocal(new Date())}" max="${toDTLocal(new Date())}" min="${toDTLocal(new Date(Date.now() - 15 * 86400000))}"/></div>
          <div class="field" style="position:relative"><label>Nguyên liệu</label>
            <input type="text" id="rc_mat_txt" autocomplete="off" placeholder="Tìm mã/tên nguyên liệu..." value="${esc(matItemsGiao[0]?.label || "")}"/>
            <input type="hidden" id="rc_mat" value="${esc(matItemsGiao[0]?.value || "")}"/></div>
          <div class="field"><label>Nhà CC</label><select id="rc_supplier">${supplierOpts}</select></div></div>
        <div class="row"><div class="field"><label>Số lượng</label><input id="rc_qty" type="number" value="500"/></div>
          <div class="field"><label>ĐVT</label><input id="rc_uom" value="${esc(matItemsGiao[0]?.uom || "")}" size="4" readonly title="Lấy tự động từ danh mục nguyên liệu — không sửa được"/></div>
          <div class="field"><label>Đơn giá</label><input id="rc_price" type="number" placeholder="(tuỳ chọn)"/></div>
          <div class="field"><label>Hạn dùng</label><input id="rc_exp" type="date"/></div></div>
        <div class="row"><div class="field" style="flex:1"><label>Diễn giải</label><input id="rc_note" placeholder="(tuỳ chọn)"/></div>
          <button class="btn" id="rc_do" style="align-self:flex-end">Nhập</button></div>
        <div class="muted" style="margin-top:4px">Mã lô do hệ thống tự sinh (tăng dần theo năm) — Số lô KCS do bộ phận KCS tự điền khi khai báo chỉ tiêu chất lượng.</div>
        <input class="searchbox" data-tbl="rc_hist" placeholder="Tìm mã lô/nguyên liệu/nhà cung cấp..." style="margin-top:12px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="rc_hist">
          <thead><tr><th>Ngày nhập</th><th>Mã lô</th><th>Số lô KCS</th><th>Nguyên liệu</th><th>Số lượng</th><th>Nhà cung cấp</th><th>Diễn giải</th><th>Người nhập</th></tr></thead>
          <tbody>${receiptRows}</tbody>
        </table></div>
      </div>

      <div class="panel"><h2>Xuất theo số phiếu đề nghị <span class="muted">(${allRequests.length} phiếu đang chờ)</span></h2>
        <div class="muted" style="margin-bottom:6px">Mỗi phiếu hiện đầy đủ danh mục vật tư đã đề nghị — bấm "Duyệt cả phiếu" để xuất
          toàn bộ 1 lần (SL đề nghị đã được chặn không vượt tồn kho công ty từ lúc tạo phiếu), hoặc xử lý riêng từng dòng.</div>
        <input class="searchbox" id="xtdn_search" placeholder="Tìm theo số phiếu, người tạo, ghi chú, vật tư..." style="margin-bottom:8px;width:100%"/>
        <div id="xtdn_block">
          ${allRequests.length
            ? allRequests.map(r => requestBlockHtml(r, matByIdGiao, lotByIdGiao, canFulfillGiao, true, allLots)).join("")
            : '<div class="muted">Không có phiếu đề nghị nào đang chờ.</div>'}
        </div>
        ${movementHistoryBlockHtml("xuat_theo_de_nghi")}
      </div>

      <div class="panel"><h2>Xuất tự do</h2>
        <div class="muted" style="margin-bottom:6px">Xuất không theo phiếu đề nghị (vd. dùng nội bộ, thử nghiệm). Lô đang
          "CHỜ DUYỆT QC" sẽ bị chặn xuất. Có thể "Hoàn lại" nếu xuất nhầm — vật tư trở về đúng lô, tránh thất thoát.</div>
        ${isAdminGiao
          ? `<div class="row"><div class="field"><label>Lô</label><select id="xt_lot">${lotsAvail}</select></div>
          <div class="field"><label>SL</label><input id="xt_qty" type="number" value="50"/></div>
          <div class="field" style="flex:1"><label>Lý do (tuỳ chọn)</label><input id="xt_reason" placeholder="(tuỳ chọn)"/></div>
          <button class="btn sec" id="xt_do" style="align-self:flex-end">Xuất tự do</button></div>`
          : '<div class="muted">Chỉ tài khoản Admin mới được thực hiện xuất tự do.</div>'}
        ${movementHistoryBlockHtml("tu_do")}
      </div>

      <div class="panel"><h2>Điều chuyển về kho công ty</h2>
        <div class="muted" style="margin-bottom:6px">Chỉ điều chuyển được lô đang ở <b>Kho phân xưởng</b> — chiều ngược lại
          của "Xuất theo đề nghị" (khi nhận thừa/cần trả lại kho chính).</div>
        <div class="row"><div class="field"><label>Lô (đang ở kho phân xưởng)</label><select id="dc_lot">${workshopLotOpts}</select></div>
          <div class="field"><label>SL</label><input id="dc_qty" type="number" value="50"/></div>
          <div class="field" style="flex:1"><label>Lý do (tuỳ chọn)</label><input id="dc_reason" placeholder="(tuỳ chọn)"/></div>
          <button class="btn sec" id="dc_do" style="align-self:flex-end">Điều chuyển</button></div>
        ${movementHistoryBlockHtml("dieu_chuyen")}
      </div>

      <div class="panel"><h2>Xuất trả nhà cung cấp</h2>
        <div class="muted" style="margin-bottom:6px">Chọn đúng lô vật tư hỏng/không đạt chỉ tiêu để trả lại nhà cung cấp — bắt buộc nêu lý do.</div>
        <div class="row"><div class="field"><label>Lô</label><select id="ncc_lot">${lotsAvail}</select></div>
          <div class="field"><label>SL</label><input id="ncc_qty" type="number" value="50"/></div>
          <div class="field" style="flex:1"><label>Lý do (bắt buộc)</label><input id="ncc_reason" placeholder="vd. hàng hỏng, không đạt chỉ tiêu"/></div>
          <button class="btn sec" id="ncc_do" style="align-self:flex-end">Xuất trả NCC</button></div>
        ${movementHistoryBlockHtml("tra_ncc")}
      </div>

      <div class="panel"><h2>🏁 Nhập tồn đầu</h2>
        <div class="muted" style="margin-bottom:6px">Nạp số dư tồn kho ban đầu khi triển khai hệ thống (không qua nhận
          hàng nhà cung cấp) — chọn đúng vị trí kho cần nạp.</div>
        <div class="row"><div class="field"><label>Mã lô</label><input id="ob_code" placeholder="MALT-..."/></div>
          <div class="field" style="position:relative"><label>Vật tư</label>
            <input type="text" id="ob_mat_txt" autocomplete="off" placeholder="Tìm mã/tên nguyên liệu..." value="${esc(matItemsGiao[0]?.label || "")}"/>
            <input type="hidden" id="ob_mat" value="${esc(matItemsGiao[0]?.value || "")}"/></div></div>
        <div class="row"><div class="field"><label>SL</label><input id="ob_qty" type="number" value="500"/></div>
          <div class="field"><label>ĐVT</label><input id="ob_uom" value="${esc(matItemsGiao[0]?.uom || "")}" size="4" readonly title="Lấy tự động từ danh mục nguyên liệu — không sửa được"/></div>
          <div class="field"><label>Vị trí kho</label><select id="ob_loc">
            <option value="Kho công ty">Kho công ty</option>
            <option value="Kho phân xưởng">Kho phân xưởng</option></select></div>
          <div class="field"><label>Hạn dùng</label><input id="ob_exp" type="date"/></div>
          <button class="btn" id="ob_do">Nhập tồn đầu</button></div></div>

      <div class="panel"><h2>🔬 Lô đang chờ KCS khai báo/duyệt chỉ tiêu chất lượng <span class="muted">(${pending.length})</span></h2>
        <div class="tablewrap"><table>
          <thead><tr><th>Lô</th><th>SL</th><th>Vị trí</th><th></th></tr></thead>
          <tbody>${pending.map(l => `<tr>
            <td><code class="k">${esc(l.lot_code)}</code>${badge("on_hold")}</td>
            <td>${l.quantity} ${l.uom}</td><td class="muted">${esc(l.location || "")}</td>
            <td><button class="btn sm sec" data-lotqc="${esc(l.lot_id)}">Xem trạng thái</button></td></tr>`).join("") ||
            '<tr><td colspan=4 class="muted">Không có lô nào đang chờ.</td></tr>'}</tbody>
        </table></div>
      </div></div>`;
  } else if (sec === "kc") {
    const [allLots, mats] = await Promise.all([GET("/lots"), GET("/materials")]);
    const matById = Object.fromEntries(mats.map(m => [m.material_id, m]));
    const rows = allLots.filter(l => !/phân xưởng/i.test(l.location || "") && l.quantity > 0)
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));   // FIFO: nhập trước hiện trước
    body = `<div class="panel"><h2>Danh sách lô kho công ty <span class="muted">(${rows.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Toàn bộ lô đang nằm ở kho công ty, sắp xếp nhập trước hiện trước (FIFO) để ưu tiên xuất/chuyển.</div>
      <input class="searchbox" data-tbl="t_kc" placeholder="Tìm mã lô/vật tư..." style="margin-bottom:8px"/>
      <div class="tablewrap"><table id="t_kc">
        <thead><tr><th>Lô</th><th>Vật tư</th><th>SL</th><th>Ngày giờ nhập</th><th>Vị trí</th><th>Trạng thái</th><th></th></tr></thead>
        <tbody>${rows.map(l => `<tr>
          <td><code class="k">${esc(l.lot_code)}</code></td>
          <td class="muted">${esc(matById[l.material_id] ? matById[l.material_id].code : l.material_id || "—")}</td>
          <td>${l.quantity} ${l.uom}</td>
          <td class="muted">${fmt(l.created_at)}</td>
          <td class="muted">${esc(l.location || "")}</td>
          <td>${badge(l.status)}</td>
          <td><button class="btn sm sec" data-lotqc="${esc(l.lot_id)}">Xem chỉ tiêu</button></td></tr>`).join("") ||
          `<tr><td colspan=7 class="muted">Chưa có lô nào ở kho công ty.</td></tr>`}</tbody>
      </table></div>
    </div>`;
  } else if (sec === "kk") {
    body = await renderStockCountSection();
  } else if (sec === "min") {
    body = await renderLowStockSection();
  }
  $("view-warehouse_kc").innerHTML = subnav("warehouse_kc", sections, sec) + body;
  wireSubnav("warehouse_kc");
  wireSearch();
  if (sec === "the") $("wc_load").onclick = () => guard(async () => {
    const card = await GET("/warehouse/card?material_id=" + $("wc_mat").value);
    $("wc_table").innerHTML = `<table><thead><tr><th>Thời gian</th><th>Loại</th><th>Lô</th><th>Nhập</th><th>Xuất</th><th>Tồn</th><th>Lý do</th></tr></thead>
      <tbody>${card.map(c => `<tr><td class="muted">${fmt(c.ts)}</td><td>${badge(c.type === "receipt" ? "available" : c.type === "issue" ? "on_hold" : "planned")}${c.type}</td>
        <td>${esc(c.lot_code || "")}</td><td style="color:var(--green)">${c.in || ""}</td><td style="color:var(--orange)">${c.out || ""}</td>
        <td><b>${c.balance}</b> ${c.uom}</td><td class="muted">${esc(c.reason || "")}</td></tr>`).join("") || '<tr><td colspan=7 class="muted">Chưa có giao dịch.</td></tr>'}</tbody></table>`;
  });
  if (sec === "giao") {
    wirePaginate("rc_hist", 10);
    wireSearchableSelect("rc_mat_txt", "rc_mat", WH_CACHE.matItems, (item) => { $("rc_uom").value = item.uom || ""; });
    wireSearchableSelect("ob_mat_txt", "ob_mat", WH_CACHE.matItems, (item) => { $("ob_uom").value = item.uom || ""; });
    $("rc_do").onclick = () => guard(async () => {
      const rcDtRaw = $("rc_dt").value;
      if (!rcDtRaw) throw new Error("Chọn ngày nhập.");
      const res = await POST("/warehouse/receive", { material_id: $("rc_mat").value,
        supplier_id: $("rc_supplier").value || null, unit_price: $("rc_price").value ? parseFloat($("rc_price").value) : null,
        quantity: parseFloat($("rc_qty").value), uom: $("rc_uom").value, received_at: new Date(rcDtRaw).toISOString(),
        expiry: $("rc_exp").value || null, reason: $("rc_note").value.trim() || "Nhập kho" });
      if (res.status === "on_hold") toast(`Đã nhập kho (mã lô ${res.lot_code}) — lô đang CHỜ khai báo & duyệt chỉ tiêu chất lượng`, "err");
      else toast(`Đã nhập kho (mã lô ${res.lot_code})`);
      render("warehouse_kc");
    });
    $("ob_do").onclick = () => guard(async () => {
      const res = await POST("/warehouse/receive", { lot_code: $("ob_code").value, material_id: $("ob_mat").value,
        quantity: parseFloat($("ob_qty").value), uom: $("ob_uom").value, location: $("ob_loc").value,
        expiry: $("ob_exp").value || null, reason: "Nhập tồn đầu" });
      if (res.status === "on_hold") toast("Đã nhập tồn đầu — lô đang CHỜ khai báo & duyệt chỉ tiêu chất lượng", "err");
      else toast(`Đã nhập tồn đầu tại ${$("ob_loc").value}`);
      render("warehouse_kc");
    });
    if ($("xt_do")) $("xt_do").onclick = () => guard(async () => {
      await POST("/warehouse/issue", { lot_id: $("xt_lot").value, quantity: parseFloat($("xt_qty").value),
        mode: "tu_do", reason: $("xt_reason").value.trim() || null });
      toast("Đã xuất tự do"); render("warehouse_kc");
    });
    $("dc_do").onclick = () => guard(async () => {
      if (!$("dc_lot").value) throw new Error("Không có lô nào đang ở kho phân xưởng để điều chuyển.");
      await POST("/warehouse/transfer-to-company", { lot_id: $("dc_lot").value, quantity: parseFloat($("dc_qty").value),
        reason: $("dc_reason").value.trim() || null });
      toast("Đã điều chuyển về kho công ty"); render("warehouse_kc");
    });
    $("ncc_do").onclick = () => guard(async () => {
      const reason = $("ncc_reason").value.trim();
      if (!reason) throw new Error("Phải nhập lý do trả nhà cung cấp.");
      await POST("/warehouse/return-to-supplier", { lot_id: $("ncc_lot").value, quantity: parseFloat($("ncc_qty").value), reason });
      toast("Đã xuất trả nhà cung cấp"); render("warehouse_kc");
    });
    Object.keys(WH_HIST_VISIBLE).forEach(wireMovementHistoryBlock);
    wireRequestBlockActions();
    wireCardSearch("xtdn_search", "#xtdn_block");
  }
  if (sec === "ton") {
    document.querySelectorAll("[data-viewlots]").forEach(b => b.onclick = () =>
      openMaterialLotsModal(b.dataset.matlabel, lotsByMaterial[b.dataset.viewlots] || []));
  }
  document.querySelectorAll("[data-lotqc]").forEach(b => b.onclick = () => openLotQcModal(b.dataset.lotqc, { editable: false }));
  if (sec === "kk") {
    $("kk_create").onclick = () => guard(async () => {
      await POST("/warehouse/counts", { location: $("kk_loc").value || null, note: $("kk_note").value.trim() || null });
      toast("Đã tạo phiếu kiểm kê"); render("warehouse_kc");
    });
    document.querySelectorAll("[data-viewcount]").forEach(b => b.onclick = () => openStockCountModal(b.dataset.viewcount));
    document.querySelectorAll("[data-approvecount]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Duyệt phiếu kiểm kê này? Xác nhận đã xem/đồng ý số liệu đã chốt — không đổi lại tồn kho, và sau khi duyệt sẽ không hoàn tác được nữa.")) return;
      await POST(`/warehouse/counts/${b.dataset.approvecount}/approve`);
      toast("Đã duyệt phiếu kiểm kê"); render("warehouse_kc");
    }));
    document.querySelectorAll("[data-undocount]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Hoàn tác phiếu kiểm kê này? Tồn kho sẽ trả về đúng số liệu hệ thống trước khi chốt, phiếu về lại trạng thái Nháp để sửa/chốt lại.")) return;
      await POST(`/warehouse/counts/${b.dataset.undocount}/undo`);
      toast("Đã hoàn tác phiếu kiểm kê"); render("warehouse_kc");
    }));
  }
};

// ================= KHO NVL — KHO PHÂN XƯỞNG =================
VIEWS.warehouse_px = async function () {
  const sec = SUB.warehouse_px || "px";
  const sections = [
    { key: "px", label: "Xem tồn kho" }, { key: "req", label: "Đề nghị nhận kho" },
    { key: "tudo", label: "Xuất tự do" }, { key: "nvlhist", label: "Lịch sử xuất dùng NVL" },
  ];
  let body = "";
  if (sec === "px") {
    const [allLots, mats] = await Promise.all([GET("/lots"), GET("/materials")]);
    const matById = Object.fromEntries(mats.map(m => [m.material_id, m]));
    const rows = allLots.filter(l => /phân xưởng/i.test(l.location || "") && l.quantity > 0)
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));   // FIFO: nhập trước hiện trước
    body = `<div class="panel"><h2>Kho phân xưởng <span class="muted">(${rows.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Lô đã được duyệt chỉ tiêu chất lượng ở kho công ty và chuyển tới đây (qua Đề nghị nhận kho) —
        không cần khai báo lại, chỉ tiêu hiển thị tự động lấy theo dữ liệu đã duyệt.</div>
      <input class="searchbox" data-tbl="t_px" placeholder="Tìm mã lô/vật tư..." style="margin-bottom:8px"/>
      <div class="tablewrap"><table id="t_px">
        <thead><tr><th>Lô</th><th>Vật tư</th><th>SL</th><th>Ngày giờ nhập</th><th>Vị trí</th><th>Trạng thái</th><th></th></tr></thead>
        <tbody>${rows.map(l => `<tr>
          <td><code class="k">${esc(l.lot_code)}</code></td>
          <td class="muted">${esc(matById[l.material_id] ? matById[l.material_id].code : l.material_id || "—")}</td>
          <td>${l.quantity} ${l.uom}</td>
          <td class="muted">${fmt(l.created_at)}</td>
          <td class="muted">${esc(l.location || "")}</td>
          <td>${badge(l.status)}</td>
          <td><button class="btn sm sec" data-lotqc="${esc(l.lot_id)}">Xem chỉ tiêu</button></td></tr>`).join("") ||
          `<tr><td colspan=7 class="muted">Chưa có lô nào ở kho phân xưởng.</td></tr>`}</tbody>
      </table></div>
    </div>`;
  } else if (sec === "req") {
    body = await renderRequestsSection();
  } else if (sec === "tudo") {
    const [allLots, mats, freeIssuesAll] = await Promise.all([GET("/lots"), GET("/materials"),
      GET("/warehouse/movements?movement_type=issue&mode=tu_do")]);
    const matById = Object.fromEntries(mats.map(m => [m.material_id, m]));
    const isAdminPx = CURRENT_USER && CURRENT_USER.role === "admin";
    const workshopLotOpts = allLots.filter(l => l.quantity > 0 && /phân xưởng/i.test(l.location || ""))
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
      .map(l => `<option value="${l.lot_id}">${esc(l.lot_code)} (${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})${l.status === "on_hold" ? " — CHỜ DUYỆT QC" : ""}</option>`).join("") ||
      `<option value="">(không có lô nào ở kho phân xưởng)</option>`;
    WH_CACHE.matById = matById;
    WH_CACHE.tu_do_px = freeIssuesAll.filter(m => /phân xưởng/i.test(m.location_from || ""));
    body = `<div class="panel"><h2>Xuất tự do (kho phân xưởng)</h2>
      <div class="muted" style="margin-bottom:6px">Xuất không theo phiếu đề nghị (vd. dùng nội bộ, thử nghiệm) trực tiếp từ lô đang ở
        kho phân xưởng. Lô đang "CHỜ DUYỆT QC" sẽ bị chặn xuất. Có thể "Hoàn lại" nếu xuất nhầm — vật tư trở về đúng lô, tránh thất thoát.</div>
      ${isAdminPx
        ? `<div class="row"><div class="field"><label>Lô</label><select id="xtpx_lot">${workshopLotOpts}</select></div>
        <div class="field"><label>SL</label><input id="xtpx_qty" type="number" value="50"/></div>
        <div class="field" style="flex:1"><label>Lý do (tuỳ chọn)</label><input id="xtpx_reason" placeholder="(tuỳ chọn)"/></div>
        <button class="btn sec" id="xtpx_do" style="align-self:flex-end">Xuất tự do</button></div>`
        : '<div class="muted">Chỉ tài khoản Admin mới được thực hiện xuất tự do.</div>'}
      ${movementHistoryBlockHtml("tu_do_px")}
    </div>`;
  } else if (sec === "nvlhist") {
    const rows = await GET("/warehouse/workshop-usage-history");
    body = `<div class="panel"><h2>Lịch sử xuất dùng NVL <span class="muted">(${rows.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">NVL đã xuất từ Kho phân xưởng và gán thật cho sản xuất (qua "NVL nấu/lọc/chiết" ở
        từng mẻ) — cho biết đúng công đoạn, mẻ, lô NVL đã dùng, khác với "Xuất tự do" (chỉ ghi lý do dạng tự do).</div>
      <input class="searchbox" data-tbl="t_nvlhist" placeholder="Tìm theo công đoạn, mẻ, vật tư, lô, người..." style="margin-bottom:8px;width:100%"/>
      <div class="tablewrap"><table id="t_nvlhist">
        <thead><tr><th>Thời gian</th><th>Công đoạn</th><th>Mẻ</th><th>Vật tư</th><th>Lô NVL</th><th>SL</th><th>Người thực hiện</th></tr></thead>
        <tbody>${rows.map(r => `<tr>
          <td class="muted">${fmt(r.ts)}</td>
          <td>${esc(r.stage)}</td>
          <td class="muted">${esc(r.batch_label || "")}</td>
          <td>${esc(r.material_name || "")}</td>
          <td class="muted">${esc(r.lot_code || "")}</td>
          <td>${r.quantity} ${esc(r.uom)}</td>
          <td class="muted">${esc(r.actor || "")}</td></tr>`).join("") ||
          `<tr><td colspan=7 class="muted">Chưa có giao dịch xuất dùng NVL nào.</td></tr>`}</tbody>
      </table></div>
    </div>`;
  }
  $("view-warehouse_px").innerHTML = subnav("warehouse_px", sections, sec) + body;
  wireSubnav("warehouse_px");
  wireSearch();
  document.querySelectorAll("[data-lotqc]").forEach(b => b.onclick = () => openLotQcModal(b.dataset.lotqc, { editable: false }));
  if (sec === "tudo") {
    if ($("xtpx_do")) $("xtpx_do").onclick = () => guard(async () => {
      await POST("/warehouse/issue", { lot_id: $("xtpx_lot").value, quantity: parseFloat($("xtpx_qty").value),
        mode: "tu_do", reason: $("xtpx_reason").value.trim() || null });
      toast("Đã xuất tự do"); render("warehouse_px");
    });
    wireMovementHistoryBlock("tu_do_px");
  }
  if (sec === "nvlhist") wirePaginate("t_nvlhist", 10);
  if (sec === "req") {
    wireCartPanel();
    wireRequestsHistoryBlock();
    document.querySelectorAll("[data-quickadd]").forEach(b => b.onclick = () => {
      const row = b.closest("tr");
      const qty = parseFloat(row.querySelector(".stk-qty").value);
      if (!qty || qty <= 0) { toast("Nhập số lượng muốn nhận trước khi thêm.", "err"); return; }
      const mat = REQ_CACHE.matById[b.dataset.pickmat];
      const lot = REQ_CACHE.lots.find(l => l.lot_id === b.dataset.quickadd);
      REQUEST_CART.push({ material_id: b.dataset.pickmat, material_code: mat ? mat.code : b.dataset.pickmat,
        lot_id: b.dataset.quickadd, lot_code: lot ? lot.lot_code : null,
        quantity: qty, uom: b.dataset.pickuom });
      toast(`Đã thêm vào đề nghị (${REQUEST_CART.length} dòng) — xem ở bảng phía trên`);
      refreshCartPanel();
    });
    if ($("stk_search")) $("stk_search").oninput = () => {
      const q = $("stk_search").value.trim().toLowerCase();
      document.querySelectorAll("#stk_table tbody tr[data-search]").forEach(tr => {
        tr.style.display = tr.dataset.search.includes(q) ? "" : "none";
      });
    };
  }
};

async function renderStockCountSection() {
  const counts = await GET("/warehouse/counts");
  return `<div class="panel"><h2>Kiểm kê định kỳ</h2>
    <div class="muted" style="margin-bottom:6px">Đối chiếu tồn hệ thống với tồn thực tế đếm tại kho — tạo phiếu để chụp tồn hệ thống hiện tại, điền số đếm thực tế, rồi chốt phiếu để tự động điều chỉnh lệch (nếu có).</div>
    <div class="row" style="margin-bottom:10px">
      <div class="field"><label>Kho</label><select id="kk_loc"><option value="">(Toàn bộ)</option><option value="Kho công ty">Kho công ty</option><option value="Kho phân xưởng">Kho phân xưởng</option></select></div>
      <div class="field" style="flex:1"><label>Ghi chú</label><input id="kk_note" placeholder="(tuỳ chọn)"/></div>
      <button class="btn" id="kk_create" style="align-self:flex-end">+ Tạo phiếu kiểm kê</button>
    </div>
    <input class="searchbox" data-tbl="t_kk" placeholder="Tìm mã phiếu/kho..." style="margin-bottom:8px"/>
    <div class="tablewrap"><table id="t_kk">
      <thead><tr><th>Mã phiếu</th><th>Kho</th><th>Số dòng</th><th>Trạng thái</th><th>Người tạo</th><th>Ngày tạo</th><th></th></tr></thead>
      <tbody>${counts.map(c => `<tr>
        <td><code class="k">${esc(c.count_code)}</code></td>
        <td class="muted">${esc(c.location || "Toàn bộ")}</td>
        <td>${c.line_count}</td>
        <td>${c.approved_by ? `<span style="color:var(--green)">Đã duyệt</span> <span class="muted" style="font-size:11px">(${esc(c.approved_by)})</span>`
              : c.status === "posted" ? '<span style="color:var(--green)">Đã chốt</span>' : '<span class="muted">Nháp</span>'}</td>
        <td class="muted">${esc(c.created_by || "")}</td>
        <td class="muted">${fmt(c.created_at)}</td>
        <td style="white-space:nowrap">
          <button class="btn sm sec" data-viewcount="${esc(c.count_id)}">Xem/Nhập số liệu</button>
          ${c.can_approve ? `<button class="btn sm" data-approvecount="${esc(c.count_id)}">Duyệt</button>` : ""}
          ${c.can_undo ? `<button class="btn sm sec" data-undocount="${esc(c.count_id)}">Hoàn tác</button>` : ""}
        </td></tr>`).join("") ||
        '<tr><td colspan=7 class="muted">Chưa có phiếu kiểm kê nào.</td></tr>'}</tbody>
    </table></div>
  </div>`;
}

async function renderLowStockSection() {
  const rows = await GET("/warehouse/low-stock");
  // Thanh ngang trục cố định — tái dùng nguyên CH.agingBars đã dùng cho "Tồn kho theo tuổi" ở
  // Dashboard, chỉ đổi trục sang khối lượng tồn thay vì số ngày. Đơn vị mỗi vật tư có thể khác
  // nhau (kg/cái/lít...) nên trục chỉ mang tính tương đối — số liệu chính xác nằm ở nhãn "disp".
  const items = rows.map(r => ({
    label: `${r.material_code} — ${r.material_name}`,
    value: r.on_hand,
    color: r.on_hand < r.stock_min * 0.7 ? "#d03b3b" : "#fab219",
    disp: `${r.on_hand.toLocaleString("vi-VN")}/${r.stock_min.toLocaleString("vi-VN")} ${r.uom}`,
  }));
  const chartHtml = items.length
    ? CH.agingBars(items, { axisLabel: "Số lượng tồn (theo ĐVT từng vật tư)" })
    : `<div class="muted">Không có vật tư nào dưới tồn tối thiểu.</div>`;
  return `<div class="panel"><h2>📉 Tồn tối thiểu ${rows.length ? `<span class="muted">(${rows.length})</span>` : ""}</h2>
    <div class="muted" style="margin-bottom:8px">Vật tư đang có tồn thực tế thấp hơn ngưỡng tồn tối thiểu đã cấu hình (Danh mục › Vật tư/Nguyên liệu) — sắp theo mức thiếu hụt giảm dần.</div>
    <div style="margin-bottom:14px">${chartHtml}</div>
    <div class="legend" style="font-size:11px;color:var(--muted);margin-bottom:10px">
      <span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px">
        <span style="width:9px;height:9px;border-radius:2px;background:#d03b3b;display:inline-block"></span>Dưới 70% ngưỡng</span>
      <span style="display:inline-flex;align-items:center;gap:6px">
        <span style="width:9px;height:9px;border-radius:2px;background:#fab219;display:inline-block"></span>70–100% ngưỡng</span>
    </div>
    <input class="searchbox" data-tbl="t_lowstock" placeholder="Tìm mã/tên vật tư..." style="margin-bottom:8px"/>
    <div class="tablewrap"><table id="t_lowstock">
      <thead><tr><th>Mã</th><th>Tên</th><th>Tồn hiện tại</th><th>Tồn tối thiểu</th><th>Thiếu hụt</th><th>ĐVT</th></tr></thead>
      <tbody>${rows.map(r => `<tr>
        <td><code class="k">${esc(r.material_code)}</code></td>
        <td>${esc(r.material_name)}</td>
        <td>${r.on_hand.toLocaleString("vi-VN")}</td>
        <td class="muted">${r.stock_min.toLocaleString("vi-VN")}</td>
        <td style="color:var(--red);font-weight:700">${r.deficit.toLocaleString("vi-VN")}</td>
        <td class="muted">${esc(r.uom)}</td></tr>`).join("") ||
        '<tr><td colspan=6 class="muted">Không có vật tư nào dưới tồn tối thiểu.</td></tr>'}</tbody>
    </table></div>
  </div>`;
}

async function openStockCountModal(countId) {
  const c = await GET(`/warehouse/counts/${countId}`);
  const isDraft = c.status === "draft";
  modal(`<h3>Phiếu kiểm kê ${esc(c.count_code)} <span class="muted">(${esc(c.location || "Toàn bộ")})</span></h3>
    <div class="muted" style="margin-bottom:8px">${isDraft
      ? "Điền số lượng đếm thực tế cho từng lô, bấm Lưu số liệu, rồi Chốt phiếu để tự động điều chỉnh lệch."
      : `Đã chốt bởi ${esc(c.posted_by || "")} lúc ${fmt(c.posted_at)}.${c.approved_by ? ` Đã duyệt bởi ${esc(c.approved_by)} lúc ${fmt(c.approved_at)}.` : ""}`}</div>
    <div class="tablewrap"><table>
      <thead><tr><th>Vật tư</th><th>Lô</th><th>Vị trí</th><th>Tồn hệ thống</th><th>Đếm thực tế</th><th>Lệch</th></tr></thead>
      <tbody>${c.lines.map(l => `<tr data-lineid="${esc(l.line_id)}">
        <td>${esc(l.material_code || l.material_id)}</td>
        <td class="muted">${esc(l.lot_code || "")}</td>
        <td class="muted">${esc(l.location || "")}</td>
        <td>${l.system_qty} ${esc(l.uom)}</td>
        <td>${isDraft ? `<input type="number" step="0.01" class="kkl_counted" style="width:90px" value="${l.counted_qty ?? ""}"/>`
          : (l.counted_qty ?? "—")}</td>
        <td class="muted">${l.variance == null ? "—" : (l.variance > 0 ? "+" : "") + l.variance}</td>
        </tr>`).join("")}</tbody>
    </table></div>
    ${isDraft ? `<div style="margin-top:12px;display:flex;gap:8px">
      <button class="btn sec" id="kk_save">Lưu số liệu</button>
      <button class="btn" id="kk_post">Chốt phiếu</button>
    </div>` : ""}`);
  if (isDraft) {
    $("kk_save").onclick = () => guard(async () => {
      const lines = Array.from(document.querySelectorAll("[data-lineid]")).map(tr => ({
        line_id: tr.dataset.lineid,
        counted_qty: tr.querySelector(".kkl_counted").value === "" ? null : parseFloat(tr.querySelector(".kkl_counted").value),
      }));
      await PUT(`/warehouse/counts/${countId}/lines`, { lines });
      toast("Đã lưu số liệu đếm"); closeModal(); openStockCountModal(countId);
    });
    $("kk_post").onclick = () => guard(async () => {
      if (!confirm("Chốt phiếu kiểm kê? Lệch tồn (nếu có) sẽ được tự động điều chỉnh và không sửa lại được.")) return;
      await POST(`/warehouse/counts/${countId}/post`, {});
      toast("Đã chốt phiếu kiểm kê"); closeModal(); render("warehouse_kc");
    });
  }
}

// ---- Sổ giao dịch kho dùng chung: xuất tự do / điều chuyển / trả NCC / xuất theo đề nghị ----
function movementRowHtml(m, matById, showUndo) {
  const mat = m.material_id ? matById[m.material_id] : null;
  const undoCell = !showUndo ? "" :
    m.reversed ? '<td><span class="muted">Đã hoàn lại</span></td>' :
    `<td><button class="btn sm sec" data-undoissue="${esc(m.movement_id)}">Hoàn lại</button></td>`;
  return `<tr>
    <td class="muted">${fmt(m.ts)}</td>
    <td>${esc(mat ? mat.code : m.material_id || "—")}</td>
    <td class="muted">${esc(m.lot_code || "")}</td>
    <td>${m.quantity} ${esc(m.uom)}</td>
    <td class="muted">${esc(m.location_from || "—")} → ${esc(m.location_to || "—")}</td>
    <td class="muted">${esc(m.reason || "")}</td>
    <td class="muted">${esc(m.actor || "")}</td>
    ${undoCell}</tr>`;
}

const WH_HIST_PAGE = 10;
// Toàn bộ giao dịch đã fetch (tối đa 200 dòng/backend) + số dòng đang hiển thị mỗi bảng —
// "Tải thêm" chỉ lộ thêm dữ liệu đã có sẵn trong bộ nhớ, không gọi lại API.
const WH_CACHE = { matById: {} };
const WH_HIST_VISIBLE = { tu_do: WH_HIST_PAGE, tu_do_px: WH_HIST_PAGE, dieu_chuyen: WH_HIST_PAGE, tra_ncc: WH_HIST_PAGE, xuat_theo_de_nghi: WH_HIST_PAGE };
const WH_HIST_TITLE = { tu_do: "Lịch sử xuất tự do", tu_do_px: "Lịch sử xuất tự do (phân xưởng)", dieu_chuyen: "Lịch sử điều chuyển",
  tra_ncc: "Lịch sử trả nhà cung cấp", xuat_theo_de_nghi: "Sổ xuất theo đề nghị (tất cả phiếu)" };
const WH_HIST_UNDO = { tu_do: true, tu_do_px: true, dieu_chuyen: false, tra_ncc: false, xuat_theo_de_nghi: false };
// "tu_do" (Kho công ty) và "tu_do_px" (Kho phân xưởng) dùng chung 1 endpoint/mode ở backend
// (StockMovement.mode="tu_do"), chỉ khác view nào gọi render() lại sau khi Hoàn tác.
const WH_HIST_VIEW = { tu_do: "warehouse_kc", tu_do_px: "warehouse_px" };

// "xuat_theo_de_nghi" hiển thị dạng thẻ phiếu accordion — giống hệt "Đề nghị nhận kho"
// (requestBlockHtml/requestLineRowHtml) thay vì bảng giao dịch phẳng, để mỗi dòng đã xuất
// có nút "Hoàn tác" ngay tại chỗ (dùng chung undo_fulfill_line, không phải undo-issue chung).
function movementHistoryBlockHtml(key) {
  const all = WH_CACHE[key] || [];
  if (key === "xuat_theo_de_nghi") {
    const visible = all.slice(0, WH_HIST_VISIBLE[key] || WH_HIST_PAGE);
    const moreBtn = all.length > visible.length
      ? `<button class="btn sm sec" data-loadmorehist="${key}" style="margin-top:6px">Tải thêm (còn ${all.length - visible.length})</button>` : "";
    return `<div id="wh_hist_${key}" style="margin-top:14px">
      <h4>${esc(WH_HIST_TITLE[key])} <span class="muted">(${visible.length}/${all.length} phiếu)</span></h4>
      ${visible.map(r => requestBlockHtml(r, WH_CACHE.matById, WH_CACHE.lotById, WH_CACHE.canFulfill, false, WH_CACHE.allLots)).join("") ||
        '<div class="muted">Chưa có phiếu nào đã xuất.</div>'}
      ${moreBtn}
    </div>`;
  }
  const showUndo = WH_HIST_UNDO[key];
  const visible = all.slice(0, WH_HIST_VISIBLE[key] || WH_HIST_PAGE);
  const cols = 7 + (showUndo ? 1 : 0);
  const moreBtn = all.length > visible.length
    ? `<button class="btn sm sec" data-loadmorehist="${key}" style="margin-top:6px">Tải thêm (còn ${all.length - visible.length})</button>` : "";
  return `<div class="tablewrap" id="wh_hist_${key}" style="margin-top:14px">
    <h4>${esc(WH_HIST_TITLE[key])} <span class="muted">(${visible.length}/${all.length})</span></h4>
    <table>
      <thead><tr><th>Thời gian</th><th>Vật tư</th><th>Lô</th><th>SL</th><th>Từ → Đến</th><th>Lý do</th><th>Người thực hiện</th>${showUndo ? "<th></th>" : ""}</tr></thead>
      <tbody>${visible.map(m => movementRowHtml(m, WH_CACHE.matById, showUndo)).join("") ||
        `<tr><td colspan=${cols} class="muted">Chưa có giao dịch nào.</td></tr>`}</tbody>
    </table>
    ${moreBtn}
  </div>`;
}

function wireMovementHistoryBlock(key) {
  const btn = document.querySelector(`[data-loadmorehist="${key}"]`);
  if (btn) btn.onclick = () => { WH_HIST_VISIBLE[key] = (WH_HIST_VISIBLE[key] || WH_HIST_PAGE) + WH_HIST_PAGE; refreshMovementHistoryBlock(key); };
  if (key === "xuat_theo_de_nghi") { wireRequestBlockActions(); return; }
  if (WH_HIST_UNDO[key]) {
    document.querySelectorAll(`#wh_hist_${key} [data-undoissue]`).forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Hoàn lại giao dịch xuất tự do này? Vật tư sẽ trở về lại lô.")) return;
      await POST(`/warehouse/movements/${b.dataset.undoissue}/undo-issue`, {});
      toast("Đã hoàn lại"); render(WH_HIST_VIEW[key] || "warehouse_kc");
    }));
  }
}

function refreshMovementHistoryBlock(key) {
  const el = document.getElementById("wh_hist_" + key);
  if (!el) return;
  el.outerHTML = movementHistoryBlockHtml(key);
  wireMovementHistoryBlock(key);
}

// ---- Đề nghị nhận kho: phân xưởng tạo, thủ kho công ty duyệt/từ chối ----
const REQ_CACHE = { lots: [], matById: {}, lotOptsByMaterial: () => "" };

function _hasPerm(perm) {
  return CURRENT_USER && (CURRENT_USER.permissions === "*" ||
    (Array.isArray(CURRENT_USER.permissions) && CURRENT_USER.permissions.includes(perm)));
}

// Tìm kiếm cho danh sách thẻ (card) như phiếu đề nghị nhận kho — khác wireSearch()/.searchbox
// (chỉ chạy được trên <table><tbody><tr>), ở đây lọc trực tiếp theo thuộc tính data-search
// gắn sẵn trên từng thẻ (xem requestBlockHtml).
function wireCardSearch(inputId, scopeSelector) {
  const inp = $(inputId);
  if (!inp) return;
  inp.oninput = () => {
    const q = inp.value.trim().toLowerCase();
    document.querySelectorAll(`${scopeSelector} [data-search]`).forEach(el => {
      el.style.display = el.dataset.search.includes(q) ? "" : "none";
    });
  };
}

// ---- "Khóa lô" (xem services/lot_lock.py) — badge dùng chung cho dòng đã khóa ở 4 bảng
// Nấu/Lên men/Lọc/Chiết. Mở khóa chỉ thao tác được từ dòng Chiết (cần bottle_id) — dòng
// Nấu/Lên men/Lọc chỉ hiện badge, không có nút mở khóa riêng.
function lockBadgeHtml(row) {
  return `<span class="muted" title="Đã khóa${row.locked_by ? " bởi " + esc(row.locked_by) : ""}">🔒 Đã khóa</span>`;
}
// HOLD (QA) — khác với "Khóa lô" (chốt sổ vĩnh viễn): hiển thị ngay trên dòng công đoạn để
// biết được lô/mẻ này đang bị QA giữ hay không mà không cần vào tab Chất lượng mới thấy
// (xem services/quality.py::set_hold + routers/brewing.py::_assert_unlocked).
function holdBadgeHtml(row) {
  return row.quality_status === "on_hold"
    ? `<span class="badge on_hold" title="Đang bị QA giữ (HOLD) — không thể sửa/xóa/chuyển bước cho tới khi RELEASE (tab Chất lượng)">⛔ HOLD</span> `
    : "";
}

let REQUEST_CART = [];   // {material_id, material_code, lot_id, lot_code, quantity, uom} — nhiều dòng, gửi 1 lần
let REQUEST_SOURCE = null;   // {type: "brew_order"|"filter_master_order", id, label} — tuỳ chọn, chỉ để tham chiếu/báo cáo

const REQ_STATUS_BADGE = { pending: "on_hold", fulfilled: "available", rejected: "obsolete", cancelled: "obsolete" };

// Mã vật tư không đổi, chỉ số lô khác nhau — so lô đang chọn với lô cũ nhất hiện có (FIFO)
// của đúng vật tư đó để cảnh báo nếu chọn nhầm lô không phải lô cũ nhất.
function fifoOldestLot(materialId, allLots) {
  const candidates = allLots.filter(l => l.material_id === materialId && l.quantity > 0 && !/phân xưởng/i.test(l.location || ""))
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  return candidates[0] || null;
}

function fifoBadgeHtml(materialId, lotId, allLots) {
  if (!lotId) return '<span class="muted">(chưa chọn — theo FIFO lúc xuất)</span>';
  const lot = allLots.find(l => l.lot_id === lotId);
  if (!lot) return "—";
  const oldest = fifoOldestLot(materialId, allLots);
  return (oldest && oldest.lot_id === lotId)
    ? '<span class="badge available">✓ Lô cũ nhất (FIFO)</span>'
    : `<span class="badge on_hold" title="Còn lô cũ hơn: ${esc(oldest ? oldest.lot_code : "")} (${oldest ? fmt(oldest.created_at) : ""})">⚠ Không phải lô cũ nhất</span>`;
}

// Dòng đã fulfilled: hiện lại đúng trạng thái FIFO đã chụp NGAY LÚC XUẤT (fifo_ok, xem
// services/warehouse.py::_is_oldest_company_lot) — KHÔNG so sánh live như fifoBadgeHtml vì
// tồn kho đã đổi khác kể từ lúc xuất (lô cũ hơn có thể đã hết/lô mới đã nhập thêm).
function fulfilledFifoBadgeHtml(fifoOk) {
  if (fifoOk === true) return '<span class="badge available">✓ Đã xuất đúng FIFO</span>';
  if (fifoOk === false) return '<span class="badge on_hold">⚠ Không đúng FIFO lúc xuất</span>';
  return "—";
}

function requestLineRowHtml(r, l, matById, lotById, canFulfill, allLots) {
  const mat = matById[l.material_id];
  const prefLot = l.preferred_lot_id ? lotById[l.preferred_lot_id] : null;
  const fulLot = l.fulfilled_lot_id ? lotById[l.fulfilled_lot_id] : null;
  const shownLot = fulLot || prefLot;
  const actions = (canFulfill && l.status === "pending")
    ? `<button class="btn sm sec" data-reqfulfill data-reqid="${esc(r.request_id)}" data-lineid="${esc(l.line_id)}">Xuất dòng này</button>
       <button class="btn sm sec" data-reqreject data-reqid="${esc(r.request_id)}" data-lineid="${esc(l.line_id)}">Từ chối</button>`
    : (canFulfill && l.status === "fulfilled")
    ? `<button class="btn sm sec" data-requndo data-reqid="${esc(r.request_id)}" data-lineid="${esc(l.line_id)}">Hoàn tác</button>`
    : (l.reason ? `<span class="muted">${esc(l.reason)}</span>` : "—");
  return `<tr>
    <td>${esc(mat ? mat.code : l.material_id)}</td>
    <td>${l.quantity} ${esc(l.uom)}</td>
    <td class="muted">${shownLot ? esc(shownLot.lot_code) : "—"}</td>
    <td class="muted">${shownLot ? fmt(shownLot.created_at) : "—"}</td>
    <td>${l.status === "fulfilled" ? fulfilledFifoBadgeHtml(l.fifo_ok) : fifoBadgeHtml(l.material_id, l.preferred_lot_id, allLots)}</td>
    <td>${badge(REQ_STATUS_BADGE[l.status] || "planned")}${esc(l.status)}</td>
    <td>${actions}</td></tr>`;
}

// 1 khối = 1 phiếu — mặc định chỉ hiện 1 dòng tóm tắt (số phiếu/người tạo/ngày/nguồn/trạng
// thái), bấm "Chi tiết" mới giãn ra bảng các dòng vật tư ngay tại chỗ (accordion, không mở
// modal/không gọi lại API) — nếu hiện luôn hết mọi dòng vật tư của MỌI phiếu như trước thì
// có hàng trăm/nghìn phiếu sẽ rất khó xem. "Duyệt cả phiếu" tự chọn lô (FIFO/lô ưu tiên) cho
// MỌI dòng đang pending trong 1 lần bấm — an toàn vì SL mỗi dòng đã được chặn không vượt tồn
// kho công ty ngay từ lúc tạo phiếu.
function requestBlockHtml(r, matById, lotById, canFulfill, showBulk, allLots, canRequest) {
  const pendingCount = r.lines.filter(l => l.status === "pending").length;
  const fulfilledCount = r.lines.filter(l => l.status === "fulfilled").length;
  const hasFulfilled = fulfilledCount > 0;
  const bulkBtn = (showBulk && canFulfill && pendingCount > 0)
    ? `<button class="btn sm" data-fulfillall="${esc(r.request_id)}">Duyệt cả phiếu (${pendingCount} dòng) →</button>` : "";
  const cancelBtn = (!hasFulfilled && pendingCount > 0 && (canRequest || canFulfill))
    ? `<button class="btn sm sec" data-reqcancel="${esc(r.request_id)}">Xóa phiếu</button>` : "";
  const summary = `${r.lines.length} dòng` +
    (pendingCount ? ` · ${pendingCount} chờ xử lý` : "") +
    (fulfilledCount ? ` · ${fulfilledCount} đã xuất` : "");
  const matCodes = r.lines.map(l => (matById[l.material_id] || {}).code || "").join(" ");
  const searchKey = [r.request_code, r.requested_by, r.note, r.source_label, matCodes]
    .filter(Boolean).join(" ").toLowerCase();
  return `<div class="tablewrap" data-search="${esc(searchKey)}" style="margin-bottom:10px">
      <div class="row" style="align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">
        <div class="row" style="align-items:center;gap:8px">
          <button class="btn sm sec" data-reqtoggle="${esc(r.request_id)}">▸ Chi tiết</button>
          <div class="muted">
            Số phiếu <code class="k">${esc(r.request_code)}</code>
            · người tạo <b>${esc(r.requested_by || "")}</b> · ${fmt(r.requested_at)}
            ${r.source_label ? " · " + esc(r.source_label) : ""}
            · ${summary}
            ${r.note ? " · " + esc(r.note) : ""}
          </div>
        </div>
        <div class="row" style="gap:6px">${bulkBtn}${cancelBtn}</div>
      </div>
      <div id="reqdetail-${esc(r.request_id)}" style="display:none;margin-top:8px">
        <table>
          <thead><tr><th>Vật tư</th><th>SL</th><th>Lô</th><th>Ngày nhập</th><th>FIFO</th><th>Trạng thái</th><th></th></tr></thead>
          <tbody>${r.lines.map(l => requestLineRowHtml(r, l, matById, lotById, canFulfill, allLots)).join("") ||
            '<tr><td colspan=7 class="muted">Phiếu không có dòng nào.</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
}

function wireRequestBlockActions() {
  document.querySelectorAll("[data-reqtoggle]").forEach(b => b.onclick = () => {
    const panel = document.getElementById("reqdetail-" + b.dataset.reqtoggle);
    if (!panel) return;
    const open = panel.style.display !== "none";
    panel.style.display = open ? "none" : "";
    b.textContent = (open ? "▸" : "▾") + " Chi tiết";
  });
  document.querySelectorAll("[data-reqfulfill]").forEach(b => b.onclick = () => openFulfillRequestModal(b.dataset.reqid, b.dataset.lineid));
  // Hàm này dùng chung cho cả 2 module (Kho công ty tab "giao" và Kho phân xưởng tab "req") —
  // render lại đúng view đang mở (không hardcode 1 view) để hoạt động đúng ở cả 2 nơi.
  const renderCurrentWarehouseView = () => {
    const v = document.querySelector("#nav button.active")?.dataset.view;
    if (v) render(v);
  };
  document.querySelectorAll("[data-reqreject]").forEach(b => b.onclick = () => guard(async () => {
    const reason = prompt("Lý do từ chối (tuỳ chọn):") || null;
    await POST(`/warehouse/requests/${b.dataset.reqid}/lines/${b.dataset.lineid}/reject`, { reason });
    toast("Đã từ chối dòng đề nghị"); renderCurrentWarehouseView();
  }));
  document.querySelectorAll("[data-fulfillall]").forEach(b => b.onclick = () => guard(async () => {
    const res = await POST(`/warehouse/requests/${b.dataset.fulfillall}/fulfill-all`, {});
    const msg = `Đã xuất ${res.fulfilled.length} dòng sang Kho phân xưởng` +
      (res.skipped.length ? `; ${res.skipped.length} dòng cần xử lý thủ công (không đủ 1 lô hoặc đang chờ QC)` : "");
    toast(msg, res.skipped.length ? "err" : "ok");
    renderCurrentWarehouseView();
  }));
  document.querySelectorAll("[data-reqcancel]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Xóa phiếu đề nghị này? (chỉ áp dụng cho các dòng chưa duyệt)")) return;
    await DELETE(`/warehouse/requests/${b.dataset.reqcancel}`);
    toast("Đã xóa phiếu đề nghị"); renderCurrentWarehouseView();
  }));
  document.querySelectorAll("[data-requndo]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Hoàn tác dòng đã xuất này? Vật tư sẽ được chuyển lại Kho công ty.")) return;
    await POST(`/warehouse/requests/${b.dataset.reqid}/lines/${b.dataset.lineid}/undo-fulfill`, {});
    toast("Đã hoàn tác — vật tư đã về lại Kho công ty"); renderCurrentWarehouseView();
  }));
}

// Khung "Tạo đề nghị nhận kho" tách riêng để cập nhật tại chỗ khi thêm/xoá dòng —
// tránh render lại cả trang làm mất vị trí cuộn/ô tìm kiếm ở bảng tồn kho bên dưới.
function cartPanelHtml() {
  if (!REQ_CACHE.canRequest) return "";
  const cartRows = REQUEST_CART.map((c, i) => {
    const lot = c.lot_id ? REQ_CACHE.lots.find(l => l.lot_id === c.lot_id) : null;
    return `<tr>
    <td>${esc(c.material_code)}</td>
    <td class="muted">${c.lot_code ? esc(c.lot_code) : "(để thủ kho chọn theo FIFO)"}</td>
    <td class="muted">${lot ? fmt(lot.created_at) : "—"}</td>
    <td>${fifoBadgeHtml(c.material_id, c.lot_id, REQ_CACHE.lots)}</td>
    <td>${c.quantity} ${esc(c.uom)}</td>
    <td><button class="btn sm sec" data-cartdel="${i}">Xoá</button></td></tr>`;
  }).join("");
  return `<div class="panel" id="rq_form_panel">
    <h2>Tạo đề nghị nhận kho ${REQUEST_CART.length ? `<span class="muted">(${REQUEST_CART.length} dòng)</span>` : ""}</h2>
    <div class="muted" style="margin-bottom:6px">Thêm nhiều dòng (nhiều vật tư/lô khác nhau) rồi gửi 1 lần — chọn nhanh
      từ bảng "Tồn kho công ty" ở cuối trang, hoặc thêm thủ công bên dưới. Mã vật tư giống nhau có thể có nhiều số lô
      khác nhau — mặc định tự chọn lô cũ nhất theo FIFO, vẫn đổi được nếu cần.</div>
    ${REQUEST_CART.length ? `<div class="tablewrap"><table>
      <thead><tr><th>Vật tư</th><th>Lô</th><th>Ngày nhập</th><th>FIFO</th><th>SL</th><th></th></tr></thead>
      <tbody>${cartRows}</tbody>
    </table></div>` : '<div class="muted" style="margin:8px 0">Chưa có dòng nào trong đề nghị.</div>'}
    <h4 style="margin-top:14px">Nạp vật tư từ Lệnh nấu / Lệnh lọc (tuỳ chọn)</h4>
    <div class="muted" style="margin-bottom:6px">Chọn 1 lệnh để tự động điền sẵn các dòng vật tư theo định mức đã lập trong lệnh đó —
      vẫn sửa số lượng/lô hoặc thêm/xoá dòng như bình thường sau khi nạp.</div>
    <div class="row">
      <div class="field"><label>Loại lệnh</label><select id="rq_srctype">
        <option value="">(không có)</option>
        <option value="brew_order">Lệnh nấu</option>
        <option value="filter_master_order">Lệnh lọc</option>
      </select></div>
      <div class="field" style="flex:1"><label>Lệnh</label><select id="rq_srcorder"><option value="">(chọn loại lệnh trước)</option></select></div>
      <button class="btn sec" id="rq_srcload" style="align-self:flex-end" disabled>Nạp vật tư từ lệnh</button>
    </div>
    ${REQUEST_SOURCE ? `<div class="muted" style="margin:6px 0">Phiếu sẽ gắn với: <b>${esc(REQUEST_SOURCE.label)}</b>
      <button class="btn sm sec" id="rq_srcclear">Bỏ gắn</button></div>` : ""}
    <h4 style="margin-top:14px">+ Thêm dòng thủ công</h4>
    <div class="row">
      <div class="field"><label>Vật tư</label><select id="rq_mat">${REQ_CACHE.matOpts}</select></div>
      <div class="field"><label>SL</label><input id="rq_qty" type="number" value="50"/></div>
      <div class="field"><label>ĐVT</label><input id="rq_uom" value="kg" size="4"/></div>
      <div class="field" style="min-width:280px"><label>Lô ưu tiên (mặc định lô cũ nhất — FIFO)</label><select id="rq_lot"></select></div>
      <button class="btn sec" id="rq_add" style="align-self:flex-end">+ Thêm dòng</button>
    </div>
    <div class="row" style="margin-top:10px">
      <div class="field" style="flex:1"><label>Ghi chú chung (tuỳ chọn)</label><input id="rq_note" placeholder="(tuỳ chọn)"/></div>
      <button class="btn" id="rq_submit" style="align-self:flex-end" ${REQUEST_CART.length ? "" : "disabled"}>
        Gửi đề nghị (${REQUEST_CART.length} dòng)</button>
    </div>
  </div>`;
}

// Cập nhật khung giỏ hàng tại chỗ (không render lại cả trang) sau khi thêm/xoá dòng.
function refreshCartPanel() {
  const panel = document.getElementById("rq_form_panel");
  if (!panel) return;
  panel.outerHTML = cartPanelHtml();
  wireCartPanel();
}

function wireCartPanel() {
  if (!$("rq_form_panel")) return;
  const fillSrcOrderOpts = () => {
    const type = $("rq_srctype").value;
    const sel = $("rq_srcorder");
    if (!type) {
      sel.innerHTML = '<option value="">(chọn loại lệnh trước)</option>';
      $("rq_srcload").disabled = true;
      return;
    }
    const opts = type === "brew_order" ? (REQ_CACHE.brewOrders || []) : (REQ_CACHE.filterMasterOrders || []);
    sel.innerHTML = '<option value="">(chọn lệnh)</option>' +
      opts.map(o => `<option value="${esc(o.id)}">${esc(o.order_code)}</option>`).join("");
    $("rq_srcload").disabled = true;
  };
  $("rq_srctype").onchange = fillSrcOrderOpts;
  $("rq_srcorder").onchange = () => { $("rq_srcload").disabled = !$("rq_srcorder").value; };
  fillSrcOrderOpts();
  $("rq_srcload").onclick = () => guard(async () => {
    const type = $("rq_srctype").value, id = $("rq_srcorder").value;
    if (!type || !id) return;
    const lines = await GET(`/warehouse/requests/source-preview?source_type=${type}&source_id=${id}`);
    if (!lines.length) { toast("Lệnh này không có dòng vật tư nào.", "err"); return; }
    for (const l of lines) {
      REQUEST_CART.push({ material_id: l.material_id, material_code: l.material_code || l.material_id,
        lot_id: null, lot_code: null, quantity: l.quantity, uom: l.uom || "kg" });
    }
    const orderCode = $("rq_srcorder").options[$("rq_srcorder").selectedIndex].textContent;
    REQUEST_SOURCE = { type, id, label: (type === "brew_order" ? "Lệnh nấu " : "Lệnh lọc ") + orderCode };
    refreshCartPanel();
    toast(`Đã nạp ${lines.length} dòng vật tư từ ${REQUEST_SOURCE.label}`);
  });
  if ($("rq_srcclear")) $("rq_srcclear").onclick = () => { REQUEST_SOURCE = null; refreshCartPanel(); };
  const fillLotOpts = () => {
    $("rq_lot").innerHTML = REQ_CACHE.lotOptsByMaterial($("rq_mat").value);
    // Mặc định chọn sẵn lô cũ nhất theo FIFO (option đầu sau "để trống") — vẫn đổi được nếu cần.
    if ($("rq_lot").options.length > 1) $("rq_lot").selectedIndex = 1;
  };
  $("rq_mat").onchange = fillLotOpts;
  fillLotOpts();
  $("rq_add").onclick = () => guard(async () => {
    const qty = parseFloat($("rq_qty").value);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    const matId = $("rq_mat").value;
    const mat = REQ_CACHE.matById[matId];
    const onHand = REQ_CACHE.lots.filter(l => l.material_id === matId && !/phân xưởng/i.test(l.location || ""))
      .reduce((sum, l) => sum + l.quantity, 0);
    if (qty > onHand) throw new Error(
      `Số lượng đề nghị (${qty}) vượt quá tồn kho công ty hiện có của ${mat ? mat.code : matId} (${onHand}).`);
    const lotId = $("rq_lot").value || null;
    const lot = lotId ? REQ_CACHE.lots.find(l => l.lot_id === lotId) : null;
    REQUEST_CART.push({ material_id: matId, material_code: mat ? mat.code : matId,
      lot_id: lotId, lot_code: lot ? lot.lot_code : null,
      quantity: qty, uom: $("rq_uom").value.trim() || "kg" });
    refreshCartPanel();
  });
  document.querySelectorAll("[data-cartdel]").forEach(b => b.onclick = () => {
    REQUEST_CART.splice(parseInt(b.dataset.cartdel, 10), 1);
    refreshCartPanel();
  });
  $("rq_submit").onclick = () => guard(async () => {
    if (!REQUEST_CART.length) throw new Error("Chưa có dòng nào trong đề nghị.");
    const note = $("rq_note").value.trim() || null;
    // 1 phiếu duy nhất gồm nhiều dòng vật tư — KHÔNG tách thành nhiều phiếu riêng.
    const res = await POST("/warehouse/requests", {
      lines: REQUEST_CART.map(c => ({ material_id: c.material_id, quantity: c.quantity,
        uom: c.uom, preferred_lot_id: c.lot_id })),
      note,
      source_type: REQUEST_SOURCE ? REQUEST_SOURCE.type : null,
      source_id: REQUEST_SOURCE ? REQUEST_SOURCE.id : null,
    });
    toast(`Đã gửi phiếu ${res.request_code} (${REQUEST_CART.length} dòng)`);
    REQUEST_CART = [];
    REQUEST_SOURCE = null;
    render("warehouse_px");
  });
}

// "Đang chờ xử lý" (còn dòng pending) luôn hiện hết vì cần thao tác; "Đã xử lý xong" (mọi dòng
// đã fulfilled/rejected/cancelled) chỉ hiện REQ_DONE_VISIBLE phiếu đầu — "Tải thêm" chỉ lộ thêm
// dữ liệu đã fetch sẵn, không gọi lại API.
const REQ_DONE_PAGE = 10;
let REQ_DONE_VISIBLE = REQ_DONE_PAGE;

function requestsHistoryBlockHtml() {
  const requests = REQ_CACHE.allRequests || [];
  const { matById, lotById, canFulfill, canRequest, lots } = REQ_CACHE;
  const pending = requests.filter(r => r.lines.some(l => l.status === "pending"));
  const done = requests.filter(r => !r.lines.some(l => l.status === "pending"));
  const visibleDone = done.slice(0, REQ_DONE_VISIBLE);
  const pendingHtml = pending.map(r => requestBlockHtml(r, matById, lotById, canFulfill, true, lots, canRequest)).join("") ||
    '<div class="muted">Không có phiếu nào đang chờ xử lý.</div>';
  const doneHtml = visibleDone.map(r => requestBlockHtml(r, matById, lotById, canFulfill, false, lots, canRequest)).join("");
  const moreBtn = done.length > visibleDone.length
    ? `<button class="btn sm sec" id="req_done_more">Tải thêm (còn ${done.length - visibleDone.length} phiếu)</button>` : "";
  return `<div id="req_history_block">
    <input class="searchbox" id="req_hist_search" placeholder="Tìm theo số phiếu, người tạo, ghi chú, vật tư..." style="margin-bottom:10px;width:100%"/>
    <h3 style="margin:14px 0 8px">Đang chờ xử lý <span class="muted">(${pending.length})</span></h3>
    ${pendingHtml}
    <h3 style="margin:18px 0 8px">Đã xử lý xong <span class="muted">(${visibleDone.length}/${done.length})</span></h3>
    ${doneHtml || '<div class="muted">Chưa có phiếu nào đã xử lý xong.</div>'}
    ${moreBtn}
  </div>`;
}

function wireRequestsHistoryBlock() {
  wireRequestBlockActions();
  wireCardSearch("req_hist_search", "#req_history_block");
  if ($("req_done_more")) $("req_done_more").onclick = () => {
    REQ_DONE_VISIBLE += REQ_DONE_PAGE;
    refreshRequestsHistoryBlock();
  };
}

function refreshRequestsHistoryBlock() {
  const el = $("req_history_block");
  if (!el) return;
  el.outerHTML = requestsHistoryBlockHtml();
  wireRequestsHistoryBlock();
}

async function renderRequestsSection() {
  const [requests, mats, lots, brewOrders, filterMasterOrders] = await Promise.all([
    GET("/warehouse/requests"), GET("/materials"), GET("/lots"),
    GET("/brewing/orders").catch(() => []), GET("/brewing/filter-master-orders").catch(() => [])]);
  // brewOrders là danh sách LỆNH NHỎ (BrewOrder con) — order_code của nó chỉ là mã nội bộ vô
  // nghĩa ("SUB-xxx", tự sinh, không phải mã người dùng gõ) nên KHÔNG hiện thẳng ra dropdown —
  // phải ghép mã Lệnh nấu lớn (master_order_code, cái người dùng thực sự đặt tên) + số thứ tự
  // lệnh nhỏ + dịch bia + ngày tạo mới đủ để phân biệt "đề nghị NVL cho lệnh nhỏ nào".
  // Chỉ hiện lệnh CHƯA hoàn thành trong danh sách nạp vật tư — lệnh đã hoàn thành (đủ sản
  // lượng + hết mẻ) không còn cần đề nghị nhận thêm NVL nữa, ẩn đi để tránh chọn nhầm.
  REQ_CACHE.brewOrders = brewOrders.filter(o => !o.is_complete).map(o => ({ id: o.brew_order_id,
    order_code: `${o.master_order_code || "(chưa gắn Lệnh nấu lớn)"} · lệnh nhỏ ${o.seq ?? "?"} · ` +
      `${o.product_code || o.product_desc || "(chưa gán dịch bia)"} · ${o.created_at ? fmt(o.created_at) : "—"}` }));
  REQ_CACHE.filterMasterOrders = filterMasterOrders.filter(o => !o.is_complete_all)
    .map(o => ({ id: o.filter_master_order_id, order_code: o.order_code }));
  REQ_CACHE.matById = Object.fromEntries(mats.map(m => [m.material_id, m]));
  REQ_CACHE.lots = lots;
  const lotById = Object.fromEntries(lots.map(l => [l.lot_id, l]));
  REQ_CACHE.lotById = lotById;
  REQ_CACHE.allRequests = requests;
  REQ_CACHE.lotOptsByMaterial = (materialId) => {
    const avail = lots.filter(l => l.material_id === materialId && l.quantity > 0 && !/phân xưởng/i.test(l.location || ""))
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));   // FIFO
    return `<option value="">(để trống — thủ kho tự chọn theo FIFO lúc xuất)</option>` + avail.map((l, i) =>
      `<option value="${l.lot_id}">${esc(l.lot_code)} (${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})` +
      `${i === 0 ? " — FIFO, lô cũ nhất" : ""}${l.status === "on_hold" ? " — CHỜ DUYỆT QC" : ""}</option>`).join("");
  };
  const canRequest = _hasPerm("warehouse.request");
  const canFulfill = _hasPerm("warehouse.issue");
  REQ_CACHE.matOpts = mats.map(m => `<option value="${m.material_id}">${esc(m.code)} — ${esc(m.name)}</option>`).join("");
  REQ_CACHE.canRequest = canRequest;
  REQ_CACHE.canFulfill = canFulfill;
  // Mỗi lần vào lại tab (kể cả sau 1 thao tác) là 1 lượt xem mới — reset về trang đầu.
  REQ_DONE_VISIBLE = REQ_DONE_PAGE;

  const cartSection = cartPanelHtml();

  const requestsTable = `<div class="panel"><h2>Lịch sử đề nghị nhận kho <span class="muted">(${requests.length} phiếu)</span></h2>
    ${requestsHistoryBlockHtml()}
    ${!canRequest && !canFulfill ? '<div class="muted" style="margin-top:8px">Cần quyền <code class="k">warehouse.request</code> (phân xưởng) hoặc <code class="k">warehouse.issue</code> (thủ kho) để thao tác.</div>' : ""}
  </div>`;

  // ---- Tồn kho công ty: bảng tham khảo để chọn nhanh — đặt cuối trang (danh mục sẽ dài, có ô tìm) ----
  const stockLots = lots.filter(l => l.quantity > 0 && !/phân xưởng/i.test(l.location || ""))
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));   // FIFO
  const stockBrowser = !canRequest ? "" : `<div class="panel"><h2>Tồn kho công ty <span class="muted">(${stockLots.length})</span></h2>
    <div class="muted" style="margin-bottom:6px">Nhập số lượng muốn nhận rồi bấm "+ Thêm" để đưa vào đề nghị phía trên — có thể thêm nhiều dòng liên tiếp.</div>
    <div class="row" style="margin-bottom:6px"><div class="field" style="flex:1"><label>Tìm vật tư/lô</label><input id="stk_search" placeholder="Gõ mã/tên vật tư hoặc mã lô..."/></div></div>
    <div class="tablewrap"><table id="stk_table">
      <thead><tr><th>Vật tư</th><th>Lô</th><th>SL còn</th><th>Ngày giờ nhập</th><th>Trạng thái QC</th><th>SL muốn nhận</th><th></th></tr></thead>
      <tbody>${stockLots.map(l => { const mat = REQ_CACHE.matById[l.material_id]; return `<tr data-search="${esc(((mat ? mat.code + " " + mat.name : "") + " " + l.lot_code).toLowerCase())}">
        <td>${esc(mat ? mat.code : l.material_id)}</td>
        <td><code class="k">${esc(l.lot_code)}</code></td>
        <td>${l.quantity} ${esc(l.uom)}</td>
        <td class="muted">${fmt(l.created_at)}</td>
        <td>${badge(l.status)}</td>
        <td><input type="number" class="stk-qty" value="${l.quantity}" min="0" max="${l.quantity}" style="width:90px"/></td>
        <td><button class="btn sm sec" data-quickadd="${esc(l.lot_id)}" data-pickmat="${esc(l.material_id)}" data-pickuom="${esc(l.uom)}">+ Thêm</button></td></tr>`; }).join("") ||
        '<tr><td colspan=7 class="muted">Kho công ty hiện không còn lô nào.</td></tr>'}</tbody>
    </table></div>
  </div>`;

  return cartSection + requestsTable + stockBrowser;
}

async function openFulfillRequestModal(requestId, lineId) {
  const [requests, mats, lots] = await Promise.all([GET("/warehouse/requests"), GET("/materials"), GET("/lots")]);
  const req = requests.find(r => r.request_id === requestId);
  const line = req && req.lines.find(l => l.line_id === lineId);
  if (!req || !line) return;
  const mat = mats.find(m => m.material_id === line.material_id);
  const avail = lots.filter(l => l.material_id === line.material_id && l.quantity > 0 && !/phân xưởng/i.test(l.location || ""))
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));   // FIFO
  const lotOpts = avail.map((l, i) =>
    `<option value="${l.lot_id}">${esc(l.lot_code)} (${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})` +
    `${i === 0 ? " — FIFO, lô cũ nhất" : ""}${l.status === "on_hold" ? " — CHỜ DUYỆT QC" : ""}</option>`).join("");
  const fifoWarn = (line.preferred_lot_id && avail.length && avail[0].lot_id !== line.preferred_lot_id)
    ? `<div class="muted" style="margin:6px 0">⚠ Lô ưu tiên lúc đề nghị không phải lô cũ nhất — lô cũ nhất hiện có là
       <b>${esc(avail[0].lot_code)}</b> (nhập ${fmt(avail[0].created_at)}).</div>` : "";
  modal(`<h3>Xuất theo phiếu đề nghị — số phiếu <code class="k">${esc(req.request_code)}</code></h3>
    <div class="muted" style="margin-bottom:8px">Vật tư <b>${esc(mat ? mat.code : line.material_id)}</b>
      · SL đề nghị ${line.quantity} ${esc(line.uom)} · người đề nghị ${esc(req.requested_by || "")}
      ${req.note ? " · " + esc(req.note) : ""}</div>
    ${fifoWarn}
    <div class="field"><label>Chọn lô (FIFO — nhập trước hiện trước)</label><select id="ffl_lot">${lotOpts}</select></div>
    <div class="row" style="margin-top:8px">
      <div class="field"><label>Số lượng xuất</label><input id="ffl_qty" type="number" value="${line.quantity}"/></div>
      <div class="field" style="flex:1"><label>Kho xuất đến</label><input id="ffl_loc" value="Kho phân xưởng"/></div>
    </div>
    <button class="btn" id="ffl_submit" style="margin-top:12px">Xác nhận xuất theo phiếu ${esc(req.request_code)}</button>`);
  // Mặc định lô ưu tiên đã chọn lúc đề nghị; nếu không có thì mặc định lô cũ nhất theo FIFO.
  if (line.preferred_lot_id) $("ffl_lot").value = line.preferred_lot_id;
  else if (avail.length) $("ffl_lot").value = avail[0].lot_id;
  $("ffl_submit").onclick = () => guard(async () => {
    const lotId = $("ffl_lot").value;
    if (!lotId) throw new Error("Chọn lô cần xuất.");
    const locationTo = $("ffl_loc").value.trim() || "Kho phân xưởng";
    await POST(`/warehouse/requests/${requestId}/lines/${lineId}/fulfill`,
      { lot_id: lotId, quantity: parseFloat($("ffl_qty").value), location_to: locationTo });
    closeModal(); toast(`Đã xuất theo phiếu ${req.request_code} — lô chuyển sang ${locationTo}`);
    const v = document.querySelector("#nav button.active")?.dataset.view;
    if (v) render(v);
  });
}

// ---- Modal: khai báo + duyệt chỉ tiêu chất lượng của 1 lô NVL ----
// editable=true (mặc định, dùng ở tab Chất lượng cho KCS): cho nhập giá trị + nút Duyệt.
// editable=false (dùng ở tab Kho NVL cho thủ kho / khu Kho phân xưởng): chỉ xem trạng thái, không nhập được.
// Chỉ tiêu Đạt/Không đạt được ghi qua nguyên cơ chế so sánh numeric có sẵn (value/lower/upper),
// không sửa logic đánh giá — quy ước value=1 (Đạt) hoặc 0 (Không đạt), lower=upper=1 để
// _evaluate()/_evaluate_stage_result() so value==upper==lower ra PASS, khác ra FAIL.
function qcValueLabel(p, value) {
  if (p.value_type === "pass_fail") return value === 1 ? "Đạt" : value === 0 ? "Không đạt" : esc(String(value));
  return esc(String(value));
}
function qcValueInputHtml(cls, p) {
  if (p.value_type === "pass_fail") {
    return `<select class="${cls}" data-code="${esc(p.code)}" data-lsl="1" data-usl="1" style="width:130px">
      <option value="">— chọn —</option><option value="1">Đạt</option><option value="0">Không đạt</option></select>`;
  }
  return `<input type="number" step="any" class="${cls}" data-code="${esc(p.code)}" data-lsl="${p.lsl ?? ""}" data-usl="${p.usl ?? ""}" style="width:110px"/>`;
}
// Người điền + ngày giờ điền — áp dụng cho mọi bảng khai báo chỉ tiêu (Kho NVL/Nấu/Lên men/
// Lọc/Chiết đều dùng chung QualityResult.recorded_by/recorded_at, xem qc_catalog.py).
function qcRecordedMetaHtml(r) {
  if (!r) return "—";
  return `<span class="muted" style="font-size:12px">${esc(r.recorded_by || "—")}<br/>${r.recorded_at ? fmt(r.recorded_at) : "—"}</span>`;
}
async function openLotQcModal(lotId, { editable = true } = {}) {
  const st = await GET(`/lots/${lotId}/qc-status`);
  const canRelease = editable && CURRENT_USER && (CURRENT_USER.permissions === "*" ||
    (Array.isArray(CURRENT_USER.permissions) && CURRENT_USER.permissions.includes("quality.release")));
  const recordedByParam = Object.fromEntries(st.recorded.map(r => [r.parameter, r]));
  modal(`<h3>Chỉ tiêu chất lượng — lô ${esc(st.lot_code)}</h3>
    ${!editable ? '<div class="muted" style="margin-bottom:8px">Chế độ xem — việc khai báo &amp; duyệt do KCS thực hiện ở tab Chất lượng.</div>' : ""}
    <div class="row" style="margin-bottom:10px">
      <div class="field"><label>Số lô KCS</label>
        <input id="lqc_kcslot" value="${esc(st.kcs_lot_no || "")}" placeholder="(KCS tự điền)" ${editable ? "" : "disabled"}/></div>
      ${editable ? '<button class="btn sec sm" id="lqc_kcslot_save" style="align-self:flex-end">Lưu số lô KCS</button>' : ""}
    </div>
    <div class="tablewrap"><table>
      <thead><tr><th>Chỉ tiêu</th><th>Min</th><th>Max</th><th>Giá trị đã khai báo</th><th>Kết quả</th><th>Người/Thời gian điền</th>${editable ? "<th>Nhập giá trị mới</th>" : ""}</tr></thead>
      <tbody>${st.required.map(p => { const r = recordedByParam[p.code]; return `<tr>
        <td>${esc(p.name)}<div class="muted">${esc(p.code)}${p.unit ? " (" + esc(p.unit) + ")" : ""}</div></td>
        <td>${p.value_type === "pass_fail" ? "—" : (p.lsl ?? "—")}</td><td>${p.value_type === "pass_fail" ? "—" : (p.usl ?? "—")}</td>
        <td>${r ? qcValueLabel(p, r.value) : "—"}</td>
        <td>${r ? badge(r.status) + r.status : '<span class="muted">chưa khai báo</span>'}</td>
        <td>${qcRecordedMetaHtml(r)}</td>
        ${editable ? `<td>${qcValueInputHtml("lqc-val", p)}</td>` : ""}
        </tr>`; }).join("") || `<tr><td colspan=${editable ? 7 : 6} class="muted">Nguyên liệu này không có chỉ tiêu bắt buộc.</td></tr>`}</tbody>
    </table></div>
    ${editable ? `<button class="btn" id="lqc_submit" style="margin-top:12px">Lưu giá trị đã nhập</button>
    ${canRelease ? `<button class="btn sec" id="lqc_release" style="margin-top:12px" ${st.can_release ? "" : "disabled"}>
      Duyệt (release)${st.can_release ? "" : " — còn thiếu khai báo"}</button>` :
      '<div class="muted" style="margin-top:12px">Cần quyền <code class="k">quality.release</code> (KCS/QA) để duyệt.</div>'}` : ""}`);
  if (!editable) return;

  $("lqc_kcslot_save").onclick = () => guard(async () => {
    await PUT(`/lots/${lotId}`, { kcs_lot_no: $("lqc_kcslot").value.trim() || null });
    toast("Đã lưu số lô KCS");
  });
  $("lqc_submit").onclick = () => guard(async () => {
    const inputs = Array.from(document.querySelectorAll(".lqc-val")).filter(i => i.value !== "");
    if (!inputs.length) throw new Error("Chưa nhập giá trị nào.");
    for (const inp of inputs) {
      await POST("/quality/results", {
        scope_type: "lot", scope_id: lotId, parameter: inp.dataset.code,
        value: parseFloat(inp.value),
        lower_limit: inp.dataset.lsl === "" ? null : parseFloat(inp.dataset.lsl),
        upper_limit: inp.dataset.usl === "" ? null : parseFloat(inp.dataset.usl),
      });
    }
    toast("Đã lưu chỉ tiêu"); openLotQcModal(lotId, { editable });
  });
  if ($("lqc_release")) $("lqc_release").onclick = () => guard(async () => {
    await POST("/quality/hold", { scope_type: "lot", scope_id: lotId, on_hold: false });
    closeModal(); toast("Đã duyệt lô — có thể chuyển sang kho phân xưởng");
    const v = document.querySelector("#nav button.active")?.dataset.view;
    if (v) render(v);
  });
}

// ---- Modal: khai báo chỉ tiêu theo công đoạn sản xuất (mẻ nấu/lên men chính-phụ/lọc/chiết/thành phẩm) ----
// Cùng cơ chế openLotQcModal nhưng lưu qua /brewing/qc-results (không gắn vòng đời batch/lot) —
// duyệt/tiếp tục công đoạn (nếu có, vd Duyệt chiết) là hành động riêng, không nằm trong modal này.
async function openStageQcModal(stage, scopeType, scopeId, opts) {
  opts = opts || {};
  const title = opts.title || (STAGE_LABELS[stage] || stage);
  let qs = `stage=${encodeURIComponent(stage)}&scope_type=${encodeURIComponent(scopeType)}&scope_id=${encodeURIComponent(scopeId)}`;
  const isProductScopedStage = PRODUCT_SCOPED_STAGES.includes(stage);
  if (opts.productId) qs += `&product_id=${encodeURIComponent(opts.productId)}`;
  if (opts.beerTypeId) qs += `&beer_type_id=${encodeURIComponent(opts.beerTypeId)}`;
  if (opts.finishedProductId) qs += `&finished_product_id=${encodeURIComponent(opts.finishedProductId)}`;
  const st = await GET(`/brewing/qc-status?${qs}`);
  const recordedByParam = Object.fromEntries(st.recorded.map(r => [r.parameter, r]));
  modal(`<h3>Chỉ tiêu ${esc(title)} — <code class="k">${esc(opts.displayId || scopeId)}</code></h3>
    ${isProductScopedStage && !opts.productId ? '<div class="muted" style="margin-bottom:8px">⚠ Bản ghi này chưa gắn dịch bia — chỉ hiện nhóm chỉ tiêu áp dụng cho mọi dịch bia (nếu có).</div>' : ""}
    ${!isProductScopedStage && !opts.beerTypeId ? '<div class="muted" style="margin-bottom:8px">⚠ Bản ghi này chưa gắn Loại bia — chỉ hiện nhóm chỉ tiêu áp dụng cho mọi loại bia (nếu có).</div>' : ""}
    ${stage === "thanh_pham" && !opts.finishedProductId ? '<div class="muted" style="margin-bottom:8px">⚠ Bản ghi này chưa gắn Sản phẩm — chỉ hiện nhóm chỉ tiêu áp dụng cho mọi sản phẩm (nếu có).</div>' : ""}
    <div class="tablewrap"><table>
      <thead><tr><th>Chỉ tiêu</th><th>Min</th><th>Max</th><th>Giá trị đã khai báo</th><th>Kết quả</th><th>Người/Thời gian điền</th><th>Nhập giá trị mới</th></tr></thead>
      <tbody>${st.required.map(p => { const r = recordedByParam[p.code]; return `<tr>
        <td>${esc(p.name)}<div class="muted">${esc(p.code)}${p.unit ? " (" + esc(p.unit) + ")" : ""}</div></td>
        <td>${p.value_type === "pass_fail" ? "—" : (p.lsl ?? "—")}</td><td>${p.value_type === "pass_fail" ? "—" : (p.usl ?? "—")}</td>
        <td>${r ? qcValueLabel(p, r.value) : "—"}</td>
        <td>${r ? badge(r.status) + r.status : '<span class="muted">chưa khai báo</span>'}</td>
        <td>${qcRecordedMetaHtml(r)}</td>
        <td>${qcValueInputHtml("sqc-val", p)}</td>
        </tr>`; }).join("") || `<tr><td colspan=7 class="muted">Chưa gán nhóm chỉ tiêu nào cho công đoạn này (gán ở tab Danh mục).</td></tr>`}</tbody>
    </table></div>
    <div class="muted" style="margin-top:8px">${st.can_release ? '<span style="color:var(--green)">✓ Đã đủ chỉ tiêu bắt buộc</span>' :
      st.pending.length ? `⚠ Còn thiếu: ${st.pending.map(esc).join(", ")}` :
      st.required.length ? '<span style="color:var(--red)">✗ Có chỉ tiêu bắt buộc không đạt (FAIL)</span>' : ""}</div>
    ${st.required.length ? `<button class="btn" id="sqc_submit" style="margin-top:12px">Lưu giá trị đã nhập</button>` : ""}`);
  if ($("sqc_submit")) $("sqc_submit").onclick = () => guard(async () => {
    const inputs = Array.from(document.querySelectorAll(".sqc-val")).filter(i => i.value !== "");
    if (!inputs.length) throw new Error("Chưa nhập giá trị nào.");
    for (const inp of inputs) {
      await POST("/brewing/qc-results", {
        stage, scope_type: scopeType, scope_id: scopeId, parameter: inp.dataset.code,
        value: parseFloat(inp.value),
        lower_limit: inp.dataset.lsl === "" ? null : parseFloat(inp.dataset.lsl),
        upper_limit: inp.dataset.usl === "" ? null : parseFloat(inp.dataset.usl),
      });
    }
    toast("Đã lưu chỉ tiêu");
    // Bảng nền (Nấu/Lên men/Lọc/Chiết) tô màu theo trạng thái chỉ tiêu lúc load trang — sửa
    // FAIL thành PASS rồi lưu ở đây không tự cập nhật màu bảng nền vì modal render tách biệt
    // với view (xem modal() — overlay riêng trên document.body). Refresh view nền để màu đúng ngay,
    // không cần F5 mới thấy — bảng dưới vẫn bị ẩn sau modal cho tới khi đóng.
    const curView = document.querySelector("#nav button.active")?.dataset.view;
    if (curView) render(curView);
    openStageQcModal(stage, scopeType, scopeId, opts);
  });
}

// Popup nhỏ xem chi tiết chỉ tiêu đang FAIL của 1 tank lên men (bấm vào badge đỏ ở biểu đồ
// Dashboard) — chỉ đọc, không cho sửa ở đây (sửa giá trị vẫn làm qua nút CT chính/CT phụ ở
// tab Lên men, xem openStageQcModal). Gộp cả 2 giai đoạn CT chính + CT phụ vì badge đếm cả hai.
async function openFermentQcFailModal(lmCode, productId) {
  const stages = [["len_men_chinh", "CT chính"], ["len_men_phu", "CT phụ"]];
  const results = await Promise.all(stages.map(([stage]) => {
    const qs = `stage=${encodeURIComponent(stage)}&scope_type=ferment&scope_id=${encodeURIComponent(lmCode + "__" + stage)}`
      + (productId ? `&product_id=${encodeURIComponent(productId)}` : "");
    return GET(`/brewing/qc-status?${qs}`);
  }));
  const rows = [];
  stages.forEach(([stage, label], i) => {
    const st = results[i];
    const recordedByParam = Object.fromEntries(st.recorded.map(r => [r.parameter, r]));
    st.required.forEach(p => {
      const r = recordedByParam[p.code];
      if (r && r.status === "fail") rows.push({ label, p, r });
    });
  });
  modal(`<h3>Chỉ tiêu đang vượt giới hạn — tank <code class="k">${esc(lmCode)}</code></h3>
    <div class="tablewrap"><table>
      <thead><tr><th>Giai đoạn</th><th>Chỉ tiêu</th><th>Min</th><th>Max</th><th>Giá trị</th><th>Người/Thời gian điền</th></tr></thead>
      <tbody>${rows.length ? rows.map(x => `<tr>
        <td>${esc(x.label)}</td>
        <td>${esc(x.p.name)}<div class="muted">${esc(x.p.code)}${x.p.unit ? " (" + esc(x.p.unit) + ")" : ""}</div></td>
        <td>${x.p.value_type === "pass_fail" ? "—" : (x.p.lsl ?? "—")}</td>
        <td>${x.p.value_type === "pass_fail" ? "—" : (x.p.usl ?? "—")}</td>
        <td style="color:var(--red);font-weight:700">${qcValueLabel(x.p, x.r.value)}</td>
        <td>${qcRecordedMetaHtml(x.r)}</td>
        </tr>`).join("") : `<tr><td colspan=6 class="muted">Không có chỉ tiêu nào đang fail.</td></tr>`}</tbody>
    </table></div>`);
}

// Chú thích "đã dùng đúng lô cũ nhất (FIFO) tại Kho phân xưởng chưa" — chụp lại (snapshot)
// lúc gán NVL, xem services/warehouse.py::is_oldest_workshop_lot. null = không có lô thật
// (nhập tên tự do) nên không áp dụng FIFO.
function fifoBadgeHtml(fifoOk) {
  if (fifoOk === true) return '<span style="color:var(--green)" title="Lô cũ nhất còn tồn tại Kho phân xưởng lúc dùng">✓ FIFO</span>';
  if (fifoOk === false) return '<span style="color:var(--red)" title="Còn lô khác cũ hơn chưa dùng hết tại Kho phân xưởng lúc dùng">⚠ Không FIFO</span>';
  return '<span class="muted">—</span>';
}
// Sắp lô Kho phân xưởng theo FIFO (cũ nhất trước) khi hiện trong dropdown chọn NVL — nhóm
// theo vật tư (material_id) để lô cũ nhất của TỪNG vật tư nổi lên trước, không trộn lẫn.
function sortLotsFifo(lotsArr) {
  return lotsArr.slice().sort((a, b) => {
    if ((a.material_id || "") !== (b.material_id || "")) return (a.material_id || "").localeCompare(b.material_id || "");
    return new Date(a.created_at) - new Date(b.created_at);
  });
}

// ---- Modal: nguyên liệu đã dùng cho 1 mẻ cụ thể (thuộc 1 mã nấu) — lấy thật từ tồn kho Kho phân xưởng ----
async function openBrewMaterialsModal(brewId, batchId, batchCode) {
  const [usage, lots, materials, brews] = await Promise.all([
    GET(`/brewing/brews/${brewId}/batches/${batchId}/materials`), GET("/lots"), GET("/materials"),
    GET("/brewing/brews").catch(() => [])]);
  const matById = Object.fromEntries(materials.map(m => [m.material_id, m]));

  // Gợi ý số lượng NVL/mẻ — lấy từ Định mức của Lệnh nấu (mã nấu này thuộc về), đã tự
  // chia đều cho số mẻ khai báo lúc lập lệnh (BrewOrderMaterialLine.qty_per_batch).
  // Chỉ là gợi ý — số thực tế dùng vẫn ghi ở ô SL riêng, sửa tự do được.
  let sugByMaterialId = {};
  const brew = brews.find(b => b.brew_id === brewId);
  if (brew && brew.brew_order_id) {
    try {
      const order = await GET(`/brewing/orders/${brew.brew_order_id}`);
      sugByMaterialId = Object.fromEntries(
        (order.lines || []).filter(l => !l.is_header && l.material_id && l.qty_per_batch != null)
          .map(l => [l.material_id, l.qty_per_batch]));
    } catch (e) { /* không có lệnh nấu/định mức — bỏ qua gợi ý */ }
  }

  // Chỉ hiển thị NVL có trong định mức của lệnh nấu này — tránh chọn nhầm vật tư
  // không thuộc công thức. Nếu lệnh nấu chưa có định mức thì mới cho chọn tự do.
  const bomMaterialIds = new Set(Object.keys(sugByMaterialId));
  const workshopLotsAll = lots.filter(l => l.quantity > 0 && l.status !== "on_hold" && /phân xưởng/i.test(l.location || ""));
  const workshopLots = sortLotsFifo(bomMaterialIds.size ? workshopLotsAll.filter(l => bomMaterialIds.has(l.material_id)) : workshopLotsAll);
  const lotOpts = `<option value="">(nhập tên tự do)</option>` + workshopLots.map(l => {
    const mat = matById[l.material_id];
    return `<option value="${esc(l.lot_id)}" data-material="${esc(l.material_id || "")}">${esc(mat ? mat.name : l.lot_code)} — lô ${esc(l.lot_code)} (còn ${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})</option>`;
  }).join("") || `<option value="">(Kho phân xưởng chưa có tồn NVL thuộc định mức lệnh nấu này)</option>`;

  modal(`<h3>Nguyên liệu dùng cho mẻ — <code class="k">${esc(batchCode)}</code></h3>
    <div class="muted" style="margin-bottom:8px">Nguyên liệu phân bổ vào mẻ nấu lấy từ tồn kho <b>Kho phân xưởng</b> — chọn lô sẽ trừ tồn kho thật ngay. Danh sách lô bên dưới đã sắp theo FIFO (cũ nhất trước) trong từng vật tư.</div>
    <div class="tablewrap"><table>
      <thead><tr><th>Nguyên liệu</th><th>Số lô PM</th><th>Ngày lô</th><th>FIFO</th><th>Số lượng</th><th>ĐVT</th><th></th></tr></thead>
      <tbody>${usage.map(u => `<tr>
        <td>${esc(u.material_name)}</td><td class="muted">${esc(u.lot_pm || "—")}</td>
        <td class="muted">${u.lot_date ? fmt(u.lot_date) : "—"}</td>
        <td>${fifoBadgeHtml(u.fifo_ok)}</td>
        <td><input type="number" step="any" class="bmu-edit-qty" data-usage="${esc(u.usage_id)}" value="${u.quantity}" style="width:90px"/></td>
        <td><input class="bmu-edit-uom" data-usage="${esc(u.usage_id)}" value="${esc(u.uom)}" style="width:60px"/></td>
        <td style="white-space:nowrap">
          <button class="btn sm sec" data-saveusage="${esc(u.usage_id)}" data-name="${esc(u.material_name)}" data-lot="${esc(u.lot_pm || "")}" data-receipt="${esc(u.receipt_id || "")}" data-lotid="${esc(u.lot_id || "")}">Lưu</button>
          <button class="btn sm sec" data-delusage="${esc(u.usage_id)}">Xóa</button>
        </td></tr>`).join("") ||
        `<tr><td colspan=7 class="muted">Chưa ghi nguyên liệu nào cho mẻ này.</td></tr>`}</tbody>
    </table></div>
    <h4 style="margin-top:14px">+ Thêm nguyên liệu</h4>
    <div class="muted" style="font-size:12px;margin-bottom:4px">Chọn nguyên liệu ở Kho phân xưởng sẽ tự hiện "Gợi ý" (định mức/mẻ theo Lệnh nấu, đã chia đều cho số mẻ) và tự điền tạm vào ô SL — chỉ là gợi ý, sửa lại SL theo thực tế dùng.</div>
    <div class="row">
      <div class="field" style="min-width:300px"><label>Chọn từ tồn kho Kho phân xưởng</label><select id="bmu_lot">${lotOpts}</select></div>
      <div class="field"><label>Hoặc tên tự do</label><input id="bmu_name" placeholder="(nếu không chọn ở trên)"/></div>
      <div class="field"><label>Gợi ý (định mức/mẻ)</label><input id="bmu_qty_sug" value="—" disabled style="width:100px;opacity:.7"/></div>
      <div class="field"><label>SL thực tế</label><input id="bmu_qty" type="number" value="0"/></div>
      <div class="field"><label>ĐVT</label><input id="bmu_uom" value="kg" size="4"/></div>
      <button class="btn" id="bmu_add" style="align-self:flex-end">Thêm</button>
    </div>`);
  $("bmu_lot").onchange = () => {
    const opt = $("bmu_lot").selectedOptions[0];
    const materialId = opt ? opt.dataset.material : "";
    const sug = materialId ? sugByMaterialId[materialId] : null;
    $("bmu_qty_sug").value = sug != null ? sug : "—";
    if (sug != null && (!$("bmu_qty").value || parseFloat($("bmu_qty").value) === 0)) {
      $("bmu_qty").value = sug;
    }
  };
  $("bmu_add").onclick = () => guard(async () => {
    const lotId = $("bmu_lot").value || null;
    const name = $("bmu_name").value.trim() || null;
    if (!lotId && !name) throw new Error("Chọn nguyên liệu từ tồn kho Kho phân xưởng, hoặc nhập tên tự do.");
    const qty = parseFloat($("bmu_qty").value);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    await POST(`/brewing/brews/${brewId}/batches/${batchId}/materials`, {
      lot_id: lotId, material_name: name, quantity: qty, uom: $("bmu_uom").value.trim() || "kg" });
    toast("Đã thêm nguyên liệu cho mẻ" + (lotId ? " — đã trừ tồn Kho phân xưởng" : "")); openBrewMaterialsModal(brewId, batchId, batchCode);
  });
  document.querySelectorAll("[data-saveusage]").forEach(b => b.onclick = () => guard(async () => {
    const usageId = b.dataset.saveusage;
    const qty = parseFloat(document.querySelector(`.bmu-edit-qty[data-usage="${usageId}"]`).value);
    const uom = document.querySelector(`.bmu-edit-uom[data-usage="${usageId}"]`).value.trim() || "kg";
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    await PUT(`/brewing/brews/${brewId}/batches/${batchId}/materials/${usageId}`, {
      lot_id: b.dataset.lotid || null, receipt_id: b.dataset.receipt || null, material_name: b.dataset.name,
      lot_pm: b.dataset.lot || null, quantity: qty, uom });
    toast("Đã lưu"); openBrewMaterialsModal(brewId, batchId, batchCode);
  }));
  document.querySelectorAll("[data-delusage]").forEach(b => b.onclick = () => guard(async () => {
    await DELETE(`/brewing/brews/${brewId}/batches/${batchId}/materials/${b.dataset.delusage}`);
    toast("Đã xóa"); openBrewMaterialsModal(brewId, batchId, batchCode);
  }));
}

// ---- Modal: nguyên liệu đã dùng cho 1 mẻ lọc cụ thể — lấy thật từ tồn kho Kho phân xưởng
// (mirror openBrewMaterialsModal, gợi ý số lượng lấy từ FilterOrderMaterialLine của Lệnh lọc) ----
async function openFilterMaterialsModal(filterId, filterOrderId, filterCode) {
  const [usage, lots, materials] = await Promise.all([
    GET(`/brewing/filters/${filterId}/materials`), GET("/lots"), GET("/materials")]);
  const matById = Object.fromEntries(materials.map(m => [m.material_id, m]));

  // Gợi ý số lượng NVL — lấy từ dòng vật tư đã khai báo lúc lập Lệnh lọc
  // (FilterOrderMaterialLine.quantity, không chia theo mẻ vì lệnh không có qty_per_batch).
  // Chỉ là gợi ý — số thực tế dùng vẫn ghi ở ô SL riêng, sửa tự do được.
  let sugByMaterialId = {};
  if (filterOrderId) {
    try {
      const order = await GET(`/brewing/filter-orders/${filterOrderId}`);
      sugByMaterialId = Object.fromEntries((order.lines || []).map(l => [l.material_id, l.quantity]));
    } catch (e) { /* không lấy được lệnh lọc — bỏ qua gợi ý */ }
  }
  // Chỉ cho lấy NVL có trong định mức của Lệnh lọc này — không cho "nhập tên tự do" nữa khi
  // đã có định mức (khác NVL nấu — ở đây siết chặt hơn theo yêu cầu: vật tư không thuộc lệnh
  // lọc thì không được lấy, không có đường vòng qua tên tự do). Lệnh lọc chưa khai báo định
  // mức nào (rỗng) thì mới cho chọn tự do như cũ.
  const bomMaterialIds = new Set(Object.keys(sugByMaterialId));
  const workshopLotsAll = lots.filter(l => l.quantity > 0 && l.status !== "on_hold" && /phân xưởng/i.test(l.location || ""));
  const workshopLots = sortLotsFifo(bomMaterialIds.size ? workshopLotsAll.filter(l => bomMaterialIds.has(l.material_id)) : workshopLotsAll);
  const lotOpts = `<option value="">${bomMaterialIds.size ? "(chọn nguyên liệu)" : "(nhập tên tự do)"}</option>` + workshopLots.map(l => {
    const mat = matById[l.material_id];
    return `<option value="${esc(l.lot_id)}" data-material="${esc(l.material_id || "")}">${esc(mat ? mat.name : l.lot_code)} — lô ${esc(l.lot_code)} (còn ${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})</option>`;
  }).join("") || `<option value="">${bomMaterialIds.size
      ? "(Kho phân xưởng chưa có tồn đúng vật tư của Lệnh lọc — khai báo ở Kho NVL)"
      : "(Kho phân xưởng chưa có tồn — khai báo ở Kho NVL)"}</option>`;

  modal(`<h3>Nguyên liệu dùng cho mẻ lọc — <code class="k">${esc(filterCode)}</code></h3>
    <div class="muted" style="margin-bottom:8px">Nguyên liệu phân bổ vào mẻ lọc lấy từ tồn kho <b>Kho phân xưởng</b> — chọn lô sẽ trừ tồn kho thật ngay. Danh sách lô bên dưới đã sắp theo FIFO (cũ nhất trước) trong từng vật tư.
      ${bomMaterialIds.size ? " Chỉ cho chọn đúng vật tư đã khai báo trong Lệnh lọc — vật tư khác không được lấy." : ""}</div>
    <div class="tablewrap"><table>
      <thead><tr><th>Nguyên liệu</th><th>Số lô PM</th><th>Ngày lô</th><th>FIFO</th><th>Số lượng</th><th>ĐVT</th><th></th></tr></thead>
      <tbody>${usage.map(u => `<tr>
        <td>${esc(u.material_name)}</td><td class="muted">${esc(u.lot_pm || "—")}</td>
        <td class="muted">${u.lot_date ? fmt(u.lot_date) : "—"}</td>
        <td>${fifoBadgeHtml(u.fifo_ok)}</td>
        <td><input type="number" step="any" class="fmu-edit-qty" data-usage="${esc(u.usage_id)}" value="${u.quantity}" style="width:90px"/></td>
        <td><input class="fmu-edit-uom" data-usage="${esc(u.usage_id)}" value="${esc(u.uom)}" style="width:60px"/></td>
        <td style="white-space:nowrap">
          <button class="btn sm sec" data-savefusage="${esc(u.usage_id)}" data-name="${esc(u.material_name)}" data-lot="${esc(u.lot_pm || "")}" data-receipt="${esc(u.receipt_id || "")}" data-lotid="${esc(u.lot_id || "")}">Lưu</button>
          <button class="btn sm sec" data-delfusage="${esc(u.usage_id)}">Xóa</button>
        </td></tr>`).join("") ||
        `<tr><td colspan=7 class="muted">Chưa ghi nguyên liệu nào cho mẻ lọc này.</td></tr>`}</tbody>
    </table></div>
    <h4 style="margin-top:14px">+ Thêm nguyên liệu</h4>
    <div class="muted" style="font-size:12px;margin-bottom:4px">Chọn nguyên liệu ở Kho phân xưởng sẽ tự hiện "Gợi ý" (số lượng đã khai báo lúc lập Lệnh lọc) và tự điền tạm vào ô SL — chỉ là gợi ý, sửa lại SL theo thực tế dùng.</div>
    <div class="row">
      <div class="field" style="min-width:300px"><label>Chọn từ tồn kho Kho phân xưởng</label><select id="fmu_lot">${lotOpts}</select></div>
      ${bomMaterialIds.size ? "" : `<div class="field"><label>Hoặc tên tự do</label><input id="fmu_name" placeholder="(nếu không chọn ở trên)"/></div>`}
      <div class="field"><label>Gợi ý (Lệnh lọc)</label><input id="fmu_qty_sug" value="—" disabled style="width:100px;opacity:.7"/></div>
      <div class="field"><label>SL thực tế</label><input id="fmu_qty" type="number" value="0"/></div>
      <div class="field"><label>ĐVT</label><input id="fmu_uom" value="kg" size="4"/></div>
      <button class="btn" id="fmu_add" style="align-self:flex-end">Thêm</button>
    </div>`);
  $("fmu_lot").onchange = () => {
    const opt = $("fmu_lot").selectedOptions[0];
    const materialId = opt ? opt.dataset.material : "";
    const sug = materialId ? sugByMaterialId[materialId] : null;
    $("fmu_qty_sug").value = sug != null ? sug : "—";
    if (sug != null && (!$("fmu_qty").value || parseFloat($("fmu_qty").value) === 0)) {
      $("fmu_qty").value = sug;
    }
  };
  $("fmu_add").onclick = () => guard(async () => {
    const lotId = $("fmu_lot").value || null;
    const name = bomMaterialIds.size ? null : ($("fmu_name")?.value.trim() || null);
    if (!lotId && !name) throw new Error("Chọn nguyên liệu từ tồn kho Kho phân xưởng" + (bomMaterialIds.size ? " (đúng vật tư của Lệnh lọc)." : ", hoặc nhập tên tự do."));
    const qty = parseFloat($("fmu_qty").value);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    await POST(`/brewing/filters/${filterId}/materials`, {
      lot_id: lotId, material_name: name, quantity: qty, uom: $("fmu_uom").value.trim() || "kg" });
    toast("Đã thêm nguyên liệu cho mẻ lọc" + (lotId ? " — đã trừ tồn Kho phân xưởng" : "")); openFilterMaterialsModal(filterId, filterOrderId, filterCode);
  });
  document.querySelectorAll("[data-savefusage]").forEach(b => b.onclick = () => guard(async () => {
    const usageId = b.dataset.savefusage;
    const qty = parseFloat(document.querySelector(`.fmu-edit-qty[data-usage="${usageId}"]`).value);
    const uom = document.querySelector(`.fmu-edit-uom[data-usage="${usageId}"]`).value.trim() || "kg";
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    await PUT(`/brewing/filters/${filterId}/materials/${usageId}`, {
      lot_id: b.dataset.lotid || null, receipt_id: b.dataset.receipt || null, material_name: b.dataset.name,
      lot_pm: b.dataset.lot || null, quantity: qty, uom });
    toast("Đã lưu"); openFilterMaterialsModal(filterId, filterOrderId, filterCode);
  }));
  document.querySelectorAll("[data-delfusage]").forEach(b => b.onclick = () => guard(async () => {
    await DELETE(`/brewing/filters/${filterId}/materials/${b.dataset.delfusage}`);
    toast("Đã xóa"); openFilterMaterialsModal(filterId, filterOrderId, filterCode);
  }));
}

// ---- Modal: nguyên liệu đã dùng cho 1 mẻ chiết cụ thể (VD: CO2, hóa chất vệ sinh) — lấy
// thật từ tồn kho Kho phân xưởng (mirror openFilterMaterialsModal). Chiết không có Lệnh với
// định mức vật tư riêng như Nấu/Lọc nên không có cột "Gợi ý" — chọn tự do trong Kho phân
// xưởng hoặc nhập tên tự do. ----
async function openBottleMaterialsModal(bottleId, bottleCode) {
  const [usage, lots, materials] = await Promise.all([
    GET(`/brewing/bottles/${bottleId}/materials`), GET("/lots"), GET("/materials")]);
  const matById = Object.fromEntries(materials.map(m => [m.material_id, m]));
  const workshopLots = sortLotsFifo(lots.filter(l => l.quantity > 0 && l.status !== "on_hold" && /phân xưởng/i.test(l.location || "")));
  const lotOpts = `<option value="">(nhập tên tự do)</option>` + workshopLots.map(l => {
    const mat = matById[l.material_id];
    return `<option value="${esc(l.lot_id)}" data-material="${esc(l.material_id || "")}">${esc(mat ? mat.name : l.lot_code)} — lô ${esc(l.lot_code)} (còn ${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})</option>`;
  }).join("") || `<option value="">(Kho phân xưởng chưa có tồn — khai báo ở Kho NVL)</option>`;

  modal(`<h3>Nguyên liệu dùng cho mẻ chiết — <code class="k">${esc(bottleCode)}</code></h3>
    <div class="muted" style="margin-bottom:8px">Nguyên liệu phân bổ vào mẻ chiết (VD CO2, hóa chất vệ sinh) lấy từ tồn kho <b>Kho phân xưởng</b> — chọn lô sẽ trừ tồn kho thật ngay. Danh sách lô bên dưới đã sắp theo FIFO (cũ nhất trước) trong từng vật tư.</div>
    <div class="tablewrap"><table>
      <thead><tr><th>Nguyên liệu</th><th>Số lô PM</th><th>Ngày lô</th><th>FIFO</th><th>Số lượng</th><th>ĐVT</th><th></th></tr></thead>
      <tbody>${usage.map(u => `<tr>
        <td>${esc(u.material_name)}</td><td class="muted">${esc(u.lot_pm || "—")}</td>
        <td class="muted">${u.lot_date ? fmt(u.lot_date) : "—"}</td>
        <td>${fifoBadgeHtml(u.fifo_ok)}</td>
        <td><input type="number" step="any" class="cmu-edit-qty" data-usage="${esc(u.usage_id)}" value="${u.quantity}" style="width:90px"/></td>
        <td><input class="cmu-edit-uom" data-usage="${esc(u.usage_id)}" value="${esc(u.uom)}" style="width:60px"/></td>
        <td style="white-space:nowrap">
          <button class="btn sm sec" data-savecusage="${esc(u.usage_id)}" data-name="${esc(u.material_name)}" data-lot="${esc(u.lot_pm || "")}" data-lotid="${esc(u.lot_id || "")}">Lưu</button>
          <button class="btn sm sec" data-delcusage="${esc(u.usage_id)}">Xóa</button>
        </td></tr>`).join("") ||
        `<tr><td colspan=7 class="muted">Chưa ghi nguyên liệu nào cho mẻ chiết này.</td></tr>`}</tbody>
    </table></div>
    <h4 style="margin-top:14px">+ Thêm nguyên liệu</h4>
    <div class="row">
      <div class="field" style="min-width:300px"><label>Chọn từ tồn kho Kho phân xưởng</label><select id="cmu_lot">${lotOpts}</select></div>
      <div class="field"><label>Hoặc tên tự do</label><input id="cmu_name" placeholder="(nếu không chọn ở trên)"/></div>
      <div class="field"><label>SL thực tế</label><input id="cmu_qty" type="number" value="0"/></div>
      <div class="field"><label>ĐVT</label><input id="cmu_uom" value="kg" size="4"/></div>
      <button class="btn" id="cmu_add" style="align-self:flex-end">Thêm</button>
    </div>`);
  $("cmu_add").onclick = () => guard(async () => {
    const lotId = $("cmu_lot").value || null;
    const name = $("cmu_name").value.trim() || null;
    if (!lotId && !name) throw new Error("Chọn nguyên liệu từ tồn kho Kho phân xưởng, hoặc nhập tên tự do.");
    const qty = parseFloat($("cmu_qty").value);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    await POST(`/brewing/bottles/${bottleId}/materials`, {
      lot_id: lotId, material_name: name, quantity: qty, uom: $("cmu_uom").value.trim() || "kg" });
    toast("Đã thêm nguyên liệu cho mẻ chiết" + (lotId ? " — đã trừ tồn Kho phân xưởng" : "")); openBottleMaterialsModal(bottleId, bottleCode);
  });
  document.querySelectorAll("[data-savecusage]").forEach(b => b.onclick = () => guard(async () => {
    const usageId = b.dataset.savecusage;
    const qty = parseFloat(document.querySelector(`.cmu-edit-qty[data-usage="${usageId}"]`).value);
    const uom = document.querySelector(`.cmu-edit-uom[data-usage="${usageId}"]`).value.trim() || "kg";
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    await PUT(`/brewing/bottles/${bottleId}/materials/${usageId}`, {
      lot_id: b.dataset.lotid || null, material_name: b.dataset.name, lot_pm: b.dataset.lot || null, quantity: qty, uom });
    toast("Đã lưu"); openBottleMaterialsModal(bottleId, bottleCode);
  }));
  document.querySelectorAll("[data-delcusage]").forEach(b => b.onclick = () => guard(async () => {
    await DELETE(`/brewing/bottles/${bottleId}/materials/${b.dataset.delcusage}`);
    toast("Đã xóa"); openBottleMaterialsModal(bottleId, bottleCode);
  }));
}

// ---- Modal: gợi ý NVL copy từ 1 mẻ nguồn sang 1 mẻ đích — KHÔNG copy thẳng lot_id cũ (có
// thể không còn là lô FIFO đúng tại thời điểm này, hoặc lô đã hết) — với mỗi dòng vật tư của
// mẻ nguồn, tự tra lại lô CŨ NHẤT còn tồn tại Kho phân xưởng NGAY LÚC MỞ màn hình này làm gợi
// ý mặc định, cho sửa lại (đổi lô/SL/bỏ dòng) trước khi xác nhận — chỉ khi bấm "Xác nhận" mới
// thật sự gọi add_brew_material (tự tính lại fifo_ok/trừ kho lúc đó, không lệ thuộc gợi ý). ----
async function openCopyMaterialsSuggestModal(brewId, source, target, onDone) {
  const [sourceUsage, targetUsage, lots, materials] = await Promise.all([
    GET(`/brewing/brews/${brewId}/batches/${source.batch_id}/materials`),
    GET(`/brewing/brews/${brewId}/batches/${target.batch_id}/materials`), GET("/lots"), GET("/materials")]);
  if (!sourceUsage.length) throw new Error(`Mẻ ${source.batch_code} chưa có nguyên liệu để gợi ý.`);
  // Mẻ đích đã tự ghi nhận NVL riêng rồi thì không cho gợi ý/copy đè lên nữa — tránh cộng dồn
  // nhầm hoặc ghi đè dữ liệu vận hành đã nhập tay cho đúng mẻ đó.
  if (targetUsage.length) throw new Error(`Mẻ ${target.batch_code} đã có ${targetUsage.length} dòng nguyên liệu riêng — không thể copy/gợi ý đè lên. Hãy xóa hết NVL của mẻ này trước nếu thực sự muốn làm lại.`);
  const lotById = Object.fromEntries(lots.map(l => [l.lot_id, l]));
  const matById = Object.fromEntries(materials.map(m => [m.material_id, m]));
  const workshopLotsAll = sortLotsFifo(lots.filter(l => l.quantity > 0 && l.status !== "on_hold" && /phân xưởng/i.test(l.location || "")));

  // Với mỗi dòng NVL của mẻ nguồn, xác định material_id qua lot_id đã dùng (nếu có) rồi tìm
  // lô cũ nhất CÒN TỒN của đúng vật tư đó ngay lúc này — đây là gợi ý FIFO thật, không phải
  // copy nguyên lô cũ (lô đó có thể đã hết hoặc không còn là lô cũ nhất).
  const rows = sourceUsage.map(u => {
    const srcLot = u.lot_id ? lotById[u.lot_id] : null;
    const materialId = srcLot ? srcLot.material_id : null;
    const candidates = materialId ? workshopLotsAll.filter(l => l.material_id === materialId) : [];
    const suggested = candidates[0] || null;
    return { material_name: u.material_name, quantity: u.quantity, uom: u.uom, materialId, candidates, suggested };
  });

  const lotOptionsHtml = (row) => {
    const opts = row.candidates.map(l =>
      `<option value="${esc(l.lot_id)}" ${row.suggested && l.lot_id === row.suggested.lot_id ? "selected" : ""}>` +
      `${esc(l.lot_code)} (còn ${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})</option>`).join("");
    const freeLabel = row.materialId ? "(nhập tên tự do — không trừ kho)" : `(giữ tên tự do: ${esc(row.material_name)})`;
    return `<option value="">${freeLabel}</option>${opts}`;
  };

  modal(`<h3>Gợi ý NVL — mẻ ${esc(source.batch_code)} → mẻ ${esc(target.batch_code)}</h3>
    <div class="muted" style="margin-bottom:8px">Danh sách vật tư/SL lấy từ mẻ ${esc(source.batch_code)} chỉ là gợi ý — lô đề xuất bên dưới đã tự tra lại theo FIFO (cũ nhất còn tồn tại Kho phân xưởng) NGAY LÚC NÀY, có thể khác lô đã dùng ở mẻ đầu. Xem lại, sửa lô/số lượng hoặc bỏ dòng không cần, rồi bấm "Xác nhận" — lúc đó hệ thống mới thật sự trừ kho cho mẻ ${esc(target.batch_code)}.</div>
    <div class="tablewrap"><table id="cpv_table">
      <thead><tr><th>Nguyên liệu</th><th>Lô đề xuất (FIFO hiện tại)</th><th>FIFO</th><th>Số lượng</th><th>ĐVT</th><th></th></tr></thead>
      <tbody>${rows.map((row, i) => `<tr data-row="${i}">
        <td>${esc(row.material_name)}${!row.materialId ? ' <span class="muted" title="Dòng gốc không gắn lô thật — không tra được FIFO">(tên tự do)</span>' : (!row.candidates.length ? ' <span style="color:var(--red)" title="Kho phân xưởng hiện không còn tồn vật tư này">(hết tồn)</span>' : "")}</td>
        <td><select class="cpv-lot" data-name="${esc(row.material_name)}" data-oldest="${row.candidates[0] ? esc(row.candidates[0].lot_id) : ""}">${lotOptionsHtml(row)}</select></td>
        <td class="cpv-fifo">${fifoBadgeHtml(row.candidates.length ? true : null)}</td>
        <td><input type="number" step="any" class="cpv-qty" value="${row.quantity}" style="width:90px"/></td>
        <td><input class="cpv-uom" value="${esc(row.uom)}" style="width:60px"/></td>
        <td><button type="button" class="btn sm sec" data-cpvremove="${i}">Bỏ dòng</button></td>
      </tr>`).join("")}</tbody>
    </table></div>
    <button class="btn" id="cpv_confirm" style="margin-top:12px">Xác nhận & thêm vào mẻ ${esc(target.batch_code)}</button>`);

  document.querySelectorAll("[data-cpvremove]").forEach(b => b.onclick = () => {
    b.closest("tr").remove();
  });
  // Đổi lô đề xuất (VD chọn lô mới hơn thay vì lô cũ nhất) → cập nhật ngay badge FIFO của
  // dòng đó, để người thao tác thấy rõ lựa chọn của mình có còn đúng FIFO hay không trước
  // khi bấm Xác nhận — không chờ tới lúc server tính lại is_oldest_workshop_lot.
  document.querySelectorAll(".cpv-lot").forEach(sel => sel.onchange = () => {
    const fifoCell = sel.closest("tr").querySelector(".cpv-fifo");
    if (!sel.value) { fifoCell.innerHTML = fifoBadgeHtml(null); return; }
    fifoCell.innerHTML = fifoBadgeHtml(sel.value === sel.dataset.oldest);
  });

  $("cpv_confirm").onclick = () => guard(async () => {
    const trs = [...document.querySelectorAll("#cpv_table tbody tr")];
    if (!trs.length) throw new Error("Không còn dòng nào để thêm — đã bỏ hết.");
    let added = 0;
    for (const tr of trs) {
      const sel = tr.querySelector(".cpv-lot");
      const lotId = sel.value || null;
      const name = lotId ? null : sel.dataset.name;
      const qty = parseFloat(tr.querySelector(".cpv-qty").value);
      const uom = tr.querySelector(".cpv-uom").value.trim() || "kg";
      if (!qty || qty <= 0) continue;
      await POST(`/brewing/brews/${brewId}/batches/${target.batch_id}/materials`, {
        lot_id: lotId, material_name: name, quantity: qty, uom });
      added++;
    }
    if (!added) throw new Error("Không có dòng hợp lệ nào (số lượng phải > 0).");
    toast(`Đã thêm ${added} dòng nguyên liệu cho mẻ ${target.batch_code} — đã trừ tồn Kho phân xưởng theo lô đã chọn`);
    closeModal();
    if (onDone) onDone();
  });
}

// ---- Modal: các mẻ thuộc 1 mã nấu — mỗi mẻ có Chỉ tiêu + NVL riêng ----
async function openBrewBatchesModal(brewId, brewCode, productId, locked = false) {
  const [batches, allLines] = await Promise.all([
    GET(`/brewing/brews/${brewId}/batches`), GET("/lines").catch(() => [])]);
  // Chỉ show dây chuyền NẤU (kind="brewhouse") trong danh mục — khác dây chuyền đóng gói
  // (kind="line") hay tank lên men (kind="tank"), xem models/lines.py::ProductionLine.kind.
  const brewLines = allLines.filter(l => l.kind === "brewhouse" && l.active);
  // locked = mã nấu đã bị khóa (Khóa lô) — vẫn cho xem đầy đủ dữ liệu (Chỉ tiêu/+NVL/Ghi
  // chép nấu là các modal xem-là-chính, backend đã tự chặn ghi qua _assert_unlocked), chỉ ẩn
  // các thao tác THUẦN SỬA/XÓA (Kết thúc, Xóa mẻ, + Thêm mẻ, Gợi ý NVL) vì chúng không có giá
  // trị xem — trước đây cả modal không mở được khi khóa (xem cột "" ở VIEWS.process/sec=nau),
  // khiến không còn cách nào xem lại dữ liệu mẻ đã khóa.
  modal(`<h3>Các mẻ thuộc mã nấu — <code class="k">${esc(brewCode)}</code></h3>
    ${locked ? '<div class="muted" style="margin-bottom:8px">🔒 Mã nấu đã khóa — chỉ xem, không sửa/xóa được.</div>' : ""}
    <div class="tablewrap"><table>
      <thead><tr><th>Số mẻ</th><th>Mã mẻ</th><th>Dây chuyền</th><th>Bắt đầu</th><th>Kết thúc</th><th>Trạng thái</th><th>Ghi chú</th><th></th></tr></thead>
      <tbody>${batches.map(b => `<tr>
        <td>${b.seq ?? "—"}</td><td class="code">${holdBadgeHtml(b)}${esc(b.batch_code)}</td>
        <td class="muted">${esc(b.line_code || "—")}</td>
        <td>${fmt(b.started_at || b.created_at)}</td><td>${fmt(b.ended_at)}</td>
        <td>${badge(b.exec_status === "hoan_thanh" ? "completed" : "in_progress")}${esc(b.exec_status_label)}</td>
        <td class="muted">${esc(b.note || "—")}</td>
        <td style="white-space:nowrap">
          <button class="btn sm sec" data-stageqc="nau|brew_batch|${esc(b.batch_id)}|${esc(productId || "")}||${esc(b.batch_code)}">Chỉ tiêu</button>
          <button class="btn sm sec" data-nvl="${esc(brewId)}|${esc(b.batch_id)}|${esc(b.batch_code)}">+ NVL</button>
          <button class="btn sm sec" data-processlog="${esc(brewId)}|${esc(b.batch_id)}|${esc(b.batch_code)}">Ghi chép nấu</button>
          ${locked ? "" : `<button class="btn sm ${b.exec_status === "hoan_thanh" ? "sec" : ""}" data-finishbatch="${esc(b.batch_id)}" data-endedat="${esc(b.ended_at || "")}">${b.exec_status === "hoan_thanh" ? "Sửa giờ KT" : "Kết thúc"}</button>
          <button class="btn sm sec" data-delbatch="${esc(b.batch_id)}">Xóa</button>`}
        </td></tr>`).join("") || `<tr><td colspan=8 class="muted">Chưa có mẻ nào — thêm mẻ bên dưới.</td></tr>`}</tbody>
    </table></div>
    ${!locked && batches.length > 1 ? `<div class="row" style="margin-top:8px;align-items:end">
      <div class="field"><label>Gợi ý NVL từ mẻ đầu (${esc(batches[0].batch_code)}) cho mẻ</label>
        <select id="bb_copytarget">${batches.slice(1).map(b => `<option value="${esc(b.batch_id)}">${esc(b.batch_code)}</option>`).join("")}</select></div>
      <div class="field"><button class="btn sec" id="bb_copynvl">Xem gợi ý</button></div>
    </div>
    <div class="muted" style="font-size:12px;margin-top:2px">Chỉ gợi ý danh sách vật tư/số lượng — hệ thống tự tìm lô FIFO còn tồn tại thời điểm này (có thể khác lô đã dùng ở mẻ đầu), bạn xem lại và xác nhận trước khi ghi nhận.</div>` : ""}
    ${locked ? "" : `<h4 style="margin-top:14px">+ Thêm mẻ</h4>
    <div class="row">
      <div class="field" style="min-width:220px"><label>Mã mẻ</label><input id="bb_code" type="number" min="1" step="1" placeholder="VD: 123"/></div>
      <div class="field"><label>Dây chuyền nấu *</label><select id="bb_line">
        <option value="">-- Chọn dây chuyền --</option>
        ${brewLines.map(l => `<option value="${esc(l.line_id)}">${esc(l.code)} — ${esc(l.name)}</option>`).join("")}
      </select></div>
      <div class="field"><label>Giờ bắt đầu</label><input id="bb_started" type="datetime-local" value="${toDTLocal(new Date())}"/></div>
      <div class="field"><label>Ghi chú</label><input id="bb_note" placeholder="(tuỳ chọn)"/></div>
      <button class="btn" id="bb_add" style="align-self:flex-end">Thêm</button>
    </div>
    ${brewLines.length === 0 ? '<div class="muted" style="font-size:12px;margin-top:2px">Chưa có dây chuyền nấu nào trong Danh mục — vào Danh mục › Dây chuyền, thêm dây chuyền loại "Nhà nấu (brewhouse)".</div>' : ""}`}`);
  if ($("bb_add")) $("bb_add").onclick = () => guard(async () => {
    // Chỉ thêm 1 mẻ mỗi lần — trước đây cho nhập nhiều mã mẻ cách nhau bằng dấu phẩy
    // nhưng tất cả sẽ dùng chung 1 giờ bắt đầu (sai thực tế), nên bỏ tạo hàng loạt.
    const code = $("bb_code").value.trim();
    // Mã mẻ (số mẻ Braumat) bắt buộc là số nguyên dương, duy nhất trong năm — xem
    // routers/brewing.py::add_brew_batch.
    if (!code || !/^\d+$/.test(code) || parseInt(code, 10) <= 0) throw new Error("Nhập mã mẻ là số nguyên dương (VD: 123).");
    const line_id = $("bb_line").value;
    if (!line_id) throw new Error("Chọn dây chuyền nấu.");
    const note = $("bb_note").value.trim() || null;
    const startedRaw = $("bb_started").value;
    const started_at = startedRaw ? new Date(startedRaw).toISOString() : null;
    await POST(`/brewing/brews/${brewId}/batches`, { batch_code: code, line_id, seq: batches.length + 1, note, started_at });
    toast("Đã thêm mẻ"); render("process"); openBrewBatchesModal(brewId, brewCode, productId, locked);
  });
  document.querySelectorAll("[data-finishbatch]").forEach(b => b.onclick = () => {
    openFinishTimeModal("Kết thúc mẻ " + b.closest("tr").querySelector(".code").textContent, b.dataset.endedat || null, async (ended_at) => {
      await POST(`/brewing/brews/${brewId}/batches/${b.dataset.finishbatch}/finish`, { ended_at });
      toast("Đã lưu giờ kết thúc"); render("process"); openBrewBatchesModal(brewId, brewCode, productId, locked);
    });
  });
  document.querySelectorAll("[data-stageqc]").forEach(b => b.onclick = () => {
    const [stage, scopeType, scopeId, pid, fpid, displayOverride, beerTypeId] = b.dataset.stageqc.split("|");
    openStageQcModal(stage, scopeType, scopeId, { productId: pid || null, finishedProductId: fpid || null,
      beerTypeId: beerTypeId || null, displayId: displayOverride || scopeId.split("__")[0] });
  });
  document.querySelectorAll("[data-nvl]").forEach(b => b.onclick = () => {
    const [bId, batchId, batchCode] = b.dataset.nvl.split("|");
    openBrewMaterialsModal(bId, batchId, batchCode);
  });
  if ($("bb_copynvl")) $("bb_copynvl").onclick = () => guard(async () => {
    const first = batches[0];
    const targetId = $("bb_copytarget").value;
    const target = batches.find(b => b.batch_id === targetId);
    await openCopyMaterialsSuggestModal(brewId, first, target, () => openBrewBatchesModal(brewId, brewCode, productId, locked));
  });
  document.querySelectorAll("[data-processlog]").forEach(b => b.onclick = () => {
    const [bId, batchId, batchCode] = b.dataset.processlog.split("|");
    openBrewProcessLogModal(bId, batchId, batchCode);
  });
  document.querySelectorAll("[data-delbatch]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Xóa mẻ này? Không thể hoàn tác.")) return;
    await DELETE(`/brewing/brews/${brewId}/batches/${b.dataset.delbatch}`);
    toast("Đã xóa"); render("process"); openBrewBatchesModal(brewId, brewCode, productId, locked);
  }));
}

// ---- Modal: Ghi chép nấu (import Step Protocol Braumat + biểu mẫu KCS QT-KCS-QT-BM-05) ----
// Mirror của backend/app/services/braumat_import.py::FORM_SECTIONS/HEADER_FIELDS — giữ
// đồng bộ khi sửa 1 bên. kind: "num"|"text"|"bool". spec:true = có cặp Quy định (Product.
// spec_json, admin sửa) / Thực hiện (BrewProcessLog.manual_json, vận hành sửa).
const BF_HEADER_FIELDS = [
  // batch_number/order_number/gio_bat_dau/gio_ket_thuc là nhân viên tự ghi tay (giống bản
  // giấy), KHÔNG lấy tự động từ batch_code/braumat_order_number/thời gian tính từ bước
  // Braumat — KCS đối chiếu 2 nguồn này với nhau sau (xem dòng "tự động" cạnh mỗi ô).
  { key: "batch_number", label: "Batch number", kind: "text" },
  { key: "order_number", label: "Order Number", kind: "text" },
  { key: "gio_bat_dau", label: "Bắt đầu", kind: "text" },
  { key: "gio_ket_thuc", label: "Kết thúc", kind: "text" },
  { key: "ka", label: "Ca", kind: "text" },
  { key: "truc_ca", label: "Trực ca", kind: "text" },
  { key: "nau_chinh", label: "Nấu chính", kind: "text" },
  { key: "ngay_nhap_gao", label: "Ngày nhập gạo", kind: "text" },
  { key: "ngay_nhap_malt", label: "Ngày nhập malt", kind: "text" },
  { key: "silo", label: "Silo", kind: "text" },
];
const BF_SECTIONS = [
  { key: "rc", title: "Nồi cháo", tempSteps: 2, fields: [
    { key: "rc_gao_truoc_kg", label: "Nghiền gạo ướt — trước (kg)", kind: "num", spec: false },
    { key: "rc_gao_sau_kg", label: "Nghiền gạo ướt — sau (kg)", kind: "num", spec: false },
    { key: "rc_bot_gao_kg", label: "Bột Gạo (kg)", kind: "num", spec: true },
    { key: "rc_nuoc_hl", label: "Nước (hl)", kind: "num", spec: true },
    { key: "rc_ph_nuoc", label: "pH nước", kind: "num", spec: true },
    { key: "rc_termamyl_ml", label: "Termamyl SCDS (ml)", kind: "num", spec: true },
    { key: "rc_toc_do_khuay", label: "Tốc độ khuấy (%)", kind: "num", spec: false },
    { key: "rc_ph", label: "pH (khi cần thiết)", kind: "num", spec: false },
  ] },
  { key: "mt", title: "Nồi malt", tempSteps: 5, fields: [
    { key: "mt_nghien_malt_uot_truoc_kg", label: "Nghiền malt ướt — trước (kg)", kind: "num", spec: false },
    { key: "mt_nghien_malt_uot_sau_kg", label: "Nghiền malt ướt — sau (kg)", kind: "num", spec: false },
    { key: "mt_malt_anh_kg", label: "Malt Anh (kg)", kind: "num", spec: true },
    { key: "mt_malt_uc_kg", label: "Malt Úc (kg)", kind: "num", spec: true },
    { key: "mt_malt_duc_kg", label: "Malt Đức (kg)", kind: "num", spec: true },
    { key: "mt_neutrase_ml", label: "Neutrase (ml)", kind: "num", spec: true },
    { key: "mt_ultraprime_ml", label: "Ultraprime (ml)", kind: "num", spec: true },
    { key: "mt_attenuazym_pro_ml", label: "Attenuazym Pro (ml)", kind: "num", spec: false },
    { key: "mt_cacl2_kg", label: "CaCl2 (kg)", kind: "num", spec: true },
    { key: "mt_caso4_kg", label: "CaSO4 (kg)", kind: "num", spec: true },
    { key: "mt_nuoc_hl", label: "Nước (hl)", kind: "num", spec: true },
    { key: "mt_ph_nuoc", label: "pH nước", kind: "num", spec: true },
    { key: "mt_kt_i2", label: "KT I2 (Đ/K)", kind: "text", spec: false },
    { key: "mt_kt_ba_malt", label: "KT bã malt (Đ/K)", kind: "text", spec: false },
  ] },
  { key: "lt", title: "Nồi lọc bã",
    timeSteps: [
      { key: "lt_chuyen", label: "Chuyển" }, { key: "lt_quayvong1", label: "Quay vòng" },
      { key: "lt_dichcot_time", label: "Dịch cốt" }, { key: "lt_quayvong2", label: "Quay vòng" },
      { key: "lt_trangba", label: "Tráng bã" },
    ],
    fields: [
    { key: "lt_dichcot_luong_hl", label: "Dịch cốt — Lượng (hl)", kind: "num", spec: false },
    { key: "lt_dichcot_bx", label: "Dịch cốt — %Bx", kind: "num", spec: false },
    { key: "lt_dichcot_nguoi", label: "Dịch cốt — Nấu chính", kind: "text", spec: false },
    { key: "lt_nuoctrang_luong_hl", label: "Nước tráng — Lượng (hl)", kind: "num", spec: false },
    { key: "lt_nuoctrang_bx", label: "Nước tráng — %Bx", kind: "num", spec: false },
    { key: "lt_nuoctrang_nguoi", label: "Nước tráng — Nấu chính", kind: "text", spec: false },
    { key: "lt_percent_bx_ket_thuc_loc_trang", label: "%Bx kết thúc lọc trong", kind: "num", spec: false },
    { key: "lt_kiem_tra_bao_muc", label: "Đã kiểm tra báo mức bầu xả bã", kind: "bool", spec: false },
  ] },
  { key: "wk", title: "Đun hoa",
    hopRows: [{ key: "wk_houb1", label: "Houb1" }, { key: "wk_houb2", label: "Houb2" }],
    fields: [
    { key: "wk_znso4_g", label: "ZnSO4 (g)", kind: "num", spec: false },
    { key: "wk_ph", label: "pH (5,2 - 5,6)", kind: "num", spec: false },
    { key: "wk_percent_bx_ket_thuc_dun_hoa", label: "%Bx kết thúc đun hoa", kind: "num", spec: false },
    { key: "wk_nuoc_cho_them_hl", label: "Nước cho thêm (hl)", kind: "num", spec: false },
  ] },
  { key: "whp", title: "Lắng xoáy + hạ T°", fields: [
    { key: "whp_chuyen_gio", label: "Chuyển (giờ)", kind: "text", spec: true },
    { key: "whp_thoi_gian_lang_phut", label: "Thời gian lắng (phút)", kind: "num", spec: true },
    { key: "whp_t0_chuyen_dich", label: "T° chuyển dịch (°C)", kind: "num", spec: true },
    { key: "whp_oxy_lit_phut", label: "Oxy (lít/phút)", kind: "num", spec: true },
    { key: "whp_percent_bx", label: "%Bx (13,15 - 13,25)", kind: "num", spec: false },
    { key: "whp_tong_luong_dich_hl", label: "Tổng lượng dịch (hl)", kind: "num", spec: false },
    { key: "whp_ph", label: "pH", kind: "num", spec: false },
    { key: "whp_axit", label: "Axit", kind: "num", spec: false },
    { key: "whp_maturex_pro_added", label: "Đã bổ sung Maturex Pro (0,5 ml/hl)", kind: "bool", spec: false },
    { key: "whp_maturex_batdau", label: "Maturex — bắt đầu", kind: "text", spec: false },
    { key: "whp_maturex_ketthuc", label: "Maturex — kết thúc", kind: "text", spec: false },
    { key: "whp_brew_clarex_added", label: "Đã bổ sung Brew Clarex (0,65 ml/hl)", kind: "bool", spec: false },
    { key: "whp_clarex_batdau", label: "Clarex — bắt đầu", kind: "text", spec: false },
    { key: "whp_clarex_ketthuc", label: "Clarex — kết thúc", kind: "text", spec: false },
    { key: "whp_ht_uv_chuyen_dich", label: "HT UV chuyển dịch (Đ/K)", kind: "bool", spec: false },
  ] },
];

function _bfInput(key, kind, value, cls) {
  if (kind === "bool") {
    return `<input type="checkbox" class="${cls}" data-key="${key}" data-bool="1" ${value ? "checked" : ""}/>`;
  }
  const type = kind === "num" ? "number" : "text";
  const step = kind === "num" ? ' step="any"' : "";
  return `<input type="${type}"${step} class="${cls}" data-key="${key}" data-kind="${kind}"
    value="${esc(value === null || value === undefined ? "" : String(value))}" style="width:100px"/>`;
}
const _bfDash = (v) => (v === null || v === undefined || v === "" ? "—" : esc(String(v)));

function _bfFieldRow(f, specVals, manualVals, mode) {
  if (mode === "spec") {
    return `<tr><td>${esc(f.label)}</td><td>${_bfInput(f.key, f.kind, specVals?.[f.key], "bf-spec")}</td></tr>`;
  }
  return `<tr><td>${esc(f.label)}</td>
    <td class="muted">${f.spec ? _bfDash(specVals?.[f.key]) : ""}</td>
    <td>${_bfInput(f.key, f.kind, manualVals?.[f.key], "pl-manual")}</td></tr>`;
}

function _bfTempStepsHtml(sectionKey, n, specVals, manualVals, mode) {
  let rows = "";
  for (let i = 1; i <= n; i++) {
    const base = `${sectionKey}_step${i}`;
    const specV = specVals?.[`${base}_nhietdo`];
    if (mode === "spec") {
      rows += `<tr><td>Bước ${i} — Nhiệt độ (°C)</td><td>${_bfInput(`${base}_nhietdo`, "num", specV, "bf-spec")}</td></tr>`;
    } else {
      rows += `<tr><td>Bước ${i}</td><td class="muted">${_bfDash(specV)}</td>
        <td>${_bfInput(`${base}_nhietdo`, "num", manualVals?.[`${base}_nhietdo`], "pl-manual")}</td>
        <td>${_bfInput(`${base}_batdau`, "text", manualVals?.[`${base}_batdau`], "pl-manual")}</td>
        <td>${_bfInput(`${base}_dung`, "text", manualVals?.[`${base}_dung`], "pl-manual")}</td>
        <td>${_bfInput(`${base}_giunhiet`, "num", manualVals?.[`${base}_giunhiet`], "pl-manual")}</td>
        <td>${_bfInput(`${base}_ketthuc`, "text", manualVals?.[`${base}_ketthuc`], "pl-manual")}</td></tr>`;
    }
  }
  if (mode === "spec") {
    return `<table class="bf-mini"><thead><tr><th>Bước</th><th>Quy định (°C)</th></tr></thead><tbody>${rows}</tbody></table>`;
  }
  return `<div class="tablewrap"><table class="bf-mini">
    <thead><tr><th>Bước</th><th>Quy định (°C)</th><th>Nhiệt độ TH (°C)</th><th>Bắt đầu</th><th>Dừng</th><th>Giữ nhiệt (phút)</th><th>Kết thúc</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

function _bfTimeStepsHtml(steps, manualVals) {
  const rows = steps.map(s => `<tr><td>${esc(s.label)}</td>
    <td>${_bfInput(`${s.key}_batdau`, "text", manualVals?.[`${s.key}_batdau`], "pl-manual")}</td>
    <td>${_bfInput(`${s.key}_ketthuc`, "text", manualVals?.[`${s.key}_ketthuc`], "pl-manual")}</td></tr>`).join("");
  return `<div class="tablewrap"><table class="bf-mini"><thead><tr><th></th><th>Bắt đầu</th><th>Kết thúc</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

function _bfHopRowsHtml(rows, manualVals) {
  const trs = rows.map(r => `<tr><td>${esc(r.label)}</td>
    <td>${_bfInput(`${r.key}_hoacao_kg`, "num", manualVals?.[`${r.key}_hoacao_kg`], "pl-manual")}</td>
    <td>${_bfInput(`${r.key}_hoavien_kg`, "num", manualVals?.[`${r.key}_hoavien_kg`], "pl-manual")}</td>
    <td>${_bfInput(`${r.key}_rho_kg`, "num", manualVals?.[`${r.key}_rho_kg`], "pl-manual")}</td>
    <td>${_bfInput(`${r.key}_batdau`, "text", manualVals?.[`${r.key}_batdau`], "pl-manual")}</td>
    <td>${_bfInput(`${r.key}_giunhiet`, "num", manualVals?.[`${r.key}_giunhiet`], "pl-manual")}</td>
    <td>${_bfInput(`${r.key}_ketthuc`, "text", manualVals?.[`${r.key}_ketthuc`], "pl-manual")}</td></tr>`).join("");
  return `<div class="tablewrap"><table class="bf-mini">
    <thead><tr><th></th><th>Hoa Cao (kg)</th><th>Hoa viên Đức (kg)</th><th>RHO Mỹ (kg)</th><th>Bắt đầu</th><th>Giữ nhiệt (dừng) phút</th><th>Kết thúc</th></tr></thead>
    <tbody>${trs}</tbody></table></div>`;
}

function _bfSectionHtml(sec, specVals, manualVals) {
  let html = `<table class="bf-mini"><thead><tr><th>Trường</th><th>Quy định</th><th>Thực hiện</th></tr></thead>
    <tbody>${sec.fields.map(f => _bfFieldRow(f, specVals, manualVals, "log")).join("")}</tbody></table>`;
  if (sec.tempSteps) html += _bfTempStepsHtml(sec.key, sec.tempSteps, specVals, manualVals, "log");
  if (sec.timeSteps) html += _bfTimeStepsHtml(sec.timeSteps, manualVals);
  if (sec.hopRows) html += _bfHopRowsHtml(sec.hopRows, manualVals);
  return html;
}

function _bfSpecSectionHtml(sec, specVals) {
  const specFields = sec.fields.filter(f => f.spec);
  let html = specFields.length ? `<table class="bf-mini"><thead><tr><th>Trường</th><th>Quy định</th></tr></thead>
    <tbody>${specFields.map(f => _bfFieldRow(f, specVals, null, "spec")).join("")}</tbody></table>` : "";
  if (sec.tempSteps) html += _bfTempStepsHtml(sec.key, sec.tempSteps, specVals, null, "spec");
  return html || '<div class="muted">Công đoạn này không có Quy định cấu hình được.</div>';
}

function _collectBfManualPayload() {
  const payload = {};
  document.querySelectorAll(".pl-manual").forEach(el => {
    const key = el.dataset.key;
    if (el.dataset.bool) payload[key] = el.checked;
    else if (el.dataset.kind === "num") payload[key] = el.value === "" ? null : parseFloat(el.value);
    else payload[key] = el.value.trim() === "" ? null : el.value.trim();
  });
  return payload;
}
function _collectBfSpecPayload() {
  const payload = {};
  document.querySelectorAll(".bf-spec").forEach(el => {
    const key = el.dataset.key;
    if (el.dataset.bool) payload[key] = el.checked;
    else if (el.dataset.kind === "num") payload[key] = el.value === "" ? null : parseFloat(el.value);
    else payload[key] = el.value.trim() === "" ? null : el.value.trim();
  });
  return payload;
}

// ---- Modal: Quy định công nghệ nấu theo dịch bia (chỉ admin/master.manage) ----
async function openBrewSpecModal(product) {
  const spec = await GET(`/products/${product.product_id}/brew-spec`);
  modal(`<h3>Quy định nấu — ${esc(product.name)} <code class="k">${esc(product.code)}</code></h3>
    <div class="muted" style="margin-bottom:8px">Giá trị chuẩn (Quy định) theo biểu mẫu QT-KCS-QT-BM-05 — hiện cạnh ô Thực hiện khi vận hành ghi chép nấu cho mẻ dùng dịch bia này.</div>
    <div style="max-height:65vh;overflow-y:auto">
    ${BF_SECTIONS.map(sec => `<div class="panel" style="margin-top:10px"><h2 style="font-size:15px">${esc(sec.title)}</h2>
      ${_bfSpecSectionHtml(sec, spec)}</div>`).join("")}
    </div>
    <button class="btn" id="bfspec_save" style="margin-top:12px">Lưu Quy định</button>`);
  $("bfspec_save").onclick = () => guard(async () => {
    await PUT(`/products/${product.product_id}/brew-spec`, _collectBfSpecPayload());
    toast("Đã lưu Quy định nấu"); closeModal();
  });
}

function _computeOverallTiming(steps) {
  const starts = steps.map(s => s.start_at).filter(Boolean).sort();
  const ends = steps.map(s => s.end_at).filter(Boolean).sort();
  return { start: starts[0] || null, end: ends[ends.length - 1] || null };
}

function _bfPrintFieldRows(sec, specVals, manualVals) {
  return sec.fields.map(f => `<tr><td>${esc(f.label)}</td><td>${f.spec ? _bfDash(specVals?.[f.key]) : ""}</td>
    <td>${_bfDash(manualVals?.[f.key])}</td></tr>`).join("");
}
function _bfPrintTempSteps(sectionKey, n, specVals, manualVals) {
  let rows = "";
  for (let i = 1; i <= n; i++) {
    const base = `${sectionKey}_step${i}`;
    rows += `<tr><td>Bước ${i}</td><td>${_bfDash(specVals?.[`${base}_nhietdo`])}</td>
      <td>${_bfDash(manualVals?.[`${base}_nhietdo`])}</td><td>${_bfDash(manualVals?.[`${base}_batdau`])}</td>
      <td>${_bfDash(manualVals?.[`${base}_dung`])}</td><td>${_bfDash(manualVals?.[`${base}_giunhiet`])}</td>
      <td>${_bfDash(manualVals?.[`${base}_ketthuc`])}</td></tr>`;
  }
  return `<table class="pf-tbl"><thead><tr><th>Bước</th><th>Quy định (°C)</th><th>TH (°C)</th><th>Bắt đầu</th><th>Dừng</th><th>Giữ nhiệt</th><th>Kết thúc</th></tr></thead><tbody>${rows}</tbody></table>`;
}
function _bfPrintTimeSteps(steps, manualVals) {
  const rows = steps.map(s => `<tr><td>${esc(s.label)}</td><td>${_bfDash(manualVals?.[`${s.key}_batdau`])}</td>
    <td>${_bfDash(manualVals?.[`${s.key}_ketthuc`])}</td></tr>`).join("");
  return `<table class="pf-tbl"><thead><tr><th></th><th>Bắt đầu</th><th>Kết thúc</th></tr></thead><tbody>${rows}</tbody></table>`;
}
function _bfPrintHopRows(rows, manualVals) {
  const trs = rows.map(r => `<tr><td>${esc(r.label)}</td><td>${_bfDash(manualVals?.[`${r.key}_hoacao_kg`])}</td>
    <td>${_bfDash(manualVals?.[`${r.key}_hoavien_kg`])}</td><td>${_bfDash(manualVals?.[`${r.key}_rho_kg`])}</td>
    <td>${_bfDash(manualVals?.[`${r.key}_batdau`])}</td><td>${_bfDash(manualVals?.[`${r.key}_giunhiet`])}</td>
    <td>${_bfDash(manualVals?.[`${r.key}_ketthuc`])}</td></tr>`).join("");
  return `<table class="pf-tbl"><thead><tr><th></th><th>Hoa Cao</th><th>Hoa viên Đức</th><th>RHO Mỹ</th><th>Bắt đầu</th><th>Giữ nhiệt</th><th>Kết thúc</th></tr></thead><tbody>${trs}</tbody></table>`;
}

function _bfPrintSectionBody(sec, data) {
  let body = `<table class="pf-tbl"><thead><tr><th>Trường</th><th>QĐ</th><th>TH</th></tr></thead>
    <tbody>${_bfPrintFieldRows(sec, data.spec, data.manual)}</tbody></table>`;
  if (sec.tempSteps) body += _bfPrintTempSteps(sec.key, sec.tempSteps, data.spec, data.manual);
  if (sec.timeSteps) body += _bfPrintTimeSteps(sec.timeSteps, data.manual);
  if (sec.hopRows) body += _bfPrintHopRows(sec.hopRows, data.manual);
  return body;
}

function printBrewForm(data, batchCode) {
  const timing = _computeOverallTiming(data.steps);
  const byKey = Object.fromEntries(BF_SECTIONS.map(s => [s.key, s]));
  const kaFields = ["ka", "truc_ca", "nau_chinh"].map(k => BF_HEADER_FIELDS.find(f => f.key === k));
  const header = kaFields.map(f => `<div><b>${esc(f.label)}:</b> ${_bfDash(data.manual?.[f.key])}</div>`).join("");
  // Bố cục 1 trang A4 nằm ngang: header rồi 3 cột dọc cân đối theo số dòng ước lượng
  // (Nồi malt 1 mình đã ~19 dòng nên ghép 3 cột thay vì 2 mới đủ chỗ vừa 1 trang, không
  // xếp cứng theo đúng nhóm trong file giấy vì bản giấy là 1 cột dài, không giới hạn cao).
  const sectionBlock = (title, bodyHtml) => `<div class="pf-section"><h3>${esc(title)}</h3>${bodyHtml}</div>`;
  const colA = [byKey.rc, byKey.lt].map(sec => sectionBlock(sec.title, _bfPrintSectionBody(sec, data))).join("");
  const colB = [byKey.mt].map(sec => sectionBlock(sec.title, _bfPrintSectionBody(sec, data))).join("")
    + sectionBlock("Ghi chú", `<div class="pf-note">${esc(data.note || "")}</div>`);
  const colC = [byKey.wk, byKey.whp].map(sec => sectionBlock(sec.title, _bfPrintSectionBody(sec, data))).join("");
  const html = `<!doctype html><html><head><meta charset="utf-8"/><title>Biểu mẫu nấu — ${esc(batchCode)}</title>
    <style>
      @page { size: A4 landscape; margin: 8mm; }
      * { box-sizing: border-box; }
      html,body{width:281mm}
      body{font-family:Arial,Helvetica,sans-serif;color:#000;background:#fff;margin:0;font-size:11px;line-height:1.2}
      h1{font-size:15px;margin:0 0 2px;text-align:center}
      h2{font-size:12px;margin:0 0 5px;text-align:center;font-weight:normal}
      h3{font-size:11.5px;margin:0 0 2px;border-bottom:1.5px solid #000;padding-bottom:1px;text-transform:uppercase}
      .pf-body{display:grid;grid-template-columns:1fr 1fr 1fr;gap:0 14px;align-items:start}
      .pf-section{margin-bottom:5px}
      .pf-header{display:grid;grid-template-columns:1fr 1.3fr 1fr;gap:0 16px;border:1.5px solid #000;padding:4px 10px;margin-bottom:5px}
      .pf-header > div > div{margin-bottom:1px}
      table.pf-tbl{border-collapse:collapse;width:100%;margin-bottom:3px}
      table.pf-tbl th, table.pf-tbl td{border:1px solid #000;padding:1px 4px;text-align:left;font-size:10px}
      table.pf-tbl th{background:#eee;font-weight:normal}
      .pf-note{border:1.5px solid #000;padding:5px;min-height:40px;white-space:pre-wrap;font-size:11px}
      .pf-auto{color:#555;font-weight:normal}
      .pf-kcs{border-top:1px solid #000;margin-top:4px;padding-top:2px}
    </style></head><body>
    <h1>1.5.2/2025/QT-KCS-QT-BM-05: CÔNG NGHỆ</h1>
    <h2>NẤU BIA ${esc((data.braumat_recipe || "").toUpperCase())} — Mã nấu ${esc(data.brew_code || "")} — Mẻ ${esc(batchCode)}</h2>
    <div class="pf-header">
      <div><div><b>Batch number:</b> ${_bfDash(data.manual?.batch_number)}
        ${batchCode ? `<span class="pf-auto"> (mã mẻ hệ thống: ${esc(batchCode)})</span>` : ""}</div>
        <div><b>Ngày nhập gạo:</b> ${_bfDash(data.manual?.ngay_nhap_gao)}</div>
        <div><b>Ngày nhập malt:</b> ${_bfDash(data.manual?.ngay_nhap_malt)}</div>
        <div><b>Silo:</b> ${_bfDash(data.manual?.silo)}</div></div>
      <div><div><b>Order Number:</b> ${_bfDash(data.manual?.order_number)}
        ${data.braumat_order_number ? `<span class="pf-auto"> (tự động: ${esc(data.braumat_order_number)})</span>` : ""}</div></div>
      <div><div><b>Bắt đầu:</b> ${_bfDash(data.manual?.gio_bat_dau)} &nbsp; <b>Kết thúc:</b> ${_bfDash(data.manual?.gio_ket_thuc)}
        ${fmt(timing.start) !== "—" ? `<span class="pf-auto"> (tự động: ${fmt(timing.start)} → ${fmt(timing.end)})</span>` : ""}</div>
        ${header}
        <div class="pf-kcs"><b>KCS kiểm tra:</b> _______________________ (Ký, ghi rõ họ tên)</div></div>
    </div>
    <div class="pf-body"><div>${colA}</div><div>${colB}</div><div>${colC}</div></div>
    </body></html>`;
  const w = window.open("", "_blank");
  if (!w) { toast("Trình duyệt chặn cửa sổ in — vui lòng cho phép popup.", "err"); return; }
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 300);
}

// ---- Modal: Ghi chép lên men (biểu mẫu giấy BM 1.11 (06) BIỂU THEO DÕI LÊN MEN) ----
// Mirror của backend/app/services/ferment_log.py::HEADER_FIELDS — giữ đồng bộ khi sửa 1
// bên. Không có import Braumat (chưa có file mẫu — xem ghi chú ở tab import bên dưới).
// order_number/batch_number nhập tay (mirror BF_HEADER_FIELDS) — giá trị Braumat lấy từ mẻ
// nấu nguồn (auto.braumat_order_number/batch_number) chỉ hiện kèm làm gợi ý đối chiếu, vì
// không phải mẻ nấu nguồn nào cũng có import Braumat.
const FL_HEADER_FIELDS = [
  { key: "order_number", label: "Order Number", kind: "text" },
  { key: "batch_number", label: "Batch Number", kind: "text" },
  { key: "kieu_men", label: "Kiểu men", kind: "text" },
  { key: "luu_luong_khi_bs", label: "Lưu lượng khí bổ sung, Lít/Phút", kind: "num" },
  { key: "mat_do_ml_b", label: "Mật độ tế bào, 10⁶/ml (B)", kind: "num" },
  { key: "pct_song_c", label: "% tế bào sống (C)", kind: "num" },
  { key: "kg_can_cap_d", label: "Khối lượng men cần cấp, kg (D)", kind: "num" },
  { key: "mat_do_ban_dau_e", label: "Mật độ ban đầu, 10⁶/ml (E)", kind: "num" },
  { key: "kg_cap_thuc_j", label: "Khối lượng men cấp thực, kg (J)", kind: "num" },
  { key: "mat_do_tach_f", label: "Tách men — mật độ, 10⁶/ml (F)", kind: "num" },
  { key: "tach_men_kg_g", label: "Tách men — khối lượng, kg (G)", kind: "num" },
  { key: "tach_men_pct_song", label: "Tách men — % tế bào sống", kind: "num" },
  { key: "day_full_at", label: "Đầy (giờ, ngày)", kind: "text" },
  { key: "nguoi_lenh_day", label: "Người lệnh (đầy tank)", kind: "text" },
  { key: "nguoi_nhan_lenh_day", label: "Người nhận lệnh (đầy tank)", kind: "text" },
  { key: "truc_ca_day", label: "Trực ca (đầy tank)", kind: "text" },
];
const FL_DAILY_ROWS = [
  { key: "reading_date", label: "Ngày tháng", kind: "date" },
  { key: "nhiet_do_c", label: "Nhiệt độ, °C", kind: "num" },
  { key: "do_s", label: "°S", kind: "num" },
  { key: "mat_do_tb", label: "Mật độ tb, 10⁶/ml", kind: "num" },
  { key: "kcs", label: "KCS", kind: "select",
    options: [["", "—"], ["dat", "Đạt"], ["khong_dat", "Không đạt"]] },
  { key: "truc_ca", label: "Trực ca", kind: "select",
    options: [["", "—"], ["dat", "Đạt"], ["khong_dat", "Không đạt"]] },
];
const FL_KCS_LABELS = { dat: "Đạt", khong_dat: "Không đạt" };

function _flDash(v) { return (v === null || v === undefined || v === "" ? "—" : esc(String(v))); }

function _flAuditText(by, at) { return by ? `${esc(by)} · ${fmt(at)}` : "—"; }

function _flDayInput(key, kind, value, dayNo, options) {
  if (kind === "select") {
    return `<select class="fl-daily-cell" data-flkey="${key}" data-flday="${dayNo}" data-flkind="${kind}">
      ${(options || []).map(([v, label]) => `<option value="${v}" ${(value || "") === v ? "selected" : ""}>${esc(label)}</option>`).join("")}
    </select>`;
  }
  const type = kind === "num" ? "number" : (kind === "date" ? "date" : "text");
  const step = kind === "num" ? ' step="any"' : "";
  const width = kind === "date" ? 130 : 88;
  return `<input type="${type}"${step} class="fl-daily-cell" data-flkey="${key}" data-flday="${dayNo}" data-flkind="${kind}"
    value="${esc(value === null || value === undefined ? "" : String(value))}" style="width:${width}px"/>`;
}

function _flHaphuInput(key, value, idx) {
  return `<input type="text" class="fl-haphu-cell" data-hpkey="${key}" data-hpidx="${idx}"
    value="${esc(value === null || value === undefined ? "" : String(value))}" style="width:120px"/>`;
}

function _collectFlManualPayload() {
  const payload = {};
  document.querySelectorAll(".fl-manual").forEach(el => {
    const key = el.dataset.key;
    if (el.dataset.kind === "num") payload[key] = el.value === "" ? null : parseFloat(el.value);
    else payload[key] = el.value.trim() === "" ? null : el.value.trim();
  });
  return payload;
}

function _flChartHtml(readings) {
  const xLabels = readings.map(r => r.day_no);
  const left = [
    { label: "Nhiệt độ, °C", color: "#3498db", points: readings.map(r => ({ x: r.day_no, value: r.nhiet_do_c })) },
    { label: "°S", color: "#f5a623", points: readings.map(r => ({ x: r.day_no, value: r.do_s })) },
  ];
  const right = [
    { label: "Mật độ tb, 10⁶/ml", color: "#2ecc71", points: readings.map(r => ({ x: r.day_no, value: r.mat_do_tb })) },
  ];
  return CH.lineDualAxis(left, right, xLabels, { height: 220 });
}

async function openFermentProcessLogModal(fermentId, lmCode) {
  const data = await GET(`/brewing/ferments/${fermentId}/process-log`);
  const auto = data.auto;
  let dayNos;
  const readingsByDay = {};
  if (data.readings.length) {
    dayNos = data.readings.map(r => r.day_no);
    data.readings.forEach(r => { readingsByDay[r.day_no] = { ...r }; });
  } else {
    // Mặc định 20 ngày, ngày 1 = ngày kết thúc nấu (auto.kt_date) — nếu chưa có kt_date thì để
    // trống, vẫn hiện đủ 20 cột để nhập.
    dayNos = Array.from({ length: 20 }, (_, i) => i + 1);
    if (auto.kt_date) {
      const base = new Date(auto.kt_date);
      dayNos.forEach(d => {
        const dt = new Date(base); dt.setDate(dt.getDate() + (d - 1));
        readingsByDay[d] = { day_no: d, reading_date: toISODateLocal(dt) };
      });
    }
  }
  let haphuEvents = (data.ha_phu_events || []).map(e => ({ ...e }));

  const autoFieldsHtml = `<div class="row" style="flex-wrap:wrap">
    <div class="field"><label>Số mẻ</label><div>${_flDash(auto.so_me)}</div></div>
    <div class="field"><label>Số Tank</label><div>${_flDash(auto.so_tank)}</div></div>
    <div class="field"><label>Thể tích Tank, hl</label><div>${_flDash(auto.the_tich_tank)}</div></div>
    <div class="field"><label>Thế hệ</label><div>${_flDash(auto.the_he)}</div></div>
  </div>`;
  // order_number/batch_number nhập tay — giá trị Braumat (nếu mẻ nấu nguồn có import) chỉ
  // hiện kèm làm gợi ý đối chiếu, không tự điền vào ô (mirror BF_HEADER_FIELDS/_headerAutoHint).
  const _flAutoHint = { order_number: auto.braumat_order_number, batch_number: auto.braumat_batch_number };
  const manualFieldsHtml = `<div class="row" style="flex-wrap:wrap">${FL_HEADER_FIELDS.map(f => `<div class="field">
    <label>${esc(f.label)}</label>${_bfInput(f.key, f.kind, data.manual?.[f.key], "fl-manual")}
    ${_flAutoHint[f.key] ? `<span class="muted" style="font-size:11px">Braumat (mẻ nấu nguồn): ${esc(_flAutoHint[f.key])}</span>` : ""}</div>`).join("")}</div>`;

  modal(`<h3>Ghi chép lên men — lô LM <code class="k">${esc(lmCode)}</code></h3>
    <div class="muted" style="margin-bottom:8px">Biểu mẫu BM 1.11 (06) — nhập tay bảng thông tin đầu, bảng theo ngày (nhiệt độ/°S/mật độ tế bào) và các mốc "Hạ phụ".</div>
    <div class="row" style="align-items:flex-end">
      <div class="field" style="flex:1"><label>Import dữ liệu Braumat (chưa hỗ trợ)</label>
        <input type="file" disabled/>
        <span class="muted" style="font-size:11px">Chưa có định dạng mẫu Braumat cho lên men — sẽ bổ sung khi có file mẫu.</span></div>
      <button class="btn sec" id="fl_print">🖨️ In biểu mẫu</button>
    </div>
    <div style="max-height:60vh;overflow-y:auto;margin-top:10px">
    <div class="panel"><h2 style="font-size:15px">Thông tin đầu</h2>
      ${autoFieldsHtml}${manualFieldsHtml}
    </div>
    <div class="panel" style="margin-top:10px"><h2 style="font-size:15px">Biểu đồ theo dõi lên men</h2>
      <div id="fl_chart">${_flChartHtml(data.readings)}</div>
    </div>
    <div class="panel" style="margin-top:10px"><h2 style="font-size:15px">Bảng theo ngày</h2>
      <div id="fl_daily_wrap"></div>
      <button class="btn" id="fl_save_readings" style="margin-top:8px">Lưu bảng ngày</button>
    </div>
    <div class="panel" style="margin-top:10px"><h2 style="font-size:15px">Hạ phụ</h2>
      <div class="tablewrap"><table><thead><tr><th>Thời điểm</th><th>Người lệnh</th><th>Người nhận lệnh</th><th>Trực ca</th><th></th></tr></thead>
        <tbody id="fl_haphu_wrap"></tbody></table></div>
      <button class="btn sm sec" id="fl_addhaphu" style="margin-top:6px">+ Thêm mốc hạ phụ</button>
    </div>
    <div class="panel" style="margin-top:10px"><h2 style="font-size:15px">Ghi chú</h2>
      <textarea id="fl_note" style="width:100%;min-height:50px">${esc(data.note || "")}</textarea></div>
    </div>
    <button class="btn" id="fl_save" style="margin-top:12px">Lưu</button>`);

  function renderDailyTable() {
    const auditRow = (label, getBy, getAt) => `<tr><td class="muted" style="font-size:11px">${esc(label)}</td>
      ${dayNos.map(d => { const r = readingsByDay[d] || {};
        return `<td class="muted" style="font-size:11px">${_flAuditText(getBy(r), getAt(r))}</td>`; }).join("")}</tr>`;
    const rowsHtml = FL_DAILY_ROWS.map(f => {
      let html = `<tr><td>${esc(f.label)}</td>
        ${dayNos.map(d => `<td>${_flDayInput(f.key, f.kind, (readingsByDay[d] || {})[f.key], d, f.options)}</td>`).join("")}</tr>`;
      if (f.key === "mat_do_tb") html += auditRow("Đo đạc bởi", r => r.measured_by, r => r.measured_at);
      if (f.key === "kcs") html += auditRow("KCS bởi", r => r.kcs_by, r => r.kcs_at);
      if (f.key === "truc_ca") html += auditRow("Trực ca bởi", r => r.truc_ca_by, r => r.truc_ca_at);
      return html;
    }).join("");
    $("fl_daily_wrap").innerHTML = `<div class="tablewrap"><table class="bf-mini">
      <thead><tr><th>Trường</th>${dayNos.map(d => `<th>Ngày ${d}</th>`).join("")}</tr></thead>
      <tbody>${rowsHtml}</tbody></table></div>
      <button class="btn sm sec" id="fl_addday" style="margin-top:6px">+ Thêm ngày</button>`;
    document.querySelectorAll(".fl-daily-cell").forEach(el => {
      const handler = () => {
        const d = parseInt(el.dataset.flday, 10), k = el.dataset.flkey;
        readingsByDay[d] = readingsByDay[d] || { day_no: d };
        readingsByDay[d][k] = el.dataset.flkind === "num" ? (el.value === "" ? null : parseFloat(el.value)) : (el.value.trim() || null);
      };
      el.oninput = handler; el.onchange = handler;
    });
    $("fl_addday").onclick = () => { dayNos.push((dayNos[dayNos.length - 1] || 0) + 1); renderDailyTable(); };
  }
  renderDailyTable();

  function renderHaphu() {
    $("fl_haphu_wrap").innerHTML = haphuEvents.map((ev, idx) => `<tr>
      <td>${_flHaphuInput("at", ev.at, idx)}</td>
      <td>${_flHaphuInput("nguoi_lenh", ev.nguoi_lenh, idx)}</td>
      <td>${_flHaphuInput("nguoi_nhan_lenh", ev.nguoi_nhan_lenh, idx)}</td>
      <td>${_flHaphuInput("truc_ca", ev.truc_ca, idx)}</td>
      <td><button class="btn sm sec" data-delhaphu="${idx}">Xóa</button></td></tr>`).join("")
      || `<tr><td colspan=5 class="muted">Chưa có mốc hạ phụ nào.</td></tr>`;
    document.querySelectorAll(".fl-haphu-cell").forEach(el => el.oninput = () => {
      const idx = parseInt(el.dataset.hpidx, 10);
      haphuEvents[idx][el.dataset.hpkey] = el.value.trim() || null;
    });
    document.querySelectorAll("[data-delhaphu]").forEach(b => b.onclick = () => {
      haphuEvents.splice(parseInt(b.dataset.delhaphu, 10), 1);
      renderHaphu();
    });
  }
  renderHaphu();
  $("fl_addhaphu").onclick = () => { haphuEvents.push({ at: null, nguoi_lenh: null, nguoi_nhan_lenh: null, truc_ca: null }); renderHaphu(); };

  $("fl_print").onclick = () => printFermentForm({ ...data, manual_current: _collectFlManualPayload() }, lmCode);

  $("fl_save_readings").onclick = () => guard(async () => {
    const readings = dayNos.map(d => ({ day_no: d, ...(readingsByDay[d] || {}) }));
    await PUT(`/brewing/ferments/${fermentId}/process-log/readings`, { readings });
    toast("Đã lưu bảng theo ngày"); openFermentProcessLogModal(fermentId, lmCode);
  });
  $("fl_save").onclick = () => guard(async () => {
    const payload = _collectFlManualPayload();
    payload.note = $("fl_note").value.trim() || null;
    payload.ha_phu_events = haphuEvents;
    // Nút "Lưu" chính ở cuối modal trước đây CHỈ lưu thông tin đầu/ghi chú, không lưu Bảng
    // theo ngày — nếu người dùng gõ số liệu ngày rồi bấm thẳng nút này (thay vì "Lưu bảng
    // ngày" ở giữa modal) thì dữ liệu ngày bị mất khi đóng modal. Lưu luôn cả 2 để không ai
    // mất dữ liệu dù bấm nút nào.
    const readings = dayNos.map(d => ({ day_no: d, ...(readingsByDay[d] || {}) }));
    await Promise.all([
      PUT(`/brewing/ferments/${fermentId}/process-log`, payload),
      PUT(`/brewing/ferments/${fermentId}/process-log/readings`, { readings }),
    ]);
    toast("Đã lưu ghi chép lên men"); closeModal(); render("process");
  });
}

function printFermentForm(data, lmCode) {
  const manual = { ...data.manual, ...(data.manual_current || {}) };
  const auto = data.auto;
  const _flPrintAutoHint = { order_number: auto.braumat_order_number, batch_number: auto.braumat_batch_number };
  const headerRows = FL_HEADER_FIELDS.map(f => `<tr><td>${esc(f.label)}</td><td>${_flDash(manual[f.key])}
    ${_flPrintAutoHint[f.key] ? ` <span style="color:#555">(Braumat: ${esc(_flPrintAutoHint[f.key])})</span>` : ""}</td></tr>`).join("");
  const dailyCols = data.readings.length ? data.readings.map(r => r.day_no) : [];
  const byDay = Object.fromEntries(data.readings.map(r => [r.day_no, r]));
  const printAuditRow = (label, getBy, getAt) => `<tr><td style="color:#555">${esc(label)}</td>
    ${dailyCols.map(d => { const r = byDay[d] || {}; return `<td style="color:#555">${_flAuditText(getBy(r), getAt(r))}</td>`; }).join("")}</tr>`;
  const dailyRows = FL_DAILY_ROWS.map(f => {
    let row = `<tr><td>${esc(f.label)}</td>
      ${dailyCols.map(d => { const v = (byDay[d] || {})[f.key];
        return `<td>${f.kind === "select" ? (FL_KCS_LABELS[v] || _flDash(v)) : _flDash(v)}</td>`; }).join("")}</tr>`;
    if (f.key === "mat_do_tb") row += printAuditRow("Đo đạc bởi", r => r.measured_by, r => r.measured_at);
    if (f.key === "kcs") row += printAuditRow("KCS bởi", r => r.kcs_by, r => r.kcs_at);
    if (f.key === "truc_ca") row += printAuditRow("Trực ca bởi", r => r.truc_ca_by, r => r.truc_ca_at);
    return row;
  }).join("");
  const haphuRows = (data.ha_phu_events || []).map(ev => `<tr><td>${_flDash(ev.at)}</td><td>${_flDash(ev.nguoi_lenh)}</td>
    <td>${_flDash(ev.nguoi_nhan_lenh)}</td><td>${_flDash(ev.truc_ca)}</td></tr>`).join("");
  const chartHtml = _flChartHtml(data.readings);
  const html = `<!doctype html><html><head><meta charset="utf-8"/><title>Ghi chép lên men — ${esc(lmCode)}</title>
    <style>
      @page { size: A4 landscape; margin: 10mm; }
      * { box-sizing: border-box; }
      body{font-family:Arial,Helvetica,sans-serif;color:#000;background:#fff;margin:0;font-size:11px;line-height:1.25}
      h1{font-size:15px;margin:0 0 2px;text-align:center}
      h2{font-size:12px;margin:0 0 8px;text-align:center;font-weight:normal}
      h3{font-size:11.5px;margin:8px 0 3px;border-bottom:1.5px solid #000;padding-bottom:1px;text-transform:uppercase}
      table.pf-tbl{border-collapse:collapse;width:100%;margin-bottom:4px}
      table.pf-tbl th, table.pf-tbl td{border:1px solid #000;padding:2px 5px;text-align:left;font-size:10.5px}
      table.pf-tbl th{background:#eee;font-weight:normal}
      .pf-header{display:grid;grid-template-columns:repeat(3,1fr);gap:2px 14px;border:1.5px solid #000;padding:5px 10px;margin-bottom:8px}
      svg text{fill:#000 !important}
      svg line{stroke:#000 !important}
    </style></head><body>
    <h1>BM 1.11 (06) — BIỂU THEO DÕI LÊN MEN</h1>
    <h2>Lô LM ${esc(lmCode)}</h2>
    <div class="pf-header">
      <div><b>Số mẻ:</b> ${_flDash(auto.so_me)}</div>
      <div><b>Số Tank:</b> ${_flDash(auto.so_tank)}</div>
      <div><b>Thể tích Tank, hl:</b> ${_flDash(auto.the_tich_tank)}</div>
      <div><b>Thế hệ:</b> ${_flDash(auto.the_he)}</div>
    </div>
    <h3>Thông tin đầu</h3>
    <table class="pf-tbl"><tbody>${headerRows}</tbody></table>
    <h3>Biểu đồ theo dõi</h3>
    <div style="max-width:500px">${chartHtml}</div>
    <h3>Bảng theo ngày</h3>
    <table class="pf-tbl"><thead><tr><th></th>${dailyCols.map(d => `<th>Ngày ${d}</th>`).join("")}</tr></thead>
      <tbody>${dailyRows}</tbody></table>
    <h3>Hạ phụ</h3>
    <table class="pf-tbl"><thead><tr><th>Thời điểm</th><th>Người lệnh</th><th>Người nhận lệnh</th><th>Trực ca</th></tr></thead>
      <tbody>${haphuRows || '<tr><td colspan=4 style="text-align:center">—</td></tr>'}</tbody></table>
    </body></html>`;
  const w = window.open("", "_blank");
  if (!w) { toast("Trình duyệt chặn cửa sổ in — vui lòng cho phép popup.", "err"); return; }
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 300);
}

async function openBrewMasterOrderModal(masterId) {
  const m = await GET(`/brewing/brew-master-orders/${masterId}`);
  modal(`<h3>Lệnh nấu — <code class="k">${esc(m.order_code)}</code></h3>
    <div class="muted" style="margin-bottom:8px">
      Sản lượng thực tế/KH: <b>${m.actual_total_hl}/${m.planned_total_hl} hl</b> ·
      ${m.is_complete_all ? `<span style="color:var(--green)">✓ Hoàn thành</span>`
        : (m.is_executed_any ? `<span class="muted">Đang nấu</span>` : `<span class="muted">Chưa thực hiện</span>`)}
      ${m.issued_by ? `<br/>Người ra lệnh: ${esc(m.issued_by)}` : ""}
    </div>
    ${m.children.map((c, ci) => {
      const shortageCount = c.lines.filter(l => l.shortage).length;
      return `<div class="panel" style="margin-bottom:8px;border:1px solid var(--border)">
      <h4 style="font-size:13px;margin:0 0 6px">Lệnh nấu nhỏ #${ci + 1}</h4>
      <div class="muted" style="margin-bottom:6px">
        Dịch bia: <b>${esc(c.product_code || c.product_desc || "—")}</b> ·
        Số mẻ KH: <b>${c.planned_batch_count}</b> ·
        Sản lượng thực tế/KH: <b>${c.actual_volume_hl}/${c.planned_volume_hl} hl</b> (±${c.volume_tolerance_hl}hl)<br/>
        ${c.is_complete
          ? `<span style="color:var(--green)">✓ Hoàn thành — mã nấu ${c.records.map(r => esc(r.brew_code)).join(", ")}</span>`
          : (c.is_executed
              ? `<span class="muted">Đang nấu — mã nấu ${c.records.map(r => esc(r.brew_code)).join(", ")}</span>`
              : `<span class="muted">Chưa thực hiện nấu</span>`)}
        ${shortageCount ? ` · <span style="color:var(--red)">⚠ ${shortageCount} dòng NVL không đủ tồn (tại thời điểm lập phiếu)</span>` : ""}
      </div>
      <div class="tablewrap" style="max-height:40vh"><table>
        <thead><tr><th>STT</th><th>Tên NVL</th><th>ĐVT</th><th>Nhu cầu 1 mẻ</th><th>Nhu cầu Tổng mẻ</th>
          <th>Tồn Kho công ty (lúc lập)</th><th>Tồn Kho phân xưởng (lúc lập)</th><th>Đơn giá</th><th></th></tr></thead>
        <tbody>${c.lines.map(l => l.is_header
          ? `<tr style="font-weight:700"><td colspan=9>${esc(l.stt_label || "")} ${esc(l.material_name || "")}</td></tr>`
          : `<tr class="${l.shortage ? "row-red" : ""}"><td>${esc(l.stt_label || "")}</td><td>${esc(l.material_name || "—")}</td>
            <td>${esc(l.uom || "")}</td><td>${l.qty_per_batch ?? "—"}</td><td>${l.qty_total ?? "—"}</td>
            <td>${l.stock_company_snapshot ?? "—"}</td><td>${l.stock_workshop_snapshot ?? "—"}</td>
            <td>${l.unit_price ?? "—"}</td><td>${l.shortage ? `<span style="color:var(--red)">⚠ Thiếu</span>` : (l.material_id ? `<span style="color:var(--green)">Đủ</span>` : "")}</td></tr>`).join("") ||
          `<tr><td colspan=9 class="muted">Chưa có dòng NVL.</td></tr>`}</tbody></table></div>
    </div>`;
    }).join("")}`);
}

async function openFilterMasterOrderModal(masterId) {
  const m = await GET(`/brewing/filter-master-orders/${masterId}`);
  modal(`<h3>Lệnh lọc — <code class="k">${esc(m.order_code)}</code></h3>
    <div class="muted" style="margin-bottom:8px">
      Thể tích kế hoạch: <b>${m.planned_total_hl} hl</b> · Thực tế: <b>${m.actual_total_hl} hl</b> ·
      ${m.is_complete_all ? `<span style="color:var(--green)">✓ Hoàn thành</span>`
        : (m.is_executed_any ? `<span class="muted">Đang lọc</span>` : `<span class="muted">Chưa thực hiện</span>`)}
      ${m.note ? `<br/>Ghi chú: ${esc(m.note)}` : ""}
    </div>
    ${m.children.map((c, ci) => `<div class="panel" style="margin-bottom:8px;border:1px solid var(--border)">
      <h4 style="font-size:13px;margin:0 0 6px">Lệnh lọc nhỏ #${ci + 1}</h4>
      <div class="muted" style="margin-bottom:6px">
        Loại lọc: <b>${c.blend_mode === "phoi" ? "Phối" : "Không phối"}</b> ·
        Loại bia: <b>${esc(c.beer_type_name || "—")}</b> ·
        Tank: <b>${c.tanks.map(t => t.tank_type === "bbt"
          ? `BBT ${esc(t.source_bbt_code)} — Lọc lại, lý do: ${esc(t.reason || "—")} (${t.planned_v_dich_hl} hl)`
          : `${esc(t.tank_lm)} (${t.planned_v_dich_hl} hl)`).join(", ") || "—"}</b> ·
        Số lô KCS: <b>${esc(c.kcs_lot_no || "—")}</b><br/>
        Thể tích kế hoạch (tổng): <b>${c.planned_volume_hl} hl</b> (± ${c.volume_tolerance_hl} hl) ·
        Thực tế: <b>${c.actual_volume_hl} hl</b><br/>
        ${c.is_complete ? `<span style="color:var(--green)">✓ Hoàn thành</span>`
          : (c.is_executed ? `<span class="muted">Đang lọc (${c.records.length} mẻ)</span>`
                           : `<span class="muted">Chưa thực hiện lọc</span>`)}
      </div>
      ${c.records.length ? `<h4 style="font-size:13px">Các bản ghi lọc đã tạo</h4>
      <div class="tablewrap" style="max-height:20vh;margin-bottom:8px"><table>
        <thead><tr><th>Mã lọc</th><th>Tank BBT</th><th>Sản lượng (hl)</th><th>Kết thúc</th></tr></thead>
        <tbody>${c.records.map(r => `<tr><td class="code">${esc(r.filter_code)}</td><td>${esc(r.to_bbt || "—")}</td>
          <td>${r.v_beer_hl ?? "—"}</td><td>${r.ended_at ? fmt(r.ended_at) : "—"}</td></tr>`).join("")}</tbody></table></div>` : ""}
      <h4 style="font-size:13px">Vật tư sử dụng</h4>
      <div class="tablewrap" style="max-height:30vh"><table>
        <thead><tr><th>Tên vật tư</th><th>ĐVT</th><th>Số lượng</th>
          <th>Tồn Kho công ty (lúc lập)</th><th>Tồn Kho phân xưởng (lúc lập)</th><th>Đơn giá</th></tr></thead>
        <tbody>${c.lines.map(l => `<tr><td>${esc(l.material_name || "—")}</td><td>${esc(l.uom || "")}</td>
          <td>${l.quantity}</td><td>${l.stock_company_snapshot ?? "—"}</td>
          <td>${l.stock_workshop_snapshot ?? "—"}</td><td>${l.unit_price ?? "—"}</td></tr>`).join("") ||
          `<tr><td colspan=6 class="muted">Chưa có dòng vật tư.</td></tr>`}</tbody></table></div>
    </div>`).join("")}`);
}

function printFilterMasterOrder(m) {
  const dash = (v) => (v === null || v === undefined || v === "" ? "—" : esc(String(v)));
  const d = new Date(m.created_at);
  const childSections = m.children.map((c, ci) => {
    const tankLm = c.tanks.map(t => t.tank_type === "bbt"
      ? `BBT ${esc(t.source_bbt_code)} — Lọc lại, lý do: ${esc(t.reason || "—")} (${Math.round((t.planned_v_dich_hl || 0) * 100)} lít)`
      : `${esc(t.tank_lm)} (${Math.round((t.planned_v_dich_hl || 0) * 100)} lít)`).join(", ");
    const actualTanksText = c.records.map(r => esc(r.to_bbt)).filter(Boolean).join(", ");
    const volumeL = Math.round((c.planned_volume_hl || 0) * 100);
    const materialRows = c.lines.map(l => `<tr><td>${dash(l.material_name)}</td><td>${dash(l.uom)}</td><td>${dash(l.quantity)}</td></tr>`).join("");
    const recordRows = c.records.map(r => `<tr><td class="code">${dash(r.filter_code)}</td><td>${dash(r.to_bbt)}</td><td>${r.v_beer_hl ?? "—"}</td></tr>`).join("");
    return `<div class="pf-section" style="border:1px solid #000;padding:6px;margin-bottom:10px">
      <h3 style="margin-top:0">Lệnh lọc nhỏ #${ci + 1}</h3>
      <table class="pf-tbl"><thead><tr><th>Loại lọc</th><th>Loại bia</th><th>Lượng lọc kế hoạch (lít)</th>
        <th>Tank LM chỉ định lọc</th><th>Tank TP đã dùng</th><th>Số lô KCS</th></tr></thead>
      <tbody><tr><td>${c.blend_mode === "phoi" ? "Phối" : "Không phối"}</td><td>${dash(c.beer_type_name)}</td><td>${volumeL}</td>
        <td>${tankLm || "—"}</td><td>${actualTanksText || "—"}</td><td>${dash(c.kcs_lot_no)}</td></tr></tbody></table>
      ${c.records.length ? `<div style="margin-top:4px"><b style="font-size:11.5px">Các bản ghi lọc đã thực hiện</b>
        <table class="pf-tbl"><thead><tr><th>Mã lọc</th><th>Tank BBT</th><th>Sản lượng (hl)</th></tr></thead>
        <tbody>${recordRows}</tbody></table></div>` : ""}
      <div style="margin-top:4px"><b style="font-size:11.5px">Vật tư sử dụng</b>
        <table class="pf-tbl"><thead><tr><th>Tên vật tư</th><th>ĐVT</th><th>Số lượng</th></tr></thead>
        <tbody>${materialRows || '<tr><td colspan=3 style="text-align:center">—</td></tr>'}</tbody></table></div>
    </div>`;
  }).join("");
  const html = `<!doctype html><html><head><meta charset="utf-8"/><title>Lệnh lọc — ${esc(m.order_code)}</title>
    <style>
      @page { size: A4; margin: 12mm; }
      * { box-sizing: border-box; }
      body{font-family:Arial,Helvetica,sans-serif;color:#000;background:#fff;margin:0;font-size:12px;line-height:1.35}
      h2{font-size:16px;margin:2px 0 10px;text-align:center;font-weight:700;text-transform:uppercase}
      .pf-header{display:flex;justify-content:space-between;margin-bottom:6px;font-size:11.5px}
      .pf-section{margin-bottom:8px}
      .pf-section h3{font-size:12.5px;margin:0 0 3px;font-weight:700}
      table.pf-tbl{border-collapse:collapse;width:100%;margin-bottom:4px}
      table.pf-tbl th, table.pf-tbl td{border:1px solid #000;padding:3px 5px;text-align:left;font-size:11px}
      table.pf-tbl th{background:#eee;font-weight:700;text-align:center}
      .pf-sign{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:30px;text-align:center;font-size:11.5px}
      .pf-sign b{display:block;margin-bottom:2px}
      .pf-sign span{display:block;color:#555;margin-bottom:40px}
    </style></head><body>
    <div class="pf-header">
      <div><b>CÔNG TY CP BIA &amp; NGK ĐÔNG MAI</b><br/>Phòng KT-KCS</div>
      <div style="text-align:right">1.12.3/2025/QT-KCS-QT-BM-01<br/>Lần ban hành: 02 · Ngày 08.05.2025</div>
    </div>
    <h2>LỆNH LỌC BIA — ${esc(m.order_code)}</h2>
    <div class="pf-section" style="font-size:11.5px">Ngày lập: ${d.getDate()}/${d.getMonth() + 1}/${d.getFullYear()} ·
      Người lệnh: ${dash(m.created_by)}${m.note ? " · Ghi chú: " + esc(m.note) : ""}<br/>
      <span class="muted" style="font-size:10.5px;color:#555">Quy định: CO2, %P, Đục theo tiêu chuẩn công ty hiện hành (xem sổ tay chất lượng).</span>
    </div>
    ${childSections}
    <div class="pf-section" style="font-size:10.5px;color:#555">
      Lệnh này lập thành 02 bản: 01 bản lưu tại Phòng KT-KCS, 01 bản giao người nhận lệnh thực hiện.
      Người nhận lệnh có trách nhiệm thực hiện đúng nội dung lệnh và các quy định liên quan.
    </div>
    <div class="pf-sign">
      <div><b>Người lệnh</b><span>${dash(m.created_by)}<br/>(Ký, ghi rõ họ tên)</span></div>
      <div><b>Người nhận lệnh</b><span>(Ký, ghi rõ họ tên)</span></div>
    </div>
    </body></html>`;
  const w = window.open("", "_blank");
  if (!w) { toast("Trình duyệt chặn cửa sổ in — vui lòng cho phép popup.", "err"); return; }
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 300);
}

function printBrewOrder(m) {
  const dash = (v) => (v === null || v === undefined || v === "" ? "—" : esc(String(v)));
  const blank = (v) => (v === null || v === undefined || v === "" ? "" : esc(String(v)));
  const safetyText = m.safety_note ||
    "Thực hiện đúng quy trình vận hành thiết bị, chỉ vận hành khi thống nhất thông tin giữa thợ chính và thợ phụ, các bộ phận khác có liên quan.";
  const childSections = m.children.map((c, ci) => {
    const lineRows = c.lines.map(l => l.is_header
      ? `<tr><td colspan=10 style="font-weight:700">${dash(l.stt_label)} ${dash(l.material_name)}</td></tr>`
      : `<tr><td>${dash(l.stt_label)}</td><td>${dash(l.material_name)}</td><td>${dash(l.uom)}</td>
          <td>${dash(l.qty_per_batch)}</td><td>${dash(l.qty_total)}</td><td></td><td></td>
          <td>${blank(l.unit_price)}</td><td></td><td></td></tr>`).join("");
    return `<div class="pf-section" style="border:1px solid #000;padding:6px;margin-bottom:10px">
      <h3 style="margin-top:0">Lệnh nấu nhỏ #${ci + 1}</h3>
      <div>1/ Nấu: <b>${dash(c.product_code || c.product_desc)}</b>; Số lượng: <b>${dash(c.planned_batch_count)}</b> mẻ ≥ <b>${dash(c.planned_volume_hl)}</b> hl dịch${c.bx_min || c.bx_max ? `, với Bx: ${dash(c.bx_min)}-${dash(c.bx_max)}%` : ""}</div>
      <div>- Chuyển dịch vào Tank lên men: ${dash(c.tank_lm)} / ${dash(c.planned_batch_count)} mẻ/Tank${c.batch_range_from ? `; mẻ ${dash(c.batch_range_from)}-${dash(c.batch_range_to)}` : ""}.</div>
      <table class="pf-tbl"><thead>
        <tr><th rowspan=2>STT</th><th rowspan=2>Tên, nhãn hiệu quy cách NVL</th><th rowspan=2>ĐVT</th>
          <th colspan=2>Lượng</th><th colspan=2>Thực xuất</th><th rowspan=2>Đơn giá</th><th colspan=2>T/Tiền (đồng)</th></tr>
        <tr><th>Nhu cầu 1 mẻ</th><th>Tổng mẻ</th><th>1 mẻ</th><th>Tổng mẻ</th><th>Nhu cầu</th><th>Thực lĩnh</th></tr>
      </thead>
      <tbody>${lineRows || '<tr><td colspan=10 style="text-align:center">—</td></tr>'}
        <tr style="font-weight:700"><td colspan=8 style="text-align:right">TỔNG GIÁ TRỊ</td><td></td><td></td></tr>
      </tbody></table>
    </div>`;
  }).join("");
  const html = `<!doctype html><html><head><meta charset="utf-8"/><title>Lệnh nấu — ${esc(m.order_code)}</title>
    <style>
      @page { size: A4; margin: 12mm; }
      * { box-sizing: border-box; }
      body{font-family:Arial,Helvetica,sans-serif;color:#000;background:#fff;margin:0;font-size:12px;line-height:1.35}
      h2{font-size:16px;margin:6px 0 10px;text-align:center;font-weight:700;text-transform:uppercase}
      .pf-header{display:flex;justify-content:space-between;margin-bottom:6px;font-size:11.5px}
      .pf-header .right{text-align:center}
      .pf-section{margin-bottom:8px}
      .pf-section h3{font-size:12.5px;margin:0 0 3px;font-weight:700}
      table.pf-tbl{border-collapse:collapse;width:100%;margin-bottom:4px}
      table.pf-tbl th, table.pf-tbl td{border:1px solid #000;padding:3px 5px;text-align:left;font-size:11px}
      table.pf-tbl th{background:#eee;font-weight:700;text-align:center}
      table.pf-tbl td{text-align:center}
      table.pf-tbl td:nth-child(2){text-align:left}
      .pf-sign{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:30px;text-align:center;font-size:11.5px}
      .pf-sign b{display:block;margin-bottom:2px}
      .pf-sign span{display:block;color:#555;margin-bottom:40px}
    </style></head><body>
    <div class="pf-header">
      <div><b>CÔNG TY CP BIA &amp; NGK ĐÔNG MAI</b><br/>Pxsx bia ĐM<br/>Số: ${dash(m.order_code)}</div>
      <div class="right"><b>CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM</b><br/>Độc lập – Tự do – Hạnh phúc</div>
    </div>
    <h2>LỆNH NẤU BIA KIÊM PHIẾU XUẤT KHO</h2>
    <div class="pf-section"><h3>I. Người ra lệnh</h3><div>${dash(m.issued_by)}</div></div>
    <div class="pf-section"><h3>II. Người nhận lệnh</h3>
      <div>1/ Người T/hiện: ${dash(m.executor_unit)}</div>
      <div>2/ Người xuất hàng: ${dash(m.warehouse_keeper)}</div></div>
    <div class="pf-section"><h3>III. Nội dung thực hiện</h3>
      ${m.reference_note ? `<div>${dash(m.reference_note)}</div>` : ""}
      ${childSections}
    </div>
    <div class="pf-section"><h3>IV. Thời gian thực hiện</h3>
      <div>Bắt đầu: Ngày ${m.start_date ? fmt(m.start_date) : "......."} — Ca: .......</div>
      <div>Kết thúc: Ngày ${m.end_date ? fmt(m.end_date) : "......."} — Ca: .......</div></div>
    <div class="pf-section"><h3>V. Biện pháp an toàn</h3><div>${dash(safetyText)}</div></div>
    <div class="pf-sign">
      <div><b>Giám đốc</b><span>(Ký, ghi rõ họ tên)</span></div>
      <div><b>Người nhận lệnh</b><span>${dash(m.executor_unit)}<br/>(Ký, ghi rõ họ tên)</span></div>
      <div><b>Thủ kho</b><span>${dash(m.warehouse_keeper)}<br/>(Ký, ghi rõ họ tên)</span></div>
      <div><b>P. Kế toán</b><span>(Ký, ghi rõ họ tên)</span></div>
    </div>
    </body></html>`;
  const w = window.open("", "_blank");
  if (!w) { toast("Trình duyệt chặn cửa sổ in — vui lòng cho phép popup.", "err"); return; }
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 300);
}

// ---- HTML "PHIẾU XUẤT KHO" (Mẫu số 02-VT, kèm theo TT 99/2025/TT-BTC) — chứng từ kế toán,
// hiện không còn nút in nào gọi trực tiếp (Xuất kho thành phẩm đã đổi sang in "Biên bản bàn
// giao hàng hóa", xem views_ext.js::printShipmentHandoverSlip) — giữ lại cho nhu cầu kế toán
// dùng Mẫu 02-VT sau này nếu cần, không xóa vì đây là biểu mẫu hợp lệ theo quy định.
// opts: {code, date, recipient_name, recipient_dept, type_label, note, driver_name,
//        vehicle_plate, from_location, delivery_place, lines: [{name, code, uom, qty}]}
function warehouseIssueSlipHtml(opts) {
  const dash = (v) => (v === null || v === undefined || v === "" ? "" : esc(String(v)));
  const d = opts.date || new Date();
  const lineRows = (opts.lines || []).map((l, i) => `<tr>
    <td style="text-align:center">${i + 1}</td>
    <td>${dash(l.name || "—")}</td>
    <td style="text-align:center">${dash(l.code)}</td>
    <td style="text-align:center">${dash(l.uom) || "Thùng"}</td>
    <td style="text-align:center">${l.qty}</td>
    <td style="text-align:center">${l.qty}</td>
    <td></td><td></td></tr>`).join("");

  return `<!doctype html><html><head><meta charset="utf-8"/><title>Phiếu xuất kho — ${esc(opts.code)}</title>
    <style>
      @page { size: A4; margin: 14mm; }
      * { box-sizing: border-box; }
      body{font-family:"Times New Roman",Times,serif;color:#000;background:#fff;margin:0;font-size:13px;line-height:1.35}
      .pk-topright{text-align:right;margin-bottom:2px}
      .pk-topright b{font-size:13px}
      .pk-topright div{font-style:italic;font-size:11.5px}
      h1{font-size:20px;margin:6px 0 2px;text-align:center;letter-spacing:1px}
      .pk-date{text-align:center;font-style:italic;font-size:13px;margin-bottom:2px}
      .pk-no{text-align:center;margin-bottom:8px}
      .pk-nocode{display:flex;justify-content:space-between;align-items:flex-start}
      .pk-info div{margin-bottom:4px}
      .pk-row2{display:flex;gap:24px}
      .pk-row2 > div{flex:1}
      table.pk-tbl{border-collapse:collapse;width:100%;margin:10px 0 6px}
      table.pk-tbl th, table.pk-tbl td{border:1px solid #000;padding:3px 6px;font-size:12.5px}
      table.pk-tbl th{background:#fff;font-weight:700;text-align:center}
      .pk-totals{display:flex;justify-content:space-between;margin-bottom:6px}
      .pk-sign{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:30px;text-align:center;font-size:12.5px}
      .pk-sign b{display:block;margin-bottom:2px}
      .pk-sign .note{font-style:italic;display:block;margin-bottom:2px}
      .pk-sign span.sig-space{display:block;margin-bottom:44px}
    </style></head><body>
    <div class="pk-topright">
      <b>Mẫu số: 02 - VT</b>
      <div>(Kèm theo Thông tư số 99/2025/TT-BTC<br/>ngày 27 tháng 10 năm 2025 của Bộ trưởng Bộ Tài chính)</div>
    </div>
    <h1>PHIẾU XUẤT KHO</h1>
    <div class="pk-nocode">
      <div style="flex:1"></div>
      <div class="pk-date" style="flex:2">Ngày ${d.getDate()} tháng ${d.getMonth() + 1} năm ${d.getFullYear()}</div>
      <div style="flex:1;text-align:right">Nợ:.......................<br/>Có:.......................</div>
    </div>
    <div class="pk-no">Số: ${dash(opts.code)}</div>
    <div class="pk-info">
      <div class="pk-row2">
        <div>Họ tên người nhận hàng: <b>${dash(opts.recipient_name) || "................................"}</b></div>
        <div>Địa chỉ (bộ phận): ${dash(opts.recipient_dept) || "................................"}</div>
      </div>
      <div>Loại xuất: <b>${dash(opts.type_label) || "Bán hàng thường"}</b></div>
      <div>Lý do xuất kho: ${dash(opts.note) || "................................................................................"}</div>
      <div class="pk-row2">
        <div>Lái xe: ${dash(opts.driver_name) || "................................"}</div>
        <div>Biển số xe: ${dash(opts.vehicle_plate) || "................................"}</div>
      </div>
      <div class="pk-row2">
        <div>Xuất tại kho (ngăn lô): ${dash(opts.from_location) || "................................"}</div>
        <div>Địa điểm: ${dash(opts.delivery_place) || "................................"}</div>
      </div>
    </div>
    <table class="pk-tbl">
      <thead>
        <tr><th rowspan="2">STT</th><th rowspan="2">Tên, nhãn hiệu, quy cách<br/>phẩm chất vật tư, dụng cụ sản<br/>phẩm, hàng hóa</th>
          <th rowspan="2">Mã số</th><th rowspan="2">Đơn vị<br/>tính</th>
          <th colspan="2">Số lượng</th><th rowspan="2">Đơn giá</th><th rowspan="2">Thành tiền</th></tr>
        <tr><th>Yêu cầu</th><th>Thực xuất</th></tr>
      </thead>
      <tbody>
        <tr style="font-style:italic"><td>A</td><td>B</td><td>C</td><td>D</td><td>1</td><td>2</td><td>3</td><td>4</td></tr>
        ${lineRows || '<tr><td colspan=8 style="text-align:center">—</td></tr>'}
        <tr><td colspan="6" style="text-align:right"><b>Tổng cộng:</b></td><td colspan="2">
          <div>Tiền xuất: 0</div><div>Tiền thuế: 0</div><div>Tổng tiền: 0</div></td></tr>
      </tbody>
    </table>
    <div>- Tổng số tiền (Viết bằng chữ): ......................................................</div>
    <div>- Số chứng từ gốc kèm theo: ......................................................</div>
    <div class="pk-sign">
      <div><b>Người lập phiếu</b><span class="note">(Ký, họ tên)</span><span class="sig-space"></span></div>
      <div><b>Người nhận hàng</b><span class="note">(Ký, họ tên)</span><span class="sig-space"></span></div>
      <div><b>Thủ kho</b><span class="note">(Ký, họ tên)</span><span class="sig-space"></span></div>
      <div><b>Kế toán trưởng</b><span class="note">(Hoặc bộ phận có nhu cầu nhập)</span><span class="note">(Ký, họ tên)</span></div>
      <div><span class="note">Ngày ..... tháng ..... năm .....</span><b>Giám đốc</b><span class="note">(Ký, họ tên)</span></div>
    </div>
    </body></html>`;
}

function openPrintWindow(html) {
  const w = window.open("", "_blank");
  if (!w) { toast("Trình duyệt chặn cửa sổ in — vui lòng cho phép popup.", "err"); return; }
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 300);
}

// ---- In "PHIẾU XUẤT KHO" (Mẫu số 02-VT, kèm theo TT 99/2025/TT-BTC) cho xuất kho thành phẩm ----
async function printWarehouseIssueSlip(shipment) {
  let nameByCode = {};
  try {
    const fps = await GET("/finished-products");
    nameByCode = Object.fromEntries(fps.map(p => [p.code, p.name]));
  } catch (e) { /* vẫn in được — chỉ thiếu tên đầy đủ, dùng tạm mã số */ }

  const html = warehouseIssueSlipHtml({
    code: shipment.shipment_code,
    date: new Date(shipment.created_at),
    recipient_name: shipment.recipient_name,
    recipient_dept: shipment.recipient_dept,
    type_label: shipment.shipment_type === "promo" ? "Khuyến mại" : shipment.shipment_type === "return" ? "Đổi trả" : "Bán hàng thường",
    note: shipment.note,
    driver_name: shipment.driver_name,
    vehicle_plate: shipment.vehicle_plate,
    from_location: shipment.from_location,
    delivery_place: shipment.delivery_place,
    lines: shipment.lines.map(l => ({ name: nameByCode[l.product] || l.product, code: l.product, uom: "Thùng", qty: l.quantity })),
  });
  openPrintWindow(html);
}

async function openBrewProcessLogModal(brewId, batchId, batchCode) {
  const data = await GET(`/brewing/brews/${brewId}/batches/${batchId}/process-log`);
  const cp = data.checkpoints;

  const autoRow = (label, value) => `<div class="muted" style="font-size:12px">${esc(label)}: <b>${value ?? "—"}</b></div>`;
  const autoBySection = {
    rc: cp.rice_cooker ? [
      autoRow("Khối lượng gạo (tự động)", cp.rice_cooker.rice_weight_kg && cp.rice_cooker.rice_weight_kg + " kg"),
      autoRow("Nhiệt độ sau nấu chín (tự động)", cp.rice_cooker.mash_in_temp_c && cp.rice_cooker.mash_in_temp_c + " °C"),
      autoRow("Heat up (tự động)", cp.rice_cooker.heat_up_temp_c && `${cp.rice_cooker.heat_up_temp_c} °C — ${cp.rice_cooker.heat_up_elapsed || ""}`),
      autoRow("Giữ nhiệt/Rest (tự động)", cp.rice_cooker.rest_temp_c && `${cp.rice_cooker.rest_temp_c} °C — ${cp.rice_cooker.rest_elapsed || ""}`),
    ].join("") : "",
    mt: cp.mash_tun ? [
      autoRow("Khối lượng malt (tự động)", cp.mash_tun.malt_weight_kg && cp.mash_tun.malt_weight_kg + " kg"),
      ...(cp.mash_tun.rests || []).map((r, i) => autoRow(`Giữ nhiệt lần ${i + 1} (tự động)`, r.temp_c && `${r.temp_c} °C — ${r.elapsed}`)),
    ].join("") : "",
    lt: cp.lauter_tun ? [
      autoRow("Dịch cốt / lượng đầu (tự động)", cp.lauter_tun.first_wort_hl && cp.lauter_tun.first_wort_hl + " hl"),
      autoRow("Nước tráng bã (tự động)", cp.lauter_tun.water_sparge_hl && cp.lauter_tun.water_sparge_hl + " hl"),
      autoRow("Dịch lần 2 (tự động)", cp.lauter_tun.second_wort_hl && cp.lauter_tun.second_wort_hl + " hl"),
    ].join("") : "",
    wk: cp.wort_kettle ? [
      autoRow("Tổng thời gian đun sôi (tự động)", cp.wort_kettle.boiling_total_elapsed_min && cp.wort_kettle.boiling_total_elapsed_min + " phút"),
      autoRow("Thời điểm châm hoa 1 (tự động)", cp.wort_kettle.hop1_time),
      autoRow("Thời điểm châm hoa 2 (tự động)", cp.wort_kettle.hop2_time),
    ].join("") : "",
    whp: cp.whirlpool ? [
      autoRow("Thời gian nhận dịch từ nồi hoa (tự động)", cp.whirlpool.receive_elapsed),
    ].join("") : "",
  };

  // Làm phẳng dữ liệu đã import (1 dòng = 1 tham số) — chỉ dùng để xuất CSV cho báo cáo
  // sau này (so với số liệu vận hành nhập tay và tiêu chuẩn công ty). Bảng hiển thị trên
  // màn hình thì gộp theo bước (giống bố cục file PDF gốc — mỗi Unit/Bước/Bắt đầu/Kết
  // thúc chỉ khai báo 1 lần, các tham số của bước đó liệt kê bên dưới, không lặp lại).
  const flatRows = [];
  data.steps.forEach(s => {
    const entries = Object.entries(s.params);
    if (!entries.length) {
      flatRows.push({ unit: s.unit, step_no: s.step_no, eop: s.eop, name: s.name,
        start_at: s.start_at, end_at: s.end_at, elapsed_actual: s.elapsed_actual,
        param: "", setpoint: "", actual: "" });
    }
    entries.forEach(([param, v]) => flatRows.push({ unit: s.unit, step_no: s.step_no, eop: s.eop,
      name: s.name, start_at: s.start_at, end_at: s.end_at, elapsed_actual: s.elapsed_actual,
      param, setpoint: v.setpoint ?? "", actual: v.actual ?? "" }));
  });
  const units = [...new Set(data.steps.map(s => s.unit))];
  const unitOpts = `<option value="">(Tất cả unit)</option>` + units.map(u => `<option value="${esc(u)}">${esc(u)}</option>`).join("");

  let groupedRowsHtml = "";
  data.steps.forEach((s, idx) => {
    const entries = Object.entries(s.params);
    const n = Math.max(1, entries.length);
    const headerCells = `
      <td rowspan="${n}" style="vertical-align:top">${esc(s.unit)}</td>
      <td rowspan="${n}" style="vertical-align:top">${s.step_no}</td>
      <td rowspan="${n}" class="muted" style="vertical-align:top">${esc(s.eop || "")}</td>
      <td rowspan="${n}" style="vertical-align:top">${esc(s.name || "")}</td>
      <td rowspan="${n}" class="muted" style="vertical-align:top">${fmt(s.start_at)}</td>
      <td rowspan="${n}" class="muted" style="vertical-align:top">${fmt(s.end_at)}</td>
      <td rowspan="${n}" style="vertical-align:top">${esc(s.elapsed_actual || "")}</td>`;
    if (!entries.length) {
      groupedRowsHtml += `<tr data-unit="${esc(s.unit)}" data-step="${idx}">${headerCells}<td class="muted" colspan=3>—</td></tr>`;
    } else {
      entries.forEach(([param, v], i) => {
        groupedRowsHtml += `<tr data-unit="${esc(s.unit)}" data-step="${idx}">${i === 0 ? headerCells : ""}
          <td>${esc(param)}</td><td>${esc(v.setpoint ?? "")}</td><td><b>${esc(v.actual ?? "")}</b></td></tr>`;
      });
    }
  });
  const rawHtml = data.steps.length ? `
    <div class="row" style="align-items:flex-end;margin-bottom:8px">
      <div class="field"><label>Lọc theo unit</label><select id="pl_raw_unit">${unitOpts}</select></div>
      <div class="field" style="flex:1"><label>Tìm kiếm</label><input id="pl_raw_search" placeholder="Enter text to search..."/></div>
      <button class="btn sec" id="pl_raw_csv">Xuất CSV</button>
    </div>
    <div class="tablewrap" style="max-height:55vh"><table id="pl_raw_tbl">
      <thead><tr><th>Unit</th><th>Bước</th><th>EOP</th><th>Tên bước</th><th>Bắt đầu</th><th>Kết thúc</th><th>Thời gian</th><th>Tham số</th><th>Setpoint</th><th>Thực tế</th></tr></thead>
      <tbody>${groupedRowsHtml}</tbody>
    </table></div>` : '<div class="muted">Chưa import Step Protocol nào.</div>';

  // 4 field nhập tay (batch_number/order_number/gio_bat_dau/gio_ket_thuc) hiện kèm giá trị
  // hệ thống/Braumat (nếu có) để KCS đối chiếu — không tự điền vào ô, chỉ hiện tham khảo.
  const _timingAuto = _computeOverallTiming(data.steps);
  const _headerAutoHint = {
    batch_number: batchCode,
    order_number: data.braumat_order_number,
    gio_bat_dau: fmt(_timingAuto.start) !== "—" ? fmt(_timingAuto.start) : null,
    gio_ket_thuc: fmt(_timingAuto.end) !== "—" ? fmt(_timingAuto.end) : null,
  };
  const _headerHintLabel = { batch_number: "Mã mẻ hệ thống" };
  const headerFieldsHtml = BF_HEADER_FIELDS.map(f => `<div class="field">
    <label>${esc(f.label)}</label>${_bfInput(f.key, f.kind, data.manual?.[f.key], "pl-manual")}
    ${_headerAutoHint[f.key] ? `<span class="muted" style="font-size:11px">${esc(_headerHintLabel[f.key] || "Tự động")}: ${esc(_headerAutoHint[f.key])}</span>` : ""}</div>`).join("");

  modal(`<h3>Ghi chép nấu — mẻ <code class="k">${esc(batchCode)}</code></h3>
    <div class="muted" style="margin-bottom:8px">Nhập số liệu đo tay (pH, %Bx, hóa chất, nhiệt độ/thời gian từng bước) theo biểu mẫu QT-KCS-QT-BM-05, hoặc import
      file Step Protocol (Braumat) để tự động điền checkpoint tham khảo bên cạnh.
      ${data.braumat_order_number ? `Đã import từ Order Number <b>${esc(data.braumat_order_number)}</b> — ${esc(data.braumat_recipe || "")}.` : ""}</div>
    <div class="row" style="align-items:flex-end">
      <div class="field" style="flex:1"><label>Import Step Protocol (PDF, có thể chọn nhiều file)</label>
        <input type="file" id="pl_files" accept="application/pdf" multiple/></div>
      <button class="btn" id="pl_import">Import</button>
      <button class="btn sec" id="pl_print">🖨️ In biểu mẫu</button>
    </div>
    <div class="subnav" style="margin-top:10px">
      <button class="active" data-pltab="form">Ghi chép</button>
      <button data-pltab="raw">Dữ liệu Braumat đã import (${flatRows.length})</button>
    </div>
    <div id="pl_tab_form" style="max-height:60vh;overflow-y:auto;margin-top:10px">
    <div class="panel"><h2 style="font-size:15px">Thông tin chung</h2>
      <div class="row" style="flex-wrap:wrap">${headerFieldsHtml}</div>
    </div>
    ${BF_SECTIONS.map(sec => `
      <div class="panel" style="margin-top:10px"><h2 style="font-size:15px">${esc(sec.title)}</h2>
        ${autoBySection[sec.key] || ""}
        ${_bfSectionHtml(sec, data.spec, data.manual)}
      </div>`).join("")}
    <div class="panel" style="margin-top:10px"><h2 style="font-size:15px">Ghi chú</h2>
      <textarea id="pl_note" style="width:100%;min-height:50px">${esc(data.note || "")}</textarea></div>
    </div>
    <div id="pl_tab_raw" style="display:none;margin-top:10px">${rawHtml}</div>
    <button class="btn" id="pl_save" style="margin-top:12px">Lưu ghi chép</button>`);

  document.querySelectorAll("[data-pltab]").forEach(b => b.onclick = () => {
    document.querySelectorAll("[data-pltab]").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    $("pl_tab_form").style.display = b.dataset.pltab === "form" ? "" : "none";
    $("pl_tab_raw").style.display = b.dataset.pltab === "raw" ? "" : "none";
  });
  // Lọc theo nhóm bước (không phải theo từng dòng riêng lẻ) — vì các dòng của cùng 1
  // bước dùng chung ô rowspan (Unit/Bước/Bắt đầu/Kết thúc), phải ẩn/hiện cả nhóm cùng lúc.
  const filterRawTable = () => {
    const q = ($("pl_raw_search")?.value || "").trim().toLowerCase();
    const u = $("pl_raw_unit")?.value || "";
    const groups = {};
    document.querySelectorAll("#pl_raw_tbl tbody tr").forEach(tr => {
      (groups[tr.dataset.step] = groups[tr.dataset.step] || []).push(tr);
    });
    Object.values(groups).forEach(trs => {
      const unit = trs[0].dataset.unit;
      const text = trs.map(tr => tr.textContent.toLowerCase()).join(" ");
      const show = (!u || unit === u) && (!q || text.includes(q));
      trs.forEach(tr => tr.style.display = show ? "" : "none");
    });
  };
  if ($("pl_raw_unit")) $("pl_raw_unit").onchange = filterRawTable;
  if ($("pl_raw_search")) $("pl_raw_search").oninput = filterRawTable;
  if ($("pl_raw_csv")) $("pl_raw_csv").onclick = () => {
    const header = ["Unit", "Bước", "EOP", "Tên bước", "Bắt đầu", "Kết thúc", "Thời gian", "Tham số", "Setpoint", "Thực tế"];
    const csvCell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [header.map(csvCell).join(",")].concat(flatRows.map(r =>
      [r.unit, r.step_no, r.eop, r.name, fmt(r.start_at), fmt(r.end_at), r.elapsed_actual, r.param, r.setpoint, r.actual]
        .map(csvCell).join(",")));
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `braumat_${batchCode}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  $("pl_import").onclick = () => guard(async () => {
    const files = $("pl_files").files;
    if (!files.length) throw new Error("Chọn ít nhất 1 file PDF.");
    const res = await POST_FILES(`/brewing/brews/${brewId}/batches/${batchId}/process-log/import`, files);
    toast(res.warning || `Đã import ${Object.values(res.units).reduce((a, b) => a + b, 0)} bước từ ${Object.keys(res.units).length} unit`,
         res.warning ? "err" : "ok");
    openBrewProcessLogModal(brewId, batchId, batchCode);
  });
  $("pl_print").onclick = () => printBrewForm(data, batchCode);
  $("pl_save").onclick = () => guard(async () => {
    const payload = _collectBfManualPayload();
    payload.note = $("pl_note").value.trim() || null;
    await PUT(`/brewing/brews/${brewId}/batches/${batchId}/process-log`, payload);
    toast("Đã lưu ghi chép nấu"); closeModal(); render("process");
  });
}

// ================= NĂNG LƯỢNG =================
VIEWS.energy = async function () {
  const sec = SUB.energy || "report_hl";
  const sections = [
    { key: "report_hl", label: "Báo cáo NL - Hạ Long" }, { key: "report_dm", label: "Báo cáo NL - Đông Mai" },
    { key: "daily", label: "Biểu đồ ngày" },
    { key: "month", label: "Tổng hợp tháng" },
    { key: "update", label: "Cập nhật số liệu" }, { key: "dm", label: "Danh mục" },
  ];
  const groups = await GET("/energy/groups");
  let body = "";
  if (sec === "report_hl" || sec === "report_dm") {
    // Mỗi nhà máy là 1 tab riêng (không dùng chung dropdown chọn site) — mỗi tab tự nhớ bộ lọc
    // riêng qua SUB key hậu tố _hl/_dm. Hiện khung màn hình điện SCADA NGAY (không đợi CSDL
    // ngoài) — dữ liệu tải bất đồng bộ sau, đổ vào #elec_data khi xong.
    const site = sec === "report_dm" ? "dm" : "hl";
    const siteLabel = site === "dm" ? "Đông Mai" : "Hạ Long";
    const eFrom = SUB[`energy_ext_from_${site}`] || "";
    const eTo = SUB[`energy_ext_to_${site}`] || "";
    const eGb = SUB[`energy_ext_gb_${site}`] || "day";
    const elecBody = `<div class="panel">
        <h2>⚡ Điện (AED) — ${esc(siteLabel)} — dữ liệu SCADA thật</h2>
        <div class="muted" style="margin-bottom:8px">Nguồn: bảng Energy/NameSys qua kết nối CSDL gán "Dùng cho: Năng lượng — ${esc(siteLabel)}".</div>
        <div class="row">
          <div class="field"><label>Từ ngày giờ</label><input id="erp_from" type="datetime-local" value="${eFrom}"/></div>
          <div class="field"><label>Đến ngày giờ</label><input id="erp_to" type="datetime-local" value="${eTo}"/></div>
          <div class="field"><label>Nhóm theo</label><select id="erp_gb">
            <option value="day" ${eGb === "day" ? "selected" : ""}>Ngày</option>
            <option value="month" ${eGb === "month" ? "selected" : ""}>Tháng</option></select></div>
          <button class="btn" id="erp_apply">Xem báo cáo</button>
        </div></div>
      <div id="elec_summary"><div class="panel muted">⏳ Đang tải dữ liệu điện từ CSDL SCADA...</div></div>`;

    // Điện theo ca (Ca1 06-14h/Ca2 14-22h/Ca3 22-06h) — mặc định NGÀY HÔM QUA (giờ máy client),
    // vì ngày hôm nay chưa qua hết ca 3 nên chưa có đủ dữ liệu để tính trọn 3 ca.
    const yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1);
    const caMode = SUB[`energy_ca_mode_${site}`] || "day";
    const caDate = SUB[`energy_ca_date_${site}`] || toISODateLocal(yesterday);
    const caMonth = SUB[`energy_ca_month_${site}`] || toISODateLocal(yesterday).slice(0, 7);
    SUB[`energy_ca_mode_${site}`] = caMode; SUB[`energy_ca_date_${site}`] = caDate; SUB[`energy_ca_month_${site}`] = caMonth;
    const elecCaBody = `<div class="panel" style="margin-top:16px">
        <h2>⚡ Điện theo ca — ${esc(siteLabel)} — Ca 1 (06h-14h) / Ca 2 (14h-22h) / Ca 3 (22h-06h hôm sau)</h2>
        <div class="muted" style="margin-bottom:8px">Chọn 1 ngày để xem 3 ca của ngày đó, hoặc chọn cả tháng để xem theo từng ngày trong tháng. Nếu không có bản ghi đúng giờ ranh giới ca, hệ thống lấy bản ghi gần giờ đó nhất TRƯỚC mốc (không lấy bản ghi ở tương lai so với mốc) — dữ liệu nguồn càng thưa, breakdown theo ca càng chỉ mang tính tham khảo.</div>
        <div class="row">
          <div class="field"><label>Xem theo</label><select id="eca_mode">
            <option value="day" ${caMode === "day" ? "selected" : ""}>Ngày cụ thể</option>
            <option value="month" ${caMode === "month" ? "selected" : ""}>Cả tháng</option></select></div>
          <div class="field" id="eca_day_field" style="${caMode === "month" ? "display:none" : ""}"><label>Ngày</label><input id="eca_date" type="date" value="${caDate}"/></div>
          <div class="field" id="eca_month_field" style="${caMode === "day" ? "display:none" : ""}"><label>Tháng</label><input id="eca_month" type="month" value="${caMonth}"/></div>
          <button class="btn" id="eca_apply">Xem báo cáo ca</button>
        </div></div>
      <div id="elec_ca_data"><div class="panel muted">⏳ Đang tải dữ liệu điện theo ca...</div></div>`;

    body = elecBody + elecCaBody + `<div id="elec_trend"></div>`;
  } else if (sec === "daily") {
    const colors = ["#f5a623", "#3498db", "#e74c3c", "#2ecc71"];
    let charts = "";
    for (let i = 0; i < groups.length; i++) {
      const g = groups[i];
      const d = await GET("/energy/daily?group_id=" + g.group_id + "&days=30");
      const pts = d.map(x => ({ ts: x.day, value: x.value }));
      charts += `<div class="panel"><h2>${esc(g.name)} (${esc(g.unit)}/ngày)</h2>${CH.line(pts, { color: colors[i % 4], unit: g.unit, label: g.name, height: 130 })}</div>`;
    }
    body = charts || '<div class="panel muted">Chưa có nhóm năng lượng.</div>';
  } else if (sec === "month") {
    const m = await GET("/energy/monthly");
    body = `<div class="panel"><h2>Tổng hợp năng lượng theo tháng</h2>
      <input class="searchbox" data-tbl="t_energymonth" placeholder="Tìm theo tháng, nhóm..."/>
      <div class="tablewrap"><table id="t_energymonth"><thead><tr><th>Tháng</th><th>Nhóm</th><th>Sản lượng</th><th>ĐVT</th></tr></thead>
      <tbody>${m.map(r => `<tr><td>${esc(r.month)}</td><td>${esc(r.group)}</td><td>${r.value.toLocaleString("vi-VN")}</td><td>${esc(r.unit)}</td></tr>`).join("")}</tbody></table></div></div>`;
  } else if (sec === "update") {
    const areas = await GET("/energy/areas");
    const gopts = groups.map(g => `<option value="${g.group_id}">${esc(g.name)} (${esc(g.unit)})</option>`).join("");
    const aopts = `<option value="">(toàn nhà máy)</option>` + areas.map(a => `<option value="${a.area_id}">${esc(a.name)}</option>`).join("");
    body = `<div class="panel"><h2>Cập nhật số liệu năng lượng (theo ngày)</h2>
      <div class="row">
        <div class="field"><label>Ngày</label><input id="en_day" type="date"/></div>
        <div class="field"><label>Nhóm</label><select id="en_group">${gopts}</select></div>
        <div class="field"><label>Khu</label><select id="en_area">${aopts}</select></div>
        <div class="field"><label>Giá trị</label><input id="en_val" type="number"/></div>
        <button class="btn" id="en_save">Lưu</button>
      </div><div class="muted">Lưu lại cùng ngày+nhóm+khu sẽ ghi đè (upsert).</div></div>`;
  } else if (sec === "dm") {
    const areas = await GET("/energy/areas");
    body = `<div class="split">
      <div class="panel"><h2>Nhóm năng lượng</h2>
        <table><thead><tr><th>Mã</th><th>Tên</th><th>ĐVT</th></tr></thead><tbody>${groups.map(g => `<tr><td>${esc(g.code)}</td><td>${esc(g.name)}</td><td>${esc(g.unit)}</td></tr>`).join("")}</tbody></table>
        <div class="row" style="margin-top:10px"><div class="field"><label>Mã</label><input id="eg_code"/></div>
          <div class="field"><label>Tên</label><input id="eg_name"/></div><div class="field"><label>ĐVT</label><input id="eg_unit" value="kWh" size="5"/></div>
          <button class="btn sm" id="eg_add">+ Thêm</button></div></div>
      <div class="panel"><h2>Khu năng lượng</h2>
        <table><thead><tr><th>Mã</th><th>Tên</th></tr></thead><tbody>${areas.map(a => `<tr><td>${esc(a.code)}</td><td>${esc(a.name)}</td></tr>`).join("")}</tbody></table>
        <div class="row" style="margin-top:10px"><div class="field"><label>Mã</label><input id="ea_code"/></div>
          <div class="field"><label>Tên</label><input id="ea_name"/></div><button class="btn sm" id="ea_add">+ Thêm</button></div></div></div>`;
  }
  $("view-energy").innerHTML = subnav("energy", sections, sec) + body;
  wireSubnav("energy"); wireSearch();
  if (sec === "month") wirePaginate("t_energymonth", 10);
  if (sec === "report_hl" || sec === "report_dm") {
    const site = sec === "report_dm" ? "dm" : "hl";
    $("erp_apply").onclick = () => {
      SUB[`energy_ext_from_${site}`] = $("erp_from").value; SUB[`energy_ext_to_${site}`] = $("erp_to").value;
      SUB[`energy_ext_gb_${site}`] = $("erp_gb").value;
      render("energy");
    };
    loadElecReport(site);

    $("eca_mode").onchange = () => {
      const isMonth = $("eca_mode").value === "month";
      $("eca_day_field").style.display = isMonth ? "none" : "";
      $("eca_month_field").style.display = isMonth ? "" : "none";
    };
    $("eca_apply").onclick = () => {
      SUB[`energy_ca_mode_${site}`] = $("eca_mode").value;
      SUB[`energy_ca_date_${site}`] = $("eca_date").value;
      SUB[`energy_ca_month_${site}`] = $("eca_month").value;
      render("energy");
    };
    loadElecCaReport(site);
  }
  if (sec === "update") $("en_save").onclick = () => guard(async () => {
    await POST("/energy/readings", { day: $("en_day").value || null, group_id: $("en_group").value,
      area_id: $("en_area").value || null, value: parseFloat($("en_val").value) });
    toast("Đã lưu số liệu"); SUB.energy = "daily"; render("energy");
  });
  if (sec === "dm") {
    $("eg_add").onclick = () => guard(async () => { await POST("/energy/groups", { code: $("eg_code").value, name: $("eg_name").value, unit: $("eg_unit").value }); toast("Đã thêm nhóm"); render("energy"); });
    $("ea_add").onclick = () => guard(async () => { await POST("/energy/areas", { code: $("ea_code").value, name: $("ea_name").value }); toast("Đã thêm khu"); render("energy"); });
  }
};

// Tải báo cáo Điện (AED) từ CSDL SCADA ngoài SAU khi khung màn hình đã hiện — tự thoát nếu
// người dùng đã chuyển sang tab/mục khác trước khi tải xong.
async function loadElecReport(site) {
  const stillHere = () => $("view-energy").classList.contains("active") && $("elec_summary");
  let hasConn = false;
  try {
    const bounds = await GET(`/energy/external-bounds?site=${site}`);
    hasConn = true;
    if (!stillHere()) return;
    let eFrom = SUB[`energy_ext_from_${site}`], eTo = SUB[`energy_ext_to_${site}`];
    if (!eFrom || !eTo) {
      // Mặc định: đến ngày = đúng thời điểm user vào trang (giờ máy client), từ ngày = 1 ngày trước đó.
      const now = new Date();
      const oneDayAgo = new Date(now); oneDayAgo.setDate(oneDayAgo.getDate() - 1);
      eFrom = toDTLocal(oneDayAgo); eTo = toDTLocal(now);
      SUB[`energy_ext_from_${site}`] = eFrom; SUB[`energy_ext_to_${site}`] = eTo;
      $("erp_from").value = eFrom; $("erp_to").value = eTo;
    }
    const eGb = SUB[`energy_ext_gb_${site}`] || "day";

    const erpt = await GET(`/energy/external-report?date_from=${encodeURIComponent(eFrom)}&date_to=${encodeURIComponent(eTo)}&group_by=${eGb}&site=${site}`);
    if (!stillHere()) return;
    const eColors = ["#3498db", "#f5a623", "#2ecc71", "#e74c3c", "#9b59b6", "#1abc9c", "#e67e22", "#8aa0b2", "#c0392b", "#16a085"];
    const ePeriods = erpt.periods;
    const seriesLookup = {};
    erpt.series.forEach(s => { seriesLookup[`${s.period}|${s.local_id}`] = s.value; });
    const sysNames = erpt.by_system.map(s => s.name);

    const barSeries = ePeriods.map((p, i) => ({
      label: p, color: eColors[i % eColors.length],
      values: erpt.by_system.map(s => seriesLookup[`${p}|${s.local_id}`] || 0),
    }));
    const lineSeries = erpt.by_system.map((s, i) => ({
      label: s.name, color: eColors[i % eColors.length],
      points: ePeriods.map(p => ({ x: p, value: seriesLookup[`${p}|${s.local_id}`] || 0 })),
    }));
    const eTrendChart = eGb === "month" ? CH.groupedN(sysNames, barSeries) : CH.lineMulti(lineSeries);

    const sysItems = erpt.by_system.map(s => ({ label: s.name, value: s.value }));
    const stationItems = erpt.by_station.map(s => ({ label: s.name, value: s.value }));

    $("elec_summary").innerHTML = `<div class="muted" style="margin-bottom:8px">📅 Đang xem dữ liệu từ <b>${fmt(erpt.date_from)}</b> đến <b>${fmt(erpt.date_to)}</b></div>
      <div class="muted" style="margin-bottom:8px">Kết nối "${esc(erpt.connection_name)}" · Dữ liệu chỉ có tới ${esc(bounds.max_date || "?")}.</div>
      <div class="row" style="gap:10px;flex-wrap:wrap">
        <div class="panel" style="flex:1;min-width:220px">
          <div class="muted" style="font-size:12px">TỔNG AED TIÊU THỤ TÍNH THEO HỆ THỐNG</div>
          <div style="font-size:26px;font-weight:700;color:#3498db">${erpt.total_system.toLocaleString("vi-VN")} <span style="font-size:14px;font-weight:400">kWh</span></div>
        </div>
        <div class="panel" style="flex:1;min-width:220px">
          <div class="muted" style="font-size:12px">TỔNG AED TIÊU THỤ TÍNH THEO TRẠM VÀ MÁY PHÁT</div>
          <div style="font-size:26px;font-weight:700;color:#2ecc71">${erpt.total_station.toLocaleString("vi-VN")} <span style="font-size:14px;font-weight:400">kWh</span></div>
        </div>
      </div>
      <div class="split">
        <div class="panel"><h2>Hệ thống tiêu thụ</h2>${sysItems.length ? CH.pie(sysItems) : '<div class="muted">Không có dữ liệu.</div>'}</div>
        <div class="panel"><h2>Trạm điện / máy phát điện</h2>${stationItems.length ? CH.pie(stationItems) : '<div class="muted">Không có dữ liệu.</div>'}</div>
      </div>`;
    if ($("elec_trend")) $("elec_trend").innerHTML = `
      <div class="panel" style="margin-top:16px"><h2>AED theo ${eGb === "month" ? "tháng" : "ngày"} — theo từng hệ</h2>${sysItems.length ? eTrendChart : '<div class="muted">Không có dữ liệu.</div>'}</div>
      <div class="panel"><h2>Phân theo hệ thống</h2>
        <table><thead><tr><th>Hệ thống</th><th>AED (kWh)</th></tr></thead>
        <tbody>${erpt.by_system.map(s => `<tr><td>${esc(s.name)}</td><td>${s.value.toLocaleString("vi-VN")}</td></tr>`).join("") ||
          '<tr><td colspan=2 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div>`;
  } catch (e) {
    if (!stillHere()) return;
    $("elec_summary").innerHTML = `<div class="panel muted">Chưa xem được điện từ SCADA thật: ${esc(e.message)}
      ${hasConn ? "" : '<button class="btn sm sec" id="erp_goto_intg">Đi tới Tích hợp › Kết nối CSDL</button>'}</div>`;
    if ($("erp_goto_intg")) $("erp_goto_intg").onclick = () => gotoView("integration", "dbconn");
  }
}

// Tải báo cáo Điện theo ca (Ca1/Ca2/Ca3) SAU khi khung màn hình đã hiện — tự thoát nếu
// người dùng đã chuyển sang tab/mục khác trước khi tải xong.
async function loadElecCaReport(site) {
  const stillHere = () => $("view-energy").classList.contains("active") && $("elec_ca_data");
  try {
    let dateFrom, dateTo;
    if (SUB[`energy_ca_mode_${site}`] === "month") {
      const [y, m] = SUB[`energy_ca_month_${site}`].split("-").map(Number);
      dateFrom = toDTLocal(new Date(y, m - 1, 1, 6, 0, 0));
      dateTo = toDTLocal(new Date(y, m, 1, 6, 0, 0));
    } else {
      const start = new Date(SUB[`energy_ca_date_${site}`] + "T06:00:00");
      const end = new Date(start); end.setDate(end.getDate() + 1);
      dateFrom = toDTLocal(start); dateTo = toDTLocal(end);
    }

    const rpt = await GET(`/energy/external-ca-report?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}&site=${site}`);
    if (!stillHere()) return;
    const caColors = ["#3498db", "#f5a623", "#9b59b6"];
    const dayLabels = rpt.by_day.map(d => d.date.slice(5));
    const barSeries = [
      { label: "Ca 1 (06h-14h)", color: caColors[0], values: rpt.by_day.map(d => d.ca1) },
      { label: "Ca 2 (14h-22h)", color: caColors[1], values: rpt.by_day.map(d => d.ca2) },
      { label: "Ca 3 (22h-06h)", color: caColors[2], values: rpt.by_day.map(d => d.ca3) },
    ];
    const pieItems = rpt.by_ca.map((c, i) => ({ label: c.label, value: c.value, color: caColors[i] }));

    $("elec_ca_data").innerHTML = `<div class="muted" style="margin-bottom:8px">📅 Đang xem dữ liệu từ <b>${fmt(rpt.date_from)}</b> đến <b>${fmt(rpt.date_to)}</b></div>
      <div class="muted" style="margin-bottom:8px">Kết nối "${esc(rpt.connection_name)}"</div>
      ${rpt.has_gap ? '<div style="color:var(--orange,#f5a623);margin-bottom:8px">⚠ Có 1+ hệ thống bị khoảng trống dữ liệu lớn trong 1+ ca — số ca đó có thể thiếu đóng góp của hệ thống đó.</div>' : ""}
      <div class="row" style="gap:10px;flex-wrap:wrap">
        <div class="panel" style="flex:1;min-width:180px">
          <div class="muted" style="font-size:12px">TỔNG ĐIỆN TIÊU THỤ</div>
          <div style="font-size:26px;font-weight:700;color:#2ecc71">${rpt.total_kwh.toLocaleString("vi-VN")} <span style="font-size:14px;font-weight:400">kWh</span></div>
        </div>
        ${rpt.by_ca.map((c, i) => `<div class="panel" style="flex:1;min-width:160px">
          <div class="muted" style="font-size:12px">${esc(c.label.toUpperCase())}${c.data_gap ? ' ⚠' : ""}</div>
          <div style="font-size:22px;font-weight:700;color:${caColors[i]}">${c.value.toLocaleString("vi-VN")} <span style="font-size:13px;font-weight:400">kWh</span></div>
        </div>`).join("")}
      </div>
      <div class="split">
        <div class="panel"><h2>Tỉ lệ theo ca</h2>${pieItems.some(p => p.value > 0) ? CH.pie(pieItems) : '<div class="muted">Không có dữ liệu.</div>'}</div>
        <div class="panel"><h2>Theo ngày — từng ca</h2>${dayLabels.length ? CH.groupedN(dayLabels, barSeries) : '<div class="muted">Không có dữ liệu.</div>'}</div>
      </div>
      <div class="panel"><h2>Chi tiết theo ca</h2>
        <div class="tablewrap"><table><thead><tr><th>Ngày</th><th>Ca</th><th>Bắt đầu</th><th>Kết thúc</th><th>Điện (kWh)</th></tr></thead>
        <tbody>${rpt.shifts.map(s => `<tr><td>${fmt(s.date)}</td><td>Ca ${s.ca}${s.data_gap ? ' ⚠' : ""}</td>
          <td class="muted">${new Date(s.start).toLocaleString("vi-VN")}</td><td class="muted">${new Date(s.end).toLocaleString("vi-VN")}</td>
          <td${s.data_gap ? ' title="1+ hệ thống bị khoảng trống dữ liệu trong ca này — số có thể thiếu"' : ""}>${s.value.toLocaleString("vi-VN")}</td></tr>`).join("") ||
          '<tr><td colspan=5 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div></div>`;
  } catch (e) {
    if (!stillHere()) return;
    $("elec_ca_data").innerHTML = `<div class="panel muted">Chưa xem được điện theo ca: ${esc(e.message)}</div>`;
  }
}

// ================= BẢO TRÌ =================
VIEWS.maint = async function () {
  const sec = SUB.maint || "incidents";
  const sections = [
    { key: "incidents", label: "Sự cố" }, { key: "plans", label: "Kế hoạch bảo trì" },
    { key: "equipment", label: "DM thiết bị" }, { key: "parts", label: "DM phụ tùng" },
  ];
  let body = "";
  if (sec === "incidents") {
    const [incs, eqs] = await Promise.all([GET("/maint/incidents"), GET("/maint/equipment")]);
    const eqOpts = eqs.map(e => `<option value="${e.equipment_id}">${esc(e.code)} — ${esc(e.name)}</option>`).join("");
    body = `<div class="panel"><h2>Thêm sự cố mới</h2>
      <div class="row"><div class="field"><label>Thiết bị</label><select id="ic_eq">${eqOpts}</select></div>
        <div class="field"><label>Tiêu đề</label><input id="ic_title"/></div>
        <div class="field"><label>Mức</label><select id="ic_sev"><option>minor</option><option>major</option><option>critical</option></select></div>
        <button class="btn" id="ic_add">Thêm sự cố</button></div></div>
      <div class="panel"><h2>Danh sách sự cố</h2>
      <input class="searchbox" data-tbl="t_incidents" placeholder="Tìm theo mã, thiết bị, tiêu đề, trạng thái..."/>
      <div class="tablewrap"><table id="t_incidents"><thead><tr><th>Mã</th><th>Thiết bị</th><th>Tiêu đề</th><th>Mức</th><th>Trạng thái</th><th>Dừng (phút)</th><th></th></tr></thead>
      <tbody>${incs.map(i => { const eq = eqs.find(e => e.equipment_id === i.equipment_id);
        return `<tr><td><code class="k">${esc(i.incident_code)}</code></td><td>${esc(eq ? eq.code : "")}</td>
        <td>${esc(i.title)}</td><td>${badge(i.severity)}</td><td>${badge(i.status)}</td><td>${i.downtime_min}</td>
        <td>${i.status === "open" || i.status === "in_progress" ? `<button class="btn sm sec" data-resolve="${i.incident_id}">Xử lý xong</button>` : ""}</td></tr>`; }).join("")}</tbody></table></div></div>`;
  } else if (sec === "plans") {
    const [plans, eqs] = await Promise.all([GET("/maint/plans"), GET("/maint/equipment")]);
    const eqOpts = eqs.map(e => `<option value="${e.equipment_id}">${esc(e.code)}</option>`).join("");
    const typeLabel = { bao_tri: "Bảo trì", kiem_tra: "Kiểm tra", tu_bo: "Tu bổ" };
    body = `<div class="panel"><h2>Tạo kế hoạch</h2>
      <div class="row"><div class="field"><label>Thiết bị</label><select id="pl_eq">${eqOpts}</select></div>
        <div class="field"><label>Loại</label><select id="pl_type"><option value="bao_tri">Bảo trì</option><option value="kiem_tra">Kiểm tra</option><option value="tu_bo">Tu bổ</option></select></div>
        <div class="field"><label>Ngày</label><input id="pl_date" type="date"/></div>
        <div class="field"><label>Ghi chú</label><input id="pl_note"/></div>
        <button class="btn" id="pl_add">Thêm</button></div></div>
      <div class="panel"><h2>Kế hoạch bảo trì</h2>
      <input class="searchbox" data-tbl="t_plans" placeholder="Tìm theo thiết bị, loại, trạng thái..."/>
      <div class="tablewrap"><table id="t_plans"><thead><tr><th>Thiết bị</th><th>Loại</th><th>Ngày</th><th>Trạng thái</th><th>Ghi chú</th><th></th></tr></thead>
      <tbody>${plans.map(p => `<tr><td>${esc(p.equipment)}</td><td>${esc(typeLabel[p.plan_type] || p.plan_type)}</td>
        <td>${fmt(p.scheduled_date)}</td><td>${badge(p.status)}</td><td class="muted">${esc(p.note || "")}</td>
        <td>${p.status !== "done" ? `<button class="btn sm sec" data-plandone="${p.plan_id}">Hoàn thành</button>` : ""}</td></tr>`).join("")}</tbody></table></div></div>`;
  } else if (sec === "equipment") {
    const eqs = await GET("/maint/equipment");
    body = `<div class="panel"><h2>Danh mục thiết bị</h2>
      <div class="row"><div class="field"><label>Mã</label><input id="eq_code"/></div><div class="field"><label>Tên</label><input id="eq_name"/></div>
        <div class="field"><label>Loại</label><input id="eq_type"/></div><div class="field"><label>Hệ thống</label><input id="eq_sys"/></div>
        <button class="btn sm" id="eq_add">+ Thêm</button></div>
      <table><thead><tr><th>Mã</th><th>Tên</th><th>Loại</th><th>Hệ thống</th><th>Vị trí</th><th>Trạng thái</th></tr></thead>
      <tbody>${eqs.map(e => `<tr><td><code class="k">${esc(e.code)}</code></td><td>${esc(e.name)}</td><td class="muted">${esc(e.eq_type || "")}</td>
        <td class="muted">${esc(e.system || "")}</td><td class="muted">${esc(e.location || "")}</td><td>${badge(e.status)}</td></tr>`).join("")}</tbody></table></div>`;
  } else if (sec === "parts") {
    const parts = await GET("/maint/parts");
    body = `<div class="panel"><h2>Danh mục phụ tùng</h2>
      <table><thead><tr><th>Mã</th><th>Tên</th><th>Tồn</th><th>Tồn min</th><th>Cảnh báo</th></tr></thead>
      <tbody>${parts.map(p => `<tr><td><code class="k">${esc(p.code)}</code></td><td>${esc(p.name)}</td><td>${p.stock} ${p.uom}</td>
        <td>${p.stock_min}</td><td>${p.below_min ? badge("overdue") + "Dưới mức min" : badge("ok") + "OK"}</td></tr>`).join("")}</tbody></table></div>`;
  }
  $("view-maint").innerHTML = subnav("maint", sections, sec) + body;
  wireSubnav("maint"); wireSearch();
  wirePaginate("t_incidents", 10); wirePaginate("t_plans", 10);
  if (sec === "incidents") {
    $("ic_add").onclick = () => guard(async () => { await POST("/maint/incidents", { equipment_id: $("ic_eq").value, title: $("ic_title").value, severity: $("ic_sev").value }); toast("Đã thêm sự cố"); render("maint"); });
    document.querySelectorAll("[data-resolve]").forEach(b => b.onclick = () => guard(async () => {
      const dt = prompt("Thời gian dừng máy (phút):", "30"); if (dt === null) return;
      await POST(`/maint/incidents/${b.dataset.resolve}/resolve?downtime_min=${parseFloat(dt) || 0}&resolution=Đã khắc phục`); toast("Đã xử lý"); render("maint");
    }));
  }
  if (sec === "plans") {
    $("pl_add").onclick = () => guard(async () => { await POST("/maint/plans", { equipment_id: $("pl_eq").value, plan_type: $("pl_type").value, scheduled_date: $("pl_date").value, note: $("pl_note").value }); toast("Đã thêm kế hoạch"); render("maint"); });
    document.querySelectorAll("[data-plandone]").forEach(b => b.onclick = () => guard(async () => { await POST(`/maint/plans/${b.dataset.plandone}/done`); toast("Đã hoàn thành"); render("maint"); }));
  }
  if (sec === "equipment") $("eq_add").onclick = () => guard(async () => { await POST("/maint/equipment", { code: $("eq_code").value, name: $("eq_name").value, eq_type: $("eq_type").value, system: $("eq_sys").value }); toast("Đã thêm thiết bị"); render("maint"); });
};

// ================= KIỂM ĐỊNH =================
VIEWS.calib = async function () {
  const [items, eqs] = await Promise.all([GET("/maint/calibrations"), GET("/maint/equipment")]);
  const typeLabel = { phong_xa: "Nguồn phóng xạ", van_an_toan: "Van an toàn", hieu_chuan_tbd: "Hiệu chuẩn TBĐ", yc_nnvat: "TB YCNNVAT" };
  const eqOpts = `<option value="">(không gắn TB)</option>` + eqs.map(e => `<option value="${e.equipment_id}">${esc(e.code)}</option>`).join("");
  $("view-calib").innerHTML = `
    <div class="panel"><h2>Thêm kiểm định / hiệu chuẩn</h2>
      <div class="row"><div class="field"><label>Tên</label><input id="cb_name"/></div>
        <div class="field"><label>Loại</label><select id="cb_type">
          <option value="hieu_chuan_tbd">Hiệu chuẩn TBĐ</option><option value="van_an_toan">Van an toàn</option>
          <option value="phong_xa">Nguồn phóng xạ</option><option value="yc_nnvat">TB YCNNVAT</option></select></div>
        <div class="field"><label>Thiết bị</label><select id="cb_eq">${eqOpts}</select></div>
        <div class="field"><label>Hạn kiểm định</label><input id="cb_due" type="date"/></div>
        <button class="btn" id="cb_add">Thêm</button></div></div>
    <div class="panel"><h2>Danh sách kiểm định</h2>
      <input class="searchbox" data-tbl="t_calib" placeholder="Tìm theo tên, loại, thiết bị, trạng thái..."/>
      <div class="tablewrap"><table id="t_calib"><thead><tr><th>Tên</th><th>Loại</th><th>Thiết bị</th><th>Lần cuối</th><th>Hạn</th><th>Còn (ngày)</th><th>Trạng thái</th></tr></thead>
      <tbody>${items.map(c => `<tr><td>${esc(c.name)}</td><td>${esc(typeLabel[c.calib_type] || c.calib_type)}</td>
        <td class="muted">${esc(c.equipment || "")}</td><td class="muted">${fmt(c.last_date)}</td><td>${fmt(c.due_date)}</td>
        <td>${c.days_left}</td><td>${badge(c.status)}</td></tr>`).join("")}</tbody></table></div></div>`;
  wireSearch(); wirePaginate("t_calib", 10);
  $("cb_add").onclick = () => guard(async () => {
    await POST("/maint/calibrations", { name: $("cb_name").value, calib_type: $("cb_type").value,
      equipment_id: $("cb_eq").value || null, due_date: $("cb_due").value });
    toast("Đã thêm kiểm định"); render("calib");
  });
};

// Ô tìm kiếm đi kèm 1 <select> nhiều lựa chọn (sản phẩm, nơi xuất đến...) — ẩn các
// <option> không khớp để dò nhanh hơn cuộn tay, vẫn giữ nguyên hành vi chọn/submit của select.
function wireSelectSearch(selectId, searchId) {
  const sel = document.getElementById(selectId);
  const inp = document.getElementById(searchId);
  if (!sel || !inp) return;
  const opts = Array.from(sel.options).filter(o => o.value);
  inp.oninput = () => {
    const q = inp.value.toLowerCase();
    opts.forEach(o => { o.hidden = q && !o.textContent.toLowerCase().includes(q); });
  };
}

// ================= NẤU-LỌC-CHIẾT (chi tiết theo công đoạn) =================
function wireSearch() {
  document.querySelectorAll(".searchbox[data-tbl]").forEach(inp => {
    const table = document.getElementById(inp.dataset.tbl);
    if (table && table.dataset.paginated === "1") return; // wirePaginate() tự xử lý tìm kiếm + phân trang
    inp.oninput = () => {
      const q = inp.value.toLowerCase();
      document.querySelectorAll(`#${inp.dataset.tbl} tbody tr`).forEach(tr =>
        tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none");
    };
  });
}

const _pagerState = {};
// Phân trang cho bảng dài (danh mục hàng chục/hàng trăm dòng) — kèm ô tìm kiếm
// .searchbox[data-tbl="<tableId>"] nếu có, để tránh phải kéo chuột qua toàn bộ danh sách.
function wirePaginate(tableId, defaultPageSize = 10) {
  const table = document.getElementById(tableId);
  if (!table) return;
  table.dataset.paginated = "1";
  const tbody = table.querySelector("tbody");
  const allRows = Array.from(tbody.children);
  const searchInput = document.querySelector(`.searchbox[data-tbl="${tableId}"]`);
  const state = _pagerState[tableId] || { page: 1, pageSize: defaultPageSize };
  _pagerState[tableId] = state;

  let bar = table.nextElementSibling;
  if (!bar || !bar.classList.contains("pager-bar")) {
    bar = document.createElement("div");
    bar.className = "pager-bar";
    table.insertAdjacentElement("afterend", bar);
  }

  function rowText(tr) {
    // gồm cả giá trị input/select (nhiều bảng danh mục cho sửa trực tiếp trên dòng,
    // nên textContent thuần không thấy được nội dung ô mã/tên/địa chỉ...)
    const fieldVals = Array.from(tr.querySelectorAll("input, select"))
      .map(f => f.tagName === "SELECT" ? (f.selectedOptions[0]?.textContent || "") : f.value).join(" ");
    return (tr.textContent + " " + fieldVals).toLowerCase();
  }

  function apply() {
    const q = (searchInput?.value || "").toLowerCase();
    const matched = q ? allRows.filter(tr => rowText(tr).includes(q)) : allRows;
    const pageSize = state.pageSize;
    const totalPages = pageSize === Infinity ? 1 : Math.max(1, Math.ceil(matched.length / pageSize));
    if (state.page > totalPages) state.page = totalPages;
    const start = pageSize === Infinity ? 0 : (state.page - 1) * pageSize;
    const end = pageSize === Infinity ? matched.length : start + pageSize;
    const visible = new Set(matched.slice(start, end));
    allRows.forEach(tr => { tr.style.display = visible.has(tr) ? "" : "none"; });
    bar.innerHTML = `
      <span class="muted">${matched.length} dòng${q ? " (đã lọc)" : ""}</span>
      <button type="button" class="btn sm sec" data-pg="prev" ${state.page <= 1 ? "disabled" : ""}>‹ Trước</button>
      <span class="muted">Trang ${state.page}/${totalPages}</span>
      <button type="button" class="btn sm sec" data-pg="next" ${state.page >= totalPages ? "disabled" : ""}>Sau ›</button>
      <select data-pg="size" style="width:auto">
        ${[10, 25, 50, 100].map(n => `<option value="${n}" ${state.pageSize === n ? "selected" : ""}>${n}/trang</option>`).join("")}
        <option value="all" ${state.pageSize === Infinity ? "selected" : ""}>Hiển thị tất cả</option>
      </select>`;
    bar.querySelector('[data-pg="prev"]').onclick = () => { state.page--; apply(); };
    bar.querySelector('[data-pg="next"]').onclick = () => { state.page++; apply(); };
    bar.querySelector('[data-pg="size"]').onchange = (e) => {
      state.pageSize = e.target.value === "all" ? Infinity : parseInt(e.target.value, 10);
      state.page = 1; apply();
    };
  }
  if (searchInput) searchInput.oninput = () => { state.page = 1; apply(); };
  apply();
}
const chk = (v) => v ? '<span class="chk">✔</span>' : '<span class="chk no">▢</span>';

VIEWS.process = async function () {
  const sec = SUB.process || "nguyenlieu";
  const sections = [
    { key: "nguyenlieu", label: "Nguyên liệu" }, { key: "nau", label: "Nấu" },
    { key: "lenmen", label: "Lên men" }, { key: "loc", label: "Lọc" },
    { key: "chiet", label: "Chiết" }, { key: "canhbao", label: "Cảnh báo chỉ tiêu" },
    { key: "hoachat", label: "Hóa chất" }, { key: "men", label: "Thu hồi men" },
  ];
  let body = "";
  let mastersLf = [];
  let mastersLn = [];
  let lotsByMaterial = {};

  if (sec === "nguyenlieu") {
    const nlLoc = SUB.process_nl_loc || "";
    const [stock, lots] = await Promise.all([
      GET("/warehouse/stock" + (nlLoc ? "?location=" + encodeURIComponent(nlLoc) : "")),
      GET("/lots")]);
    const matchesLoc = (loc) => !nlLoc || (/phân xưởng/i.test(nlLoc) === /phân xưởng/i.test(loc || ""));
    lots.filter(l => l.quantity > 0 && matchesLoc(l.location)).forEach(l => {
      (lotsByMaterial[l.material_id] = lotsByMaterial[l.material_id] || []).push(l);
    });
    const whOpts = ["", "Kho công ty", "Kho phân xưởng"].map(v =>
      `<option value="${esc(v)}" ${v === nlLoc ? "selected" : ""}>${v || "(Tất cả)"}</option>`).join("");
    const NL_LOT_CELL_MAX = 3;
    const nlLotChip = (l) => `<code class="k">${esc(l.lot_code)}</code> (${l.quantity}${l.uom}${l.status === "on_hold" ? ", CHỜ QC" : ""})`;
    body = `<div class="panel"><h2>Tồn kho NVL theo kho <span class="muted">(${stock.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Tồn kho thật từ hệ thống Kho NVL — nguyên liệu phân bổ vào mẻ nấu (nút "+NVL" ở tab Nấu) lấy từ <b>Kho phân xưởng</b>.</div>
      <div class="row" style="margin-bottom:8px"><div class="field"><label>Kho</label><select id="nl_loc">${whOpts}</select></div></div>
      <div class="tablewrap"><table><thead><tr><th>Mã VT</th><th>Tên</th><th>Nhóm</th><th>Mã lô</th><th>Tồn</th><th>ĐVT</th></tr></thead>
      <tbody>${stock.map(s => { const matLots = (lotsByMaterial[s.material_id] || [])
          .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
        const shown = matLots.slice(0, NL_LOT_CELL_MAX);
        const rest = matLots.length - shown.length;
        const lotCell = shown.map(nlLotChip).join(", ") +
          (rest > 0 ? ` <button type="button" class="btn sm sec" data-viewlots="${esc(s.material_id)}" data-matlabel="${esc(s.material_code)} — ${esc(s.material_name)}">+${rest} lô khác</button>` : "");
        return `<tr><td><code class="k">${esc(s.material_code)}</code></td><td>${esc(s.material_name)}</td>
        <td class="muted">${esc(s.category || "")}</td>
        <td class="muted">${lotCell || "—"}</td>
        <td>${s.on_hand}</td><td>${s.uom}</td></tr>`; }).join("") ||
        '<tr><td colspan=6 class="muted">Không có tồn kho.</td></tr>'}</tbody></table></div></div>`;
  }

  else if (sec === "nau") {
    const [rows, fermentTanks, yeast, products, brewMasters] = await Promise.all([
      GET("/brewing/brews"), GET("/brewing/ferment-tanks").catch(() => []), GET("/process/yeast").catch(() => []),
      GET("/products").catch(() => []), GET("/brewing/brew-master-orders").catch(() => [])]);
    // Chỉ hiện tank lên men đang TRỐNG (không bị 1 lô LM còn hoạt động chiếm dụng) — xem
    // services/dashboard.py::available_ferment_tanks.
    const tankOptsNau = fermentTanks.filter(t => !t.occupied).map(t => `<option value="${esc(t.code)}">${esc(t.code)}</option>`).join("") ||
      `<option value="">(không còn tank trống — khai báo thêm ở Danh mục)</option>`;
    const yeastOpts = `<option value="">(không chọn)</option>` + yeast.filter(y => y.status === "available")
      .map(y => `<option value="${esc(y.code)}">${esc(y.code)} (${y.strain}, đời ${y.generation})</option>`).join("");
    const wortOpts = `<option value="">(chọn dịch bia)</option>` + products.map(p =>
      `<option value="${esc(p.product_id)}">${esc(p.name)}</option>`).join("") ||
      `<option value="">(chưa có dịch bia nào — khai báo Dịch bia ở Danh mục)</option>`;
    const canLockLot = _hasPerm("quality.release");
    const isAdminLot = CURRENT_USER && CURRENT_USER.role === "admin";
    // Nhóm các "lệnh nấu nhỏ" CHƯA hoàn thành theo "lệnh nấu lớn" — chọn theo 2 bước: chọn
    // Lệnh nấu (lớn) rồi chọn đúng Lệnh nấu nhỏ bên trong để tạo mã nấu (mirror Lọc).
    mastersLn = brewMasters.map(m => ({ id: m.brew_master_order_id, code: m.order_code,
      children: m.children.filter(c => !c.is_complete) })).filter(m => m.children.length);
    const masterOptsLn = `<option value="">(chọn Lệnh nấu — bắt buộc)</option>` + mastersLn.map(m =>
      `<option value="${esc(m.id)}">${esc(m.code)} (${m.children.length} lệnh nhỏ chưa xong)</option>`).join("");
    body = `<div class="panel"><h2>Thêm thông tin nấu</h2>
      <div class="muted" style="margin-bottom:6px">1 mã nấu = 1 lần nấu vào 1 tank — chọn <b>Tank lên men</b> để tự động chuyển mã nấu này sang lên men (xem ở tab "Lên men").
        Sau khi tạo, bấm "Mẻ" trên dòng đó để khai báo các mẻ cụ thể (số mẻ từ Braumat, VD 123,124,125,126) — mỗi mẻ nhập nguyên liệu &amp; chỉ tiêu riêng.
        Chọn <b>Lệnh nấu</b> rồi chọn đúng <b>Lệnh nấu nhỏ</b> (chưa hoàn thành) bên trong — <b>Dịch bia</b> trích tự động từ lệnh nhỏ đã chọn (không sửa
        được, tránh lệch giữa mã nấu và lệnh nấu) — nếu lệnh nhỏ chưa gắn dịch bia thì chọn tay. Tạo lệnh mới ở tab "Lệnh nấu" nếu danh sách trống.
        <b>Tank lên men</b> chỉ hiện tank đang trống (không bị lô LM khác chiếm dụng).
        <b>Ngày KT (nạp đầy tank)</b> không nhập tay — tự tính bằng giờ kết thúc của mẻ cuối cùng khi vận hành bấm "Kết thúc" ở mẻ đó, hiển thị ở cột tương ứng bên dưới.</div>
      <div class="row">
        <div class="field"><label>Lệnh nấu</label><select id="nb_master">${masterOptsLn}</select></div>
        <div class="field"><label>Lệnh nấu nhỏ</label><select id="nb_order"><option value="">(chọn Lệnh nấu trước)</option></select></div>
        <div class="field"><label>Mã nấu</label><input id="nb_code" placeholder="VD: N-0715"/></div>
        <div class="field"><label>Ngày nấu</label><input id="nb_date" type="datetime-local"/></div>
      </div>
      <div class="row">
        <div class="field"><label>Dịch bia</label><select id="nb_wort">${wortOpts}</select></div>
        <div class="field"><label>SL nấu/hl</label><input id="nb_vol" type="number" value="900"/></div>
        <div class="field"><label>Tank lên men</label><select id="nb_tank"><option value="">(chưa chuyển lên men)</option>${tankOptsNau}</select></div>
        <div class="field"><label>Men sử dụng</label><select id="nb_yeast">${yeastOpts}</select></div>
      </div>
      <div class="row">
        <div class="field" style="flex:1"><label>Ghi chú</label><input id="nb_note" placeholder="(tuỳ chọn)"/></div>
        <button class="btn" id="nb_add" style="align-self:flex-end">Thêm</button>
      </div></div>
      <div class="panel"><h2>Thông tin nấu <span class="muted">(${rows.length})</span></h2>
      <input class="searchbox" data-tbl="t_nau" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_nau"><thead><tr><th>Mã nấu</th><th>Lệnh nấu</th><th>Ngày nấu</th><th>Dịch nha</th><th>SL kế hoạch/hl</th><th>SL thực tế/hl</th>
        <th>Lô LM</th><th>Tank</th><th>Ngày KT (nạp đầy tank)</th><th>Số mẻ</th><th></th><th>Khóa lô</th></tr></thead>
      <tbody>${rows.map(b => `<tr class="row-${b.color}"><td class="code">${esc(b.brew_code)}</td>
        <td class="muted">${esc(b.brew_order_code || "—")}</td><td>${fmt(b.brew_date)}</td>
        <td>${esc(b.wort_type)}</td><td>${b.volume_hl}</td>
        <td class="muted" title="Tổng &quot;Tổng lượng dịch&quot; (Ghi chép nấu) cộng dồn qua các mẻ">${b.actual_volume_hl ?? "—"}</td>
        <td class="muted">${esc(b.lm_code || "—")}</td><td class="muted">${esc(b.tank_lm || "—")}</td>
        <td class="muted">${b.kt_date ? fmt(b.kt_date) : "—"}</td><td class="muted">${b.batch_count}</td>
        <td style="white-space:nowrap"><button class="btn sm" data-brewbatches="${esc(b.brew_id)}|${esc(b.brew_code)}|${esc(b.product_id || "")}|${b.locked ? "1" : "0"}">Mẻ (${b.batch_count})</button>
          ${b.locked ? "" : `<button class="btn sm sec" data-delrec="brew|${esc(b.brew_id)}">Xóa</button>`}</td>
        <td style="white-space:nowrap">${b.locked
            ? (isAdminLot ? `<button class="btn sm sec" data-unlocklot="brew|${esc(b.brew_id)}">Mở khóa</button>` : '<span class="muted">—</span>')
            : (canLockLot ? `<button class="btn sm" data-locklot="brew|${esc(b.brew_id)}">Khóa lô</button>` : '<span class="muted">—</span>')}</td></tr>`).join("")}</tbody></table></div>
      <div class="legend">Bấm "Mẻ" để khai báo/xem các mẻ cụ thể của mã nấu này. Chú thích màu:
        <b class="red">Đỏ</b>: Có mẻ thiếu chỉ tiêu bắt buộc, hoặc đã nhập đủ nhưng có chỉ tiêu FAIL (ngoài khoảng min-max) — <b class="green">Xanh lá</b>: Đủ chỉ tiêu (không FAIL) nhưng có mẻ chưa nhập NVL —
        <b class="blue">Xanh dương</b>: Tất cả mẻ đầy đủ.</div></div>`;
  }

  else if (sec === "lenmen") {
    const data = await GET("/brewing/ferments");
    // dang_nau: còn mẻ nấu nào của mã nấu nạp vào tank này chưa "Kết thúc" — chưa thật sự
    // lên men dù đã có dịch trong tank, xem services/derived.py::ferment_status.
    const stLabel = { dang_nau: "Đang nấu", len_men: "Đang lên men", loc_mot_phan: "Lọc 1 phần", da_loc_het: "Lọc hết" };
    const stBadge = { dang_nau: "in_progress", len_men: "running", loc_mot_phan: "due", da_loc_het: "done" };
    const canApproveLm = _hasPerm("quality.release");
    const canLockLot = _hasPerm("quality.release");
    const isAdminLot = CURRENT_USER && CURRENT_USER.role === "admin";
    const daysFermentedCell = (r) => {
      if (!r.kt_date) return '<span class="muted">—</span>';
      let diffMs = new Date() - new Date(r.kt_date);
      if (diffMs < 0) diffMs = 0;
      const totalMin = Math.floor(diffMs / 60000);
      const d = Math.floor(totalMin / 1440), h = Math.floor((totalMin % 1440) / 60), m = totalMin % 60;
      const dd = String(d), hh = String(h).padStart(2, "0"), mm = String(m).padStart(2, "0");
      return `${dd}.${hh}.${mm}${r.ferment_days_std ? ` / ${r.ferment_days_std} ngày` : ""}`;
    };
    const readyBadge = (r) => {
      if (r.qc_approved) return '<span class="muted">—</span>';
      if (!r.ready_date) return '<span class="muted">—</span>';
      const ready = new Date(r.ready_date) <= new Date();
      return ready ? `<span style="color:var(--red)">Đủ ${r.ferment_days_std} ngày — chờ KCS duyệt</span>` :
        `<span class="muted">Còn ${Math.max(0, r.ferment_days_std - (r.days_elapsed ?? 0))} ngày (dự kiến ${fmt(r.ready_date)})</span>`;
    };
    body = `<div class="panel"><h2>Thông tin quá trình lên men <span class="muted">(${data.items.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Tank &amp; lô LM được gán ngay lúc tạo mẻ nấu (tab "Nấu") — 1 tank có thể nhận nhiều mẻ.
        Tab này chỉ dùng để xem &amp; khai báo chỉ tiêu lên men chính/phụ. Số ngày lên men chuẩn khai báo theo loại bia ở Danh mục —
        sau khi đủ ngày, KCS ký duyệt "tank lên men đạt" mới được tạo bản ghi Lọc từ tank đó.</div>
      <input class="searchbox" data-tbl="t_lm" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_lm"><thead><tr><th>Duyệt</th><th>Chỉ tiêu</th><th>Lô LM</th><th>Mã nấu</th><th>Ngày nấu</th><th>Ngày KT</th><th>Số ngày đã lên men</th><th>Số mẻ</th>
        <th>Dịch nha</th><th>Đời men</th><th>Tank LM</th><th>SL nấu/hl</th><th>Đang tồn CCT/hl</th><th>Trạng thái</th><th>Sẵn sàng chiết</th><th></th><th>Khóa lô</th></tr></thead>
      <tbody>${data.items.map(r => `<tr class="row-${r.color}">
        <td style="white-space:nowrap">${r.locked ? lockBadgeHtml(r) : (r.qc_approved
            ? `<span style="color:var(--green)">✓ ${esc(r.qc_approved_by || "")}</span><div class="muted">${fmt(r.qc_approved_at)}</div>`
            : (canApproveLm ? `<button class="btn sm" data-lmapprove="${esc(r.ferment_id)}">Duyệt LM (KCS)</button>` : '<span class="muted">—</span>'))}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-stageqc="len_men_chinh|ferment|${esc(r.lm_code)}__len_men_chinh|${esc(r.product_id || "")}">CT chính</button>
          <button class="btn sm sec" data-stageqc="len_men_phu|ferment|${esc(r.lm_code)}__len_men_phu|${esc(r.product_id || "")}">CT phụ</button></td>
        <td>${holdBadgeHtml(r)}${esc(r.lm_code)}</td><td>${esc(r.brew_code || "")}</td><td>${fmt(r.brew_date)}</td>
        <td>${fmt(r.kt_date)}</td><td>${daysFermentedCell(r)}</td><td class="muted">${esc(r.batch_numbers || "")}</td><td>${esc(r.wort_type)}</td>
        <td class="muted">${esc(r.yeast_gen || "")}</td><td>${esc(r.tank_lm)}</td><td>${r.volume_hl.toLocaleString("vi-VN")}</td>
        <td>${r.on_hand_cct.toLocaleString("vi-VN")}</td><td>${badge(stBadge[r.status] || "planned")}${stLabel[r.status] || r.status}</td>
        <td>${readyBadge(r)}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-fermentlog="${esc(r.ferment_id)}|${esc(r.lm_code)}">Ghi chép LM</button>
          ${r.locked ? "" : `<button class="btn sm sec" data-delrec="ferment|${esc(r.ferment_id)}">Xóa</button>`}</td>
        <td style="white-space:nowrap">${r.locked
            ? (isAdminLot ? `<button class="btn sm sec" data-unlocklot="ferment|${esc(r.ferment_id)}">Mở khóa</button>` : '<span class="muted">—</span>')
            : (canLockLot ? `<button class="btn sm" data-locklot="ferment|${esc(r.ferment_id)}">Khóa lô</button>` : '<span class="muted">—</span>')}</td></tr>`).join("")}
      <tr style="font-weight:700"><td colspan=10 style="text-align:right">Tổng cộng:</td><td>${data.total_brew_hl.toLocaleString("vi-VN")}</td><td>${data.total_cct_hl.toLocaleString("vi-VN")}</td><td colspan=4></td></tr></tbody></table></div>
      <div class="legend">Chú thích: <b class="red">Đỏ</b>: Thiếu chỉ tiêu bắt buộc, hoặc đã đủ nhưng có chỉ tiêu FAIL — <b class="blue">Xanh dương</b>: Đầy đủ, không FAIL</div></div>`;
  }

  else if (sec === "loc") {
    const [rows, filterOrders, lines, bbtTanksLoc] = await Promise.all([
      GET("/brewing/filters"), GET("/brewing/filter-orders"), GET("/lines").catch(() => []),
      GET("/brewing/bbt-tanks").catch(() => [])]);
    const canApproveFilter = _hasPerm("quality.release");
    const canLockLot = _hasPerm("quality.release");
    const isAdminLot = CURRENT_USER && CURRENT_USER.role === "admin";
    const ordersById = Object.fromEntries(filterOrders.map(o => [o.filter_order_id, o]));
    const availableOrders = filterOrders.filter(o => !o.is_complete);
    // Nhóm các "lệnh lọc nhỏ" CHƯA hoàn thành theo "lệnh lọc lớn" (master_order_id) — chọn
    // theo 2 bước: chọn Lệnh lọc (lớn) rồi chọn đúng Lệnh lọc nhỏ bên trong để thực hiện lọc.
    const mastersMap = new Map();
    for (const o of availableOrders) {
      if (!o.master_order_id) continue;
      if (!mastersMap.has(o.master_order_id)) mastersMap.set(o.master_order_id, { id: o.master_order_id, code: o.master_order_code, children: [] });
      mastersMap.get(o.master_order_id).children.push(o);
    }
    mastersLf = [...mastersMap.values()];
    mastersLf.forEach(m => m.children.sort((a, b) => (a.seq || 0) - (b.seq || 0)));
    const masterOptsLf = `<option value="">(chọn Lệnh lọc — bắt buộc)</option>` + mastersLf.map(m =>
      `<option value="${esc(m.id)}">${esc(m.code)} (${m.children.length} lệnh nhỏ chưa xong)</option>`).join("");
    // Tank BBT đang bị chiếm dụng (đang lọc vào dở dang HOẶC còn dịch chưa chiết hết) không
    // cho chọn làm đích lọc mới — tránh 2 lô lọc khác nhau vô tình đổ chung 1 tank vật lý
    // (mirror server-side filter_order_svc._bbt_target_blocked_by, áp dụng thêm ở UI để
    // không phải bấm thử mới biết bị chặn).
    const occupiedBbtCodes = new Set(bbtTanksLoc.filter(t => !t.all_finished || t.on_hand_bbt > 1e-6).map(t => t.to_bbt));
    const freeBbtLines = lines.filter(l => l.kind === "tank_bbt" && !occupiedBbtCodes.has(l.code));
    const bbtOpts = freeBbtLines.map(l => `<option value="${esc(l.code)}">${esc(l.code)}</option>`).join("") ||
      `<option value="">(không còn Tank BBT trống — tank khác đang lọc/còn dịch chưa chiết hết)</option>`;
    body = `<div class="panel"><h2>Thêm thông tin lọc (Lọc thường)</h2>
      <div class="muted" style="margin-bottom:6px">Bắt buộc chọn <b>Lệnh lọc</b> rồi chọn đúng <b>Lệnh lọc nhỏ</b> bên trong (chưa dùng hết) — tạo lệnh mới ở tab "Lệnh lọc" nếu danh sách trống; tank nguồn kế thừa từ lệnh nhỏ đã chọn, không chọn lại.
        Dịch nha lọc/Sản lượng lọc chưa cần điền ngay — sẽ nhập khi bấm "Kết thúc" từng tank (kèm nước bài khí, sản lượng tự tính = dịch nha lọc + nước bài khí, cộng dồn nếu lọc phối).</div>
      <div class="row">
        <div class="field"><label>Lệnh lọc</label><select id="fl_master">${masterOptsLf}</select></div>
        <div class="field"><label>Lệnh lọc nhỏ</label><select id="fl_order"><option value="">(chọn Lệnh lọc trước)</option></select></div>
        <div class="field"><label>Loại bia</label><div id="fl_beer_display" class="muted" style="padding:6px 0">— (chọn Lệnh lọc nhỏ trước)</div></div>
        <div class="field"><label>Cho vào Tank BBT</label><select id="fl_bbt"><option value=""></option>${bbtOpts}</select>
          <div id="fl_bbt_locked" class="muted" style="padding:6px 0;display:none"></div></div>
        <button class="btn" id="fl_add">Thêm</button>
      </div></div>
      <div class="panel"><h2>Thông tin lọc <span class="muted">(${rows.length})</span></h2>
      <input class="searchbox" data-tbl="t_loc" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_loc"><thead><tr><th>Duyệt KCS</th><th>Chỉ tiêu</th><th>Mã lọc</th><th>Lệnh lọc</th><th>Mã nấu</th><th>Ngày lọc</th>
        <th>Loại dịch nha lọc</th><th>Lọc từ CCT</th><th>V dịch/hl</th><th>Nước bài khí/hl</th><th>Loại bia lọc</th><th>Sản phẩm</th><th>V Bia/hl</th><th>Lọc cho vào</th>
        <th>Trạng thái</th><th>Đang tồn BBT/hl</th><th>Kết thúc</th><th>TH thực tế</th><th></th><th></th><th>Khóa lô</th></tr></thead>
      <tbody>${rows.map(r => { const tankCount = ordersById[r.filter_order_id]?.tanks?.length || 0;
        const ord = ordersById[r.filter_order_id];
        const lenhLocText = ord && ord.master_order_code ? `${esc(ord.master_order_code)}${ord.seq ? ` (nhỏ #${ord.seq})` : ""}` : "—";
        return `<tr class="row-${r.color}">
        <td style="white-space:nowrap">${r.locked ? lockBadgeHtml(r) : (r.qc_approved ? `<span style="color:var(--green)">✓ ${esc(r.qc_approved_by || "")}</span><div class="muted">${fmt(r.qc_approved_at)}</div>`
          : (r.exec_status !== "hoan_thanh") ? `<span class="muted" title="Chỉ duyệt được khi đã lọc xong (kết thúc hết các tank)">— (đang lọc)</span>`
          : (canApproveFilter ? `<button class="btn sm" data-filterapprove="${esc(r.filter_id)}">Duyệt KCS</button>` : '<span class="muted">—</span>'))}</td>
        <td><button class="btn sm sec" data-stageqc="loc|filter|${esc(r.filter_code)}|${esc(r.product_id || "")}|${esc(r.finished_product_id || "")}|${""}|${esc(r.beer_type_id || "")}">Chỉ tiêu</button></td><td class="code">${holdBadgeHtml(r)}${esc(r.filter_code)}</td>
        <td class="muted">${lenhLocText}</td><td>${esc(r.brew_code || "")}</td>
        <td>${fmt(r.filter_date)}</td><td>${esc(r.wort_type || "")}</td><td>${esc(r.from_cct || "")}</td><td>${r.v_dich_hl > 0 ? r.v_dich_hl : "—"}</td>
        <td>${r.nuoc_bai_khi_hl > 0 ? r.nuoc_bai_khi_hl : "—"}</td>
        <td>${esc(r.beer_type)}</td><td class="muted">${r.finished_product_code ? `${esc(r.finished_product_code)} — ${esc(r.finished_product_name || "")}` : "—"}</td><td>${r.v_beer_hl > 0 ? r.v_beer_hl : "—"}</td><td>${esc(r.to_bbt || "")}</td>
        <td>${badge({ dang_loc: "in_progress", cho_chiet: "planned", chiet_1_phan: "due", da_chiet_het: "done" }[r.status] || "planned")}${esc(r.status_label)}</td>
        <td>${r.on_hand_bbt}</td>
        <td>${fmt(r.ended_at)}</td>
        <td>${badge(r.exec_status === "hoan_thanh" ? "completed" : "in_progress")}${esc(r.exec_status_label)}
          <button class="btn sm" data-filtertanks="${esc(r.filter_id)}" data-filterbbt="${r.on_hand_bbt || 0}" style="margin-left:6px">Tank (${tankCount})</button></td>
        <td><button class="btn sm sec" data-nvlloc="${esc(r.filter_id)}|${esc(r.filter_order_id || "")}|${esc(r.filter_code)}">NVL lọc</button></td>
        <td>${r.locked ? '<span class="muted">—</span>' : `<button class="btn sm sec" data-delrec="filter|${esc(r.filter_id)}">Xóa</button>`}</td>
        <td style="white-space:nowrap">${r.locked
            ? (isAdminLot ? `<button class="btn sm sec" data-unlocklot="filter|${esc(r.filter_id)}">Mở khóa</button>` : '<span class="muted">—</span>')
            : (canLockLot ? `<button class="btn sm" data-locklot="filter|${esc(r.filter_id)}">Khóa lô</button>` : '<span class="muted">—</span>')}</td></tr>`; }).join("")}</tbody></table></div>
      <div class="legend">Chú thích: <b class="red">Đỏ</b>: Thiếu chỉ tiêu bắt buộc, hoặc đã đủ nhưng có chỉ tiêu FAIL — <b class="green">Xanh lá</b>: Đủ chỉ tiêu (không FAIL) nhưng chưa nhập NVL — <b class="blue">Xanh dương</b>: Đầy đủ, không FAIL — <b class="cyan">Xanh nhạt</b>: Lọc vào BBT phối</div></div>`;
  }

  else if (sec === "chiet") {
    const [rows, finishedProducts, lines, bbtTanksChiet] = await Promise.all([
      GET("/brewing/bottles"), GET("/finished-products").catch(() => []), GET("/lines").catch(() => []),
      GET("/brewing/bbt-tanks").catch(() => [])]);
    const canLockLot = _hasPerm("quality.release");
    const isAdminLot = CURRENT_USER && CURRENT_USER.role === "admin";
    // Tank BBT chỉ hiện khi ĐÃ LỌC XONG (mọi mẻ lọc cùng tank có ended_at) + KCS duyệt hết
    // + KHÔNG đang bị chọn làm nguồn "lọc lại" (xem services/filter_order.py::available_bbt_tanks,
    // enforce lại server-side ở add_bottle — đây chỉ để ẩn lựa chọn không hợp lệ trên UI).
    const bbtTanksApproved = bbtTanksChiet.filter(t => t.eligible_for_chiet);
    const bbtOpts = bbtTanksApproved.map(t =>
      `<option value="${esc(t.to_bbt)}" data-beer="${esc(t.beer_type || "")}" data-fp="${esc(t.finished_product_code || "")}">${esc(t.to_bbt)} — ${esc(t.beer_type || "")}${t.finished_product_code ? ` · SP: ${esc(t.finished_product_code)} — ${esc(t.finished_product_name || "")}` : " · (mọi sản phẩm)"}</option>`).join("");
    const fpOpts = `<option value="">(chọn sản phẩm)</option>` + finishedProducts.map(fp =>
      `<option value="${esc(fp.finished_product_id)}">${esc(fp.code)} — ${esc(fp.name)}</option>`).join("");
    const packagingLines = lines.filter(l => l.kind === "line" && l.active);
    const lineItems = packagingLines.map(l => ({ value: l.code, label: `${l.code} — ${l.name}` }));
    body = `<div class="panel"><h2>Thêm thông tin chiết</h2>
      <div class="muted" style="margin-bottom:6px">V cấp chiết/hl và Ca 1/2/3 chưa cần điền ngay — sẽ nhập khi bấm "Kết thúc".
        Chỉ hiện Tank BBT có mẻ lọc đã được KCS duyệt (xem tab "Lọc").</div>
      <div class="row">
        <div class="field"><label>Chiết từ tank BBT</label><select id="bo_bbt"><option value=""></option>${bbtOpts}</select></div>
        <div class="field"><label>Sản phẩm</label><select id="bo_fp">${fpOpts}</select></div>
        <div class="field"><label>Dây chuyền</label><div id="bo_line_wrap" data-items="${esc(JSON.stringify(lineItems))}"></div></div>
        <div class="field"><label>Loại bia</label><div id="bo_beer_display" class="muted" style="padding:6px 0">— (chọn Tank BBT trước)</div></div>
        <div class="field"><label>Ngày giờ chiết</label><input id="bo_date" type="datetime-local" value="${toDTLocal(new Date())}"/></div>
        <button class="btn" id="bo_add">Thêm</button>
      </div></div>
      <div class="panel"><h2>Thông tin chiết <span class="muted">(${rows.length})</span></h2>
      <input class="searchbox" data-tbl="t_chiet" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_chiet"><thead><tr><th>Duyệt</th><th>Chỉ tiêu</th><th>Mã chiết</th><th>Mã lọc</th><th>Ngày chiết</th><th>Loại bia</th><th>Sản phẩm</th>
        <th>Số lô bia</th><th>V cấp chiết/hl</th><th>Chiết từ Tank BBT</th><th>SL ca 1</th><th>SL ca 2</th><th>SL ca 3</th>
        <th>Tổng Cộng</th><th>Đã nhập kho</th><th>Chiết duyệt</th><th>Ngày giờ kết thúc</th><th>TH thực tế</th><th></th><th></th><th>Khóa lô</th></tr></thead>
      <tbody>${rows.map(b => `<tr class="row-${b.color}"><td style="white-space:nowrap">${b.locked ? lockBadgeHtml(b) : (b.approved ? `<span style="color:var(--green)">✓ ${esc(b.approved_by || "")}</span><div class="muted">${fmt(b.approved_at)}</div>` : `<a href="#" data-approve="${b.bottle_id}" style="color:var(--accent)">Duyệt</a>`)}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-stageqc="thanh_pham|bottle|${esc(b.bottle_code)}__thanh_pham|${esc(b.product_id || "")}|${esc(b.finished_product_id || "")}|${""}|${esc(b.beer_type_id || "")}">Thành phẩm</button></td>
        <td class="code">${holdBadgeHtml(b)}${esc(b.bottle_code)}</td><td>${esc(b.filter_code || "")}</td><td>${fmt(b.bottle_date)}</td><td>${esc(b.beer_type)}</td>
        <td class="muted">${b.finished_product_code ? `${esc(b.finished_product_code)} — ${esc(b.finished_product_name || "")}` : "—"}</td>
        <td>${esc(b.lot_no || "")}</td><td>${b.v_cap_chiet_hl}</td><td>${esc(b.from_bbt || "")}</td>
        <td>${b.ca1 ? b.ca1.toLocaleString("vi-VN") : ""}</td><td>${b.ca2 ? b.ca2.toLocaleString("vi-VN") : ""}</td>
        <td>${b.ca3 ? b.ca3.toLocaleString("vi-VN") : ""}</td><td>${b.total.toLocaleString("vi-VN")}</td>
        <td style="text-align:center">${chk(b.stocked)}</td><td style="text-align:center">${chk(b.approved)}</td>
        <td class="muted">${b.ended_at ? fmt(b.ended_at) : "—"}</td>
        <td>${badge(b.exec_status === "hoan_thanh" ? "completed" : "in_progress")}${esc(b.exec_status_label)}
          ${b.locked ? "" : `<button class="btn sm ${b.exec_status === "hoan_thanh" ? "sec" : ""}" data-finishrec="bottle|${esc(b.bottle_id)}" data-endedat="${esc(b.ended_at || "")}"
            data-vcap="${b.v_cap_chiet_hl || 0}" data-ca1="${b.ca1 || 0}" data-ca2="${b.ca2 || 0}" data-ca3="${b.ca3 || 0}"
            style="margin-left:6px">${b.exec_status === "hoan_thanh" ? "Sửa" : "Kết thúc"}</button>`}
          ${!b.locked && b.filter_id && (b.source_filter_on_hand_bbt || 0) > 0 ? `<button class="btn sm sec" data-emptybbtchiet="${esc(b.filter_id)}"
            title="Buộc tồn BBT (${b.source_filter_on_hand_bbt} hl) của tank nguồn về 0 khi tank vật lý đã chiết cạn thật nhưng số liệu còn lệch"
            style="margin-left:6px">Làm rỗng tank</button>` : ""}</td>
        <td><button class="btn sm sec" data-nvlchiet="${esc(b.bottle_id)}|${esc(b.bottle_code)}">NVL chiết</button></td>
        <td>${b.locked ? '<span class="muted">—</span>' : `<button class="btn sm sec" data-delrec="bottle|${esc(b.bottle_id)}">Xóa</button>`}</td>
        <td style="white-space:nowrap">${b.locked
            ? (isAdminLot ? `<button class="btn sm sec" data-unlocklot="bottle|${esc(b.bottle_id)}">Mở khóa</button>` : '<span class="muted">—</span>')
            : (canLockLot ? `<button class="btn sm" data-locklot="bottle|${esc(b.bottle_id)}">Khóa lô</button>` : '<span class="muted">—</span>')}</td></tr>`).join("")}</tbody></table></div>
      <div class="legend">Chú thích: <b class="red">Đỏ</b>: Thiếu chỉ tiêu bắt buộc, hoặc đã đủ nhưng có chỉ tiêu FAIL — <b class="blue">Xanh dương</b>: Đầy đủ, không FAIL</div></div>`;
  }

  else if (sec === "canhbao") {
    const now = new Date();
    body = `<div class="panel"><h2>Cảnh báo chỉ tiêu chất lượng</h2>
      <div class="row"><div class="field"><label>Tháng</label><input id="al_m" type="number" min="1" max="12" value="${now.getMonth() + 1}" size="3"/></div>
        <div class="field"><label>Năm</label><input id="al_y" type="number" value="${now.getFullYear()}" size="5"/></div>
        <button class="btn" id="al_load">Xem cảnh báo</button></div>
      <div class="muted" style="margin:6px 0">Cảnh báo (nếu không cập nhật đủ những thông tin bên dưới báo cáo sẽ không đúng)</div>
      <div id="al_out"></div></div>`;
  }

  else if (sec === "hoachat") {
    const chems = await GET("/process/chemicals");
    const batches = await GET("/batches");
    const bopts = batches.map(b => `<option value="${b.batch_id}">${esc(b.batch_code)}</option>`).join("");
    const stageLabel = { nau: "Nấu", len_men: "Lên men", loc: "Lọc", chiet: "Chiết", cip: "CIP" };
    body = `<div class="panel"><h2>Ghi sử dụng hóa chất</h2>
      <div class="row"><div class="field"><label>Mẻ</label><select id="ch_batch">${bopts}</select></div>
        <div class="field"><label>Công đoạn</label><select id="ch_stage"><option value="nau">Nấu</option><option value="len_men">Lên men</option><option value="loc">Lọc</option><option value="chiet">Chiết</option><option value="cip">CIP</option></select></div>
        <div class="field"><label>Hóa chất</label><input id="ch_name"/></div>
        <div class="field"><label>SL</label><input id="ch_qty" type="number"/></div>
        <div class="field"><label>ĐVT</label><input id="ch_uom" value="kg" size="4"/></div>
        <button class="btn" id="ch_add">Ghi</button></div></div>
      <div class="panel"><h2>Lịch sử sử dụng hóa chất</h2>
      <table><thead><tr><th>Thời gian</th><th>Công đoạn</th><th>Hóa chất</th><th>SL</th><th>Ghi chú</th></tr></thead>
      <tbody>${chems.map(c => `<tr><td class="muted">${fmt(c.ts)}</td><td>${esc(stageLabel[c.stage] || c.stage)}</td>
        <td>${esc(c.chemical)}</td><td>${c.quantity} ${esc(c.uom)}</td><td class="muted">${esc(c.note || "")}</td></tr>`).join("")}</tbody></table></div>`;
  }

  else if (sec === "men") {
    const [yeast, issues, batches] = await Promise.all([GET("/process/yeast"), GET("/process/yeast/issues"), GET("/batches")]);
    const bopts = `<option value="">(không gắn mẻ)</option>` + batches.map(b => `<option value="${b.batch_id}">${esc(b.batch_code)}</option>`).join("");
    const yopts = yeast.filter(y => y.status === "available").map(y => `<option value="${y.yeast_lot_id}">${esc(y.code)} (${y.quantity}${y.uom})</option>`).join("");
    body = `<div class="split">
      <div class="panel"><h2>Lô men thu hồi</h2>
        <table><thead><tr><th>Mã</th><th>Chủng</th><th>Đời</th><th>SL</th><th>Sống %</th><th>Trạng thái</th></tr></thead>
        <tbody>${yeast.map(y => `<tr><td><code class="k">${esc(y.code)}</code></td><td>${esc(y.strain)}</td><td>${y.generation}</td>
          <td>${y.quantity} ${y.uom}</td><td>${y.viability ?? "—"}</td><td>${badge(y.status === "available" ? "available" : "obsolete")}${y.status}</td></tr>`).join("")}</tbody></table></div>
      <div class="panel"><h2>Xuất men thu hồi</h2>
        <div class="row"><div class="field"><label>Lô men</label><select id="ye_lot">${yopts}</select></div>
          <div class="field"><label>Cấy cho mẻ</label><select id="ye_batch">${bopts}</select></div>
          <div class="field"><label>SL</label><input id="ye_qty" type="number" value="20"/></div>
          <button class="btn" id="ye_issue">Xuất men</button></div>
        <h3>Lịch sử xuất men</h3>
        <table><thead><tr><th>Thời gian</th><th>Lô men</th><th>Mẻ</th><th>SL</th></tr></thead>
        <tbody>${issues.map(i => `<tr><td class="muted">${fmt(i.ts)}</td><td>${esc(i.yeast_code)}</td><td>${esc(i.batch || "—")}</td><td>${i.quantity} ${i.uom}</td></tr>`).join("") || '<tr><td colspan=4 class="muted">Chưa có.</td></tr>'}</tbody></table></div></div>`;
  }

  $("view-process").innerHTML = subnav("process", sections, sec) + body;
  wireSubnav("process"); wireSearch();

  if (sec === "nguyenlieu") {
    $("nl_loc").onchange = () => { SUB.process_nl_loc = $("nl_loc").value; render("process"); };
    document.querySelectorAll("[data-viewlots]").forEach(b => b.onclick = () =>
      openMaterialLotsModal(b.dataset.matlabel, lotsByMaterial[b.dataset.viewlots] || []));
  }
  if (sec === "nau") {
    const updateNbWortFromOrder = () => {
      const opt = $("nb_order").selectedOptions[0];
      // Dịch bia trích từ Lệnh nấu nhỏ đã chọn — lệnh nhỏ đã chốt sẵn 1 dịch bia lúc lập,
      // không cho chọn khác đi để tránh lệch giữa mã nấu và lệnh nấu của nó (gợi ý NVL/BOM sẽ sai).
      if (opt && opt.value && opt.dataset.wort) {
        $("nb_wort").value = opt.dataset.wort;
        $("nb_wort").disabled = true;
      } else {
        $("nb_wort").disabled = false;
      }
      if (!opt || !opt.value) { $("nb_vol").disabled = false; return; }
      // SL nấu/hl luôn LẤY THEO sản lượng kế hoạch (planned_volume_hl) của Lệnh nấu nhỏ đã
      // chọn, không cho sửa tay — không chia theo số mẻ, vì planned_batch_count là số MẺ
      // (Braumat) bên trong 1 mã nấu, không phải số mã nấu chia sẻ sản lượng của lệnh nhỏ (1
      // lệnh nhỏ có thể có NHIỀU mã nấu, mỗi mã nấu cộng dồn tới khi đạt kế hoạch — xem
      // services/brew_order.py::_is_complete).
      const vol = parseFloat(opt.dataset.vol) || 0;   // đã là hl (tổng kế hoạch)
      $("nb_vol").value = vol;
      $("nb_vol").disabled = true;
    };
    $("nb_master").onchange = () => {
      const master = mastersLn.find(m => m.id === $("nb_master").value);
      $("nb_order").innerHTML = master
        ? `<option value="">(chọn Lệnh nấu nhỏ — bắt buộc)</option>` + master.children.map(c =>
            `<option value="${esc(c.brew_order_id)}" data-wort="${esc(c.product_id || "")}" data-vol="${c.planned_volume_hl}">${esc(c.product_code || c.product_desc || "—")} — ${c.actual_volume_hl}/${c.planned_volume_hl} hl</option>`).join("")
        : `<option value="">(chọn Lệnh nấu trước)</option>`;
      updateNbWortFromOrder();
    };
    $("nb_order").onchange = updateNbWortFromOrder;
    $("nb_add").onclick = () => guard(async () => {
      const orderId = $("nb_order").value;
      if (!orderId) throw new Error("Chọn Lệnh nấu nhỏ trước khi thêm mã nấu.");
      const code = $("nb_code").value.trim();
      if (!code) throw new Error("Nhập mã nấu.");
      const tank = $("nb_tank").value || null;
      const lmCode = tank ? code : null;   // 1 mã nấu = 1 lô LM — dùng luôn mã nấu làm mã lô LM
      const productId = $("nb_wort").value || null;
      if (!productId) throw new Error("Chọn Dịch bia trước khi thêm mã nấu.");
      const wortName = $("nb_wort").selectedOptions[0].textContent;
      await POST("/brewing/brews", { brew_code: code, wort_type: wortName, product_id: productId,
        brew_date: $("nb_date").value || null,
        volume_hl: parseFloat($("nb_vol").value),
        note: $("nb_note").value.trim() || null,
        lm_code: lmCode, tank_lm: tank,
        yeast_gen: $("nb_yeast").value || null,
        brew_order_id: orderId });
      toast("Đã thêm mã nấu" + (tank ? ` — đã chuyển sang lên men tại tank ${tank}` : "")); render("process");
    });
  }
  if (sec === "loc") {
    const updateFlBeerDisplay = () => {
      const opt = $("fl_order").selectedOptions[0];
      const beer = opt && opt.dataset.beer;
      $("fl_beer_display").textContent = opt && opt.value ? (beer || "(chưa xác định — kiểm tra Loại bia của lệnh lọc)") : "— (chọn Lệnh lọc nhỏ trước)";
    };
    $("fl_master").onchange = () => {
      const master = mastersLf.find(m => m.id === $("fl_master").value);
      $("fl_order").innerHTML = master
        ? `<option value="">(chọn Lệnh lọc nhỏ — bắt buộc)</option>` + master.children.map(o =>
            `<option value="${esc(o.filter_order_id)}" data-beer="${esc(o.beer_type_name || "")}" data-tobbt="${esc(o.records.length ? o.records[0].to_bbt || "" : "")}">Lệnh nhỏ #${o.seq} — ${o.blend_mode === "phoi" ? "Phối" : "Không phối"} (${o.tanks.map(t => esc(t.tank_lm)).join(", ")}) — ${o.actual_volume_hl}/${o.planned_volume_hl} hl${o.finished_product_code ? ` — SP: ${esc(o.finished_product_code)} — ${esc(o.finished_product_name || "")}` : ""}${o.records.length ? ` — đã có ${o.records.length} mẻ` : ""}</option>`).join("")
        : `<option value="">(chọn Lệnh lọc trước)</option>`;
      updateFlBeerDisplay(); updateFlBbtLock();
    };
    // Lệnh nhỏ ĐÃ có mẻ lọc trước (o.records không rỗng) — tank BBT đã khoá theo mẻ đầu tiên,
    // không cho chọn tank khác cho mẻ tiếp theo (xem routers/brewing.py::add_filter, chặn
    // 2 lệnh nhỏ khác nhau vô tình cùng vào 1 tank vật lý). Lệnh CHƯA có mẻ lọc nào thì vẫn
    // chọn tank tự do như cũ — server sẽ tự kiểm tra tank chưa bị lệnh khác giữ khi submit.
    const updateFlBbtLock = () => {
      const opt = $("fl_order").selectedOptions[0];
      const locked = opt && opt.dataset.tobbt;
      $("fl_bbt").style.display = locked ? "none" : "";
      $("fl_bbt_locked").style.display = locked ? "" : "none";
      if (locked) $("fl_bbt_locked").textContent = `${locked} (đã khoá — lệnh này đã có mẻ lọc trước, không đổi được tank)`;
    };
    $("fl_order").onchange = () => { updateFlBeerDisplay(); updateFlBbtLock(); };
    $("fl_add").onclick = () => guard(async () => {
      const orderId = $("fl_order").value;
      if (!orderId) throw new Error("Chọn Lệnh lọc nhỏ trước khi thêm bản ghi lọc.");
      // Không gửi wort_type — backend tự suy ra đúng dịch nha từ tank nguồn của lệnh lọc
      // (xem routers/brewing.py::add_filter, "if not data.get(wort_type)"). Trước đây gửi
      // cứng "Dịch bia 14oP" ở đây khiến điều kiện đó luôn False nên giá trị đúng bị đè mất.
      await POST("/brewing/filters", { filter_code: "FL-" + Date.now().toString().slice(-5), filter_order_id: orderId,
        to_bbt: $("fl_bbt").value });
      toast("Đã thêm bản ghi lọc (mã lô lọc tự sinh) — điền Dịch nha lọc/Nước bài khí khi bấm \"Kết thúc\" từng tank"); render("process");
    });
  }
  if (sec === "chiet") {
    const updateBoBeerDisplay = () => {
      const opt = $("bo_bbt").selectedOptions[0];
      const beer = opt && opt.dataset.beer;
      $("bo_beer_display").textContent = opt && opt.value ? (beer || "(chưa xác định — kiểm tra Loại bia của mẻ lọc)") : "— (chọn Tank BBT trước)";
    };
    $("bo_bbt").onchange = updateBoBeerDisplay;
    updateBoBeerDisplay();
    const boLineItems = JSON.parse($("bo_line_wrap").dataset.items || "[]");
    const boLinePicker = initCheckboxMultiSelect($("bo_line_wrap"), boLineItems, []);
    $("bo_add").onclick = () => guard(async () => {
      const finishedProductId = $("bo_fp").value;
      if (!finishedProductId) throw new Error("Chọn Sản phẩm trước khi thêm bản ghi chiết.");
      const selectedLines = boLinePicker.getSelected();
      if (!selectedLines.length) throw new Error("Chọn ít nhất 1 Dây chuyền.");
      const dateRaw = $("bo_date").value;
      await POST("/brewing/bottles", { bottle_code: "CH-" + Date.now().toString().slice(-5), from_bbt: $("bo_bbt").value,
        finished_product_id: finishedProductId,
        bottle_date: dateRaw ? new Date(dateRaw).toISOString() : null,
        line: selectedLines.join(", ") });
      toast("Đã thêm bản ghi chiết (số lô tự sinh) — điền V cấp chiết/Ca 1/2/3 khi bấm \"Kết thúc\""); render("process");
    });
    document.querySelectorAll("[data-approve]").forEach(a => a.onclick = (e) => { e.preventDefault(); guard(async () => {
      const res = await POST(`/brewing/bottles/${a.dataset.approve}/approve`);
      const unitLabel = res.unit_type === "keg" ? "keg" : "vỉ";
      if (res.qc_has_fail)
        toast(`⚠ Đã duyệt chiết (đã nhập kho ${res.count} ${unitLabel}), nhưng còn chỉ tiêu thành phẩm KHÔNG ĐẠT — vui lòng theo dõi.`, "warn");
      else
        toast(`Đã duyệt chiết — đã nhập kho thành phẩm (${res.count} ${unitLabel})`);
      render("process");
    }); });
  }
  if (sec === "canhbao") {
    const load = () => guard(async () => {
      const a = await GET(`/brewing/alerts?month=${$("al_m").value}&year=${$("al_y").value}`);
      $("al_out").innerHTML = `<table><thead><tr><th>Cảnh báo (${a.count})</th></tr></thead>
        <tbody>${a.alerts.map(x => `<tr><td>${esc(x)}</td></tr>`).join("") || '<tr><td class="muted">Không có cảnh báo.</td></tr>'}</tbody></table>`;
    });
    $("al_load").onclick = load; load();
  }
  if (sec === "hoachat") $("ch_add").onclick = () => guard(async () => {
    await POST("/process/chemicals", { batch_id: $("ch_batch").value, stage: $("ch_stage").value,
      chemical: $("ch_name").value, quantity: parseFloat($("ch_qty").value), uom: $("ch_uom").value });
    toast("Đã ghi hóa chất"); render("process");
  });
  if (sec === "men") $("ye_issue").onclick = () => guard(async () => {
    await POST(`/process/yeast/${$("ye_lot").value}/issue`, { batch_id: $("ye_batch").value || null, quantity: parseFloat($("ye_qty").value) });
    toast("Đã xuất men"); render("process");
  });
  document.querySelectorAll("[data-stageqc]").forEach(b => b.onclick = () => {
    const [stage, scopeType, scopeId, productId, finishedProductId, displayOverride, beerTypeId] = b.dataset.stageqc.split("|");
    openStageQcModal(stage, scopeType, scopeId, { productId: productId || null, finishedProductId: finishedProductId || null,
      beerTypeId: beerTypeId || null, displayId: displayOverride || scopeId.split("__")[0] });
  });
  document.querySelectorAll("[data-lmapprove]").forEach(b => b.onclick = () => guard(async () => {
    const res = await POST(`/brewing/ferments/${b.dataset.lmapprove}/approve`);
    if (res.qc_has_fail) toast("⚠ Đã duyệt lên men, nhưng còn chỉ tiêu lên men phụ KHÔNG ĐẠT — vui lòng theo dõi.", "warn");
    else toast("Đã duyệt lên men — cho phép lọc từ tank này");
    render("process");
  }));
  document.querySelectorAll("[data-fermentlog]").forEach(b => b.onclick = () => {
    const [fermentId, lmCode] = b.dataset.fermentlog.split("|");
    openFermentProcessLogModal(fermentId, lmCode);
  });
  document.querySelectorAll("[data-filterapprove]").forEach(b => b.onclick = () => guard(async () => {
    const res = await POST(`/brewing/filters/${b.dataset.filterapprove}/approve`);
    if (res.qc_has_fail) toast("⚠ Đã duyệt mẻ lọc, nhưng còn chỉ tiêu lọc KHÔNG ĐẠT — vui lòng theo dõi.", "warn");
    else toast("Đã duyệt KCS mẻ lọc");
    render("process");
  }));
  document.querySelectorAll("[data-brewbatches]").forEach(b => b.onclick = () => {
    const [brewId, brewCode, productId, locked] = b.dataset.brewbatches.split("|");
    openBrewBatchesModal(brewId, brewCode, productId || null, locked === "1");
  });
  const DELREC_PATH = { material: "materials", brew: "brews", ferment: "ferments", filter: "filters", bottle: "bottles" };
  document.querySelectorAll("[data-delrec]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Xóa bản ghi này? Không thể hoàn tác.")) return;
    const [type, id] = b.dataset.delrec.split("|");
    await DELETE(`/brewing/${DELREC_PATH[type]}/${id}`);
    toast("Đã xóa"); render("process");
  }));
  document.querySelectorAll("[data-finishrec]").forEach(b => b.onclick = () => {
    const [type, id] = b.dataset.finishrec.split("|");
    openFinishBottleModal("Kết thúc chiết", b.dataset.endedat || null,
      parseFloat(b.dataset.vcap) || 0, parseFloat(b.dataset.ca1) || 0, parseFloat(b.dataset.ca2) || 0, parseFloat(b.dataset.ca3) || 0,
      async (payload) => {
        await POST(`/brewing/bottles/${id}/finish`, payload);
        closeModal(); toast("Đã lưu kết quả chiết"); render("process");
      });
  });
  document.querySelectorAll("[data-filtertanks]").forEach(b => b.onclick = () => openFilterTanksModal(b.dataset.filtertanks, parseFloat(b.dataset.filterbbt) || 0));
  document.querySelectorAll("[data-emptybbtchiet]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Buộc tồn tank thành phẩm (BBT) nguồn của mẻ chiết này về 0? Chỉ dùng khi tank vật lý đã chiết cạn thật. Không thể hoàn tác.")) return;
    const res = await POST(`/brewing/filters/${b.dataset.emptybbtchiet}/empty-bbt`, {});
    toast(`Đã làm rỗng — tồn BBT: ${res.on_hand_bbt} hl`); render("process");
  }));
  document.querySelectorAll("[data-nvlloc]").forEach(b => b.onclick = () => {
    const [fId, fOrderId, fCode] = b.dataset.nvlloc.split("|");
    openFilterMaterialsModal(fId, fOrderId || null, fCode);
  });
  document.querySelectorAll("[data-nvlchiet]").forEach(b => b.onclick = () => {
    const [bId, bCode] = b.dataset.nvlchiet.split("|");
    openBottleMaterialsModal(bId, bCode);
  });
  // Khóa lô theo từng công đoạn — Nấu/Lên men/Lọc/Chiết mỗi bảng có nút riêng (xem
  // services/lot_lock.py) — KCS khóa xuôi (chặn nếu công đoạn nguồn chưa khóa), chỉ admin
  // mở khóa được và phải mở ngược (chặn nếu công đoạn hạ lưu còn khóa) — lỗi trả về từ
  // server hiển thị qua guard()/toast như các lỗi domain khác, không cần xử lý riêng.
  const LOCKLOT_PATH = { brew: "brews", ferment: "ferments", filter: "filters", bottle: "bottles" };
  const LOCKLOT_LABEL = { brew: "mã nấu", ferment: "lô LM", filter: "mẻ lọc", bottle: "mẻ chiết" };
  document.querySelectorAll("[data-locklot]").forEach(b => b.onclick = () => guard(async () => {
    const [kind, id] = b.dataset.locklot.split("|");
    if (!confirm(`Khóa ${LOCKLOT_LABEL[kind]} này? Cần đã hoàn thành + đủ chỉ tiêu + công đoạn nguồn đã khóa.`)) return;
    await POST(`/brewing/${LOCKLOT_PATH[kind]}/${id}/lock-lot`);
    toast(`Đã khóa ${LOCKLOT_LABEL[kind]}`); render("process");
  }));
  document.querySelectorAll("[data-unlocklot]").forEach(b => b.onclick = () => guard(async () => {
    const [kind, id] = b.dataset.unlocklot.split("|");
    if (!confirm(`Mở khóa ${LOCKLOT_LABEL[kind]} này?`)) return;
    await POST(`/brewing/${LOCKLOT_PATH[kind]}/${id}/unlock-lot`);
    toast(`Đã mở khóa ${LOCKLOT_LABEL[kind]}`); render("process");
  }));
};

// ================= REALTIME (trạm quan trắc nước thải + máy chiết lon 30K) =================
VIEWS.realtime = async function () {
  $("view-realtime").innerHTML = `
    <div class="panel"><h2>🌊 Trạm quan trắc nước thải Hạ Long <span id="rtww_clock" class="muted"></span></h2>
      <div class="muted">Dữ liệu thật từ SCADA quan trắc nước thải — bảng <code class="k">QT_Realtime</code>, qua kết nối <code class="k">CSDL_NL_HL</code> (WAN). Tự cập nhật mỗi 15 giây.</div>
      <div id="rtww_body" class="muted" style="margin-top:12px">Đang tải…</div>
    </div>
    <div class="panel"><h2>🥫 Máy chiết lon 30K — Realtime <span id="rt30k_clock" class="muted"></span></h2>
      <div class="muted">Dữ liệu thật từ SCADA máy chiết lon "30K" (nhà máy Đông Mai) — bảng <code class="k">30K_Realtime</code>, qua kết nối <code class="k">CSDL_NL_ĐM</code> (WAN). Tự cập nhật mỗi 15 giây.</div>
      <div id="rt30k_body" class="muted" style="margin-top:12px">Đang tải…</div>
    </div>`;
  let rtwwBusy = false;
  const refreshWw = async () => {
    if (rtwwBusy) return;
    rtwwBusy = true;
    try {
      let s;
      try { s = await GET("/reports/wastewater-realtime"); }
      catch (e) {
        $("rtww_clock").textContent = "· cập nhật " + new Date().toLocaleTimeString("vi-VN");
        $("rtww_body").innerHTML = `<div class="muted" style="color:var(--red)">Không lấy được dữ liệu từ SCADA: ${esc(e.message)}</div>`;
        return;
      }
      $("rtww_clock").textContent = "· cập nhật " + new Date().toLocaleTimeString("vi-VN");
      if (!s.available) {
        $("rtww_body").innerHTML = `<div class="muted" style="color:var(--red)">Không có bản ghi nào trong bảng QT_Realtime.</div>`;
        return;
      }
      // Tiêu chuẩn xả thải theo QCVN 40:2011/BTNMT (cột B) — dùng để tô cảnh báo khi vượt ngưỡng,
      // không áp dụng cho FlowIn/FlowOut (chỉ là lưu lượng, không có ngưỡng xả thải).
      const wwCard = (value, decimals, unit, label, std, ok) => `
        <div class="card">
          <div class="n" style="font-size:22px${value != null && !ok ? ";color:var(--red)" : ""}">${value != null ? value.toFixed(decimals) : "—"}${unit ? `<span style="font-size:12px;color:var(--muted)"> ${unit}</span>` : ""}</div>
          <div class="l">${label}${value != null ? " " + badge(ok ? "available" : "critical") + (ok ? "Đạt" : "Vượt chuẩn") : ""}</div>
          <div class="muted" style="font-size:11px;margin-top:2px">Tiêu chuẩn: ${std}</div>
        </div>`;
      const phOk = s.ph == null || (s.ph >= 5.5 && s.ph <= 9);
      const tempOk = s.temp == null || s.temp <= 40;
      const tssOk = s.tss == null || s.tss <= 100;
      const codOk = s.cod == null || s.cod <= 150;
      const nh4Ok = s.nh4 == null || s.nh4 <= 10;
      $("rtww_body").innerHTML = `
        <div class="cards">
          ${wwCard(s.ph, 2, "", "pH", "5.5 – 9", phOk)}
          ${wwCard(s.temp, 1, "°C", "Nhiệt độ (Temp)", "≤ 40 °C", tempOk)}
          ${wwCard(s.tss, 1, "mg/L", "TSS", "≤ 100 mg/L", tssOk)}
          ${wwCard(s.cod, 1, "mg/L", "COD", "≤ 150 mg/L", codOk)}
          ${wwCard(s.nh4, 3, "mg/L", "NH4", "≤ 10 mg/L", nh4Ok)}
          <div class="card"><div class="n" style="font-size:22px">${s.flow_in != null ? s.flow_in.toFixed(2) : "—"}<span style="font-size:12px;color:var(--muted)"> m³/h</span></div><div class="l">Lưu lượng vào (FlowIn)</div></div>
          <div class="card"><div class="n" style="font-size:22px">${s.flow_out != null ? s.flow_out.toFixed(2) : "—"}<span style="font-size:12px;color:var(--muted)"> m³/h</span></div><div class="l">Lưu lượng ra (FlowOut)</div></div>
        </div>
        <div class="muted" style="margin-top:8px">Bản ghi SCADA lúc: ${s.last_update ? fmt(s.last_update) : "—"} · Kết nối: <code class="k">${esc(s.connection_name)}</code></div>`;
    } finally { rtwwBusy = false; }
  };
  let rt30kBusy = false;
  const refresh30k = async () => {
    if (rt30kBusy) return;   // kết nối WAN có thể chậm — không gọi chồng lượt trước chưa xong
    rt30kBusy = true;
    try {
      let s;
      try { s = await GET("/reports/filling-realtime"); }
      catch (e) {
        $("rt30k_clock").textContent = "· cập nhật " + new Date().toLocaleTimeString("vi-VN");
        $("rt30k_body").innerHTML = `<div class="muted" style="color:var(--red)">Không lấy được dữ liệu từ SCADA: ${esc(e.message)}</div>`;
        return;
      }
      $("rt30k_clock").textContent = "· cập nhật " + new Date().toLocaleTimeString("vi-VN");
      if (!s.available) {
        $("rt30k_body").innerHTML = `<div class="muted" style="color:var(--red)">Không có bản ghi nào trong bảng 30K_Realtime.</div>`;
        return;
      }
      $("rt30k_body").innerHTML = `
        <div class="cards">
          <div class="card"><div class="n" style="font-size:20px">${badge(s.machine_running ? "available" : "overdue")}${s.machine_running ? "Đang chạy" : "Đang dừng"}</div><div class="l">Trạng thái máy (MachineRunning)</div></div>
          <div class="card"><div class="n" style="font-size:22px">${s.production_flow != null ? s.production_flow.toFixed(2) : "—"}<span style="font-size:12px;color:var(--muted)"> m³/h</span></div><div class="l">Lưu lượng hiện tại (Production_Flow)</div></div>
          <div class="card"><div class="n" style="font-size:22px">${s.machine_speed != null ? s.machine_speed.toLocaleString("vi-VN") : "—"}<span style="font-size:12px;color:var(--muted)"> lon/h</span></div><div class="l">Tốc độ máy (MachineSpeed)</div></div>
          <div class="card"><div class="n" style="font-size:22px">${s.total_product != null ? Math.round(s.total_product).toLocaleString("vi-VN") : "—"}<span style="font-size:12px;color:var(--muted)"> m³</span></div><div class="l">Sản lượng lũy kế (TotalProduct)</div></div>
          <div class="card"><div class="n" style="font-size:22px">${s.total_can != null ? s.total_can.toLocaleString("vi-VN") : "—"}<span style="font-size:12px;color:var(--muted)"> lon</span></div><div class="l">Số lon lũy kế (TotalCan)</div></div>
        </div>
        <div class="muted" style="margin-top:8px">Bản ghi SCADA lúc: ${s.last_update ? fmt(s.last_update) : "—"} · Kết nối: <code class="k">${esc(s.connection_name)}</code></div>`;
    } finally { rt30kBusy = false; }
  };
  await refreshWw();
  await refresh30k();
  window.__rt30k = setInterval(() => { refreshWw(); refresh30k(); }, 15000);
};

// ================= TRỢ LÝ AI =================
let AI_HISTORY = [];
let CURRENT_CONV = null;   // hội thoại đang mở (lưu phía server)
const sevBadge = (s) => badge(s === "high" ? "critical" : s === "medium" ? "due" : "available") + s;
VIEWS.ai = async function () {
  const [status, ins, convs] = await Promise.all([
    GET("/ai/status"), GET("/ai/insights"), GET("/ai/conversations").catch(() => [])]);
  const modeTag = status.llm_available
    ? `<span class="badge available">Claude ${esc(status.model)}</span>`
    : `<span class="badge planned">Engine luật (offline)</span>`;
  const convOpts = (list, sel) => `<option value="">+ Hội thoại mới</option>` +
    list.map(c => `<option value="${esc(c.conv_id)}" ${c.conv_id === sel ? "selected" : ""}>${esc(c.title)} (${c.messages})</option>`).join("");
  $("view-ai").innerHTML = `
    <div class="split">
      <div class="panel">
        <h2>Trợ lý AI ${modeTag} <span class="badge due">chỉ tư vấn</span></h2>
        <div class="row" style="margin-bottom:8px">
          <div class="field" style="flex:1"><label>Hội thoại (lưu trên máy chủ)</label>
            <select id="ai_conv" style="width:100%">${convOpts(convs, CURRENT_CONV)}</select></div>
          <button class="btn sec sm" id="ai_new" style="align-self:flex-end">Mới</button>
          <button class="btn sec sm" id="ai_del" style="align-self:flex-end">Xoá</button>
        </div>
        <div id="chatlog" style="height:330px;overflow-y:auto;background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:10px"></div>
        <div class="row">
          <div class="field" style="flex:1"><input id="chatmsg" placeholder="Hỏi: tồn kho, OEE, cảnh báo, mẻ, kiểm định, sự cố, năng lượng, truy xuất…" style="width:100%"/></div>
          <button class="btn" id="chatsend">Gửi</button>
        </div>
        <div class="muted" style="margin-top:6px">Lịch sử lưu trên máy chủ — còn nguyên khi tải lại/đổi máy. ${status.llm_available ? "" : "Đặt ANTHROPIC_API_KEY + cài <code class='k'>anthropic</code> để bật Claude thật."}</div>
      </div>
      <div class="panel">
        <h2>AI vận hành — cảnh báo & đề xuất <span class="muted">(${ins.count})</span>
          <button class="btn sec sm" id="ai_job" style="float:right">📋 Báo cáo nền</button></h2>
        <div id="ai_jobout" class="muted" style="margin-bottom:8px"></div>
        <div class="cards" style="grid-template-columns:repeat(3,1fr)">
          <div class="card"><div class="n" style="color:var(--red)">${ins.summary.high}</div><div class="l">Cao</div></div>
          <div class="card"><div class="n" style="color:var(--orange)">${ins.summary.medium}</div><div class="l">Trung bình</div></div>
          <div class="card"><div class="n" style="color:var(--green)">${ins.summary.low}</div><div class="l">Thấp</div></div>
        </div>
        <table><thead><tr><th>Mức</th><th>Miền</th><th>Phát hiện</th><th>Đề xuất</th></tr></thead>
        <tbody>${ins.insights.map(i => `<tr><td>${sevBadge(i.severity)}</td><td>${esc(i.domain)}</td>
          <td>${esc(i.finding)}</td><td class="muted">${esc(i.recommendation)}</td></tr>`).join("") || '<tr><td colspan=4 class="muted">Không có cảnh báo.</td></tr>'}</tbody></table>
        <div class="muted" style="margin-top:8px">${esc(ins.note)}</div>
      </div>
    </div>`;
  const renderChat = () => {
    $("chatlog").innerHTML = AI_HISTORY.map(m => {
      const me = m.role === "user";
      const tools = m.tools_used ? (Array.isArray(m.tools_used) ? m.tools_used : String(m.tools_used).split(",")) : (m.tools || null);
      return `<div style="margin:6px 0;text-align:${me ? "right" : "left"}">
        <span style="display:inline-block;max-width:85%;padding:8px 12px;border-radius:10px;text-align:left;
          background:${me ? "var(--accent)" : "var(--panel)"};color:${me ? "#1a1206" : "var(--text)"};border:1px solid var(--border)">
          ${esc(m.content)}${tools && tools.length ? `<div style="font-size:11px;opacity:.7;margin-top:4px">🔧 ${tools.map(esc).join(", ")}</div>` : ""}</span></div>`;
    }).join("") || '<div class="muted">Bắt đầu hỏi trợ lý…</div>';
    $("chatlog").scrollTop = $("chatlog").scrollHeight;
  };
  const refreshConvList = async () => {
    const list = await GET("/ai/conversations").catch(() => []);
    $("ai_conv").innerHTML = convOpts(list, CURRENT_CONV);
  };
  const loadConv = async (id) => {
    if (!id) { CURRENT_CONV = null; AI_HISTORY = []; renderChat(); return; }
    const c = await GET(`/ai/conversations/${id}`);
    CURRENT_CONV = id; AI_HISTORY = c.messages; renderChat();
  };
  // nạp hội thoại đang chọn (nếu có) khi mở view
  if (CURRENT_CONV && convs.some(c => c.conv_id === CURRENT_CONV)) await loadConv(CURRENT_CONV);
  else renderChat();

  $("ai_conv").onchange = () => guard(() => loadConv($("ai_conv").value));
  $("ai_new").onclick = () => { CURRENT_CONV = null; AI_HISTORY = []; $("ai_conv").value = ""; renderChat(); };
  $("ai_del").onclick = () => guard(async () => {
    if (!CURRENT_CONV) return;
    await api(`/ai/conversations/${CURRENT_CONV}`, { method: "DELETE" });
    CURRENT_CONV = null; AI_HISTORY = []; renderChat(); await refreshConvList(); toast("Đã xoá hội thoại");
  });
  const send = () => guard(async () => {
    const msg = $("chatmsg").value.trim(); if (!msg) return;
    AI_HISTORY.push({ role: "user", content: msg }); $("chatmsg").value = "";
    const asst = { role: "assistant", content: "", tools_used: [] };
    AI_HISTORY.push(asst); renderChat();
    let res;
    try {
      res = await fetch("/api/ai/chat/stream", { method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + TOKEN },
        body: JSON.stringify({ message: msg, conversation_id: CURRENT_CONV }) });
    } catch (e) { asst.content = "[lỗi kết nối]"; renderChat(); return; }
    const ct = res.headers.get("content-type") || "";
    if (!res.ok || !ct.includes("event-stream")) {     // vd 429 rate-limit trả JSON
      let detail = "Lỗi " + res.status;
      try { detail = (await res.json()).detail || detail; } catch (e) {}
      asst.content = "[" + detail + "]"; renderChat(); toast(detail, "err"); return;
    }
    const reader = res.body.getReader(), dec = new TextDecoder(); let buf = "";
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, i).trim(); buf = buf.slice(i + 2);
        if (!raw.startsWith("data:")) continue;
        let ev; try { ev = JSON.parse(raw.slice(5).trim()); } catch (e) { continue; }
        if (ev.type === "meta") CURRENT_CONV = ev.conversation_id;
        else if (ev.type === "delta") { asst.content += ev.text; renderChat(); }
        else if (ev.type === "tool") { asst.tools_used.push(ev.name); renderChat(); }
        else if (ev.type === "done") { CURRENT_CONV = ev.conversation_id; if (ev.answer) asst.content = ev.answer; if (ev.tools_used) asst.tools_used = ev.tools_used; renderChat(); }
        else if (ev.type === "error") { asst.content += " [lỗi: " + esc(ev.detail) + "]"; renderChat(); }
      }
    }
    await refreshConvList();           // cập nhật danh sách + giữ chọn hội thoại hiện tại
  });
  $("chatsend").onclick = send;
  $("chatmsg").onkeydown = (e) => { if (e.key === "Enter") send(); };

  // Tác vụ nền (worker): tạo báo cáo AI + poll trạng thái.
  $("ai_job").onclick = () => guard(async () => {
    $("ai_jobout").textContent = "Đang chạy báo cáo nền…";
    const { job_id } = await POST("/jobs", { kind: "ai_report" });
    for (let i = 0; i < 40; i++) {
      await new Promise(r => setTimeout(r, 400));
      const j = await GET("/jobs/" + job_id);
      $("ai_jobout").textContent = `Báo cáo nền: ${j.status} (${j.progress}%)`;
      if (j.status === "done") { $("ai_jobout").textContent = "📋 " + (j.result.headline || "xong"); return; }
      if (j.status === "error") { $("ai_jobout").textContent = "Lỗi: " + j.error; return; }
    }
    $("ai_jobout").textContent = "Báo cáo nền vẫn đang chạy…";
  });
};

// ================= TÍCH HỢP (Open API) =================
VIEWS.integration = async function () {
  const isAdmin = CURRENT_USER && CURRENT_USER.role === "admin";
  const itgTab = SUB.integration || "gateway";
  let keys = [], hooks = [], sqlConns = [];
  if (isAdmin) {
    [keys, hooks, sqlConns] = await Promise.all([GET("/integration/keys"), GET("/integration/webhooks"), GET("/integration/connections")]);
  }
  const manifest = await GET("/ai/tools");
  $("view-integration").innerHTML = `
    <div class="subnav">
      <a href="#" data-itg="gateway" class="${itgTab === "gateway" ? "active" : ""}">Cổng API & Webhook</a>
      <a href="#" data-itg="import" class="${itgTab === "import" ? "active" : ""}">📥 Tích hợp dữ liệu (Import)</a>
      <a href="#" data-itg="dbconn" class="${itgTab === "dbconn" ? "active" : ""}">🗄️ Kết nối CSDL</a>
    </div>
    <div id="intg-import" style="display:${itgTab === "import" ? "" : "none"}"></div>
    <div id="intg-dbconn" style="display:${itgTab === "dbconn" ? "" : "none"}">
      <div class="panel"><h2>Kết nối CSDL SQL bên ngoài</h2>
        <div class="muted" style="margin-bottom:8px">Khai báo kết nối tới 1 CSDL SQL Server bên ngoài đã mở port — bước đầu để dùng làm nguồn tích hợp dữ liệu sau này. Mật khẩu lưu ở máy chủ, không hiển thị lại.</div>
        ${isAdmin ? `
        <div class="row" style="flex-wrap:wrap">
          <div class="field"><label>Tên kết nối</label><input id="sc_name" placeholder="VD: ERP kho"/></div>
          <div class="field"><label>Host</label><input id="sc_host" placeholder="10.0.0.5"/></div>
          <div class="field"><label>Port</label><input id="sc_port" type="number" value="1433" style="width:90px"/></div>
          <div class="field"><label>Database</label><input id="sc_db" placeholder="ERP_PROD"/></div>
          <div class="field"><label>Username</label><input id="sc_user" placeholder="sa"/></div>
          <div class="field"><label>Password</label><input id="sc_pass" type="password" placeholder="(để trống nếu không đổi)"/></div>
          <div class="field" style="flex:1;min-width:220px"><label>Tham số khác (tuỳ chọn)</label><input id="sc_extra" placeholder="Encrypt=yes&TrustServerCertificate=yes" style="width:100%"/></div>
          <button class="btn" id="sc_add" style="align-self:flex-end">+ Thêm kết nối</button>
        </div>
        <input class="searchbox" data-tbl="t_sqlconns" placeholder="Tìm theo tên, host, database, username..."/>
        <div class="tablewrap" style="margin-top:10px"><table id="t_sqlconns">
          <thead><tr><th>Tên</th><th>Host:Port</th><th>Database</th><th>Username</th><th>Mật khẩu</th><th>Tham số khác</th><th>Lần test gần nhất</th><th></th></tr></thead>
          <tbody>${sqlConns.map(c => `<tr>
            <td>${esc(c.name)}</td><td class="muted">${esc(c.host)}:${c.port}</td><td>${esc(c.database_name)}</td><td>${esc(c.username)}</td>
            <td>${c.password_set ? "••••••" : '<span class="muted">(chưa đặt)</span>'}</td>
            <td class="muted">${esc(c.extra_params || "—")}</td>
            <td data-sctestcell="${esc(c.connection_id)}">${c.last_tested_at ? `${badge(c.last_test_ok ? "available" : "critical")}${c.last_test_ok ? "OK" : "Lỗi"} · ${fmt(c.last_tested_at)}${c.last_test_ok === false ? `<div class="muted" style="font-size:11px;max-width:260px;white-space:normal">${esc(c.last_test_message || "")}</div>` : ""}` : '<span class="muted">Chưa test</span>'}</td>
            <td style="white-space:nowrap">
              <button class="btn sm sec" data-scedit="${esc(c.connection_id)}">Sửa</button>
              <button class="btn sm sec" data-sctest="${esc(c.connection_id)}">Test kết nối</button>
              <button class="btn sm sec" data-scpreview="${esc(c.connection_id)}">Xem bảng</button>
              <button class="btn sm sec" data-scdel="${esc(c.connection_id)}">Xoá</button>
            </td></tr>`).join("") || '<tr><td colspan=8 class="muted">Chưa có kết nối nào.</td></tr>'}</tbody>
        </table></div>
        <div id="sc_test_result" class="muted" style="margin-top:8px"></div>
        ` : `<div class="muted">Đăng nhập vai trò <code class="k">admin</code> để khai báo/kiểm tra kết nối.</div>`}
      </div>
    </div>
    <div id="intg-gateway" style="display:${itgTab === "gateway" ? "" : "none"}">
    <div class="panel"><h2>Cổng API mở <code class="k">/api/v1</code></h2>
      <div class="muted">Phần mềm ngoài (ERP/WMS/BI/AI agent) gọi qua header <code class="k">X-API-Key</code>. Đọc theo scope <code class="k">read</code>; ghi cần <code class="k">write</code>.</div>
      <h3>Endpoint sẵn có</h3>
      <table><thead><tr><th>Method</th><th>Đường dẫn</th><th>Mô tả</th></tr></thead><tbody>
        ${[["GET","/api/v1/ping","Kiểm tra key"],["GET","/api/v1/production/batches","Trạng thái mẻ"],
           ["GET","/api/v1/inventory","Tồn kho"],["GET","/api/v1/oee","OEE đóng gói"],
           ["GET","/api/v1/energy","Năng lượng tháng"],["GET","/api/v1/quality/alerts","Cảnh báo chất lượng"],
           ["GET","/api/v1/traceability?code=","Truy xuất lô"],["GET","/api/v1/events?since_seq=","Feed sự kiện"],
           ["POST","/api/v1/events","Nhận sự kiện từ ngoài (write)"]].map(r =>
          `<tr><td><code class="k">${r[0]}</code></td><td><code class="k">${esc(r[1])}</code></td><td class="muted">${esc(r[2])}</td></tr>`).join("")}
      </tbody></table>
      <div class="muted" style="margin-top:8px">Ví dụ: <code class="k">curl -H "X-API-Key: mes_demo_readonly_key_0001" localhost:8077/api/v1/inventory</code></div>
    </div>
    <div class="panel"><h2>AI Agent — Tool Manifest</h2>
      <div class="muted">${esc(manifest.description)} — ${manifest.tools.length} tool, advisory_only=${manifest.advisory_only}. Dùng cho AI agent / MCP tương lai khám phá năng lực MES.</div>
      <table><thead><tr><th>Tool</th><th>Mô tả</th></tr></thead><tbody>
        ${manifest.tools.map(t => `<tr><td><code class="k">${esc(t.name)}</code></td><td class="muted">${esc(t.description)}</td></tr>`).join("")}
      </tbody></table>
    </div>
    ${isAdmin ? `
    <div class="split">
      <div class="panel"><h2>API Keys</h2>
        <div class="row"><div class="field"><label>Tên hệ thống</label><input id="k_name" placeholder="ERP / WMS / BI"/></div>
          <div class="field"><label>Quyền</label><select id="k_scope"><option value="read">read</option><option value="read,write">read,write</option></select></div>
          <button class="btn" id="k_add">Tạo key</button></div>
        <input class="searchbox" data-tbl="t_apikeys" placeholder="Tìm theo tên, scope, trạng thái..."/>
        <div class="tablewrap"><table id="t_apikeys"><thead><tr><th>Tên</th><th>Token</th><th>Scope</th><th>Gọi</th><th>Trạng thái</th><th></th></tr></thead>
        <tbody>${keys.map(k => `<tr><td>${esc(k.name)}</td><td><code class="k">${esc(k.token_preview)}</code></td><td>${esc(k.scopes)}</td>
          <td>${k.call_count}</td><td>${badge(k.active ? "available" : "obsolete")}${k.active ? "active" : "revoked"}</td>
          <td>${k.active ? `<button class="btn sm sec" data-revoke="${k.key_id}">Khoá</button>` : ""}</td></tr>`).join("")}</tbody></table></div></div>
      <div class="panel"><h2>Webhooks</h2>
        <div class="row"><div class="field" style="flex:1"><label>URL nhận sự kiện</label><input id="w_url" placeholder="https://..." style="width:100%"/></div>
          <button class="btn" id="w_add">Đăng ký</button></div>
        <input class="searchbox" data-tbl="t_webhooks" placeholder="Tìm theo URL, loại sự kiện..."/>
        <div class="tablewrap"><table id="t_webhooks"><thead><tr><th>URL</th><th>Loại</th><th>Đã gửi</th><th>Trạng thái</th></tr></thead>
        <tbody>${hooks.map(w => `<tr><td class="muted">${esc(w.target_url)}</td><td>${esc(w.event_types)}</td><td>${w.delivered_count}</td>
          <td>${badge(w.active ? "available" : "obsolete")}${w.active ? "active" : "off"}</td></tr>`).join("") || '<tr><td colspan=4 class="muted">Chưa có webhook.</td></tr>'}</tbody></table></div></div>
    </div>` : `<div class="panel muted">Đăng nhập vai trò <code class="k">admin</code> (góc phải) để quản trị API key & webhook.</div>`}</div>`;
  wireSearch(); wirePaginate("t_apikeys", 10); wirePaginate("t_webhooks", 10); wirePaginate("t_sqlconns", 10);
  // sub-tab: Cổng API ↔ Import dữ liệu (Import Mapping Explorer) ↔ Kết nối CSDL
  document.querySelectorAll("[data-itg]").forEach(a => a.onclick = (e) => {
    e.preventDefault();
    const t = a.dataset.itg;
    SUB.integration = t;
    document.querySelectorAll("[data-itg]").forEach(x => x.classList.toggle("active", x.dataset.itg === t));
    $("intg-gateway").style.display = t === "gateway" ? "" : "none";
    $("intg-import").style.display = t === "import" ? "" : "none";
    $("intg-dbconn").style.display = t === "dbconn" ? "" : "none";
    if (t === "import" && window.ImportExplorer) window.ImportExplorer.open("intg-import");
  });
  if (itgTab === "import" && window.ImportExplorer) window.ImportExplorer.open("intg-import");
  if (isAdmin) {
    $("k_add").onclick = () => guard(async () => {
      const r = await POST("/integration/keys", { name: $("k_name").value, scopes: $("k_scope").value });
      toast("Đã tạo key — lưu token: " + r.token); alert("Token (lưu lại, chỉ hiện 1 lần):\n\n" + r.token); render("integration");
    });
    document.querySelectorAll("[data-revoke]").forEach(b => b.onclick = () => guard(async () => {
      await POST(`/integration/keys/${b.dataset.revoke}/revoke`); toast("Đã khoá key"); render("integration");
    }));
    $("w_add").onclick = () => guard(async () => {
      await POST("/integration/webhooks", { target_url: $("w_url").value }); toast("Đã đăng ký webhook"); render("integration");
    });
    $("sc_add").onclick = () => guard(async () => {
      const name = $("sc_name").value.trim(), host = $("sc_host").value.trim(), database_name = $("sc_db").value.trim(), username = $("sc_user").value.trim();
      if (!name || !host || !database_name || !username) throw new Error("Nhập đủ Tên/Host/Database/Username.");
      await POST("/integration/connections", { name, host, port: parseInt($("sc_port").value, 10) || 1433,
        database_name, username, password: $("sc_pass").value || null, extra_params: $("sc_extra").value.trim() || null });
      toast("Đã thêm kết nối"); render("integration");
    });
    document.querySelectorAll("[data-sctest]").forEach(b => b.onclick = () => guard(async () => {
      $("sc_test_result").textContent = "Đang kiểm tra kết nối...";
      const r = await POST(`/integration/connections/${b.dataset.sctest}/test`);
      $("sc_test_result").innerHTML = r.ok ? `<span style="color:var(--green)">✔ ${esc(r.message)}</span>` : `<span style="color:var(--red)">✘ ${esc(r.message)}</span>`;
      render("integration");
    }));
    document.querySelectorAll("[data-scdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xoá kết nối này? Không thể hoàn tác.")) return;
      await DELETE(`/integration/connections/${b.dataset.scdel}`); toast("Đã xoá kết nối"); render("integration");
    }));
    document.querySelectorAll("[data-scpreview]").forEach(b => b.onclick = () => {
      const connId = b.dataset.scpreview;
      modal(`<h3>Xem trước bảng (chỉ đọc)</h3>
        <div class="muted" style="margin-bottom:8px">Nhập tên bảng/view trong CSDL đã kết nối để xem cột + vài dòng mẫu — không sửa/ghi dữ liệu.</div>
        <div class="row"><div class="field"><label>Tên bảng</label><input id="scp_table" value="Energy"/></div>
          <button class="btn sm" id="scp_go">Xem</button></div>
        <div id="scp_result" style="margin-top:12px"></div>`);
      $("scp_go").onclick = () => guard(async () => {
        $("scp_result").innerHTML = '<div class="muted">Đang tải...</div>';
        const r = await GET(`/integration/connections/${connId}/preview-table?table=${encodeURIComponent($("scp_table").value.trim())}&limit=5`);
        $("scp_result").innerHTML = `<h4>Cột (${r.columns.length})</h4>
          <table><thead><tr><th>Tên cột</th><th>Kiểu</th></tr></thead>
          <tbody>${r.columns.map(c => `<tr><td><code class="k">${esc(c.name)}</code></td><td class="muted">${esc(c.type)}</td></tr>`).join("")}</tbody></table>
          <h4 style="margin-top:12px">Dữ liệu mẫu (${r.sample_rows.length} dòng)</h4>
          <div class="tablewrap"><table><thead><tr>${r.columns.map(c => `<th>${esc(c.name)}</th>`).join("")}</tr></thead>
          <tbody>${r.sample_rows.map(row => `<tr>${r.columns.map(c => `<td>${esc(String(row[c.name] ?? ""))}</td>`).join("")}</tr>`).join("") ||
            `<tr><td colspan="${r.columns.length}" class="muted">Không có dữ liệu.</td></tr>`}</tbody></table></div>`;
      });
    });
    document.querySelectorAll("[data-scedit]").forEach(b => b.onclick = () => {
      const c = sqlConns.find(x => x.connection_id === b.dataset.scedit);
      modal(`<h3>Sửa kết nối — ${esc(c.name)}</h3>
        <div class="row" style="flex-wrap:wrap">
          <div class="field"><label>Tên kết nối</label><input id="sce_name" value="${esc(c.name)}"/></div>
          <div class="field"><label>Host</label><input id="sce_host" value="${esc(c.host)}"/></div>
          <div class="field"><label>Port</label><input id="sce_port" type="number" value="${c.port}" style="width:90px"/></div>
          <div class="field"><label>Database</label><input id="sce_db" value="${esc(c.database_name)}"/></div>
          <div class="field"><label>Username</label><input id="sce_user" value="${esc(c.username)}"/></div>
          <div class="field"><label>Password</label><input id="sce_pass" type="password" placeholder="(để trống nếu không đổi)"/></div>
          <div class="field" style="flex:1;min-width:220px"><label>Tham số khác</label><input id="sce_extra" value="${esc(c.extra_params || "")}" placeholder="Encrypt=yes&TrustServerCertificate=yes" style="width:100%"/></div>
        </div>
        <button class="btn" id="sce_save" style="margin-top:12px">Lưu</button>`);
      $("sce_save").onclick = () => guard(async () => {
        await PUT(`/integration/connections/${c.connection_id}`, {
          name: $("sce_name").value.trim(), host: $("sce_host").value.trim(),
          port: parseInt($("sce_port").value, 10) || 1433, database_name: $("sce_db").value.trim(),
          username: $("sce_user").value.trim(), password: $("sce_pass").value || null,
          extra_params: $("sce_extra").value.trim() || null,
        });
        closeModal(); toast("Đã lưu kết nối"); render("integration");
      });
    });
    // Tự động thử lại kết nối SQL đang lỗi mỗi 15 giây (chỉ những connection last_test_ok===false,
    // không đụng tới connection OK hoặc chưa từng test) — khi WAN thông trở lại, badge tự chuyển
    // OK mà không cần bấm "Test kết nối" thủ công.
    let scRetryBusy = false;
    const scRetryTick = () => guard(async () => {
      if (scRetryBusy) return;
      const failing = sqlConns.filter(c => c.last_test_ok === false);
      if (!failing.length) return;
      scRetryBusy = true;
      try {
        await Promise.all(failing.map(async (c) => {
          let r;
          try { r = await POST(`/integration/connections/${c.connection_id}/test`); }
          catch (e) { return; }
          c.last_test_ok = r.ok; c.last_test_message = r.message; c.last_tested_at = new Date().toISOString();
          const cell = document.querySelector(`[data-sctestcell="${c.connection_id}"]`);
          if (cell) cell.innerHTML = `${badge(r.ok ? "available" : "critical")}${r.ok ? "OK" : "Lỗi"} · ${fmt(c.last_tested_at)}${!r.ok ? `<div class="muted" style="font-size:11px;max-width:260px;white-space:normal">${esc(r.message || "")}</div>` : ""}`;
        }));
      } finally { scRetryBusy = false; }
    });
    if (window.__scRetry) clearInterval(window.__scRetry);
    window.__scRetry = setInterval(scRetryTick, 15000);
  }
};

// ================= BÁO CÁO SẢN XUẤT =================
const normStatus = { dat: ["available", "đạt"], vuot: ["critical", "vượt định mức"], thieu: ["due", "thiếu"] };
VIEWS.reports = async function () {
  const sec = SUB.reports || "material";
  const sections = [{ key: "material", label: "Định mức NVL" }, { key: "filling", label: "Chiết (lon)" },
    { key: "keg", label: "Chiết (keg)" }, { key: "lostatus", label: "Trạng thái lô" }];
  let body = "";

  if (sec === "material") {
    const days = SUB.reports_days || 3650;
    const rep = await GET("/reports/material-norm?days=" + days);
    body = `<div class="panel"><h2>BC định mức nguyên vật liệu <span class="muted">(${rep.batch_count} mẻ)</span></h2>
      <div class="row"><div class="field"><label>Kỳ (ngày gần đây)</label>
        <select id="rp_days"><option value="30">30 ngày</option><option value="90">90 ngày</option><option value="365">365 ngày</option><option value="3650" selected>Tất cả</option></select></div>
      </div>
      <h3>Tổng hợp theo vật tư (định mức scale ↔ thực tế)</h3>
      <input class="searchbox" data-tbl="t_matnorm" placeholder="Tìm theo mã vật tư, trạng thái..."/>
      <div class="tablewrap"><table id="t_matnorm"><thead><tr><th>Vật tư</th><th>Số mẻ</th><th>Định mức</th><th>Thực tế</th><th>Chênh</th><th>%</th><th>ĐVT</th><th>Trạng thái</th></tr></thead>
      <tbody>${rep.materials.map(m => `<tr class="row-${{dat:"blue",vuot:"red",thieu:"green"}[m.status] || ""}">
        <td><code class="k">${esc(m.material_code)}</code></td><td>${m.batches}</td>
        <td>${m.planned.toLocaleString("vi-VN")}</td><td>${m.actual.toLocaleString("vi-VN")}</td>
        <td style="color:${m.diff > 0 ? "var(--red)" : m.diff < 0 ? "var(--orange)" : "var(--muted)"}">${m.diff > 0 ? "+" : ""}${m.diff.toLocaleString("vi-VN")}</td>
        <td>${m.pct}%</td><td>${esc(m.uom || "")}</td>
        <td>${badge((normStatus[m.status] || ["planned", m.status])[0])}${(normStatus[m.status] || ["", m.status])[1]}</td></tr>`).join("") || '<tr><td colspan=8 class="muted">Chưa có dữ liệu.</td></tr>'}</tbody></table></div>
      <h3>Theo mẻ</h3>
      <input class="searchbox" data-tbl="t_matnorm_batch" placeholder="Tìm theo mã mẻ, trạng thái..."/>
      <div class="tablewrap"><table id="t_matnorm_batch"><thead><tr><th>Mã mẻ</th><th>Trạng thái</th><th>SL kế hoạch</th><th>Tổng định mức</th><th>Tổng thực tế</th></tr></thead>
      <tbody>${rep.batches.map(b => `<tr><td><code class="k">${esc(b.batch_code)}</code></td><td>${badge(b.state)}</td>
        <td>${b.planned_qty.toLocaleString("vi-VN")} ${esc(b.uom)}</td><td>${b.planned_total.toLocaleString("vi-VN")}</td>
        <td>${b.actual_total.toLocaleString("vi-VN")}</td></tr>`).join("") || '<tr><td colspan=5 class="muted">—</td></tr>'}</tbody></table></div>
      <div class="muted" style="margin-top:8px">Định mức = BOM của từng mẻ đã scale theo SL kế hoạch; thực tế = tiêu thụ thật (genealogy). Ngưỡng đạt: ±5%.</div>
    </div>`;
  } else if (sec === "filling") {
    // Hiện khung màn hình NGAY (không đợi CSDL SCADA ngoài) — dữ liệu tải bất đồng bộ sau,
    // đổ vào #fp_data khi xong, tránh cảm giác "bấm vào tab rất lâu mới thấy gì".
    // Mặc định NGÀY HÔM QUA (giờ máy client) — giống Điện theo ca: hôm nay chưa qua hết ca 3
    // nên chưa có đủ dữ liệu để tính trọn 3 ca.
    const fYesterday = new Date(); fYesterday.setDate(fYesterday.getDate() - 1);
    const fMode = SUB.filling_mode || "day";
    const fDate = SUB.filling_date || toISODateLocal(fYesterday);
    const fMonth = SUB.filling_month || toISODateLocal(fYesterday).slice(0, 7);
    SUB.filling_mode = fMode; SUB.filling_date = fDate; SUB.filling_month = fMonth;
    body = `<div class="panel"><h2>🥫 Sản lượng chiết lon — dữ liệu SCADA thật</h2>
      <div class="muted" style="margin-bottom:8px">Nguồn: bảng 30K_Report qua kết nối CSDL gán "Dùng cho: Chiết (đóng gói)". Chọn 1 ngày để xem 3 ca của ngày đó, hoặc chọn cả tháng để xem theo từng ngày trong tháng. Nếu không có bản ghi đúng giờ ranh giới ca, hệ thống lấy bản ghi gần giờ đó nhất TRƯỚC mốc (không lấy bản ghi ở tương lai so với mốc) — dữ liệu nguồn càng thưa, breakdown theo ca càng chỉ mang tính tham khảo.</div>
      <div class="row">
        <div class="field"><label>Xem theo</label><select id="fp_mode">
          <option value="day" ${fMode === "day" ? "selected" : ""}>Ngày cụ thể</option>
          <option value="month" ${fMode === "month" ? "selected" : ""}>Cả tháng</option></select></div>
        <div class="field" id="fp_day_field" style="${fMode === "month" ? "display:none" : ""}"><label>Ngày</label><input id="fp_date" type="date" value="${fDate}"/></div>
        <div class="field" id="fp_month_field" style="${fMode === "day" ? "display:none" : ""}"><label>Tháng</label><input id="fp_month" type="month" value="${fMonth}"/></div>
        <button class="btn" id="fp_apply">Xem báo cáo</button>
      </div></div>
      <div id="fp_data"><div class="panel muted">⏳ Đang tải dữ liệu từ CSDL SCADA...</div></div>`;
  } else if (sec === "keg") {
    // Giống hệt Chiết (lon): hiện khung màn hình NGAY, mặc định NGÀY HÔM QUA (giờ máy client).
    const kYesterday = new Date(); kYesterday.setDate(kYesterday.getDate() - 1);
    const kMode = SUB.keg_mode || "day";
    const kDate = SUB.keg_date || toISODateLocal(kYesterday);
    const kMonth = SUB.keg_month || toISODateLocal(kYesterday).slice(0, 7);
    SUB.keg_mode = kMode; SUB.keg_date = kDate; SUB.keg_month = kMonth;
    body = `<div class="panel"><h2>🛢️ Sản lượng chiết keg — dữ liệu SCADA thật</h2>
      <div class="muted" style="margin-bottom:8px">Nguồn: bảng Donggoi (4 line L1-L4) qua kết nối CSDL gán "Dùng cho: Chiết (keg)". Chọn 1 ngày để xem 3 ca của ngày đó, hoặc chọn cả tháng để xem theo từng ngày trong tháng. Nếu không có bản ghi đúng giờ ranh giới ca, hệ thống lấy bản ghi gần giờ đó nhất TRƯỚC mốc (không lấy bản ghi ở tương lai so với mốc) — dữ liệu nguồn càng thưa, breakdown theo ca càng chỉ mang tính tham khảo.</div>
      <div class="row">
        <div class="field"><label>Xem theo</label><select id="kp_mode">
          <option value="day" ${kMode === "day" ? "selected" : ""}>Ngày cụ thể</option>
          <option value="month" ${kMode === "month" ? "selected" : ""}>Cả tháng</option></select></div>
        <div class="field" id="kp_day_field" style="${kMode === "month" ? "display:none" : ""}"><label>Ngày</label><input id="kp_date" type="date" value="${kDate}"/></div>
        <div class="field" id="kp_month_field" style="${kMode === "day" ? "display:none" : ""}"><label>Tháng</label><input id="kp_month" type="month" value="${kMonth}"/></div>
        <button class="btn" id="kp_apply">Xem báo cáo</button>
      </div></div>
      <div id="kp_data"><div class="panel muted">⏳ Đang tải dữ liệu từ CSDL SCADA...</div></div>`;
  } else if (sec === "lostatus") {
    const rows = await GET("/reports/lo-status");
    const nauBadge = { chua_co_me: "planned", dang_thuc_hien: "in_progress", hoan_thanh: "completed" };
    const lmBadge = { len_men: "running", loc_mot_phan: "due", da_loc_het: "done" };
    const locBadge = { chua_loc: "planned", dang_loc: "in_progress", da_ket_thuc: "completed" };
    const chietBadge = { chua_chiet: "planned", dang_chiet: "in_progress", da_ket_thuc: "completed" };
    body = `<div class="panel"><h2>Trạng thái lô — Nấu / Lên men / Lọc / Chiết <span class="muted">(${rows.length} mã nấu)</span></h2>
      <div class="muted" style="margin-bottom:8px">Trạng thái Nấu/Lọc/Chiết theo việc vận hành đã bấm "Kết thúc" hay chưa ở từng tab; Lên men vẫn tự động theo tồn CCT như trước.</div>
      <input class="searchbox" data-tbl="t_lostatus" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_lostatus"><thead><tr><th>Mã nấu</th><th>Ngày nấu</th><th>Dịch nha</th>
        <th>Nấu</th><th>Lên men</th><th>Lọc</th><th>Chiết</th></tr></thead>
      <tbody>${rows.map(r => `<tr><td class="code">${esc(r.brew_code)}</td><td>${fmt(r.brew_date)}</td><td>${esc(r.wort_type || "")}</td>
        <td>${badge(nauBadge[r.nau] || "planned")}${esc(r.nau_label)}</td>
        <td>${r.len_men ? badge(lmBadge[r.len_men] || "planned") + esc(r.len_men_label) : `${badge("planned")}${esc(r.len_men_label)}`}</td>
        <td>${badge(locBadge[r.loc] || "planned")}${esc(r.loc_label)}</td>
        <td>${badge(chietBadge[r.chiet] || "planned")}${esc(r.chiet_label)}</td></tr>`).join("") ||
        '<tr><td colspan=7 class="muted">Chưa có mã nấu nào.</td></tr>'}</tbody></table></div></div>`;
  }

  $("view-reports").innerHTML = subnav("reports", sections, sec) + body;
  wireSubnav("reports"); wireSearch();
  if (sec === "lostatus") wirePaginate("t_lostatus", 20);
  if (sec === "material") { wirePaginate("t_matnorm", 10); wirePaginate("t_matnorm_batch", 10); }
  if (sec === "material") {
    $("rp_days").value = String(SUB.reports_days || 3650);
    $("rp_days").onchange = () => { SUB.reports_days = parseInt($("rp_days").value); render("reports"); };
  }
  if (sec === "filling") {
    $("fp_mode").onchange = () => {
      const isMonth = $("fp_mode").value === "month";
      $("fp_day_field").style.display = isMonth ? "none" : "";
      $("fp_month_field").style.display = isMonth ? "" : "none";
    };
    $("fp_apply").onclick = () => {
      SUB.filling_mode = $("fp_mode").value;
      SUB.filling_date = $("fp_date").value;
      SUB.filling_month = $("fp_month").value;
      render("reports");
    };
    loadFillingData();
  }
  if (sec === "keg") {
    $("kp_mode").onchange = () => {
      const isMonth = $("kp_mode").value === "month";
      $("kp_day_field").style.display = isMonth ? "none" : "";
      $("kp_month_field").style.display = isMonth ? "" : "none";
    };
    $("kp_apply").onclick = () => {
      SUB.keg_mode = $("kp_mode").value;
      SUB.keg_date = $("kp_date").value;
      SUB.keg_month = $("kp_month").value;
      render("reports");
    };
    loadKegData();
  }
};

// Tải dữ liệu sản lượng chiết lon (CSDL SCADA ngoài) SAU khi khung màn hình đã hiện —
// tự thoát nếu người dùng đã chuyển sang tab khác trước khi tải xong.
async function loadFillingData() {
  const stillHere = () => $("view-reports").classList.contains("active") && $("fp_data");
  try {
    let dateFrom, dateTo;
    if (SUB.filling_mode === "month") {
      const [y, m] = SUB.filling_month.split("-").map(Number);
      dateFrom = toDTLocal(new Date(y, m - 1, 1, 6, 0, 0));
      dateTo = toDTLocal(new Date(y, m, 1, 6, 0, 0));
    } else {
      const start = new Date(SUB.filling_date + "T06:00:00");
      const end = new Date(start); end.setDate(end.getDate() + 1);
      dateFrom = toDTLocal(start); dateTo = toDTLocal(end);
    }

    const rpt = await GET(`/reports/filling-report?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}`);
    if (!stillHere()) return;
    const caColors = ["#3498db", "#f5a623", "#9b59b6"];
    const dayLabels = rpt.by_day.map(d => d.date.slice(5));
    const barSeries = [
      { label: "Ca 1 (06h-14h)", color: caColors[0], values: rpt.by_day.map(d => d.ca1) },
      { label: "Ca 2 (14h-22h)", color: caColors[1], values: rpt.by_day.map(d => d.ca2) },
      { label: "Ca 3 (22h-06h)", color: caColors[2], values: rpt.by_day.map(d => d.ca3) },
    ];
    const pieItems = rpt.by_ca.map((c, i) => ({ label: c.label, value: c.value, color: caColors[i] }));

    $("fp_data").innerHTML = `<div class="muted" style="margin-bottom:8px">📅 Đang xem dữ liệu từ <b>${fmt(rpt.date_from)}</b> đến <b>${fmt(rpt.date_to)}</b></div>
      <div class="muted" style="margin-bottom:8px">Kết nối "${esc(rpt.connection_name)}"</div>
      ${rpt.has_gap ? '<div style="color:var(--orange,#f5a623);margin-bottom:8px">⚠ Có khoảng trống dữ liệu lớn trong CSDL nguồn ở 1+ ca — các ca đó hiện "—" thay vì số bịa, tổng có thể chưa đầy đủ.</div>' : ""}
      <div class="row" style="gap:10px;flex-wrap:wrap">
        <div class="panel" style="flex:1;min-width:180px">
          <div class="muted" style="font-size:12px">TỔNG SỐ LON</div>
          <div style="font-size:26px;font-weight:700;color:#2ecc71">${rpt.total_cans.toLocaleString("vi-VN")} <span style="font-size:14px;font-weight:400">lon</span></div>
        </div>
        ${rpt.by_ca.map((c, i) => `<div class="panel" style="flex:1;min-width:160px">
          <div class="muted" style="font-size:12px">${esc(c.label.toUpperCase())}${c.data_gap ? ' ⚠' : ""}</div>
          <div style="font-size:22px;font-weight:700;color:${caColors[i]}">${c.value.toLocaleString("vi-VN")} <span style="font-size:13px;font-weight:400">lon</span></div>
        </div>`).join("")}
      </div>
      <div class="split">
        <div class="panel"><h2>Tỉ lệ theo ca</h2>${pieItems.some(p => p.value > 0) ? CH.pie(pieItems) : '<div class="muted">Không có dữ liệu.</div>'}</div>
        <div class="panel"><h2>Theo ngày — từng ca</h2>${dayLabels.length ? CH.groupedN(dayLabels, barSeries) : '<div class="muted">Không có dữ liệu.</div>'}</div>
      </div>
      <div class="panel"><h2>Chi tiết theo ca</h2>
        <div class="tablewrap"><table><thead><tr><th>Ngày</th><th>Ca</th><th>Bắt đầu</th><th>Kết thúc</th><th>Số lon</th></tr></thead>
        <tbody>${rpt.shifts.map(s => `<tr><td>${fmt(s.date)}</td><td>Ca ${s.ca}</td>
          <td class="muted">${new Date(s.start).toLocaleString("vi-VN")}</td><td class="muted">${new Date(s.end).toLocaleString("vi-VN")}</td>
          <td${s.data_gap ? ' class="muted" title="Thiếu dữ liệu — khoảng trống lớn trong CSDL nguồn"' : ""}>${s.cans != null ? s.cans.toLocaleString("vi-VN") : "— ⚠"}</td></tr>`).join("") ||
          '<tr><td colspan=5 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div></div>`;
  } catch (e) {
    if (!stillHere()) return;
    $("fp_data").innerHTML = `<div class="panel muted">Chưa xem được sản lượng chiết: ${esc(e.message)}
      <button class="btn sm sec" id="fp_goto_intg">Đi tới Tích hợp › Kết nối CSDL</button></div>`;
    $("fp_goto_intg").onclick = () => gotoView("integration", "dbconn");
  }
}

// Tải dữ liệu sản lượng chiết keg (CSDL SCADA ngoài) SAU khi khung màn hình đã hiện —
// tự thoát nếu người dùng đã chuyển sang tab khác trước khi tải xong.
async function loadKegData() {
  const stillHere = () => $("view-reports").classList.contains("active") && $("kp_data");
  try {
    let dateFrom, dateTo;
    if (SUB.keg_mode === "month") {
      const [y, m] = SUB.keg_month.split("-").map(Number);
      dateFrom = toDTLocal(new Date(y, m - 1, 1, 6, 0, 0));
      dateTo = toDTLocal(new Date(y, m, 1, 6, 0, 0));
    } else {
      const start = new Date(SUB.keg_date + "T06:00:00");
      const end = new Date(start); end.setDate(end.getDate() + 1);
      dateFrom = toDTLocal(start); dateTo = toDTLocal(end);
    }

    const rpt = await GET(`/reports/keg-report?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}`);
    if (!stillHere()) return;
    const caColors = ["#3498db", "#f5a623", "#9b59b6"];
    const dayLabels = rpt.by_day.map(d => d.date.slice(5));
    const barSeries = [
      { label: "Ca 1 (06h-14h)", color: caColors[0], values: rpt.by_day.map(d => d.ca1) },
      { label: "Ca 2 (14h-22h)", color: caColors[1], values: rpt.by_day.map(d => d.ca2) },
      { label: "Ca 3 (22h-06h)", color: caColors[2], values: rpt.by_day.map(d => d.ca3) },
    ];
    const pieItems = rpt.by_ca.map((c, i) => ({ label: c.label, value: c.value, color: caColors[i] }));

    $("kp_data").innerHTML = `<div class="muted" style="margin-bottom:8px">📅 Đang xem dữ liệu từ <b>${fmt(rpt.date_from)}</b> đến <b>${fmt(rpt.date_to)}</b></div>
      <div class="muted" style="margin-bottom:8px">Kết nối "${esc(rpt.connection_name)}"</div>
      ${rpt.has_gap ? '<div style="color:var(--orange,#f5a623);margin-bottom:8px">⚠ Có khoảng trống dữ liệu lớn trong CSDL nguồn ở 1+ ca — các ca đó hiện "—" thay vì số bịa, tổng có thể chưa đầy đủ.</div>' : ""}
      <div class="row" style="gap:10px;flex-wrap:wrap">
        <div class="panel" style="flex:1;min-width:180px">
          <div class="muted" style="font-size:12px">TỔNG SỐ KEG</div>
          <div style="font-size:26px;font-weight:700;color:#2ecc71">${rpt.total_kegs.toLocaleString("vi-VN")} <span style="font-size:14px;font-weight:400">keg</span></div>
        </div>
        ${rpt.by_ca.map((c, i) => `<div class="panel" style="flex:1;min-width:160px">
          <div class="muted" style="font-size:12px">${esc(c.label.toUpperCase())}${c.data_gap ? ' ⚠' : ""}</div>
          <div style="font-size:22px;font-weight:700;color:${caColors[i]}">${c.value.toLocaleString("vi-VN")} <span style="font-size:13px;font-weight:400">keg</span></div>
        </div>`).join("")}
      </div>
      <div class="split">
        <div class="panel"><h2>Tỉ lệ theo ca</h2>${pieItems.some(p => p.value > 0) ? CH.pie(pieItems) : '<div class="muted">Không có dữ liệu.</div>'}</div>
        <div class="panel"><h2>Theo ngày — từng ca</h2>${dayLabels.length ? CH.groupedN(dayLabels, barSeries) : '<div class="muted">Không có dữ liệu.</div>'}</div>
      </div>
      <div class="panel"><h2>Chi tiết theo ca</h2>
        <div class="tablewrap"><table><thead><tr><th>Ngày</th><th>Ca</th><th>Bắt đầu</th><th>Kết thúc</th><th>Số keg</th></tr></thead>
        <tbody>${rpt.shifts.map(s => `<tr><td>${fmt(s.date)}</td><td>Ca ${s.ca}</td>
          <td class="muted">${new Date(s.start).toLocaleString("vi-VN")}</td><td class="muted">${new Date(s.end).toLocaleString("vi-VN")}</td>
          <td${s.data_gap ? ' class="muted" title="Thiếu dữ liệu — khoảng trống lớn trong CSDL nguồn"' : ""}>${s.kegs != null ? s.kegs.toLocaleString("vi-VN") : "— ⚠"}</td></tr>`).join("") ||
          '<tr><td colspan=5 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div></div>
      <div class="panel"><h2>Theo từng line</h2>
        <div class="muted" style="margin-bottom:8px">Sản lượng từng line chiết keg (L1-L4), chia theo ca.${rpt.has_gap ? ' ⚠ Có ca thiếu dữ liệu (xem ở trên) — số theo line dưới đây không tính ca đó.' : ""}</div>
        ${rpt.by_line.some(l => l.total > 0) ? CH.groupedN(rpt.by_line.map(l => l.label), [
          { label: "Ca 1 (06h-14h)", color: caColors[0], values: rpt.by_line.map(l => l.ca1) },
          { label: "Ca 2 (14h-22h)", color: caColors[1], values: rpt.by_line.map(l => l.ca2) },
          { label: "Ca 3 (22h-06h)", color: caColors[2], values: rpt.by_line.map(l => l.ca3) },
        ]) : '<div class="muted">Không có dữ liệu.</div>'}
        <div class="tablewrap" style="margin-top:12px"><table><thead><tr><th>Line</th><th>Ca 1</th><th>Ca 2</th><th>Ca 3</th><th>Tổng</th></tr></thead>
        <tbody>${rpt.by_line.map(l => `<tr><td>${esc(l.label)}</td>
          <td>${l.ca1.toLocaleString("vi-VN")}</td><td>${l.ca2.toLocaleString("vi-VN")}</td><td>${l.ca3.toLocaleString("vi-VN")}</td>
          <td><b>${l.total.toLocaleString("vi-VN")}</b></td></tr>`).join("") ||
          '<tr><td colspan=5 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div></div>`;
  } catch (e) {
    if (!stillHere()) return;
    $("kp_data").innerHTML = `<div class="panel muted">Chưa xem được sản lượng chiết keg: ${esc(e.message)}
      <button class="btn sm sec" id="kp_goto_intg">Đi tới Tích hợp › Kết nối CSDL</button></div>`;
    $("kp_goto_intg").onclick = () => gotoView("integration", "dbconn");
  }
}

// ================= QUẢN TRỊ TÀI KHOẢN (admin) =================
const ROLE_DESC = { operator: "Vận hành (ghi nhận)", supervisor: "Trưởng ca/Quản đốc",
  qa: "QA/KCS (release)", engineer: "Kỹ sư (recipe)", admin: "Quản trị" };
const ALL_VIEWS = ["dashboard","flowmap","orders","dispatch","recipes","batches","quality","process","trace",
  "warehouse_kc","warehouse_px","energy","realtime","maint","calib","reports","ai","integration","master","users","audit"];

// ================= DANH MỤC (master data: sản phẩm + vật tư) =================
const STAGE_LABELS = { nau: "Mẻ nấu", len_men_chinh: "Lên men chính", len_men_phu: "Lên men phụ",
  loc: "Lọc", chiet: "Chiết", thanh_pham: "Thành phẩm" };

function lineSectionHtml(kind, title, rows, canManage, noPerm) {
  const isLine = kind === "line";
  const p = kind; // id prefix, tránh trùng id giữa 3 mục
  const kindPicker = isLine ? `<div class="field"><label>Loại</label><select id="ln_${p}_kind">
      <option value="line">Dây chuyền (đóng gói)</option>
      <option value="brewhouse">Nhà nấu (brewhouse)</option></select></div>` : "";
  const capField = isLine
    ? `<div class="field"><label>Công suất</label><input id="ln_${p}_rate" type="number" placeholder="VD: 200" style="width:100px"/></div>
       <div class="field"><label>Đơn vị công suất</label><input id="ln_${p}_rate_uom" placeholder="lon/phút" style="width:110px"/></div>`
    : `<div class="field"><label>Thể tích</label><input id="ln_${p}_vol" type="number" placeholder="VD: 200" style="width:100px"/></div>
       <div class="field"><label>Đơn vị thể tích</label><input id="ln_${p}_vol_uom" value="hl" style="width:90px"/></div>`;
  const rowsHtml = rows.map(l => `<tr>
      <td><code class="k">${esc(l.code)}</code></td><td>${esc(l.name)}</td>
      <td>${esc(l.area || "—")}</td>
      <td>${isLine ? (l.ideal_rate_per_min ? l.ideal_rate_per_min + (l.capacity_uom ? " " + esc(l.capacity_uom) : "/phút") : "—")
                   : (l.volume ? l.volume + " " + esc(l.volume_uom || "") : "—")}</td>
      <td>${badge(l.active ? "available" : "obsolete")}${l.active ? "hoạt động" : "ngừng"}</td>
      ${canManage ? `<td style="white-space:nowrap">
        <button class="btn sm sec" data-ledit="${p}|${esc(l.line_id)}">Sửa</button>
        <button class="btn sm sec" data-ltoggle="${esc(l.line_id)}">${l.active ? "Ngừng" : "Bật lại"}</button>
        <button class="btn sm sec" data-ldel="${esc(l.line_id)}">Xóa</button></td>` : ""}</tr>`).join("")
    || `<tr><td colspan="${canManage ? 6 : 5}" class="muted">Chưa có mục nào.</td></tr>`;
  return `<div class="panel"><h2>${title} <span class="muted">(${rows.length})</span></h2>
    ${noPerm}
    ${canManage ? `<div class="row">
      <div class="field"><label>Mã</label><input id="ln_${p}_code" placeholder="${isLine ? "Line-3 (keg)" : kind === "tank" ? "FV-05" : "BBT-01"}"/></div>
      <div class="field"><label>Tên</label><input id="ln_${p}_name" placeholder="${isLine ? "Dây chuyền keg #3" : "Tank " + (kind === "tank" ? "lên men" : "BBT") + " #5"}"/></div>
      ${kindPicker}
      <div class="field"><label>Khu vực</label><input id="ln_${p}_area" style="width:90px"/></div>
      ${capField}
      <button class="btn" id="ln_${p}_add" style="align-self:flex-end">+ Thêm</button>
    </div>` : ""}
    <div class="tablewrap" style="margin-top:12px"><table>
      <thead><tr><th>Mã</th><th>Tên</th><th>Khu vực</th><th>${isLine ? "Công suất" : "Thể tích"}</th><th>Trạng thái</th>${canManage ? "<th></th>" : ""}</tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table></div>
  </div>`;
}
const PRODUCT_SCOPED_STAGES = ["nau", "len_men_chinh", "len_men_phu"];
// Sản phẩm (SKU) chỉ có ý nghĩa ở "loc" và "thanh_pham" — mirror qc_catalog.SKU_SCOPED_STAGES.
const SKU_SCOPED_STAGES = ["loc", "thanh_pham"];
VIEWS.master = async function () {
  const [products, finishedProducts, materials, plines, qcParams, qcGroups, stageGroups, beerTypes, suppliers, materialGroups, opsSettings] = await Promise.all([
    GET("/products"), GET("/finished-products").catch(() => []), GET("/materials"), GET("/lines").catch(() => []),
    GET("/qc/parameters?active_only=false").catch(() => []),
    GET("/qc/groups").catch(() => []), GET("/qc/stage-groups").catch(() => []), GET("/beer-types").catch(() => []),
    GET("/suppliers").catch(() => []), GET("/material-groups").catch(() => []),
    GET("/ops-settings").catch(() => ({ empty_cct_tolerance_hl: 2, empty_bbt_tolerance_hl: 2 }))]);
  const canManage = CURRENT_USER && (CURRENT_USER.permissions === "*" ||
    (Array.isArray(CURRENT_USER.permissions) && CURRENT_USER.permissions.includes("master.manage")));
  const noPerm = canManage ? "" :
    `<div class="muted" style="margin-bottom:8px">Bạn chỉ có quyền xem danh mục (cần quyền <code class="k">master.manage</code> để tạo/sửa).</div>`;
  const activeGroups = materialGroups.filter(g => g.active);
  const fpCats = ["Bia chai", "Bia lon", "Bia hơi", "Bia tươi"];
  $("view-master").innerHTML = `
    <div class="split">
      <div class="panel"><h2>🍺 Dịch bia <span class="muted">(${products.length})</span></h2>
        <div class="muted" style="margin-bottom:6px">Loại dịch bia/công thức đang chạy qua nấu → lên men → lọc (khác Sản phẩm — SKU đóng gói cuối cùng, khai báo ở panel bên dưới). Gán "Loại bia" (thương hiệu, VD Sapphire) để chỉ tiêu Lọc/Chiết áp dụng chung cho mọi độ oP của cùng 1 Loại bia.</div>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã dịch bia</label><input id="pr_code" placeholder="BIA-IPA"/></div>
          <div class="field"><label>Tên dịch bia</label><input id="pr_name" placeholder="Bia IPA 5.5%"/></div>
          <div class="field"><label>ĐVT</label><input id="pr_uom" value="L" style="width:70px"/></div>
          <div class="field"><label>Số ngày lên men</label><input id="pr_ferment_days" type="number" placeholder="VD: 20" style="width:120px"/></div>
          <div class="field"><label>Loại bia (tuỳ chọn)</label><select id="pr_beertype"><option value="">(chưa gán)</option>${beerTypes.map(bt => `<option value="${bt.beer_type_id}">${esc(bt.code)} — ${esc(bt.name)}</option>`).join("")}</select></div>
        </div>
        <div class="field"><label>Mô tả</label><input id="pr_desc" placeholder="(tuỳ chọn)" style="width:100%"/></div>
        <button class="btn" id="pr_add" style="margin-top:10px">+ Tạo dịch bia</button>` : ""}
        <input class="searchbox" data-tbl="t_products" placeholder="Tìm mã/tên dịch bia..." style="margin-top:10px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_products">
          <thead><tr><th>Mã</th><th>Tên</th><th>ĐVT</th><th>Số ngày lên men</th><th>Loại bia</th><th>Mô tả</th>${canManage ? "<th></th>" : ""}</tr></thead>
          <tbody>${products.map(p => { const bt = beerTypes.find(x => x.beer_type_id === p.beer_type_id); return `<tr>
            <td><code class="k">${esc(p.code)}</code></td><td>${esc(p.name)}</td><td>${esc(p.uom)}</td>
            <td class="muted">${p.ferment_days_std ?? "—"}</td>
            <td class="muted">${bt ? esc(bt.name) : "—"}</td>
            <td class="muted">${esc(p.description || "—")}</td>
            ${canManage ? `<td style="white-space:nowrap">
              <button class="btn sm sec" data-ep="${esc(p.product_id)}">Sửa</button>
              <button class="btn sm sec" data-brewspec="${esc(p.product_id)}">Quy định nấu</button>
              <button class="btn sm sec" data-epdel="${esc(p.product_id)}">Xóa</button>
            </td>` : ""}</tr>`; }).join("")}</tbody>
        </table></div>
      </div>

      <div class="panel"><h2>🏷️ Loại bia <span class="muted">(${beerTypes.length})</span></h2>
        <div class="muted" style="margin-bottom:6px">Thương hiệu bia (VD Sapphire) — gộp nhiều Dịch bia khác độ oP; Lọc/Chiết tra chỉ tiêu theo Loại bia (không phân biệt oP), xem panel Dịch bia bên cạnh.</div>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã</label><input id="bt_code" placeholder="SAPPHIRE"/></div>
          <div class="field"><label>Tên</label><input id="bt_name" placeholder="Sapphire"/></div>
          <div class="field"><label>Ghi chú</label><input id="bt_note" placeholder="(tuỳ chọn)"/></div>
          <button class="btn" id="bt_add" style="align-self:flex-end">+ Tạo Loại bia</button>
        </div>` : ""}
        <input class="searchbox" data-tbl="t_beertypes" placeholder="Tìm mã/tên loại bia..." style="margin-top:10px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_beertypes">
          <thead><tr><th>Mã</th><th>Tên</th><th>Ghi chú</th>${canManage ? "<th></th>" : ""}</tr></thead>
          <tbody>${beerTypes.map(bt => `<tr>
            <td><code class="k">${esc(bt.code)}</code></td><td>${esc(bt.name)}</td>
            <td class="muted">${esc(bt.note || "—")}</td>
            ${canManage ? `<td style="white-space:nowrap">
              <button class="btn sm sec" data-ebt="${esc(bt.beer_type_id)}">Sửa</button>
              <button class="btn sm sec" data-btdel="${esc(bt.beer_type_id)}">Xóa</button>
            </td>` : ""}</tr>`).join("") ||
            `<tr><td colspan="${canManage ? 4 : 3}" class="muted">Chưa có Loại bia nào.</td></tr>`}</tbody>
        </table></div>
      </div>

      <div class="panel"><h2>📦 Vật tư / Nguyên liệu <span class="muted">(${materials.length})</span></h2>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã VT</label><input id="mt_code" placeholder="MALT-CARA"/></div>
          <div class="field"><label>Tên vật tư</label><input id="mt_name" placeholder="Malt Caramel"/></div>
          <div class="field"><label>ĐVT</label><input id="mt_uom" value="kg" style="width:70px"/></div>
          <div class="field"><label>Nhóm</label><select id="mt_cat">${activeGroups.map(g => `<option value="${esc(g.code)}">${esc(g.name)}</option>`).join("") ||
            "<option value=''>(chưa có nhóm — khai báo ở panel Nhóm vật tư)</option>"}</select></div>
          <div class="field"><label>Tồn tối thiểu</label><input id="mt_stockmin" type="number" step="0.01" placeholder="(tuỳ chọn)" style="width:110px"/></div>
        </div>
        <button class="btn" id="mt_add" style="margin-top:10px">+ Tạo vật tư</button>` : ""}
        <input class="searchbox" data-tbl="t_materials" placeholder="Tìm mã/tên vật tư..." style="margin-top:10px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_materials">
          <thead><tr><th>Mã</th><th>Tên</th><th>ĐVT</th><th>Nhóm</th><th>Tồn tối thiểu</th>${canManage ? "<th></th>" : ""}</tr></thead>
          <tbody>${materials.map(m => { const grp = materialGroups.find(g => g.code === m.category); return `<tr>
            <td><code class="k">${esc(m.code)}</code></td><td>${esc(m.name)}</td><td>${esc(m.uom)}</td>
            <td>${grp ? esc(grp.name) : esc(m.category || "—")}</td>
            <td>${m.stock_min ?? "—"}</td>
            ${canManage ? `<td style="white-space:nowrap">
              <button class="btn sm sec" data-em="${esc(m.material_id)}">Sửa</button>
              <button class="btn sm sec" data-mqc="${esc(m.material_id)}">Chỉ tiêu QC</button>
              <button class="btn sm sec" data-emdel="${esc(m.material_id)}">Xóa</button>
            </td>` : ""}</tr>`; }).join("")}</tbody>
        </table></div>
      </div>

      <div class="panel"><h2>🏷️ Nhóm vật tư <span class="muted">(${materialGroups.length})</span></h2>
        <div class="muted" style="margin-bottom:6px">Nhóm phân loại vật tư (malt/gạo/hoa bia/men/...) — chọn ở panel Vật tư/Nguyên liệu bên cạnh. Đánh dấu "Bao bì tiêu hao" để vật tư thuộc nhóm đó tự động xuất hiện ở báo cáo lô bao bì (tab Bao bì) — không áp dụng cho vỏ chai/két/keg tuần hoàn.</div>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã nhóm</label><input id="mg_code" placeholder="malt"/></div>
          <div class="field"><label>Tên nhóm</label><input id="mg_name" placeholder="Malt"/></div>
          <div class="field"><label><input type="checkbox" id="mg_packaging"/> Bao bì tiêu hao</label></div>
          <button class="btn" id="mg_add" style="align-self:flex-end">+ Tạo nhóm</button>
        </div>` : ""}
        <input class="searchbox" data-tbl="t_matgroups" placeholder="Tìm mã/tên nhóm vật tư..." style="margin-top:10px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_matgroups">
          <thead><tr><th>Mã</th><th>Tên</th><th>Trạng thái</th><th>Bao bì?</th>${canManage ? "<th></th>" : ""}</tr></thead>
          <tbody>${materialGroups.map(g => `<tr>
            <td><code class="k">${esc(g.code)}</code></td><td>${esc(g.name)}</td>
            <td>${g.active ? '<span style="color:var(--green)">Đang dùng</span>' : '<span class="muted">Đã ẩn</span>'}</td>
            <td>${g.is_packaging ? '<span style="color:var(--accent)">📦 Bao bì</span>' : '<span class="muted">—</span>'}</td>
            ${canManage ? `<td style="white-space:nowrap">
              <button class="btn sm sec" data-emg="${esc(g.group_id)}">Sửa</button>
              <button class="btn sm sec" data-mgdel="${esc(g.group_id)}">Xóa</button>
            </td>` : ""}</tr>`).join("") ||
            `<tr><td colspan="${canManage ? 5 : 4}" class="muted">Chưa có Nhóm vật tư nào.</td></tr>`}</tbody>
        </table></div>
      </div>

      <div class="panel"><h2>🚚 Nhà cung cấp <span class="muted">(${suppliers.length})</span></h2>
        <div class="muted" style="margin-bottom:6px">Danh mục nhà cung cấp NVL — chọn ở màn hình Nhập kho (tab Kho NVL → Nhập/Xuất/Hoàn/Sang ngang).</div>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã</label><input id="sp_code" placeholder="NCC-01"/></div>
          <div class="field"><label>Tên</label><input id="sp_name" placeholder="Công ty TNHH ..."/></div>
          <div class="field"><label>Địa chỉ</label><input id="sp_address" placeholder="(tuỳ chọn)"/></div>
          <div class="field"><label>Liên hệ</label><input id="sp_contact" placeholder="(tuỳ chọn)"/></div>
          <button class="btn" id="sp_add" style="align-self:flex-end">+ Tạo nhà cung cấp</button>
        </div>` : ""}
        <input class="searchbox" data-tbl="t_suppliers" placeholder="Tìm mã/tên nhà cung cấp..." style="margin-top:10px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_suppliers">
          <thead><tr><th>Mã</th><th>Tên</th><th>Địa chỉ</th><th>Liên hệ</th>${canManage ? "<th></th>" : ""}</tr></thead>
          <tbody>${suppliers.map(s => `<tr>
            <td><code class="k">${esc(s.code)}</code></td><td>${esc(s.name)}</td>
            <td class="muted">${esc(s.address || "—")}</td><td class="muted">${esc(s.contact || "—")}</td>
            ${canManage ? `<td style="white-space:nowrap">
              <button class="btn sm sec" data-esp="${esc(s.supplier_id)}">Sửa</button>
              <button class="btn sm sec" data-espdel="${esc(s.supplier_id)}">Xóa</button>
            </td>` : ""}</tr>`).join("") ||
            `<tr><td colspan="${canManage ? 5 : 4}" class="muted">Chưa có nhà cung cấp nào.</td></tr>`}</tbody>
        </table></div>
      </div>
    </div>

    <div class="panel"><h2>🍾 Sản phẩm (thành phẩm) <span class="muted">(${finishedProducts.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">SKU đóng gói (chai/lon/keg...) — chọn ở bước Chiết cùng tank BBT nguồn. Khác Dịch bia ở trên: cùng 1 dịch bia có thể ra nhiều Sản phẩm khác nhau.</div>
      ${noPerm}
      ${canManage ? `<div class="row">
        <div class="field"><label>Mã sản phẩm</label><input id="fp_code" placeholder="SKU-LON-330"/></div>
        <div class="field"><label>Tên sản phẩm</label><input id="fp_name" placeholder="Lon 330ml"/></div>
        <div class="field"><label>ĐVT</label><input id="fp_uom" value="lon" style="width:80px"/></div>
        <div class="field"><label>Loại đơn vị tồn kho</label><select id="fp_unittype"><option value="vi">Vỉ</option><option value="keg">Keg</option></select></div>
        <div class="field"><label>SL/1 đơn vị</label><input id="fp_pack" type="number" value="24" style="width:80px"/></div>
        <div class="field"><label>Loại sản phẩm</label><select id="fp_cat"><option value="">(không chọn)</option>${fpCats.map(c => `<option>${esc(c)}</option>`).join("")}</select></div>
        <div class="field"><label>Dịch bia gốc (tuỳ chọn)</label><select id="fp_product"><option value="">(không chọn)</option>${products.map(p => `<option value="${p.product_id}">${esc(p.code)}</option>`).join("")}</select></div>
      </div>
      <div class="muted" style="font-size:12px;margin-top:4px">Vỉ: SL/1 đơn vị = số lon/vỉ (VD 24). Keg: mỗi keg tự nó là 1 đơn vị (SL/1 đơn vị = 1).</div>
      <div class="field" style="margin-top:6px"><label>Mô tả</label><input id="fp_desc" placeholder="(tuỳ chọn)" style="width:100%"/></div>
      <button class="btn" id="fp_add" style="margin-top:10px">+ Tạo sản phẩm</button>` : ""}
      <input class="searchbox" data-tbl="t_fp" placeholder="Tìm theo mã, tên, loại sản phẩm..." style="margin-top:10px"/>
      <div class="tablewrap" style="margin-top:12px"><table id="t_fp">
        <thead><tr><th>Mã</th><th>Tên</th><th>ĐVT</th><th>Loại đơn vị</th><th>SL/1 đơn vị</th><th>Loại sản phẩm</th><th>Dịch bia gốc</th><th>Mô tả</th>${canManage ? "<th></th>" : ""}</tr></thead>
        <tbody>${finishedProducts.map(fp => { const prod = products.find(p => p.product_id === fp.product_id); return `<tr>
          <td><code class="k">${esc(fp.code)}</code></td><td>${esc(fp.name)}</td><td>${esc(fp.uom)}</td>
          <td>${fp.unit_type === "keg" ? "Keg" : "Vỉ"}</td>
          <td>${fp.pack_size}</td>
          <td class="muted">${esc(fp.category || "—")}</td>
          <td class="muted">${prod ? esc(prod.code) : "—"}</td>
          <td class="muted">${esc(fp.description || "—")}</td>
          ${canManage ? `<td style="white-space:nowrap">
            <button class="btn sm sec" data-efp="${esc(fp.finished_product_id)}">Sửa</button>
            <button class="btn sm sec" data-efpdel="${esc(fp.finished_product_id)}">Xóa</button>
          </td>` : ""}</tr>`; }).join("") ||
          `<tr><td colspan="${canManage ? 9 : 8}" class="muted">Chưa có sản phẩm nào.</td></tr>`}</tbody>
      </table></div>
    </div>

    <div class="panel"><h2>📋 Danh mục chỉ tiêu chất lượng <span class="muted">(${qcParams.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Chỉ tiêu dùng chung, tạo 1 lần ở đây rồi gán vào từng nhóm ("Chỉ tiêu trong nhóm" ở bảng bên dưới).</div>
      ${noPerm}
      ${canManage ? `<div class="row">
        <div class="field"><label>Mã CT</label><input id="qp_code" placeholder="DO_AM"/></div>
        <div class="field"><label>Tên chỉ tiêu</label><input id="qp_name" placeholder="Độ ẩm"/></div>
        <div class="field"><label>Kiểu ghi nhận</label><select id="qp_value_type">
          <option value="numeric">Nhập số (so target/USL/LSL)</option>
          <option value="pass_fail">Đạt / Không đạt</option></select></div>
        <div class="field"><label>ĐVT</label><input id="qp_unit" placeholder="%" style="width:80px"/></div>
        <div class="field"><label>Phương pháp thử</label><input id="qp_method" placeholder="(tuỳ chọn)"/></div>
        <button class="btn" id="qp_add" style="align-self:flex-end">+ Tạo chỉ tiêu</button>
      </div>` : ""}
      <input class="searchbox" data-tbl="t_qcparam" placeholder="Tìm mã/tên chỉ tiêu..." style="margin-top:10px"/>
      <div class="tablewrap" style="margin-top:8px"><table id="t_qcparam">
        <thead><tr><th>Mã CT</th><th>Tên</th><th>Kiểu</th><th>ĐVT</th><th>Phương pháp thử</th><th>Trạng thái</th>${canManage ? "<th></th>" : ""}</tr></thead>
        <tbody>${qcParams.map(p => `<tr>
          <td><code class="k">${esc(p.code)}</code></td><td>${esc(p.name)}</td>
          <td class="muted">${p.value_type === "pass_fail" ? "Đạt/Không đạt" : "Số"}</td>
          <td class="muted">${esc(p.unit || "—")}</td><td class="muted">${esc(p.method || "—")}</td>
          <td>${badge(p.active ? "available" : "obsolete")}${p.active ? "hoạt động" : "ngừng"}</td>
          ${canManage ? `<td style="white-space:nowrap"><button class="btn sm sec" data-qpedit="${esc(p.param_id)}">Sửa</button>
            <button class="btn sm sec" data-qptoggle="${esc(p.param_id)}">${p.active ? "Ngừng" : "Kích hoạt"}</button></td>` : ""}</tr>`).join("") ||
          `<tr><td colspan="${canManage ? 7 : 6}" class="muted">Chưa có chỉ tiêu nào.</td></tr>`}</tbody>
      </table></div>
    </div>

    <div class="panel"><h2>🧪 Nhóm chỉ tiêu chất lượng <span class="muted">(${qcGroups.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Chỉ nguyên liệu được gán nhóm chỉ tiêu (nút "Chỉ tiêu QC" ở bảng Vật tư)
        mới bị bắt buộc khai báo &amp; duyệt chỉ tiêu trước khi nhập kho nhà máy chính thức.</div>
      ${noPerm}
      ${canManage ? `<div class="row">
        <div class="field"><label>Mã nhóm</label><input id="qg_code" placeholder="MALT-ANH-BAO"/></div>
        <div class="field"><label>Tên nhóm</label><input id="qg_name" placeholder="Chỉ tiêu Malt Anh (bao)"/></div>
        <div class="field"><label>Ghi chú</label><input id="qg_note" placeholder="(tuỳ chọn)"/></div>
        <button class="btn" id="qg_add" style="align-self:flex-end">+ Tạo nhóm</button>
      </div>` : ""}
      <input class="searchbox" data-tbl="t_qcgroups" placeholder="Tìm mã/tên nhóm chỉ tiêu..." style="margin-top:10px"/>
      <div class="tablewrap" style="margin-top:8px"><table id="t_qcgroups">
        <thead><tr><th>Mã</th><th>Tên</th><th>Ghi chú</th><th>Trạng thái</th>${canManage ? "<th></th>" : ""}</tr></thead>
        <tbody>${qcGroups.map(g => `<tr>
          <td><code class="k">${esc(g.code)}</code></td><td>${esc(g.name)}</td>
          <td class="muted">${esc(g.note || "—")}</td>
          <td>${badge(g.active ? "available" : "obsolete")}${g.active ? "hoạt động" : "ngừng"}</td>
          ${canManage ? `<td style="white-space:nowrap"><button class="btn sm sec" data-qgi="${esc(g.group_id)}">Chỉ tiêu trong nhóm</button>
            <button class="btn sm sec" data-qgedit="${esc(g.group_id)}">Sửa</button>
            <button class="btn sm sec" data-qgdel="${esc(g.group_id)}">Xóa</button></td>` : ""}</tr>`).join("")}</tbody>
      </table></div>
    </div>

    <div class="panel"><h2>🍺 Nhóm chỉ tiêu theo công đoạn sản xuất <span class="muted">(${stageGroups.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Gán nhóm chỉ tiêu (ở bảng trên) cho một công đoạn — mẻ nấu, lên men chính/phụ, lọc,
        thành phẩm — để bắt buộc khai báo trước khi được duyệt/xuất tiếp. Nấu/Lên men tra theo <b>Dịch bia</b> (phân biệt cả độ oP);
        Lọc/Thành phẩm tra theo <b>Loại bia</b> (thương hiệu, VD Sapphire — không phân biệt oP, vì lọc phối có thể gộp nhiều
        Dịch bia cùng 1 Loại bia). Để trống Loại bia/Sản phẩm = áp dụng cho mọi loại bia/sản phẩm thuộc Loại bia đó — cùng 1 Loại bia
        vẫn có thể cần chỉ tiêu Lọc/Thành phẩm khác nhau theo hình thức đóng gói (VD Legend chai khác Legend tươi): chọn thêm
        <b>Sản phẩm</b> ở đây để gán riêng, nhóm gán riêng theo Sản phẩm luôn thắng nhóm áp dụng chung. Với Lọc, mỗi mẻ lọc biết mình
        thuộc Sản phẩm nào là do khai báo 1 lần ở Lệnh lọc (mục Lệnh SX) rồi tự kế thừa xuống — không cần chọn lại. Công đoạn "Chiết"
        dùng chung chỉ tiêu với "Thành phẩm" (không có mục riêng trong danh sách Công đoạn bên dưới).</div>
      ${noPerm}
      ${canManage ? `<div class="row">
        <div class="field"><label>Công đoạn</label><select id="sg_stage">${Object.entries(STAGE_LABELS).filter(([k]) => k !== "chiet").map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></div>
        <div class="field" id="sg_product_wrap"><label>Dịch bia (tuỳ chọn)</label><select id="sg_product"><option value="">(Mọi dịch bia)</option>${products.map(p => `<option value="${p.product_id}">${esc(p.code)}</option>`).join("")}</select></div>
        <div class="field" id="sg_beertype_wrap" style="display:none"><label>Loại bia (tuỳ chọn)</label><select id="sg_beertype"><option value="">(Mọi loại bia)</option>${beerTypes.map(bt => `<option value="${bt.beer_type_id}">${esc(bt.code)} — ${esc(bt.name)}</option>`).join("")}</select></div>
        <div class="field" id="sg_fproduct_wrap" style="display:none"><label>Sản phẩm (tuỳ chọn)</label><select id="sg_fproduct"><option value="">(Mọi sản phẩm)</option>${finishedProducts.map(fp => `<option value="${fp.finished_product_id}">${esc(fp.code)} — ${esc(fp.name)}</option>`).join("")}</select></div>
        <div class="field" style="min-width:200px"><label>Nhóm chỉ tiêu</label><select id="sg_group">${qcGroups.map(g => `<option value="${g.group_id}">${esc(g.code)} — ${esc(g.name)}</option>`).join("") ||
          "<option value=''>(chưa có nhóm nào — tạo ở bảng trên)</option>"}</select></div>
        <div class="field"><label>Bắt buộc</label><input id="sg_mandatory" type="checkbox" checked/></div>
        <button class="btn" id="sg_add" style="align-self:flex-end">+ Gán</button>
      </div>` : ""}
      <input class="searchbox" data-tbl="t_stagegroups" placeholder="Tìm công đoạn/dịch bia/nhóm chỉ tiêu..." style="margin-top:10px"/>
      <div class="tablewrap" style="margin-top:8px"><table id="t_stagegroups">
        <thead><tr><th>Công đoạn</th><th>Dịch bia</th><th>Loại bia</th><th>Sản phẩm</th><th>Nhóm chỉ tiêu</th><th>Bắt buộc</th>${canManage ? "<th></th>" : ""}</tr></thead>
        <tbody>${stageGroups.map(sg => { const prod = products.find(p => p.product_id === sg.product_id);
          const bt = beerTypes.find(x => x.beer_type_id === sg.beer_type_id);
          const fprod = finishedProducts.find(fp => fp.finished_product_id === sg.finished_product_id); return `<tr>
          <td>${esc(STAGE_LABELS[sg.stage] || sg.stage)}</td>
          <td class="muted">${prod ? esc(prod.code) : "—"}</td>
          <td class="muted">${bt ? esc(bt.name) : "—"}</td>
          <td class="muted">${fprod ? `<code class="k">${esc(fprod.code)}</code> ${esc(fprod.name)}` : "(Mọi sản phẩm)"}</td>
          <td><code class="k">${esc(sg.group_code || "—")}</code> ${esc(sg.group_name || "")}</td>
          <td>${sg.mandatory ? "Có" : "Không"}</td>
          ${canManage ? `<td style="white-space:nowrap"><button class="btn sm sec" data-sgedit="${esc(sg.link_id)}">Sửa</button>
            <button class="btn sm sec" data-sgdel="${esc(sg.link_id)}">Xóa gán</button></td>` : ""}</tr>`; }).join("") ||
          `<tr><td colspan="${canManage ? 7 : 6}" class="muted">Chưa gán nhóm chỉ tiêu cho công đoạn nào.</td></tr>`}</tbody>
      </table></div>
    </div>

    ${lineSectionHtml("line", "🏭 Dây chuyền sản xuất", plines.filter(l => l.kind === "line" || l.kind === "brewhouse"), canManage, noPerm)}
    ${lineSectionHtml("tank", "🛢️ Tank lên men", plines.filter(l => l.kind === "tank"), canManage, noPerm)}
    ${lineSectionHtml("tank_bbt", "🧪 Tank thành phẩm (BBT)", plines.filter(l => l.kind === "tank_bbt"), canManage, noPerm)}

    <div class="panel"><h2>⚙️ Cài đặt vận hành</h2>
      <div class="muted" style="margin-bottom:6px">Ngưỡng dung sai thể tích (hl) cho phép nút "Làm rỗng" (tab Lọc, modal Tank) buộc tồn tank
        CCT/BBT về 0 — chỉ dùng khi tank vật lý đã cạn/chiết hết thật nhưng số liệu phần mềm còn lệch một khoảng nhỏ do hao hụt đo
        đạc. Nếu phần lệch vượt ngưỡng này, hệ thống sẽ chặn (báo lỗi) để tránh xoá nhầm sai lệch lớn do lỗi nhập liệu thật.</div>
      ${noPerm}
      <div class="row">
        <div class="field"><label>Ngưỡng làm rỗng CCT (hl)</label><input id="ops_cct_tol" type="number" step="any" value="${opsSettings.empty_cct_tolerance_hl}" ${canManage ? "" : "disabled"}/></div>
        <div class="field"><label>Ngưỡng làm rỗng BBT (hl)</label><input id="ops_bbt_tol" type="number" step="any" value="${opsSettings.empty_bbt_tolerance_hl}" ${canManage ? "" : "disabled"}/></div>
        ${canManage ? `<button class="btn" id="ops_save" style="align-self:flex-end">Lưu</button>` : ""}
      </div>
      ${opsSettings.updated_by ? `<div class="muted" style="font-size:12px;margin-top:6px">Cập nhật lần cuối: ${esc(opsSettings.updated_by)} · ${fmt(opsSettings.updated_at)}</div>` : ""}
    </div>`;

  wireSearch();
  wirePaginate("t_products", 10);
  wirePaginate("t_beertypes", 10);
  wirePaginate("t_materials", 10);
  wirePaginate("t_matgroups", 10);
  wirePaginate("t_qcparam", 10);
  wirePaginate("t_qcgroups", 10);
  wirePaginate("t_stagegroups", 10);
  wirePaginate("t_fp", 10);
  wirePaginate("t_suppliers", 10);
  if (canManage) {
    $("pr_add").onclick = () => guard(async () => {
      await POST("/products", { code: $("pr_code").value.trim(), name: $("pr_name").value.trim(),
        uom: $("pr_uom").value.trim() || "L", description: $("pr_desc").value.trim() || null,
        ferment_days_std: $("pr_ferment_days").value === "" ? null : parseInt($("pr_ferment_days").value, 10),
        beer_type_id: $("pr_beertype").value || null });
      toast("Đã tạo dịch bia"); render("master");
    });
    if ($("bt_add")) $("bt_add").onclick = () => guard(async () => {
      await POST("/beer-types", { code: $("bt_code").value.trim(), name: $("bt_name").value.trim(),
        note: $("bt_note").value.trim() || null });
      toast("Đã tạo Loại bia"); render("master");
    });
    if ($("ops_save")) $("ops_save").onclick = () => guard(async () => {
      await PUT("/ops-settings", {
        empty_cct_tolerance_hl: parseFloat($("ops_cct_tol").value) || 0,
        empty_bbt_tolerance_hl: parseFloat($("ops_bbt_tol").value) || 0,
        aging_caution_days: opsSettings.aging_caution_days ?? 30,
        aging_warning_days: opsSettings.aging_warning_days ?? 60,
        aging_critical_days: opsSettings.aging_critical_days ?? 90,
      });
      toast("Đã lưu cài đặt vận hành"); render("master");
    });
    document.querySelectorAll("[data-ebt]").forEach(b => b.onclick = () => {
      const bt = beerTypes.find(x => x.beer_type_id === b.dataset.ebt);
      modal(`<h3>Sửa Loại bia</h3>
        <div class="field"><label>Mã</label><input id="ebt_code" value="${esc(bt.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="ebt_name" value="${esc(bt.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>Ghi chú</label><input id="ebt_note" value="${esc(bt.note || "")}"/></div>
        <button class="btn" id="ebt_save" style="margin-top:12px">Lưu</button>`);
      $("ebt_save").onclick = () => guard(async () => {
        await PUT(`/beer-types/${bt.beer_type_id}`, { code: $("ebt_code").value.trim(),
          name: $("ebt_name").value.trim(), note: $("ebt_note").value.trim() || null });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-btdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa Loại bia này? Không thể hoàn tác.")) return;
      await DELETE(`/beer-types/${b.dataset.btdel}`);
      toast("Đã xóa Loại bia"); render("master");
    }));
    if ($("sp_add")) $("sp_add").onclick = () => guard(async () => {
      await POST("/suppliers", { code: $("sp_code").value.trim(), name: $("sp_name").value.trim(),
        address: $("sp_address").value.trim() || null, contact: $("sp_contact").value.trim() || null });
      toast("Đã tạo nhà cung cấp"); render("master");
    });
    document.querySelectorAll("[data-esp]").forEach(b => b.onclick = () => {
      const sp = suppliers.find(x => x.supplier_id === b.dataset.esp);
      modal(`<h3>Sửa nhà cung cấp</h3>
        <div class="field"><label>Mã</label><input id="esp_code" value="${esc(sp.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="esp_name" value="${esc(sp.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>Địa chỉ</label><input id="esp_address" value="${esc(sp.address || "")}"/></div>
        <div class="field" style="margin-top:8px"><label>Liên hệ</label><input id="esp_contact" value="${esc(sp.contact || "")}"/></div>
        <button class="btn" id="esp_save" style="margin-top:12px">Lưu</button>`);
      $("esp_save").onclick = () => guard(async () => {
        await PUT(`/suppliers/${sp.supplier_id}`, { code: $("esp_code").value.trim(), name: $("esp_name").value.trim(),
          address: $("esp_address").value.trim() || null, contact: $("esp_contact").value.trim() || null });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-espdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa nhà cung cấp này? Không thể hoàn tác.")) return;
      await DELETE(`/suppliers/${b.dataset.espdel}`);
      toast("Đã xóa nhà cung cấp"); render("master");
    }));
    if ($("mg_add")) $("mg_add").onclick = () => guard(async () => {
      const code = $("mg_code").value.trim(), name = $("mg_name").value.trim();
      if (!code || !name) throw new Error("Nhập đủ Mã nhóm và Tên nhóm.");
      await POST("/material-groups", { code, name, is_packaging: $("mg_packaging").checked });
      toast("Đã tạo nhóm vật tư"); render("master");
    });
    document.querySelectorAll("[data-emg]").forEach(b => b.onclick = () => {
      const g = materialGroups.find(x => x.group_id === b.dataset.emg);
      modal(`<h3>Sửa nhóm vật tư</h3>
        <div class="field"><label>Mã</label><input id="emg_code" value="${esc(g.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="emg_name" value="${esc(g.name)}"/></div>
        <div class="field" style="margin-top:8px"><label><input type="checkbox" id="emg_active" ${g.active ? "checked" : ""}/> Đang dùng (hiện trong danh sách chọn khi tạo vật tư)</label></div>
        <div class="field" style="margin-top:8px"><label><input type="checkbox" id="emg_packaging" ${g.is_packaging ? "checked" : ""}/> Bao bì tiêu hao (hiện ở báo cáo lô bao bì, tab Bao bì)</label></div>
        <button class="btn" id="emg_save" style="margin-top:12px">Lưu</button>`);
      $("emg_save").onclick = () => guard(async () => {
        await PUT(`/material-groups/${g.group_id}`, { code: $("emg_code").value.trim(),
          name: $("emg_name").value.trim(), active: $("emg_active").checked,
          is_packaging: $("emg_packaging").checked });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-mgdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa nhóm vật tư này? Không thể hoàn tác.")) return;
      await DELETE(`/material-groups/${b.dataset.mgdel}`);
      toast("Đã xóa nhóm vật tư"); render("master");
    }));
    $("mt_add").onclick = () => guard(async () => {
      await POST("/materials", { code: $("mt_code").value.trim(), name: $("mt_name").value.trim(),
        uom: $("mt_uom").value.trim() || "kg", category: $("mt_cat").value,
        stock_min: $("mt_stockmin").value === "" ? null : parseFloat($("mt_stockmin").value) });
      toast("Đã tạo vật tư"); render("master");
    });
    if ($("ln_line_add")) $("ln_line_add").onclick = () => guard(async () => {
      await POST("/lines", { code: $("ln_line_code").value.trim(), name: $("ln_line_name").value.trim(),
        kind: $("ln_line_kind").value, area: $("ln_line_area").value.trim() || null,
        ideal_rate_per_min: parseFloat($("ln_line_rate").value) || 0,
        capacity_uom: $("ln_line_rate_uom").value.trim() || null });
      toast("Đã thêm dây chuyền"); render("master");
    });
    ["tank", "tank_bbt"].forEach(k => {
      const el = $(`ln_${k}_add`);
      if (el) el.onclick = () => guard(async () => {
        await POST("/lines", { code: $(`ln_${k}_code`).value.trim(), name: $(`ln_${k}_name`).value.trim(),
          kind: k, area: $(`ln_${k}_area`).value.trim() || null,
          volume: parseFloat($(`ln_${k}_vol`).value) || null,
          volume_uom: $(`ln_${k}_vol_uom`).value.trim() || null });
        toast("Đã thêm tank"); render("master");
      });
    });
    document.querySelectorAll("[data-ltoggle]").forEach(b => b.onclick = () => guard(async () => {
      await POST(`/lines/${b.dataset.ltoggle}/toggle`); toast("Đã đổi trạng thái"); render("master");
    }));
    document.querySelectorAll("[data-ldel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa mục này? Không thể hoàn tác.")) return;
      await DELETE(`/lines/${b.dataset.ldel}`);
      toast("Đã xóa"); render("master");
    }));
    document.querySelectorAll("[data-ledit]").forEach(b => b.onclick = () => {
      const [kind, lineId] = b.dataset.ledit.split("|");
      const l = plines.find(x => x.line_id === lineId);
      const isLine = kind === "line";
      modal(`<h3>Sửa ${isLine ? "dây chuyền" : "tank"}</h3>
        <div class="field"><label>Tên</label><input id="le_name" value="${esc(l.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>Khu vực</label><input id="le_area" value="${esc(l.area || "")}"/></div>
        ${isLine ? `
        <div class="field" style="margin-top:8px"><label>Công suất</label><input id="le_rate" type="number" value="${l.ideal_rate_per_min ?? ""}"/></div>
        <div class="field" style="margin-top:8px"><label>Đơn vị công suất</label><input id="le_rate_uom" value="${esc(l.capacity_uom || "")}"/></div>` : `
        <div class="field" style="margin-top:8px"><label>Thể tích</label><input id="le_vol" type="number" value="${l.volume ?? ""}"/></div>
        <div class="field" style="margin-top:8px"><label>Đơn vị thể tích</label><input id="le_vol_uom" value="${esc(l.volume_uom || "")}"/></div>`}
        <button class="btn" id="le_save" style="margin-top:12px">Lưu</button>`);
      $("le_save").onclick = () => guard(async () => {
        const payload = { name: $("le_name").value.trim(), area: $("le_area").value.trim() || null };
        if (isLine) {
          payload.ideal_rate_per_min = parseFloat($("le_rate").value) || 0;
          payload.capacity_uom = $("le_rate_uom").value.trim() || null;
        } else {
          payload.volume = parseFloat($("le_vol").value) || null;
          payload.volume_uom = $("le_vol_uom").value.trim() || null;
        }
        await PUT(`/lines/${lineId}`, payload);
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-ep]").forEach(b => b.onclick = () => {
      const p = products.find(x => x.product_id === b.dataset.ep);
      modal(`<h3>Sửa dịch bia</h3>
        <div class="field"><label>Mã</label><input id="ep_code" value="${esc(p.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="ep_name" value="${esc(p.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>ĐVT</label><input id="ep_uom" value="${esc(p.uom)}"/></div>
        <div class="field" style="margin-top:8px"><label>Số ngày lên men</label><input id="ep_ferment_days" type="number" value="${p.ferment_days_std ?? ""}"/></div>
        <div class="field" style="margin-top:8px"><label>Loại bia</label><select id="ep_beertype"><option value="">(chưa gán)</option>${beerTypes.map(bt => `<option value="${bt.beer_type_id}" ${bt.beer_type_id === p.beer_type_id ? "selected" : ""}>${esc(bt.code)} — ${esc(bt.name)}</option>`).join("")}</select></div>
        <div class="field" style="margin-top:8px"><label>Mô tả</label><input id="ep_desc" value="${esc(p.description || "")}"/></div>
        <button class="btn" id="ep_save" style="margin-top:12px">Lưu</button>`);
      $("ep_save").onclick = () => guard(async () => {
        await PUT(`/products/${p.product_id}`, { code: $("ep_code").value.trim(), name: $("ep_name").value.trim(),
          uom: $("ep_uom").value.trim(), description: $("ep_desc").value.trim() || null,
          ferment_days_std: $("ep_ferment_days").value === "" ? null : parseInt($("ep_ferment_days").value, 10),
          beer_type_id: $("ep_beertype").value || null });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-epdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa dịch bia này? Không thể hoàn tác.")) return;
      await DELETE(`/products/${b.dataset.epdel}`);
      toast("Đã xóa dịch bia"); render("master");
    }));
    document.querySelectorAll("[data-brewspec]").forEach(b => b.onclick = () => guard(async () => {
      const p = products.find(x => x.product_id === b.dataset.brewspec);
      openBrewSpecModal(p);
    }));
    if ($("fp_add")) $("fp_add").onclick = () => guard(async () => {
      await POST("/finished-products", { code: $("fp_code").value.trim(), name: $("fp_name").value.trim(),
        uom: $("fp_uom").value.trim() || "L", product_id: $("fp_product").value || null,
        unit_type: $("fp_unittype").value, pack_size: parseInt($("fp_pack").value, 10) || 24,
        category: $("fp_cat").value || null, description: $("fp_desc").value.trim() || null });
      toast("Đã tạo sản phẩm"); render("master");
    });
    document.querySelectorAll("[data-efp]").forEach(b => b.onclick = () => {
      const fp = finishedProducts.find(x => x.finished_product_id === b.dataset.efp);
      modal(`<h3>Sửa sản phẩm</h3>
        <div class="field"><label>Mã</label><input id="efp_code" value="${esc(fp.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="efp_name" value="${esc(fp.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>ĐVT</label><input id="efp_uom" value="${esc(fp.uom)}"/></div>
        <div class="field" style="margin-top:8px"><label>Loại đơn vị tồn kho</label><select id="efp_unittype">
          <option value="vi" ${fp.unit_type === "vi" ? "selected" : ""}>Vỉ</option>
          <option value="keg" ${fp.unit_type === "keg" ? "selected" : ""}>Keg</option></select></div>
        <div class="field" style="margin-top:8px"><label>SL/1 đơn vị</label><input id="efp_pack" type="number" value="${fp.pack_size}"/></div>
        <div class="field" style="margin-top:8px"><label>Loại sản phẩm</label><select id="efp_cat"><option value="">(không chọn)</option>${fpCats.map(c => `<option ${c === fp.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></div>
        <div class="field" style="margin-top:8px"><label>Dịch bia gốc</label><select id="efp_product"><option value="">(không chọn)</option>${products.map(p => `<option value="${p.product_id}" ${p.product_id === fp.product_id ? "selected" : ""}>${esc(p.code)}</option>`).join("")}</select></div>
        <div class="field" style="margin-top:8px"><label>Mô tả</label><input id="efp_desc" value="${esc(fp.description || "")}"/></div>
        <button class="btn" id="efp_save" style="margin-top:12px">Lưu</button>`);
      $("efp_save").onclick = () => guard(async () => {
        await PUT(`/finished-products/${fp.finished_product_id}`, { code: $("efp_code").value.trim(),
          name: $("efp_name").value.trim(), uom: $("efp_uom").value.trim(),
          product_id: $("efp_product").value || null, unit_type: $("efp_unittype").value,
          pack_size: parseInt($("efp_pack").value, 10) || 24,
          category: $("efp_cat").value || null, description: $("efp_desc").value.trim() || null });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-efpdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa sản phẩm này? Không thể hoàn tác.")) return;
      await DELETE(`/finished-products/${b.dataset.efpdel}`);
      toast("Đã xóa sản phẩm"); render("master");
    }));
    document.querySelectorAll("[data-em]").forEach(b => b.onclick = () => {
      const m = materials.find(x => x.material_id === b.dataset.em);
      modal(`<h3>Sửa vật tư</h3>
        <div class="field"><label>Mã</label><input id="em_code" value="${esc(m.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="em_name" value="${esc(m.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>ĐVT</label><input id="em_uom" value="${esc(m.uom)}"/></div>
        <div class="field" style="margin-top:8px"><label>Nhóm</label><select id="em_cat">${materialGroups.map(g => `<option value="${esc(g.code)}" ${g.code === m.category ? "selected" : ""}>${esc(g.name)}${g.active ? "" : " (đã ẩn)"}</option>`).join("") ||
          "<option value=''>(chưa có nhóm)</option>"}</select></div>
        <div class="field" style="margin-top:8px"><label>Tồn tối thiểu</label><input id="em_stockmin" type="number" step="0.01" value="${m.stock_min ?? ""}" placeholder="(tuỳ chọn)"/></div>
        <button class="btn" id="em_save" style="margin-top:12px">Lưu</button>`);
      $("em_save").onclick = () => guard(async () => {
        await PUT(`/materials/${m.material_id}`, { code: $("em_code").value.trim(), name: $("em_name").value.trim(),
          uom: $("em_uom").value.trim(), category: $("em_cat").value || null,
          stock_min: $("em_stockmin").value === "" ? null : parseFloat($("em_stockmin").value) });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-emdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa vật tư này? Không thể hoàn tác.")) return;
      await DELETE(`/materials/${b.dataset.emdel}`);
      toast("Đã xóa vật tư"); render("master");
    }));

    if ($("qp_add")) $("qp_add").onclick = () => guard(async () => {
      const code = $("qp_code").value.trim(), name = $("qp_name").value.trim();
      if (!code || !name) throw new Error("Nhập đủ Mã CT và Tên chỉ tiêu.");
      await POST("/qc/parameters", { code, name, value_type: $("qp_value_type").value,
        unit: $("qp_unit").value.trim() || null, method: $("qp_method").value.trim() || null });
      toast("Đã tạo chỉ tiêu mới"); render("master");
    });
    document.querySelectorAll("[data-qpedit]").forEach(b => b.onclick = () => {
      const p = qcParams.find(x => x.param_id === b.dataset.qpedit);
      modal(`<h3>Sửa chỉ tiêu — ${esc(p.code)}</h3>
        <div class="field"><label>Mã CT</label><input id="qpe_code" value="${esc(p.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên chỉ tiêu</label><input id="qpe_name" value="${esc(p.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>Kiểu ghi nhận</label><select id="qpe_value_type">
          <option value="numeric" ${p.value_type !== "pass_fail" ? "selected" : ""}>Nhập số (so target/USL/LSL)</option>
          <option value="pass_fail" ${p.value_type === "pass_fail" ? "selected" : ""}>Đạt / Không đạt</option></select></div>
        <div class="field" style="margin-top:8px"><label>ĐVT</label><input id="qpe_unit" value="${esc(p.unit || "")}"/></div>
        <div class="field" style="margin-top:8px"><label>Phương pháp thử</label><input id="qpe_method" value="${esc(p.method || "")}"/></div>
        <button class="btn" id="qpe_save" style="margin-top:12px">Lưu</button>`);
      $("qpe_save").onclick = () => guard(async () => {
        const code = $("qpe_code").value.trim(), name = $("qpe_name").value.trim();
        if (!code || !name) throw new Error("Nhập đủ Mã CT và Tên chỉ tiêu.");
        await PUT(`/qc/parameters/${p.param_id}`, { code, name, value_type: $("qpe_value_type").value,
          unit: $("qpe_unit").value.trim() || null, method: $("qpe_method").value.trim() || null,
          target: p.target, usl: p.usl, lsl: p.lsl, stage: p.stage, note: p.note, active: p.active });
        closeModal(); toast("Đã lưu chỉ tiêu"); render("master");
      });
    });
    document.querySelectorAll("[data-qptoggle]").forEach(b => b.onclick = () => guard(async () => {
      const p = qcParams.find(x => x.param_id === b.dataset.qptoggle);
      await PUT(`/qc/parameters/${p.param_id}`, { code: p.code, name: p.name, unit: p.unit,
        target: p.target, usl: p.usl, lsl: p.lsl, stage: p.stage, method: p.method, note: p.note,
        value_type: p.value_type, active: !p.active });
      toast(p.active ? "Đã ngừng chỉ tiêu" : "Đã kích hoạt lại chỉ tiêu"); render("master");
    }));

    $("qg_add").onclick = () => guard(async () => {
      const code = $("qg_code").value.trim(), name = $("qg_name").value.trim();
      if (!code || !name) throw new Error("Nhập đủ Mã nhóm và Tên nhóm.");
      await POST("/qc/groups", { code, name, note: $("qg_note").value.trim() || null });
      toast("Đã tạo nhóm chỉ tiêu"); render("master");
    });

    document.querySelectorAll("[data-qgi]").forEach(b => b.onclick = () => {
      const g = qcGroups.find(x => x.group_id === b.dataset.qgi);
      openQcGroupItemsModal(g);
    });
    document.querySelectorAll("[data-qgedit]").forEach(b => b.onclick = () => {
      const g = qcGroups.find(x => x.group_id === b.dataset.qgedit);
      modal(`<h3>Sửa nhóm chỉ tiêu</h3>
        <div class="field"><label>Mã</label><input id="qge_code" value="${esc(g.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="qge_name" value="${esc(g.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>Ghi chú</label><input id="qge_note" value="${esc(g.note || "")}"/></div>
        <button class="btn" id="qge_save" style="margin-top:12px">Lưu</button>`);
      $("qge_save").onclick = () => guard(async () => {
        const code = $("qge_code").value.trim(), name = $("qge_name").value.trim();
        if (!code || !name) throw new Error("Nhập đủ Mã nhóm và Tên nhóm.");
        await PUT(`/qc/groups/${g.group_id}`, { code, name, note: $("qge_note").value.trim() || null });
        closeModal(); toast("Đã cập nhật nhóm chỉ tiêu"); render("master");
      });
    });
    document.querySelectorAll("[data-qgdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa nhóm chỉ tiêu này? Không thể hoàn tác.")) return;
      await DELETE(`/qc/groups/${b.dataset.qgdel}`);
      toast("Đã xóa nhóm chỉ tiêu"); render("master");
    }));
    document.querySelectorAll("[data-mqc]").forEach(b => b.onclick = () => {
      const m = materials.find(x => x.material_id === b.dataset.mqc);
      openMaterialQcModal(m);
    });

    if ($("sg_stage")) {
      const toggleSgScope = () => {
        const isProductScoped = PRODUCT_SCOPED_STAGES.includes($("sg_stage").value);
        $("sg_product_wrap").style.display = isProductScoped ? "" : "none";
        $("sg_beertype_wrap").style.display = isProductScoped ? "none" : "";
        // Sản phẩm (SKU, tuỳ chọn) có ý nghĩa ở Lọc và Thành phẩm — Lọc khai báo Sản phẩm
        // đích ở Lệnh lọc (kế thừa xuống mẻ lọc, xem FilterOrder.finished_product_id) vì
        // cùng 1 Loại bia vẫn có thể cần chỉ tiêu Lọc khác nhau theo hình thức đóng gói.
        $("sg_fproduct_wrap").style.display = SKU_SCOPED_STAGES.includes($("sg_stage").value) ? "" : "none";
      };
      $("sg_stage").onchange = toggleSgScope;
      toggleSgScope();
    }
    if ($("sg_add")) $("sg_add").onclick = () => guard(async () => {
      const groupId = $("sg_group").value;
      if (!groupId) throw new Error("Chưa có nhóm chỉ tiêu nào để gán — tạo nhóm ở bảng trên trước.");
      const stage = $("sg_stage").value;
      const isProductScoped = PRODUCT_SCOPED_STAGES.includes(stage);
      await POST("/qc/stage-groups", { stage, group_id: groupId,
        product_id: isProductScoped ? ($("sg_product").value || null) : null,
        beer_type_id: isProductScoped ? null : ($("sg_beertype").value || null),
        finished_product_id: SKU_SCOPED_STAGES.includes(stage) ? ($("sg_fproduct").value || null) : null,
        mandatory: $("sg_mandatory").checked });
      toast("Đã gán nhóm chỉ tiêu cho công đoạn"); render("master");
    });
    document.querySelectorAll("[data-sgedit]").forEach(b => b.onclick = () => {
      const sg = stageGroups.find(x => x.link_id === b.dataset.sgedit);
      const stageOptions = Object.entries(STAGE_LABELS).filter(([k]) => k !== "chiet")
        .map(([k, v]) => `<option value="${k}" ${k === sg.stage ? "selected" : ""}>${esc(v)}</option>`).join("");
      const productOptions = `<option value="">(Mọi dịch bia)</option>` + products.map(p =>
        `<option value="${p.product_id}" ${p.product_id === sg.product_id ? "selected" : ""}>${esc(p.code)}</option>`).join("");
      const beerTypeOptions = `<option value="">(Mọi loại bia)</option>` + beerTypes.map(bt =>
        `<option value="${bt.beer_type_id}" ${bt.beer_type_id === sg.beer_type_id ? "selected" : ""}>${esc(bt.code)} — ${esc(bt.name)}</option>`).join("");
      const fproductOptions = `<option value="">(Mọi sản phẩm)</option>` + finishedProducts.map(fp =>
        `<option value="${fp.finished_product_id}" ${fp.finished_product_id === sg.finished_product_id ? "selected" : ""}>${esc(fp.code)} — ${esc(fp.name)}</option>`).join("");
      const groupOptions = qcGroups.map(g => `<option value="${g.group_id}" ${g.group_id === sg.group_id ? "selected" : ""}>${esc(g.code)} — ${esc(g.name)}</option>`).join("");
      modal(`<h3>Sửa gán nhóm chỉ tiêu công đoạn</h3>
        <div class="field"><label>Công đoạn</label><select id="sge_stage">${stageOptions}</select></div>
        <div class="field" id="sge_product_wrap" style="margin-top:8px"><label>Dịch bia (tuỳ chọn)</label><select id="sge_product">${productOptions}</select></div>
        <div class="field" id="sge_beertype_wrap" style="margin-top:8px"><label>Loại bia (tuỳ chọn)</label><select id="sge_beertype">${beerTypeOptions}</select></div>
        <div class="field" id="sge_fproduct_wrap" style="margin-top:8px"><label>Sản phẩm (tuỳ chọn)</label><select id="sge_fproduct">${fproductOptions}</select></div>
        <div class="field" style="margin-top:8px"><label>Nhóm chỉ tiêu</label><select id="sge_group">${groupOptions}</select></div>
        <div class="field" style="margin-top:8px"><label>Bắt buộc</label><input id="sge_mandatory" type="checkbox" ${sg.mandatory ? "checked" : ""}/></div>
        <button class="btn" id="sge_save" style="margin-top:12px">Lưu</button>`);
      const toggleSgeScope = () => {
        const isProductScoped = PRODUCT_SCOPED_STAGES.includes($("sge_stage").value);
        $("sge_product_wrap").style.display = isProductScoped ? "" : "none";
        $("sge_beertype_wrap").style.display = isProductScoped ? "none" : "";
        $("sge_fproduct_wrap").style.display = SKU_SCOPED_STAGES.includes($("sge_stage").value) ? "" : "none";
      };
      $("sge_stage").onchange = toggleSgeScope;
      toggleSgeScope();
      $("sge_save").onclick = () => guard(async () => {
        const groupId = $("sge_group").value;
        if (!groupId) throw new Error("Chưa có nhóm chỉ tiêu nào để gán — tạo nhóm ở bảng trên trước.");
        const stage = $("sge_stage").value;
        const isProductScoped = PRODUCT_SCOPED_STAGES.includes(stage);
        await PUT(`/qc/stage-groups/${sg.link_id}`, { stage, group_id: groupId,
          product_id: isProductScoped ? ($("sge_product").value || null) : null,
          beer_type_id: isProductScoped ? null : ($("sge_beertype").value || null),
          finished_product_id: SKU_SCOPED_STAGES.includes(stage) ? ($("sge_fproduct").value || null) : null,
          mandatory: $("sge_mandatory").checked });
        closeModal(); toast("Đã cập nhật gán nhóm chỉ tiêu"); render("master");
      });
    });
    document.querySelectorAll("[data-sgdel]").forEach(b => b.onclick = () => guard(async () => {
      await DELETE(`/qc/stage-groups/${b.dataset.sgdel}`);
      toast("Đã xóa gán"); render("master");
    }));
  }

  // ---- Modal: chỉ tiêu trong 1 nhóm ----
  async function openQcGroupItemsModal(group) {
    const [items, allParams] = await Promise.all([GET(`/qc/groups/${group.group_id}/items`), GET("/qc/parameters?active_only=false")]);
    // Chỉ hiển thị chỉ tiêu NVL do người dùng tự tạo (stage rỗng) — không lẫn chỉ tiêu SPC quy trình sản xuất có sẵn (stage=nau/len_men/loc/chiet).
    const params = allParams.filter(p => !p.stage);
    const paramOpts = params.map(p => `<option value="${esc(p.param_id)}">${esc(p.code)} — ${esc(p.name)}${p.unit ? " (" + esc(p.unit) + ")" : ""}</option>`).join("");
    modal(`<h3>Chỉ tiêu trong nhóm — ${esc(group.name)}</h3>
      <div class="tablewrap"><table>
        <thead><tr><th>Mã CT</th><th>Tên</th><th>ĐVT</th><th>Min</th><th>Max</th><th>Bắt buộc</th><th></th></tr></thead>
        <tbody>${items.map(it => `<tr>
          <td><code class="k">${esc(it.param_code || "—")}</code></td><td>${esc(it.param_name || "—")}</td>
          <td>${esc(it.param_unit || "—")}</td>
          <td><input type="number" step="any" class="qgi-lsl-edit" data-item="${esc(it.item_id)}" value="${it.lsl_override ?? ""}" style="width:85px"/></td>
          <td><input type="number" step="any" class="qgi-usl-edit" data-item="${esc(it.item_id)}" value="${it.usl_override ?? ""}" style="width:85px"/></td>
          <td><input type="checkbox" class="qgi-mand-edit" data-item="${esc(it.item_id)}" ${it.mandatory ? "checked" : ""}/></td>
          <td style="white-space:nowrap"><button class="btn sm sec" data-saveitem="${esc(it.item_id)}">Lưu</button>
            <button class="btn sm sec" data-delitem="${esc(it.item_id)}">Xóa</button></td></tr>`).join("") ||
          `<tr><td colspan="7" class="muted">Chưa có chỉ tiêu nào trong nhóm.</td></tr>`}</tbody>
      </table></div>
      <h4 style="margin-top:14px">+ Thêm chỉ tiêu vào nhóm</h4>
      <div class="row">
        <div class="field" style="min-width:220px"><label>Chỉ tiêu</label><select id="qgi_param">${paramOpts || "<option value=''>(chưa có chỉ tiêu nào — tạo ở Danh mục chỉ tiêu chất lượng)</option>"}</select></div>
        <div class="field"><label>Min (LSL)</label><input id="qgi_lsl" type="number" step="any" style="width:90px"/></div>
        <div class="field"><label>Max (USL)</label><input id="qgi_usl" type="number" step="any" style="width:90px"/></div>
        <div class="field"><label>Bắt buộc</label><input id="qgi_mandatory" type="checkbox" checked/></div>
        <button class="btn" id="qgi_add" style="align-self:flex-end">Thêm</button>
      </div>
      <div class="muted" style="margin-top:10px">Chưa thấy chỉ tiêu cần dùng? Tạo mới ở panel "📋 Danh mục chỉ tiêu chất lượng" (phía trên bảng Nhóm chỉ tiêu), rồi quay lại đây để thêm vào nhóm.</div>`);

    $("qgi_add").onclick = () => guard(async () => {
      const paramId = $("qgi_param").value;
      if (!paramId) throw new Error("Chưa có chỉ tiêu để thêm — tạo chỉ tiêu mới trước.");
      await POST(`/qc/groups/${group.group_id}/items`, {
        param_id: paramId, mandatory: $("qgi_mandatory").checked,
        lsl_override: $("qgi_lsl").value === "" ? null : parseFloat($("qgi_lsl").value),
        usl_override: $("qgi_usl").value === "" ? null : parseFloat($("qgi_usl").value),
      });
      toast("Đã thêm chỉ tiêu vào nhóm"); openQcGroupItemsModal(group);
    });
    document.querySelectorAll("[data-saveitem]").forEach(b => b.onclick = () => guard(async () => {
      const itemId = b.dataset.saveitem;
      const it = items.find(x => x.item_id === itemId);
      const lsl = document.querySelector(`.qgi-lsl-edit[data-item="${itemId}"]`).value;
      const usl = document.querySelector(`.qgi-usl-edit[data-item="${itemId}"]`).value;
      const mandatory = document.querySelector(`.qgi-mand-edit[data-item="${itemId}"]`).checked;
      await PUT(`/qc/groups/${group.group_id}/items/${itemId}`, {
        param_id: it.param_id, seq: it.seq, mandatory,
        lsl_override: lsl === "" ? null : parseFloat(lsl),
        usl_override: usl === "" ? null : parseFloat(usl),
      });
      toast("Đã lưu chỉ tiêu"); openQcGroupItemsModal(group);
    }));
    document.querySelectorAll("[data-delitem]").forEach(b => b.onclick = () => guard(async () => {
      await api(`/qc/groups/${group.group_id}/items/${b.dataset.delitem}`, { method: "DELETE" });
      toast("Đã xóa chỉ tiêu khỏi nhóm"); openQcGroupItemsModal(group);
    }));
  }

  // ---- Modal: gán nhóm chỉ tiêu cho 1 nguyên liệu ----
  async function openMaterialQcModal(material) {
    const links = await GET(`/materials/${material.material_id}/qc-groups`);
    const linkedByGroup = Object.fromEntries(links.map(l => [l.group_id, l]));
    modal(`<h3>Chỉ tiêu QC — ${esc(material.name)}</h3>
      <div class="muted" style="margin-bottom:8px">Tích chọn nhóm chỉ tiêu mà nguyên liệu này bắt buộc phải khai báo &amp; duyệt trước khi nhập kho nhà máy.</div>
      <div class="tablewrap"><table>
        <thead><tr><th></th><th>Mã nhóm</th><th>Tên nhóm</th><th>Bắt buộc</th></tr></thead>
        <tbody>${qcGroups.map(g => `<tr>
          <td><input type="checkbox" class="mqc-chk" data-gid="${esc(g.group_id)}" ${linkedByGroup[g.group_id] ? "checked" : ""}/></td>
          <td><code class="k">${esc(g.code)}</code></td><td>${esc(g.name)}</td>
          <td><input type="checkbox" class="mqc-mand" data-gid="${esc(g.group_id)}" ${(!linkedByGroup[g.group_id] || linkedByGroup[g.group_id].mandatory) ? "checked" : ""}/></td>
          </tr>`).join("") || `<tr><td colspan="4" class="muted">Chưa có nhóm chỉ tiêu nào — tạo ở bảng bên trên.</td></tr>`}</tbody>
      </table></div>
      <button class="btn" id="mqc_save" style="margin-top:12px">Lưu</button>`);
    $("mqc_save").onclick = () => guard(async () => {
      const rows = Array.from(document.querySelectorAll(".mqc-chk"));
      for (const chk of rows) {
        const gid = chk.dataset.gid;
        const mandatory = document.querySelector(`.mqc-mand[data-gid="${gid}"]`).checked;
        const wasLinked = !!linkedByGroup[gid];
        if (chk.checked) {
          await POST(`/materials/${material.material_id}/qc-groups`, { group_id: gid, mandatory });
        } else if (wasLinked) {
          await api(`/materials/${material.material_id}/qc-groups/${gid}`, { method: "DELETE" });
        }
      }
      closeModal(); toast("Đã cập nhật chỉ tiêu QC cho vật tư");
    });
  }
};
VIEWS.users = async function () {
  if (!CURRENT_USER || CURRENT_USER.role !== "admin") {
    $("view-users").innerHTML = '<div class="panel muted">Chỉ quản trị viên (admin) xem được trang này.</div>';
    return;
  }
  const [users, pcat, scat] = await Promise.all([
    GET("/auth/users"), GET("/auth/permissions"),
    GET("/auth/scope-catalog").catch(() => ({ areas: [], lines: [], qc_params: [], warehouse_locations: [] }))]);
  const roleOpts = Object.keys(ROLE_DESC).map(r => `<option value="${r}">${r} — ${ROLE_DESC[r]}</option>`).join("");
  const permBoxes = pcat.catalog.map(p =>
    `<label style="display:inline-flex;align-items:center;gap:4px;margin:3px 10px 3px 0;font-size:12px">
       <input type="checkbox" class="nu_perm" value="${p.key}"/> ${esc(p.label)} <code class="k">${esc(p.key)}</code></label>`).join("");
  $("view-users").innerHTML = `
    <div class="panel"><h2>Tạo tài khoản</h2>
      <div class="row">
        <div class="field"><label>Đăng nhập</label><input id="nu_user"/></div>
        <div class="field"><label>Mật khẩu</label><input id="nu_pass" type="password" autocomplete="new-password"/>
          <div class="muted" style="font-size:11px">≥ 8 ký tự, gồm chữ và số</div></div>
        <div class="field"><label>Họ tên</label><input id="nu_name"/></div>
        <div class="field"><label>Chức danh</label><input id="nu_title"/></div>
        <div class="field"><label>Vai trò</label><select id="nu_role">${roleOpts}</select></div>
      </div>
      <div class="field"><label>Menu được phép (cách nhau dấu phẩy, hoặc * = tất cả)</label>
        <input id="nu_views" value="dashboard" style="width:100%"/></div>
      <div class="muted" style="margin:4px 0">Menu hợp lệ: ${ALL_VIEWS.join(", ")}</div>
      <h3>Phạm vi dữ liệu (data-scoping)</h3>
      <div class="row">
        <div class="field"><label>Line (csv / *)</label><input id="nu_lines" value="*"/></div>
        <div class="field"><label>Khu vực (csv / *)</label><input id="nu_areas" value="*"/></div>
        <div class="field"><label>Loại test QC (csv / *)</label><input id="nu_qc" value="*"/></div>
        <div class="field"><label>Địa điểm kho (${(scat.warehouse_locations || []).map(w => esc(w.key)).join("/") || "cong_ty/phan_xuong"} / *)</label><input id="nu_wh" value="*"/></div>
      </div>
      <div class="muted" style="margin:4px 0">Khu vực: ${scat.areas.map(a => esc(a.key)).join(", ") || "—"} · Line: ${scat.lines.map(esc).join(", ") || "(chưa có)"} · Địa điểm kho: ${(scat.warehouse_locations || []).map(w => `${esc(w.key)}=${esc(w.label)}`).join(", ") || "—"}</div>
      <h3>Quyền thao tác (ma trận quyền)</h3>
      <div style="background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:10px">${permBoxes}</div>
      <button class="btn" id="nu_add" style="margin-top:12px">Tạo tài khoản</button>
    </div>
    <div class="panel"><h2>Danh sách tài khoản <span class="muted">(${users.length})</span></h2>
      <input class="searchbox" data-tbl="t_users" placeholder="Tìm theo đăng nhập, họ tên, vai trò..."/>
      <div class="tablewrap"><table id="t_users"><thead><tr><th>Đăng nhập</th><th>Họ tên</th><th>Vai trò</th><th>Quyền thao tác</th><th>Phạm vi (line)</th><th>Đăng nhập gần nhất</th><th>Trạng thái</th><th></th></tr></thead>
      <tbody>${users.map(u => `<tr><td><code class="k">${esc(u.username)}</code></td><td>${esc(u.full_name)}<div class="muted" style="font-size:11px">${esc(u.job_title)}</div></td>
        <td>${badge(u.role === "admin" ? "critical" : "available")}${esc(u.role)}</td>
        <td style="font-size:12px">${u.permissions === "*" ? '<span class="badge critical">toàn quyền</span>' : (u.permissions ? u.permissions.split(",").map(p => `<span class="badge planned" style="margin:1px">${esc(p)}</span>`).join(" ") : '<span class="muted">chỉ xem</span>')}</td>
        <td style="font-size:12px">${scopeBadge(u.scope_lines)}</td>
        <td class="muted">${fmt(u.last_login_at)}</td>
        <td>${badge(u.active ? "available" : "obsolete")}${u.active ? "hoạt động" : "khoá"}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-scope="${esc(u.username)}">Phạm vi</button>
          <button class="btn sm sec" data-copyperm="${esc(u.username)}">Copy quyền</button>
          ${u.username !== CURRENT_USER.username ? `<button class="btn sm sec" data-toggle="${u.username}">${u.active ? "Khoá" : "Mở"}</button>` : ""}</td></tr>`).join("")}</tbody></table></div></div>`;
  wireSearch(); wirePaginate("t_users", 10);
  $("nu_add").onclick = () => guard(async () => {
    const weak = passwordPolicyMsg($("nu_pass").value, $("nu_user").value);
    if (weak) { toast(weak, "err"); return; }
    const perms = [...document.querySelectorAll(".nu_perm:checked")].map(c => c.value).join(",");
    await POST("/auth/users", { username: $("nu_user").value, password: $("nu_pass").value,
      full_name: $("nu_name").value, job_title: $("nu_title").value, role: $("nu_role").value,
      allowed_views: $("nu_views").value, permissions: perms,
      scope_lines: $("nu_lines").value || "*", scope_areas: $("nu_areas").value || "*", scope_qc: $("nu_qc").value || "*",
      scope_warehouse: $("nu_wh").value || "*" });
    toast("Đã tạo tài khoản"); render("users");
  });
  document.querySelectorAll("[data-toggle]").forEach(b => b.onclick = () => guard(async () => {
    await POST(`/auth/users/${b.dataset.toggle}/toggle`); toast("Đã đổi trạng thái"); render("users");
  }));
  document.querySelectorAll("[data-scope]").forEach(b => b.onclick = () => {
    const u = users.find(x => x.username === b.dataset.scope);
    modal(`<h3>Phạm vi dữ liệu: ${esc(u.username)}</h3>
      <div class="muted" style="margin-bottom:8px">Để <code class="k">*</code> = toàn nhà máy. Nhiều giá trị cách nhau dấu phẩy.</div>
      <div class="field"><label>Line</label><input id="sc_lines" value="${esc(u.scope_lines || "*")}"/></div>
      <div class="field" style="margin-top:8px"><label>Khu vực (${(scat.areas || []).map(a => esc(a.key)).join(",")})</label><input id="sc_areas" value="${esc(u.scope_areas || "*")}"/></div>
      <div class="field" style="margin-top:8px"><label>Loại test QC</label><input id="sc_qc" value="${esc(u.scope_qc || "*")}"/></div>
      <div class="field" style="margin-top:8px"><label>Địa điểm kho (${(scat.warehouse_locations || []).map(w => esc(w.key)).join(",")})</label><input id="sc_wh" value="${esc(u.scope_warehouse || "*")}"/></div>
      <button class="btn" id="sc_save" style="margin-top:12px">Lưu phạm vi</button>`);
    $("sc_save").onclick = () => guard(async () => {
      await PUT(`/auth/users/${u.username}/scope`, { scope_lines: $("sc_lines").value,
        scope_areas: $("sc_areas").value, scope_qc: $("sc_qc").value, scope_warehouse: $("sc_wh").value });
      closeModal(); toast("Đã cập nhật phạm vi"); render("users");
    });
  });
  document.querySelectorAll("[data-copyperm]").forEach(b => b.onclick = () => {
    const dst = b.dataset.copyperm;
    const others = users.filter(x => x.username !== dst);
    modal(`<h3>Copy quyền vào tài khoản: ${esc(dst)}</h3>
      <div class="muted" style="margin-bottom:8px">Copy toàn bộ vai trò, menu, quyền thao tác và 4 chiều phạm vi dữ liệu (line/khu vực/QC/địa điểm kho)
        từ 1 tài khoản khác sang <code class="k">${esc(dst)}</code> — ghi đè hoàn toàn, không hợp nhất. Dùng khi 2 người cùng chức danh.</div>
      <div class="field"><label>Copy quyền TỪ tài khoản</label>
        <select id="cp_src">${others.map(o => `<option value="${esc(o.username)}">${esc(o.username)} — ${esc(o.full_name)} (${esc(o.job_title || "")})</option>`).join("")}</select></div>
      <button class="btn" id="cp_go" style="margin-top:12px">Copy quyền</button>`);
    $("cp_go").onclick = () => guard(async () => {
      const src = $("cp_src").value;
      if (!confirm(`Ghi đè toàn bộ quyền/phạm vi của '${dst}' bằng đúng cấu hình của '${src}'? Không thể hoàn tác.`)) return;
      await POST(`/auth/users/${dst}/copy-permissions`, { source_username: src });
      closeModal(); toast(`Đã copy quyền từ '${src}' sang '${dst}'`); render("users");
    });
  });
};

// ================= HỒ SƠ CÁ NHÂN =================
VIEWS.profile = async function () {
  const me = await GET("/auth/me");
  const perms = me.permissions === "*" ? ["Toàn quyền (admin)"] : me.permissions;
  $("view-profile").innerHTML = `
    <div class="split">
      <div class="panel"><h2>Thông tin cá nhân</h2>
        <dl class="detail">
          <dt>Đăng nhập</dt><dd><code class="k">${esc(me.username)}</code></dd>
          <dt>Họ tên</dt><dd><input id="pf_name" value="${esc(me.full_name)}" style="width:240px"/> <button class="btn sm" id="pf_save">Lưu</button></dd>
          <dt>Chức danh</dt><dd>${esc(me.job_title)}</dd>
          <dt>Vai trò</dt><dd>${badge(me.role === "admin" ? "critical" : "available")}${esc(me.role)}</dd>
          <dt>Quyền được cấp</dt><dd>${(Array.isArray(perms) ? perms : [perms]).map(p => `<span class="badge planned" style="margin:2px">${esc(p)}</span>`).join(" ") || '<span class="muted">— chỉ xem —</span>'}</dd>
          <dt>Phạm vi line</dt><dd>${scopeBadge(me.scope_lines)}</dd>
          <dt>Phạm vi khu vực</dt><dd>${scopeBadge(me.scope_areas)}</dd>
          <dt>Phạm vi loại test</dt><dd>${scopeBadge(me.scope_qc)}</dd>
          <dt>Phạm vi kho</dt><dd>${scopeBadge(me.scope_warehouse)}</dd>
        </dl>
      </div>
      <div class="panel"><h2>Đổi mật khẩu</h2>
        <div class="field"><label>Mật khẩu hiện tại</label><input id="pf_old" type="password" autocomplete="current-password"/></div>
        <div class="field" style="margin-top:8px"><label>Mật khẩu mới</label><input id="pf_new" type="password" autocomplete="new-password"/></div>
        <div class="muted" style="font-size:12px;margin:2px 0">Mật khẩu mạnh: tối thiểu 8 ký tự, gồm cả chữ và số, không chứa tên đăng nhập.</div>
        <div class="field" style="margin-top:8px"><label>Nhập lại mật khẩu mới</label><input id="pf_new2" type="password" autocomplete="new-password"/></div>
        <button class="btn" id="pf_pwd" style="margin-top:12px">Đổi mật khẩu</button>
      </div>
    </div>`;
  $("pf_save").onclick = () => guard(async () => {
    const r = await PUT("/auth/me", { full_name: $("pf_name").value });
    CURRENT_USER.full_name = r.full_name; $("u_name").textContent = r.full_name;
    toast("Đã cập nhật hồ sơ");
  });
  $("pf_pwd").onclick = () => guard(async () => {
    if ($("pf_new").value !== $("pf_new2").value) { toast("Mật khẩu nhập lại không khớp", "err"); return; }
    const weak = passwordPolicyMsg($("pf_new").value, CURRENT_USER && CURRENT_USER.username);
    if (weak) { toast(weak, "err"); return; }
    await POST("/auth/change-password", { old_password: $("pf_old").value, new_password: $("pf_new").value });
    if (CURRENT_USER) CURRENT_USER.must_change_password = false;   // bỏ cờ buộc đổi trong phiên
    toast("Đã đổi mật khẩu"); $("pf_old").value = $("pf_new").value = $("pf_new2").value = "";
  });
};

// ================= AUTH / BOOT =================
function applyMenu() {
  const views = CURRENT_USER.views;
  const allowed = views === "*" ? null : new Set(views);
  let first = null;
  document.querySelectorAll("#nav button").forEach(b => {
    const ok = !allowed || allowed.has(b.dataset.view) || b.dataset.view === "profile" || b.dataset.view === "flowmap";
    b.style.display = ok ? "" : "none";
    if (ok && b.dataset.view !== "profile" && !first) first = b;
  });
  $("u_name").textContent = CURRENT_USER.full_name;
  $("u_title").textContent = CURRENT_USER.job_title + " · " + CURRENT_USER.role;
  // chọn tab đầu tiên được phép
  document.querySelectorAll("#nav button").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".view").forEach(x => x.classList.remove("active"));
  if (first) {
    first.classList.add("active");
    $("view-" + first.dataset.view).classList.add("active");
    render(first.dataset.view);
  }
}

function enterApp() {
  $("login").style.display = "none";
  $("app").style.display = "";
  applyMenu();
  // Buộc đổi mật khẩu lần đầu (mật khẩu mặc định) — modal chặn, không bỏ qua được.
  if (CURRENT_USER && CURRENT_USER.must_change_password) forcePasswordChange();
}

// Modal đổi mật khẩu lần đầu — KHÔNG cho đóng/bỏ qua cho tới khi đặt mật khẩu mạnh.
function forcePasswordChange() {
  closeModal();
  const bg = el(`<div class="modal-bg" id="modalbg"><div class="modal">
    <h2>🔒 Đổi mật khẩu lần đầu</h2>
    <div class="muted" style="margin-bottom:10px">Tài khoản đang dùng <b>mật khẩu mặc định</b>. Vì lý do an toàn, bạn phải đặt mật khẩu mới trước khi tiếp tục sử dụng hệ thống.</div>
    <div class="field"><label>Mật khẩu hiện tại</label><input id="fp_old" type="password" autocomplete="current-password"/></div>
    <div class="field" style="margin-top:8px"><label>Mật khẩu mới</label><input id="fp_new" type="password" autocomplete="new-password"/></div>
    <div class="muted" style="font-size:12px;margin:2px 0">Mật khẩu mạnh: tối thiểu 8 ký tự, gồm cả chữ và số, không chứa tên đăng nhập.</div>
    <div class="field" style="margin-top:8px"><label>Nhập lại mật khẩu mới</label><input id="fp_new2" type="password" autocomplete="new-password"/></div>
    <div id="fp_err" style="color:var(--red);font-size:13px;min-height:18px;margin-top:6px"></div>
    <button class="btn" id="fp_go" style="margin-top:8px;width:100%;padding:10px">Đặt mật khẩu & tiếp tục</button>
  </div></div>`);
  document.body.appendChild(bg);   // không gắn sự kiện đóng nền → bắt buộc hoàn thành
  const submit = async () => {
    const err = $("fp_err");
    if ($("fp_new").value !== $("fp_new2").value) { err.textContent = "Mật khẩu nhập lại không khớp."; return; }
    const weak = passwordPolicyMsg($("fp_new").value, CURRENT_USER && CURRENT_USER.username);
    if (weak) { err.textContent = weak; return; }
    try {
      await POST("/auth/change-password", { old_password: $("fp_old").value, new_password: $("fp_new").value });
      if (CURRENT_USER) CURRENT_USER.must_change_password = false;
      closeModal();
      toast("Đã đổi mật khẩu thành công.");
    } catch (e) { err.textContent = e.message; }
  };
  $("fp_go").onclick = submit;
  $("fp_new2").onkeydown = (e) => { if (e.key === "Enter") submit(); };
  $("fp_old").focus();
}

function showLogin(msg) {
  $("app").style.display = "none";
  $("login").style.display = "flex";
  $("li_err").textContent = msg || "";
}

async function doLogin() {
  const username = $("li_user").value.trim();
  const password = $("li_pass").value;
  if (!username || !password) { $("li_err").textContent = "Nhập tài khoản và mật khẩu."; return; }
  try {
    const res = await fetch("/api/auth/login", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }) });
    const data = await res.json();
    if (!res.ok) { $("li_err").textContent = data.detail || "Đăng nhập thất bại."; return; }
    TOKEN = data.token; localStorage.setItem("mes_token", TOKEN);
    CURRENT_USER = data.user;
    enterApp();
  } catch (e) { $("li_err").textContent = "Lỗi kết nối: " + e.message; }
}

async function doLogout() {
  try { await fetch("/api/auth/logout", { method: "POST", headers: { "Authorization": "Bearer " + TOKEN } }); } catch (e) {}
  TOKEN = ""; CURRENT_USER = null; localStorage.removeItem("mes_token");
  AI_HISTORY = []; CURRENT_CONV = null;
  showLogin();
}

$("li_btn").onclick = doLogin;
$("li_pass").onkeydown = (e) => { if (e.key === "Enter") doLogin(); };
$("logout").onclick = doLogout;

// boot: khôi phục phiên nếu còn token
(async () => {
  if (TOKEN) {
    try {
      CURRENT_USER = await GET("/auth/me");
      enterApp();
      return;
    } catch (e) { TOKEN = ""; localStorage.removeItem("mes_token"); }
  }
  showLogin();
})();
