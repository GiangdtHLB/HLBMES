"use strict";

// ---------- Auth + API helper ----------
let TOKEN = localStorage.getItem("mes_token") || "";
let CURRENT_USER = null;  // {username, full_name, job_title, role, views}
let PENDING_QUALITY_SCOPE = null;  // {key: "scope_type:scope_id", kind: "hold"|"dev"} — set by Dashboard alert row click, consumed once by VIEWS.quality to preselect h_scope/d_scope
let PENDING_CAPA_DEVIATION = null;  // deviation_id — set by "+ Tạo CAPA cho deviation này" trong devRow, consumed once by VIEWS.qclab để chọn sẵn ca_dev
let PENDING_OPEN_CAPA_ID = null;  // capa_id — set khi bấm mã CAPA ở cột "CAPA liên kết" (Deviations), consumed once by VIEWS.qclab để tự mở modal chi tiết CAPA đó
let PENDING_OPEN_DEVIATION_ID = null;  // deviation_id — set khi bấm mã Deviation ở cột "Deviation liên kết" (CAPA), consumed once by VIEWS.quality để cuộn/hiện đúng deviation đó

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  const res = await fetch("/api" + path, { headers, ...opts });
  if (res.status === 403 && CURRENT_USER && path !== "/auth/me") {
    // có thể phiên hết hạn → kiểm tra lại
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  // Lỗi 422 validate của FastAPI trả detail dạng MẢNG object Pydantic ({loc,msg,type}), không
  // phải chuỗi — new Error(mảng) sẽ ép kiểu thành "[object Object]" vô nghĩa hiện lên toast.
  if (!res.ok) throw new Error(data && data.detail
    ? (Array.isArray(data.detail) ? data.detail.map(d => (d && d.msg) ? d.msg : JSON.stringify(d)).join("; ") : data.detail)
    : "HTTP " + res.status);
  return data;
}
const GET = (p) => api(p);
const POST = (p, body) => api(p, { method: "POST", body: JSON.stringify(body || {}) });
const PUT = (p, body) => api(p, { method: "PUT", body: JSON.stringify(body || {}) });
const DELETE = (p) => api(p, { method: "DELETE" });
async function POST_FILES(path, files) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  return POST_FORM(path, fd);
}
// Gửi 1 FormData tự do (multipart) — dùng khi endpoint nhận field khác "files" (VD "file" +
// "note" cho đính kèm CAPA) — KHÔNG set Content-Type tay để browser tự set boundary multipart.
async function POST_FORM(path, formData) {
  const headers = {};
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  const res = await fetch("/api" + path, { method: "POST", headers, body: formData });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  // Lỗi 422 validate của FastAPI trả detail dạng MẢNG object Pydantic ({loc,msg,type}), không
  // phải chuỗi — new Error(mảng) sẽ ép kiểu thành "[object Object]" vô nghĩa hiện lên toast.
  if (!res.ok) throw new Error(data && data.detail
    ? (Array.isArray(data.detail) ? data.detail.map(d => (d && d.msg) ? d.msg : JSON.stringify(d)).join("; ") : data.detail)
    : "HTTP " + res.status);
  return data;
}

// ---------- utils ----------
const $ = (id) => document.getElementById(id);
const el = (html) => { const d = document.createElement("div"); d.innerHTML = html.trim(); return d.firstChild; };
const round3 = (n) => Math.round(n * 1000) / 1000;
const badge = (s) => `<span class="badge ${s}">${s}</span>`;
const scopeBadge = (raw) => (raw === "*" || raw == null || raw === "")
  ? '<span class="badge available">Toàn nhà máy</span>'
  : String(raw).split(",").map(s => `<span class="badge planned" style="margin:2px">${esc(s.trim())}</span>`).join(" ");

// ---------- ô chọn phạm vi dữ liệu (line/khu vực/loại test QC/địa điểm kho) ----------
// items: mảng string hoặc mảng {key,label}. current: csv hoặc "*"/rỗng = không giới hạn.
function scopePickerHtml(idPrefix, items, current) {
  const isAll = current == null || current === "" || current === "*";
  const curSet = isAll ? new Set() : new Set(String(current).split(",").map(s => s.trim()).filter(Boolean));
  const norm = (items || []).map(it => typeof it === "string" ? { key: it, label: it } : it);
  const boxes = norm.map(it =>
    `<label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text)">
       <input type="checkbox" class="${idPrefix}_item" value="${esc(it.key)}" ${curSet.has(it.key) ? "checked" : ""} ${isAll ? "disabled" : ""}/> ${esc(it.label)}</label>`
  ).join("") || '<span class="muted" style="font-size:12px">(chưa có dữ liệu)</span>';
  return `<label style="display:flex;align-items:center;gap:6px;font-size:12px;margin-bottom:6px;color:var(--text)">
      <input type="checkbox" id="${idPrefix}_all" ${isAll ? "checked" : ""}/> <b>Toàn bộ (không giới hạn)</b></label>
    <div id="${idPrefix}_items" style="display:grid;grid-auto-rows:min-content;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:5px 12px;background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:8px;max-height:150px;overflow-y:auto">${boxes}</div>`;
}
// Gắn sự kiện bật/tắt ô "Toàn bộ" — gọi sau khi HTML từ scopePickerHtml đã được chèn vào DOM.
function wireScopePicker(idPrefix) {
  const all = $(`${idPrefix}_all`), box = $(`${idPrefix}_items`);
  if (!all || !box) return;
  all.onchange = () => {
    box.querySelectorAll(`.${idPrefix}_item`).forEach(c => c.disabled = all.checked);
  };
}
// Đọc lại giá trị đã chọn thành csv hoặc "*" (khớp định dạng backend đang lưu).
function readScopePicker(idPrefix) {
  const all = $(`${idPrefix}_all`);
  if (!all || all.checked) return "*";
  const vals = [...document.querySelectorAll(`.${idPrefix}_item:checked`)].map(c => c.value);
  return vals.length ? vals.join(",") : "*";
}
// Ghi đè lại trạng thái ô chọn (VD khi áp dụng mẫu chức danh) sau khi đã render sẵn.
function setScopePicker(idPrefix, current) {
  const all = $(`${idPrefix}_all`), box = $(`${idPrefix}_items`);
  if (!all || !box) return;
  const isAll = current == null || current === "" || current === "*";
  const curSet = isAll ? new Set() : new Set(String(current).split(",").map(s => s.trim()).filter(Boolean));
  all.checked = isAll;
  box.querySelectorAll(`.${idPrefix}_item`).forEach(c => { c.checked = curSet.has(c.value); c.disabled = isAll; });
}
const fmt = (t) => t ? new Date(t).toLocaleString("vi-VN") : "—";
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));
const plateLast5 = (plate) => { const digits = String(plate || "").replace(/\D/g, ""); return digits ? digits.slice(-5) : "—"; };
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

// Tải file từ endpoint yêu cầu Authorization header (thẻ <a href> thường không gửi được header
// này) — fetch kèm token, đọc về Blob rồi bấm giả 1 link tạm để trình duyệt lưu file.
async function downloadFile(path, filename) {
  const headers = {};
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  const res = await fetch("/api" + path, { headers });
  if (!res.ok) throw new Error("HTTP " + res.status);
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

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

// onBack (tuỳ chọn): modal này được mở TỪ 1 modal danh sách khác (vd Chỉ tiêu/+NVL/Ghi chép
// nấu/CIP mở từ "Các mẻ thuộc mã nấu") — hiện thêm nút "‹ Quay lại" gọi lại đúng modal cha
// (thường là render lại modal danh sách đó, không phải chỉ đóng) thay vì chỉ có nút ✕ đóng hẳn.
function modal(html, onBack, wide) {
  closeModal();
  const backBtn = onBack ? `<span class="modal-back" title="Quay lại">‹ Quay lại</span>` : "";
  const bg = el(`<div class="modal-bg" id="modalbg"><div class="modal${wide ? " modal-wide" : ""}">${backBtn}<span class="modal-x" title="Đóng">✕</span>${html}</div></div>`);
  bg.onclick = (e) => { if (e.target === bg) closeModal(); };
  bg.querySelector(".modal-x").onclick = () => closeModal();
  if (onBack) bg.querySelector(".modal-back").onclick = () => onBack();
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

// Ô tìm nhanh phía trên 1 <select multiple> dài (VD chọn vật tư thành viên Nhóm vật tư thay
// thế) — ẩn bớt <option> không khớp từ khóa, KHÔNG đụng tới lựa chọn hiện có (option.hidden
// không làm mất selected).
function wireMultiSelectFilter(searchEl, selectEl) {
  if (!searchEl || !selectEl) return;
  searchEl.addEventListener("input", () => {
    const q = searchEl.value.trim().toLowerCase();
    [...selectEl.options].forEach(o => { o.hidden = !!q && !o.textContent.toLowerCase().includes(q); });
  });
}

// Dòng phụ hiện tồn TỪNG mã thành viên của 1 dòng NVL khai theo Nhóm vật tư thay thế (VD
// "Malt Úc" = Malt Úc rời + Malt Úc bao) — để người lập Lệnh nấu thấy đúng nhóm gồm những
// mã nào và mã nào đang thực sự còn tồn, không chỉ số tổng cộng dồn của cả nhóm. colspanLeft/
// colspanRight canh dòng phụ thẳng cột với bảng chính (STT+Tên NVL ở bên trái, Tồn CT/PX ở
// giữa, phần còn lại bên phải để trống).
function bomMemberRowsHtml(l, colspanLeft, colspanRight, showQtyCells) {
  if (!l.member_breakdown || !l.member_breakdown.length) return "";
  return l.member_breakdown.map(mb => {
    // actual_used: tổng đã dùng THẬT của đúng mã này qua mọi mẻ của lệnh (đối chiếu với Nhu
    // cầu Tổng mẻ của dòng gộp) — chỉ có ở get_order() (đã tạo lệnh), không có ở preview.
    const usedNote = mb.actual_used !== undefined
      ? ` · <b>Đã dùng: ${mb.actual_used}</b>` : "";
    const hasQty = mb.qty_per_batch != null;
    // showQtyCells: bảng có sẵn cột riêng Nhu cầu 1 mẻ/Tổng mẻ/SL lấy Company/Workshop — hiện
    // đúng số CỦA CHÍNH mã này vào các cột đó (không chỉ ghi chú trong tên) — dùng cho bảng có
    // đủ cột này (VD "Xem" Lệnh nấu). Dòng nhóm khai kiểu cũ (không có qty_per_batch riêng) vẫn
    // hiện "—" ở các cột số, không suy đoán.
    if (showQtyCells) {
      return `<tr class="muted" style="font-size:12px" title="Tồn kho hiện tại (không phải lúc lập phiếu)">
      <td colspan="${colspanLeft}" style="padding-left:24px">↳ ${esc(mb.material_code || "")} — ${esc(mb.material_name || "")}${usedNote}</td>
      <td>${hasQty ? mb.qty_per_batch : "—"}</td><td>${hasQty ? mb.qty_total : "—"}</td>
      <td>${hasQty ? (mb.qty_from_company ?? "—") : "—"}</td><td>${hasQty ? (mb.qty_from_workshop ?? "—") : "—"}</td>
      <td>${mb.stock_company} <span style="font-size:10px">(hiện tại)</span></td><td>${mb.stock_workshop} <span style="font-size:10px">(hiện tại)</span></td>
      <td colspan="${colspanRight}"></td></tr>`;
    }
    // Dòng Nhóm vật tư khai định mức riêng từng thành viên (member_qty) có sẵn qty_per_batch/
    // qty_total CỦA CHÍNH mã này (khác dòng nhóm kiểu cũ, chỉ có tồn kho) — hiện luôn ra để
    // biết ngay cần lấy bao nhiêu mã này, không chỉ thấy tên nhóm chung ở dòng cha.
    const qtyNote = hasQty
      ? ` · <b>Nhu cầu: ${mb.qty_per_batch}/mẻ, ${mb.qty_total} tổng mẻ</b>` : "";
    return `<tr class="muted" style="font-size:12px" title="Tồn kho hiện tại (không phải lúc lập phiếu)">
    <td colspan="${colspanLeft}" style="padding-left:24px">↳ ${esc(mb.material_code || "")} — ${esc(mb.material_name || "")}${qtyNote}${usedNote}</td>
    <td>${mb.stock_company} <span style="font-size:10px">(hiện tại)</span></td><td>${mb.stock_workshop} <span style="font-size:10px">(hiện tại)</span></td>
    <td colspan="${colspanRight}"></td></tr>`;
  }).join("");
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
// Sửa 1 mẻ nấu: gộp Mã mẻ + Giờ bắt đầu + Giờ kết thúc vào 1 modal duy nhất (trước đây tách
// 2 nút "Sửa giờ BĐ"/"Kết thúc"·"Sửa giờ KT") — Giờ kết thúc để trống nếu mẻ chưa kết thúc,
// điền vào coi như bấm "Kết thúc"; sửa lại giờ đã có coi như "Sửa giờ KT" (gọi lại /finish
// được nhiều lần, xem routers/brewing.py::finish_brew_batch). Chỉ gọi API cho field THỰC SỰ
// đổi, tránh gọi /start hay /finish không cần thiết khi người dùng chỉ sửa Mã mẻ.
function openEditBrewBatchModal(batch, onSubmit, onBack) {
  const startVal = toDTLocal(batch.started_at ? new Date(batch.started_at) : new Date());
  const endVal = batch.ended_at ? toDTLocal(new Date(batch.ended_at)) : "";
  modal(`<h3>Sửa mẻ <code class="k">${esc(batch.batch_code)}</code></h3>
    <div class="field"><label>Mã mẻ</label><input id="eb_code" type="number" min="1" step="1" value="${esc(batch.batch_code)}"/></div>
    <div class="field" style="margin-top:8px"><label>Giờ bắt đầu</label><input id="eb_start" type="datetime-local" value="${startVal}"/></div>
    <div class="field" style="margin-top:8px"><label>Giờ kết thúc <span class="muted" style="font-weight:400">(để trống nếu mẻ chưa kết thúc)</span></label><input id="eb_end" type="datetime-local" value="${endVal}"/></div>
    <button class="btn" id="eb_ok" style="margin-top:12px">Lưu</button>`, onBack);
  $("eb_ok").onclick = () => guard(async () => {
    const code = $("eb_code").value.trim();
    if (!code || !/^\d+$/.test(code) || parseInt(code, 10) <= 0) throw new Error("Mã mẻ phải là số nguyên dương (VD: 123).");
    const startRaw = $("eb_start").value;
    if (!startRaw) throw new Error("Chọn giờ bắt đầu.");
    const endRaw = $("eb_end").value;
    await onSubmit({
      code: code !== batch.batch_code ? code : null,
      started_at: startRaw !== startVal ? new Date(startRaw).toISOString() : null,
      ended_at: (endRaw && endRaw !== endVal) ? new Date(endRaw).toISOString() : null,
    });
  });
}

// Kết thúc lọc CHO 1 TANK (lọc phối kết thúc riêng từng tank rồi cộng dồn) — Dịch nha
// lọc/Sản lượng lọc không bắt buộc lúc tạo, điền ở đây kèm Nước bài khí; Sản lượng lọc
// (V Bia/hl) tự tính = Dịch nha lọc + Nước bài khí (không nhập tay).
function openFinishFilterModal(title, currentEndedAt, currentVDich, currentBaiKhi, currentBatchNumber, currentOrderNumber, currentBatchSeqNo, suggestedSeqNo, usedSeqNos, onSubmit, onBack) {
  const defaultVal = toDTLocal(currentEndedAt ? new Date(currentEndedAt) : new Date());
  // Gợi ý "Mẻ lọc số" kế tiếp (chỉ khi chưa có giá trị đã lưu — sửa lại mẻ cũ vẫn giữ nguyên số
  // đã ghi) — vận hành có thể sửa tay, không khoá cứng vì số này KHÔNG bắt buộc phải tăng dần
  // (xem services/filter_order.py::next_batch_seq_no).
  const seqValue = currentBatchSeqNo || suggestedSeqNo || "";
  modal(`<h3>${esc(title)}</h3>
    <div class="row">
      <div class="field"><label>Số mẻ (Batch number Brewmax) *</label><input id="ff_batch" value="${esc(currentBatchNumber || "")}"/></div>
      <div class="field"><label>Số lệnh (Order number Brewmax) *</label><input id="ff_order" value="${esc(currentOrderNumber || "")}"/></div>
      <div class="field"><label>Mẻ lọc số * <span class="muted" style="font-weight:400">(gợi ý: ${esc(suggestedSeqNo || "1")})</span></label><input id="ff_seqno" value="${esc(seqValue)}"/></div>
    </div>
    <div class="field" style="margin-top:8px"><label>Giờ kết thúc</label><input id="ff_time" type="datetime-local" value="${defaultVal}"/></div>
    <div class="row" style="margin-top:8px">
      <div class="field"><label>Dịch nha lọc (hl)</label><input id="ff_dich" type="number" value="${currentVDich || 0}"/></div>
      <div class="field"><label>Nước bài khí (hl)</label><input id="ff_baikhi" type="number" value="${currentBaiKhi || 0}"/></div>
    </div>
    <div class="muted" style="margin-top:8px">Tổng tank này (hl) = Dịch nha lọc + Nước bài khí = <b id="ff_total">${((currentVDich || 0) + (currentBaiKhi || 0)).toFixed(1)}</b></div>
    <button class="btn" id="ff_ok" style="margin-top:12px">Xác nhận</button>`, onBack);
  const recalc = () => {
    const d = parseFloat($("ff_dich").value) || 0;
    const k = parseFloat($("ff_baikhi").value) || 0;
    $("ff_total").textContent = (d + k).toFixed(1);
  };
  $("ff_dich").oninput = recalc; $("ff_baikhi").oninput = recalc;
  $("ff_ok").onclick = () => guard(async () => {
    const raw = $("ff_time").value;
    if (!raw) throw new Error("Chọn giờ kết thúc.");
    const batchNumber = $("ff_batch").value.trim();
    const orderNumber = $("ff_order").value.trim();
    const batchSeqNo = $("ff_seqno").value.trim();
    if (!batchNumber || !orderNumber || !batchSeqNo) throw new Error("Nhập Mẻ lọc số, Số mẻ (Batch number Brewmax) và Số lệnh (Order number Brewmax).");
    const vDich = parseFloat($("ff_dich").value) || 0;
    if (vDich <= 0) throw new Error("Dịch nha lọc (hl) phải lớn hơn 0 mới được kết thúc mẻ lọc.");
    // batch_seq_no KHÔNG chặn trùng ở BE (thực tế có thể trùng hợp lệ giữa các lệnh lọc khác
    // nhau) — chỉ hỏi lại ở đây để bắt lỗi gõ nhầm (nhập lại đúng số mẻ trước trong CÙNG lệnh
    // lọc này) trước khi lưu.
    if (batchSeqNo !== (currentBatchSeqNo || "") && (usedSeqNos || []).includes(batchSeqNo)) {
      if (!confirm(`Mẻ lọc số "${batchSeqNo}" đã dùng trong lệnh lọc này trước đó. Mẻ này có phải là mẻ lọc trùng với mẻ trước không? Bấm OK để vẫn lưu.`)) return;
    }
    await onSubmit({
      ended_at: new Date(raw).toISOString(),
      v_dich_hl: parseFloat($("ff_dich").value) || 0,
      nuoc_bai_khi_hl: parseFloat($("ff_baikhi").value) || 0,
      batch_number: batchNumber,
      order_number: orderNumber,
      batch_seq_no: batchSeqNo,
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

// ---- Modal: các tank nguồn (CCT lên men hoặc BBT lọc lại) thuộc 1 bản ghi lọc — mirror
// openBrewBatchesModal, mỗi tank kết thúc RIÊNG (đặc biệt cần cho lọc phối, nhiều tank cùng
// lọc vào 1 BBT). "Làm rỗng lên men" (CCT nguồn) chuyển sang màn hình Lên men (rỗng cả tank,
// không riêng theo mẻ lọc); "Làm rỗng tank thành phẩm" (BBT đích) + CIP nằm ngay trên dòng
// đầu mỗi khối Tank BBT ở bảng "Thông tin lọc" (rỗng cả tank, không riêng theo mẻ) — xem
// VIEWS.process sec=loc, renderTankBlock.
async function openFilterTanksModal(filterId, onHandBbt) {
  const tanks = await GET(`/brewing/filters/${filterId}/tanks`);
  // Nhóm các dòng theo CÙNG 1 tank nguồn vật lý (tank lên men hoặc BBT lọc lại) — 1 tank có
  // thể có NHIỀU mẻ (nhiều đợt rút dịch), mỗi mẻ kết thúc riêng qua data-finishtank; nút
  // data-addbatch chỉ hiện khi mẻ mới nhất của tank đã kết thúc (không rút dịch 2 đợt cùng lúc).
  const groups = [];
  const byKey = new Map();
  tanks.forEach(t => {
    const key = t.tank_type + "|" + (t.tank_type === "bbt" ? t.source_bbt_code : t.ferment_id);
    let g = byKey.get(key);
    if (!g) { g = { key, tank_type: t.tank_type, tank_lm: t.tank_lm, lm_code: t.lm_code, source_bbt_code: t.source_bbt_code, rows: [] }; byKey.set(key, g); groups.push(g); }
    g.rows.push(t);
  });
  const rowHtml = (t, label) => `<tr>
    <td>${fmt(t.ended_at)}</td>
    <td>${badge(t.exec_status === "hoan_thanh" ? "completed" : "in_progress")}${esc(t.exec_status_label)}
      ${t.is_final_batch ? `<div><span class="badge planned" style="margin-top:2px">Mẻ cuối</span></div>` : ""}</td>
    <td>${t.v_dich_hl ?? "—"}</td><td>${t.nuoc_bai_khi_hl ?? "—"}</td>
    <td>${esc(t.batch_number || "—")}</td><td>${esc(t.order_number || "—")}</td><td>${esc(t.batch_seq_no || "—")}</td>
    <td style="white-space:nowrap"><button class="btn sm ${t.exec_status === "hoan_thanh" ? "sec" : ""}" data-finishtank="${esc(t.line_id)}"
      data-tanklabel="${esc(label)}" data-endedat="${esc(t.ended_at || "")}" data-vdich="${t.v_dich_hl || 0}"
      data-baikhi="${t.nuoc_bai_khi_hl || 0}" data-batchnumber="${esc(t.batch_number || "")}"
      data-ordernumber="${esc(t.order_number || "")}" data-batchseqno="${esc(t.batch_seq_no || "")}">
      ${t.exec_status === "hoan_thanh" ? "Sửa giờ KT" : "Kết thúc"}</button>
      ${tanks.length > 1 ? `<button class="btn sm sec" data-delbatch="${esc(t.line_id)}" style="margin-left:4px">Xóa mẻ</button>` : ""}
      ${t.exec_status === "hoan_thanh" ? `<button class="btn sm sec" data-togglefinal="${esc(t.line_id)}" style="margin-left:4px">${t.is_final_batch ? "Bỏ đánh dấu cuối" : "Xác nhận mẻ cuối"}</button>` : ""}</td></tr>`;
  const groupHtml = (g) => {
    const total = g.rows.reduce((s, t) => s + (t.v_dich_hl || 0) + (t.nuoc_bai_khi_hl || 0), 0);
    const last = g.rows[g.rows.length - 1];
    const label = g.tank_type === "bbt" ? `BBT ${g.source_bbt_code} (lọc lại)` : `${g.tank_lm || "—"} (Lô LM ${g.lm_code || "—"})`;
    return `<tr><td colspan=8 style="padding-top:14px;border-top:1px solid var(--border)"><b>${esc(label)}</b>
        <span class="muted"> — Tổng: ${total.toFixed(1)} hl</span>
        ${last.ended_at ? `<button class="btn sm sec" data-addbatch="${esc(last.line_id)}" style="margin-left:10px">+ Thêm mẻ</button>` : ""}</td></tr>
      ${g.rows.map(t => rowHtml(t, label)).join("")}`;
  };
  modal(`<h3>Các tank nguồn thuộc bản ghi lọc</h3>
    <div class="tablewrap"><table>
      <thead><tr><th>Kết thúc</th><th>Trạng thái</th><th>Dịch nha lọc (hl)</th><th>Nước bài khí (hl)</th><th>Batch number Brewmax</th><th>Order number Brewmax</th><th>Mẻ lọc số</th><th></th></tr></thead>
      <tbody>${groups.map(groupHtml).join("") || `<tr><td colspan=8 class="muted">Không có tank nào.</td></tr>`}</tbody>
    </table></div>`);
  document.querySelectorAll("[data-finishtank]").forEach(b => b.onclick = () => guard(async () => {
    const lineId = b.dataset.finishtank;
    const suggest = await GET(`/brewing/next-batch-seq-no?exclude_line_id=${encodeURIComponent(lineId)}`);
    openFinishFilterModal("Kết thúc mẻ — " + b.dataset.tanklabel,
      b.dataset.endedat || null, parseFloat(b.dataset.vdich) || 0, parseFloat(b.dataset.baikhi) || 0,
      b.dataset.batchnumber || "", b.dataset.ordernumber || "", b.dataset.batchseqno || "",
      suggest.next_batch_seq_no, suggest.used_batch_seq_nos || [],
      async (payload) => {
        await POST(`/brewing/filters/${filterId}/tanks/${lineId}/finish`, payload);
        toast("Đã lưu kết quả lọc"); openFilterTanksModal(filterId, onHandBbt); render("process");
      }, () => openFilterTanksModal(filterId, onHandBbt));
  }));
  document.querySelectorAll("[data-addbatch]").forEach(b => b.onclick = () => guard(async () => {
    await POST(`/brewing/filters/${filterId}/tanks/${b.dataset.addbatch}/add-batch`, {});
    toast("Đã thêm mẻ mới cho tank này — bấm \"Kết thúc\" khi rút dịch xong");
    openFilterTanksModal(filterId, onHandBbt); render("process");
  }));
  document.querySelectorAll("[data-delbatch]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Xóa mẻ này? Tồn sẽ hoàn lại tank nguồn nếu đã ghi nhận thể tích. Không thể hoàn tác.")) return;
    await DELETE(`/brewing/filters/${filterId}/tanks/${b.dataset.delbatch}`);
    toast("Đã xóa mẻ"); openFilterTanksModal(filterId, onHandBbt); render("process");
  }));
  document.querySelectorAll("[data-togglefinal]").forEach(b => b.onclick = () => guard(async () => {
    const r = await POST(`/brewing/filters/${filterId}/tanks/${b.dataset.togglefinal}/toggle-final`, {});
    toast(r.is_final_batch ? "Đã đánh dấu mẻ cuối — không tính Thấp/Cao trong báo cáo sản lượng" : "Đã bỏ đánh dấu mẻ cuối");
    openFilterTanksModal(filterId, onHandBbt); render("process");
  }));
}

// ---------- SVG charts (CH): đã tách sang charts.js (nạp trước app.js) ----------

// caches for dropdowns
let CACHE = { products: [], orders: [], recipes: [] };

// ---------- navigation ----------
const VIEWS = {};
// Nhóm domain cấp cao nhất chứa mỗi view — dùng để tự mở/đóng đúng 1 trong 5 nhóm khi bấm view.
const GROUP_OF_VIEW = {
  flowmap: "sanxuat", orders: "sanxuat", process: "sanxuat", recipes: "sanxuat", cip: "sanxuat",
  dispatch: "sanxuat", batches: "sanxuat", dispense: "sanxuat", recipeadv: "sanxuat", isa88: "sanxuat", schedule: "sanxuat",
  oee: "baotri", maint: "baotri", calib: "baotri",
  quality: "chatluong", qclab: "chatluong",
  realtime: "giamsat", energy: "giamsat", reports: "giamsat",
  integration: "hethong", users: "hethong", audit: "hethong", profile: "hethong",
  // dashboard/master/trace/ai/warehouse_kc/warehouse_px/wms/packaging: đứng riêng, không thuộc nhóm nào.
};
// Chỉ 1 trong 5 nhóm domain cấp cao nhất được xổ ra tại 1 thời điểm (không tính nhóm lồng riêng
// của Danh mục — #nav-master-groups nằm sâu bên trong nhóm "hethong", có accordion độc lập).
function openNavGroup(grpKey) {
  document.querySelectorAll("#nav .nav-topgroup").forEach(g => g.classList.toggle("active", !!grpKey && g.dataset.navgrp === grpKey));
  document.querySelectorAll("#nav > .nav-scroll > .nav-groups").forEach(g => g.classList.toggle("open", !!grpKey && g.id === "nav-group-" + grpKey));
}
document.querySelectorAll("#nav button[data-view]").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("#nav button").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".view").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    $("view-" + b.dataset.view).classList.add("active");
    openNavGroup(GROUP_OF_VIEW[b.dataset.view]);
    // Danh sách 5 nhóm con của Danh mục chỉ xổ ra khi đang ở đúng view Danh mục — bấm sang view
    // khác thì thu gọn lại, tránh menu trái dài thường trực.
    $("nav-master-groups").classList.toggle("open", b.dataset.view === "master");
    render(b.dataset.view);
  };
});
// Nhóm con lồng dưới "🗂️ Danh mục" trong menu trái — bấm 1 nhóm thì vào thẳng view Danh mục
// với nhóm đó (không phải 1 view riêng), tái dùng đúng logic active-class của #nav button ở trên.
document.querySelectorAll("#nav [data-mastergrp]").forEach(b => {
  b.onclick = () => {
    MASTER_GROUP = b.dataset.mastergrp;
    document.querySelectorAll("#nav button").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".view").forEach(x => x.classList.remove("active"));
    document.querySelector('#nav button[data-view="master"]').classList.add("active");
    b.classList.add("active");
    openNavGroup(null);
    $("nav-master-groups").classList.add("open");
    $("view-master").classList.add("active");
    render("master");
  };
});
// 5 nút tiêu đề nhóm domain cấp cao nhất — bấm để xổ ra/thu gọn, không đổi view hiện tại.
document.querySelectorAll("#nav .nav-topgroup").forEach(b => {
  b.onclick = () => {
    const willOpen = !b.classList.contains("active");
    openNavGroup(willOpen ? b.dataset.navgrp : null);
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
  const lowYieldDays = SUB.dashboard_low_yield_days || 5;
  const [batches, audit, prodSummary, agingRows, expiryRows, agingOpsRaw, alerts, fermentsRaw, lowYield, bottledNotApproved, overdueActions] = await Promise.all([
    GET("/batches"), GET("/audit?limit=10"), safe("/reports/dashboard-summary"),
    safe("/reports/inventory-aging"), safe("/warehouse/expiry?warn_days=14"), safe("/ops-settings"),
    safe("/reports/qc-attention-alerts"), safe("/brewing/ferments"),
    safe(`/reports/low-yield-filter-alerts?days=${lowYieldDays}&limit=5`),
    safe("/reports/bottled-not-approved"),
    safe("/reports/overdue-action-alerts"),
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
      color: AGING_BUCKET_COLOR[r.age_bucket] || "var(--muted)",
      disp: `${(r.count || 0).toLocaleString("vi-VN")} ${AGING_UNIT_LABEL[r.unit_type] || r.unit_type} · ${r.age_days} ngày`,
    }));
  // Khi không có lô nào cần chú ý, vẫn hiện biểu đồ (không thay bằng câu chữ) — 3 mức luôn có
  // mặt, giá trị 0 nếu không có lô nào ở mức đó.
  const agingChartDisplay = agingChartItems.length ? agingChartItems : AGING_BUCKET_ORDER.map(b => ({
    label: AGING_BUCKET_META[b].label, value: 0, color: AGING_BUCKET_COLOR[b], disp: "0",
  }));
  // Trục X dùng chung 1 thang đo cố định (KHÔNG co giãn theo lô dài nhất — 1 lô tồn kho lâu năm
  // do lỗi dữ liệu/test cũ có thể lên tới hàng nghìn ngày, nếu đưa vào công thức max() sẽ kéo dãn
  // cả trục khiến mọi lô còn lại (7-30 ngày) co lại thành 1 vệt sát mép trái, không đọc được).
  // Chỉ dựa vào ngưỡng "nghiêm trọng" (tối thiểu 50 ngày) — lô vượt trục sẽ hiện thanh đầy (kịch
  // trục) kèm số ngày thật ở nhãn bên phải, thay vì làm hỏng thang đo chung.
  const agingAxisMax = Math.ceil(Math.max(agingOps.aging_critical_days * 1.1, 50) / 10) * 10;
  // Danh sách lô cần chú ý có thể rất dài (hàng chục lô) — chỉ hiện top N (đã sort theo số
  // ngày tồn giảm dần từ backend, nên top N luôn là các lô đáng lo nhất) kèm nút "Xem thêm" để
  // tránh dashboard dài lê thê; "Xem thêm" vẽ lại SVG với đầy đủ dữ liệu (agingBars dựng 1 khối
  // SVG duy nhất theo chiều cao items.length, không có cơ chế ẩn/hiện từng dòng như bảng).
  const AGING_CHART_LIMIT = 10;
  const agingMoreCount = Math.max(0, agingChartDisplay.length - AGING_CHART_LIMIT);
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
    <span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px;font-size:11px;color:var(--muted)">
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
      color: EXPIRY_COLOR[e.status] || "var(--muted)",
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
    <span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px;font-size:11px;color:var(--muted)">
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
      ${s ? `<div class="muted" style="font-size:11px;margin-top:4px;line-height:1.6">
        ${s.dang_nap ? `<span style="color:var(--orange)">${s.dang_nap} tank đang nạp dịch nấu</span> · ` : ""}${s.trong} tank trống</div>` : ""}
    </div>`;
  // Ô "Cảnh báo QC" trước đây gộp chung 1 bảng — nay tách thành 3 panel riêng theo đúng yêu cầu,
  // mỗi panel lọc từ CÙNG 1 nguồn dữ liệu alerts.items (BE không đổi): (1) Cảnh báo QC = lô có
  // chỉ tiêu đang fail, (2) Hold/Release = lô đang giữ MaterialLot.status=on_hold, (3) Deviation =
  // scope đang có deviation mở. 1 lô có thể xuất hiện ở nhiều panel nếu thoả nhiều điều kiện.
  const REASON_LABEL = { on_hold: "Đang giữ", deviation: "Deviation mở" };
  const qcFailItems = alerts ? alerts.items.filter(it => it.fail_param_count > 0) : [];
  const holdItems = alerts ? alerts.items.filter(it => it.reasons.includes("on_hold")) : [];
  const devItems = alerts ? alerts.items.filter(it => it.reasons.includes("deviation")) : [];
  const MINI_ALERT_LIMIT = 5;
  // Cột "Chi tiết": trước đây luôn hiện "Vật tư"/"SL" — 2 cột này chỉ có ý nghĩa với scope="lot"
  // (lô NVL), còn mẻ nấu/mẻ lọc/mã chiết luôn hiện "—" ở cả 2 cột vì không có vật tư/SL riêng.
  // Đổi thành 1 cột theo ngữ cảnh: lô NVL vẫn hiện vật tư+SL; mẻ nấu/lọc/chiết hiện lô cha
  // (parent_label từ BE, VD "Lô nấu BR-260801") — kèm TÊN các chỉ tiêu đang fail (fail_params,
  // VD "Độ đục, Plato") thay vì chỉ đếm số lượng ở cột "Chỉ tiêu fail", để biết ngay đang fail gì.
  const miniAlertDetail = (it) => {
    const matLabel = it.material_name ? `${esc(it.material_code || "")} ${esc(it.material_name)}`.trim() : esc(it.material_code || "—");
    const base = it.scope_type === "lot"
      ? `${matLabel}${it.quantity != null ? ` · ${it.quantity.toLocaleString("vi-VN")} ${esc(it.uom || "")}` : ""}`
      : (it.parent_label ? esc(it.parent_label) : "");
    const failNames = (it.fail_params && it.fail_params.length) ? esc(it.fail_params.join(", ")) : "";
    if (base && failNames) return `${base}<br><span style="color:var(--red)">${failNames}</span>`;
    return base || failNames || "—";
  };
  const miniAlertPanel = (title, icon, items, emptyText, extraCol, key) => {
    const moreCount = items.length - MINI_ALERT_LIMIT;
    return `
    <div class="panel" style="flex:1;min-width:280px;margin-bottom:0">
      <h2>${icon} ${title} ${items.length ? `<span class="muted">(${items.length})</span>` : ""}</h2>
      ${items.length ? `<div class="tablewrap" style="max-height:240px;overflow:auto"><table style="font-size:12px">
        <thead><tr><th>Lô/Phạm vi</th><th>Chi tiết</th><th>${extraCol.label}</th></tr></thead>
        <tbody>${items.map((it, i) => { const kind = key === "hold" ? "hold" : key === "dev" ? "dev" : (it.reasons.includes("on_hold") ? "hold" : "dev");
          return `<tr style="cursor:pointer${i >= MINI_ALERT_LIMIT ? ";display:none" : ""}" class="${i >= MINI_ALERT_LIMIT ? `miniextra-${key}` : ""}" data-goto="quality" data-scope="${esc(it.scope_type)}:${esc(it.scope_id)}" data-scopekind="${kind}" tabindex="0" role="button">
          <td>${esc(it.scope_label || it.lot_code || it.scope_id)}</td>
          <td class="muted">${miniAlertDetail(it)}</td>
          <td>${extraCol.render(it)}</td>
        </tr>`; }).join("")}</tbody></table></div>
        ${moreCount > 0 ? `<button type="button" class="btn sm sec" data-minimore="${key}" data-minimorecount="${moreCount}" style="margin-top:8px">Xem thêm (${moreCount})</button>` : ""}`
        : `<div class="muted">${emptyText}</div>`}
    </div>`;
  };
  // Sản lượng lọc thấp: top N mẻ lọc (theo "mẻ lọc số") dưới ngưỡng Thấp trong 5 ngày gần nhất
  // (services/dashboard.py::low_yield_filter_alerts, đã lọc+sort+giới hạn sẵn ở BE) — panel
  // riêng vì cột khác hẳn 3 panel trên (không phải lô NVL/thành phẩm), nhưng giữ đúng khung
  // hình + kiểu chữ để đồng bộ hàng cảnh báo trên Dashboard.
  const lowYieldItems = (lowYield && lowYield.items) || [];
  const LOW_YIELD_DAY_OPTS = [3, 5, 7, 14, 30];
  const lowYieldPanel = `
    <div class="panel" style="flex:1;min-width:280px;margin-bottom:0">
      <h2>📉 Sản lượng lọc thấp ${lowYieldItems.length ? `<span class="muted">(${lowYieldItems.length})</span>` : ""}</h2>
      <div class="muted" style="font-size:11px;margin-bottom:6px;display:flex;align-items:center;gap:6px">
        <select id="lowyield_days" style="font-size:11px;padding:1px 4px">
          ${LOW_YIELD_DAY_OPTS.map(d => `<option value="${d}" ${d === lowYieldDays ? "selected" : ""}>${d} ngày gần nhất</option>`).join("")}
        </select>
        · dưới ngưỡng Thấp (${lowYield ? lowYield.low_l : "—"} lít)</div>
      ${lowYieldItems.length ? `<div class="tablewrap" style="max-height:240px;overflow:auto"><table>
        <thead><tr><th>Mã lọc</th><th>Mẻ lọc số</th><th>Loại dịch bia</th><th>V bia (lít)</th><th>Phân loại</th></tr></thead>
        <tbody>${lowYieldItems.map(it => `<tr style="cursor:pointer" data-goto="process" data-gotosub="loc" tabindex="0" role="button">
          <td>${esc(it.filter_code || "—")}</td>
          <td class="muted">${esc(it.batch_seq_no || "—")}</td>
          <td>${esc(it.beer_type || "—")}</td>
          <td>${it.v_l != null ? it.v_l.toLocaleString("vi-VN") : "—"}</td>
          <td><span class="badge critical">Thấp</span></td>
        </tr>`).join("")}</tbody></table></div>`
        : `<div class="muted">Không có mẻ lọc nào dưới ngưỡng Thấp trong 5 ngày gần nhất.</div>`}
    </div>`;
  // Đã chiết nhưng chưa duyệt: mẻ chiết đã bấm "Kết thúc" (ended_at có giá trị) nhưng chưa được
  // Giám đốc SX duyệt nhập kho (services/dashboard.py::bottled_not_approved_report) — trước đây
  // không có báo cáo/bộ lọc riêng cho khoảng trống này nên hàng chiết xong có thể nằm chờ vô thời
  // hạn mà không ai để ý.
  const bnaItems = (bottledNotApproved && bottledNotApproved.items) || [];
  const bnaPanel = `
    <div class="panel" style="flex:1;min-width:280px;margin-bottom:0">
      <h2>⏳ Đã chiết chưa duyệt ${bnaItems.length ? `<span class="muted">(${bnaItems.length})</span>` : ""}</h2>
      ${bnaItems.length ? `<div class="tablewrap" style="max-height:240px;overflow:auto"><table>
        <thead><tr><th>Lô chiết</th><th>Sản phẩm</th><th>Loại bia</th><th>Chờ (giờ)</th></tr></thead>
        <tbody>${bnaItems.map(it => `<tr style="cursor:pointer" data-goto="process" data-gotosub="chiet" tabindex="0" role="button">
          <td>${esc(it.bottle_code || "—")}</td>
          <td>${esc(it.finished_product_name || it.finished_product_code || "—")}</td>
          <td class="muted">${esc(it.beer_type || "—")}</td>
          <td><b style="color:${it.hours_waiting > 24 ? "var(--red)" : "var(--orange)"}">${it.hours_waiting}</b></td>
        </tr>`).join("")}</tbody></table></div>`
        : `<div class="muted">Không có mẻ chiết nào đang chờ duyệt.</div>`}
    </div>`;
  // Deviation/CAPA quá hạn xử lý (services/dashboard.py::overdue_action_alerts) — gộp cả 2
  // loại vì cùng ý nghĩa "còn mở, đã qua hạn", chỉ khác nơi xử lý tiếp (Deviation → tab Chất
  // lượng, CAPA → tab QC Lab).
  const overdueItems = (overdueActions && overdueActions.items) || [];
  const overduePanel = `
    <div class="panel" style="flex:1;min-width:280px;margin-bottom:0">
      <h2>⏰ Deviation/CAPA quá hạn ${overdueItems.length ? `<span class="muted">(${overdueItems.length})</span>` : ""}</h2>
      ${overdueItems.length ? `<div class="tablewrap" style="max-height:240px;overflow:auto"><table style="font-size:12px">
        <thead><tr><th>Mã</th><th>Tiêu đề</th><th>Mức</th><th>Quá hạn</th></tr></thead>
        <tbody>${overdueItems.map(it => `<tr style="cursor:pointer" data-goto="${it.kind === "capa" ? "qclab" : "quality"}" tabindex="0" role="button">
          <td><code class="k">${esc(it.code)}</code></td>
          <td class="muted">${esc(it.title || "—")}</td>
          <td>${badge(it.severity)}</td>
          <td><b style="color:var(--red)">${it.days_overdue} ngày</b></td>
        </tr>`).join("")}</tbody></table></div>`
        : `<div class="muted">Không có Deviation/CAPA nào quá hạn xử lý.</div>`}
    </div>`;
  const alertsHtml = alerts ? `
    <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:stretch;margin-bottom:16px">
      ${miniAlertPanel("Cảnh báo QC", "🚨", qcFailItems, "Không có chỉ tiêu QC nào đang fail.",
        { label: "Chỉ tiêu fail", render: it => `<b style="color:var(--red)">${it.fail_param_count}</b>` }, "qc")}
      ${miniAlertPanel("Hold / Release", "🔒", holdItems, "Không có lô nào đang giữ.",
        { label: "Trạng thái", render: () => `<span class="badge on_hold">${REASON_LABEL.on_hold}</span>` }, "hold")}
      ${miniAlertPanel("Deviation", "📋", devItems, "Không có deviation nào đang mở.",
        { label: "Số lượng mở", render: it => `<span class="badge on_hold">${it.deviation_count}</span>` }, "dev")}
      ${lowYieldPanel}
      ${bnaPanel}
      ${overduePanel}
    </div>` : "";
  // Tank đang lên men theo số ngày lên men so ngày quy định — 2 dạng xem (thanh liên tục + lưới ô
  // màu), nhóm theo loại dịch bia rồi sắp theo số ngày quá hạn giảm dần trong từng nhóm. Chỉ lấy
  // tank đang thật sự lên men (status="len_men", xem services/derived.py::ferment_status) và có
  // khai báo ngày lên men chuẩn (ferment_days_std) — thiếu 1 trong 2 thì không xét được quá/còn hạn.
  const FERMENT_STAGE_BG = { accent: "#E7F0FB", success: "#E4F3EA", warning: "#FBEEDD", danger: "#FBE7E7" };
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
  const fermentGroupHead = (product, isFirst) => `<div style="font-size:12px;font-weight:700;color:var(--text);
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
      <div style="position:relative;height:20px;background:var(--panel2);border-radius:3px;overflow:hidden;display:flex">
        <div style="width:${basePct}%;height:100%;background:var(--blue)"></div>
        <div style="width:${overPct}%;height:100%;background:var(--red)"></div>
        <div style="position:absolute;inset:0;display:flex;align-items:center;padding-left:8px;font-size:11px;color:#fff;font-weight:700">${it.days}/${it.std} ngày</div>
      </div>
      <div style="font-size:12px;font-weight:700;color:${it.over > 0 ? "var(--red)" : "var(--muted)"}">${label}</div>
    </div>`;
    fermentGridHtml += `<div style="position:relative;background:${FERMENT_STAGE_BG[it.stage]};border-radius:6px;padding:6px 8px;text-align:center">
      ${fermentQcBadge(it.qcFail, "position:absolute;top:-6px;right:-6px", it.lmCode, it.productId)}
      <div style="font-size:12px;font-weight:700;color:${FERMENT_STAGE_FG[it.stage]}">${esc(it.tank)}</div>
      <div style="font-size:10px;color:var(--muted)">${it.days}/${it.std} ngày</div>
    </div>`;
  });
  if (gridOpen) fermentGridHtml += `</div>`;
  if (!fermentTankItems.length) {
    fermentBarHtml = '<div class="muted">Không có tank nào đang lên men.</div>';
    fermentGridHtml = fermentBarHtml;
  }
  const fermentLegendHtml = FERMENT_STAGE_ORDER.map(s => `
    <span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px;font-size:11px;color:var(--muted)">
      <span style="width:9px;height:9px;border-radius:2px;background:${FERMENT_STAGE_FG[s]};display:inline-block"></span>${FERMENT_STAGE_LABEL[s]}</span>`).join("")
    + `<span style="display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--muted)">${fermentQcBadge(1)} Số chỉ tiêu CT chính/phụ đang fail</span>`;

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
    <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:stretch;margin-bottom:16px">
      <div class="panel" style="flex:1;min-width:320px;margin-bottom:0">
        <h2>📦 Tồn kho thành phẩm cần chú ý (theo tuổi lô)</h2>
        <div class="muted" style="margin-bottom:8px">Các lô từ mức 🟡 Chú ý trở lên — xem đầy đủ tại <button class="btn sm sec" data-goto="wms" data-gotosub="aging" style="padding:1px 8px">Kho TP › Tồn kho theo tuổi</button></div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;padding:10px 12px;background:var(--panel2);border:1px solid var(--border);border-radius:10px">${agingKpiHtml}</div>
        <div style="margin-bottom:8px">${agingLegendHtml}</div>
        <div id="db_aging_chart">${CH.agingBars(agingChartDisplay.slice(0, AGING_CHART_LIMIT), { max: agingAxisMax, axisLabel: "Số ngày tồn kho" })}</div>
        ${agingMoreCount > 0 ? `<button type="button" class="btn sm sec" id="db_aging_more" data-expanded="0" style="margin-top:8px">Xem thêm (${agingMoreCount})</button>` : ""}
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
    <div class="panel"><h2>Audit gần đây</h2>${tableAudit(audit)}</div>
    <div class="panel"><h2>Mẻ gần đây</h2>${tableBatches(batches.slice(0, 8))}</div>`;

  document.querySelectorAll("#view-dashboard [data-goto]").forEach(el => {
    el.onclick = () => {
      if (el.dataset.scope) PENDING_QUALITY_SCOPE = { key: el.dataset.scope, kind: el.dataset.scopekind || "hold" };
      gotoView(el.dataset.goto, el.dataset.gotosub || null);
    };
  });
  if ($("db_aging_more")) {
    $("db_aging_more").onclick = () => {
      const btn = $("db_aging_more");
      const expanding = btn.dataset.expanded === "0";
      $("db_aging_chart").innerHTML = CH.agingBars(
        expanding ? agingChartDisplay : agingChartDisplay.slice(0, AGING_CHART_LIMIT),
        { max: agingAxisMax, axisLabel: "Số ngày tồn kho" });
      btn.dataset.expanded = expanding ? "1" : "0";
      btn.textContent = expanding ? "Thu gọn" : `Xem thêm (${agingMoreCount})`;
    };
  }
  document.querySelectorAll("#view-dashboard [data-minimore]").forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const key = btn.dataset.minimore;
      const rows = document.querySelectorAll(`#view-dashboard .miniextra-${key}`);
      const expanding = rows[0] && rows[0].style.display === "none";
      rows.forEach(r => r.style.display = expanding ? "" : "none");
      btn.textContent = expanding ? "Thu gọn" : `Xem thêm (${btn.dataset.minimorecount})`;
    };
  });
  document.querySelectorAll("#view-dashboard [data-fermqc]").forEach(el => {
    el.onclick = () => {
      const [lm, pid] = el.dataset.fermqc.split("|");
      openFermentQcFailModal(lm, pid || null);
    };
  });
  wireAuditDetail();
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
  if ($("lowyield_days")) $("lowyield_days").onchange = () => {
    SUB.dashboard_low_yield_days = parseInt($("lowyield_days").value);
    render("dashboard");
  };
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

// Target/ca do người dùng tự đặt cho biểu đồ sản lượng chiết theo ca ở Dashboard — lưu trình
// duyệt (localStorage, không phải cấu hình chung của nhà máy) vì đây chỉ là đường tham chiếu
// hiển thị cho riêng người xem, không ảnh hưởng số liệu/logic nghiệp vụ nào khác.
function chietTarget(key) {
  return parseFloat(localStorage.getItem("mes_chiet_target_" + key)) || 0;
}
function setChietTarget(key, value) {
  if (value > 0) localStorage.setItem("mes_chiet_target_" + key, String(value));
  else localStorage.removeItem("mes_chiet_target_" + key);
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
  // key = "lon"/"keg" — dùng để lưu/đọc target riêng từng dây chuyền (xem chietTarget).
  const block = (key, title, plantNote, unit, results) => {
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
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap">
        <div>
          <div style="font-size:16px;font-weight:700;margin-bottom:2px">${title}</div>
          <div class="muted" style="font-size:12px;margin-bottom:6px">${esc(plantNote)}</div>
        </div>
        <div style="display:flex;align-items:center;gap:6px">
          <label class="muted" style="font-size:12px;white-space:nowrap">Target/ca (${esc(unit)})</label>
          <input type="number" min="0" step="1" data-chiet-target="${key}" value="${chietTarget(key) || ""}" style="width:90px" placeholder="—"/>
        </div>
      </div>
      ${anyGap ? `<div style="color:var(--orange,#f5a623);font-size:12px;margin-bottom:6px">⚠ Có khoảng trống dữ liệu trong CSDL nguồn ở 1+ ngày/ca.</div>` : ""}
      <div class="muted" style="font-size:12px;margin-bottom:4px">Tổng 5 ngày: <b style="color:var(--green)">${grandTotal.toLocaleString("vi-VN")} ${esc(unit)}</b></div>
      <div data-chiet-chart="${key}">${CH.groupedN(dayLabels, series, { unit, height: 130, target: chietTarget(key) })}</div>
    </div>`;
  };

  $("db_chiet_data").innerHTML = `<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:stretch">
    <div style="flex:1;min-width:280px">${block("lon", "🥫 Dây chuyền 30.000 lon/giờ", "NM Đông Mai", "lon", lonDays)}</div>
    <div style="flex:1;min-width:280px">${block("keg", "🛢️ Dây chuyền 400 keg/giờ", "NM Hạ Long", "keg", kegDays)}</div>
  </div>`;
  document.querySelectorAll("#db_chiet_data [data-goto-intg]").forEach(b => b.onclick = () => gotoView("integration", "dbconn"));
  // Đổi target chỉ vẽ lại đúng SVG của dây chuyền đó (dùng lại series đã tải, không gọi lại API).
  document.querySelectorAll("#db_chiet_data [data-chiet-target]").forEach(inp => {
    inp.onchange = () => {
      const key = inp.dataset.chietTarget;
      setChietTarget(key, parseFloat(inp.value) || 0);
      const results = key === "lon" ? lonDays : kegDays;
      const unit = key === "lon" ? "lon" : "keg";
      const series = [1, 2, 3].map((ca, i) => ({
        label: `Ca ${ca}`, color: caColors[i],
        values: results.map(r => r.ok ? ((r.rpt.by_ca.find(c => c.ca === ca) || {}).value || 0) : 0),
      }));
      const chartEl = document.querySelector(`#db_chiet_data [data-chiet-chart="${key}"]`);
      if (chartEl) chartEl.innerHTML = CH.groupedN(dayLabels, series, { unit, height: 130, target: chietTarget(key) });
    };
  });
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
        <div class="muted" style="font-size:12px;margin-bottom:4px">Tổng 5 ngày: <b style="color:var(--green)">${grandTotal.toLocaleString("vi-VN")} kWh</b></div>
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
    safe("/brewing/orders"), safe("/brewing/filter-master-orders"), safe("/lots"),
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
      <h2 id="o_form_title">Tạo lệnh sản xuất (ERP)</h2>
      <div class="muted" style="margin-bottom:6px">Chọn Sản phẩm rồi chọn <b>Công thức</b> đang hiệu lực của sản phẩm đó (tuỳ chọn) — dùng để xem trước
        định mức NVL (BOM), chia đều theo <b>Số mẻ kế hoạch</b>. Đây chỉ là thông tin kế hoạch/tham khảo, KHÔNG lưu thành dòng định mức riêng —
        SL kế hoạch/ĐVT ở trên vẫn là nguồn sự thật duy nhất cho sản lượng.</div>
      <div class="row">
        <div class="field"><label>Mã lệnh</label><input id="o_code" placeholder="PO-..." /></div>
        <div class="field"><label>Sản phẩm</label><select id="o_prod">${opts}</select></div>
        <div class="field"><label>SL kế hoạch</label><input id="o_qty" type="number" value="50000" /></div>
        <div class="field"><label>ĐVT</label><input id="o_uom" value="L" size="4" /></div>
        <div class="field"><label>Ưu tiên</label><input id="o_pri" type="number" value="5" size="3" /></div>
        <div class="field"><label>Số mẻ kế hoạch</label><input id="o_batches" type="number" min="1" value="1" style="width:80px"/></div>
      </div>
      <div id="o_recipe_box"></div>
      <div class="row">
        <div class="field"><label>Người ra lệnh</label><input id="o_issuedby" placeholder="(tuỳ chọn)"/></div>
        <div class="field"><label>Đơn vị thực hiện</label><input id="o_exec" value="Phân xưởng bia Đông Mai"/></div>
        <div class="field"><label>Thủ kho</label><input id="o_kho" value="Thủ kho"/></div>
      </div>
      <div class="row">
        <div class="field" style="flex:1"><label>Căn cứ</label><input id="o_refnote" placeholder="VD: Căn cứ theo kế hoạch sản xuất..."/></div>
        <div class="field"><label>Thời gian bắt đầu</label><input id="o_start" type="datetime-local"/></div>
        <div class="field"><label>Thời gian kết thúc</label><input id="o_end" type="datetime-local"/></div>
      </div>
      <div class="row">
        <div class="field" style="flex:1"><label>Biện pháp an toàn</label><input id="o_safety" placeholder="(tuỳ chọn)"/></div>
      </div>
      <div class="row"><button class="btn sec" id="o_bom_preview" style="align-self:flex-end">📋 Xem NVL (đủ/thiếu tồn)</button>
        <button class="btn" id="o_save" style="align-self:flex-end">Tạo lệnh</button>
        <span id="o_cancel_wrap"></span></div>
      <div id="o_bom_box"></div>
    </div>
    <div class="panel"><h2>Danh sách lệnh</h2>
      <input class="searchbox" data-tbl="t_po" placeholder="Tìm theo mã lệnh, sản phẩm, trạng thái..."/>
      <div class="tablewrap"><table id="t_po"><thead><tr><th>Mã</th><th>Sản phẩm</th><th>SL</th><th>Ưu tiên</th>
        <th>Tên công thức</th><th>Version</th><th>Ghi chú công thức</th><th>Số mẻ (KH)</th><th>Trạng thái</th><th>Tạo lúc</th><th></th></tr></thead>
      <tbody>${orders.map(o => `<tr><td><code class="k">${esc(o.order_code)}</code></td>
        <td>${esc(prodName(o.product_id))}</td><td>${o.planned_qty} ${o.uom}</td>
        <td>${o.priority}</td>
        <td class="muted">${esc(o.recipe_name || "—")}</td>
        <td class="muted">${o.recipe_code ? `v${o.recipe_version_no}` : "—"}</td>
        <td class="muted">${esc(o.recipe_note || "—")}</td>
        <td class="muted">${o.planned_batch_count ?? "—"}</td>
        <td>${badge(o.status)}</td><td class="muted">${fmt(o.created_at)}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-vieworder="${esc(o.order_id)}">Xem</button>
          <button class="btn sm sec" data-printorder="${esc(o.order_id)}">🖨️ In</button>
          ${!o.is_executed ? `<button class="btn sm sec" data-editorder="${esc(o.order_id)}">Sửa</button>
          <button class="btn sm sec" data-delorder="${esc(o.order_id)}">Xóa</button>` : ""}</td></tr>`).join("") ||
        `<tr><td colspan=11 class="muted">Chưa có lệnh sản xuất nào.</td></tr>`}</tbody></table></div>
    </div>`;
  }

  else if (sec === "lenhnau") {
    const [orders, recipes, lnProducts] = await Promise.all([
      GET("/brewing/orders"), GET("/recipes").catch(() => []), GET("/products").catch(() => [])]);
    CACHE.recipesLn = recipes;
    CACHE.products = lnProducts;
    const recipeOpts = recipes.map(r => `<option value="${esc(r.recipe_id)}">${esc(r.code)} — ${esc(r.name)}</option>`).join("");
    body = `<div class="panel"><h2 id="lo_form_title">Tạo Lệnh nấu</h2>
      <div class="muted" style="margin-bottom:6px">Chọn <b>Loại bia</b> rồi chọn <b>Version</b> đang hiệu lực — định mức NVL (BOM) tự nạp
        theo Số mẻ kế hoạch, xem trước (đủ/thiếu tồn) trước khi tạo lệnh. Có thể ứng với nhiều mã nấu (tạo ở tab "Nấu-Lọc-Chiết → Nấu") —
        sản lượng thực tế cộng dồn qua các mã nấu tới khi đạt kế hoạch (±sai số) thì lệnh hoàn thành, không chọn được nữa.</div>
      <div class="row">
        <div class="field"><label>Số lệnh</label><input id="lo_code" placeholder="VD: 36/PXSXBĐM-T6/2026"/></div>
        <div class="field"><label>Chọn loại bia</label><select id="lo_recipe"><option value="">(chọn loại bia)</option>${recipeOpts}</select></div>
        <button class="btn sec" id="lo_bom_preview" style="align-self:flex-end">📋 Xem NVL (đủ/thiếu tồn)</button>
      </div>
      <div id="lo_recipe_box"></div>
      <div class="row">
        <div class="field"><label>Số mẻ kế hoạch</label><input id="lo_batches" type="number" min="1" value="1"/></div>
        <div class="field"><label>Sản lượng nấu kế hoạch (hl)</label><input id="lo_volplan" type="number" placeholder="VD: 100"/></div>
        <div class="field"><label>Sai số cho phép (±hl)</label><input id="lo_voltol" type="number" value="0"/></div>
      </div>
      <div class="row">
        <div class="field"><label>Người ra lệnh</label><input id="lo_issuedby" placeholder="(tuỳ chọn)"/></div>
        <div class="field"><label>Đơn vị thực hiện</label><input id="lo_exec" value="Phân xưởng bia Đông Mai"/></div>
        <div class="field"><label>Thủ kho</label><input id="lo_kho" value="Thủ kho"/></div>
      </div>
      <div class="row">
        <div class="field"><label>Thời gian bắt đầu</label><input id="lo_start" type="datetime-local"/></div>
        <div class="field"><label>Thời gian kết thúc</label><input id="lo_end" type="datetime-local"/></div>
      </div>
      <div class="row"><button class="btn" id="lo_add" style="align-self:flex-end">Tạo lệnh</button>
        <span id="lo_cancel_wrap"></span></div>
      <div id="lo_bom_box"></div>
    </div>
    <div class="panel"><h2>Danh sách Lệnh nấu <span class="muted">(${orders.length})</span></h2>
      <input class="searchbox" data-tbl="t_lenhnau" placeholder="Tìm theo số lệnh, dịch bia, trạng thái..."/>
      <div class="tablewrap"><table id="t_lenhnau"><thead><tr><th>Số lệnh</th><th>Loại bia</th><th>Dịch bia</th>
        <th>Version</th><th>Ghi chú công thức</th>
        <th>Thực tế/KH (hl)</th><th>Ngày lập</th><th>Trạng thái</th><th></th></tr></thead>
      <tbody>${orders.map(o => `<tr>
        <td class="code">${esc(o.order_code)}</td>
        <td class="muted">${esc(o.recipe_name || "—")}</td>
        <td>${esc(o.product_code || o.product_desc || "—")}</td>
        <td class="muted">${o.recipe_code ? "v" + o.recipe_version_no : "—"}</td>
        <td class="muted">${esc(o.recipe_note || "—")}</td>
        <td class="muted">${o.actual_volume_hl}/${o.planned_volume_hl}</td>
        <td class="muted">${fmt(o.created_at)}</td>
        <td>${o.is_complete
          ? `<span style="color:var(--green)">✓ Hoàn thành</span>`
          : (o.is_executed
              ? `<span style="color:var(--orange)">Đang nấu</span>`
              : `<span class="muted">Chưa thực hiện</span>`)}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-viewlo="${esc(o.brew_order_id)}">Xem</button>
          <button class="btn sm sec" data-printlo="${esc(o.brew_order_id)}">🖨️ In</button>
          ${!o.is_executed ? `<button class="btn sm sec" data-editlo="${esc(o.brew_order_id)}">Sửa</button>
          <button class="btn sm sec" data-dello="${esc(o.brew_order_id)}">Xóa</button>` : ""}</td></tr>`).join("") ||
        `<tr><td colspan=9 class="muted">Chưa có lệnh nấu nào.</td></tr>`}</tbody></table></div></div>`;
  }

  else if (sec === "lenhloc") {
    const ynLf = YEARS.lenhloc;
    const [masters, fermentsData, materialsLf, bbtTanksLf, finishedProductsLf, materialGroupsLf, materialAltGroupsLf] = await Promise.all([
      GET("/brewing/filter-master-orders" + (ynLf ? "?" + ynLf.map(y => "years=" + y).join("&") : "")),
      GET("/brewing/ferments"), GET("/materials"),
      GET("/brewing/bbt-tanks").catch(() => []), GET("/finished-products"),
      GET("/material-groups"), GET("/material-alt-groups")]);
    // Tank đã lọc hết (on_hand_cct về 0 hoặc âm — derived.ferment_status trả "da_loc_het")
    // không còn dịch để lọc thêm nữa, dù đã KCS duyệt cũng không hiện ra để chọn lại.
    approvedTanksLf = fermentsData.items.filter(f => f.qc_approved && f.status !== "da_loc_het");
    // Tank thành phẩm (BBT) đủ điều kiện làm NGUỒN lọc lại — đã lọc xong + KCS duyệt hết
    // (xem services/filter_order.py::available_bbt_tanks); còn khả dụng bao nhiêu (sau khi
    // trừ phần đã bị lệnh khác giữ chỗ) hiện ở remaining_hl.
    availableBbtTanksLf = bbtTanksLf.filter(t => t.eligible_for_refilter_source);
    CACHE.materialsLf = materialsLf;
    CACHE.finishedProductsLf = finishedProductsLf;
    CACHE.materialGroupsLf = materialGroupsLf;
    CACHE.materialAltGroupsLf = materialAltGroupsLf;
    body = `<div class="panel"><h2>Tạo Lệnh lọc</h2>
      <div class="muted" style="margin-bottom:6px">1 Lệnh lọc (số lệnh) có thể chứa nhiều "Tank thành phẩm" bên trong — mỗi tank tự chọn
        <b>Không phối</b> (1 tank lên men) hoặc <b>Phối</b> (2+ tank, phải cùng 1 dịch bia), tự có vật tư riêng, tự khai báo thể tích dịch kế hoạch
        riêng. Khi in sẽ in chung 1 tờ gồm tất cả tank. Mỗi bản ghi lọc thật (ở tab "Nấu-Lọc-Chiết → Lọc") chọn đúng 1 tank thành phẩm CHƯA hoàn thành
        để thực hiện — sản lượng cộng dồn tới khi đạt thể tích kế hoạch (±sai số) của tank đó thì không chọn được nữa.</div>
      <div class="row">
        <div class="field"><label>Số lệnh</label><input id="lf_code" placeholder="VD: LOC-0715"/></div>
        <div class="field" style="flex:1"><label>Ghi chú</label><input id="lf_note" placeholder="(tuỳ chọn)"/></div>
      </div>
      <div id="lf_children"></div>
      <div class="row"><button class="btn sec" id="lf_addchild">+ Thêm tank thành phẩm</button></div>
      <div class="row"><button class="btn" id="lf_add" style="align-self:flex-end">Tạo lệnh lọc</button>
        <span id="lf_cancel_wrap"></span></div></div>
      <div class="panel"><h2>Danh sách Lệnh lọc <span class="muted">(${masters.length})</span></h2>
      ${yearFilterControl("lenhloc", ynLf)}
      <input class="searchbox" data-tbl="t_lenhloc" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_lenhloc"><thead><tr><th>Số lệnh</th><th>Loại lọc</th>
        <th>Thể tích (hl)</th><th>Ngày lập</th><th>Trạng thái</th><th></th></tr></thead>
      <tbody>${masters.map(m => `<tr>
        <td class="code">${esc(m.order_code)}</td>
        <td class="muted">${m.children.map((c, i) => `${m.children.length > 1 ? `#${i + 1} ` : ""}${c.blend_mode === "phoi" ? "Phối" : "Không phối"}
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
  if (sec === "lenhloc") wireYearFilter("lenhloc", "orders");

  if (sec === "po") {
    let poRecipeVersionId = "";
    let poActiveVersions = [];
    let poRecipe = null;
    let editingOrderId = null;
    // Cho sửa lại SL lấy tại Kho công ty/phân xưởng + chọn thành viên Nhóm vật tư thay thế
    // trước khi lưu — mirror hệt Lệnh nấu (lnQtyOverrides/lnMemberSelection/
    // lnMemberQtySplits, xem renderLnPreview), cùng dạng state phẳng (1 Lệnh SX = 1 dòng).
    let poQtyOverrides = {};
    let poMemberSelection = {};
    let poMemberQtySplits = {};
    let poPreviewLines = [];
    let poAltGroupsCache = null;
    const getPoAltGroups = async () => poAltGroupsCache || (poAltGroupsCache = await GET("/material-alt-groups").catch(() => []));
    function setPoFormMode(editing) {
      $("o_form_title").textContent = editing ? "Sửa lệnh sản xuất (ERP)" : "Tạo lệnh sản xuất (ERP)";
      $("o_save").textContent = editing ? "Lưu chỉnh sửa lệnh" : "Tạo lệnh";
      $("o_cancel_wrap").innerHTML = editing ? `<button class="btn sm sec" id="o_canceledit" style="align-self:flex-end">Hủy sửa</button>` : "";
      if (editing) $("o_canceledit").onclick = () => render("orders");
    }
    // Nạp lại state từ dòng NVL ĐÃ LƯU (get_order) khi vào chế độ Sửa — chỉ khôi phục lựa chọn,
    // KHÔNG tự hiện lại bảng preview (giống Lệnh nấu: phải bấm "Xem NVL" lại mới thấy, lúc
    // đó renderPoPreview sẽ merge state này vào định mức mới nạp từ Công thức).
    function resetPoOverridesFromSavedLines(lines) {
      poQtyOverrides = {}; poMemberSelection = {}; poMemberQtySplits = {};
      (lines || []).forEach(l => {
        if (l.is_header) return;
        const seq = String(l.seq);
        const isMemberDeclared = l.member_breakdown && l.member_breakdown.length && l.member_breakdown.some(mb => mb.qty_per_batch != null);
        if (isMemberDeclared) {
          poMemberSelection[seq] = l.member_breakdown.map(mb => mb.material_id).filter(Boolean);
          const splits = {};
          l.member_breakdown.forEach(mb => { if (mb.material_code) splits[mb.material_code] = { fromCompany: mb.qty_from_company, fromWorkshop: mb.qty_from_workshop }; });
          poMemberQtySplits[seq] = splits;
        } else if (l.qty_from_company != null || l.qty_from_workshop != null) {
          poQtyOverrides[seq] = { fromCompany: l.qty_from_company, fromWorkshop: l.qty_from_workshop };
        }
      });
    }

    async function renderPoRecipeBox(preselectVersionId) {
      const box = $("o_recipe_box");
      const productId = $("o_prod").value;
      if (!productId) { box.innerHTML = ""; poActiveVersions = []; poRecipe = null; poRecipeVersionId = ""; return; }
      box.innerHTML = `<div class="muted" style="margin-top:6px">Đang tải công thức...</div>`;
      try {
        const recipes = await GET(`/recipes`);
        if ($("o_prod").value !== productId) return; // đã đổi Sản phẩm khác trong lúc chờ — bỏ kết quả cũ
        const product = (CACHE.products || []).find(p => p.product_id === productId);
        poRecipe = (recipes || []).find(r => r.beer_type_id === (product && product.beer_type_id)) || null;
        poActiveVersions = poRecipe
          ? (await GET(`/recipes/${poRecipe.recipe_id}/versions`)).filter(v => v.state === "effective" && v.product_id === productId)
          : [];
        if (!poActiveVersions.length) {
          box.innerHTML = `<div class="muted" style="margin-top:6px">Sản phẩm này chưa có công thức hiệu lực — vẫn tạo được lệnh, chỉ không xem trước được NVL.</div>`;
          poRecipeVersionId = ""; return;
        }
        poRecipeVersionId = preselectVersionId && poActiveVersions.some(v => v.version_id === preselectVersionId)
          ? preselectVersionId : (poActiveVersions.length === 1 ? poActiveVersions[0].version_id : "");
        box.innerHTML = `<div class="row" style="margin-top:6px">
          <div class="field"><label>Công thức</label><select id="o_recipe">
            <option value="">(không chọn — bỏ qua BOM)</option>
            ${poActiveVersions.map(v => `<option value="${esc(v.version_id)}" ${v.version_id === poRecipeVersionId ? "selected" : ""}>
              ${esc(poRecipe.code)} v${v.version_no} · ${v.base_qty} ${esc(v.base_uom)}</option>`).join("")}
          </select></div>
          <div class="field" style="flex:1"><label>Ghi chú công thức</label><div class="muted" id="o_recipe_note" style="margin-top:8px"></div></div>
        </div>`;
        const showNote = () => {
          const v = poActiveVersions.find(x => x.version_id === poRecipeVersionId);
          $("o_recipe_note").textContent = v && v.change_reason ? v.change_reason : "—";
        };
        showNote();
        $("o_recipe").onchange = () => { poRecipeVersionId = $("o_recipe").value; $("o_bom_box").innerHTML = ""; showNote(); };
      } catch (e) { box.innerHTML = ""; }
    }
    $("o_prod").onchange = () => { $("o_bom_box").innerHTML = ""; renderPoRecipeBox(); };
    if ($("o_prod").value) renderPoRecipeBox();

    // Bảng "Xem NVL" tương tác — mirror renderLnPreview (Lệnh nấu)
    // (state là poQtyOverrides/poMemberSelection/poMemberQtySplits module-scope ở trên, không
    // lồng trong 1 mảng children). SL lấy tại 2 kho + thành viên đã chọn được LƯU LẠI khi tạo/
    // sửa lệnh (xem services/orders.py::_persist_lines), không chỉ để xem tham khảo.
    async function renderPoPreview(lines) {
      poPreviewLines = lines;
      const box = $("o_bom_box");
      if (!lines.length) {
        box.innerHTML = `<div class="muted" style="margin-top:8px">Công thức này chưa khai báo NVL — không có định mức để xem.</div>`;
        return;
      }
      const altGroups = await getPoAltGroups();
      const ov = poQtyOverrides;
      const isMemberDeclared = (l) => l.member_breakdown && l.member_breakdown.length && l.member_breakdown.some(mb => mb.qty_per_batch != null);
      const rowsHtml = lines.map(l => {
        const seqKey = String(l.seq);
        if (isMemberDeclared(l)) {
          const grp = altGroups.find(g => g.code === l.material_group_code);
          const mode = grp ? grp.selection_mode : "single";
          let selected = poMemberSelection[seqKey];
          if (!selected || !selected.length) {
            selected = mode === "single" ? [l.member_breakdown[0].material_id] : l.member_breakdown.map(mb => mb.material_id);
            poMemberSelection[seqKey] = selected;
          }
          const selectedSet = new Set(selected);
          const selMembers = l.member_breakdown.filter(mb => selectedSet.has(mb.material_id));
          const dispQtyPerBatch = round3(selMembers.reduce((s, mb) => s + (mb.qty_per_batch || 0), 0));
          const dispQtyTotal = round3(selMembers.reduce((s, mb) => s + (mb.qty_total || 0), 0));
          const dispShortage = selMembers.length > 0 && selMembers.every(mb => mb.shortage);
          const memberRows = l.member_breakdown.map(mb => {
            const checked = selectedSet.has(mb.material_id);
            const inputType = mode === "multi" ? "checkbox" : "radio";
            const nameAttr = mode === "multi" ? "" : ` name="po_memsel_${seqKey}"`;
            const splitOv = ((poMemberQtySplits[seqKey] || {})[mb.material_code]) || {};
            const fromCompany = splitOv.fromCompany ?? mb.qty_from_company;
            const fromWorkshop = splitOv.fromWorkshop ?? mb.qty_from_workshop;
            const splitCells = checked
              ? `<td><input type="number" class="po_mem_qty_company" data-seq="${esc(seqKey)}" data-code="${esc(mb.material_code)}" value="${fromCompany ?? ""}" style="width:70px"/></td>
                 <td><input type="number" class="po_mem_qty_workshop" data-seq="${esc(seqKey)}" data-code="${esc(mb.material_code)}" value="${fromWorkshop ?? ""}" style="width:70px"/></td>`
              : `<td class="muted">—</td><td class="muted">—</td>`;
            return `<tr class="muted" style="font-size:12px">
              <td colspan="4" style="padding-left:24px"><label style="display:flex;align-items:center;gap:6px;cursor:pointer">
                <input type="${inputType}" class="po-memsel" data-seq="${esc(seqKey)}" data-mid="${esc(mb.material_id)}"${nameAttr} ${checked ? "checked" : ""}/>
                ${esc(mb.material_code)} — ${esc(mb.material_name)}</label></td>
              <td>${mb.qty_per_batch}</td><td>${mb.qty_total}</td>
              ${splitCells}
              <td>${mb.stock_company}</td><td>${mb.stock_workshop}</td>
              <td>${mb.shortage ? '<span class="badge on_hold">⚠ Thiếu</span>' : '<span class="badge available">✓ Đủ</span>'}</td></tr>`;
          }).join("");
          return `<tr class="${dispShortage ? "row-red" : ""}">
          <td>${esc(l.stt_label || "")}</td><td class="muted">—</td><td>${esc(l.material_name || "—")}
            <span class="muted" style="font-size:11px"> (nhóm — ${mode === "multi" ? "chọn nhiều mã" : "chọn 1 mã"})</span></td><td>${esc(l.uom || "")}</td>
          <td>${dispQtyPerBatch}</td><td>${dispQtyTotal}</td>
          <td colspan="2" class="muted">—</td>
          <td>${l.stock_company_snapshot ?? "—"}</td><td>${l.stock_workshop_snapshot ?? "—"}</td>
          <td>${selMembers.length === 0 ? '<span class="badge on_hold">⚠ Chưa chọn mã</span>'
            : (dispShortage ? '<span class="badge on_hold">⚠ Thiếu</span>' : '<span class="badge available">✓ Đủ</span>')}</td></tr>${memberRows}`;
        }
        const curOv = ov[seqKey] || {};
        const fromCompany = curOv.fromCompany ?? l.qty_from_company;
        const fromWorkshop = curOv.fromWorkshop ?? l.qty_from_workshop;
        return `<tr class="${l.shortage ? "row-red" : ""}">
        <td>${esc(l.stt_label || "")}</td><td class="muted">${esc(l.material_code || "—")}</td><td>${esc(l.material_name || "—")}</td><td>${esc(l.uom || "")}</td>
        <td>${l.qty_per_batch ?? "—"}</td><td>${l.qty_total ?? "—"}</td>
        <td>${l.is_header ? "" : `<input type="number" class="po_qty_company" data-seq="${seqKey}" value="${fromCompany ?? ""}" style="width:80px"/>`}</td>
        <td>${l.is_header ? "" : `<input type="number" class="po_qty_workshop" data-seq="${seqKey}" value="${fromWorkshop ?? ""}" style="width:80px"/>`}</td>
        <td>${l.stock_company_snapshot ?? "—"}</td><td>${l.stock_workshop_snapshot ?? "—"}</td>
        <td>${!l.is_header
          ? (l.shortage ? '<span class="badge on_hold">⚠ Thiếu</span>' : '<span class="badge available">✓ Đủ</span>')
          : '<span class="muted">—</span>'}</td></tr>${bomMemberRowsHtml(l, 8, 1)}`;
      }).join("");
      const shortageCount = lines.filter(l => isMemberDeclared(l)
        ? new Set(poMemberSelection[String(l.seq)] || []).size === 0
        : l.shortage).length;
      box.innerHTML = `<div class="panel" style="margin-top:8px">
        <h3 style="font-size:14px">Xem trước định mức NVL ${shortageCount
          ? `<span style="color:var(--red)">— ⚠ ${shortageCount} dòng thiếu tồn/chưa chọn mã</span>`
          : `<span style="color:var(--green)">— ✓ đủ tồn tất cả</span>`}</h3>
        <div class="muted" style="margin-bottom:6px">Cột "SL lấy" là GỢI Ý (ưu tiên dùng hết tồn đang có tại Kho phân xưởng, phần
          còn thiếu lấy tại Kho công ty) — có thể sửa lại trước khi tạo lệnh, sẽ được LƯU LẠI (không chỉ để xem). Dòng theo
          Nhóm vật tư có định mức riêng từng vật tư — chọn vật tư áp dụng ngay bên dưới, Nhu cầu chỉ tính mã đã chọn.</div>
        <div class="tablewrap"><table><thead><tr><th>STT</th><th>Mã NVL</th><th>Tên NVL</th><th>ĐVT</th><th>Nhu cầu 1 mẻ</th>
          <th>Nhu cầu Tổng mẻ</th><th>SL lấy tại Kho công ty</th><th>SL lấy tại Kho phân xưởng</th>
          <th>Tồn Kho công ty</th><th>Tồn Kho phân xưởng</th><th>Trạng thái</th></tr></thead>
        <tbody>${rowsHtml}</tbody></table></div></div>`;
      box.querySelectorAll(".po_qty_company").forEach(inp => inp.onchange = () => {
        const seq = inp.dataset.seq;
        poQtyOverrides[seq] = { ...(poQtyOverrides[seq] || {}), fromCompany: inp.value === "" ? null : parseFloat(inp.value) };
      });
      box.querySelectorAll(".po_qty_workshop").forEach(inp => inp.onchange = () => {
        const seq = inp.dataset.seq;
        poQtyOverrides[seq] = { ...(poQtyOverrides[seq] || {}), fromWorkshop: inp.value === "" ? null : parseFloat(inp.value) };
      });
      box.querySelectorAll(".po-memsel").forEach(inp => inp.onchange = () => {
        const seq = inp.dataset.seq;
        if (inp.type === "radio") {
          poMemberSelection[seq] = [inp.dataset.mid];
        } else {
          const cur = new Set(poMemberSelection[seq] || []);
          if (inp.checked) cur.add(inp.dataset.mid); else cur.delete(inp.dataset.mid);
          poMemberSelection[seq] = [...cur];
        }
        renderPoPreview(poPreviewLines);
      });
      box.querySelectorAll(".po_mem_qty_company").forEach(inp => inp.onchange = () => {
        const seq = inp.dataset.seq, code = inp.dataset.code;
        poMemberQtySplits[seq] = { ...(poMemberQtySplits[seq] || {}) };
        poMemberQtySplits[seq][code] = { ...(poMemberQtySplits[seq][code] || {}), fromCompany: inp.value === "" ? null : parseFloat(inp.value) };
      });
      box.querySelectorAll(".po_mem_qty_workshop").forEach(inp => inp.onchange = () => {
        const seq = inp.dataset.seq, code = inp.dataset.code;
        poMemberQtySplits[seq] = { ...(poMemberQtySplits[seq] || {}) };
        poMemberQtySplits[seq][code] = { ...(poMemberQtySplits[seq][code] || {}), fromWorkshop: inp.value === "" ? null : parseFloat(inp.value) };
      });
    }
    $("o_bom_preview").onclick = () => guard(async () => {
      if (!poRecipeVersionId) throw new Error("Chọn Công thức trước khi xem định mức NVL.");
      const batches = parseInt($("o_batches").value, 10) || 1;
      const lines = await GET(`/orders/bom-preview?recipe_version_id=${encodeURIComponent(poRecipeVersionId)}&planned_batch_count=${batches}`);
      await renderPoPreview(lines);
    });
    // Gộp 2 loại override trước khi gửi: SL lấy Company/Workshop (dòng thường) và thành viên
    // đã chọn (dòng Nhóm vật tư có định mức riêng — poMemberSelection giữ material_id, cần đổi
    // sang material_code vì server nhận selected_material_codes) — mirror lnBuildMaterialQtyOverrides.
    function poBuildMaterialQtyOverrides() {
      const out = {};
      for (const [seq, o] of Object.entries(poQtyOverrides)) {
        out[seq] = { qty_from_company: o.fromCompany ?? null, qty_from_workshop: o.fromWorkshop ?? null };
      }
      for (const [seq, materialIds] of Object.entries(poMemberSelection)) {
        const line = poPreviewLines.find(l => String(l.seq) === seq);
        const codeById = Object.fromEntries((line ? line.member_breakdown : []).map(mb => [mb.material_id, mb.material_code]));
        out[seq] = { ...(out[seq] || {}), selected_material_codes: materialIds.map(mid => codeById[mid]).filter(Boolean) };
      }
      for (const [seq, byCode] of Object.entries(poMemberQtySplits)) {
        const member_qty_splits = Object.fromEntries(Object.entries(byCode).map(([code, o]) =>
          [code, { qty_from_company: o.fromCompany ?? null, qty_from_workshop: o.fromWorkshop ?? null }]));
        out[seq] = { ...(out[seq] || {}), member_qty_splits };
      }
      return out;
    }

    $("o_save").onclick = () => guard(async () => {
      const payload = { order_code: $("o_code").value, product_id: $("o_prod").value,
        planned_qty: parseFloat($("o_qty").value), uom: $("o_uom").value, priority: parseInt($("o_pri").value),
        recipe_version_id: poRecipeVersionId || null,
        planned_batch_count: parseInt($("o_batches").value, 10) || null,
        issued_by: $("o_issuedby").value.trim() || null,
        executor_unit: $("o_exec").value.trim() || null,
        warehouse_keeper: $("o_kho").value.trim() || null,
        reference_note: $("o_refnote").value.trim() || null,
        start_date: $("o_start").value || null,
        end_date: $("o_end").value || null,
        safety_note: $("o_safety").value.trim() || null,
        material_qty_overrides: poBuildMaterialQtyOverrides() };
      if (editingOrderId) {
        await PUT(`/orders/${editingOrderId}`, payload);
        toast("Đã lưu lệnh sản xuất");
      } else {
        await POST("/orders", payload);
        toast("Đã tạo lệnh sản xuất");
      }
      render("orders");
    });

    document.querySelectorAll("[data-vieworder]").forEach(b => b.onclick = () => openProductionOrderModal(b.dataset.vieworder));
    document.querySelectorAll("[data-printorder]").forEach(b => b.onclick = () => guard(async () => {
      const o = await GET(`/orders/${b.dataset.printorder}`);
      printProductionOrder(o, o.lines);
    }));
    document.querySelectorAll("[data-editorder]").forEach(b => b.onclick = () => guard(async () => {
      const o = await GET(`/orders/${b.dataset.editorder}`);
      editingOrderId = o.order_id;
      $("o_code").value = o.order_code;
      $("o_prod").value = o.product_id;
      $("o_qty").value = o.planned_qty;
      $("o_uom").value = o.uom;
      $("o_pri").value = o.priority;
      $("o_batches").value = o.planned_batch_count || 1;
      $("o_issuedby").value = o.issued_by || "";
      $("o_exec").value = o.executor_unit || "";
      $("o_kho").value = o.warehouse_keeper || "";
      $("o_refnote").value = o.reference_note || "";
      $("o_start").value = o.start_date ? o.start_date.slice(0, 16) : "";
      $("o_end").value = o.end_date ? o.end_date.slice(0, 16) : "";
      $("o_safety").value = o.safety_note || "";
      resetPoOverridesFromSavedLines(o.lines);
      $("o_bom_box").innerHTML = "";
      await renderPoRecipeBox(o.recipe_version_id);
      setPoFormMode(true);
      $("o_code").scrollIntoView({ behavior: "smooth", block: "center" });
      toast(`Đang sửa lệnh ${o.order_code} — thay đổi rồi bấm "Lưu chỉnh sửa lệnh"`);
    }));
    document.querySelectorAll("[data-delorder]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa lệnh sản xuất này? Không thể hoàn tác.")) return;
      await DELETE(`/orders/${b.dataset.delorder}`);
      toast("Đã xóa lệnh sản xuất"); render("orders");
    }));
  }

  if (sec === "lenhnau") {
    let editingOrderId = null;
    let lnQtyOverrides = {};
    let lnMemberSelection = {};
    let lnMemberQtySplits = {};
    let lnPreviewLines = [];
    let lnAltGroupsCache = null;
    let lnActiveVersions = [];
    let lnRecipeVersionId = "";
    const getLnAltGroups = async () => lnAltGroupsCache || (lnAltGroupsCache = await GET("/material-alt-groups").catch(() => []));
    function setLoFormMode(editing) {
      $("lo_form_title").textContent = editing ? "Sửa Lệnh nấu" : "Tạo Lệnh nấu";
      $("lo_add").textContent = editing ? "Lưu chỉnh sửa lệnh" : "Tạo lệnh";
      $("lo_cancel_wrap").innerHTML = editing ? `<button class="btn sm sec" id="lo_canceledit" style="align-self:flex-end">Hủy sửa</button>` : "";
      if (editing) $("lo_canceledit").onclick = () => render("orders");
    }
    // Nạp lại state từ dòng NVL ĐÃ LƯU (get_order) khi vào chế độ Sửa — chỉ khôi phục lựa chọn,
    // KHÔNG tự hiện lại bảng preview (phải bấm "Xem NVL" lại mới thấy, lúc đó renderLnPreview
    // sẽ merge state này vào định mức mới nạp từ Công thức) — mirror resetPoOverridesFromSavedLines.
    function resetLnOverridesFromSavedLines(lines) {
      lnQtyOverrides = {}; lnMemberSelection = {}; lnMemberQtySplits = {};
      (lines || []).forEach(l => {
        if (l.is_header) return;
        const seq = String(l.seq);
        const isMemberDeclared = l.member_breakdown && l.member_breakdown.length && l.member_breakdown.some(mb => mb.qty_per_batch != null);
        if (isMemberDeclared) {
          lnMemberSelection[seq] = l.member_breakdown.map(mb => mb.material_id).filter(Boolean);
          const splits = {};
          l.member_breakdown.forEach(mb => { if (mb.material_code) splits[mb.material_code] = { fromCompany: mb.qty_from_company, fromWorkshop: mb.qty_from_workshop }; });
          lnMemberQtySplits[seq] = splits;
        } else if (l.qty_from_company != null || l.qty_from_workshop != null) {
          lnQtyOverrides[seq] = { fromCompany: l.qty_from_company, fromWorkshop: l.qty_from_workshop };
        }
      });
    }

    async function renderLnRecipeBox(preselectVersionId) {
      const box = $("lo_recipe_box");
      const recipeId = $("lo_recipe").value;
      if (!recipeId) { box.innerHTML = ""; lnActiveVersions = []; lnRecipeVersionId = ""; return; }
      box.innerHTML = `<div class="muted" style="margin-top:6px">Đang tải version...</div>`;
      try {
        const recipe = (CACHE.recipesLn || []).find(r => r.recipe_id === recipeId);
        if (!recipe) { box.innerHTML = ""; return; }
        lnActiveVersions = (await GET(`/recipes/${recipe.recipe_id}/versions`)).filter(v => v.state === "effective");
        if ($("lo_recipe").value !== recipeId) return; // đã đổi công thức khác trong lúc chờ — bỏ kết quả cũ
        if (!lnActiveVersions.length) {
          box.innerHTML = `<div class="muted" style="margin-top:6px">Công thức này chưa có version hiệu lực — vẫn tạo được lệnh, chỉ không xem trước được NVL.</div>`;
          lnRecipeVersionId = ""; return;
        }
        lnRecipeVersionId = preselectVersionId && lnActiveVersions.some(v => v.version_id === preselectVersionId)
          ? preselectVersionId : (lnActiveVersions.length === 1 ? lnActiveVersions[0].version_id : "");
        box.innerHTML = `<div class="row" style="margin-top:6px">
          <div class="field"><label>Chọn version</label><select id="lo_version">
            <option value="">(chọn version)</option>
            ${lnActiveVersions.map(v => `<option value="${esc(v.version_id)}" ${v.version_id === lnRecipeVersionId ? "selected" : ""}>
              ${esc(prodName(v.product_id))} · v${v.version_no} · ${v.base_qty} ${esc(v.base_uom)}</option>`).join("")}
          </select></div>
          <div class="field" style="flex:1"><label>Ghi chú</label><div class="muted" id="lo_version_note" style="margin-top:8px"></div></div>
        </div>`;
        const showNote = () => {
          const v = lnActiveVersions.find(x => x.version_id === lnRecipeVersionId);
          $("lo_version_note").textContent = v && v.change_reason ? v.change_reason : "—";
        };
        showNote();
        $("lo_version").onchange = () => { lnRecipeVersionId = $("lo_version").value; $("lo_bom_box").innerHTML = ""; showNote(); };
      } catch (e) { box.innerHTML = ""; }
    }
    $("lo_recipe").onchange = () => { $("lo_bom_box").innerHTML = ""; renderLnRecipeBox(); };
    if ($("lo_recipe").value) renderLnRecipeBox();

    // Bảng "Xem NVL" tương tác — mirror renderPoPreview (Lệnh SX ERP), state module-scope ở trên.
    async function renderLnPreview(lines) {
      lnPreviewLines = lines;
      const box = $("lo_bom_box");
      if (!lines.length) {
        box.innerHTML = `<div class="muted" style="margin-top:8px">Công thức này chưa khai báo NVL — không có định mức để xem.</div>`;
        return;
      }
      const altGroups = await getLnAltGroups();
      const ov = lnQtyOverrides;
      const isMemberDeclared = (l) => l.member_breakdown && l.member_breakdown.length && l.member_breakdown.some(mb => mb.qty_per_batch != null);
      const rowsHtml = lines.map(l => {
        const seqKey = String(l.seq);
        if (isMemberDeclared(l)) {
          const grp = altGroups.find(g => g.code === l.material_group_code);
          const mode = grp ? grp.selection_mode : "single";
          let selected = lnMemberSelection[seqKey];
          if (!selected || !selected.length) {
            selected = mode === "single" ? [l.member_breakdown[0].material_id] : l.member_breakdown.map(mb => mb.material_id);
            lnMemberSelection[seqKey] = selected;
          }
          const selectedSet = new Set(selected);
          const selMembers = l.member_breakdown.filter(mb => selectedSet.has(mb.material_id));
          const dispQtyPerBatch = round3(selMembers.reduce((s, mb) => s + (mb.qty_per_batch || 0), 0));
          const dispQtyTotal = round3(selMembers.reduce((s, mb) => s + (mb.qty_total || 0), 0));
          const dispShortage = selMembers.length > 0 && selMembers.every(mb => mb.shortage);
          const memberRows = l.member_breakdown.map(mb => {
            const checked = selectedSet.has(mb.material_id);
            const inputType = mode === "multi" ? "checkbox" : "radio";
            const nameAttr = mode === "multi" ? "" : ` name="ln_memsel_${seqKey}"`;
            const splitOv = ((lnMemberQtySplits[seqKey] || {})[mb.material_code]) || {};
            const fromCompany = splitOv.fromCompany ?? mb.qty_from_company;
            const fromWorkshop = splitOv.fromWorkshop ?? mb.qty_from_workshop;
            const splitCells = checked
              ? `<td><input type="number" class="ln_mem_qty_company" data-seq="${esc(seqKey)}" data-code="${esc(mb.material_code)}" value="${fromCompany ?? ""}" style="width:70px"/></td>
                 <td><input type="number" class="ln_mem_qty_workshop" data-seq="${esc(seqKey)}" data-code="${esc(mb.material_code)}" value="${fromWorkshop ?? ""}" style="width:70px"/></td>`
              : `<td class="muted">—</td><td class="muted">—</td>`;
            return `<tr class="muted" style="font-size:12px">
              <td colspan="4" style="padding-left:24px"><label style="display:flex;align-items:center;gap:6px;cursor:pointer">
                <input type="${inputType}" class="ln-memsel" data-seq="${esc(seqKey)}" data-mid="${esc(mb.material_id)}"${nameAttr} ${checked ? "checked" : ""}/>
                ${esc(mb.material_code)} — ${esc(mb.material_name)}</label></td>
              <td>${mb.qty_per_batch}</td><td>${mb.qty_total}</td>
              ${splitCells}
              <td>${mb.stock_company}</td><td>${mb.stock_workshop}</td>
              <td>${mb.shortage ? '<span class="badge on_hold">⚠ Thiếu</span>' : '<span class="badge available">✓ Đủ</span>'}</td></tr>`;
          }).join("");
          return `<tr class="${dispShortage ? "row-red" : ""}">
          <td>${esc(l.stt_label || "")}</td><td class="muted">—</td><td>${esc(l.material_name || "—")}
            <span class="muted" style="font-size:11px"> (nhóm — ${mode === "multi" ? "chọn nhiều mã" : "chọn 1 mã"})</span></td><td>${esc(l.uom || "")}</td>
          <td>${dispQtyPerBatch}</td><td>${dispQtyTotal}</td>
          <td colspan="2" class="muted">—</td>
          <td>${l.stock_company_snapshot ?? "—"}</td><td>${l.stock_workshop_snapshot ?? "—"}</td>
          <td>${selMembers.length === 0 ? '<span class="badge on_hold">⚠ Chưa chọn mã</span>'
            : (dispShortage ? '<span class="badge on_hold">⚠ Thiếu</span>' : '<span class="badge available">✓ Đủ</span>')}</td></tr>${memberRows}`;
        }
        const curOv = ov[seqKey] || {};
        const fromCompany = curOv.fromCompany ?? l.qty_from_company;
        const fromWorkshop = curOv.fromWorkshop ?? l.qty_from_workshop;
        return `<tr class="${l.shortage ? "row-red" : ""}">
        <td>${esc(l.stt_label || "")}</td><td class="muted">${esc(l.material_code || "—")}</td><td>${esc(l.material_name || "—")}</td><td>${esc(l.uom || "")}</td>
        <td>${l.qty_per_batch ?? "—"}</td><td>${l.qty_total ?? "—"}</td>
        <td>${l.is_header ? "" : `<input type="number" class="ln_qty_company" data-seq="${seqKey}" value="${fromCompany ?? ""}" style="width:80px"/>`}</td>
        <td>${l.is_header ? "" : `<input type="number" class="ln_qty_workshop" data-seq="${seqKey}" value="${fromWorkshop ?? ""}" style="width:80px"/>`}</td>
        <td>${l.stock_company_snapshot ?? "—"}</td><td>${l.stock_workshop_snapshot ?? "—"}</td>
        <td>${!l.is_header
          ? (l.shortage ? '<span class="badge on_hold">⚠ Thiếu</span>' : '<span class="badge available">✓ Đủ</span>')
          : '<span class="muted">—</span>'}</td></tr>${bomMemberRowsHtml(l, 8, 1)}`;
      }).join("");
      const shortageCount = lines.filter(l => isMemberDeclared(l)
        ? new Set(lnMemberSelection[String(l.seq)] || []).size === 0
        : l.shortage).length;
      box.innerHTML = `<div class="panel" style="margin-top:8px">
        <h3 style="font-size:14px">Xem trước định mức NVL ${shortageCount
          ? `<span style="color:var(--red)">— ⚠ ${shortageCount} dòng thiếu tồn/chưa chọn mã</span>`
          : `<span style="color:var(--green)">— ✓ đủ tồn tất cả</span>`}</h3>
        <div class="muted" style="margin-bottom:6px">Cột "SL lấy" là GỢI Ý (ưu tiên dùng hết tồn đang có tại Kho phân xưởng, phần
          còn thiếu lấy tại Kho công ty) — có thể sửa lại trước khi tạo lệnh, sẽ được LƯU LẠI. Dòng theo Nhóm vật tư có định mức
          riêng từng vật tư — chọn vật tư áp dụng ngay bên dưới, Nhu cầu chỉ tính mã đã chọn.</div>
        <div class="tablewrap"><table><thead><tr><th>STT</th><th>Mã NVL</th><th>Tên NVL</th><th>ĐVT</th><th>Nhu cầu 1 mẻ</th>
          <th>Nhu cầu Tổng mẻ</th><th>SL lấy tại Kho công ty</th><th>SL lấy tại Kho phân xưởng</th>
          <th>Tồn Kho công ty</th><th>Tồn Kho phân xưởng</th><th>Trạng thái</th></tr></thead>
        <tbody>${rowsHtml}</tbody></table></div></div>`;
      box.querySelectorAll(".ln_qty_company").forEach(inp => inp.onchange = () => {
        const seq = inp.dataset.seq;
        lnQtyOverrides[seq] = { ...(lnQtyOverrides[seq] || {}), fromCompany: inp.value === "" ? null : parseFloat(inp.value) };
      });
      box.querySelectorAll(".ln_qty_workshop").forEach(inp => inp.onchange = () => {
        const seq = inp.dataset.seq;
        lnQtyOverrides[seq] = { ...(lnQtyOverrides[seq] || {}), fromWorkshop: inp.value === "" ? null : parseFloat(inp.value) };
      });
      box.querySelectorAll(".ln-memsel").forEach(inp => inp.onchange = () => {
        const seq = inp.dataset.seq;
        if (inp.type === "radio") {
          lnMemberSelection[seq] = [inp.dataset.mid];
        } else {
          const cur = new Set(lnMemberSelection[seq] || []);
          if (inp.checked) cur.add(inp.dataset.mid); else cur.delete(inp.dataset.mid);
          lnMemberSelection[seq] = [...cur];
        }
        renderLnPreview(lnPreviewLines);
      });
      box.querySelectorAll(".ln_mem_qty_company").forEach(inp => inp.onchange = () => {
        const seq = inp.dataset.seq, code = inp.dataset.code;
        lnMemberQtySplits[seq] = { ...(lnMemberQtySplits[seq] || {}) };
        lnMemberQtySplits[seq][code] = { ...(lnMemberQtySplits[seq][code] || {}), fromCompany: inp.value === "" ? null : parseFloat(inp.value) };
      });
      box.querySelectorAll(".ln_mem_qty_workshop").forEach(inp => inp.onchange = () => {
        const seq = inp.dataset.seq, code = inp.dataset.code;
        lnMemberQtySplits[seq] = { ...(lnMemberQtySplits[seq] || {}) };
        lnMemberQtySplits[seq][code] = { ...(lnMemberQtySplits[seq][code] || {}), fromWorkshop: inp.value === "" ? null : parseFloat(inp.value) };
      });
    }
    $("lo_bom_preview").onclick = () => guard(async () => {
      if (!$("lo_recipe").value) throw new Error("Chọn loại bia trước khi xem định mức NVL.");
      if (!lnRecipeVersionId) throw new Error("Chọn version trước khi xem định mức NVL.");
      const volHl = parseFloat($("lo_volplan").value) || 0;
      const batches = parseInt($("lo_batches").value, 10) || 1;
      const qs = `recipe_version_id=${encodeURIComponent(lnRecipeVersionId)}&planned_batch_count=${batches}&planned_volume_hl=${volHl}`;
      const lines = await GET(`/brewing/orders/bom-preview?${qs}`);
      await renderLnPreview(lines);
    });
    // Gộp 2 loại override trước khi gửi: SL lấy Company/Workshop (dòng thường) và thành viên đã
    // chọn (dòng Nhóm vật tư có định mức riêng — lnMemberSelection giữ material_id, cần đổi
    // sang material_code vì server nhận selected_material_codes) — mirror poBuildMaterialQtyOverrides.
    function lnBuildMaterialQtyOverrides() {
      const out = {};
      for (const [seq, o] of Object.entries(lnQtyOverrides)) {
        out[seq] = { qty_from_company: o.fromCompany ?? null, qty_from_workshop: o.fromWorkshop ?? null };
      }
      for (const [seq, materialIds] of Object.entries(lnMemberSelection)) {
        const line = lnPreviewLines.find(l => String(l.seq) === seq);
        const codeById = Object.fromEntries((line ? line.member_breakdown : []).map(mb => [mb.material_id, mb.material_code]));
        out[seq] = { ...(out[seq] || {}), selected_material_codes: materialIds.map(mid => codeById[mid]).filter(Boolean) };
      }
      for (const [seq, byCode] of Object.entries(lnMemberQtySplits)) {
        const member_qty_splits = Object.fromEntries(Object.entries(byCode).map(([code, o]) =>
          [code, { qty_from_company: o.fromCompany ?? null, qty_from_workshop: o.fromWorkshop ?? null }]));
        out[seq] = { ...(out[seq] || {}), member_qty_splits };
      }
      return out;
    }

    $("lo_add").onclick = () => guard(async () => {
      const code = $("lo_code").value.trim();
      if (!code) throw new Error("Nhập Số lệnh.");
      const volHl = parseFloat($("lo_volplan").value) || 0;
      if (!(volHl > 0)) throw new Error("Nhập Sản lượng nấu kế hoạch (hl) (phải lớn hơn 0).");
      const recipeId = $("lo_recipe").value;
      if (recipeId && !lnRecipeVersionId) throw new Error("Chọn Version đang dùng cho lệnh này.");
      const chosenVersion = lnActiveVersions.find(v => v.version_id === lnRecipeVersionId);
      const payload = {
        order_code: code,
        product_id: chosenVersion ? chosenVersion.product_id : null,
        recipe_version_id: lnRecipeVersionId || null,
        planned_batch_count: parseInt($("lo_batches").value, 10) || 1,
        planned_volume_hl: volHl,
        volume_tolerance_hl: parseFloat($("lo_voltol").value) || 0,
        issued_by: $("lo_issuedby").value.trim() || null,
        executor_unit: $("lo_exec").value.trim() || null,
        warehouse_keeper: $("lo_kho").value.trim() || null,
        start_date: $("lo_start").value || null,
        end_date: $("lo_end").value || null,
        auto_from_bom: true, lines: [],
        material_qty_overrides: lnBuildMaterialQtyOverrides(),
      };
      if (editingOrderId) {
        await PUT(`/brewing/orders/${editingOrderId}`, payload);
        toast("Đã lưu lệnh nấu");
      } else {
        await POST("/brewing/orders", payload);
        toast("Đã tạo lệnh nấu");
      }
      render("orders");
    });

    document.querySelectorAll("[data-viewlo]").forEach(b => b.onclick = () => openBrewOrderModal(b.dataset.viewlo));
    document.querySelectorAll("[data-printlo]").forEach(b => b.onclick = () => guard(async () => {
      printBrewOrder(await GET(`/brewing/orders/${b.dataset.printlo}`));
    }));
    document.querySelectorAll("[data-editlo]").forEach(b => b.onclick = () => guard(async () => {
      const o = await GET(`/brewing/orders/${b.dataset.editlo}`);
      editingOrderId = o.brew_order_id;
      $("lo_code").value = o.order_code;
      const recipeId = o.recipe_version_id ? (await GET(`/recipes/versions/${o.recipe_version_id}`)).recipe_id : "";
      $("lo_recipe").value = recipeId;
      $("lo_batches").value = o.planned_batch_count || 1;
      $("lo_volplan").value = o.planned_volume_hl || "";
      $("lo_voltol").value = o.volume_tolerance_hl || 0;
      $("lo_issuedby").value = o.issued_by || "";
      $("lo_exec").value = o.executor_unit || "";
      $("lo_kho").value = o.warehouse_keeper || "";
      $("lo_start").value = o.start_date ? o.start_date.slice(0, 16) : "";
      $("lo_end").value = o.end_date ? o.end_date.slice(0, 16) : "";
      resetLnOverridesFromSavedLines(o.lines);
      $("lo_bom_box").innerHTML = "";
      await renderLnRecipeBox(o.recipe_version_id);
      setLoFormMode(true);
      $("lo_code").scrollIntoView({ behavior: "smooth", block: "center" });
      toast(`Đang sửa lệnh ${o.order_code} — thay đổi rồi bấm "Lưu chỉnh sửa lệnh"`);
    }));
    document.querySelectorAll("[data-dello]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa lệnh nấu này? Không thể hoàn tác.")) return;
      await DELETE(`/brewing/orders/${b.dataset.dello}`);
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

    // Loại bia của tank thành phẩm = suy từ Dịch bia của các tank đã chọn (qua approvedTanksLf.beer_type_id/
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

    // Lượng CCT đã bị các tank thành phẩm PHÍA TRÊN (ci' < ci) đặt trước cho cùng 1 tank — để
    // tank phía dưới thấy đúng phần còn lại thật sự có thể lấy, không bị trùng lắp.
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

    // Lượng khả dụng của tank BBT (thành phẩm) đã bị các tank thành phẩm PHÍA TRÊN (ci' < ci)
    // đặt trước làm nguồn lọc lại — mirror reservedByEarlierLf nhưng theo mã tank BBT.
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
        return `Còn khả dụng để lọc lại: <b>${t.remaining_hl.toLocaleString("vi-VN")} hl</b> — tank thành phẩm phía trên đã đặt: <b>${reserved.toLocaleString("vi-VN")} hl</b> — còn lại: <b>${remaining.toLocaleString("vi-VN")} hl</b>`;
      }
      return `Còn khả dụng để lọc lại: <b>${t.remaining_hl.toLocaleString("vi-VN")} hl</b>`;
    };
    // Vật tư sử dụng trong Lệnh lọc — tìm-để-lọc thay vì <select> liệt kê hết (hàng trăm mã,
    // đa số không phải NVL);
    // danh sách CHỈ lấy vật tư thuộc Nhóm vật tư được đánh dấu "Nguyên liệu (chính/phụ)"
    // (MaterialGroup.is_raw_material), cộng thêm lựa chọn Nhóm vật tư thay thế (Malt Úc rời/
    // bao...). Value dùng material_id (khác Công thức dùng material_code) vì
    // FilterOrderMaterialLineIn vốn nhận material_id trực tiếp.
    const lfMaterialSearchItems = () => {
      const rawGroupCodes = new Set((CACHE.materialGroupsLf || []).filter(g => g.is_raw_material).map(g => g.code));
      const matItems = (CACHE.materialsLf || []).filter(m => rawGroupCodes.has(m.category))
        .map(m => ({ value: m.material_id, label: `${m.code} — ${m.name}` }));
      const groupItems = (CACHE.materialAltGroupsLf || []).filter(g => g.active)
        .map(g => ({ value: `grp:${g.code}`, label: `${g.name} (nhóm vật tư thay thế)` }));
      return [...matItems, ...groupItems];
    };
    const lfMaterialLabel = (materialId, groupCode) => {
      if (groupCode) {
        const g = (CACHE.materialAltGroupsLf || []).find(x => x.code === groupCode);
        return g ? `${g.name} (nhóm vật tư thay thế)` : groupCode;
      }
      if (materialId) {
        const m = (CACHE.materialsLf || []).find(x => x.material_id === materialId);
        return m ? `${m.code} — ${m.name}` : materialId;
      }
      return "";
    };
    const lfGroupMembers = (groupCode) => {
      const g = (CACHE.materialAltGroupsLf || []).find(x => x.code === groupCode);
      return g ? (g.member_material_ids || []) : [];
    };
    // Nhắc lại rõ tồn CCT còn lại của tank vừa chọn (sau khi trừ phần các tank thành phẩm phía
    // trên đã đặt) — để người dùng nhập đúng thể tích dịch lọc kế hoạch, không vượt quá số thật sự
    // còn lại của tank.
    const tankCctInfo = (ci, fermentId) => {
      const f = approvedTanksLf.find(x => x.ferment_id === fermentId);
      if (!f) return "";
      const reserved = reservedByEarlierLf(ci, fermentId);
      const remaining = f.on_hand_cct - reserved;
      if (reserved > 0) {
        return `Đang tồn CCT: <b>${f.on_hand_cct.toLocaleString("vi-VN")} hl</b> — tank thành phẩm phía trên đã đặt: <b>${reserved.toLocaleString("vi-VN")} hl</b> — còn lại: <b>${remaining.toLocaleString("vi-VN")} hl</b>`;
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
        <div class="muted" style="margin-top:4px">Tổng thể tích dịch lọc kế hoạch của tank thành phẩm này: <b>${lfChildTotalVol(ci).toLocaleString("vi-VN")} hl</b></div>
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
        box.innerHTML = `<div class="field"><label>Các tank thuộc nhiều Loại bia khác nhau — chọn 1 Loại bia cho tank thành phẩm này</label>
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
          const value = l.altGroupCode ? `grp:${l.altGroupCode}` : (l.material_id || "");
          const label = lfMaterialLabel(l.material_id, l.altGroupCode);
          return `<div class="row" style="align-items:flex-end;flex-wrap:wrap;border-bottom:1px solid var(--border);padding-bottom:8px;margin-bottom:8px">
            <div class="field"><label>Vật tư</label>
              <input type="text" class="lfc_mat_txt" data-ci="${ci}" data-li="${li}" value="${esc(label)}" placeholder="Gõ để tìm vật tư/nhóm..." autocomplete="off" style="min-width:220px"/>
              <input type="hidden" class="lfc_mat" data-ci="${ci}" data-li="${li}" value="${esc(value)}"/></div>
            <div class="field"><label>Số lượng cần</label><input class="lfc_matqty" data-ci="${ci}" data-li="${li}" type="number" value="${l.quantity ?? ""}" style="width:110px"/></div>
            <button class="btn sm sec" data-lfc-matrm data-ci="${ci}" data-li="${li}">Xóa dòng</button>
            ${!showFifo && value ? `<div class="muted" style="flex-basis:100%;font-size:13px;margin-top:4px">Nhập số lượng cần để xem tồn kho + lô FIFO.</div>` : ""}
            ${showFifo ? `<div style="flex-basis:100%;font-size:13px;margin-top:4px">
              Kho công ty: <b>${fifo.stock_company}</b> · Kho phân xưởng: <b>${fifo.stock_workshop}</b> ·
              Tổng: <b>${fifo.stock_total}</b>
              ${short ? `<span style="color:var(--red)"> — ⚠ Thiếu (cần ${l.quantity})</span>` : `<span style="color:var(--green)"> — Đủ</span>`}
              ${l.altGroupCode ? `<div class="tablewrap" style="margin-top:4px"><table><thead><tr><th>Mã thành viên</th><th>Kho công ty</th><th>Kho phân xưởng</th></tr></thead>
                <tbody>${(fifo.memberBreakdown || []).map(mb => `<tr><td class="code">${esc(mb.label)}</td><td>${mb.stock_company}</td><td>${mb.stock_workshop}</td></tr>`).join("")}</tbody></table></div>`
                : (fifo.lots.length ? `<div class="tablewrap" style="margin-top:4px"><table><thead><tr><th>Lô (FIFO)</th><th>Kho</th><th>SL</th><th>Ngày nhập</th></tr></thead>
                <tbody>${fifo.lots.map(lo => `<tr><td class="code">${esc(lo.lot_code)}</td><td class="muted">${esc(lo.location || "—")}</td>
                  <td>${lo.quantity}</td><td class="muted">${fmt(lo.received_at)}</td></tr>`).join("")}</tbody></table></div>`
                : `<div class="muted">Không còn lô nào.</div>`)}
            </div>` : ""}
          </div>`;
        }).join("") || `<div class="muted">Chưa có dòng vật tư nào.</div>`}
        <button class="btn sec" data-lfc-mataddrow data-ci="${ci}">+ Thêm vật tư</button></div>`;
      box.querySelector("[data-lfc-mataddrow]").onclick = () => {
        lfChildren[ci].materialLines.push({ material_id: "", altGroupCode: "", quantity: "", fifo: null }); renderLfChildMaterials(ci);
      };
      box.querySelectorAll("[data-lfc-matrm]").forEach(b => b.onclick = () => {
        lfChildren[ci].materialLines.splice(parseInt(b.dataset.li, 10), 1); renderLfChildMaterials(ci);
      });
      const refreshFifo = async (li) => {
        const l = lfChildren[ci].materialLines[li];
        if (l.altGroupCode) {
          const memberIds = lfGroupMembers(l.altGroupCode);
          const details = await Promise.all(memberIds.map(mid => GET(`/warehouse/materials/${mid}/fifo`)));
          const round3 = (n) => Math.round(n * 1000) / 1000;
          const company = details.reduce((s, d) => s + d.stock_company, 0);
          const workshop = details.reduce((s, d) => s + d.stock_workshop, 0);
          l.fifo = { stock_company: round3(company), stock_workshop: round3(workshop), stock_total: round3(company + workshop),
            lots: [], memberBreakdown: memberIds.map((mid, i) => ({ label: lfMaterialLabel(mid, null), stock_company: details[i].stock_company, stock_workshop: details[i].stock_workshop })) };
        } else if (l.material_id) {
          l.fifo = await GET(`/warehouse/materials/${l.material_id}/fifo`);
        } else {
          l.fifo = null;
        }
        renderLfChildMaterials(ci);
      };
      box.querySelectorAll(".lfc_mat_txt").forEach(txt => {
        const li = parseInt(txt.dataset.li, 10);
        const hidden = txt.nextElementSibling;
        let panel = null;
        const closePanel = () => { if (panel) { panel.remove(); panel = null; } };
        const openPanel = (query) => {
          closePanel();
          const items = lfMaterialSearchItems();
          const q = (query || "").trim().toLowerCase();
          const matches = (q ? items.filter(i => i.label.toLowerCase().includes(q)) : items).slice(0, 50);
          const rect = txt.getBoundingClientRect();
          panel = el(`<div class="ss-dd" style="top:${rect.bottom + window.scrollY + 2}px; left:${rect.left + window.scrollX}px; width:${Math.max(rect.width, 260)}px">
            ${matches.map(i => `<div class="ss-item" data-v="${esc(i.value)}">${esc(i.label)}</div>`).join("") ||
              '<div class="ss-empty">Không tìm thấy.</div>'}</div>`);
          document.body.appendChild(panel);
          panel.querySelectorAll(".ss-item").forEach(row => {
            row.onmousedown = (e) => {
              e.preventDefault();
              const item = items.find(i => i.value === row.dataset.v);
              if (item) {
                hidden.value = item.value; txt.value = item.label;
                if (item.value.startsWith("grp:")) {
                  lfChildren[ci].materialLines[li].altGroupCode = item.value.slice(4);
                  lfChildren[ci].materialLines[li].material_id = "";
                } else {
                  lfChildren[ci].materialLines[li].material_id = item.value;
                  lfChildren[ci].materialLines[li].altGroupCode = "";
                }
                refreshFifo(li);
              }
              closePanel();
            };
          });
        };
        txt.addEventListener("focus", () => { txt.select(); openPanel(""); });
        txt.addEventListener("input", () => openPanel(txt.value));
        txt.addEventListener("blur", () => setTimeout(closePanel, 150));
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
            <h3 style="font-size:14px;margin:0;flex:1">TANK THÀNH PHẨM SỐ ${String(ci + 1).padStart(2, "0")}</h3>
            ${lfChildren.length > 1 ? `<button class="btn sm sec" data-lfchildrm="${ci}">Xóa tank</button>` : ""}
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
        if (c.blendMode === "khong_phoi" && tanks.length !== 1) throw new Error(`Tank thành phẩm #${ci + 1}: Không phối phải chọn đúng 1 tank nguồn.`);
        if (c.blendMode === "phoi" && tanks.length < 2) throw new Error(`Tank thành phẩm #${ci + 1}: Phối phải chọn từ 2 tank nguồn trở lên.`);
        for (const t of tanks) {
          if (!(parseFloat(t.vol) > 0)) throw new Error(`Tank thành phẩm #${ci + 1}: Nhập thể tích dịch lọc kế hoạch cho từng tank.`);
          if (t.tankType === "bbt" && !(t.reason || "").trim()) throw new Error(`Tank thành phẩm #${ci + 1}: Tank BBT ${t.sourceBbtCode} phải nhập lý do lọc lại.`);
        }
        const { list: btCandidates, missing: btMissing } = lfChildBeerTypeCandidates(ci);
        if (btMissing) throw new Error(`Tank thành phẩm #${ci + 1}: có tank chưa được gán Loại bia — vào Danh mục Dịch bia để gán trước.`);
        if (btCandidates.length > 1 && !c.beerTypeId) throw new Error(`Tank thành phẩm #${ci + 1}: các tank thuộc nhiều Loại bia khác nhau — chọn 1 Loại bia.`);
        const lines = c.materialLines.filter(l => (l.material_id || l.altGroupCode) && l.quantity)
          .map(l => l.altGroupCode ? { alt_group_code: l.altGroupCode, quantity: l.quantity } : { material_id: l.material_id, quantity: l.quantity });
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
        materialLines: c.lines.map(l => ({ material_id: l.material_id, altGroupCode: l.material_group_code || "", quantity: l.quantity, fifo: null })),
        tolerance: c.volume_tolerance_hl || 0, kcsLotNo: c.kcs_lot_no || "",
        beerTypeId: c.beer_type_id || "", finishedProductId: c.finished_product_id || "",
      }));
      renderLfChildren();
      setLfFormMode(true);
      $("lf_code").scrollIntoView({ behavior: "smooth", block: "center" });
      toast(`Đang sửa lệnh ${m.order_code} — thay đổi rồi bấm "Lưu chỉnh sửa lệnh lọc"`);
    }));
    document.querySelectorAll("[data-dellf]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa lệnh lọc này (cả các tank thành phẩm bên trong)? Không thể hoàn tác.")) return;
      await DELETE(`/brewing/filter-master-orders/${b.dataset.dellf}`);
      toast("Đã xóa lệnh lọc"); render("orders");
    }));
  }
};
const prodName = (id) => { const p = CACHE.products.find(x => x.product_id === id); return p ? p.code : id; };
const beerTypeName = (id) => { const bt = (CACHE.beerTypes || []).find(x => x.beer_type_id === id); return bt ? bt.name : id; };

// ================= ĐIỀU ĐỘ (Work Orders) =================
const WO_STATUS = { planned: ["planned", "Lập KH"], released: ["released", "Đã phát hành"],
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

// ================= CÔNG THỨC (Recipe/RecipeVersion — ISA-88, có version) =================
// Khôi phục nguyên bản màn hình gốc (trước khi bị thay bằng Formula ở commit 6820717): mỗi
// version có BOM (materials) + Tham số quy trình (parameters, VD nhiệt độ đường hóa/lên men)
// + Chỉ tiêu QC (quality_checks) + Quy trình ISA-88 (procedure: Unit Procedure → Operation →
// Phase, có setpoint nhiệt độ/thời lượng). Chuyển trạng thái (draft→review→approved→effective,
// hoặc suspended/obsolete) gọi thẳng /transition — KHÔNG qua chữ ký điện tử change-approve
// (đúng bản gốc; change-approve là API riêng cho quy trình duyệt nghiêm ngặt hơn, chưa từng
// được UI này dùng tới). Lệnh nấu (BrewOrder) nạp NVL từ 1 version "effective" do người lập
// lệnh tự chọn (services/brew_order.py::build_lines_from_recipe_version) — không phụ thuộc
// màn này hiển thị thế nào.
VIEWS.recipes = async function () {
  const [recipes, products, beerTypes, materials, materialAltGroups] = await Promise.all([
    GET("/recipes"), GET("/products"), GET("/beer-types"), GET("/materials"), GET("/material-alt-groups").catch(() => [])]);
  CACHE.products = products; CACHE.recipes = recipes; CACHE.beerTypes = beerTypes; CACHE.materials = materials;
  CACHE.materialAltGroups = materialAltGroups;
  const btopts = beerTypes.map(bt => `<option value="${bt.beer_type_id}">${esc(bt.code)} — ${esc(bt.name)}</option>`).join("");
  let versionsHtml = "";
  for (const r of recipes) {
    const vs = await GET(`/recipes/${r.recipe_id}/versions`);
    versionsHtml += `<div class="panel"><h2>${esc(r.code)} — ${esc(r.name)} ${badge(beerTypeName(r.beer_type_id))}</h2>
      <button class="btn sm" data-newver="${r.recipe_id}">+ Tạo version (BOM)</button>
      <button class="btn sm sec" data-rdel="${esc(r.recipe_id)}" data-rcode="${esc(r.code)}">🗑 Xóa công thức</button>
      <div class="tablewrap"><table><thead><tr><th>Ver</th><th>Dịch bia</th><th>Trạng thái</th><th>Quy mô chuẩn</th><th>Ghi chú</th><th>Dòng BOM</th><th>Tham số</th><th>QC</th><th>Soạn</th><th>Duyệt</th><th>Hành động</th></tr></thead>
      <tbody>${vs.map(v => recipeVerRow(r, v)).join("")}</tbody></table></div></div>`;
  }
  $("view-recipes").innerHTML = `
    <div class="panel"><h2>Tạo công thức</h2>
      <div class="row">
        <div class="field"><label>Mã</label><input id="r_code" placeholder="REC-..." /></div>
        <div class="field"><label>Tên</label><input id="r_name" /></div>
        <div class="field"><label>Loại bia</label><select id="r_beertype">${btopts}</select></div>
        <button class="btn" id="r_save">Tạo</button>
      </div></div>
    <div id="rv_detail"></div>
    ${versionsHtml || '<div class="panel muted">Chưa có công thức.</div>'}`;
  $("r_save").onclick = () => guard(async () => {
    await POST("/recipes", { code: $("r_code").value, name: $("r_name").value, beer_type_id: $("r_beertype").value });
    toast("Đã tạo công thức"); render("recipes");
  });
  document.querySelectorAll("[data-newver]").forEach(b => b.onclick = () => newVersionForm(b.dataset.newver));
  document.querySelectorAll("[data-rdel]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm(`Xóa công thức ${b.dataset.rcode}? Chỉ xóa được nếu chưa có work order/mẻ sản xuất nào dùng. Không thể hoàn tác.`)) return;
    await DELETE(`/recipes/${b.dataset.rdel}`);
    toast("Đã xóa công thức"); render("recipes");
  }));
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
  return `<tr><td>v${v.version_no}</td><td>${esc(prodName(v.product_id))}</td><td>${badge(v.state)}</td>
    <td>${v.base_qty ? v.base_qty.toLocaleString("vi-VN") + " " + esc(v.base_uom) : "—"}</td>
    <td class="muted">${esc(v.change_reason || "—")}</td>
    <td><b>${(v.materials || []).length}</b></td><td>${v.parameters.length}</td>
    <td>${v.quality_checks.length}</td><td class="muted">${esc(v.created_by || "—")}</td>
    <td class="muted">${esc(v.approved_by || "—")}</td>
    <td><a href="#" data-vdetail="${v.version_id}" style="color:var(--accent2);margin-right:8px">Xem BOM</a>${btns}</td></tr>`;
}

async function showVersion(versionId) {
  const v = await GET("/recipes/versions/" + versionId);
  const bom = (v.materials || []).map(m => {
    if (m.alt_group_code) {
      const grp = (CACHE.materialAltGroups || []).find(g => g.code === m.alt_group_code);
      const memberRows = (m.member_qty || []).map(mq => `<tr class="muted" style="font-size:12px">
        <td style="padding-left:20px">↳ ${esc(mq.material_code)}</td><td>${mq.qty}</td><td>${esc(m.uom || "")}</td><td></td></tr>`).join("");
      return `<tr><td>${esc(grp ? grp.name : m.alt_group_code)} <span class="muted">(nhóm vật tư thay thế${grp && grp.selection_mode === "multi" ? " — chọn nhiều mã" : ""})</span></td>
      <td>${m.member_qty ? "—" : m.qty}</td><td>${esc(m.uom || "")}</td><td>±${m.tol_pct || 0}%</td></tr>${memberRows}`;
    }
    const mat = (CACHE.materials || []).find(x => x.code === m.material_code);
    return `<tr><td><code class="k">${esc(m.material_code)}</code> ${esc(mat ? mat.name : "")}</td>
    <td>${m.qty}</td><td>${esc(m.uom || "")}</td><td>±${m.tol_pct || 0}%</td></tr>`;
  }).join("");
  const params = (v.parameters || []).map(p => `<tr><td>${esc(p.name)}</td><td>${p.target ?? ""}</td>
    <td class="muted">${p.lower ?? "−∞"} … ${p.upper ?? "+∞"}</td><td>${esc(p.unit || "")}</td></tr>`).join("");
  const qc = (v.quality_checks || []).map(c => `<tr><td>${esc(c.parameter)}</td>
    <td class="muted">${c.lower ?? "−∞"} … ${c.upper ?? "+∞"} ${esc(c.unit || "")}</td>
    <td>${c.mandatory ? badge("critical") + "bắt buộc" : "tùy chọn"}</td></tr>`).join("");
  $("rv_detail").innerHTML = `<div class="panel"><h2>Chi tiết version v${v.version_no} ${badge(v.state)}
      <span class="muted">· quy mô chuẩn ${v.base_qty ? v.base_qty.toLocaleString("vi-VN") + " " + esc(v.base_uom) : "—"}</span></h2>
    ${v.change_reason ? `<div class="muted" style="margin:-4px 0 10px">Ghi chú: ${esc(v.change_reason)}</div>` : ""}
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
// Ô chọn vật tư là input gõ-để-tìm (không phải <select> dài — danh mục vật tư có hàng trăm
// mã), value thật giữ trong input hidden kế bên, tiền tố "grp:" cho dòng khai theo Nhóm vật
// tư thay thế (VD "Malt Úc" = rời + bao — xem models/master.py::MaterialAltGroup) thay vì 1
// material_code cụ thể — services/brew_order.py::build_lines_from_recipe_version đã hỗ trợ
// alt_group_code trong materials JSON. ĐVT: vật tư có khai đơn vị phụ (alt_uom+alt_uom_ratio)
// thì cho chọn Đơn vị chính/Đơn vị phụ, dòng nhóm thì khoá theo ĐVT của nhóm, còn lại khoá
// cứng theo đơn vị chính (readonly) — số lượng luôn quy đổi về đơn vị chính trước khi gửi lên
// server (collectBom).
function bomMaterialSearchItems() {
  const matItems = (CACHE.materials || []).map(m => ({ code: m.code, label: `${m.code} — ${m.name}`, mat: m }));
  const groupItems = (CACHE.materialAltGroups || []).filter(g => g.active)
    .map(g => ({ code: `grp:${g.code}`, label: `${g.name} (nhóm vật tư thay thế)`, isGroup: true, uom: g.unit || null }));
  return [...matItems, ...groupItems];
}
function bomMaterialLabel(materialCode, groupCode) {
  if (groupCode) {
    const g = (CACHE.materialAltGroups || []).find(x => x.code === groupCode);
    return g ? `${g.name} (nhóm vật tư thay thế)` : groupCode;
  }
  const m = (CACHE.materials || []).find(x => x.code === materialCode);
  return m ? `${m.code} — ${m.name}` : (materialCode || "");
}
function bomUomCellHTML(mat, isGroup, groupUom) {
  if (isGroup) {
    return `<input class="bm-uom" value="${esc(groupUom || "")}" size="5" readonly title="ĐVT lấy theo Nhóm vật tư thay thế — không sửa được ở đây" style="width:90px"/>`;
  }
  return altUomFieldHtml(mat, `class="bm-uom"`, 90);
}
// Dòng khai theo Nhóm vật tư thay thế có 2 cách khai định mức, người tạo Công thức TỰ CHỌN
// bằng checkbox "bm-permember" (mặc định TẮT — giữ đúng hành vi gốc):
// - TẮT (mặc định, VD "Malt Anh" rời/bao — hoàn toàn tương đương nhau): chỉ điền 1 TỔNG dùng
//   chung, giống hệt trước đây — người lập Lệnh nấu/ghi NVL thực tế tự do phân bổ tổng này
//   qua các mã thành viên tuỳ tồn kho lúc đó (mirror hành vi Nhóm vật tư gốc, không đổi).
// - BẬT (VD nhóm CO2 nhiều nồng độ khác nhau): mỗi thành viên có 1 định mức RIÊNG do khác bản
//   chất/nồng độ — hiện 1 ô nhập/thành viên; lúc ghi NVL thực tế được chọn dùng 1 hay nhiều mã
//   (tuỳ selection_mode của nhóm ở Danh mục), mỗi mã dùng đúng định mức đã khai cho chính nó.
function bomGroupMemberQtyHTML(groupCode, memberQty, legacyQty) {
  const g = (CACHE.materialAltGroups || []).find(x => x.code === groupCode);
  if (!g) return `<div class="muted" style="font-size:12px">(nhóm vật tư không tồn tại)</div>`;
  const qtyByCode = Object.fromEntries((memberQty || []).map(mq => [mq.material_code, mq.qty]));
  const rows = (g.member_material_ids || []).map(mid => {
    const mat = (CACHE.materials || []).find(m => m.material_id === mid);
    const code = mat ? mat.code : mid;
    const val = qtyByCode.hasOwnProperty(code) ? qtyByCode[code] : (legacyQty ?? "");
    return `<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
      <input type="number" step="any" class="bm-member-qty" data-code="${esc(code)}" value="${esc(val)}" style="width:80px" placeholder="0"/>
      <span class="muted" style="font-size:11px">${esc(mat ? `${mat.code} — ${mat.name}` : code)}</span>
    </div>`;
  }).join("");
  return `<div class="bm-group-qty">${rows || '<span class="muted" style="font-size:12px">(nhóm chưa có thành viên)</span>'}</div>`;
}
function bomQtyCellHTML(line, groupCode, permember) {
  if (groupCode && permember) return bomGroupMemberQtyHTML(groupCode, line.member_qty, line.qty);
  return `<input class="bm-qty" type="number" step="any" value="${line.qty ?? ""}" style="width:110px" title="${groupCode ? 'Tổng dùng chung cho cả nhóm — người lập Lệnh nấu tự phân bổ qua các mã thành viên' : ''}"/>`;
}
function bomPermemberLabelHTML(groupCode, checked) {
  if (!groupCode) return "";
  return `<label class="muted bm-permember-wrap" style="display:block;font-size:11px;margin-top:2px"><input type="checkbox" class="bm-permember" ${checked ? "checked" : ""}/> Định mức riêng từng thành viên</label>`;
}
function bomRowHTML(line) {
  line = line || {};
  const value = line.alt_group_code ? `grp:${line.alt_group_code}` : (line.material_code || "");
  const mat = line.material_code ? (CACHE.materials || []).find(m => m.code === line.material_code) : null;
  const permember = !!(line.member_qty && line.member_qty.length);
  return `<tr class="bomrow">
    <td><input type="text" class="bm-mat-txt" value="${esc(bomMaterialLabel(line.material_code, line.alt_group_code))}" placeholder="Gõ để tìm vật tư/nhóm..." autocomplete="off" style="min-width:220px"/>
      <input type="hidden" class="bm-mat" value="${esc(value)}"/>
      ${bomPermemberLabelHTML(line.alt_group_code, permember)}</td>
    <td class="bm-qty-cell">${bomQtyCellHTML(line, line.alt_group_code, permember)}</td>
    <td class="bm-uom-cell">${bomUomCellHTML(mat, !!line.alt_group_code, line.uom)}</td>
    <td><input class="bm-tol" type="number" value="${line.tol_pct ?? 0}" size="4"/> %</td>
    <td><button class="btn sm sec bm-del" type="button">×</button></td></tr>`;
}
function wireBomEditor() {
  $("bm_add").onclick = () => { $("bm_body").insertAdjacentHTML("beforeend", bomRowHTML()); wireBomRows(); };
  wireBomRows();
}
function wireBomPermemberCheckbox(tr) {
  const cb = tr.querySelector(".bm-permember");
  if (!cb) return;
  cb.onchange = () => {
    const groupCode = tr.querySelector(".bm-mat").value.slice(4);
    tr.querySelector(".bm-qty-cell").innerHTML = bomQtyCellHTML({}, groupCode, cb.checked);
  };
}
function wireBomRows() {
  document.querySelectorAll(".bm-del").forEach(b => b.onclick = () => { b.closest("tr").remove(); });
  document.querySelectorAll(".bomrow").forEach(tr => wireBomPermemberCheckbox(tr));
  document.querySelectorAll(".bm-mat-txt").forEach(txt => {
    if (txt.dataset.wired) return;
    txt.dataset.wired = "1";
    const hidden = txt.nextElementSibling;
    let panel = null;
    const closePanel = () => { if (panel) { panel.remove(); panel = null; } };
    const openPanel = (query) => {
      closePanel();
      const items = bomMaterialSearchItems();
      const q = (query || "").trim().toLowerCase();
      const matches = (q ? items.filter(i => i.label.toLowerCase().includes(q)) : items).slice(0, 50);
      const rect = txt.getBoundingClientRect();
      panel = el(`<div class="ss-dd" style="top:${rect.bottom + window.scrollY + 2}px; left:${rect.left + window.scrollX}px; width:${Math.max(rect.width, 260)}px">
        ${matches.map(i => `<div class="ss-item" data-v="${esc(i.code)}">${esc(i.label)}</div>`).join("") ||
          '<div class="ss-empty">Không tìm thấy.</div>'}</div>`);
      document.body.appendChild(panel);
      // mousedown (không phải click) để chạy trước sự kiện blur của ô nhập, mirror wireSearchableSelect.
      panel.querySelectorAll(".ss-item").forEach(row => {
        row.onmousedown = (e) => {
          e.preventDefault();
          const item = items.find(i => i.code === row.dataset.v);
          if (item) {
            hidden.value = item.code; txt.value = item.label;
            const tr = txt.closest("tr");
            tr.querySelector(".bm-uom-cell").innerHTML = bomUomCellHTML(item.mat, !!item.isGroup, item.uom);
            tr.querySelector(".bm-qty-cell").innerHTML = bomQtyCellHTML({}, item.isGroup ? item.code.slice(4) : null, false);
            const existingLabel = txt.parentElement.querySelector(".bm-permember-wrap");
            if (existingLabel) existingLabel.remove();
            if (item.isGroup) hidden.insertAdjacentHTML("afterend", bomPermemberLabelHTML(item.code.slice(4), false));
            wireBomPermemberCheckbox(tr);
          }
          closePanel();
        };
      });
    };
    txt.addEventListener("focus", () => { txt.select(); openPanel(""); });
    txt.addEventListener("input", () => openPanel(txt.value));
    txt.addEventListener("blur", () => setTimeout(closePanel, 150));
  });
}
function collectBom() {
  return [...document.querySelectorAll(".bomrow")].map(tr => {
    const val = tr.querySelector(".bm-mat").value;
    const chosenUom = tr.querySelector(".bm-uom").value;
    const tol_pct = parseFloat(tr.querySelector(".bm-tol").value) || 0;
    if (val.startsWith("grp:")) {
      const permemberCb = tr.querySelector(".bm-permember");
      if (permemberCb && permemberCb.checked) {
        // Định mức RIÊNG từng thành viên — chỉ lưu kiểu này khi người tạo Công thức chủ động
        // bật checkbox (VD nhóm CO2 nhiều nồng độ khác nhau).
        const member_qty = [...tr.querySelectorAll(".bm-member-qty")].map(inp => ({
          material_code: inp.dataset.code, qty: parseFloat(inp.value) || 0,
        })).filter(mq => mq.qty > 0);
        return { alt_group_code: val.slice(4), member_qty, uom: chosenUom, tol_pct };
      }
      // Mặc định: 1 TỔNG dùng chung cho cả nhóm (VD "Malt Anh" rời/bao hoàn toàn tương đương)
      // — người lập Lệnh nấu/ghi NVL thực tế tự phân bổ qua các mã thành viên tuỳ tồn kho.
      const qtyRaw = parseFloat(tr.querySelector(".bm-qty").value) || 0;
      return { alt_group_code: val.slice(4), qty: qtyRaw, uom: chosenUom, tol_pct };
    }
    const qtyRaw = parseFloat(tr.querySelector(".bm-qty").value) || 0;
    const mat = (CACHE.materials || []).find(m => m.code === val);
    // Nếu chọn đơn vị phụ (VD "bao") để nhập, quy đổi về đơn vị chính trước khi gửi — server
    // luôn lưu/scale BOM theo đơn vị chính của vật tư.
    const qty = altUomToBaseQty(mat, qtyRaw, chosenUom);
    return {
      material_code: val,
      qty,
      uom: mat ? mat.uom : chosenUom,
      tol_pct,
    };
  }).filter(l => (l.material_code || l.alt_group_code) && (l.member_qty ? l.member_qty.length > 0 : l.qty > 0));
}
function versionFormHTML(v, recipe) {
  v = v || {};
  const productOpts = (CACHE.products || []).filter(p => !recipe || p.beer_type_id === recipe.beer_type_id)
    .map(p => `<option value="${p.product_id}" ${p.product_id === v.product_id ? "selected" : ""}>${esc(p.code)} — ${esc(p.name)}</option>`).join("");
  const rows = (v.materials && v.materials.length ? v.materials : [{}]).map(bomRowHTML).join("");
  return `<div class="panel"><h2>${v.version_id ? "Sửa" : "Tạo"} version công thức ${v.version_id ? "v" + v.version_no : ""}</h2>
    <div class="row">
      <div class="field"><label>Dịch bia</label><select id="vf_product"><option value="">(chọn dịch bia — bắt buộc)</option>${productOpts}</select></div>
      <div class="field"><label>Quy mô mẻ chuẩn</label><input id="vf_base" type="number" value="${v.base_qty || 50000}" style="width:140px"/></div>
      <div class="field"><label>ĐVT</label><input id="vf_baseu" value="${esc(v.base_uom || "L")}" size="5"/></div>
      <span class="muted" style="align-self:center">BOM bên dưới tính cho quy mô này; khi chạy mẻ sẽ tự scale theo SL kế hoạch.</span>
    </div>
    <div class="field"><label>Ghi chú</label><input id="vf_note" style="width:100%" value="${esc(v.change_reason || "")}" placeholder="(tuỳ chọn) — hiển thị kèm khi chọn version này ở Lệnh nấu"/></div>
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
  const recipe = (CACHE.recipes || []).find(r => r.recipe_id === recipeId);
  $("rv_detail").innerHTML = versionFormHTML(null, recipe);
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
  const recipe = (CACHE.recipes || []).find(r => r.recipe_id === v.recipe_id);
  $("rv_detail").innerHTML = versionFormHTML(v, recipe);
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
    product_id: $("vf_product").value,
    base_qty: parseFloat($("vf_base").value) || 0,
    base_uom: $("vf_baseu").value,
    change_reason: $("vf_note").value.trim() || null,
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
        <td>${l.pct}%</td><td><span class="badge ${{dat:"available",vuot:"critical",thieu:"due",chua_dung:"planned"}[l.status] || "planned"}">${{dat:"đạt",vuot:"vượt định mức",thieu:"thiếu",chua_dung:"chưa dùng"}[l.status] || l.status}</span></td></tr>`).join("")}
      ${(bom.extras || []).map(e => `<tr><td><code class="k">${esc(e.material_code)}</code></td><td class="muted">(ngoài BOM)</td><td>${e.actual}</td><td colspan=3><span class="badge obsolete">ngoài định mức</span></td></tr>`).join("")}</tbody></table>`
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
  const [results, devs, batches, lots, materials, qcParams, brewBatches, fermentsData, filtersData, bottlesData, holdHistory, pendingStageQc, capas, matLocsQuality, pendingKcPxQuality, pendingSngQuality] = await Promise.all([
    GET("/quality/results"), GET("/quality/deviations"), GET("/batches"), GET("/lots"), GET("/materials"),
    GET("/qc/parameters?active_only=false").catch(() => []),
    GET("/brewing/brew-batches").catch(() => []),
    GET("/brewing/ferments").catch(() => ({ items: [] })),
    GET("/brewing/filters").catch(() => []),
    GET("/brewing/bottles").catch(() => []),
    GET("/audit?action=hold,release&limit=100").catch(() => []),
    GET("/quality/pending-stage-qc").catch(() => []),
    GET("/qc/capa").catch(() => []),
    GET("/warehouse/locations").catch(() => []),
    GET("/warehouse/transfer-kcpx-requests?status=pending").catch(() => []),
    GET("/warehouse/sang-ngang?status=pending").catch(() => [])]);
  // Deviation major/critical bắt buộc có CAPA đã đóng trước khi đóng được (xem
  // services/quality.py::_has_closed_capa) — tính sẵn theo deviation_id để devRow() cảnh báo
  // sớm phía UI, chặn thật vẫn ở backend.
  const closedCapaDevIds = new Set(capas.filter(c => c.state === "closed" && c.deviation_id).map(c => c.deviation_id));
  const anyCapaDevIds = new Set(capas.filter(c => c.deviation_id).map(c => c.deviation_id));
  // Map deviation_id -> [CAPA...] để render cột "CAPA liên kết" bấm được (điều hướng 2 chiều
  // Deviation<->CAPA — xem PENDING_OPEN_CAPA_ID/PENDING_OPEN_DEVIATION_ID).
  const capaByDevId = {};
  capas.filter(c => c.deviation_id).forEach(c => (capaByDevId[c.deviation_id] ??= []).push(c));
  const ferments = fermentsData.items || [];
  // Hold/Release + Mở deviation tách riêng theo công đoạn sản xuất (Nấu/Lên men/Lọc/Chiết),
  // ngoài Mẻ SX (ISA-88)/Lô NVL đã có — mỗi <optgroup> 1 công đoạn, nhãn kèm trạng thái hiện
  // tại để thấy ngay công đoạn nào đang bị giữ. Xem services/quality.py::_STAGE_MODELS.
  const hqLabel = (q) => q === "on_hold" ? " — ĐANG HOLD" : "";
  // Deviation đã "closed" (đã qua CAPA/approval) coi như xong việc — ẩn khỏi danh sách, chỉ
  // hiện những cái còn đang xử lý để không làm rối bảng theo thời gian.
  const openDevs = devs.filter(d => d.state !== "closed");
  // Điều hướng từ CAPA -> Deviation (bấm mã Deviation trong cột "Deviation liên kết" ở CAPA) —
  // tiêu thụ 1 lần đúng mẫu PENDING_CAPA_DEVIATION (chiều ngược lại). Deviation đã đóng bị ẩn
  // khỏi openDevs nên không cuộn tới được — hiện thông báo thay vào đó.
  let devNavNotice = "";
  let devNavHighlightId = null;
  if (PENDING_OPEN_DEVIATION_ID) {
    const targetId = PENDING_OPEN_DEVIATION_ID;
    PENDING_OPEN_DEVIATION_ID = null;
    if (openDevs.some(d => d.deviation_id === targetId)) {
      devNavHighlightId = targetId;
    } else {
      const closedDev = devs.find(d => d.deviation_id === targetId);
      devNavNotice = `<div class="muted" style="margin-bottom:6px">Deviation ${esc(closedDev?.deviation_code || "")} đã đóng — không hiện trong danh sách này.</div>`;
    }
  }
  const batchById = Object.fromEntries(batches.map(b => [b.batch_id, b]));
  const lotById = Object.fromEntries(lots.map(l => [l.lot_id, l]));
  const matById = Object.fromEntries(materials.map(m => [m.material_id, m]));
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
  // Gộp các dòng chỉ tiêu (đã gán groupLabel/paramLabel ở qcResultsWithGroupLabel) thành 1
  // dòng tổng hợp cho mỗi mẻ/lô nguồn — người dùng bấm "Xem chi tiết" mới thấy từng chỉ tiêu,
  // thay vì liệt kê lặp lại tên mẻ/lô cho mỗi chỉ tiêu như trước.
  const qcGroups = groupQcResultsByScope(qcResultsWithGroupLabel(results,
    { batchById, lotById, brewBatchByKey, fermentByLm, filterByCode, bottleByCode, paramByCode }));
  // Quy đổi mỗi qcGroup (dùng quy ước scope_id riêng của QualityResult — xem comment ở
  // qcResultsWithGroupLabel) về khóa "scope_type:PK thật" khớp với value của <option> bên dưới
  // VÀ khớp với Deviation.scope_type/scope_id (luôn là PK thật, xem services/quality.py) — nhờ
  // đó biết ngay mẻ/lô nào đang có chỉ tiêu FAIL để gợi ý trong dropdown Hold/Release/Mở
  // deviation, và để hiện cột "Chỉ tiêu không đạt" trong bảng Deviations bên dưới.
  const scopeKeyToFailParams = {};
  for (const g of qcGroups) {
    if (!g.failCount) continue;
    const failLabels = g.rows.filter(r => r.status === "fail").map(r => r.paramLabel);
    let key = null;
    if (g.scope_type === "batch" || g.scope_type === "lot") key = `${g.scope_type}:${g.scope_id}`;
    else if (g.scope_type === "brew_batch" || g.scope_type === "brew") key = `brew_batch:${g.scope_id}`;
    else if (g.scope_type === "ferment") { const [lmCode] = g.scope_id.split("__"); const f = fermentByLm[lmCode]; if (f) key = `ferment:${f.ferment_id}`; }
    else if (g.scope_type === "filter") { const f = filterByCode[g.scope_id]; if (f) key = `filter:${f.filter_id}`; }
    else if (g.scope_type === "bottle") { const [code] = g.scope_id.split("__"); const b = bottleByCode[code]; if (b) key = `bottle:${b.bottle_id}`; }
    if (key) (scopeKeyToFailParams[key] || (scopeKeyToFailParams[key] = [])).push(...failLabels);
  }
  // Gợi ý ngay trong dropdown mẻ/lô nào đang có chỉ tiêu không đạt — hiện cảnh báo kèm tên chỉ
  // tiêu, và tách hẳn thành 2 optgroup riêng: "Đang FAIL" (gộp mọi công đoạn) lên trên, và
  // "Không FAIL" bên dưới — thay vì trộn theo công đoạn rồi sắp fail lên đầu như trước.
  const failMark = (key) => {
    const params = scopeKeyToFailParams[key];
    if (!params || !params.length) return "";
    const uniq = [...new Set(params)];
    return ` ⚠ FAIL: ${esc(uniq.slice(0, 2).join(", "))}${uniq.length > 2 ? "…" : ""}`;
  };
  const scopeStages = [
    { tag: "Mẻ SX", items: batches, keyFn: b => `batch:${b.batch_id}`,
      optFn: b => `mẻ ${esc(b.batch_code)}` },
    { tag: "Nấu", items: brewBatches, keyFn: b => `brew_batch:${b.batch_id}`,
      optFn: b => `mẻ ${esc(b.batch_code)} (mã nấu ${esc(b.brew_code || "?")})${hqLabel(b.quality_status)}` },
    { tag: "Lên men", items: ferments, keyFn: f => `ferment:${f.ferment_id}`,
      optFn: f => `lô LM ${esc(f.lm_code)}${hqLabel(f.quality_status)}` },
    { tag: "Lọc", items: filtersData, keyFn: f => `filter:${f.filter_id}`,
      optFn: f => `mẻ lọc ${esc(f.filter_code)}${hqLabel(f.quality_status)}` },
    { tag: "Chiết", items: bottlesData, keyFn: b => `bottle:${b.bottle_id}`,
      optFn: b => `mã chiết ${esc(b.bottle_code)}${hqLabel(b.quality_status)}` },
    { tag: "NVL", items: lots, keyFn: l => `lot:${l.lot_id}`,
      optFn: l => `lô ${esc(l.lot_code)}` },
  ];
  const scopeEntries = scopeStages.flatMap(({ tag, items, keyFn, optFn }) => items.map(item => {
    const key = keyFn(item);
    return { key, failing: !!scopeKeyToFailParams[key]?.length,
      html: `<option value="${key}">[${tag}] ${optFn(item)}${failMark(key)}</option>` };
  }));
  const failEntries = scopeEntries.filter(e => e.failing);
  const okEntries = scopeEntries.filter(e => !e.failing);
  const hdScopeOpts = `<optgroup label="⚠ Đang FAIL chỉ tiêu (${failEntries.length})">${
      failEntries.map(e => e.html).join("") || '<option disabled>Không có</option>'}</optgroup>
    <optgroup label="Không FAIL (${okEntries.length})">${okEntries.map(e => e.html).join("")}</optgroup>`;
  // Nhãn hiển thị cho lịch sử Hold/Release — scope_id ở đây LUÔN là PK thật (khác quy ước
  // scope_id ghép chuỗi của qc_catalog dùng cho khai báo chỉ tiêu), xem services/quality.py.
  const holdScopeLabel = (scopeType, scopeId) => {
    if (scopeType === "batch") return `Mẻ SX ${batchById[scopeId] ? esc(batchById[scopeId].batch_code) : scopeId}`;
    if (scopeType === "lot") return `Lô NVL ${lotById[scopeId] ? esc(lotById[scopeId].lot_code) : scopeId}`;
    if (scopeType === "brew_batch") { const b = brewBatchByKey[scopeId];
      return b ? `Mẻ nấu ${esc(b.batch_code)} (mã nấu ${esc(b.brew_code || "?")})` : `Mẻ nấu ${scopeId}`; }
    if (scopeType === "ferment") return `Lô LM ${fermentById[scopeId] ? esc(fermentById[scopeId].lm_code) : scopeId}`;
    if (scopeType === "filter") return `Mẻ lọc ${filterById[scopeId] ? esc(filterById[scopeId].filter_code) : scopeId}`;
    if (scopeType === "bottle") return `Lô chiết ${bottleById[scopeId] ? esc(bottleById[scopeId].bottle_code) : scopeId}`;
    return `${esc(scopeType)} ${scopeId}`;
  };
  // Lọc đúng "Lô NVL" (material_id có giá trị) — lô bright tank/thành phẩm cũng dùng chung
  // MaterialLot.status=on_hold cho lý do khác (QC mẻ/sản phẩm, không phải chỉ tiêu NVL) nên
  // không có material_id; hiện lẫn vào đây sẽ mở "Khai báo/Duyệt" ra trống trơn (không có chỉ
  // tiêu NVL nào để khai vì required_params_for_material cần material_id) — gây hiểu lầm.
  const pendingQc = lots.filter(l => l.status === "on_hold" && l.material_id);
  // "Nghiệp vụ" — vì sao lô này đang HOLD: nếu có đề nghị Điều chuyển CT->PX (transfer-kcpx) hoặc
  // Xuất sang ngang đang "pending" gắn với lô, thì HOLD là do đang chờ KCS duyệt lại để PX nhận
  // hàng (xem create_transfer_kcpx_request/create_sang_ngang ở services/warehouse.py) — hiện rõ
  // vị trí nguồn (Kho công ty) để KCS biết ngay bối cảnh, không phải tự suy đoán từ mã lô.
  const matLocByIdQuality = Object.fromEntries((matLocsQuality || []).map(m => [m.loc_id, m]));
  const locLabelQuality = (locId) => { const m = matLocByIdQuality[locId]; return m ? `${esc(m.code)} — ${esc(m.name)}` : ""; };
  const nghiepVuByLotId = {};
  (pendingKcPxQuality || []).forEach(r => {
    const l = lotById[r.lot_id]; if (!l) return;
    nghiepVuByLotId[r.lot_id] = `Điều chuyển từ Kho công ty${l.location_id ? ` – ${locLabelQuality(l.location_id)}` : ""} sang Kho phân xưởng`;
  });
  (pendingSngQuality || []).forEach(r => {
    const l = lotById[r.lot_id]; if (!l || nghiepVuByLotId[r.lot_id]) return;
    nghiepVuByLotId[r.lot_id] = `Xuất sang ngang từ Kho công ty${l.location_id ? ` – ${locLabelQuality(l.location_id)}` : ""} sang Kho phân xưởng`;
  });
  $("view-quality").innerHTML = `
    <div class="panel"><h2>🔬 Lô NVL chờ khai báo/duyệt chỉ tiêu chất lượng <span class="muted">(${pendingQc.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Nguyên liệu nhập kho có gán nhóm chỉ tiêu bắt buộc sẽ nằm ở đây cho tới khi KCS khai báo đủ &amp; duyệt.</div>
      <input class="searchbox" data-tbl="t_qcpendinglots" placeholder="Tìm theo mã lô, mã/tên NVL..."/>
      <div class="tablewrap"><table id="t_qcpendinglots">
        <thead><tr><th>Lô</th><th>Mã NVL</th><th>Tên NVL</th><th>SL</th><th>Vị trí</th><th>Nghiệp vụ</th><th>Ngày nhập</th><th></th></tr></thead>
        <tbody>${pendingQc.map(l => `<tr>
          <td><code class="k">${lotCodeCellHtml(l)}</code>${badge("on_hold")}</td>
          <td class="muted">${esc(matById[l.material_id] ? matById[l.material_id].code : "")}</td>
          <td>${esc(matById[l.material_id] ? matById[l.material_id].name : "")}</td>
          <td>${l.quantity} ${l.uom}</td><td class="muted">${esc(l.location || "")}</td>
          <td class="muted">${nghiepVuByLotId[l.lot_id] || "—"}</td>
          <td class="muted">${fmt(l.created_at)}</td>
          <td><button class="btn sm" data-qclot="${esc(l.lot_id)}">Khai báo / Duyệt</button></td></tr>`).join("") ||
          '<tr><td colspan=8 class="muted">Không có lô nào đang chờ.</td></tr>'}</tbody>
      </table></div>
    </div>
    <div class="panel"><h2>🧪 Công đoạn chờ khai báo chỉ tiêu chất lượng <span class="muted">(${pendingStageQc.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Mẻ nấu/lô lên men/mẻ lọc/mã chiết có gán nhóm chỉ tiêu bắt buộc nhưng chưa khai báo đủ sẽ nằm ở đây — bấm "Khai báo" để chuyển tới đúng công đoạn.</div>
      <input class="searchbox" data-tbl="t_stageqcpending" placeholder="Tìm theo công đoạn, mẻ/lô..."/>
      <div class="tablewrap"><table id="t_stageqcpending">
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
        <div id="h_scope_qc" class="muted" style="margin-bottom:8px">Đang tải chỉ tiêu của phạm vi này...</div>
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
          <div class="field"><label>Hạn xử lý</label><input id="d_due" type="date"/></div>
          <button class="btn sec" id="d_open">Mở</button>
        </div>
        <div class="muted" style="margin-bottom:8px">Deviation mức <b>major/critical</b> bắt buộc phải có CAPA liên kết đã đóng (root cause + action plan + hiệu lực + ngày kiểm tra) trước khi đóng được.</div>
        <div id="d_scope_qc" class="muted" style="margin-bottom:8px">Đang tải chỉ tiêu của phạm vi này...</div>
        <h3>Lịch sử Hold/Release <span class="muted">(${holdHistory.length})</span></h3>
        <input class="searchbox" data-tbl="t_holdrelease" placeholder="Tìm theo phạm vi, hành động, lý do, người thực hiện..."/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_holdrelease">
          <thead><tr><th>Lúc</th><th>Phạm vi</th><th>Hành động</th><th>Lý do</th><th>Chỉ tiêu liên quan</th><th>Người thực hiện</th></tr></thead>
          <tbody>${holdHistory.map(h => `<tr>
            <td class="muted">${fmt(h.ts)}</td>
            <td>${holdScopeLabel(h.entity_type, h.entity_id)}</td>
            <td>${h.action === "hold" ? badge("on_hold") + "HOLD" : badge("available") + "RELEASE"}</td>
            <td class="muted">${esc(h.reason || "—")}</td>
            <td class="muted">${esc((h.after && h.after.parameter) || "—")}</td>
            <td class="muted">${esc(h.actor || "")}</td></tr>`).join("") ||
            '<tr><td colspan=6 class="muted">Chưa có lượt Hold/Release nào.</td></tr>'}</tbody>
        </table></div>
    </div>
    <div class="panel"><h2>Kết quả QC gần đây</h2>
      <div class="muted" style="margin-bottom:6px">Gộp theo mẻ/lô nguồn — mỗi công đoạn (mẻ nấu, lô LM, lô lọc, mã chiết, lô NVL...) là 1 dòng. Bấm vào tên mẻ/lô để chuyển tới đúng khu vực, bấm "Xem chi tiết" để xem từng chỉ tiêu.</div>
      <input class="searchbox" data-tbl="t_qcresults" placeholder="Tìm theo mẻ/lô, người ghi..."/>
      <div class="tablewrap" style="margin-top:6px"><table id="t_qcresults">
      <thead><tr><th>Mẻ/lô nguồn</th><th>Số chỉ tiêu</th><th>KQ</th><th>Người ghi gần nhất</th><th>Cập nhật lúc</th><th></th></tr></thead>
      <tbody>${qcGroups.map((g, gi) => `<tr>
        <td class="muted">${g.navigable ? `<button type="button" class="btn sm sec" data-navscope="${esc(g.scope_type)}|${esc(g.scope_id)}">${esc(g.groupLabel)}</button>` : esc(g.groupLabel)}</td>
        <td>${g.count}</td>
        <td>${badge(g.overallStatus)}${g.failCount > 0 ? ` <span class="muted">(${g.failCount}/${g.count})</span>` : ""}</td>
        <td class="muted">${esc(g.recordedBy || "")}</td><td class="muted">${fmt(g.latestAt)}</td>
        <td><button type="button" class="btn sm sec" data-qcdetail="${gi}">Xem chi tiết</button></td></tr>`).join("") ||
        '<tr><td colspan=6 class="muted">Chưa có kết quả QC nào.</td></tr>'}</tbody></table></div></div>
    <div class="panel"><h2>Deviations <span class="muted">(${openDevs.length} đang mở)</span></h2>
      ${devNavNotice}
      <input class="searchbox" data-tbl="t_deviations" placeholder="Tìm theo mã, lý do..."/>
      <table id="t_deviations"><thead><tr><th>Mã</th><th>Mức</th><th>Lý do</th><th>Chỉ tiêu không đạt</th><th>CAPA liên kết</th><th>Trạng thái</th><th>Hành động</th></tr></thead>
      <tbody>${openDevs.map(d => devRow(d, scopeKeyToFailParams[`${d.scope_type}:${d.scope_id}`], closedCapaDevIds.has(d.deviation_id), anyCapaDevIds.has(d.deviation_id), capaByDevId[d.deviation_id] || [])).join("") ||
        '<tr><td colspan=7 class="muted">Không còn deviation nào đang mở.</td></tr>'}</tbody></table></div>`;
  const parseScope = (v) => { const [t, i] = v.split(":"); return { scope_type: t, scope_id: i }; };
  // Lấy chỉ tiêu ĐÃ khai báo cho 1 phạm vi (mẻ/lô) để hiện trước khi Hold/Release/Mở deviation —
  // người bấm cần thấy NGAY vì sao (chỉ tiêu nào fail/đạt) thay vì chỉ gõ lý do tự do. Quy ước
  // scope_id lưu ở QualityResult khác nhau theo loại: lot/batch/brew_batch dùng thẳng scope_id
  // (khớp _get_scope_obj), còn ferment/filter/bottle dùng mã CÓ NĂM (year-lm_code__part /
  // year-filter_code / year-bottle_code__thanh_pham, xem qc_catalog.ferment_scope_id/
  // filter_scope_id/bottle_scope_id — mã lô LM/lọc/chiết chỉ duy nhất TRONG 1 năm nên phải kèm
  // năm để không lẫn giữa 2 lô khác năm trùng mã) — phải quy đổi ngược từ id sang mã tương ứng
  // trước khi gọi /quality/results.
  async function scopeQcParams(scopeValue) {
    const [type, id] = scopeValue.split(":");
    const paramLabel = (code) => { const p = paramByCode[code]; return p ? p.name : code; };
    try {
      if (type === "lot") {
        const st = await GET(`/lots/${id}/qc-status`);
        return (st.recorded || []).map(r => ({ code: r.parameter, label: paramLabel(r.parameter), value: r.value, status: r.status }));
      }
      let results;
      if (type === "ferment") {
        const f = fermentById[id];
        if (!f) return [];
        const [chinh, phu] = await Promise.all([
          GET(`/quality/results?scope_id=${encodeURIComponent(f.ferment_year + "-" + f.lm_code + "__len_men_chinh")}`),
          GET(`/quality/results?scope_id=${encodeURIComponent(f.ferment_year + "-" + f.lm_code + "__len_men_phu")}`)]);
        results = [...chinh, ...phu];
      } else if (type === "filter") {
        const flt = filterById[id];
        results = flt ? await GET(`/quality/results?scope_id=${encodeURIComponent(flt.filter_year + "-" + flt.filter_code)}`) : [];
      } else if (type === "bottle") {
        const b = bottleById[id];
        results = b ? await GET(`/quality/results?scope_id=${encodeURIComponent(b.bottle_year + "-" + b.bottle_code + "__thanh_pham")}`) : [];
      } else {
        // batch, brew_batch: scope_id dùng thẳng id
        results = await GET(`/quality/results?scope_id=${encodeURIComponent(id)}`);
      }
      const seen = new Set(); const out = [];
      for (const r of results) {
        if (seen.has(r.parameter)) continue;
        seen.add(r.parameter);
        out.push({ code: r.parameter, label: paramLabel(r.parameter), value: r.value, status: r.status });
      }
      return out;
    } catch (e) { return []; }
  }
  async function renderScopeQcPanel(containerId, scopeValue) {
    const el = $(containerId);
    if (!el) return;
    el.innerHTML = `<span class="muted">Đang tải chỉ tiêu của phạm vi này...</span>`;
    const params = await scopeQcParams(scopeValue);
    if (!params.length) { el.innerHTML = `<span class="muted">Phạm vi này chưa khai báo chỉ tiêu chất lượng nào.</span>`; return; }
    el.innerHTML = `<div class="muted" style="margin-bottom:4px">Chỉ tiêu của phạm vi này — tick chỉ tiêu liên quan tới thao tác này:</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px">${params.map(p => `
        <label style="display:inline-flex;align-items:center;gap:4px;border:1px solid var(--border);border-radius:6px;padding:2px 8px;font-size:12px">
          <input type="checkbox" class="scope-qc-param" value="${esc(p.code)}"/>
          ${esc(p.label)}: ${p.value ?? "—"} ${badge(p.status)}
        </label>`).join("")}</div>`;
  }
  const checkedParams = (containerId) => Array.from(document.querySelectorAll(`#${containerId} .scope-qc-param:checked`))
    .map(i => i.value).join(",") || null;
  // Đến từ 1 dòng cảnh báo trên Dashboard (Cảnh báo QC/Hold-Release/Deviation) — set sẵn đúng
  // phạm vi vào select tương ứng (chỉ dùng 1 lần rồi xoá, không áp dụng lại nếu người dùng
  // load lại trang Chất lượng theo cách khác).
  if (PENDING_QUALITY_SCOPE) {
    const { key, kind } = PENDING_QUALITY_SCOPE;
    PENDING_QUALITY_SCOPE = null;
    const targetSelect = kind === "dev" ? $("d_scope") : $("h_scope");
    if (targetSelect && [...targetSelect.options].some(o => o.value === key)) {
      targetSelect.value = key;
      targetSelect.closest(".panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }
  renderScopeQcPanel("h_scope_qc", $("h_scope").value);
  renderScopeQcPanel("d_scope_qc", $("d_scope").value);
  $("h_scope").addEventListener("change", () => renderScopeQcPanel("h_scope_qc", $("h_scope").value));
  $("d_scope").addEventListener("change", () => renderScopeQcPanel("d_scope_qc", $("d_scope").value));
  $("h_hold").onclick = () => guard(async () => {
    const reason = $("h_hold_reason").value.trim();
    if (!reason) throw new Error("Bắt buộc nhập Lý do HOLD.");
    await POST("/quality/hold", { ...parseScope($("h_scope").value), on_hold: true, reason, parameter: checkedParams("h_scope_qc") });
    toast("Đã HOLD"); render("quality");
  });
  $("h_rel").onclick = () => guard(async () => {
    const reason = $("h_release_reason").value.trim();
    if (!reason) throw new Error("Bắt buộc nhập Lý do RELEASE.");
    await POST("/quality/hold", { ...parseScope($("h_scope").value), on_hold: false, reason, parameter: checkedParams("h_scope_qc") });
    toast("Đã RELEASE"); render("quality");
  });
  wireSelectSearch("h_scope", "h_scope_q");
  wireSelectSearch("d_scope", "d_scope_q");
  $("d_open").onclick = () => guard(async () => {
    await POST("/quality/deviations", { ...parseScope($("d_scope").value), severity: $("d_sev").value,
      reason: $("d_reason").value, parameter: checkedParams("d_scope_qc"), due_date: $("d_due").value || null });
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
  document.querySelectorAll("[data-devcapa]").forEach(b => b.onclick = () => {
    PENDING_CAPA_DEVIATION = b.dataset.devcapa;
    gotoView("qclab");
  });
  document.querySelectorAll("[data-opencapa]").forEach(b => b.onclick = () => {
    PENDING_OPEN_CAPA_ID = b.dataset.opencapa;
    gotoView("qclab");
  });
  if (devNavHighlightId) {
    const row = document.querySelector(`tr[data-devid="${devNavHighlightId}"]`);
    if (row) {
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.style.outline = "2px solid var(--accent)";
      setTimeout(() => { row.style.outline = ""; }, 2000);
    }
  }
  document.querySelectorAll("[data-qclot]").forEach(b => b.onclick = () => openLotQcModal(b.dataset.qclot, { editable: true }));
  document.querySelectorAll("[data-qcdetail]").forEach(b => b.onclick = () => {
    const g = qcGroups[parseInt(b.dataset.qcdetail, 10)];
    modal(`<h3>Chỉ tiêu — ${esc(g.groupLabel)}</h3>
      <div class="tablewrap"><table>
        <thead><tr><th>Tham số</th><th>Giá trị</th><th>Giới hạn</th><th>KQ</th><th>Người ghi</th><th>Lúc</th></tr></thead>
        <tbody>${g.rows.map(r => `<tr><td>${esc(r.paramLabel)}</td><td>${r.value ?? "—"} ${esc(r.unit || "")}</td>
          <td class="muted">${r.lower_limit ?? "−∞"} … ${r.upper_limit ?? "+∞"}</td><td>${badge(r.status)}</td>
          <td class="muted">${esc(r.recorded_by || "")}</td><td class="muted">${fmt(r.recorded_at)}</td></tr>`).join("")}</tbody>
      </table></div>`);
  });
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
  wirePaginate("t_qcpendinglots", 10);
  wirePaginate("t_stageqcpending", 10);
  wirePaginate("t_deviations", 10);
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
      return { label: `Lô chiết ${bottleCode}`, navigable: !!b };
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
// Gộp các dòng chỉ tiêu (đã có groupLabel/paramLabel từ qcResultsWithGroupLabel) thành 1 dòng
// tổng hợp mỗi mẻ/lô nguồn — cùng 1 lô + cùng 1 lượt khai báo chỉ tiêu (scope_type/scope_id)
// thì chỉ hiện 1 dòng, xem từng chỉ tiêu qua nút "Xem chi tiết" thay vì liệt kê lặp lại tên
// mẻ/lô cho mỗi tham số như trước.
function groupQcResultsByScope(rows) {
  const order = []; const byKey = new Map();
  for (const r of rows) {
    const key = `${r.scope_type}|${r.scope_id}`;
    if (!byKey.has(key)) { byKey.set(key, []); order.push(key); }
    byKey.get(key).push(r);
  }
  return order.map(key => {
    const [scope_type, scope_id] = key.split("|");
    const groupRows = byKey.get(key);
    const failCount = groupRows.filter(r => r.status === "fail").length;
    const overallStatus = failCount > 0 ? "fail" : groupRows.every(r => r.status === "pass") ? "pass" : (groupRows[0].status || "pass");
    const recordedBy = [...new Set(groupRows.map(r => r.recorded_by).filter(Boolean))].join(", ");
    const latestAt = groupRows.reduce((max, r) => !max || new Date(r.recorded_at) > new Date(max) ? r.recorded_at : max, null);
    return { scope_type, scope_id, groupLabel: groupRows[0].groupLabel, navigable: groupRows[0].navigable,
      rows: groupRows, count: groupRows.length, failCount, overallStatus, recordedBy, latestAt };
  });
}
// Chuyển sang "investigation" cần ghi Nội dung điều tra; chuyển sang "disposition" cần ghi
// Hướng xử lý — 2 trường CAPA này backend đã hỗ trợ (DeviationTransitionIn.investigation/
// disposition) nhưng trước đây UI không có ô nhập, nút chỉ đổi trạng thái suông.
const DEV_TEXT_FIELD = {
  investigation: { field: "investigation", label: "Nội dung điều tra" },
  disposition: { field: "disposition", label: "Hướng xử lý" },
  closed: { field: "close_note", label: "Ghi chú đóng" },
};
// failParams: mảng tên chỉ tiêu ĐANG fail (live, tính từ kết quả QC gần đây nhất của đúng
// phạm vi deviation này — xem scopeKeyToFailParams trong VIEWS.quality), không phải chỉ tiêu
// người mở TỰ CHỌN lúc "Mở" (d.parameter) — hiện cả 2 để phân biệt rõ.
// hasClosedCapa/hasAnyCapa: tính sẵn ở VIEWS.quality từ GET /qc/capa — dùng để cảnh báo sớm
// phía UI khi severity major/critical còn thiếu CAPA đã đóng (chặn thật ở backend,
// services/quality.py::transition_deviation nhánh CLOSED).
function devRow(d, failParams, hasClosedCapa, hasAnyCapa, capaList) {
  const next = { open: ["triage"], triage: ["investigation"], investigation: ["disposition"],
    disposition: ["approval"], approval: ["closed"], closed: [] }[d.state] || [];
  const needsCapa = ["major", "critical"].includes(d.severity) && !hasClosedCapa;
  const actions = next.map(n => {
    const t = DEV_TEXT_FIELD[n];
    if (!t) return `<button class="btn sm sec" data-dt="${n}" data-did="${d.deviation_id}">→ ${n}</button>`;
    return `<span style="display:inline-flex;gap:4px;align-items:center">
      <input class="dv-text" data-devfield="${t.field}" placeholder="${esc(t.label)}..." style="width:150px"/>
      <button class="btn sm sec" data-dt="${n}" data-did="${d.deviation_id}" data-devfield="${t.field}">→ ${n}</button>
    </span>`;
  }).join(" ");
  const notes = [d.investigation ? `<div class="muted">Điều tra: ${esc(d.investigation)}</div>` : "",
    d.disposition ? `<div class="muted">Xử lý: ${esc(d.disposition)}</div>` : "",
    d.due_date ? `<div class="muted">Hạn xử lý: ${esc(d.due_date)}</div>` : "",
    needsCapa ? `<div class="muted" style="color:var(--red)">⚠ Chưa có CAPA đóng — bắt buộc trước khi đóng deviation này.
      <button class="btn sm sec" data-devcapa="${d.deviation_id}">+ Tạo CAPA</button></div>` : ""].join("");
  const failCell = failParams && failParams.length
    ? `<span class="badge fail">${esc([...new Set(failParams)].join(", "))}</span>`
    : d.parameter ? `<span class="muted">${esc(d.parameter)} (đã chọn khi mở)</span>` : `<span class="muted">—</span>`;
  const capaCell = (capaList && capaList.length)
    ? capaList.map(c => `<button class="btn sm sec" data-opencapa="${esc(c.capa_id)}">${esc(c.capa_code)}</button>`).join(" ")
    : `<span class="muted">—</span>`;
  return `<tr data-devid="${esc(d.deviation_id)}"><td><code class="k">${esc(d.deviation_code)}</code></td><td>${badge(d.severity)}</td>
    <td>${esc(d.reason)}${notes}</td><td>${failCell}</td><td>${capaCell}</td><td>${badge(d.state)}</td><td style="white-space:nowrap">${actions || "—"}</td></tr>`;
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
function cipLinksHtml(cip) {
  if (!cip || !cip.length) return '<div class="muted" style="font-size:12px">Chưa gắn CIP nào.</div>';
  return `<table><thead><tr><th>Mã CIP</th><th>Thiết bị</th><th>Thời gian</th><th>Kết quả</th></tr></thead>
    <tbody>${cip.map(c => `<tr><td class="code">${esc(c.cip_code)}</td><td>${esc(c.equipment_name || "—")}</td>
      <td class="muted">${fmt(c.started_at)}</td>
      <td>${c.result === "dat" ? '<span class="qc-pill ok">Đạt</span>' : c.result === "khong_dat" ? '<span class="qc-pill err">Không đạt</span>' : '<span class="qc-pill muted">Chờ nghiệm thu</span>'}</td></tr>`).join("")}</tbody></table>`;
}
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
      <h4>CIP liên quan</h4>${cipLinksHtml(b.cip)}
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
      <h4>CIP liên quan</h4>${cipLinksHtml(f.cip)}
      <h4>Biểu đồ theo dõi lên men</h4>
      ${(f.readings && f.readings.length) ? _flChartHtml(f.readings) : '<div class="muted">Chưa có số liệu ghi chép hàng ngày.</div>'}
    </div>`).join("") || `<div class="muted">Không có lô lên men nào trong chuỗi này.</div>`;

  const locBlock = data.filters.map(f => `
    <div class="panel" style="margin-top:8px">
      <h3>Mã lọc ${esc(f.filter_code)} <span class="muted">(mã nấu ${esc(f.brew_code || "—")} · Lệnh lọc ${esc(f.filter_master_order_code || f.filter_order_code || "—")}${f.batch_number || f.order_number ? ` · Số mẻ ${esc(f.batch_number || "—")} · Số lệnh ${esc(f.order_number || "—")}` : ""})</span></h3>
      ${periodLine(f.started_at, f.ended_at)}
      ${f.is_refilter ? `<div class="muted" style="color:var(--red)">⚠ Lọc lại từ tank BBT <b>${esc(f.refilter_source_bbt_code)}</b> — lý do: ${esc(f.refilter_reason || "—")}</div>` : ""}
      ${qcStatusTable(f.qc)}
      <h4>CIP liên quan</h4>${cipLinksHtml(f.cip)}
      <h4>Mẻ lọc số (từng đợt rút dịch)</h4>
      <table><thead><tr><th>Mẻ lọc số</th><th>Tank nguồn</th><th>V dịch/hl</th><th>Nước bài khí/hl</th><th>V bia/hl</th><th>Kết thúc</th><th></th></tr></thead>
        <tbody>${(f.tank_lines || []).map(l => `<tr>
          <td>${esc(l.batch_seq_no || "—")}</td>
          <td class="muted">${l.tank_type === "bbt" ? `BBT ${esc(l.source_bbt_code || "—")} (lọc lại)` : esc(l.tank_lm || "—")}${l.brew_code ? ` · mã nấu ${esc(l.brew_code)}` : ""}</td>
          <td>${l.v_dich_hl != null ? l.v_dich_hl : "—"}</td>
          <td>${l.nuoc_bai_khi_hl != null ? l.nuoc_bai_khi_hl : "—"}</td>
          <td>${l.v_beer_hl != null ? l.v_beer_hl : "—"}</td>
          <td>${l.ended_at ? fmt(l.ended_at) : "—"}</td>
          <td>${l.is_final_batch ? '<span class="badge planned">Mẻ cuối</span>' : ""}</td>
        </tr>`).join("") ||
          '<tr><td colspan=7 class="muted">Chưa có đợt rút dịch nào.</td></tr>'}</tbody></table>
      <h4>Nguyên vật liệu lọc</h4>
      <table><thead><tr><th>Nguyên liệu</th><th>Lô PM</th><th>Ngày lô</th><th>FIFO</th><th>SL</th><th>ĐVT</th></tr></thead>
        <tbody>${(f.materials || []).map(m => `<tr><td>${esc(m.material_name)}</td><td>${esc(m.lot_pm || "")}</td>
          <td class="muted">${m.lot_date ? fmt(m.lot_date) : "—"}</td><td>${fifoBadgeHtml(m.fifo_ok)}</td>
          <td>${m.quantity}</td><td>${esc(m.uom)}</td></tr>`).join("") ||
          '<tr><td colspan=6 class="muted">Chưa ghi nguyên liệu nào.</td></tr>'}</tbody></table>
    </div>`).join("") || `<div class="muted">Không có bản ghi lọc nào trong chuỗi này.</div>`;

  const chietBlock = data.bottles.map(b => `
    <div class="panel" style="margin-top:8px">
      <h3>Lô chiết ${esc(b.bottle_code)} <span class="muted">(số lô bia ${esc(b.lot_no || "—")})</span></h3>
      ${periodLine(b.started_at, b.ended_at)}
      <h4>Nguyên vật liệu chiết</h4>
      <table><thead><tr><th>Nguyên liệu</th><th>Lô PM</th><th>Ngày lô</th><th>FIFO</th><th>SL</th><th>ĐVT</th></tr></thead>
        <tbody>${(b.materials || []).map(m => `<tr><td>${esc(m.material_name)}</td><td>${esc(m.lot_pm || "")}</td>
          <td class="muted">${m.lot_date ? fmt(m.lot_date) : "—"}</td><td>${fifoBadgeHtml(m.fifo_ok)}</td>
          <td>${m.quantity}</td><td>${esc(m.uom)}</td></tr>`).join("") ||
          '<tr><td colspan=6 class="muted">Chưa ghi nguyên liệu nào.</td></tr>'}</tbody></table>
      <h4>Thành phẩm</h4>${qcStatusTable(b.qc.thanh_pham)}
      <h4>CIP liên quan</h4>${cipLinksHtml(b.cip)}
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
  ferment: "Lô lên men", filter: "Mã lọc", bottle: "Lô chiết",
  finished_goods_unit: "Đơn vị TP", ship_to: "Nơi xuất",
  shipment_group: "Đã xuất", stock_group: "Còn tồn kho",
};
const SHIPMENT_TYPE_LABEL = { promo: "Khuyến mại", return: "Đổi trả", normal: "Thường", mixed: "Nhiều loại" };
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
      <b>${n.count} ${esc(n.unit_type_label || (n.unit_type === "keg" ? "keg" : n.unit_type === "lon" ? "lon" : "vỉ"))}</b>
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
    wireSearch(); wirePaginate("t_audit", 10); wireAuditDetail("t_audit");
  });
  $("au_load").onclick = load; load();
};
// Nhãn tiếng Việt cho Audit trail — entity_type/action là mã kỹ thuật cố định trong code (không
// đổi được vì đã ghi vào các dòng audit cũ), nên dịch sang tiếng Việt CHỈ ở tầng hiển thị. Không
// bao phủ hết mọi entity_type/action có thể xuất hiện (danh mục sinh động theo code, xem
// backend record_audit call sites) — phần không có trong dict sẽ tự "làm đẹp" (thay _ bằng khoảng
// trắng, viết hoa chữ đầu) thay vì hiện mã thô khó đọc.
const AUDIT_ENTITY_LABELS = {
  finished_goods_unit: "Đơn vị kho thành phẩm", near_expiry_entry: "Bia cận date", shipment: "Phiếu xuất kho",
  batch: "Mẻ sản xuất", lot: "Lô", brew_order: "Lệnh nấu", brew_master_order: "Lệnh nấu (gộp)",
  filter_order: "Lệnh lọc", filter_master_order: "Lệnh lọc (gộp)", ferment_record: "Lô lên men",
  bbt_tank: "Tank BBT", work_order: "Lệnh sản xuất (WO)", yeast_lot: "Lô men giống",
  recipe_version: "Phiên bản công thức", packaging: "Bao bì", downtime: "Dừng máy", order: "Lệnh SX",
  schedule: "Lịch sản xuất", quality_result: "Kết quả QC", brew_batch: "Mẻ nấu", ferment: "Lô lên men",
  filter: "Mẻ lọc", bottle: "Lô chiết", deviation: "Deviation (sai lệch)", capa: "CAPA",
  sample: "Mẫu QC", qc_parameter: "Chỉ tiêu QC", qc_parameter_group: "Nhóm chỉ tiêu QC",
  qc_parameter_group_item: "Chỉ tiêu trong nhóm", material_qc_group: "Gán nhóm chỉ tiêu NVL",
  stage_qc_group: "Gán nhóm chỉ tiêu công đoạn", cip_form_type: "Loại biểu mẫu CIP",
  cip_equipment: "Thiết bị CIP", cip_record: "Biên bản CIP", material_request: "Đề nghị nhận kho",
  material_request_line: "Dòng đề nghị nhận kho", stock_movement: "Phiếu xuất/nhập kho NVL",
  stock_count: "Phiếu kiểm kê", auth: "Tài khoản", role_template: "Mẫu chức danh", beer_type: "Loại bia",
  unit_type_catalog: "Loại đơn vị tồn kho", supplier: "Nhà cung cấp", material_group: "Nhóm vật tư",
  product: "Dịch bia", product_brew_spec: "Thông số nấu sản phẩm", finished_product: "Sản phẩm (SKU)",
  material: "Vật tư/NVL", recipe: "Công thức", line: "Dây chuyền", incident: "Sự cố bảo trì",
  ship_to_location: "Nơi xuất đến",
};
const AUDIT_ACTION_LABELS = {
  build: "Tạo/nhập kho", putaway: "Cất vào vị trí", transfer: "Điều chuyển", decompose: "Phân rã 1 đơn vị",
  decompose_batch: "Phân rã theo số lượng", undo_decompose_batch: "Hoàn tác phân rã",
  free_issue_batch: "Xuất tự do", undo_free_issue_batch: "Hoàn tác xuất tự do",
  adjust_bottle_finish: "Điều chỉnh khi kết thúc chiết", relocate_batch: "Cất vào vị trí (theo lô)",
  delete: "Xóa", delete_by_lot: "Xóa theo lô", create: "Tạo mới", undo: "Hoàn tác", update: "Cập nhật",
  record_actual: "Ghi nhận thực tế", consume_lot: "Tiêu thụ lô NVL", produce: "Ghi nhận sản lượng",
  ebr_sign: "Ký hồ sơ lô (EBR)", ebr_lock: "Khóa hồ sơ lô (EBR)", record_yield: "Ghi nhận hiệu suất",
  empty_cct: "Xả rỗng tank CCT", empty_bbt: "Xả rỗng tank BBT", dispatch: "Điều độ",
  harvest: "Thu hoạch men", issue: "Xuất dùng", update_draft: "Cập nhật bản nháp", record: "Ghi nhận",
  record_sample: "Ghi nhận mẫu", auto_schedule: "Tự động lập lịch", hold: "Giữ lô", release: "Nhả lô",
  open: "Mở", register: "Đăng ký", copy_items: "Sao chép chỉ tiêu", link: "Gán", unlink: "Gỡ gán",
  approve: "Duyệt", receipt: "Nhập kho", return: "Trả hàng", cancel: "Hủy phiếu",
  fulfill: "Xuất theo đề nghị", undo_fulfill: "Hoàn tác xuất theo đề nghị", reject: "Từ chối",
  undo_issue: "Hoàn tác xuất kho", post: "Ghi sổ (post)", login: "Đăng nhập",
  login_failed: "Đăng nhập thất bại", logout: "Đăng xuất", change_password: "Đổi mật khẩu",
  create_user: "Tạo tài khoản", set_scope: "Gán phạm vi quyền", copy_permissions: "Sao chép quyền",
  edit_user: "Sửa tài khoản", resolve: "Xử lý xong",
};
const AUDIT_ACTION_PREFIX_LABELS = { transition: "Chuyển trạng thái", isa88: "ISA-88", move: "Di chuyển", sample: "Lấy mẫu" };
// entity_type -> module trên thanh menu chính (đúng tên hiện trên nav, xem index.html) — để biết
// 1 dòng audit thuộc module nào khi entity_type/action không tự nói lên điều đó. "lot" và
// "stock_movement"/"material_request*"/"stock_count" mặc định gắn "Kho công ty" vì đó là nơi
// receive/issue/transfer NVL chính (services/warehouse.py) — không phân biệt được Kho phân xưởng
// ở tầng hiển thị vì audit không lưu location.
const AUDIT_MODULE_MAP = {
  finished_goods_unit: "Kho TP (WMS)", near_expiry_entry: "Kho TP (WMS)", shipment: "Kho TP (WMS)",
  ship_to_location: "Kho TP (WMS)",
  batch: "Nấu-Lọc-Chiết", ferment_record: "Nấu-Lọc-Chiết", bbt_tank: "Nấu-Lọc-Chiết", yeast_lot: "Nấu-Lọc-Chiết",
  brew_order: "Lệnh SX", brew_master_order: "Lệnh SX", filter_order: "Lệnh SX", filter_master_order: "Lệnh SX",
  order: "Lệnh SX", work_order: "Điều độ",
  recipe_version: "Công thức", packaging: "Bao bì", downtime: "OEE/Dừng máy", schedule: "Lập lịch",
  quality_result: "Chất lượng", brew_batch: "Chất lượng", ferment: "Chất lượng", filter: "Chất lượng",
  bottle: "Chất lượng", qc_parameter: "Chất lượng", qc_parameter_group: "Chất lượng",
  qc_parameter_group_item: "Chất lượng", material_qc_group: "Chất lượng", stage_qc_group: "Chất lượng",
  deviation: "QC Lab", capa: "QC Lab", sample: "QC Lab",
  cip_form_type: "CIP", cip_equipment: "CIP", cip_record: "CIP",
  lot: "Kho công ty", material_request: "Kho công ty", material_request_line: "Kho công ty",
  stock_movement: "Kho công ty", stock_count: "Kho công ty",
  auth: "Tài khoản", role_template: "Tài khoản",
  beer_type: "Danh mục", unit_type_catalog: "Danh mục", supplier: "Danh mục", material_group: "Danh mục",
  product: "Danh mục", product_brew_spec: "Danh mục", finished_product: "Danh mục", material: "Danh mục",
  recipe: "Danh mục", line: "Danh mục",
  incident: "Bảo trì",
};
function auditModuleLabel(entityType) { return AUDIT_MODULE_MAP[entityType] || "—"; }
const AUDIT_FIELD_LABELS = {
  product_name: "Sản phẩm", lot_code: "Mã lô", unit_type: "Loại đơn vị", quantity: "Số lượng",
  requested: "Số lượng yêu cầu", count: "Số lượng", status: "Trạng thái", location: "Vị trí",
  from_location: "Vị trí nguồn", to_location: "Vị trí đích", unit_code: "Mã đơn vị",
  unit_codes: "Mã đơn vị", reason: "Lý do", vi_decomposed: "Số đã phân rã", lon_created: "Số lon sinh ra",
  source_unit_ids: "Đơn vị nguồn", lon_unit_ids: "Đơn vị lon sinh ra", material_code: "Mã vật tư",
  material_id: "Vật tư", supplier_id: "Nhà cung cấp", supplier_code: "Mã nhà cung cấp",
  unit_price: "Đơn giá", kcs_lot_no: "Số lô KCS", batch_code: "Số mẻ", batch_number: "Số mẻ",
  order_number: "Số lệnh", brew_order_id: "Lệnh nấu", filter_order_id: "Lệnh lọc",
  ferment_id: "Lô lên men", filter_id: "Mẻ lọc", bottle_id: "Lô chiết", product_id: "Dịch bia",
  finished_product_id: "Sản phẩm", volume_hl: "Thể tích (hl)", v_beer_hl: "Thể tích bia (hl)",
  planned_volume_hl: "Thể tích kế hoạch (hl)", value: "Giá trị", result: "Kết quả",
  param_id: "Chỉ tiêu", parameter_id: "Chỉ tiêu", username: "Tài khoản", role: "Vai trò",
  name: "Tên", code: "Mã", active: "Đang dùng", divide_by_pack_size: "Chia theo pack",
  selectable: "Cho chọn", ship_to_code: "Mã nơi xuất đến", ship_to_name: "Nơi xuất đến",
  pack_size: "SL/1 đơn vị", uom: "ĐVT", category: "Nhóm", description: "Mô tả",
};
function auditPrettify(k) {
  return k ? String(k).replace(/_/g, " ").replace(/^./, c => c.toUpperCase()) : "";
}
function auditEntityLabel(t) { return AUDIT_ENTITY_LABELS[t] || auditPrettify(t); }
function auditActionLabel(a) {
  if (AUDIT_ACTION_LABELS[a]) return AUDIT_ACTION_LABELS[a];
  const idx = (a || "").indexOf(":");
  if (idx > -1) {
    const prefixLabel = AUDIT_ACTION_PREFIX_LABELS[a.slice(0, idx)];
    if (prefixLabel) return `${prefixLabel}: ${auditPrettify(a.slice(idx + 1))}`;
  }
  return auditPrettify(a);
}
function auditFieldLabel(k) { return AUDIT_FIELD_LABELS[k] || auditPrettify(k); }
function auditFmtVal(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") return esc(JSON.stringify(v));
  return esc(String(v));
}
const AUDIT_ROW_STORE = {};
function showAuditDetail(row) {
  const before = row.before || {}, after = row.after || {};
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  const diffRows = keys.map(k => {
    const bv = before[k], av = after[k];
    const changed = JSON.stringify(bv) !== JSON.stringify(av);
    return `<tr>
      <td>${esc(auditFieldLabel(k))} <span class="muted" style="font-size:11px">(${esc(k)})</span></td>
      <td class="muted">${auditFmtVal(bv)}</td>
      <td class="muted" style="text-align:center">${changed ? "→" : ""}</td>
      <td${changed ? ' style="font-weight:700"' : ' class="muted"'}>${auditFmtVal(av)}</td>
    </tr>`;
  }).join("") || `<tr><td colspan=4 class="muted">Không có dữ liệu trước/sau cho dòng này.</td></tr>`;
  const modLabel = auditModuleLabel(row.entity_type);
  modal(`
    <h2 style="margin-bottom:4px">${esc(auditEntityLabel(row.entity_type))} — ${esc(auditActionLabel(row.action))}</h2>
    <div class="muted" style="margin-bottom:12px;line-height:1.7">
      ${modLabel !== "—" ? `Module: <b>${esc(modLabel)}</b><br>` : ""}
      Mã đối tượng: <code class="k">${esc(row.entity_id)}</code><br>
      Người: ${esc(row.actor)} (${esc(row.actor_role || "—")}) · Lúc: ${fmt(row.ts)}
      ${row.reason ? `<br>Lý do: ${esc(row.reason)}` : ""}
      ${row.correlation_id ? `<br>Mã liên kết: <code class="k">${esc(row.correlation_id)}</code>` : ""}
    </div>
    <table><thead><tr><th>Trường</th><th>Trước</th><th></th><th>Sau</th></tr></thead>
      <tbody>${diffRows}</tbody></table>
    <div class="muted" style="margin-top:10px;font-size:11px">
      Mã kỹ thuật gốc: đối tượng <code>${esc(row.entity_type)}</code> · hành động <code>${esc(row.action)}</code>
    </div>`);
}
function wireAuditDetail(tableId) {
  const key = tableId || "_default";
  document.querySelectorAll(`[data-auditdetail="${key}"]`).forEach(btn => {
    btn.onclick = () => showAuditDetail(AUDIT_ROW_STORE[key][parseInt(btn.dataset.idx, 10)]);
  });
}
function tableAudit(rows, tableId) {
  const key = tableId || "_default";
  AUDIT_ROW_STORE[key] = rows;
  return `<table${tableId ? ` id="${tableId}"` : ""}><thead><tr><th>Module</th><th>#</th><th>Đối tượng</th><th>Hành động</th><th>Người</th><th>Vai trò</th><th>Lúc</th><th></th></tr></thead>
    <tbody>${rows.map((r, i) => `<tr>
      <td>${esc(auditModuleLabel(r.entity_type))}</td>
      <td class="muted">${r.seq}</td>
      <td>${esc(auditEntityLabel(r.entity_type))} <span class="muted" style="font-size:11px">(${esc(r.entity_type)})</span></td>
      <td>${esc(auditActionLabel(r.action))} <span class="muted" style="font-size:11px">(${esc(r.action)})</span></td>
      <td>${esc(r.actor)}</td><td class="muted">${esc(r.actor_role || "")}</td>
      <td class="muted">${fmt(r.ts)}</td>
      <td><button class="btn sm sec" data-auditdetail="${key}" data-idx="${i}">Xem</button></td>
    </tr>`).join("") || '<tr><td colspan=8 class="muted">Trống</td></tr>'}</tbody></table>`;
}

// ================= helpers cho module mới =================
const SUB = {};  // sub-section đang chọn theo view
// Bộ lọc kho đang chọn ở tab "Xem tồn kho" của mỗi module — Kho công ty/Kho phân xưởng là 2
// kho khác nhau (khác người quản lý) nhưng cả 2 bên đều cần xem được tồn của TẤT CẢ ("" =
// không lọc), Kho công ty, hay Kho phân xưởng — không chỉ đúng kho của riêng mình. Mặc định
// mỗi bên vẫn ưu tiên hiện đúng kho của mình trước.
const TON_LOC = { warehouse_kc: "Kho công ty", warehouse_px: "Kho phân xưởng" };
const TON_LOC_OPTS = [
  { value: "", label: "Tất cả" },
  { value: "Kho công ty", label: "Kho công ty" },
  { value: "Kho phân xưởng", label: "Kho phân xưởng" },
];
const tonLocSelectHtml = (id, selected) => `<select id="${esc(id)}">${TON_LOC_OPTS.map(o =>
  `<option value="${esc(o.value)}" ${o.value === selected ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select>`;
// Bộ lọc năm dùng chung cho các màn hình mã/số hiệu theo năm (Thông tin nấu/lên men/lọc/chiết,
// Lệnh lọc) — mã nấu/lô lên men/lệnh lọc/mã lọc/mã chiết chỉ duy nhất TRONG 1 năm (xem backend
// common.py::resolve_years), nên các màn liệt kê cần cho chọn xem theo năm nào, mặc định năm
// hiện tại khi chưa chọn gì. Lệnh nấu đã bỏ bộ lọc này khi phẳng hóa (mirror Lệnh
// SX ERP, danh sách không lọc theo năm).
const YEARS = {};  // { [key]: [năm] hoặc [năm1, năm2 liên tiếp] } theo từng màn hình
function yearFilterControl(key, years) {
  const now = new Date().getFullYear();
  const a = (years && years[0]) || now;
  const b = (years && years[1]) || "";
  const optsA = [];
  for (let y = now + 1; y >= now - 5; y--) optsA.push(y);
  const optsB = ["", a - 1, a + 1];
  return `<div class="row" style="align-items:flex-end;margin-bottom:10px">
    <div class="field"><label>Năm</label><select id="yf_${key}_a">
      ${optsA.map(y => `<option value="${y}" ${y === a ? "selected" : ""}>${y}</option>`).join("")}</select></div>
    <div class="field"><label>+ Năm liền kề (tuỳ chọn)</label><select id="yf_${key}_b">
      ${optsB.map(y => `<option value="${y}" ${String(y) === String(b) ? "selected" : ""}>${y === "" ? "(không chọn)" : y}</option>`).join("")}</select></div>
    <button class="btn sec" id="yf_${key}_go">Xem</button>
  </div>`;
}
function wireYearFilter(key, view) {
  const selA = $(`yf_${key}_a`), selB = $(`yf_${key}_b`), btn = $(`yf_${key}_go`);
  if (!selA) return;
  selA.onchange = () => {
    const a = parseInt(selA.value);
    selB.innerHTML = ["", a - 1, a + 1].map(y =>
      `<option value="${y}">${y === "" ? "(không chọn)" : y}</option>`).join("");
  };
  btn.onclick = () => {
    const a = parseInt(selA.value);
    const b = selB.value ? parseInt(selB.value) : null;
    YEARS[key] = b ? [a, b].sort((x, y) => x - y) : [a];
    render(view);
  };
}
function subnav(view, sections, current) {
  return `<div class="subnav">${sections.map(s =>
    `<button class="${s.key === current ? "active" : ""}" data-sub="${view}:${s.key}">${esc(s.label)}</button>`
  ).join("")}</div>`;
}
function wireSubnav(view) {
  document.querySelectorAll(`[data-sub^="${view}:"]`).forEach(b => b.onclick = () => {
    // Đổi trạng thái active ngay khi bấm (trước khi dữ liệu tải xong) để nút phản hồi tức thì,
    // tránh cảm giác "đứng hình" trong lúc chờ fetch — render(view) phía dưới sẽ vẽ lại đúng
    // nội dung khi xong, active class ở đây chỉ là phản hồi tạm thời.
    document.querySelectorAll(`[data-sub^="${view}:"]`).forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    SUB[view] = b.dataset.sub.split(":")[1]; render(view);
  });
}
// Vị trí kho dùng CHUNG 1 danh mục cho cả Kho công ty lẫn Kho phân xưởng — scope quyết định vị
// trí đó hiện ở màn chọn vị trí nào (xem backend/app/models/materials.py::MaterialLocation.scope).
const LOC_SCOPE_LABELS = { cong_ty: "Kho công ty", phan_xuong: "Kho phân xưởng", ca_hai: "Cả 2 kho" };
function locScopeLabel(scope) { return LOC_SCOPE_LABELS[scope] || scope; }
function locScopeOptsHtml(selected) {
  return Object.entries(LOC_SCOPE_LABELS).map(([v, l]) =>
    `<option value="${v}" ${v === selected ? "selected" : ""}>${l}</option>`).join("");
}
// Khi 1 lô bị tách do điều chuyển 1 phần số lượng (xem services/warehouse.py::_transfer_lot),
// mã lô đổi sang mã mới tự sinh — backend trả kèm `split_from_lot_code` (routers/materials.py::
// list_lots) để hiển thị "(tách từ mã X)" ngay tại chỗ, người dùng không phải vào Truy xuất mới
// biết lô này vốn là 1 phần của lô nào trước đó (ngày nhập gốc/NCC/số lô KCS vẫn giữ nguyên,
// chỉ đổi mã).
function lotCodeCellHtml(l) {
  if (!l) return "";
  const tag = l.split_from_lot_code ? ` <span class="muted" style="font-size:11px">(tách từ ${esc(l.split_from_lot_code)})</span>` : "";
  return `${esc(l.lot_code)}${tag}`;
}
function lotCodePlain(l) {
  if (!l) return "";
  return l.split_from_lot_code ? `${esc(l.lot_code)} (tách từ ${esc(l.split_from_lot_code)})` : esc(l.lot_code);
}
async function lotOptions(db, onlyAvailable) {
  const [lots, mats] = await Promise.all([GET("/lots"), GET("/materials")]);
  const matById = Object.fromEntries(mats.map(m => [m.material_id, m]));
  return lots.filter(l => l.quantity > 0 && (!onlyAvailable || l.status === "available"))
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))   // FIFO: nhập trước hiện trước
    .map(l => {
      const m = matById[l.material_id];
      return `<option value="${l.lot_id}" data-material="${esc(l.material_id || "")}">${lotCodePlain(l)}${m ? " — " + esc(m.name) : ""} (${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})${l.status === "on_hold" ? " — CHỜ DUYỆT QC" : ""}</option>`;
    }).join("");
}

// Đơn vị phụ (VD Lon->kg): vật tư khai báo alt_uom+alt_uom_ratio (1 uom chính = alt_uom_ratio
// đơn vị phụ) cho phép người dùng xuất/nhập theo 1 trong 2 đơn vị ở 1 số màn hình xuất/kiểm kê.
// Luôn quy đổi về uom chính (altUomToBaseQty) trước khi gọi API — kho vẫn chỉ lưu theo uom chính.
function altUomFieldHtml(mat, attrs, width) {
  const w = width || 70;
  const a = /=/.test(attrs) ? attrs : `id="${attrs}"`;   // cho phép truyền id đơn giản hoặc attrs đầy đủ (class/data-*)
  if (mat && mat.alt_uom && mat.alt_uom_ratio) {
    return `<select ${a} style="width:${w}px">
      <option value="${esc(mat.uom)}">${esc(mat.uom)}</option>
      <option value="${esc(mat.alt_uom)}">${esc(mat.alt_uom)}</option>
    </select>`;
  }
  if (mat) return `<input ${a} value="${esc(mat.uom)}" readonly style="width:${w}px;background:var(--bg2,#f2f2f2)"/>`;
  return `<input ${a} value="kg" style="width:${w}px"/>`;
}
function altUomToBaseQty(mat, qty, chosenUom) {
  if (mat && mat.alt_uom && mat.alt_uom_ratio && chosenUom === mat.alt_uom) return qty / mat.alt_uom_ratio;
  return qty;
}
// Giao của các đơn vị (uom chính + alt_uom nếu có) mà MỌI vật tư trong memberIds đều khai
// được — dùng để hiện ô "Đơn vị nhóm" khi tạo/sửa Nhóm vật tư thay thế (mirror backend
// services/master_data.py::group_unit_options — giữ 2 bên tính giống nhau).
function groupUnitOptions(materialsById, memberIds) {
  let common = null;
  for (const mid of memberIds) {
    const m = materialsById[mid];
    if (!m) continue;
    const opts = new Set([m.uom]); if (m.alt_uom) opts.add(m.alt_uom);
    common = common === null ? opts : new Set([...common].filter(u => opts.has(u)));
  }
  return common ? [...common].sort() : [];
}
function groupUnitSelectHtml(options, selected) {
  if (!options.length) return `<option value="">(không có đơn vị chung)</option>`;
  return options.map(u => `<option value="${esc(u)}" ${u === selected ? "selected" : ""}>${esc(u)}</option>`).join("");
}
// Gắn 1 ô ĐVT (select/input, xem altUomFieldHtml) cạnh 1 <select> chọn Lô — tự cập nhật khi
// đổi lô (mỗi <option data-material> từ lotOptions()) dựa vào bảng vật tư đã cache (matById).
function wireLotAltUom(lotSelectId, wrapId, matById) {
  const wrap = document.getElementById(wrapId);
  const sel = document.getElementById(lotSelectId);
  if (!wrap || !sel) return;
  const refresh = () => {
    const opt = sel.selectedOptions[0];
    const mat = opt ? (matById || WH_CACHE.matById || {})[opt.dataset.material] : null;
    wrap.innerHTML = altUomFieldHtml(mat, wrapId + "_sel");
  };
  sel.onchange = refresh;
  refresh();
}
function lotAltUomQty(lotSelectId, wrapId, qty, matById) {
  const sel = document.getElementById(lotSelectId);
  const opt = sel ? sel.selectedOptions[0] : null;
  const mat = opt ? (matById || WH_CACHE.matById || {})[opt.dataset.material] : null;
  const uomSel = document.getElementById(wrapId + "_sel");
  return altUomToBaseQty(mat, qty, uomSel ? uomSel.value : (mat ? mat.uom : null));
}

// ================= KHO NVL =================
// Modal xem TOÀN BỘ mã lô của 1 vật tư — tách khỏi bảng Xem tồn kho vì hiển thị thẳng
// trong ô "Mã lô" không chịu được khi vật tư có hàng trăm/nghìn lô (xem "+N lô khác").
function openMaterialLotsModal(matLabel, lots) {
  const sorted = lots.slice().sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  modal(`<h3>Toàn bộ lô — <code class="k">${esc(matLabel)}</code> <span class="muted">(${sorted.length} lô)</span></h3>
    <input class="searchbox" data-tbl="t_matlots" placeholder="Tìm mã lô/vị trí..." style="margin-bottom:8px"/>
    <div class="tablewrap"><table id="t_matlots"><thead><tr><th>Mã lô</th><th>Số lượng</th><th>ĐVT</th><th>Trạng thái</th><th>Vị trí</th><th>Ngày nhập</th></tr></thead>
      <tbody>${sorted.map(l => `<tr><td><code class="k">${lotCodeCellHtml(l)}</code></td><td>${l.quantity}</td><td>${esc(l.uom)}</td>
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
// Trước đây "Nhập/Xuất/Hoàn/Sang ngang" là 1 tab dồn 9 khối chức năng — tách thành nhiều tab
// riêng theo nghiệp vụ (nhap/obal/xtdn/sng/tudo/dc/tra) cho gọn, nhưng tất cả vẫn cần chung 1
// bộ dữ liệu (lots/materials/requests/...) nên giữ đúng nguyên logic fetch+tính toán cũ, chỉ
// tách ra thành hàm dùng chung để mỗi tab tự gọi khi cần, tránh phải viết lại/duy trì 2 nơi.
async function loadGiaoData() {
  const [lotsAvail, mats, allLots, allRequestsFull, freeIssues, pxRequests, factoryLocationsGiao, factoryTransfers, supplierReturns, suppliers, receipts, sangNgangRequests, qcReqIdsGiao, matLocsGiao, kcpxRequests] = await Promise.all([
    lotOptions(null, false), GET("/materials"), GET("/lots"), GET("/warehouse/requests"),
    GET("/warehouse/movements?movement_type=issue&mode=tu_do"),
    GET("/warehouse/transfer-px-requests"), GET("/factory-locations").catch(() => []),
    GET("/warehouse/movements?movement_type=issue&mode=dieu_chuyen_nha_may"),
    GET("/warehouse/movements?movement_type=issue&mode=tra_ncc"),
    GET("/suppliers"), GET("/warehouse/movements?movement_type=receipt"),
    GET("/warehouse/sang-ngang"), GET("/materials/qc-required"),
    GET("/warehouse/locations").catch(() => []),
    GET("/warehouse/transfer-kcpx-requests").catch(() => []),
  ]);
  const activeMatLocsGiao = matLocsGiao.filter(l => l.active && (l.scope === "cong_ty" || l.scope === "ca_hai"));
  const matLocOptsGiao = activeMatLocsGiao.map(l =>
    `<option value="${esc(l.loc_id)}">${esc(l.code)} — ${esc(l.name)}</option>`).join("") ||
    `<option value="">(chưa khai báo vị trí kho — vào Danh mục để thêm)</option>`;
  const matLocByIdGiao = Object.fromEntries(matLocsGiao.map(l => [l.loc_id, l]));
  WH_CACHE.matLocById = matLocByIdGiao;
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
  const supplierItemsGiao = suppliers.map(s => ({ value: s.supplier_id, label: `${s.code} — ${s.name}` }));
  const pending = allLots.filter(l => l.status === "on_hold");
  const canFulfillGiao = _hasPerm("warehouse.issue");
  const isAdminGiao = CURRENT_USER && CURRENT_USER.role === "admin";
  const canApproveTransferPx = _hasPerm("warehouse.receive");
  const canTransferToFactory = _hasPerm("warehouse.issue");
  const canApproveFactory = _hasPerm("warehouse.transfer_approve_factory");
  const factoryByIdGiao = Object.fromEntries(factoryLocationsGiao.map(f => [f.factory_id, f]));
  const activeFactoryOpts = factoryLocationsGiao.filter(f => f.active)
    .map(f => `<option value="${f.factory_id}">${esc(f.code)} — ${esc(f.name)}</option>`).join("") ||
    `<option value="">(chưa có nhà máy nào trong danh mục)</option>`;
  const qcReqSetGiao = new Set(qcReqIdsGiao);
  const sngPending = sangNgangRequests.filter(r => r.status === "pending").sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const sngDone = sangNgangRequests.filter(r => r.status !== "pending").sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const canCreateSangNgang = _hasPerm("warehouse.receive");
  // Mỗi lần vào lại 1 trong các tab này (kể cả sau 1 thao tác) là 1 lượt xem mới — reset về
  // trang đầu (10 dòng) cho gọn; dữ liệu mới nhất (nếu vừa thao tác) luôn nằm trong 10 dòng đầu.
  WH_CACHE.matById = matByIdGiao;
  WH_CACHE.matItems = matItemsGiao;
  WH_CACHE.tu_do = freeIssuesKc;
  WH_CACHE.dieu_chuyen_nha_may = factoryTransfers;
  WH_CACHE.factoryById = factoryByIdGiao;
  WH_CACHE.tra_ncc = supplierReturns;
  WH_CACHE.xuat_theo_de_nghi = doneRequests;
  WH_CACHE.lotById = lotByIdGiao;
  WH_CACHE.allLots = allLots;
  WH_CACHE.canFulfill = canFulfillGiao;
  WH_CACHE.receipts = receipts;
  WH_CACHE.sangNgangRequests = sangNgangRequests;
  WH_CACHE.supplierItems = supplierItemsGiao;
  Object.keys(WH_HIST_VISIBLE).forEach(k => { WH_HIST_VISIBLE[k] = WH_HIST_PAGE; });
  const pxPending = pxRequests.filter(r => r.status === "pending").sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  const pxDone = pxRequests.filter(r => r.status !== "pending").sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const kcpxPending = kcpxRequests.filter(r => r.status === "pending").sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const kcpxDone = kcpxRequests.filter(r => r.status !== "pending").sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const workshopLotOpts = allLots.filter(l => l.quantity > 0 && /phân xưởng/i.test(l.location || ""))
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
    .map(l => { const m = matByIdGiao[l.material_id];
      return `<option value="${l.lot_id}">${lotCodePlain(l)}${m ? ` — ${esc(m.code)} ${esc(m.name)}` : ""} (${l.quantity}${l.uom}, tại ${esc(l.location)})</option>`; }).join("") ||
    `<option value="">(không có lô nào ở kho phân xưởng)</option>`;
  const companyLotOptsGiao = allLots.filter(l => l.quantity > 0 && !/phân xưởng/i.test(l.location || "") && l.status !== "on_hold")
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
    .map(l => { const m = matByIdGiao[l.material_id];
      return `<option value="${l.lot_id}">${lotCodePlain(l)}${m ? ` — ${esc(m.code)} ${esc(m.name)}` : ""} (${l.quantity}${l.uom})</option>`; }).join("") ||
    `<option value="">(không có lô nào ở kho công ty)</option>`;
  const canEditReceipt = _hasPerm("warehouse.receive");
  const receiptRows = receipts.slice().sort((a, b) => new Date(b.ts) - new Date(a.ts)).map(m => {
    const mat = m.material_id ? matByIdGiao[m.material_id] : null;
    const lot = m.lot_id ? lotByIdGiao[m.lot_id] : null;
    const sup = lot && lot.supplier_id ? supplierByIdGiao[lot.supplier_id] : null;
    return `<tr>
      <td class="muted">${fmt(m.ts)}</td>
      <td><code class="k">${esc(m.lot_code || "")}</code></td>
      <td class="muted">${esc(lot ? lot.kcs_lot_no || "" : "")}</td>
      <td class="muted">${esc(lot ? lot.supplier_lot || "" : "")}</td>
      <td>${mat ? `<code class="k">${esc(mat.code)}</code> ${esc(mat.name)}` : esc(m.material_id || "—")}</td>
      <td>${m.quantity} ${esc(m.uom)}</td>
      <td class="muted">${esc(sup ? sup.name : "")}</td>
      <td class="muted">${esc(m.reason || "")}</td>
      <td class="muted">${esc(m.actor || "")}</td>
      <td style="white-space:nowrap">${canEditReceipt ? `<button class="btn sm sec" data-editrc="${esc(m.movement_id)}">Sửa</button>
        <button class="btn sm sec" data-delrc="${esc(m.movement_id)}" style="color:var(--red)">Xóa</button>` : ""}</td></tr>`;
  }).join("") || `<tr><td colspan="10" class="muted">Chưa có phiếu nhập kho nào.</td></tr>`;
  return { lotsAvail, mats, allLots, allRequestsFull, freeIssues, pxRequests, factoryLocationsGiao, factoryTransfers,
    supplierReturns, suppliers, receipts, sangNgangRequests, qcReqIdsGiao, matLocsGiao, activeMatLocsGiao,
    matLocOptsGiao, matLocByIdGiao, allRequests, doneRequests, freeIssuesKc, matItemsGiao, matByIdGiao, lotByIdGiao,
    supplierByIdGiao, supplierItemsGiao, pending, canFulfillGiao, isAdminGiao, canApproveTransferPx,
    canTransferToFactory, canApproveFactory, factoryByIdGiao, activeFactoryOpts, qcReqSetGiao, sngPending, sngDone,
    canCreateSangNgang, pxPending, pxDone, workshopLotOpts, companyLotOptsGiao, canEditReceipt, receiptRows,
    kcpxRequests, kcpxPending, kcpxDone };
}
VIEWS.warehouse_kc = async function () {
  const sec = SUB.warehouse_kc || "ton";
  const sections = [
    { key: "ton", label: "Xem tồn kho" }, { key: "the", label: "Thẻ kho" },
    { key: "han", label: "Hạn sử dụng" }, { key: "bc", label: "BC nhập-xuất-tồn" },
    { key: "nhap", label: "Nhập kho" }, { key: "obal", label: "🏁 Nhập tồn đầu" },
    { key: "xtdn", label: "Xuất theo đề nghị" }, { key: "sng", label: "Xuất sang ngang" },
    { key: "tudo", label: "Xuất tự do" }, { key: "dc", label: "Điều chuyển" },
    { key: "tra", label: "Hoàn / Trả NCC" },
    { key: "kc", label: "Danh sách lô (FIFO)" },
    { key: "vitri", label: "📍 Vị trí kho" },
    { key: "kk", label: "Kiểm kê định kỳ" }, { key: "min", label: "📉 Tồn tối thiểu" },
  ];
  let body = "";
  let lotsByMaterial = {};
  const LOT_CELL_MAX = 3;
  const lotChip = (l) => `<code class="k">${lotCodeCellHtml(l)}</code> (${l.quantity}${l.uom}${l.status === "on_hold" ? ", CHỜ QC" : ""})`;
  if (sec === "ton") {
    const tonLoc = TON_LOC.warehouse_kc;
    const [stock, allLots, matLocsTon] = await Promise.all([
      GET("/warehouse/stock" + (tonLoc ? "?location=" + encodeURIComponent(tonLoc) : "")), GET("/lots"),
      GET("/warehouse/locations").catch(() => [])]);
    const locByIdTon = Object.fromEntries(matLocsTon.map(l => [l.loc_id, l]));
    const lotMatchesLoc = (l) => tonLoc === "" ? true : tonLoc === "Kho phân xưởng"
      ? /phân xưởng/i.test(l.location || "") : !/phân xưởng/i.test(l.location || "");
    allLots.filter(l => l.quantity > 0 && lotMatchesLoc(l)).forEach(l => {
      (lotsByMaterial[l.material_id] = lotsByMaterial[l.material_id] || []).push(l);
    });
    const lowCount = stock.filter(s => s.low_stock).length;
    const matByIdTon = Object.fromEntries((CACHE.materials || []).map(m => [m.material_id, m]));
    body = `<div class="panel"><h2>Tồn kho hiện tại — ${esc(tonLoc || "Tất cả")}</h2>
      <div class="row" style="margin-bottom:8px"><div class="field"><label>Kho</label>${tonLocSelectHtml("ton_loc", tonLoc)}</div></div>
      ${lowCount ? `<div class="muted" style="color:var(--red);margin-bottom:8px">⚠ ${lowCount} vật tư đang dưới tồn tối thiểu.</div>` : ""}
      <input class="searchbox" data-tbl="t_ton" placeholder="Tìm mã/tên vật tư..." style="margin-bottom:8px"/>
      <div id="ton_total" class="muted" style="margin-bottom:6px"></div>
      <div class="tablewrap"><table id="t_ton"><thead><tr><th>Mã VT</th><th>Tên</th><th>Nhóm</th><th>Mã lô</th><th>Vị trí kho</th><th>Tổng tồn thực tế</th><th>Đang chờ QC</th><th>Tồn khả dụng</th><th>ĐVT</th><th>Quy đổi</th><th>Tồn tối thiểu</th></tr></thead>
      <tbody>${stock.map(s => { const matLots = (lotsByMaterial[s.material_id] || [])
          .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
        const shown = matLots.slice(0, LOT_CELL_MAX);
        const rest = matLots.length - shown.length;
        const lotCell = shown.map(lotChip).join(", ") +
          (rest > 0 ? ` <button type="button" class="btn sm sec" data-viewlots="${esc(s.material_id)}" data-matlabel="${esc(s.material_code)} — ${esc(s.material_name)}">+${rest} lô khác</button>` : "");
        const locCodes = [...new Set(matLots.map(l => l.location_id && locByIdTon[l.location_id] ? locByIdTon[l.location_id].code : null).filter(Boolean))];
        const locCell = locCodes.length ? locCodes.slice(0, 2).map(c => `<code class="k">${esc(c)}</code>`).join(", ") +
          (locCodes.length > 2 ? ` +${locCodes.length - 2}` : "") : "—";
        const matTon = matByIdTon[s.material_id];
        const altDisp = matTon && matTon.alt_uom && matTon.alt_uom_ratio
          ? `${(s.on_hand * matTon.alt_uom_ratio).toFixed(2)} ${esc(matTon.alt_uom)}` : "—";
        return `<tr data-qty="${s.on_hand}" data-uom="${esc(s.uom)}"${s.low_stock ? ' style="background:color-mix(in srgb, var(--red) 10%, transparent)"' : ""}><td><code class="k">${esc(s.material_code)}</code></td><td>${esc(s.material_name)}</td>
        <td class="muted">${esc(s.category || "")}</td>
        <td class="muted">${lotCell || "—"}</td>
        <td class="muted">${locCell}</td>
        <td>${s.actual_total}</td>
        <td class="muted">${s.pending_qc > 0 ? s.pending_qc : "—"}</td>
        <td>${s.on_hand}${s.low_stock ? ' <span style="color:var(--red)" title="Dưới tồn tối thiểu">⚠</span>' : ""}</td><td>${s.uom}</td>
        <td class="muted">${altDisp}</td>
        <td class="muted">${s.stock_min ?? "—"}</td></tr>`; }).join("") ||
        '<tr><td colspan=11 class="muted">Không có tồn kho.</td></tr>'}</tbody></table></div></div>`;
  } else if (sec === "the") {
    const mats = await GET("/materials");
    const wcItems = mats.map(m => ({ value: m.material_id, label: `${m.code} — ${m.name}`, uom: m.uom }));
    WH_CACHE.matItemsThe = wcItems;
    body = `<div class="panel"><h2>Thẻ kho</h2>
      <div class="row"><div class="field" style="position:relative"><label>Vật tư</label>
          <input type="text" id="wc_mat_txt" autocomplete="off" placeholder="Tìm mã/tên nguyên liệu..." value="${esc(wcItems[0]?.label || "")}"/>
          <input type="hidden" id="wc_mat" value="${esc(wcItems[0]?.value || "")}"/></div>
        <button class="btn" id="wc_load" style="align-self:flex-end">Xem thẻ</button></div>
      <div id="wc_table"><div class="muted">Chọn vật tư.</div></div></div>`;
  } else if (sec === "han") {
    const exp = await GET("/warehouse/expiry");
    body = `<div class="panel"><h2>Hạn sử dụng</h2>
      <input class="searchbox" data-tbl="t_expiry" placeholder="Tìm theo mã/tên vật tư, mã lô..."/>
      <table id="t_expiry"><thead><tr><th>Vật tư</th><th>Lô</th><th>SL</th><th>Hạn</th><th>Còn (ngày)</th><th>Trạng thái</th><th>Vị trí</th></tr></thead>
      <tbody>${exp.map(e => `<tr><td>${e.material_code ? `<code class="k">${esc(e.material_code)}</code> ${esc(e.material_name || "")}` : "—"}</td>
        <td><code class="k">${esc(e.lot_code)}</code></td><td>${e.quantity} ${e.uom}</td>
        <td class="muted">${fmt(e.expiry)}</td><td>${e.days_left}</td><td>${badge(e.status)}</td><td class="muted">${esc(e.location || "")}</td></tr>`).join("") || '<tr><td colspan=7 class="muted">Không có lô có hạn dùng.</td></tr>'}</tbody></table></div>`;
  } else if (sec === "bc") {
    // Mặc định khung 60 ngày gần nhất, cho chọn lại từ-đến ngày — persist lựa chọn trong SUB
    // giống các báo cáo khác (mirror sec === "netship" ở VIEWS.reports).
    const bcToday = new Date();
    const bcFrom60 = new Date(bcToday); bcFrom60.setDate(bcFrom60.getDate() - 60);
    const bcDateFrom = SUB.bc_date_from || toISODateLocal(bcFrom60);
    const bcDateTo = SUB.bc_date_to || toISODateLocal(bcToday);
    SUB.bc_date_from = bcDateFrom; SUB.bc_date_to = bcDateTo;
    const bcStart = new Date(bcDateFrom + "T00:00:00");
    const bcEnd = new Date(bcDateTo + "T00:00:00"); bcEnd.setDate(bcEnd.getDate() + 1);
    const bcQ = `date_from=${encodeURIComponent(toDTLocal(bcStart))}&date_to=${encodeURIComponent(toDTLocal(bcEnd))}&location=${encodeURIComponent("Kho công ty")}`;
    const rep = await GET(`/warehouse/report?${bcQ}`);
    body = `<div class="panel"><h2>Báo cáo nhập-xuất-tồn — Kho công ty <span class="muted">(${esc(bcDateFrom)} → ${esc(bcDateTo)})</span></h2>
      <div class="row">
        <div class="field"><label>Từ ngày</label><input id="bc_from" type="date" value="${bcDateFrom}"/></div>
        <div class="field"><label>Đến ngày</label><input id="bc_to" type="date" value="${bcDateTo}"/></div>
        <button class="btn" id="bc_apply" style="align-self:flex-end">Xem báo cáo</button>
      </div>
      <input class="searchbox" data-tbl="t_bcrep" placeholder="Tìm theo mã/tên vật tư..."/>
      <div class="tablewrap"><table id="t_bcrep"><thead><tr><th>Mã VT</th><th>Tên</th><th>Nhập</th><th>Xuất</th><th>Tồn cuối</th><th>ĐVT</th></tr></thead>
      <tbody>${rep.map(r => `<tr><td><code class="k">${esc(r.material_code)}</code></td><td>${esc(r.material_name)}</td>
        <td style="color:var(--green)">${r.received}</td><td style="color:var(--orange)">${r.issued}</td>
        <td>${r.on_hand}</td><td>${r.uom}</td></tr>`).join("") || '<tr><td colspan=6 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div></div>`;
  } else if (sec === "nhap") {
    const { matItemsGiao, matLocOptsGiao, isAdminGiao, receiptRows } = await loadGiaoData();
    body = `<div class="panel"><h2>Nhập kho ${isAdminGiao ? `<button class="btn sm sec" id="rc_delhist" style="color:var(--red);font-size:12px;font-weight:normal">🗑️ Xóa lịch sử</button>` : ""}</h2>
        <div class="row"><div class="field"><label>Ngày nhập</label><input id="rc_dt" type="datetime-local" value="${toDTLocal(new Date())}" max="${toDTLocal(new Date())}" min="${toDTLocal(new Date(Date.now() - 15 * 86400000))}"/></div>
          <div class="field" style="position:relative"><label>Nguyên liệu</label>
            <input type="text" id="rc_mat_txt" autocomplete="off" placeholder="Tìm mã/tên nguyên liệu..." value="${esc(matItemsGiao[0]?.label || "")}"/>
            <input type="hidden" id="rc_mat" value="${esc(matItemsGiao[0]?.value || "")}"/></div>
          <div class="field" style="position:relative"><label>Nhà CC</label>
            <input type="text" id="rc_supplier_txt" autocomplete="off" placeholder="Tìm nhà cung cấp..."/>
            <input type="hidden" id="rc_supplier"/></div></div>
        <div class="row"><div class="field"><label>Số lượng</label><input id="rc_qty" type="number" value="500"/></div>
          <div class="field"><label>ĐVT</label><input id="rc_uom" value="${esc(matItemsGiao[0]?.uom || "")}" size="4" readonly title="Lấy tự động từ danh mục nguyên liệu — không sửa được"/></div>
          <div class="field"><label>Đơn giá</label><input id="rc_price" type="number" placeholder="(tuỳ chọn)"/></div>
          <div class="field"><label>Hạn dùng</label><input id="rc_exp" type="date"/></div></div>
        <div class="row"><div class="field"><label>Vị trí cất *</label><select id="rc_loc">${matLocOptsGiao}</select></div>
          <div class="field"><label>Số LOT nhà cung cấp</label><input id="rc_supplier_lot" placeholder="Ghi trên bao bì NCC"/></div>
          <div class="field" style="flex:1"><label>Diễn giải</label><input id="rc_note" placeholder="(tuỳ chọn)"/></div>
          <button class="btn" id="rc_do" style="align-self:flex-end">Nhập</button></div>
        <div class="muted" style="margin-top:4px">Mã lô do hệ thống tự sinh (tăng dần theo năm) — Số lô KCS do bộ phận KCS tự điền khi khai báo chỉ tiêu chất lượng. Nguyên liệu chính/phụ bắt buộc phải có Số lô KCS hoặc Số LOT nhà cung cấp mới được KCS duyệt.</div>
        <input class="searchbox" data-tbl="rc_hist" placeholder="Tìm mã lô/nguyên liệu/nhà cung cấp..." style="margin-top:12px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="rc_hist">
          <thead><tr><th>Ngày nhập</th><th>Mã lô</th><th>Số lô KCS</th><th>Số LOT NCC</th><th>Nguyên liệu</th><th>Số lượng</th><th>Nhà cung cấp</th><th>Diễn giải</th><th>Người nhập</th><th></th></tr></thead>
          <tbody>${receiptRows}</tbody>
        </table></div>
      </div>`;
  } else if (sec === "obal") {
    const { matItemsGiao, isAdminGiao } = await loadGiaoData();
    body = `<div class="panel"><h2>🏁 Nhập tồn đầu (kho công ty)</h2>
        <div class="muted" style="margin-bottom:6px">Nạp số dư tồn kho ban đầu khi triển khai hệ thống (không qua nhận hàng nhà cung cấp).</div>
        ${isAdminGiao
          ? `<div class="row"><div class="field"><label>Mã lô</label><input id="ob_code" placeholder="MALT-..."/></div>
          <div class="field" style="position:relative"><label>Vật tư</label>
            <input type="text" id="ob_mat_txt" autocomplete="off" placeholder="Tìm mã/tên nguyên liệu..." value="${esc(matItemsGiao[0]?.label || "")}"/>
            <input type="hidden" id="ob_mat" value="${esc(matItemsGiao[0]?.value || "")}"/></div></div>
        <div class="row"><div class="field"><label>SL</label><input id="ob_qty" type="number" value="500"/></div>
          <div class="field"><label>ĐVT</label><input id="ob_uom" value="${esc(matItemsGiao[0]?.uom || "")}" size="4" readonly title="Lấy tự động từ danh mục nguyên liệu — không sửa được"/></div>
          <div class="field"><label>Hạn dùng</label><input id="ob_exp" type="date"/></div>
          <div class="field"><label>Số lô KCS</label><input id="ob_kcs" placeholder="(tuỳ chọn)"/></div>
          <div class="field"><label>Số LOT NCC</label><input id="ob_supplier_lot" placeholder="(tuỳ chọn)"/></div>
          <button class="btn" id="ob_do">Nhập tồn đầu</button></div>
        <div class="row" style="margin-top:10px;border-top:1px solid var(--border);padding-top:10px">
          <div class="field" style="flex:1"><label>Hoặc import Excel (cột: Ngày nhập, Mã vật tư, Lô, Số lượng, tuỳ chọn thêm Số lô KCS)</label>
            <input type="file" id="ob_file" accept=".xlsx"/></div>
          <button class="btn sec" id="ob_import" style="align-self:flex-end">📥 Import Excel</button></div>`
          : '<div class="muted">Chỉ tài khoản Admin mới được thực hiện nhập tồn đầu.</div>'}
      </div>`;
  } else if (sec === "xtdn") {
    const { allRequests, matByIdGiao, lotByIdGiao, canFulfillGiao, allLots } = await loadGiaoData();
    body = `<div class="panel"><h2>Xuất theo số phiếu đề nghị <span class="muted">(${allRequests.length} phiếu đang chờ)</span></h2>
        <div class="muted" style="margin-bottom:6px">Mỗi phiếu hiện đầy đủ danh mục vật tư đã đề nghị — bấm "Duyệt cả phiếu" để xuất
          toàn bộ 1 lần (SL đề nghị đã được chặn không vượt tồn kho công ty từ lúc tạo phiếu), hoặc xử lý riêng từng dòng.</div>
        <input class="searchbox" id="xtdn_search" placeholder="Tìm theo số phiếu, người tạo, ghi chú, vật tư..." style="margin-bottom:8px;width:100%"/>
        <div id="xtdn_block">
          ${allRequests.length
            ? allRequests.map(r => requestBlockHtml(r, matByIdGiao, lotByIdGiao, canFulfillGiao, true, allLots)).join("")
            : '<div class="muted">Không có phiếu đề nghị nào đang chờ.</div>'}
        </div>
        ${movementHistoryBlockHtml("xuat_theo_de_nghi")}
      </div>`;
  } else if (sec === "sng") {
    const { matItemsGiao, matByIdGiao, lotByIdGiao, matLocOptsGiao, sngPending, sngDone, canCreateSangNgang, qcReqSetGiao } = await loadGiaoData();
    body = `<div class="panel"><h2>Xuất sang ngang <span class="muted">(${sngPending.length} đang chờ phân xưởng duyệt)</span></h2>
        <div class="muted" style="margin-bottom:6px">Vật tư về thẳng kho phân xưởng nhưng khai báo Ở ĐÂY — hệ thống vẫn ghi tăng tồn
          Kho công ty (như Nhập kho thường) rồi tạo đề nghị xuất ngay sang Kho phân xưởng. Thủ kho phân xưởng duyệt (tab Kho phân xưởng
          → Xuất sang ngang) thì lô mới thật sự chuyển. Nếu vật tư có chỉ tiêu chất lượng bắt buộc, phải qua KCS duyệt trước khi phân
          xưởng duyệt được.</div>
        ${canCreateSangNgang
          ? `<div class="row"><div class="field" style="position:relative"><label>Nguyên liệu</label>
            <input type="text" id="sng_mat_txt" autocomplete="off" placeholder="Tìm mã/tên nguyên liệu..." value="${esc(matItemsGiao[0]?.label || "")}"/>
            <input type="hidden" id="sng_mat" value="${esc(matItemsGiao[0]?.value || "")}"/></div>
          <div class="field" style="position:relative"><label>Nhà CC</label>
            <input type="text" id="sng_supplier_txt" autocomplete="off" placeholder="Tìm nhà cung cấp..."/>
            <input type="hidden" id="sng_supplier"/></div></div>
        <div class="row"><div class="field"><label>Số lượng</label><input id="sng_qty" type="number" value="500"/></div>
          <div class="field"><label>ĐVT</label><span id="sng_uom_wrap">${altUomFieldHtml(matByIdGiao[matItemsGiao[0]?.value], "sng_uom", 60)}</span></div>
          <div class="field"><label>Đơn giá</label><input id="sng_price" type="number" placeholder="(tuỳ chọn)"/></div>
          <div class="field"><label>Hạn dùng</label><input id="sng_exp" type="date"/></div></div>
        <div class="row"><div class="field"><label>Vị trí cất (tuỳ chọn)</label><select id="sng_loc"><option value="">(không cần chọn — chuyển thẳng phân xưởng)</option>${matLocOptsGiao}</select></div>
          <div class="field"><label>Số LOT NCC</label><input id="sng_supplier_lot" placeholder="(tuỳ chọn)"/></div>
          <div class="field" style="flex:1"><label>Diễn giải</label><input id="sng_note" placeholder="(tuỳ chọn)"/></div>
          <button class="btn" id="sng_do" style="align-self:flex-end">Xuất sang ngang</button></div>`
          : '<div class="muted">Bạn không có quyền tạo Xuất sang ngang.</div>'}
        <h4 style="margin-top:14px">Đang chờ phân xưởng duyệt <span class="muted">(${sngPending.length})</span></h4>
        <div class="tablewrap"><table id="t_sng_pending">
          <thead><tr><th>Ngày tạo</th><th>Số đề nghị</th><th>Mã VT</th><th>Tên vật tư</th><th>Lô</th><th>SL</th><th>Trạng thái QC</th><th></th></tr></thead>
          <tbody>${sngPending.map(r => sangNgangKcRowHtml(r, matByIdGiao, lotByIdGiao, qcReqSetGiao)).join("") ||
            `<tr><td colspan=8 class="muted">Không có đề nghị nào đang chờ.</td></tr>`}</tbody>
        </table></div>
        <h4 style="margin-top:14px">Lịch sử đã xử lý <span class="muted">(${sngDone.length})</span></h4>
        <div class="tablewrap"><table id="t_sng_done">
          <thead><tr><th>Ngày tạo</th><th>Số đề nghị</th><th>Mã VT</th><th>Tên vật tư</th><th>Lô</th><th>SL</th><th>Trạng thái</th><th>Người xử lý</th><th></th></tr></thead>
          <tbody>${sngDone.map(r => sangNgangHistoryRowHtml(r, matByIdGiao, lotByIdGiao)).join("") ||
            `<tr><td colspan=9 class="muted">Chưa có đề nghị nào đã xử lý.</td></tr>`}</tbody>
        </table></div>
      </div>`;
  } else if (sec === "tudo") {
    const { lotsAvail, isAdminGiao } = await loadGiaoData();
    body = `<div class="panel"><h2>Xuất tự do</h2>
        <div class="muted" style="margin-bottom:6px">Xuất không theo phiếu đề nghị (vd. dùng nội bộ, thử nghiệm). Lô đang
          "CHỜ DUYỆT QC" sẽ bị chặn xuất. Có thể "Hoàn lại" nếu xuất nhầm — vật tư trở về đúng lô, tránh thất thoát.</div>
        ${isAdminGiao
          ? `<div class="row"><div class="field"><label>Lô</label>
          <input id="xt_lot_q" placeholder="Tìm nhanh (gõ mã/tên vật tư)..." style="margin-bottom:2px"/>
          <select id="xt_lot">${lotsAvail}</select></div>
          <div class="field"><label>SL</label><input id="xt_qty" type="number" value="50"/></div>
          <div class="field"><label>ĐVT</label><span id="xt_uom"></span></div>
          <div class="field" style="flex:1"><label>Lý do (tuỳ chọn)</label><input id="xt_reason" placeholder="(tuỳ chọn)"/></div>
          <button class="btn sec" id="xt_do" style="align-self:flex-end">Xuất tự do</button></div>`
          : '<div class="muted">Chỉ tài khoản Admin mới được thực hiện xuất tự do.</div>'}
        ${movementHistoryBlockHtml("tu_do")}
      </div>`;
  } else if (sec === "dc") {
    const { pxPending, pxDone, matByIdGiao, lotByIdGiao, canApproveTransferPx, isAdminGiao, companyLotOptsGiao, activeFactoryOpts, canTransferToFactory, kcpxPending, kcpxDone, qcReqSetGiao } = await loadGiaoData();
    body = `<div class="split">
      <div class="panel"><h2>Đề nghị điều chuyển Phân xưởng → Công ty <span class="muted">(${pxPending.length} đang chờ duyệt)</span></h2>
        <div class="muted" style="margin-bottom:6px">Thủ kho phân xưởng gửi đề nghị (tab Kho phân xưởng → Điều chuyển) — chưa
          động tồn kho, chỉ khi duyệt ở đây lệnh mới thật sự chuyển. Sau khi duyệt, chỉ ADMIN mới "Hoàn tác" được.</div>
        <div class="tablewrap"><table id="t_pxpending">
          <thead><tr><th>Ngày tạo</th><th>Số đề nghị</th><th>Vật tư</th><th>Lô</th><th>SL</th><th>Lý do</th><th>Người tạo</th>${canApproveTransferPx ? "<th></th>" : ""}</tr></thead>
          <tbody>${pxPending.map(r => transferPxRequestRowHtml(r, matByIdGiao, lotByIdGiao, canApproveTransferPx, isAdminGiao)).join("") ||
            `<tr><td colspan="${canApproveTransferPx ? 8 : 7}" class="muted">Không có đề nghị nào đang chờ.</td></tr>`}</tbody>
        </table></div>
        <h4 style="margin-top:14px">Lịch sử đề nghị đã xử lý <span class="muted">(${pxDone.length})</span></h4>
        <div class="tablewrap"><table id="t_pxdone">
          <thead><tr><th>Ngày tạo</th><th>Số đề nghị</th><th>Vật tư</th><th>Lô</th><th>SL</th><th>Lý do</th><th>Trạng thái</th><th>Người xử lý</th>${isAdminGiao ? "<th></th>" : ""}</tr></thead>
          <tbody>${pxDone.map(r => transferPxRequestHistoryRowHtml(r, matByIdGiao, lotByIdGiao, isAdminGiao)).join("") ||
            `<tr><td colspan="${isAdminGiao ? 8 : 7}" class="muted">Chưa có đề nghị nào đã xử lý.</td></tr>`}</tbody>
        </table></div>
      </div>

      <div class="panel"><h2>Điều chuyển Công ty → Nhà máy khác</h2>
        <div class="muted" style="margin-bottom:6px">Chỉ điều chuyển được lô đang ở <b>Kho công ty</b> — xuất NGAY (giảm tồn), tự do
          hoàn tác cho tới khi Trưởng phòng Kế hoạch duyệt; sau khi duyệt chỉ ADMIN mới "Hoàn tác" được.</div>
        ${canTransferToFactory
          ? `<div class="row"><div class="field"><label>Lô (đang ở kho công ty)</label>
          <input id="dcnm_lot_q" placeholder="Tìm nhanh (gõ mã/tên vật tư)..." style="margin-bottom:2px"/>
          <select id="dcnm_lot">${companyLotOptsGiao}</select></div>
          <div class="field"><label>SL</label><input id="dcnm_qty" type="number" value="50"/></div>
          <div class="field"><label>Nhà máy đến</label><select id="dcnm_factory">${activeFactoryOpts}</select></div>
          <div class="field" style="flex:1"><label>Lý do (tuỳ chọn)</label><input id="dcnm_reason" placeholder="(tuỳ chọn)"/></div>
          <button class="btn sec" id="dcnm_do" style="align-self:flex-end">Điều chuyển</button></div>`
          : '<div class="muted">Bạn không có quyền điều chuyển sang nhà máy khác.</div>'}
        ${movementHistoryBlockHtml("dieu_chuyen_nha_may")}
      </div>

      <div class="panel"><h2>Điều chuyển Công ty → Phân xưởng <span class="muted">(${kcpxPending.length} đang chờ Phân xưởng duyệt)</span></h2>
        <div class="muted" style="margin-bottom:6px">Điều chuyển 1 lô ĐANG CÓ SẴN ở Kho công ty sang Kho phân xưởng — chưa động tồn kho, chỉ
          khi Phân xưởng duyệt (tab Kho phân xưởng → Điều chuyển) mới thật sự chuyển. Nếu vật tư có chỉ tiêu chất lượng bắt buộc, lô sẽ
          quay lại "Đang chờ KCS duyệt" (dù trước đó đã qua QC) — Phân xưởng KHÔNG duyệt được cho tới khi KCS duyệt lại.</div>
        ${canTransferToFactory
          ? `<div class="row"><div class="field"><label>Lô (đang ở kho công ty)</label>
          <input id="dckp_lot_q" placeholder="Tìm nhanh (gõ mã/tên vật tư)..." style="margin-bottom:2px"/>
          <select id="dckp_lot">${companyLotOptsGiao}</select></div>
          <div class="field"><label>SL</label><input id="dckp_qty" type="number" value="50"/></div>
          <div class="field" style="flex:1"><label>Lý do (tuỳ chọn)</label><input id="dckp_reason" placeholder="(tuỳ chọn)"/></div>
          <button class="btn sec" id="dckp_do" style="align-self:flex-end">Gửi đề nghị</button></div>`
          : '<div class="muted">Bạn không có quyền tạo đề nghị điều chuyển.</div>'}
        <h4 style="margin-top:14px">Đang chờ Phân xưởng duyệt <span class="muted">(${kcpxPending.length})</span></h4>
        <div class="tablewrap"><table id="t_kcpx_pending">
          <thead><tr><th>Ngày tạo</th><th>Số đề nghị</th><th>Mã VT</th><th>Tên vật tư</th><th>Lô</th><th>SL</th><th>Trạng thái QC</th></tr></thead>
          <tbody>${kcpxPending.map(r => transferKcPxKcRowHtml(r, matByIdGiao, lotByIdGiao, qcReqSetGiao)).join("") ||
            `<tr><td colspan=7 class="muted">Không có đề nghị nào đang chờ.</td></tr>`}</tbody>
        </table></div>
        <h4 style="margin-top:14px">Lịch sử đã xử lý <span class="muted">(${kcpxDone.length})</span></h4>
        <div class="tablewrap"><table id="t_kcpx_done">
          <thead><tr><th>Ngày tạo</th><th>Số đề nghị</th><th>Mã VT</th><th>Tên vật tư</th><th>Lô</th><th>SL</th><th>Trạng thái</th><th>Người xử lý</th></tr></thead>
          <tbody>${kcpxDone.map(r => transferKcPxHistoryRowHtml(r, matByIdGiao, lotByIdGiao)).join("") ||
            `<tr><td colspan=8 class="muted">Chưa có đề nghị nào đã xử lý.</td></tr>`}</tbody>
        </table></div>
      </div></div>`;
  } else if (sec === "tra") {
    const { lotsAvail } = await loadGiaoData();
    body = `<div class="panel"><h2>Xuất trả nhà cung cấp</h2>
        <div class="muted" style="margin-bottom:6px">Chọn đúng lô vật tư hỏng/không đạt chỉ tiêu để trả lại nhà cung cấp — bắt buộc nêu lý do.</div>
        <div class="row"><div class="field"><label>Lô</label><select id="ncc_lot">${lotsAvail}</select></div>
          <div class="field"><label>SL</label><input id="ncc_qty" type="number" value="50"/></div>
          <div class="field" style="flex:1"><label>Lý do (bắt buộc)</label><input id="ncc_reason" placeholder="vd. hàng hỏng, không đạt chỉ tiêu"/></div>
          <button class="btn sec" id="ncc_do" style="align-self:flex-end">Xuất trả NCC</button></div>
        ${movementHistoryBlockHtml("tra_ncc")}
      </div>`;
  } else if (sec === "kc") {
    const [allLots, mats, qcReqIds, matLocsKc] = await Promise.all([GET("/lots"), GET("/materials"),
      GET("/materials/qc-required"), GET("/warehouse/locations").catch(() => [])]);
    const matById = Object.fromEntries(mats.map(m => [m.material_id, m]));
    const qcReqSet = new Set(qcReqIds);
    const matLocByIdKc = Object.fromEntries(matLocsKc.map(l => [l.loc_id, l]));
    WH_CACHE.matLocById = matLocByIdKc;
    WH_CACHE.matLocsActive = matLocsKc.filter(l => l.active && (l.scope === "cong_ty" || l.scope === "ca_hai"));
    const rowsAllKc = allLots.filter(l => !/phân xưởng/i.test(l.location || "") && l.quantity > 0)
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));   // FIFO: nhập trước hiện trước
    const qcPendingCountKc = rowsAllKc.filter(l => l.status === "on_hold").length;
    const rows = SUB.kc_only_qc ? rowsAllKc.filter(l => l.status === "on_hold") : rowsAllKc;
    body = `<div class="panel"><h2>Danh sách lô kho công ty <span class="muted">(${rows.length}${SUB.kc_only_qc ? "/" + rowsAllKc.length : ""})</span></h2>
      <div class="muted" style="margin-bottom:6px">Toàn bộ lô đang nằm ở kho công ty, sắp xếp nhập trước hiện trước (FIFO) để ưu tiên xuất/chuyển.</div>
      <label class="muted" style="display:inline-flex;align-items:center;gap:6px;margin-bottom:8px">
        <input type="checkbox" id="kc_only_qc" ${SUB.kc_only_qc ? "checked" : ""}/> 🔬 Chỉ hiện lô đang chờ KCS khai báo/duyệt chỉ tiêu (${qcPendingCountKc})</label>
      <input class="searchbox" data-tbl="t_kc" placeholder="Tìm mã lô/vật tư..." style="margin-bottom:8px"/>
      <div class="tablewrap"><table id="t_kc">
        <thead><tr><th>Lô</th><th>Vật tư</th><th>Tên vật tư</th><th>SL</th><th>Ngày giờ nhập</th><th>Vị trí cất</th><th>Trạng thái</th><th></th></tr></thead>
        <tbody>${rows.map(l => `<tr>
          <td><code class="k">${lotCodeCellHtml(l)}</code></td>
          <td class="muted">${esc(matById[l.material_id] ? matById[l.material_id].code : l.material_id || "—")}</td>
          <td>${esc(matById[l.material_id] ? matById[l.material_id].name : "—")}</td>
          <td>${l.quantity} ${l.uom}</td>
          <td class="muted">${fmt(l.created_at)}</td>
          <td class="muted">${l.location_id && matLocByIdKc[l.location_id] ? esc(matLocByIdKc[l.location_id].code) + " — " + esc(matLocByIdKc[l.location_id].name) : "(chưa gán vị trí)"}</td>
          <td>${badge(l.status)}</td>
          <td style="white-space:nowrap">${qcReqSet.has(l.material_id) ? `<button class="btn sm sec" data-lotqc="${esc(l.lot_id)}">Xem chỉ tiêu</button>` : ""}
            <button class="btn sm sec" data-relocatelot="${esc(l.lot_id)}">Đổi vị trí</button></td></tr>`).join("") ||
          `<tr><td colspan=8 class="muted">Chưa có lô nào ở kho công ty.</td></tr>`}</tbody>
      </table></div>
    </div>`;
  } else if (sec === "vitri") {
    const [allLotsVt, matsVt, matLocsVt] = await Promise.all([GET("/lots"), GET("/materials"),
      GET("/warehouse/locations").catch(() => [])]);
    const matByIdVt = Object.fromEntries(matsVt.map(m => [m.material_id, m]));
    WH_CACHE.vtMatById = matByIdVt;
    WH_CACHE.vtLots = allLotsVt.filter(l => !/phân xưởng/i.test(l.location || "") && l.quantity > 0);
    const unplacedVt = WH_CACHE.vtLots.filter(l => !l.location_id);
    const activeLocsVt = matLocsVt.filter(l => l.active && (l.scope === "cong_ty" || l.scope === "ca_hai"));
    const locOptsVt = activeLocsVt.map(l => `<option value="${esc(l.loc_id)}">${esc(l.code)} — ${esc(l.name)}</option>`).join("") ||
      `<option value="">(chưa khai báo vị trí kho — vào Danh mục để thêm)</option>`;
    body = `<div class="panel"><h2>🚚 Cất vào vị trí <span class="muted">(${unplacedVt.length})</span></h2>
      <div class="muted" style="margin-bottom:8px">Gán vị trí kho cho các lô Kho công ty CHƯA có vị trí (nhập trước khi khai danh mục vị trí, hoặc nhập tồn đầu bằng Excel) — chọn vị trí đích rồi tick các lô cần cất.</div>
      <div class="row"><div class="field"><label>Vị trí đích</label><select id="vt_to">${locOptsVt}</select></div></div>
      <input class="searchbox" data-tbl="t_vt_unplaced" placeholder="Tìm mã lô/vật tư..." style="margin-bottom:8px"/>
      <div class="tablewrap" style="margin-top:10px"><table id="t_vt_unplaced">
        <thead><tr><th></th><th>Lô</th><th>Vật tư</th><th>SL</th><th>Ngày nhập</th></tr></thead>
        <tbody>${unplacedVt.map(l => `<tr><td><input type="checkbox" data-vtu="${esc(l.lot_id)}"/></td>
          <td><code class="k">${lotCodeCellHtml(l)}</code></td>
          <td>${esc(matByIdVt[l.material_id] ? matByIdVt[l.material_id].name : "—")}</td>
          <td>${l.quantity} ${l.uom}</td><td class="muted">${fmt(l.created_at)}</td></tr>`).join("") ||
          `<tr><td colspan=5 class="muted">Không có lô nào chưa gán vị trí.</td></tr>`}</tbody>
      </table></div>
      <button class="btn" id="vt_place_submit" style="margin-top:10px">Cất vào vị trí</button>
    </div>
    <div class="panel"><h2>🔁 Chuyển vị trí trong kho</h2>
      <div class="muted" style="margin-bottom:8px">Chuyển các lô ĐÃ CẤT sang vị trí khác (VD sắp xếp lại kho) — chọn vị trí nguồn để xem các lô đang ở đó, chọn vị trí đích rồi tick lô cần chuyển.</div>
      <div class="row">
        <div class="field"><label>Vị trí nguồn</label><select id="vt_from"><option value="">(chọn vị trí nguồn)</option>${locOptsVt}</select></div>
        <div class="field"><label>Vị trí đích</label><select id="vt_to2">${locOptsVt}</select></div>
      </div>
      <div id="vt_move_wrap" class="muted" style="margin-top:10px">Chọn vị trí nguồn để xem các lô đang ở đó.</div>
      <button class="btn" id="vt_move_submit" style="margin-top:10px">Chuyển vị trí</button>
    </div>`;
  } else if (sec === "kk") {
    body = await renderStockCountSection("Kho công ty");
  } else if (sec === "min") {
    body = await renderLowStockSection();
  }
  $("view-warehouse_kc").innerHTML = subnav("warehouse_kc", sections, sec) + body;
  wireSubnav("warehouse_kc");
  wireSearch();
  if (sec === "the") {
    wireSearchableSelect("wc_mat_txt", "wc_mat", WH_CACHE.matItemsThe);
    $("wc_load").onclick = () => guard(async () => {
    const card = await GET("/warehouse/card?material_id=" + $("wc_mat").value);
    $("wc_table").innerHTML = `<table id="t_wc_card"><thead><tr><th>Thời gian</th><th>Loại</th><th>Lô</th><th>Nhập</th><th>Xuất</th><th>Tồn</th><th>Lý do</th></tr></thead>
      <tbody>${card.map(c => `<tr><td class="muted">${fmt(c.ts)}</td><td>${badge(c.type === "receipt" ? "available" : c.type === "issue" ? "on_hold" : "planned")}${c.type}</td>
        <td>${esc(c.lot_code || "")}</td><td style="color:var(--green)">${c.in || ""}</td><td style="color:var(--orange)">${c.out || ""}</td>
        <td><b>${c.balance}</b> ${c.uom}</td><td class="muted">${esc(c.reason || "")}</td></tr>`).join("") || '<tr><td colspan=7 class="muted">Chưa có giao dịch.</td></tr>'}</tbody></table>`;
      if (!_pagerState.t_wc_card) _pagerState.t_wc_card = { page: 1, pageSize: 10, sortCol: 0, sortDir: -1 };
      wirePaginate("t_wc_card", 10);
    });
  }
  if (sec === "han") wirePaginate("t_expiry", 10);
  if (sec === "ton") wirePaginate("t_ton", 10, { onFilter: (trs) => {
    const el = document.getElementById("ton_total");
    if (el) el.innerHTML = `Tổng số lượng (theo bộ lọc đang áp dụng): ${sumTotalsHtml(trs)}`;
  } });
  if (sec === "kc") {
    // Mặc định hiện lô nhập GẦN NHẤT trước (cột "Ngày giờ nhập", đảo chiều) để đỡ phải kéo dài
    // — vẫn giữ đúng dữ liệu FIFO nhập-trước-hiện-trước bên dưới, người dùng bấm lại tiêu đề cột
    // là quay về đúng thứ tự FIFO (nhập trước lên đầu) khi cần chọn lô ưu tiên xuất/chuyển.
    if (!_pagerState.t_kc) _pagerState.t_kc = { page: 1, pageSize: 10, sortCol: 4, sortDir: -1 };
    wirePaginate("t_kc", 10);
    $("kc_only_qc").onchange = () => { SUB.kc_only_qc = $("kc_only_qc").checked; render("warehouse_kc"); };
    document.querySelectorAll("[data-relocatelot]").forEach(b => b.onclick = () => {
      const lotId = b.dataset.relocatelot;
      const locs = WH_CACHE.matLocsActive || [];
      const opts = locs.map(l => `<option value="${esc(l.loc_id)}">${esc(l.code)} — ${esc(l.name)}</option>`).join("") ||
        `<option value="">(chưa khai báo vị trí kho — vào Danh mục để thêm)</option>`;
      modal(`<h3>Đổi vị trí cất</h3>
        <div class="field"><label>Vị trí mới</label><select id="rl_loc">${opts}</select></div>
        <button class="btn" id="rl_save" style="margin-top:12px">Lưu</button>`);
      $("rl_save").onclick = () => guard(async () => {
        if (!$("rl_loc").value) throw new Error("Chọn vị trí mới.");
        await POST(`/warehouse/lots/${lotId}/relocate`, { location_id: $("rl_loc").value });
        closeModal(); toast("Đã đổi vị trí cất"); render("warehouse_kc");
      });
    });
  }
  if (sec === "vitri") {
    wirePaginate("t_vt_unplaced", 10);
    const rebuildMoveTable = () => {
      const fromId = $("vt_from").value;
      if (!fromId) { $("vt_move_wrap").innerHTML = '<div class="muted">Chọn vị trí nguồn để xem các lô đang ở đó.</div>'; return; }
      const lotsAt = (WH_CACHE.vtLots || []).filter(l => l.location_id === fromId);
      $("vt_move_wrap").innerHTML = `<div class="tablewrap"><table id="t_vt_move">
        <thead><tr><th></th><th>Lô</th><th>Vật tư</th><th>SL</th></tr></thead>
        <tbody>${lotsAt.map(l => `<tr><td><input type="checkbox" data-vtm="${esc(l.lot_id)}"/></td>
          <td><code class="k">${lotCodeCellHtml(l)}</code></td>
          <td>${esc((WH_CACHE.vtMatById[l.material_id] || {}).name || "—")}</td>
          <td>${l.quantity} ${l.uom}</td></tr>`).join("") ||
          `<tr><td colspan=4 class="muted">Không có lô nào ở vị trí này.</td></tr>`}</tbody>
      </table></div>`;
      wirePaginate("t_vt_move", 10);
    };
    if ($("vt_from")) $("vt_from").onchange = rebuildMoveTable;
    if ($("vt_place_submit")) $("vt_place_submit").onclick = () => guard(async () => {
      const toId = $("vt_to").value;
      if (!toId) throw new Error("Chọn vị trí đích.");
      const ids = Array.from(document.querySelectorAll("[data-vtu]:checked")).map(c => c.dataset.vtu);
      if (!ids.length) throw new Error("Chọn ít nhất 1 lô cần cất.");
      for (const id of ids) await POST(`/warehouse/lots/${id}/relocate`, { location_id: toId });
      toast(`Đã cất ${ids.length} lô vào vị trí`);
      render("warehouse_kc");
    });
    if ($("vt_move_submit")) $("vt_move_submit").onclick = () => guard(async () => {
      const toId = $("vt_to2").value;
      if (!toId) throw new Error("Chọn vị trí đích.");
      const ids = Array.from(document.querySelectorAll("[data-vtm]:checked")).map(c => c.dataset.vtm);
      if (!ids.length) throw new Error("Chọn ít nhất 1 lô cần chuyển.");
      for (const id of ids) await POST(`/warehouse/lots/${id}/relocate`, { location_id: toId });
      toast(`Đã chuyển ${ids.length} lô sang vị trí mới`);
      render("warehouse_kc");
    });
  }
  if (sec === "min") wirePaginate("t_lowstock", 10);
  if (sec === "bc") {
    wirePaginate("t_bcrep", 10);
    $("bc_apply").onclick = () => {
      SUB.bc_date_from = $("bc_from").value;
      SUB.bc_date_to = $("bc_to").value;
      render("warehouse_kc");
    };
  }
  if (sec === "nhap") {
    wirePaginate("rc_hist", 10);
    wireSearchableSelect("rc_mat_txt", "rc_mat", WH_CACHE.matItems, (item) => { $("rc_uom").value = item.uom || ""; });
    wireSearchableSelect("rc_supplier_txt", "rc_supplier", WH_CACHE.supplierItems);
    $("rc_do").onclick = () => guard(async () => {
      const rcDtRaw = $("rc_dt").value;
      if (!rcDtRaw) throw new Error("Chọn ngày nhập.");
      if (!$("rc_loc").value) throw new Error("Chọn vị trí cất trước khi nhập.");
      const res = await POST("/warehouse/receive", { material_id: $("rc_mat").value,
        supplier_id: $("rc_supplier").value || null, unit_price: $("rc_price").value ? parseFloat($("rc_price").value) : null,
        quantity: parseFloat($("rc_qty").value), uom: $("rc_uom").value, received_at: new Date(rcDtRaw).toISOString(),
        location_id: $("rc_loc").value, supplier_lot: $("rc_supplier_lot").value.trim() || null,
        expiry: $("rc_exp").value || null, reason: $("rc_note").value.trim() || "Nhập kho" });
      if (res.status === "on_hold") toast(`Đã nhập kho (mã lô ${res.lot_code}) — lô đang CHỜ khai báo & duyệt chỉ tiêu chất lượng`, "err");
      else toast(`Đã nhập kho (mã lô ${res.lot_code})`);
      render("warehouse_kc");
    });
    if ($("rc_delhist")) $("rc_delhist").onclick = () => guard(async () => {
      if (!confirm("Xóa TOÀN BỘ lịch sử nhập kho? Lô/tồn kho hiện tại KHÔNG bị đụng tới, chỉ mất bảng ghi lịch sử nhập. Không thể hoàn tác.")) return;
      const res = await DELETE("/warehouse/movements/receipt-history");
      toast(`Đã xóa ${res.deleted} dòng lịch sử nhập kho`);
      render("warehouse_kc");
    });
    document.querySelectorAll("[data-editrc]").forEach(b => b.onclick = () => {
      const m = WH_CACHE.receipts.find(r => r.movement_id === b.dataset.editrc);
      if (!m) return;
      const lot = m.lot_id ? WH_CACHE.lotById[m.lot_id] : null;
      modal(`<h3>Sửa lượt nhập kho — lô ${esc(m.lot_code || "")}</h3>
        <div class="muted" style="margin-bottom:10px">Chỉ sửa được khi lô CHƯA xuất/chuyển/tiêu thụ — nếu đã dùng, lưu sẽ báo lỗi.</div>
        <div class="row"><div class="field"><label>Số lượng</label><input id="erc_qty" type="number" value="${m.quantity}"/></div>
          <div class="field"><label>ĐVT</label><input value="${esc(m.uom)}" size="4" readonly/></div></div>
        <div class="row"><div class="field" style="position:relative"><label>Nhà CC</label>
            <input type="text" id="erc_supplier_txt" autocomplete="off" placeholder="Tìm nhà cung cấp..."/>
            <input type="hidden" id="erc_supplier"/></div>
          <div class="field"><label>Đơn giá</label><input id="erc_price" type="number" value="${lot && lot.unit_price != null ? lot.unit_price : ""}" placeholder="(tuỳ chọn)"/></div></div>
        <div class="row"><div class="field"><label>Số lô KCS</label><input id="erc_kcs" value="${esc(lot && lot.kcs_lot_no || "")}"/></div>
          <div class="field"><label>Số LOT nhà cung cấp</label><input id="erc_supplier_lot" value="${esc(lot && lot.supplier_lot || "")}"/></div>
          <div class="field"><label>Hạn dùng</label><input id="erc_exp" type="date" value="${lot && lot.expiry ? lot.expiry.slice(0, 10) : ""}"/></div></div>
        <div class="row"><div class="field" style="flex:1"><label>Diễn giải</label><input id="erc_note" value="${esc(m.reason || "")}"/></div>
          <button class="btn" id="erc_save" style="align-self:flex-end">Lưu</button></div>`);
      wireSearchableSelect("erc_supplier_txt", "erc_supplier", WH_CACHE.supplierItems);
      if (lot && lot.supplier_id) {
        const item = WH_CACHE.supplierItems.find(i => i.value === lot.supplier_id);
        if (item) { $("erc_supplier").value = item.value; $("erc_supplier_txt").value = item.label; }
      }
      $("erc_save").onclick = () => guard(async () => {
        await PUT(`/warehouse/movements/${m.movement_id}`, {
          quantity: parseFloat($("erc_qty").value), supplier_id: $("erc_supplier").value || null,
          unit_price: $("erc_price").value ? parseFloat($("erc_price").value) : null,
          kcs_lot_no: $("erc_kcs").value.trim() || null, supplier_lot: $("erc_supplier_lot").value.trim() || null,
          expiry: $("erc_exp").value || null, reason: $("erc_note").value.trim() || null,
        });
        toast("Đã lưu"); closeModal(); render("warehouse_kc");
      });
    });
    document.querySelectorAll("[data-delrc]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa lượt nhập kho này? Số lượng sẽ bị trừ khỏi tồn lô (hoặc xóa cả lô nếu đây là lượt nhập duy nhất). Không thể hoàn tác.")) return;
      const res = await DELETE(`/warehouse/movements/${b.dataset.delrc}`);
      toast(res.lot_deleted ? "Đã xóa lượt nhập kho và cả lô (không còn lượt nhập nào khác)" : "Đã xóa lượt nhập kho");
      render("warehouse_kc");
    }));
  }
  if (sec === "obal") {
    wireSearchableSelect("ob_mat_txt", "ob_mat", WH_CACHE.matItems, (item) => { $("ob_uom").value = item.uom || ""; });
    if ($("ob_do")) $("ob_do").onclick = () => guard(async () => {
      const res = await POST("/warehouse/receive", { lot_code: $("ob_code").value, material_id: $("ob_mat").value,
        quantity: parseFloat($("ob_qty").value), uom: $("ob_uom").value, location: "Kho công ty",
        expiry: $("ob_exp").value || null, kcs_lot_no: $("ob_kcs").value.trim() || null,
        supplier_lot: $("ob_supplier_lot").value.trim() || null,
        reason: "Nhập tồn đầu", is_opening_balance: true });
      if (res.status === "on_hold") toast("Đã nhập tồn đầu — lô đang CHỜ khai báo & duyệt chỉ tiêu chất lượng", "err");
      else toast("Đã nhập tồn đầu tại Kho công ty");
      render("warehouse_kc");
    });
    if ($("ob_import")) $("ob_import").onclick = () => guard(async () => {
      const f = $("ob_file").files[0];
      if (!f) throw new Error("Chọn file Excel trước.");
      const fd = new FormData();
      fd.append("file", f);
      fd.append("location", "Kho công ty");
      const headers = {};
      if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
      const res = await fetch("/api/warehouse/opening-balance/import", { method: "POST", headers, body: fd });
      const result = await res.json();
      if (!res.ok) throw new Error(result && result.detail ? result.detail : "HTTP " + res.status);
      if (result.failed && result.failed.length) {
        alert(`Đã nhập ${result.created.length}/${result.total} dòng. ${result.failed.length} dòng lỗi:\n` +
          result.failed.map(x => `Dòng ${x.row}: ${x.reason}`).join("\n"));
      } else {
        toast(`Đã nhập tồn đầu từ Excel: ${result.created.length}/${result.total} dòng`);
      }
      render("warehouse_kc");
    });
  }
  if (sec === "sng") {
    wirePaginate("t_sng_pending", 10);
    wirePaginate("t_sng_done", 10);
    if ($("sng_mat_txt")) wireSearchableSelect("sng_mat_txt", "sng_mat", WH_CACHE.matItems, (item) => {
      $("sng_uom_wrap").innerHTML = altUomFieldHtml((WH_CACHE.matById || {})[item.value], "sng_uom", 60);
    });
    if ($("sng_supplier_txt")) wireSearchableSelect("sng_supplier_txt", "sng_supplier", WH_CACHE.supplierItems);
    if ($("sng_do")) $("sng_do").onclick = () => guard(async () => {
      const sngMat = (WH_CACHE.matById || {})[$("sng_mat").value];
      const sngQty = altUomToBaseQty(sngMat, parseFloat($("sng_qty").value), $("sng_uom").value);
      const res = await POST("/warehouse/sang-ngang", { material_id: $("sng_mat").value,
        supplier_id: $("sng_supplier").value || null, unit_price: $("sng_price").value ? parseFloat($("sng_price").value) : null,
        quantity: sngQty, uom: sngMat ? sngMat.uom : $("sng_uom").value, location_id: $("sng_loc").value || null,
        supplier_lot: $("sng_supplier_lot").value.trim() || null,
        expiry: $("sng_exp").value || null, reason: $("sng_note").value.trim() || "Xuất sang ngang" });
      toast(`Đã tạo đề nghị xuất sang ngang (số ${res.request_code}) — chờ phân xưởng duyệt`);
      render("warehouse_kc");
    });
    document.querySelectorAll("[data-sngedit]").forEach(b => b.onclick = () => {
      const r = WH_CACHE.sangNgangRequests.find(x => x.request_id === b.dataset.sngedit);
      if (!r) return;
      const lot = r.lot_id ? WH_CACHE.lotById[r.lot_id] : null;
      modal(`<h3>Sửa đề nghị Xuất sang ngang — ${esc(r.request_code)}</h3>
        <div class="muted" style="margin-bottom:10px">Chỉ sửa được khi CHƯA được Kho phân xưởng duyệt — nếu đã duyệt, lưu sẽ báo lỗi.</div>
        <div class="row"><div class="field"><label>Số lượng</label><input id="esng_qty" type="number" value="${r.quantity}"/></div>
          <div class="field"><label>ĐVT</label><input value="${esc(r.uom)}" size="4" readonly/></div></div>
        <div class="row"><div class="field" style="position:relative"><label>Nhà CC</label>
            <input type="text" id="esng_supplier_txt" autocomplete="off" placeholder="Tìm nhà cung cấp..."/>
            <input type="hidden" id="esng_supplier"/></div>
          <div class="field"><label>Đơn giá</label><input id="esng_price" type="number" value="${lot && lot.unit_price != null ? lot.unit_price : ""}" placeholder="(tuỳ chọn)"/></div></div>
        <div class="row"><div class="field"><label>Số lô KCS</label><input id="esng_kcs" value="${esc(lot && lot.kcs_lot_no || "")}"/></div>
          <div class="field"><label>Số LOT NCC</label><input id="esng_supplier_lot" value="${esc(lot && lot.supplier_lot || "")}"/></div>
          <div class="field"><label>Hạn dùng</label><input id="esng_exp" type="date" value="${lot && lot.expiry ? lot.expiry.slice(0, 10) : ""}"/></div></div>
        <div class="row"><div class="field" style="flex:1"><label>Diễn giải</label><input id="esng_note" value="${esc(r.reason || "")}"/></div>
          <button class="btn" id="esng_save" style="align-self:flex-end">Lưu</button></div>`);
      wireSearchableSelect("esng_supplier_txt", "esng_supplier", WH_CACHE.supplierItems);
      if (lot && lot.supplier_id) {
        const item = WH_CACHE.supplierItems.find(i => i.value === lot.supplier_id);
        if (item) { $("esng_supplier").value = item.value; $("esng_supplier_txt").value = item.label; }
      }
      $("esng_save").onclick = () => guard(async () => {
        await PUT(`/warehouse/sang-ngang/${r.request_id}`, {
          quantity: parseFloat($("esng_qty").value), supplier_id: $("esng_supplier").value || null,
          unit_price: $("esng_price").value ? parseFloat($("esng_price").value) : null,
          kcs_lot_no: $("esng_kcs").value.trim() || null, supplier_lot: $("esng_supplier_lot").value.trim() || null,
          expiry: $("esng_exp").value || null, reason: $("esng_note").value.trim() || null,
        });
        toast("Đã lưu"); closeModal(); render("warehouse_kc");
      });
    });
    document.querySelectorAll("[data-sngdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa đề nghị Xuất sang ngang này? Số lượng sẽ bị trừ khỏi tồn lô (hoặc xóa cả lô nếu đây là lượt nhập duy nhất). Không thể hoàn tác.")) return;
      const res = await DELETE(`/warehouse/sang-ngang/${b.dataset.sngdel}`);
      toast(res.lot_deleted ? "Đã xóa đề nghị và cả lô (không còn lượt nhập nào khác)" : "Đã xóa đề nghị");
      render("warehouse_kc");
    }));
    document.querySelectorAll("[data-sngresubmit]").forEach(b => b.onclick = () => guard(async () => {
      await POST(`/warehouse/sang-ngang/${b.dataset.sngresubmit}/resubmit`, {});
      toast("Đã gửi lại — đề nghị về trạng thái chờ Kho phân xưởng duyệt");
      render("warehouse_kc");
    }));
  }
  if (sec === "tudo") {
    if ($("xt_lot")) wireLotAltUom("xt_lot", "xt_uom");
    wireSelectSearch("xt_lot", "xt_lot_q");
    if ($("xt_do")) $("xt_do").onclick = () => guard(async () => {
      const qty = lotAltUomQty("xt_lot", "xt_uom", parseFloat($("xt_qty").value));
      await POST("/warehouse/issue", { lot_id: $("xt_lot").value, quantity: qty,
        mode: "tu_do", reason: $("xt_reason").value.trim() || null });
      toast("Đã xuất tự do"); render("warehouse_kc");
    });
    Object.keys(WH_HIST_VISIBLE).forEach(wireMovementHistoryBlock);
  }
  if (sec === "dc") {
    wirePaginate("t_pxpending", 10);
    wirePaginate("t_pxdone", 10);
    wirePaginate("t_kcpx_pending", 10);
    wirePaginate("t_kcpx_done", 10);
    document.querySelectorAll("[data-pxapprove]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Duyệt đề nghị điều chuyển này? Lô sẽ thật sự chuyển về Kho công ty ngay.")) return;
      await POST(`/warehouse/transfer-px-requests/${b.dataset.pxapprove}/approve`, {});
      toast("Đã duyệt điều chuyển"); render("warehouse_kc");
    }));
    document.querySelectorAll("[data-pxreject]").forEach(b => b.onclick = () => guard(async () => {
      const reason = prompt("Lý do từ chối (tuỳ chọn):") || null;
      await POST(`/warehouse/transfer-px-requests/${b.dataset.pxreject}/reject`, { reason });
      toast("Đã từ chối đề nghị"); render("warehouse_kc");
    }));
    document.querySelectorAll("[data-pxundo]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Hoàn tác đề nghị đã duyệt này? Lô sẽ trả về lại Kho phân xưởng.")) return;
      await POST(`/warehouse/transfer-px-requests/${b.dataset.pxundo}/undo`, {});
      toast("Đã hoàn tác điều chuyển"); render("warehouse_kc");
    }));
    wireSelectSearch("dcnm_lot", "dcnm_lot_q");
    wireSelectSearch("dckp_lot", "dckp_lot_q");
    if ($("dcnm_do")) $("dcnm_do").onclick = () => guard(async () => {
      if (!$("dcnm_lot").value) throw new Error("Không có lô nào đang ở kho công ty để điều chuyển.");
      if (!$("dcnm_factory").value) throw new Error("Chưa có nhà máy nào trong danh mục — vào Danh mục để tạo trước.");
      await POST("/warehouse/transfer-to-factory", { lot_id: $("dcnm_lot").value, quantity: parseFloat($("dcnm_qty").value),
        factory_id: $("dcnm_factory").value, reason: $("dcnm_reason").value.trim() || null });
      toast("Đã điều chuyển sang nhà máy khác"); render("warehouse_kc");
    });
    if ($("dckp_do")) $("dckp_do").onclick = () => guard(async () => {
      if (!$("dckp_lot").value) throw new Error("Không có lô nào đang ở kho công ty để điều chuyển.");
      await POST("/warehouse/transfer-kcpx-requests", { lot_id: $("dckp_lot").value,
        quantity: parseFloat($("dckp_qty").value), reason: $("dckp_reason").value.trim() || null });
      toast("Đã gửi đề nghị điều chuyển sang Phân xưởng — chờ Phân xưởng duyệt"); render("warehouse_kc");
    });
    Object.keys(WH_HIST_VISIBLE).forEach(wireMovementHistoryBlock);
  }
  if (sec === "tra") {
    $("ncc_do").onclick = () => guard(async () => {
      const reason = $("ncc_reason").value.trim();
      if (!reason) throw new Error("Phải nhập lý do trả nhà cung cấp.");
      await POST("/warehouse/return-to-supplier", { lot_id: $("ncc_lot").value, quantity: parseFloat($("ncc_qty").value), reason });
      toast("Đã xuất trả nhà cung cấp"); render("warehouse_kc");
    });
    Object.keys(WH_HIST_VISIBLE).forEach(wireMovementHistoryBlock);
  }
  if (sec === "xtdn") {
    Object.keys(WH_HIST_VISIBLE).forEach(wireMovementHistoryBlock);
    wireRequestBlockActions();
    wireCardSearch("xtdn_search", "#xtdn_block");
  }
  if (sec === "ton") {
    document.querySelectorAll("[data-viewlots]").forEach(b => b.onclick = () =>
      openMaterialLotsModal(b.dataset.matlabel, lotsByMaterial[b.dataset.viewlots] || []));
    $("ton_loc").onchange = () => { TON_LOC.warehouse_kc = $("ton_loc").value; render("warehouse_kc"); };
  }
  document.querySelectorAll("[data-lotqc]").forEach(b => b.onclick = () => openLotQcModal(b.dataset.lotqc, { editable: false }));
  if (sec === "kk") wireStockCountSection("warehouse_kc");
};

// Kiểm kê định kỳ: dùng chung giữa Kho công ty và Kho phân xưởng — mỗi bên chỉ tạo/xem/duyệt
// phiếu của ĐÚNG kho mình (tách theo `location` cố định truyền vào, không còn dropdown chọn
// kho tự do như trước — vd Kho công ty không tạo/thấy phiếu của Kho phân xưởng và ngược lại).
// BE vẫn tự chặn theo User.scope_warehouse (_assert_location_scope) nếu ai đó cố gọi thẳng API.
async function renderStockCountSection(location) {
  const allCounts = await GET("/warehouse/counts");
  const counts = allCounts.filter(c => c.location === location);
  const canApproveCount = _hasPerm("warehouse.count_approve");
  return `<div class="panel"><h2>Kiểm kê định kỳ — ${esc(location)}</h2>
    <div class="muted" style="margin-bottom:6px">Đối chiếu tồn hệ thống với tồn thực tế đếm tại kho — tạo phiếu để chụp tồn hệ thống hiện tại, điền số đếm thực tế, rồi chốt phiếu để tự động điều chỉnh lệch (nếu có).</div>
    <div class="row" style="margin-bottom:10px">
      <div class="field"><label>Ngày bắt đầu kiểm kê</label><input id="kk_start" type="date"/></div>
      <div class="field"><label>Ngày kết thúc kiểm kê</label><input id="kk_end" type="date"/></div>
      <div class="field" style="flex:1"><label>Ghi chú</label><input id="kk_note" placeholder="(tuỳ chọn)"/></div>
      <button class="btn" id="kk_create" data-location="${esc(location)}" style="align-self:flex-end">+ Tạo phiếu kiểm kê</button>
    </div>
    <input class="searchbox" data-tbl="t_kk" placeholder="Tìm mã phiếu..." style="margin-bottom:8px"/>
    <div class="tablewrap"><table id="t_kk">
      <thead><tr><th>Mã phiếu</th><th>Kỳ kiểm kê</th><th>Số dòng</th><th>Trạng thái</th><th>Người tạo</th><th>Ngày tạo</th><th></th></tr></thead>
      <tbody>${counts.map(c => `<tr>
        <td><code class="k">${esc(c.count_code)}</code></td>
        <td class="muted">${c.start_date || c.end_date ? `${c.start_date ? fmt(c.start_date) : "?"} → ${c.end_date ? fmt(c.end_date) : "?"}` : "—"}</td>
        <td>${c.line_count}</td>
        <td>${c.approved_by ? `<span style="color:var(--green)">Đã duyệt</span> <span class="muted" style="font-size:11px">(${esc(c.approved_by)})</span>`
              : c.status === "posted" ? '<span style="color:var(--green)">Đã chốt</span>' : '<span class="muted">Nháp</span>'}</td>
        <td class="muted">${esc(c.created_by || "")}</td>
        <td class="muted">${fmt(c.created_at)}</td>
        <td style="white-space:nowrap">
          <button class="btn sm sec" data-viewcount="${esc(c.count_id)}">Xem/Nhập số liệu</button>
          ${c.can_approve && canApproveCount ? `<button class="btn sm" data-approvecount="${esc(c.count_id)}">Duyệt</button>` : ""}
          ${c.can_undo ? `<button class="btn sm sec" data-undocount="${esc(c.count_id)}">Hoàn tác</button>` : ""}
        </td></tr>`).join("") ||
        `<tr><td colspan=7 class="muted">Chưa có phiếu kiểm kê nào cho ${esc(location)}.</td></tr>`}</tbody>
    </table></div>
  </div>`;
}

function wireStockCountSection(viewName) {
  // Mặc định phiếu kiểm kê mới tạo GẦN NHẤT lên đầu (cột "Ngày tạo", đảo chiều) — đỡ phải kéo
  // dài khi đã có nhiều phiếu qua nhiều đợt, bấm lại tiêu đề cột để đổi chiều nếu cần.
  if (!_pagerState.t_kk) _pagerState.t_kk = { page: 1, pageSize: 10, sortCol: 5, sortDir: -1 };
  wirePaginate("t_kk", 10);
  $("kk_create").onclick = () => guard(async () => {
    await POST("/warehouse/counts", { location: $("kk_create").dataset.location,
      start_date: $("kk_start").value || null, end_date: $("kk_end").value || null,
      note: $("kk_note").value.trim() || null });
    toast("Đã tạo phiếu kiểm kê"); render(viewName);
  });
  document.querySelectorAll("[data-viewcount]").forEach(b => b.onclick = () => openStockCountModal(b.dataset.viewcount));
  document.querySelectorAll("[data-approvecount]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Duyệt phiếu kiểm kê này? Xác nhận đã xem/đồng ý số liệu đã chốt — không đổi lại tồn kho, và sau khi duyệt sẽ không hoàn tác được nữa.")) return;
    await POST(`/warehouse/counts/${b.dataset.approvecount}/approve`);
    toast("Đã duyệt phiếu kiểm kê"); render(viewName);
  }));
  document.querySelectorAll("[data-undocount]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Hoàn tác phiếu kiểm kê này? Tồn kho sẽ trả về đúng số liệu hệ thống trước khi chốt, phiếu về lại trạng thái Nháp để sửa/chốt lại.")) return;
    await POST(`/warehouse/counts/${b.dataset.undocount}/undo`);
    toast("Đã hoàn tác phiếu kiểm kê"); render(viewName);
  }));
}

// ================= KHO NVL — KHO PHÂN XƯỞNG =================
VIEWS.warehouse_px = async function () {
  const sec = SUB.warehouse_px || "px";
  const sections = [
    { key: "px", label: "Xem tồn kho" }, { key: "tondau", label: "🏁 Nhập tồn đầu" },
    { key: "req", label: "Đề nghị nhận kho" }, { key: "dieuchuyen", label: "Điều chuyển" },
    { key: "sangngang", label: "Xuất sang ngang" },
    { key: "tudo", label: "Xuất tự do" }, { key: "nvlhist", label: "Lịch sử xuất dùng NVL" },
    { key: "vitri", label: "📍 Vị trí kho" },
    { key: "kk", label: "Kiểm kê định kỳ" },
  ];
  let body = "";
  if (sec === "px") {
    const pxLoc = TON_LOC.warehouse_px;
    const pxLotMatchesLoc = (l) => pxLoc === "" ? true : pxLoc === "Kho phân xưởng"
      ? /phân xưởng/i.test(l.location || "") : !/phân xưởng/i.test(l.location || "");
    const [allLots, mats, qcReqIdsPx, wsLocsPx] = await Promise.all([GET("/lots"), GET("/materials"),
      GET("/materials/qc-required").catch(() => []), GET("/warehouse/locations").catch(() => [])]);
    const matById = Object.fromEntries(mats.map(m => [m.material_id, m]));
    const qcReqSetPx = new Set(qcReqIdsPx);
    const wsLocByIdPx = Object.fromEntries(wsLocsPx.map(l => [l.loc_id, l]));
    const rows = allLots.filter(l => pxLotMatchesLoc(l) && l.quantity > 0)
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));   // FIFO: nhập trước hiện trước
    body = `<div class="panel"><h2>Tồn kho — ${esc(pxLoc || "Tất cả")} <span class="muted">(${rows.length})</span></h2>
      <div class="row" style="margin-bottom:8px"><div class="field"><label>Kho</label>${tonLocSelectHtml("px_loc", pxLoc)}</div></div>
      <div class="muted" style="margin-bottom:6px">Lô đã được duyệt chỉ tiêu chất lượng ở kho công ty và chuyển tới đây (qua Đề nghị nhận kho) —
        không cần khai báo lại, chỉ tiêu hiển thị tự động lấy theo dữ liệu đã duyệt.</div>
      <input class="searchbox" data-tbl="t_px" placeholder="Tìm mã lô/vật tư..." style="margin-bottom:8px"/>
      <div id="px_total" class="muted" style="margin-bottom:6px"></div>
      <div class="tablewrap"><table id="t_px">
        <thead><tr><th>Lô</th><th>Vật tư</th><th>Tên vật tư</th><th>SL</th><th>Ngày giờ nhập</th><th>Vị trí</th><th>Trạng thái</th><th></th></tr></thead>
        <tbody>${rows.map(l => `<tr data-qty="${l.quantity}" data-uom="${esc(l.uom)}">
          <td><code class="k">${lotCodeCellHtml(l)}</code></td>
          <td class="muted">${esc(matById[l.material_id] ? matById[l.material_id].code : l.material_id || "—")}</td>
          <td>${esc(matById[l.material_id] ? matById[l.material_id].name : "—")}</td>
          <td>${l.quantity} ${l.uom}</td>
          <td class="muted">${fmt(l.created_at)}</td>
          <td class="muted">${esc(l.location || "")}${l.workshop_location_id && wsLocByIdPx[l.workshop_location_id] ? " — " + esc(wsLocByIdPx[l.workshop_location_id].code) : ""}</td>
          <td>${badge(l.status)}</td>
          <td>${qcReqSetPx.has(l.material_id) ? `<button class="btn sm sec" data-lotqc="${esc(l.lot_id)}">Xem chỉ tiêu</button>` : ""}</td></tr>`).join("") ||
          `<tr><td colspan=8 class="muted">Chưa có lô nào ở ${esc(pxLoc || "kho nào")}.</td></tr>`}</tbody>
      </table></div>
    </div>`;
  } else if (sec === "tondau") {
    const mats = await GET("/materials");
    const matItemsPx = mats.map(m => ({ value: m.material_id, label: `${m.code} — ${m.name}`, uom: m.uom }));
    const isAdminTondauPx = CURRENT_USER && CURRENT_USER.role === "admin";
    WH_CACHE.matItemsPx = matItemsPx;
    body = `<div class="panel"><h2>🏁 Nhập tồn đầu (kho phân xưởng)</h2>
      <div class="muted" style="margin-bottom:6px">Nạp số dư tồn kho ban đầu khi triển khai hệ thống trực tiếp tại kho phân xưởng
        (không qua nhận hàng nhà cung cấp hay điều chuyển từ kho công ty).</div>
      ${isAdminTondauPx
        ? `<div class="row"><div class="field"><label>Mã lô</label><input id="obpx_code" placeholder="MALT-..."/></div>
        <div class="field" style="position:relative"><label>Vật tư</label>
          <input type="text" id="obpx_mat_txt" autocomplete="off" placeholder="Tìm mã/tên nguyên liệu..." value="${esc(matItemsPx[0]?.label || "")}"/>
          <input type="hidden" id="obpx_mat" value="${esc(matItemsPx[0]?.value || "")}"/></div></div>
        <div class="row"><div class="field"><label>SL</label><input id="obpx_qty" type="number" value="500"/></div>
          <div class="field"><label>ĐVT</label><input id="obpx_uom" value="${esc(matItemsPx[0]?.uom || "")}" size="4" readonly title="Lấy tự động từ danh mục nguyên liệu — không sửa được"/></div>
          <div class="field"><label>Hạn dùng</label><input id="obpx_exp" type="date"/></div>
          <div class="field"><label>Số lô KCS</label><input id="obpx_kcs" placeholder="(tuỳ chọn)"/></div>
          <div class="field"><label>Số LOT NCC</label><input id="obpx_supplier_lot" placeholder="(tuỳ chọn)"/></div>
          <button class="btn" id="obpx_do">Nhập tồn đầu</button></div>
        <div class="row" style="margin-top:10px;border-top:1px solid var(--border);padding-top:10px">
          <div class="field" style="flex:1"><label>Hoặc import Excel (cột: Ngày nhập, Mã vật tư, Lô, Số lượng, tuỳ chọn thêm Số lô KCS)</label>
            <input type="file" id="obpx_file" accept=".xlsx"/></div>
          <button class="btn sec" id="obpx_import" style="align-self:flex-end">📥 Import Excel</button></div>`
        : '<div class="muted">Chỉ tài khoản Admin mới được thực hiện nhập tồn đầu.</div>'}
    </div>`;
  } else if (sec === "req") {
    body = await renderRequestsSection();
  } else if (sec === "dieuchuyen") {
    const [allLots, mats, pxRequests, kcpxRequestsPx, qcReqIdsKcpx, workshopLocsPx] = await Promise.all([
      GET("/lots"), GET("/materials"), GET("/warehouse/transfer-px-requests"),
      GET("/warehouse/transfer-kcpx-requests").catch(() => []), GET("/materials/qc-required").catch(() => []),
      GET("/warehouse/locations").catch(() => [])]);
    const matById = Object.fromEntries(mats.map(m => [m.material_id, m]));
    const lotByIdPxDc = Object.fromEntries(allLots.map(l => [l.lot_id, l]));
    const qcReqSetKcpx = new Set(qcReqIdsKcpx);
    const canRequestPx = _hasPerm("warehouse.request");
    const canApproveKcpx = _hasPerm("warehouse.request");
    const isAdminDc = CURRENT_USER && CURRENT_USER.role === "admin";
    const activeWorkshopLocs = workshopLocsPx.filter(l => l.active && (l.scope === "phan_xuong" || l.scope === "ca_hai"));
    WH_CACHE.matById = matById;
    WH_CACHE.lotById = lotByIdPxDc;
    WH_CACHE.workshopLocs = activeWorkshopLocs;
    const workshopLocByIdPx = Object.fromEntries(workshopLocsPx.map(l => [l.loc_id, l]));
    const workshopLotOpts = allLots.filter(l => l.quantity > 0 && /phân xưởng/i.test(l.location || "") && l.status !== "on_hold")
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
      .map(l => { const m = matById[l.material_id];
        return `<option value="${l.lot_id}">${lotCodePlain(l)}${m ? ` — ${esc(m.code)} ${esc(m.name)}` : ""} (${l.quantity}${l.uom})</option>`; }).join("") ||
      `<option value="">(không có lô nào ở kho phân xưởng)</option>`;
    const sortedPx = pxRequests.slice().sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    const pxRows = sortedPx.map(r => {
      const lot = allLots.find(l => l.lot_id === r.lot_id);
      const mat = lot ? matById[lot.material_id] : null;
      return `<tr>
        <td class="muted">${fmt(r.created_at)}</td>
        <td><code class="k">${esc(r.request_code)}</code></td>
        <td>${esc(mat ? mat.code : "—")}</td>
        <td class="muted">${lotCodeCellHtml(lot)}</td>
        <td>${r.quantity} ${esc(r.uom)}</td>
        <td class="muted">${esc(r.reason || "")}</td>
        <td>${badge(r.status)}</td></tr>`;
    }).join("") || `<tr><td colspan=7 class="muted">Chưa có đề nghị nào.</td></tr>`;
    const kcpxPendingPx = kcpxRequestsPx.filter(r => r.status === "pending").sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    const kcpxDonePx = kcpxRequestsPx.filter(r => r.status !== "pending").sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    const kcpxPendingRows = kcpxPendingPx.map(r => {
      const lot = lotByIdPxDc[r.lot_id];
      const mat = lot ? matById[lot.material_id] : null;
      const qcBlocked = lot && qcReqSetKcpx.has(lot.material_id) && lot.status === "on_hold";
      return `<tr>
        <td class="muted">${fmt(r.created_at)}</td>
        <td><code class="k">${esc(r.request_code)}</code></td>
        <td>${esc(mat ? mat.code : "—")}</td>
        <td>${esc(mat ? mat.name : "—")}</td>
        <td class="muted">${lotCodeCellHtml(lot)}</td>
        <td>${r.quantity} ${esc(r.uom)}</td>
        <td class="muted">${esc(r.created_by || "")}</td>
        <td>${sangNgangQcBadge(r, lotByIdPxDc, qcReqSetKcpx)}</td>
        ${canApproveKcpx ? `<td style="white-space:nowrap">
          <button class="btn sm" data-kcpxapprove="${esc(r.request_id)}" ${qcBlocked ? "disabled title=\"Đang chờ KCS duyệt chỉ tiêu chất lượng\"" : ""}>Duyệt</button>
          <button class="btn sm sec" data-kcpxreject="${esc(r.request_id)}">Từ chối</button></td>` : ""}</tr>`;
    }).join("") || `<tr><td colspan="${canApproveKcpx ? 9 : 8}" class="muted">Không có đề nghị nào đang chờ.</td></tr>`;
    const kcpxDoneRows = kcpxDonePx.map(r => {
      const lot = lotByIdPxDc[r.lot_id];
      const mat = lot ? matById[lot.material_id] : null;
      const wsloc = r.workshop_location_id ? workshopLocByIdPx[r.workshop_location_id] : null;
      const processedBy = r.status === "approved" ? r.approved_by : r.rejected_by;
      let actionCellKcpx = "";
      if (isAdminDc && r.status === "approved") {
        actionCellKcpx = r.reversed ? `<td class="muted">Đã hoàn tác</td>`
          : `<td><button class="btn sm sec" data-kcpxundo="${esc(r.request_id)}">Hoàn tác</button></td>`;
      } else if (isAdminDc) actionCellKcpx = "<td></td>";
      return `<tr>
        <td class="muted">${fmt(r.created_at)}</td>
        <td><code class="k">${esc(r.request_code)}</code></td>
        <td>${esc(mat ? mat.code : "—")}</td>
        <td>${esc(mat ? mat.name : "—")}</td>
        <td class="muted">${lotCodeCellHtml(lot)}</td>
        <td>${r.quantity} ${esc(r.uom)}</td>
        <td class="muted">${wsloc ? esc(wsloc.code) : "—"}</td>
        <td>${badge(r.status)}</td>
        <td class="muted">${esc(processedBy || "")}</td>
        ${actionCellKcpx}</tr>`;
    }).join("") || `<tr><td colspan="${isAdminDc ? 9 : 8}" class="muted">Chưa có đề nghị nào đã xử lý.</td></tr>`;
    body = `<div class="split">
      <div class="panel"><h2>Gửi đề nghị về Kho công ty</h2>
      <div class="muted" style="margin-bottom:6px">Gửi đề nghị điều chuyển 1 lô đang ở Kho phân xưởng về lại Kho công ty —
        chưa động tồn kho ngay, chỉ khi Thủ kho công ty duyệt lệnh mới thật sự chuyển.</div>
      ${canRequestPx
        ? `<div class="row"><div class="field"><label>Lô (đang ở kho phân xưởng)</label>
        <input id="dcpx_lot_q" placeholder="Tìm nhanh (gõ mã/tên vật tư)..." style="margin-bottom:2px"/>
        <select id="dcpx_lot">${workshopLotOpts}</select></div>
        <div class="field"><label>SL</label><input id="dcpx_qty" type="number" value="50"/></div>
        <div class="field" style="flex:1"><label>Lý do (tuỳ chọn)</label><input id="dcpx_reason" placeholder="(tuỳ chọn)"/></div>
        <button class="btn" id="dcpx_do" style="align-self:flex-end">Gửi đề nghị</button></div>`
        : '<div class="muted">Bạn không có quyền tạo đề nghị điều chuyển.</div>'}
      <input class="searchbox" data-tbl="t_dcpx" placeholder="Tìm mã đề nghị/vật tư/lô..." style="margin-top:12px"/>
      <div class="tablewrap" style="margin-top:6px"><table id="t_dcpx">
        <thead><tr><th>Ngày tạo</th><th>Số đề nghị</th><th>Vật tư</th><th>Lô</th><th>SL</th><th>Lý do</th><th>Trạng thái</th></tr></thead>
        <tbody>${pxRows}</tbody>
      </table></div>
      </div>

      <div class="panel"><h2>Nhận điều chuyển từ Kho công ty <span class="muted">(${kcpxPendingPx.length} đang chờ duyệt)</span></h2>
      <div class="muted" style="margin-bottom:6px">Kho công ty gửi đề nghị điều chuyển 1 lô đang có sẵn sang Kho phân xưởng — bấm "Duyệt"
        để thật sự nhận (bắt buộc chọn vị trí cất). Nếu vật tư có chỉ tiêu chất lượng bắt buộc, phải chờ KCS duyệt xong (hết "Đang chờ
        KCS duyệt") mới duyệt được.</div>
      <div class="tablewrap"><table id="t_kcpx_pending_px">
        <thead><tr><th>Ngày tạo</th><th>Số đề nghị</th><th>Mã VT</th><th>Tên vật tư</th><th>Lô</th><th>SL</th><th>Người tạo</th><th>Trạng thái QC</th>${canApproveKcpx ? "<th></th>" : ""}</tr></thead>
        <tbody>${kcpxPendingRows}</tbody>
      </table></div>
      <h4 style="margin-top:14px">Lịch sử đã xử lý <span class="muted">(${kcpxDonePx.length})</span></h4>
      <div class="tablewrap"><table id="t_kcpx_done_px">
        <thead><tr><th>Ngày tạo</th><th>Số đề nghị</th><th>Mã VT</th><th>Tên vật tư</th><th>Lô</th><th>SL</th><th>Vị trí cất</th><th>Trạng thái</th><th>Người xử lý</th>${isAdminDc ? "<th></th>" : ""}</tr></thead>
        <tbody>${kcpxDoneRows}</tbody>
      </table></div>
      </div></div>`;
  } else if (sec === "sangngang") {
    const [allLots, mats, sangNgangRequestsPx, qcReqIdsPx] = await Promise.all([GET("/lots"), GET("/materials"),
      GET("/warehouse/sang-ngang"), GET("/materials/qc-required")]);
    const matById = Object.fromEntries(mats.map(m => [m.material_id, m]));
    const lotByIdPx = Object.fromEntries(allLots.map(l => [l.lot_id, l]));
    const qcReqSetPx = new Set(qcReqIdsPx);
    const isAdminSngPx = CURRENT_USER && CURRENT_USER.role === "admin";
    const canApproveSangNgang = _hasPerm("warehouse.request");
    WH_CACHE.matById = matById;
    WH_CACHE.lotById = lotByIdPx;
    const sngPendingPx = sangNgangRequestsPx.filter(r => r.status === "pending").sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    const sngDonePx = sangNgangRequestsPx.filter(r => r.status !== "pending").sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    const sngPendingRows = sngPendingPx.map(r => {
      const lot = lotByIdPx[r.lot_id];
      const mat = lot ? matById[lot.material_id] : null;
      const qcBlocked = lot && qcReqSetPx.has(lot.material_id) && lot.status === "on_hold";
      return `<tr>
        <td class="muted">${fmt(r.created_at)}</td>
        <td><code class="k">${esc(r.request_code)}</code></td>
        <td>${esc(mat ? mat.code : "—")}</td>
        <td>${esc(mat ? mat.name : "—")}</td>
        <td class="muted">${lotCodeCellHtml(lot)}</td>
        <td>${r.quantity} ${esc(r.uom)}</td>
        <td class="muted">${esc(r.created_by || "")}</td>
        <td>${sangNgangQcBadge(r, lotByIdPx, qcReqSetPx)}</td>
        ${canApproveSangNgang ? `<td style="white-space:nowrap">
          <button class="btn sm" data-sngapprove="${esc(r.request_id)}" ${qcBlocked ? "disabled title=\"Đang chờ KCS duyệt chỉ tiêu chất lượng\"" : ""}>Duyệt</button>
          <button class="btn sm sec" data-sngreject="${esc(r.request_id)}">Từ chối</button></td>` : ""}</tr>`;
    }).join("") || `<tr><td colspan="${canApproveSangNgang ? 9 : 8}" class="muted">Không có đề nghị nào đang chờ.</td></tr>`;
    const sngDoneRows = sngDonePx.map(r => {
      const lot = lotByIdPx[r.lot_id];
      const mat = lot ? matById[lot.material_id] : null;
      const processedBy = r.status === "approved" ? r.approved_by : r.rejected_by;
      let actionCell = "";
      if (isAdminSngPx && r.status === "approved") {
        actionCell = r.reversed ? `<td class="muted">Đã hoàn tác</td>`
          : `<td><button class="btn sm sec" data-sngundo="${esc(r.request_id)}">Hoàn tác</button></td>`;
      } else if (isAdminSngPx) actionCell = "<td></td>";
      return `<tr>
        <td class="muted">${fmt(r.created_at)}</td>
        <td><code class="k">${esc(r.request_code)}</code></td>
        <td>${esc(mat ? mat.code : "—")}</td>
        <td>${esc(mat ? mat.name : "—")}</td>
        <td class="muted">${lotCodeCellHtml(lot)}</td>
        <td>${r.quantity} ${esc(r.uom)}</td>
        <td>${badge(r.status)}</td>
        <td class="muted">${esc(processedBy || "")}</td>
        ${actionCell}</tr>`;
    }).join("") || `<tr><td colspan="${isAdminSngPx ? 9 : 8}" class="muted">Chưa có đề nghị nào đã xử lý.</td></tr>`;
    body = `<div class="panel"><h2>Xuất sang ngang <span class="muted">(${sngPendingPx.length} đang chờ duyệt)</span></h2>
      <div class="muted" style="margin-bottom:6px">Vật tư do Kho công ty khai báo "Xuất sang ngang" (đã tăng tồn Kho công ty) — bấm "Duyệt"
        để thật sự nhận vào Kho phân xưởng. Nếu vật tư có chỉ tiêu chất lượng bắt buộc, phải chờ KCS duyệt xong (hết "Đang chờ KCS duyệt")
        mới duyệt được.</div>
      <div class="tablewrap"><table id="t_sng_pending_px">
        <thead><tr><th>Ngày tạo</th><th>Số đề nghị</th><th>Mã VT</th><th>Tên vật tư</th><th>Lô</th><th>SL</th><th>Người tạo</th><th>Trạng thái QC</th>${canApproveSangNgang ? "<th></th>" : ""}</tr></thead>
        <tbody>${sngPendingRows}</tbody>
      </table></div>
      <h4 style="margin-top:14px">Lịch sử đã xử lý <span class="muted">(${sngDonePx.length})</span></h4>
      <div class="tablewrap"><table id="t_sng_done_px">
        <thead><tr><th>Ngày tạo</th><th>Số đề nghị</th><th>Mã VT</th><th>Tên vật tư</th><th>Lô</th><th>SL</th><th>Trạng thái</th><th>Người xử lý</th>${isAdminSngPx ? "<th></th>" : ""}</tr></thead>
        <tbody>${sngDoneRows}</tbody>
      </table></div>
    </div>`;
  } else if (sec === "tudo") {
    const [allLots, mats, freeIssuesAll] = await Promise.all([GET("/lots"), GET("/materials"),
      GET("/warehouse/movements?movement_type=issue&mode=tu_do")]);
    const matById = Object.fromEntries(mats.map(m => [m.material_id, m]));
    const isAdminPx = CURRENT_USER && CURRENT_USER.role === "admin";
    const workshopLotOpts = allLots.filter(l => l.quantity > 0 && /phân xưởng/i.test(l.location || ""))
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
      .map(l => { const m = matById[l.material_id];
        return `<option value="${l.lot_id}" data-material="${esc(l.material_id || "")}">${lotCodePlain(l)}${m ? ` — ${esc(m.code)} ${esc(m.name)}` : ""} (${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})${l.status === "on_hold" ? " — CHỜ DUYỆT QC" : ""}</option>`; }).join("") ||
      `<option value="">(không có lô nào ở kho phân xưởng)</option>`;
    WH_CACHE.matById = matById;
    WH_CACHE.tu_do_px = freeIssuesAll.filter(m => /phân xưởng/i.test(m.location_from || ""));
    body = `<div class="panel"><h2>Xuất tự do (kho phân xưởng)</h2>
      <div class="muted" style="margin-bottom:6px">Xuất không theo phiếu đề nghị (vd. dùng nội bộ, thử nghiệm) trực tiếp từ lô đang ở
        kho phân xưởng. Lô đang "CHỜ DUYỆT QC" sẽ bị chặn xuất. Có thể "Hoàn lại" nếu xuất nhầm — vật tư trở về đúng lô, tránh thất thoát.</div>
      ${isAdminPx
        ? `<div class="row"><div class="field"><label>Lô</label><select id="xtpx_lot">${workshopLotOpts}</select></div>
        <div class="field"><label>SL</label><input id="xtpx_qty" type="number" value="50"/></div>
        <div class="field"><label>ĐVT</label><span id="xtpx_uom"></span></div>
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
  } else if (sec === "vitri") {
    const [allLotsVtPx, matsVtPx, wsLocsVtPx] = await Promise.all([GET("/lots"), GET("/materials"),
      GET("/warehouse/locations").catch(() => [])]);
    const matByIdVtPx = Object.fromEntries(matsVtPx.map(m => [m.material_id, m]));
    WH_CACHE.vtMatByIdPx = matByIdVtPx;
    WH_CACHE.vtLotsPx = allLotsVtPx.filter(l => /phân xưởng/i.test(l.location || "") && l.quantity > 0);
    const unplacedVtPx = WH_CACHE.vtLotsPx.filter(l => !l.workshop_location_id);
    const activeLocsVtPx = wsLocsVtPx.filter(l => l.active && (l.scope === "phan_xuong" || l.scope === "ca_hai"));
    const locOptsVtPx = activeLocsVtPx.map(l => `<option value="${esc(l.loc_id)}">${esc(l.code)} — ${esc(l.name)}</option>`).join("") ||
      `<option value="">(chưa khai báo vị trí kho phân xưởng — vào Danh mục để thêm)</option>`;
    body = `<div class="panel"><h2>🚚 Cất vào vị trí <span class="muted">(${unplacedVtPx.length})</span></h2>
      <div class="muted" style="margin-bottom:8px">Gán vị trí kho cho các lô Kho phân xưởng CHƯA có vị trí (lô đến từ Xuất sang ngang, Nhập tồn đầu, hoặc lô cũ trước khi khai danh mục vị trí) — chọn vị trí đích rồi tick các lô cần cất.</div>
      <div class="row"><div class="field"><label>Vị trí đích</label><select id="vtpx_to">${locOptsVtPx}</select></div></div>
      <input class="searchbox" data-tbl="t_vtpx_unplaced" placeholder="Tìm mã lô/vật tư..." style="margin-bottom:8px"/>
      <div class="tablewrap" style="margin-top:10px"><table id="t_vtpx_unplaced">
        <thead><tr><th></th><th>Lô</th><th>Vật tư</th><th>SL</th><th>Ngày nhập</th></tr></thead>
        <tbody>${unplacedVtPx.map(l => `<tr><td><input type="checkbox" data-vtpxu="${esc(l.lot_id)}"/></td>
          <td><code class="k">${lotCodeCellHtml(l)}</code></td>
          <td>${esc(matByIdVtPx[l.material_id] ? matByIdVtPx[l.material_id].name : "—")}</td>
          <td>${l.quantity} ${l.uom}</td><td class="muted">${fmt(l.created_at)}</td></tr>`).join("") ||
          `<tr><td colspan=5 class="muted">Không có lô nào chưa gán vị trí.</td></tr>`}</tbody>
      </table></div>
      <button class="btn" id="vtpx_place_submit" style="margin-top:10px">Cất vào vị trí</button>
    </div>
    <div class="panel"><h2>🔁 Chuyển vị trí trong kho</h2>
      <div class="muted" style="margin-bottom:8px">Chuyển các lô ĐÃ CẤT sang vị trí khác (VD sắp xếp lại kho) — chọn vị trí nguồn để xem các lô đang ở đó, chọn vị trí đích rồi tick lô cần chuyển.</div>
      <div class="row">
        <div class="field"><label>Vị trí nguồn</label><select id="vtpx_from"><option value="">(chọn vị trí nguồn)</option>${locOptsVtPx}</select></div>
        <div class="field"><label>Vị trí đích</label><select id="vtpx_to2">${locOptsVtPx}</select></div>
      </div>
      <div id="vtpx_move_wrap" class="muted" style="margin-top:10px">Chọn vị trí nguồn để xem các lô đang ở đó.</div>
      <button class="btn" id="vtpx_move_submit" style="margin-top:10px">Chuyển vị trí</button>
    </div>`;
  } else if (sec === "kk") {
    body = await renderStockCountSection("Kho phân xưởng");
  }
  $("view-warehouse_px").innerHTML = subnav("warehouse_px", sections, sec) + body;
  wireSubnav("warehouse_px");
  wireSearch();
  document.querySelectorAll("[data-lotqc]").forEach(b => b.onclick = () => openLotQcModal(b.dataset.lotqc, { editable: false }));
  if (sec === "kk") wireStockCountSection("warehouse_px");
  if (sec === "px") {
    $("px_loc").onchange = () => { TON_LOC.warehouse_px = $("px_loc").value; render("warehouse_px"); };
    // Mặc định hiện lô nhập GẦN NHẤT trước (cột "Ngày giờ nhập", đảo chiều) — mirror đúng cách
    // làm ở "Danh sách lô (FIFO)" bên Kho công ty, bấm lại tiêu đề cột để quay về thứ tự FIFO
    // (nhập trước lên đầu) khi cần chọn lô ưu tiên dùng/chuyển.
    if (!_pagerState.t_px) _pagerState.t_px = { page: 1, pageSize: 10, sortCol: 3, sortDir: -1 };
    wirePaginate("t_px", 10, { onFilter: (trs) => {
      const el = document.getElementById("px_total");
      if (el) el.innerHTML = `Tổng số lượng (theo bộ lọc đang áp dụng): ${sumTotalsHtml(trs)}`;
    } });
  }
  if (sec === "vitri") {
    wirePaginate("t_vtpx_unplaced", 10);
    const rebuildMoveTablePx = () => {
      const fromId = $("vtpx_from").value;
      if (!fromId) { $("vtpx_move_wrap").innerHTML = '<div class="muted">Chọn vị trí nguồn để xem các lô đang ở đó.</div>'; return; }
      const lotsAt = (WH_CACHE.vtLotsPx || []).filter(l => l.workshop_location_id === fromId);
      $("vtpx_move_wrap").innerHTML = `<div class="tablewrap"><table id="t_vtpx_move">
        <thead><tr><th></th><th>Lô</th><th>Vật tư</th><th>SL</th></tr></thead>
        <tbody>${lotsAt.map(l => `<tr><td><input type="checkbox" data-vtpxm="${esc(l.lot_id)}"/></td>
          <td><code class="k">${lotCodeCellHtml(l)}</code></td>
          <td>${esc((WH_CACHE.vtMatByIdPx[l.material_id] || {}).name || "—")}</td>
          <td>${l.quantity} ${l.uom}</td></tr>`).join("") ||
          `<tr><td colspan=4 class="muted">Không có lô nào ở vị trí này.</td></tr>`}</tbody>
      </table></div>`;
      wirePaginate("t_vtpx_move", 10);
    };
    if ($("vtpx_from")) $("vtpx_from").onchange = rebuildMoveTablePx;
    if ($("vtpx_place_submit")) $("vtpx_place_submit").onclick = () => guard(async () => {
      const toId = $("vtpx_to").value;
      if (!toId) throw new Error("Chọn vị trí đích.");
      const ids = Array.from(document.querySelectorAll("[data-vtpxu]:checked")).map(c => c.dataset.vtpxu);
      if (!ids.length) throw new Error("Chọn ít nhất 1 lô cần cất.");
      for (const id of ids) await POST(`/warehouse/lots/${id}/relocate-workshop`, { workshop_location_id: toId });
      toast(`Đã cất ${ids.length} lô vào vị trí`);
      render("warehouse_px");
    });
    if ($("vtpx_move_submit")) $("vtpx_move_submit").onclick = () => guard(async () => {
      const toId = $("vtpx_to2").value;
      if (!toId) throw new Error("Chọn vị trí đích.");
      const ids = Array.from(document.querySelectorAll("[data-vtpxm]:checked")).map(c => c.dataset.vtpxm);
      if (!ids.length) throw new Error("Chọn ít nhất 1 lô cần chuyển.");
      for (const id of ids) await POST(`/warehouse/lots/${id}/relocate-workshop`, { workshop_location_id: toId });
      toast(`Đã chuyển ${ids.length} lô sang vị trí mới`);
      render("warehouse_px");
    });
  }
  if (sec === "tondau") {
    wireSearchableSelect("obpx_mat_txt", "obpx_mat", WH_CACHE.matItemsPx, (item) => { $("obpx_uom").value = item.uom || ""; });
    if ($("obpx_do")) $("obpx_do").onclick = () => guard(async () => {
      const res = await POST("/warehouse/receive", { lot_code: $("obpx_code").value, material_id: $("obpx_mat").value,
        quantity: parseFloat($("obpx_qty").value), uom: $("obpx_uom").value, location: "Kho phân xưởng",
        expiry: $("obpx_exp").value || null, kcs_lot_no: $("obpx_kcs").value.trim() || null,
        supplier_lot: $("obpx_supplier_lot").value.trim() || null,
        reason: "Nhập tồn đầu", is_opening_balance: true });
      if (res.status === "on_hold") toast("Đã nhập tồn đầu — lô đang CHỜ khai báo & duyệt chỉ tiêu chất lượng", "err");
      else toast("Đã nhập tồn đầu tại Kho phân xưởng");
      render("warehouse_px");
    });
    if ($("obpx_import")) $("obpx_import").onclick = () => guard(async () => {
      const f = $("obpx_file").files[0];
      if (!f) throw new Error("Chọn file Excel trước.");
      const fd = new FormData();
      fd.append("file", f);
      fd.append("location", "Kho phân xưởng");
      const headers = {};
      if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
      const res = await fetch("/api/warehouse/opening-balance/import", { method: "POST", headers, body: fd });
      const result = await res.json();
      if (!res.ok) throw new Error(result && result.detail ? result.detail : "HTTP " + res.status);
      if (result.failed && result.failed.length) {
        alert(`Đã nhập ${result.created.length}/${result.total} dòng. ${result.failed.length} dòng lỗi:\n` +
          result.failed.map(x => `Dòng ${x.row}: ${x.reason}`).join("\n"));
      } else {
        toast(`Đã nhập tồn đầu từ Excel: ${result.created.length}/${result.total} dòng`);
      }
      render("warehouse_px");
    });
  }
  if (sec === "dieuchuyen") {
    wirePaginate("t_dcpx", 10);
    wirePaginate("t_kcpx_pending_px", 10);
    wirePaginate("t_kcpx_done_px", 10);
    wireSelectSearch("dcpx_lot", "dcpx_lot_q");
    if ($("dcpx_do")) $("dcpx_do").onclick = () => guard(async () => {
      if (!$("dcpx_lot").value) throw new Error("Không có lô nào đang ở kho phân xưởng để điều chuyển.");
      await POST("/warehouse/transfer-px-requests", { lot_id: $("dcpx_lot").value, quantity: parseFloat($("dcpx_qty").value),
        reason: $("dcpx_reason").value.trim() || null });
      toast("Đã gửi đề nghị điều chuyển"); render("warehouse_px");
    });
    document.querySelectorAll("[data-kcpxapprove]").forEach(b => b.onclick = () => {
      const requestId = b.dataset.kcpxapprove;
      const locs = WH_CACHE.workshopLocs || [];
      const opts = locs.map(l => `<option value="${esc(l.loc_id)}">${esc(l.code)} — ${esc(l.name)}</option>`).join("") ||
        `<option value="">(chưa khai báo vị trí kho phân xưởng — vào Danh mục để thêm)</option>`;
      modal(`<h3>Duyệt nhận điều chuyển từ Kho công ty</h3>
        <div class="muted" style="margin-bottom:10px">Chọn vị trí cất tại Kho phân xưởng cho lô này (bắt buộc).</div>
        <div class="field"><label>Vị trí cất *</label><select id="kcpxa_loc">${opts}</select></div>
        <button class="btn" id="kcpxa_save" style="margin-top:12px">Duyệt</button>`);
      $("kcpxa_save").onclick = () => guard(async () => {
        if (!$("kcpxa_loc").value) throw new Error("Chọn vị trí cất trước khi duyệt.");
        await POST(`/warehouse/transfer-kcpx-requests/${requestId}/approve`, { workshop_location_id: $("kcpxa_loc").value });
        closeModal(); toast("Đã duyệt — lô đã về Kho phân xưởng"); render("warehouse_px");
      });
    });
    document.querySelectorAll("[data-kcpxreject]").forEach(b => b.onclick = () => guard(async () => {
      const reason = prompt("Lý do từ chối (tuỳ chọn):") || null;
      await POST(`/warehouse/transfer-kcpx-requests/${b.dataset.kcpxreject}/reject`, { reason });
      toast("Đã từ chối đề nghị"); render("warehouse_px");
    }));
    document.querySelectorAll("[data-kcpxundo]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Hoàn tác đề nghị đã duyệt này? Lô sẽ trả về lại Kho công ty.")) return;
      await POST(`/warehouse/transfer-kcpx-requests/${b.dataset.kcpxundo}/undo`, {});
      toast("Đã hoàn tác điều chuyển"); render("warehouse_px");
    }));
  }
  if (sec === "sangngang") {
    wirePaginate("t_sng_pending_px", 10);
    wirePaginate("t_sng_done_px", 10);
    document.querySelectorAll("[data-sngapprove]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Duyệt đề nghị xuất sang ngang này? Lô sẽ thật sự chuyển vào Kho phân xưởng ngay.")) return;
      await POST(`/warehouse/sang-ngang/${b.dataset.sngapprove}/approve`, {});
      toast("Đã duyệt — lô đã về Kho phân xưởng"); render("warehouse_px");
    }));
    document.querySelectorAll("[data-sngreject]").forEach(b => b.onclick = () => guard(async () => {
      const reason = prompt("Lý do từ chối (tuỳ chọn):") || null;
      await POST(`/warehouse/sang-ngang/${b.dataset.sngreject}/reject`, { reason });
      toast("Đã từ chối đề nghị"); render("warehouse_px");
    }));
    document.querySelectorAll("[data-sngundo]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Hoàn tác đề nghị đã duyệt này? Lô sẽ trả về lại Kho công ty.")) return;
      await POST(`/warehouse/sang-ngang/${b.dataset.sngundo}/undo`, {});
      toast("Đã hoàn tác xuất sang ngang"); render("warehouse_px");
    }));
  }
  if (sec === "tudo") {
    if ($("xtpx_lot")) wireLotAltUom("xtpx_lot", "xtpx_uom", matById);
    if ($("xtpx_do")) $("xtpx_do").onclick = () => guard(async () => {
      const qty = lotAltUomQty("xtpx_lot", "xtpx_uom", parseFloat($("xtpx_qty").value), matById);
      await POST("/warehouse/issue", { lot_id: $("xtpx_lot").value, quantity: qty,
        mode: "tu_do", reason: $("xtpx_reason").value.trim() || null });
      toast("Đã xuất tự do"); render("warehouse_px");
    });
    wireMovementHistoryBlock("tu_do_px");
  }
  if (sec === "nvlhist") wirePaginate("t_nvlhist", 10);
  if (sec === "req") {
    wireCartPanel();
    wireRequestsHistoryBlock();
    document.querySelectorAll("#stk_table [data-pickmat]").forEach(b => b.onclick = () => {
      const row = b.closest("tr");
      const qty = parseFloat(row.querySelector(".stk-qty").value);
      if (!qty || qty <= 0) { toast("Nhập số lượng muốn nhận trước khi thêm.", "err"); return; }
      const mat = REQ_CACHE.matById[b.dataset.pickmat];
      // Chỉ chọn vật tư + số lượng — KHÔNG gắn lot_id cụ thể, để thủ kho Kho công ty tự
      // quyết định xuất lô nào (mặc định FIFO) lúc duyệt phiếu.
      REQUEST_CART.push({ material_id: b.dataset.pickmat, material_code: mat ? mat.code : b.dataset.pickmat,
        lot_id: null, lot_code: null,
        quantity: qty, uom: b.dataset.pickuom });
      toast(`Đã thêm vào đề nghị (${REQUEST_CART.length} dòng) — xem ở bảng phía trên`);
      refreshCartPanel();
    });
    wirePaginate("stk_table", 10);
  }
};

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
  const matByIdKk = Object.fromEntries((CACHE.materials || []).map(m => [m.material_id, m]));
  modal(`<h3>Phiếu kiểm kê ${esc(c.count_code)} <span class="muted">(${esc(c.location || "Toàn bộ")})</span></h3>
    <div class="muted" style="margin-bottom:8px">${isDraft
      ? "Điền số lượng đếm thực tế cho từng lô, bấm Lưu số liệu, rồi Chốt phiếu để tự động điều chỉnh lệch."
      : `Đã chốt bởi ${esc(c.posted_by || "")} lúc ${fmt(c.posted_at)}.${c.approved_by ? ` Đã duyệt bởi ${esc(c.approved_by)} lúc ${fmt(c.approved_at)}.` : ""}`}</div>
    <div class="tablewrap"><table>
      <thead><tr><th>Vật tư</th><th>Lô</th><th>Vị trí</th><th>Tồn hệ thống</th><th>Đếm thực tế</th><th>ĐVT</th><th>Lệch</th></tr></thead>
      <tbody>${c.lines.map(l => `<tr data-lineid="${esc(l.line_id)}" data-material="${esc(l.material_id || "")}">
        <td>${esc(l.material_code || l.material_id)}</td>
        <td class="muted">${esc(l.lot_code || "")}</td>
        <td class="muted">${esc(l.location || "")}</td>
        <td>${l.system_qty} ${esc(l.uom)}</td>
        <td>${isDraft ? `<input type="number" step="0.01" class="kkl_counted" style="width:90px" value="${l.counted_qty ?? ""}"/>`
          : (l.counted_qty ?? "—")}</td>
        <td>${isDraft ? altUomFieldHtml(matByIdKk[l.material_id], `class="kkl_uom"`, 60) : esc(l.uom)}</td>
        <td class="muted">${l.variance == null ? "—" : (l.variance > 0 ? "+" : "") + l.variance}</td>
        </tr>`).join("")}</tbody>
    </table></div>
    ${isDraft ? `<div style="margin-top:12px;display:flex;gap:8px">
      <button class="btn sec" id="kk_save">Lưu số liệu</button>
      <button class="btn" id="kk_post">Chốt phiếu</button>
    </div>` : ""}`);
  if (isDraft) {
    $("kk_save").onclick = () => guard(async () => {
      const lines = Array.from(document.querySelectorAll("[data-lineid]")).map(tr => {
        const raw = tr.querySelector(".kkl_counted").value;
        const mat = matByIdKk[tr.dataset.material];
        const uomSel = tr.querySelector(".kkl_uom");
        return { line_id: tr.dataset.lineid,
          counted_qty: raw === "" ? null : altUomToBaseQty(mat, parseFloat(raw), uomSel ? uomSel.value : null) };
      });
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
    <td>${mat ? `<code class="k">${esc(mat.code)}</code> ${esc(mat.name)}` : esc(m.material_id || "—")}</td>
    <td class="muted">${esc(m.lot_code || "")}</td>
    <td>${m.quantity} ${esc(m.uom)}</td>
    <td class="muted">${esc(m.location_from || "—")} → ${esc(m.location_to || "—")}</td>
    <td class="muted">${esc(m.reason || "")}</td>
    <td class="muted">${esc(m.actor || "")}</td>
    ${undoCell}</tr>`;
}

// ---- Điều chuyển kho công ty, chiều 1: Kho phân xưởng → Kho công ty (duyệt trước khi chuyển) ----
function transferPxRequestRowHtml(r, matById, lotById, canApprove, isAdmin) {
  const lot = lotById[r.lot_id];
  const mat = lot ? matById[lot.material_id] : null;
  const actionCell = canApprove ? `<td style="white-space:nowrap">
      <button class="btn sm" data-pxapprove="${esc(r.request_id)}">Duyệt</button>
      <button class="btn sm sec" data-pxreject="${esc(r.request_id)}">Từ chối</button></td>` : "";
  return `<tr>
    <td class="muted">${fmt(r.created_at)}</td>
    <td><code class="k">${esc(r.request_code)}</code></td>
    <td>${esc(mat ? mat.code : "—")}</td>
    <td class="muted">${lotCodeCellHtml(lot)}</td>
    <td>${r.quantity} ${esc(r.uom)}</td>
    <td class="muted">${esc(r.reason || "")}</td>
    <td class="muted">${esc(r.created_by || "")}</td>
    ${actionCell}</tr>`;
}

function transferPxRequestHistoryRowHtml(r, matById, lotById, isAdmin) {
  const lot = lotById[r.lot_id];
  const mat = lot ? matById[lot.material_id] : null;
  const processedBy = r.status === "approved" ? r.approved_by : r.rejected_by;
  let actionCell = "";
  if (isAdmin && r.status === "approved") {
    actionCell = r.reversed
      ? `<td class="muted">Đã hoàn tác</td>`
      : `<td><button class="btn sm sec" data-pxundo="${esc(r.request_id)}">Hoàn tác</button></td>`;
  } else if (isAdmin) {
    actionCell = "<td></td>";
  }
  return `<tr>
    <td class="muted">${fmt(r.created_at)}</td>
    <td><code class="k">${esc(r.request_code)}</code></td>
    <td>${esc(mat ? mat.code : "—")}</td>
    <td class="muted">${lotCodeCellHtml(lot)}</td>
    <td>${r.quantity} ${esc(r.uom)}</td>
    <td class="muted">${esc(r.reason || "")}</td>
    <td>${badge(r.status)}</td>
    <td class="muted">${esc(processedBy || "")}</td>
    ${actionCell}</tr>`;
}

// ---- Xuất sang ngang: hàng cập Kho công ty nhưng đích thực sự là Kho phân xưởng ----
function sangNgangQcBadge(r, lotById, qcReqSet) {
  const lot = lotById[r.lot_id];
  if (!lot || !qcReqSet.has(lot.material_id)) return "";
  return lot.status === "on_hold"
    ? `<span class="badge on_hold">Đang chờ KCS duyệt</span>`
    : `<span class="badge approved">KCS đã duyệt</span>`;
}

function sangNgangEditDelCell(r) {
  // Chỉ cho Sửa/Xóa khi CHƯA được Kho phân xưởng duyệt (pending hoặc rejected — can_edit từ
  // backend, xem services/warehouse.py::update_sang_ngang/delete_sang_ngang) — đã duyệt thì lô
  // thật sự chuyển sang Kho phân xưởng rồi, không còn "sửa nhập kho" an toàn nữa.
  if (!r.can_edit) return "<td></td>";
  // "Gửi lại" chỉ có ý nghĩa khi đã bị từ chối — đưa đề nghị về "pending" để phân xưởng duyệt
  // lại (VD sau khi đã Sửa số lượng/lý do sai), xem services/warehouse.py::resubmit_sang_ngang.
  const resubmitBtn = r.status === "rejected"
    ? `<button class="btn sm" data-sngresubmit="${esc(r.request_id)}">Gửi lại</button> ` : "";
  return `<td style="white-space:nowrap">${resubmitBtn}<button class="btn sm sec" data-sngedit="${esc(r.request_id)}">Sửa</button>
    <button class="btn sm sec" data-sngdel="${esc(r.request_id)}" style="color:var(--red)">Xóa</button></td>`;
}

function sangNgangKcRowHtml(r, matById, lotById, qcReqSet) {
  const lot = lotById[r.lot_id];
  const mat = lot ? matById[lot.material_id] : null;
  return `<tr>
    <td class="muted">${fmt(r.created_at)}</td>
    <td><code class="k">${esc(r.request_code)}</code></td>
    <td>${esc(mat ? mat.code : "—")}</td>
    <td>${esc(mat ? mat.name : "—")}</td>
    <td class="muted">${lotCodeCellHtml(lot)}</td>
    <td>${r.quantity} ${esc(r.uom)}</td>
    <td>${sangNgangQcBadge(r, lotById, qcReqSet)}</td>
    ${sangNgangEditDelCell(r)}</tr>`;
}

// ---- Điều chuyển kho công ty, chiều 3: Kho công ty → Kho phân xưởng (lô đang có sẵn) ----
function transferKcPxKcRowHtml(r, matById, lotById, qcReqSet) {
  const lot = lotById[r.lot_id];
  const mat = lot ? matById[lot.material_id] : null;
  return `<tr>
    <td class="muted">${fmt(r.created_at)}</td>
    <td><code class="k">${esc(r.request_code)}</code></td>
    <td>${esc(mat ? mat.code : "—")}</td>
    <td>${esc(mat ? mat.name : "—")}</td>
    <td class="muted">${lotCodeCellHtml(lot)}</td>
    <td>${r.quantity} ${esc(r.uom)}</td>
    <td>${sangNgangQcBadge(r, lotById, qcReqSet)}</td></tr>`;
}

function transferKcPxHistoryRowHtml(r, matById, lotById) {
  const lot = lotById[r.lot_id];
  const mat = lot ? matById[lot.material_id] : null;
  const processedBy = r.status === "approved" ? r.approved_by : r.rejected_by;
  return `<tr>
    <td class="muted">${fmt(r.created_at)}</td>
    <td><code class="k">${esc(r.request_code)}</code></td>
    <td>${esc(mat ? mat.code : "—")}</td>
    <td>${esc(mat ? mat.name : "—")}</td>
    <td class="muted">${lotCodeCellHtml(lot)}</td>
    <td>${r.quantity} ${esc(r.uom)}</td>
    <td>${badge(r.status)}${r.reversed ? ' <span class="muted" style="font-size:11px">(đã hoàn tác)</span>' : ""}</td>
    <td class="muted">${esc(processedBy || "")}</td></tr>`;
}

function sangNgangHistoryRowHtml(r, matById, lotById) {
  const lot = lotById[r.lot_id];
  const mat = lot ? matById[lot.material_id] : null;
  const processedBy = r.status === "approved" ? r.approved_by : r.rejected_by;
  return `<tr>
    <td class="muted">${fmt(r.created_at)}</td>
    <td><code class="k">${esc(r.request_code)}</code></td>
    <td>${esc(mat ? mat.code : "—")}</td>
    <td>${esc(mat ? mat.name : "—")}</td>
    <td class="muted">${lotCodeCellHtml(lot)}</td>
    <td>${r.quantity} ${esc(r.uom)}</td>
    <td>${badge(r.status)}${r.reversed ? ' <span class="muted" style="font-size:11px">(đã hoàn tác)</span>' : ""}</td>
    <td class="muted">${esc(processedBy || "")}</td>
    ${sangNgangEditDelCell(r)}</tr>`;
}

// ---- Điều chuyển kho công ty, chiều 2: Kho công ty → Nhà máy khác (xuất ngay, duyệt sau) ----
function factoryTransferRowHtml(m) {
  const mat = m.material_id ? WH_CACHE.matById[m.material_id] : null;
  const factory = (WH_CACHE.factoryById || {})[m.destination_factory_id];
  const isAdmin = CURRENT_USER && CURRENT_USER.role === "admin";
  const canApproveFactory = _hasPerm("warehouse.transfer_approve_factory");
  const approveCell = m.approved_by ? `<td class="muted">${esc(m.approved_by)}</td>` :
    canApproveFactory ? `<td><button class="btn sm sec" data-approvefactory="${esc(m.movement_id)}">Duyệt</button></td>` :
    `<td class="muted">Chưa duyệt</td>`;
  const undoCell = m.reversed ? '<td><span class="muted">Đã hoàn lại</span></td>' :
    (m.approved_by && !isAdmin) ? '<td class="muted">—</td>' :
    `<td><button class="btn sm sec" data-undoissue="${esc(m.movement_id)}">Hoàn lại</button></td>`;
  return `<tr>
    <td class="muted">${fmt(m.ts)}</td>
    <td>${mat ? `<code class="k">${esc(mat.code)}</code> ${esc(mat.name)}` : esc(m.material_id || "—")}</td>
    <td class="muted">${esc(m.lot_code || "")}</td>
    <td>${m.quantity} ${esc(m.uom)}</td>
    <td class="muted">${esc(factory ? factory.name : m.destination_factory_id || "—")}</td>
    <td class="muted">${esc(m.reason || "")}</td>
    <td class="muted">${esc(m.actor || "")}</td>
    ${approveCell}
    ${undoCell}</tr>`;
}

const WH_HIST_PAGE = 10;
// Toàn bộ giao dịch đã fetch (tối đa 200 dòng/backend) + số dòng đang hiển thị mỗi bảng —
// "Tải thêm" chỉ lộ thêm dữ liệu đã có sẵn trong bộ nhớ, không gọi lại API.
const WH_CACHE = { matById: {} };
const WH_HIST_VISIBLE = { tu_do: WH_HIST_PAGE, tu_do_px: WH_HIST_PAGE, dieu_chuyen_nha_may: WH_HIST_PAGE, tra_ncc: WH_HIST_PAGE, xuat_theo_de_nghi: WH_HIST_PAGE };
const WH_HIST_TITLE = { tu_do: "Lịch sử xuất tự do", tu_do_px: "Lịch sử xuất tự do (phân xưởng)", dieu_chuyen_nha_may: "Lịch sử điều chuyển sang nhà máy khác",
  tra_ncc: "Lịch sử trả nhà cung cấp", xuat_theo_de_nghi: "Sổ xuất theo đề nghị (tất cả phiếu)" };
const WH_HIST_UNDO = { tu_do: true, tu_do_px: true, dieu_chuyen_nha_may: true, tra_ncc: false, xuat_theo_de_nghi: false };
// "tu_do" (Kho công ty) và "tu_do_px" (Kho phân xưởng) dùng chung 1 endpoint/mode ở backend
// (StockMovement.mode="tu_do"), chỉ khác view nào gọi render() lại sau khi Hoàn tác.
const WH_HIST_VIEW = { tu_do: "warehouse_kc", tu_do_px: "warehouse_px" };
// Nút "Xóa lịch sử" (chỉ admin) — mỗi key trỏ tới 1 endpoint xóa riêng ở backend (xem
// services/warehouse.py::delete_free_issue_history/delete_request_history). Chỉ xóa được
// dữ liệu THẬT SỰ là lịch sử (không đụng NVL đã dùng cho mẻ sản xuất/phiếu còn đang chờ).
const WH_HIST_DELETE = {
  tu_do: { url: "/warehouse/movements/free-issue-history?workshop=false",
    confirm: "Xóa TOÀN BỘ lịch sử xuất tự do (Kho công ty)? Các dòng NVL đã dùng thật cho mẻ nấu/lọc/chiết sẽ được giữ lại, không mất. Không thể hoàn tác." },
  tu_do_px: { url: "/warehouse/movements/free-issue-history?workshop=true",
    confirm: "Xóa TOÀN BỘ lịch sử xuất tự do (Kho phân xưởng)? Các dòng NVL đã dùng thật cho mẻ nấu/lọc/chiết sẽ được giữ lại, không mất. Không thể hoàn tác." },
  xuat_theo_de_nghi: { url: "/warehouse/requests-history",
    confirm: "Xóa TOÀN BỘ sổ xuất theo đề nghị đã xử lý xong? Phiếu còn dòng đang chờ sẽ không bị ảnh hưởng. Không thể hoàn tác." },
};

// "xuat_theo_de_nghi" hiển thị dạng thẻ phiếu accordion — giống hệt "Đề nghị nhận kho"
// (requestBlockHtml/requestLineRowHtml) thay vì bảng giao dịch phẳng, để mỗi dòng đã xuất
// có nút "Hoàn tác" ngay tại chỗ (dùng chung undo_fulfill_line, không phải undo-issue chung).
function movementHistoryBlockHtml(key) {
  const all = WH_CACHE[key] || [];
  const isAdmin = CURRENT_USER && CURRENT_USER.role === "admin";
  const delBtn = isAdmin && WH_HIST_DELETE[key]
    ? ` <button class="btn sm sec" data-delhist="${key}" style="color:var(--red)">🗑️ Xóa lịch sử</button>` : "";
  if (key === "xuat_theo_de_nghi") {
    const visible = all.slice(0, WH_HIST_VISIBLE[key] || WH_HIST_PAGE);
    const moreBtn = all.length > visible.length
      ? `<button class="btn sm sec" data-loadmorehist="${key}" style="margin-top:6px">Tải thêm (còn ${all.length - visible.length})</button>` : "";
    return `<div id="wh_hist_${key}" style="margin-top:14px">
      <h4>${esc(WH_HIST_TITLE[key])} <span class="muted">(${visible.length}/${all.length} phiếu)</span>${delBtn}</h4>
      ${visible.map(r => requestBlockHtml(r, WH_CACHE.matById, WH_CACHE.lotById, WH_CACHE.canFulfill, false, WH_CACHE.allLots)).join("") ||
        '<div class="muted">Chưa có phiếu nào đã xuất.</div>'}
      ${moreBtn}
    </div>`;
  }
  if (key === "dieu_chuyen_nha_may") {
    const visible = all.slice(0, WH_HIST_VISIBLE[key] || WH_HIST_PAGE);
    const moreBtn = all.length > visible.length
      ? `<button class="btn sm sec" data-loadmorehist="${key}" style="margin-top:6px">Tải thêm (còn ${all.length - visible.length})</button>` : "";
    return `<div class="tablewrap" id="wh_hist_${key}" style="margin-top:14px">
      <h4>${esc(WH_HIST_TITLE[key])} <span class="muted">(${visible.length}/${all.length})</span>${delBtn}</h4>
      <table>
        <thead><tr><th>Thời gian</th><th>Vật tư</th><th>Lô</th><th>SL</th><th>Nhà máy đến</th><th>Lý do</th><th>Người thực hiện</th><th>Duyệt</th><th></th></tr></thead>
        <tbody>${visible.map(m => factoryTransferRowHtml(m)).join("") ||
          `<tr><td colspan=9 class="muted">Chưa có giao dịch nào.</td></tr>`}</tbody>
      </table>
      ${moreBtn}
    </div>`;
  }
  const showUndo = WH_HIST_UNDO[key];
  const visible = all.slice(0, WH_HIST_VISIBLE[key] || WH_HIST_PAGE);
  const cols = 7 + (showUndo ? 1 : 0);
  const moreBtn = all.length > visible.length
    ? `<button class="btn sm sec" data-loadmorehist="${key}" style="margin-top:6px">Tải thêm (còn ${all.length - visible.length})</button>` : "";
  const tblId = `wh_histtbl_${key}`;
  return `<div class="tablewrap" id="wh_hist_${key}" style="margin-top:14px">
    <h4>${esc(WH_HIST_TITLE[key])} <span class="muted">(${visible.length}/${all.length})</span>${delBtn}</h4>
    <input class="searchbox" data-tbl="${tblId}" placeholder="Tìm mã lô/vật tư/người thực hiện..." style="margin-bottom:6px"/>
    <table id="${tblId}">
      <thead><tr><th>Thời gian</th><th>Vật tư</th><th>Lô</th><th>SL</th><th>Từ → Đến</th><th>Lý do</th><th>Người thực hiện</th>${showUndo ? "<th></th>" : ""}</tr></thead>
      <tbody>${visible.map(m => movementRowHtml(m, WH_CACHE.matById, showUndo)).join("") ||
        `<tr><td colspan=${cols} class="muted">Chưa có giao dịch nào.</td></tr>`}</tbody>
    </table>
    ${moreBtn}
  </div>`;
}

function wireMovementHistoryBlock(key) {
  wireSearch();
  const btn = document.querySelector(`[data-loadmorehist="${key}"]`);
  if (btn) btn.onclick = () => { WH_HIST_VISIBLE[key] = (WH_HIST_VISIBLE[key] || WH_HIST_PAGE) + WH_HIST_PAGE; refreshMovementHistoryBlock(key); };
  const delBtn = document.querySelector(`#wh_hist_${key} [data-delhist]`);
  if (delBtn) delBtn.onclick = () => guard(async () => {
    if (!confirm(WH_HIST_DELETE[key].confirm)) return;
    const res = await DELETE(WH_HIST_DELETE[key].url);
    toast(`Đã xóa ${res.deleted} dòng lịch sử`);
    render(WH_HIST_VIEW[key] || "warehouse_kc");
  });
  if (key === "xuat_theo_de_nghi") { wireRequestBlockActions(); return; }
  if (WH_HIST_UNDO[key]) {
    document.querySelectorAll(`#wh_hist_${key} [data-undoissue]`).forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Hoàn lại giao dịch xuất tự do này? Vật tư sẽ trở về lại lô.")) return;
      await POST(`/warehouse/movements/${b.dataset.undoissue}/undo-issue`, {});
      toast("Đã hoàn lại"); render(WH_HIST_VIEW[key] || "warehouse_kc");
    }));
  }
  if (key === "dieu_chuyen_nha_may") {
    document.querySelectorAll(`#wh_hist_${key} [data-approvefactory]`).forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Duyệt giao dịch điều chuyển sang nhà máy khác này? Sau khi duyệt, chỉ ADMIN mới hoàn tác được.")) return;
      await POST(`/warehouse/movements/${b.dataset.approvefactory}/approve-factory`, {});
      toast("Đã duyệt điều chuyển sang nhà máy khác"); render(WH_HIST_VIEW[key] || "warehouse_kc");
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

// Lọc danh sách Kho thành phẩm (WMS) theo phạm vi được phân của user hiện tại
// (CURRENT_USER.wms_warehouse_scope — admin/"*" = không lọc) — dùng cho mọi picker chọn kho
// (Xuất kho/Điều chuyển/Cất vào vị trí/Nhập kho) để tránh chọn nhầm kho ngoài phạm vi (BE vẫn tự
// chặn nếu ai đó cố gọi thẳng API, xem services/wms.py::_assert_wh_scope).
function myAllowedWarehouses(allWarehouses) {
  const scope = CURRENT_USER && CURRENT_USER.wms_warehouse_scope;
  if (!CURRENT_USER || CURRENT_USER.role === "admin" || !scope || scope === "*") return allWarehouses;
  const allowed = new Set(String(scope).split(",").map(s => s.trim()).filter(Boolean));
  return allWarehouses.filter(w => allowed.has(w.code));
}
// Ngược lại myAllowedLocations — dùng riêng cho "Vị trí đích" của Điều chuyển (liên kho): tài
// khoản bị giới hạn kho chỉ điều chuyển ĐẾN kho NGOÀI phạm vi của mình (điều chuyển về chính
// kho mình quản lý là vô nghĩa, xem services/wms.py::create_transfer) — admin/không giới hạn
// vẫn thấy toàn bộ như myAllowedLocations.
function otherWarehouseLocations(allLocations) {
  const active = allLocations.filter(l => l.active);
  const scope = CURRENT_USER && CURRENT_USER.wms_warehouse_scope;
  if (!CURRENT_USER || CURRENT_USER.role === "admin" || !scope || scope === "*") return active;
  const allowed = new Set(String(scope).split(",").map(s => s.trim()).filter(Boolean));
  return active.filter(l => !allowed.has(l.warehouse_code));
}
function isWhScopeRestricted() {
  const scope = CURRENT_USER && CURRENT_USER.wms_warehouse_scope;
  return !!(CURRENT_USER && CURRENT_USER.role !== "admin" && scope && scope !== "*");
}
// Mirror myAllowedWarehouses nhưng lọc trực tiếp danh sách WmsLocation (GET /wms/locations) theo
// warehouse_code — dùng cho các picker chọn THẲNG vị trí (Nhập kho/Cất vào vị trí/Điều chuyển).
function myAllowedLocations(allLocations) {
  const active = allLocations.filter(l => l.active);
  const scope = CURRENT_USER && CURRENT_USER.wms_warehouse_scope;
  if (!CURRENT_USER || CURRENT_USER.role === "admin" || !scope || scope === "*") return active;
  const allowed = new Set(String(scope).split(",").map(s => s.trim()).filter(Boolean));
  return active.filter(l => allowed.has(l.warehouse_code));
}
// Kiểm tra 1 mã kho (warehouse_code) đơn lẻ có nằm trong phạm vi được phân hay không — dùng khi
// lọc theo từng dòng thay vì cả mảng (VD picker Điều chuyển lấy warehouse_code từ vị trí lô hàng).
function isWarehouseAllowed(warehouseCode) {
  const scope = CURRENT_USER && CURRENT_USER.wms_warehouse_scope;
  if (!CURRENT_USER || CURRENT_USER.role === "admin" || !scope || scope === "*") return true;
  const allowed = new Set(String(scope).split(",").map(s => s.trim()).filter(Boolean));
  return allowed.has(warehouseCode);
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

let REQUEST_CART = [];   // {material_id, material_code, lot_id, lot_code, quantity, uom,
                          //  group_code?, group_name?, group_members?} — nhiều dòng, gửi 1 lần.
                          // group_code/group_name/group_members chỉ có ở dòng được "Nạp vật tư từ lệnh"
                          // đưa lên từ 1 Nhóm vật tư thay thế — mỗi mã thành viên thành 1 dòng riêng,
                          // thủ kho tự xoá bớt chỉ giữ đúng 1 mã muốn xuất (xem cartPanelHtml).
let REQUEST_SOURCE = null;   // {type: "brew_order"|"filter_master_order", id, label} — tuỳ chọn, chỉ để tham chiếu/báo cáo

const REQ_STATUS_BADGE = { pending: "on_hold", fulfilled: "available", rejected: "obsolete", cancelled: "obsolete" };

// Mã vật tư không đổi, chỉ số lô khác nhau — so lô đang chọn với lô cũ nhất hiện có (FIFO)
// của đúng vật tư đó để cảnh báo nếu chọn nhầm lô không phải lô cũ nhất.
function fifoOldestLot(materialId, allLots) {
  const candidates = allLots.filter(l => l.material_id === materialId && l.quantity > 0 && !/phân xưởng/i.test(l.location || ""))
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  return candidates[0] || null;
}
// Tồn kho THỰC TẾ khả dụng tại Kho công ty của 1 vật tư — chỉ tính lô status "available"/
// "released" (mirror LotStatus ở backend/app/common.py + services/warehouse.py::material_fifo_detail),
// KHÔNG tính lô đang "on_hold" (chờ QC duyệt) hay đã consumed/scrapped — đây là số thực sự có thể
// xuất ngay, dùng để chặn tạo đề nghị vượt quá tồn (xem wireCartPanel::rq_submit/rq_add).
function materialAvailableCompanyQty(materialId, allLots) {
  return allLots.filter(l => l.material_id === materialId && !/phân xưởng/i.test(l.location || "") &&
      (l.status === "available" || l.status === "released"))
    .reduce((sum, l) => sum + l.quantity, 0);
}
// Tồn đang chờ QC duyệt (status "on_hold") tại Kho công ty — CHƯA được tính vào tồn khả dụng ở
// trên, chỉ hiển thị để thủ kho/người đề nghị biết vì sao tồn thực tế thấp hơn tổng nhập kho.
function materialPendingQcCompanyQty(materialId, allLots) {
  return allLots.filter(l => l.material_id === materialId && !/phân xưởng/i.test(l.location || "") &&
      l.status === "on_hold")
    .reduce((sum, l) => sum + l.quantity, 0);
}
// Tồn đang có sẵn tại Kho phân xưởng — chỉ để THAM KHẢO (biết xưởng còn sẵn bao nhiêu trước khi
// xin thêm từ Kho công ty), KHÔNG dùng để chặn số lượng đề nghị (việc đó vẫn dựa vào tồn Kho
// công ty, xem materialAvailableCompanyQty).
function materialWorkshopQty(materialId, allLots) {
  return allLots.filter(l => l.material_id === materialId && /phân xưởng/i.test(l.location || "") &&
      (l.status === "available" || l.status === "released"))
    .reduce((sum, l) => sum + l.quantity, 0);
}

function requestFifoBadgeHtml(materialId, lotId, allLots) {
  if (!lotId) return '<span class="muted">(chưa chọn — theo FIFO lúc xuất)</span>';
  const lot = allLots.find(l => l.lot_id === lotId);
  if (!lot) return "—";
  const oldest = fifoOldestLot(materialId, allLots);
  return (oldest && oldest.lot_id === lotId)
    ? '<span class="badge available">✓ Lô cũ nhất (FIFO)</span>'
    : `<span class="badge on_hold" title="Còn lô cũ hơn: ${esc(oldest ? oldest.lot_code : "")} (${oldest ? fmt(oldest.created_at) : ""})">⚠ Không phải lô cũ nhất</span>`;
}
// So sánh FIFO GIỮA CÁC MÃ THÀNH VIÊN của 1 Nhóm vật tư thay thế (khác requestFifoBadgeHtml —
// hàm đó so 1 mã với chính nó qua các lô; hàm này so NHIỀU MÃ khác nhau với nhau) — dùng khi
// "Nạp vật tư từ lệnh" đưa thẳng từng mã thành viên lên giỏ, để thủ kho biết ngay mã nào đang
// tồn lâu nhất mà không phải tự tra từng mã (xem wireCartPanel::rq_srcload).
// Mã thành viên đang có lô nhập sớm nhất trong 1 Nhóm vật tư thay thế (null nếu cả nhóm
// không còn tồn Kho công ty) — dùng chung cho cả hiển thị badge và cảnh báo lúc gửi đề nghị
// (xem groupMemberFifoBadgeHtml + wireCartPanel::rq_submit).
function groupFifoBestMaterialId(memberIds, allLots) {
  const withStock = (memberIds || []).map(mid => ({ mid, oldest: fifoOldestLot(mid, allLots) })).filter(x => x.oldest);
  if (!withStock.length) return null;
  withStock.sort((a, b) => new Date(a.oldest.created_at) - new Date(b.oldest.created_at));
  return withStock[0].mid;
}
// Toàn bộ mã thành viên của 1 Nhóm vật tư thay thế, sắp theo FIFO (cũ nhất trước) — mã không
// còn tồn Kho công ty (không có lô nào) rơi xuống cuối. Dùng để tự động phân bổ số lượng cần
// lấy khi "Nạp vật tư từ lệnh": lấy hết khả dụng của mã cũ nhất trước, thiếu bao nhiêu mới sang
// mã cũ thứ 2, 3... (xem wireCartPanel::rq_srcload).
function sortGroupMembersFifo(memberIds, allLots) {
  return (memberIds || []).map(mid => ({ mid, oldest: fifoOldestLot(mid, allLots) }))
    .sort((a, b) => {
      if (a.oldest && b.oldest) return new Date(a.oldest.created_at) - new Date(b.oldest.created_at);
      if (a.oldest) return -1;
      if (b.oldest) return 1;
      return 0;
    }).map(x => x.mid);
}
// Mã thành viên nào trong nhóm đang bị "bỏ qua FIFO" — tức còn tồn khả dụng CHƯA dùng hết ở 1 mã
// cũ hơn, nhưng giỏ hàng vẫn đang lấy số lượng > 0 ở 1 mã kém FIFO hơn. Duyệt theo đúng thứ tự
// FIFO của cả nhóm, không chỉ so với "mã tốt nhất" — vì cách lấy tự động (rq_srcload) có thể hợp
// lệ dùng CẢ mã cũ nhất VÀ mã cũ thứ 2 cùng lúc khi mã cũ nhất không đủ tồn (xem rq_submit).
function groupSkippedFifoMaterialIds(memberIds, cartEntriesForGroup, allLots) {
  const skipped = new Set();
  let earlierHasUnusedStock = false;
  for (const mid of sortGroupMembersFifo(memberIds, allLots)) {
    const rowQty = cartEntriesForGroup.filter(c => c.material_id === mid).reduce((s, c) => s + c.quantity, 0);
    if (rowQty > 0 && earlierHasUnusedStock) skipped.add(mid);
    if (materialAvailableCompanyQty(mid, allLots) - rowQty > 1e-9) earlierHasUnusedStock = true;
  }
  return skipped;
}

function groupMemberFifoBadgeHtml(materialId, memberIds, allLots) {
  const best = groupFifoBestMaterialId(memberIds, allLots);
  if (!best) return '<span class="muted">(chưa có tồn Kho công ty)</span>';
  if (best === materialId) {
    return '<span class="badge available" title="Trong nhóm, mã này đang có lô nhập sớm nhất">✓ Tồn cũ nhất trong nhóm (FIFO)</span>';
  }
  const bestMat = REQ_CACHE.matById[best];
  return `<span class="badge on_hold" title="Mã ${esc(bestMat ? bestMat.code : best)} đang có lô cũ hơn">⚠ Còn mã khác cũ hơn trong nhóm</span>`;
}
// Danh sách lô khả dụng của 1 vật tư tại Kho công ty, sắp theo FIFO (cũ nhất trước) — dùng để
// dựng <select> chọn lô ngay trong bảng dòng đề nghị (đỡ phải mở modal riêng cho từng dòng).
function requestLotOptionsHtml(materialId, allLots, selectedLotId) {
  const avail = allLots.filter(l => l.material_id === materialId && l.quantity > 0 && !/phân xưởng/i.test(l.location || ""))
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  if (!avail.length) return { html: '<option value="">(không còn lô khả dụng)</option>', defaultId: "" };
  const defaultId = selectedLotId && avail.some(l => l.lot_id === selectedLotId) ? selectedLotId : avail[0].lot_id;
  const html = avail.map((l, i) => `<option value="${l.lot_id}" ${l.lot_id === defaultId ? "selected" : ""}>` +
    `${esc(l.lot_code)} (${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})${i === 0 ? " — FIFO, lô cũ nhất" : ""}` +
    `${l.status === "on_hold" ? " — CHỜ DUYỆT QC" : ""}</option>`).join("");
  return { html, defaultId };
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
  const matLabel = mat ? `${esc(mat.code)} — ${esc(mat.name)}` : esc(l.material_id);
  const fulLot = l.fulfilled_lot_id ? lotById[l.fulfilled_lot_id] : null;
  const showLotPicker = canFulfill && l.status === "pending";
  const lotOpts = showLotPicker ? requestLotOptionsHtml(l.material_id, allLots, l.preferred_lot_id) : null;
  const lotCell = showLotPicker
    ? `<select class="reqlot-select" id="reqlot-${esc(l.line_id)}">${lotOpts.html}</select>`
    : `<span class="muted">${fulLot ? esc(fulLot.lot_code) : "—"}</span>`;
  const dateCell = showLotPicker ? "" : `<span class="muted">${fulLot ? fmt(fulLot.created_at) : "—"}</span>`;
  const dispLot = fulLot || (l.preferred_lot_id ? lotById[l.preferred_lot_id] : null);
  const dispLoc = dispLot && dispLot.location_id ? (WH_CACHE.matLocById || {})[dispLot.location_id] : null;
  const locCell = dispLoc ? `<code class="k">${esc(dispLoc.code)}</code>` : `<span class="muted">—</span>`;
  const actions = (canFulfill && l.status === "pending")
    ? `<button class="btn sm sec" data-reqfulfill data-reqid="${esc(r.request_id)}" data-lineid="${esc(l.line_id)}" data-qty="${l.quantity}">Xuất dòng này</button>
       <button class="btn sm sec" data-reqreject data-reqid="${esc(r.request_id)}" data-lineid="${esc(l.line_id)}">Từ chối</button>`
    : (canFulfill && l.status === "fulfilled")
    ? `<button class="btn sm sec" data-requndo data-reqid="${esc(r.request_id)}" data-lineid="${esc(l.line_id)}">Hoàn tác</button>`
    : (l.reason ? `<span class="muted">${esc(l.reason)}</span>` : "—");
  return `<tr>
    <td>${matLabel}</td>
    <td>${l.quantity} ${esc(l.uom)}</td>
    <td>${lotCell}</td>
    <td>${dateCell}</td>
    <td>${locCell}</td>
    <td>${l.status === "fulfilled" ? fulfilledFifoBadgeHtml(l.fifo_ok) : requestFifoBadgeHtml(l.material_id, l.preferred_lot_id, allLots)}</td>
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
          <button class="btn sm sec" data-reqtoggle>▸ Chi tiết</button>
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
      <div class="reqdetail" style="display:none;margin-top:8px">
        <table>
          <thead><tr><th>Vật tư</th><th>SL</th><th>Lô</th><th>Ngày nhập</th><th>Vị trí kho</th><th>FIFO</th><th>Trạng thái</th><th></th></tr></thead>
          <tbody>${r.lines.map(l => requestLineRowHtml(r, l, matById, lotById, canFulfill, allLots)).join("") ||
            '<tr><td colspan=8 class="muted">Phiếu không có dòng nào.</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
}

function wireRequestBlockActions() {
  // Tìm khối chi tiết qua quan hệ DOM (sibling trong cùng .tablewrap), KHÔNG dùng
  // document.getElementById — cùng 1 phiếu MaterialRequest render đồng thời ở cả Kho công ty
  // (tab "giao") và Kho phân xưởng (tab "req"), 2 khối luôn cùng tồn tại trong DOM (chỉ 1 view
  // đang hiện qua CSS) nên id trùng nhau sẽ khiến getElementById luôn trả về bản đầu tiên,
  // có thể là bản đang ẩn ở view khác — bấm "Chi tiết" không thấy gì đổi trên màn hình đang xem.
  document.querySelectorAll("[data-reqtoggle]").forEach(b => b.onclick = () => {
    const panel = b.closest(".tablewrap")?.querySelector(".reqdetail");
    if (!panel) return;
    const open = panel.style.display !== "none";
    panel.style.display = open ? "none" : "";
    b.textContent = (open ? "▸" : "▾") + " Chi tiết";
  });
  // Hàm này dùng chung cho cả 2 module (Kho công ty tab "giao" và Kho phân xưởng tab "req") —
  // render lại đúng view đang mở (không hardcode 1 view) để hoạt động đúng ở cả 2 nơi.
  const renderCurrentWarehouseView = () => {
    const v = document.querySelector("#nav button.active")?.dataset.view;
    if (v) render(v);
  };
  // Xuất trực tiếp từ lô đã chọn ở <select> ngay trong dòng (không cần mở modal riêng) — lô
  // mặc định đã gợi ý theo FIFO (requestLotOptionsHtml), thủ kho chỉ cần đổi lại nếu muốn.
  document.querySelectorAll("[data-reqfulfill]").forEach(b => b.onclick = () => guard(async () => {
    const sel = document.getElementById(`reqlot-${b.dataset.lineid}`);
    const lotId = sel ? sel.value : "";
    if (!lotId) throw new Error("Không còn lô khả dụng để xuất cho dòng này.");
    await POST(`/warehouse/requests/${b.dataset.reqid}/lines/${b.dataset.lineid}/fulfill`,
      { lot_id: lotId, quantity: parseFloat(b.dataset.qty), location_to: "Kho phân xưởng" });
    toast("Đã xuất dòng theo lô đã chọn"); renderCurrentWarehouseView();
  }));
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
    const fifoCell = c.group_code
      ? groupMemberFifoBadgeHtml(c.material_id, c.group_members, REQ_CACHE.lots)
      : requestFifoBadgeHtml(c.material_id, c.lot_id, REQ_CACHE.lots);
    const available = round3(materialAvailableCompanyQty(c.material_id, REQ_CACHE.lots));
    const pendingQc = round3(materialPendingQcCompanyQty(c.material_id, REQ_CACHE.lots));
    const workshopQty = round3(materialWorkshopQty(c.material_id, REQ_CACHE.lots));
    const insufficient = c.quantity > available;
    const slCell = c.locked
      ? `<span class="muted" title="Mã cũ hơn (FIFO) trong nhóm đã đủ định mức theo lệnh — mã này không cần lấy">0 ${esc(c.uom)} — đã đủ từ mã cũ hơn</span>`
      : `<input type="number" min="0" step="any" value="${c.quantity}" data-cartqty="${i}" style="width:80px"/> ${esc(c.uom)}`;
    const matNameCart = REQ_CACHE.matById[c.material_id] ? REQ_CACHE.matById[c.material_id].name : "";
    return `<tr${c.locked ? ' style="opacity:.6"' : ""}>
    <td><code class="k">${esc(c.material_code)}</code>${matNameCart ? ` ${esc(matNameCart)}` : ""}</td>
    <td>${c.group_code ? `<span class="badge on_hold" title="1 trong các mã thuộc Nhóm vật tư thay thế &quot;${esc(c.group_name)}&quot; — các mã trong nhóm dùng thay thế nhau, số lượng mỗi mã đã tự phân bổ theo FIFO">⚠️ Nhóm: ${esc(c.group_name)}</span>` : '<span class="muted">—</span>'}</td>
    <td class="${insufficient ? "" : "muted"}"${insufficient ? ` style="color:var(--red)" title="Không đủ tồn thực tế để xuất số lượng đang đề nghị"` : ""}>${available} ${esc(c.uom)}</td>
    <td class="muted">${pendingQc > 0 ? `${pendingQc} ${esc(c.uom)}` : "—"}</td>
    <td class="muted" title="Tồn đang có sẵn tại Kho phân xưởng — chỉ để tham khảo, không tính vào giới hạn số lượng đề nghị">${workshopQty > 0 ? `${workshopQty} ${esc(c.uom)}` : "—"}</td>
    <td class="muted">${c.lot_code ? esc(c.lot_code) : "(để thủ kho chọn theo FIFO)"}</td>
    <td class="muted">${lot ? fmt(lot.created_at) : "—"}</td>
    <td>${fifoCell}</td>
    <td class="muted">${c.order_label ? esc(c.order_label) : "—"}</td>
    <td class="muted">${c.qty_per_order != null ? `${c.qty_per_order} ${esc(c.uom)}` : "—"}</td>
    <td>${slCell}</td>
    <td><button class="btn sm sec" data-cartdel="${i}">Xoá</button></td></tr>`;
  }).join("");
  return `<div class="panel" id="rq_form_panel">
    <h2>Tạo đề nghị nhận kho ${REQUEST_CART.length ? `<span class="muted">(${REQUEST_CART.length} dòng)</span>` : ""}</h2>
    <div class="muted" style="margin-bottom:6px">Thêm nhiều dòng (nhiều vật tư khác nhau) rồi gửi 1 lần — chọn nhanh
      từ bảng "Tồn kho công ty" ở cuối trang, hoặc thêm thủ công bên dưới. Chỉ chọn vật tư + số lượng — lô cụ thể
      xuất từ đâu do thủ kho Kho công ty quyết định lúc duyệt phiếu (mặc định theo FIFO). Khi nạp từ Nhóm vật tư
      thay thế, mã nào đã đủ từ mã cũ hơn trong nhóm (SL = 0) sẽ tự động bỏ qua, không hiện trong bảng dưới đây.</div>
    ${REQUEST_CART.length ? `<div class="tablewrap"><table>
      <thead><tr><th>Vật tư</th><th>Cảnh báo</th><th>Tồn kho công ty thực tế</th><th>Đang chờ QC duyệt</th><th>Tồn kho phân xưởng</th><th>Lô</th><th>Ngày nhập</th><th>FIFO</th><th>Lệnh</th><th>SL theo lệnh</th><th>SL</th><th></th></tr></thead>
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
      <div class="field"><label>Vật tư</label>
        <input id="rq_mat_q" placeholder="Tìm nhanh (gõ mã/tên vật tư)..." style="margin-bottom:2px"/>
        <select id="rq_mat">${REQ_CACHE.matOpts}</select></div>
      <div class="field"><label>SL</label><input id="rq_qty" type="number" value="50"/></div>
      <div class="field"><label>ĐVT</label><span id="rq_uom_wrap"></span></div>
      <button class="btn sec" id="rq_add" style="align-self:flex-end">+ Thêm dòng</button>
    </div>
    <div class="row" style="margin-top:10px">
      <div class="field" style="flex:1"><label>Ghi chú chung (tuỳ chọn)</label><input id="rq_note" placeholder="(tuỳ chọn)"/></div>
      <button class="btn" id="rq_submit" style="align-self:flex-end" ${REQUEST_CART.some(c => c.quantity > 0) ? "" : "disabled"}>
        Gửi đề nghị (${REQUEST_CART.filter(c => c.quantity > 0).length} dòng)</button>
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
    const groupLines = lines.filter(l => l.is_group);
    const normalLines = lines.filter(l => !l.is_group);
    const orderCode = $("rq_srcorder").options[$("rq_srcorder").selectedIndex].textContent;
    const orderLabel = (type === "brew_order" ? "Lệnh nấu " : "Lệnh lọc ") + orderCode;
    for (const l of normalLines) {
      REQUEST_CART.push({ material_id: l.material_id, material_code: l.material_code || l.material_id,
        lot_id: null, lot_code: null, quantity: l.quantity, uom: l.uom || "kg",
        order_label: orderLabel, qty_per_order: l.quantity });
    }
    // Dòng Nhóm vật tư thay thế (material_id=null) — đưa THẲNG từng mã thành viên lên giỏ (mỗi mã
    // 1 dòng), tự động lấy hết tồn khả dụng của mã đang cũ nhất (FIFO) trước, thiếu bao nhiêu mới
    // sang mã cũ thứ 2, 3... — mã nào không cần lấy (vì mã cũ hơn đã đủ định mức) thì SL=0, BỎ
    // QUA HẲN không đưa vào giỏ (trước đây vẫn thêm rồi khoá xám dòng "0kg — đã đủ", gây rối mắt
    // không cần thiết vì đằng nào cũng không được tạo trong phiếu lúc gửi).
    let addedMemberRows = 0, skippedMemberRows = 0;
    for (const l of groupLines) {
      const members = l.member_material_ids || [];
      const sortedMembers = sortGroupMembersFifo(members, REQ_CACHE.lots);
      let remaining = l.quantity;
      for (const mid of sortedMembers) {
        const available = materialAvailableCompanyQty(mid, REQ_CACHE.lots);
        const take = Math.min(remaining, available);
        remaining -= take;
        if (take <= 0) { skippedMemberRows++; continue; }
        const m = REQ_CACHE.matById[mid];
        REQUEST_CART.push({ material_id: mid, material_code: m ? m.code : mid,
          lot_id: null, lot_code: null, quantity: take, uom: l.uom || "kg",
          group_code: l.group_code, group_name: l.material_name, group_members: members,
          order_label: orderLabel, qty_per_order: l.quantity });
        addedMemberRows++;
      }
    }
    REQUEST_SOURCE = { type, id, label: orderLabel };
    refreshCartPanel();
    toast(groupLines.length
      ? `Đã nạp ${normalLines.length} dòng vật tư — còn ${groupLines.length} Nhóm vật tư thay thế đã tự phân bổ ` +
        `${addedMemberRows} mã thành viên cần lấy theo FIFO` +
        (skippedMemberRows ? ` (bỏ qua ${skippedMemberRows} mã đã đủ từ mã cũ hơn)` : "")
      : `Đã nạp ${lines.length} dòng vật tư từ ${REQUEST_SOURCE.label}`,
      groupLines.length ? "warn" : undefined);
  });
  // "Bỏ gắn" phải xoá luôn các dòng đã tự nạp từ lệnh (đánh dấu bằng order_label) — không chỉ
  // bỏ nhãn REQUEST_SOURCE — nếu không, các dòng đó vẫn nằm trong giỏ dù không còn gắn với lệnh
  // nào, dễ gửi nhầm. Dòng người dùng tự thêm thủ công (không có order_label) vẫn được giữ lại.
  if ($("rq_srcclear")) $("rq_srcclear").onclick = () => {
    REQUEST_SOURCE = null;
    REQUEST_CART = REQUEST_CART.filter(c => !c.order_label);
    refreshCartPanel();
  };
  const refreshRqUom = () => {
    $("rq_uom_wrap").innerHTML = altUomFieldHtml(REQ_CACHE.matById[$("rq_mat").value], "rq_uom", 60);
  };
  $("rq_mat").onchange = refreshRqUom;
  refreshRqUom();
  wireSelectSearch("rq_mat", "rq_mat_q");
  $("rq_add").onclick = () => guard(async () => {
    const matId = $("rq_mat").value;
    const mat = REQ_CACHE.matById[matId];
    const qty = altUomToBaseQty(mat, parseFloat($("rq_qty").value), $("rq_uom").value);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    const onHand = materialAvailableCompanyQty(matId, REQ_CACHE.lots);
    if (qty > onHand) throw new Error(
      `Số lượng đề nghị (${qty}) vượt quá tồn kho CÔNG TY THỰC TẾ (đã trừ hàng đang chờ QC duyệt) của ` +
      `${mat ? mat.code : matId} (${onHand}).`);
    // Người đề nghị (phân xưởng) chỉ chọn vật tư + số lượng — KHÔNG chọn lô/ngày nhập cụ thể,
    // để thủ kho Kho công ty tự quyết định xuất lô nào (mặc định FIFO) lúc duyệt phiếu.
    REQUEST_CART.push({ material_id: matId, material_code: mat ? mat.code : matId,
      lot_id: null, lot_code: null,
      quantity: qty, uom: mat ? mat.uom : ($("rq_uom").value.trim() || "kg") });
    refreshCartPanel();
  });
  document.querySelectorAll("[data-cartdel]").forEach(b => b.onclick = () => {
    REQUEST_CART.splice(parseInt(b.dataset.cartdel, 10), 1);
    refreshCartPanel();
  });
  // Cho sửa SL trực tiếp trên dòng (kể cả dòng vừa nạp từ lệnh/nhóm) — chặn vượt tồn Kho công
  // ty hiện có, giống điều kiện lúc "+ Thêm dòng thủ công" ở rq_add bên dưới.
  document.querySelectorAll("[data-cartqty]").forEach(inp => inp.onchange = () => guard(async () => {
    const i = parseInt(inp.dataset.cartqty, 10);
    const c = REQUEST_CART[i];
    const qty = parseFloat(inp.value);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    const onHand = materialAvailableCompanyQty(c.material_id, REQ_CACHE.lots);
    if (qty > onHand) throw new Error(
      `Số lượng (${qty}) vượt quá tồn kho CÔNG TY THỰC TẾ (đã trừ hàng đang chờ QC duyệt) của ${c.material_code} (${onHand}).`);
    c.quantity = qty;
    refreshCartPanel();
  }));
  $("rq_submit").onclick = () => guard(async () => {
    if (!REQUEST_CART.length) throw new Error("Chưa có dòng nào trong đề nghị.");
    // Dòng SL=0 (mã trong Nhóm vật tư thay thế đã đủ định mức từ mã cũ hơn, tự khoá lại lúc nạp
    // từ lệnh) KHÔNG được tạo trong phiếu — chỉ gửi các dòng thực sự có số lượng > 0.
    const submitRows = REQUEST_CART.filter(c => c.quantity > 0);
    if (!submitRows.length) throw new Error("Không có dòng nào có số lượng > 0 để gửi đề nghị.");
    // Chặn hẳn (không hỏi lại) nếu SL đang đề nghị vượt quá tồn kho THỰC TẾ (đã trừ hàng đang
    // chờ QC duyệt) — không cho tạo phiếu xin nhiều hơn số thực sự có thể xuất ngay.
    const overStockRows = submitRows.filter(c => c.quantity > materialAvailableCompanyQty(c.material_id, REQ_CACHE.lots));
    if (overStockRows.length) {
      const detail = overStockRows.map(c => `${c.material_code} (cần ${c.quantity}, tồn thực tế ` +
        `${materialAvailableCompanyQty(c.material_id, REQ_CACHE.lots)} ${c.uom})`).join("; ");
      throw new Error(`Không đủ tồn kho công ty thực tế để tạo đề nghị: ${detail}. Giảm số lượng hoặc chờ hàng hết QC.`);
    }
    // Dòng thuộc Nhóm vật tư thay thế mà SL > 0 nhưng còn mã cũ hơn trong nhóm CHƯA dùng hết tồn
    // — nghĩa là đã bỏ qua FIFO (thường do sửa tay sau khi nạp từ lệnh) — hỏi xác nhận trước khi
    // cho gửi. Không tính các mã "đã đủ từ mã cũ hơn" (SL=0, không nằm trong submitRows).
    const groupCodesSeen = new Set();
    const skippedFifoRows = [];
    for (const c of submitRows) {
      if (!c.group_code || groupCodesSeen.has(c.group_code)) continue;
      groupCodesSeen.add(c.group_code);
      const groupCartEntries = REQUEST_CART.filter(x => x.group_code === c.group_code);
      const skipped = groupSkippedFifoMaterialIds(c.group_members, groupCartEntries, REQ_CACHE.lots);
      for (const g of groupCartEntries) if (g.quantity > 0 && skipped.has(g.material_id)) skippedFifoRows.push(g);
    }
    if (skippedFifoRows.length) {
      const names = skippedFifoRows.map(c => esc(c.material_code)).join(", ");
      if (!confirm(`Mã ${names} không phải mã đang tồn cũ nhất còn khả dụng trong Nhóm vật tư thay thế của nó ` +
                   `(không đảm bảo FIFO). Bạn có chắc chắn muốn gửi đề nghị với mã này không?`)) return;
    }
    const note = $("rq_note").value.trim() || null;
    // 1 phiếu duy nhất gồm nhiều dòng vật tư — KHÔNG tách thành nhiều phiếu riêng.
    const res = await POST("/warehouse/requests", {
      lines: submitRows.map(c => ({ material_id: c.material_id, quantity: c.quantity,
        uom: c.uom, preferred_lot_id: c.lot_id })),
      note,
      source_type: REQUEST_SOURCE ? REQUEST_SOURCE.type : null,
      source_id: REQUEST_SOURCE ? REQUEST_SOURCE.id : null,
    });
    toast(`Đã gửi phiếu ${res.request_code} (${submitRows.length} dòng)`);
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
  const { matById, lotById, canRequest, lots } = REQ_CACHE;
  // Khối này chỉ dùng ở tab "Đề nghị nhận kho" của Kho phân xưởng — phía NGƯỜI ĐỀ NGHỊ, không
  // phải người duyệt. Duyệt/từ chối/hoàn tác phiếu là việc của Kho công ty (tab "Xuất theo đề
  // nghị" ở VIEWS.warehouse_kc dùng canFulfillGiao riêng) — nên ép canFulfill=false tại đây, kể cả khi
  // người đang xem (vd admin) có sẵn quyền warehouse.issue, để không lộ nút duyệt sai chỗ.
  const canFulfill = false;
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
  // Chỉ hiện lệnh CHƯA hoàn thành trong danh sách nạp vật tư — lệnh đã hoàn thành (đủ sản
  // lượng + hết mẻ) không còn cần đề nghị nhận thêm NVL nữa, ẩn đi để tránh chọn nhầm.
  REQ_CACHE.brewOrders = brewOrders.filter(o => !o.is_complete).map(o => ({ id: o.brew_order_id,
    order_code: `${o.order_code} · ${o.product_code || o.product_desc || "(chưa gán dịch bia)"} · ${o.created_at ? fmt(o.created_at) : "—"}` }));
  REQ_CACHE.filterMasterOrders = filterMasterOrders.filter(o => !o.is_complete_all)
    .map(o => ({ id: o.filter_master_order_id, order_code: o.order_code }));
  REQ_CACHE.matById = Object.fromEntries(mats.map(m => [m.material_id, m]));
  REQ_CACHE.lots = lots;
  const lotById = Object.fromEntries(lots.map(l => [l.lot_id, l]));
  REQ_CACHE.lotById = lotById;
  REQ_CACHE.allRequests = requests;
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
  // Gộp theo VẬT TƯ (không hiện từng lô riêng) — người đề nghị chỉ chọn vật tư + số lượng,
  // lô cụ thể xuất từ đâu do thủ kho Kho công ty tự quyết định lúc duyệt (mặc định FIFO).
  const stockByMat = {};
  for (const l of lots) {
    if (!l.material_id || l.quantity <= 0 || /phân xưởng/i.test(l.location || "")) continue;
    const agg = stockByMat[l.material_id] || (stockByMat[l.material_id] = { material_id: l.material_id, uom: l.uom, quantity: 0, lotCount: 0 });
    agg.quantity += l.quantity; agg.lotCount += 1;
  }
  const stockRows = Object.values(stockByMat).sort((a, b) => {
    const ca = REQ_CACHE.matById[a.material_id], cb = REQ_CACHE.matById[b.material_id];
    const codeA = (ca ? ca.code : a.material_id) || "";
    const codeB = (cb ? cb.code : b.material_id) || "";
    return codeA.localeCompare(codeB);
  });
  const stockBrowser = !canRequest ? "" : `<div class="panel"><h2>Tồn kho công ty <span class="muted">(${stockRows.length})</span></h2>
    <div class="muted" style="margin-bottom:6px">Nhập số lượng muốn nhận rồi bấm "+ Thêm" để đưa vào đề nghị phía trên — có thể thêm nhiều dòng liên tiếp.
      Chỉ chọn vật tư + số lượng — lô cụ thể do thủ kho Kho công ty quyết định lúc duyệt.</div>
    <div class="row" style="margin-bottom:6px"><div class="field" style="flex:1"><label>Tìm vật tư</label><input class="searchbox" data-tbl="stk_table" placeholder="Gõ mã/tên vật tư..."/></div></div>
    <div class="tablewrap"><table id="stk_table">
      <thead><tr><th>Vật tư</th><th>Tổng tồn</th><th>Số lô</th><th>SL muốn nhận</th><th></th></tr></thead>
      <tbody>${stockRows.map(r => { const mat = REQ_CACHE.matById[r.material_id]; return `<tr>
        <td>${esc(mat ? `${mat.code} — ${mat.name}` : r.material_id)}</td>
        <td>${r.quantity} ${esc(r.uom)}</td>
        <td class="muted">${r.lotCount}</td>
        <td><input type="number" class="stk-qty" value="${r.quantity}" min="0" max="${r.quantity}" style="width:90px"/></td>
        <td><button class="btn sm sec" data-pickmat="${esc(r.material_id)}" data-pickuom="${esc(r.uom)}">+ Thêm</button></td></tr>`; }).join("") ||
        '<tr><td colspan=5 class="muted">Kho công ty hiện không còn vật tư nào.</td></tr>'}</tbody>
    </table></div>
  </div>`;

  return cartSection + requestsTable + stockBrowser;
}

// ---- Modal: khai báo + duyệt chỉ tiêu chất lượng của 1 lô NVL ----
// editable=true (mặc định, dùng ở tab Chất lượng cho KCS): cho nhập giá trị + nút Duyệt.
// editable=false (dùng ở tab Kho NVL cho thủ kho / khu Kho phân xưởng): chỉ xem trạng thái, không nhập được.
// Chỉ tiêu Đạt/Không đạt được ghi qua nguyên cơ chế so sánh numeric có sẵn (value/lower/upper),
// không sửa logic đánh giá — quy ước value=1 (Đạt) hoặc 0 (Không đạt), lower=upper=1 để
// _evaluate()/_evaluate_stage_result() so value==upper==lower ra PASS, khác ra FAIL.
function qcValueLabel(p, value, valueText) {
  if (p.value_type === "text") return valueText ? esc(String(valueText)) : "—";
  if (p.value_type === "pass_fail") return value === 1 ? "Đạt" : value === 0 ? "Không đạt" : esc(String(value));
  return esc(String(value));
}
function qcValueInputHtml(cls, p) {
  if (p.value_type === "pass_fail") {
    return `<select class="${cls}" data-code="${esc(p.code)}" data-lsl="1" data-usl="1" style="width:130px">
      <option value="">— chọn —</option><option value="1">Đạt</option><option value="0">Không đạt</option></select>`;
  }
  // Chỉ tiêu kiểu "text" — người vận hành nhập ghi chú tự do, không so target/USL/LSL, không
  // tính pass/fail (đánh dấu data-text để submit handler gửi value_text thay vì value số).
  if (p.value_type === "text") {
    return `<input type="text" class="${cls}" data-code="${esc(p.code)}" data-text="1" style="width:180px"/>`;
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
  const paramByCodeLqc = Object.fromEntries(st.required.map(p => [p.code, p]));
  // st.recorded gồm TOÀN BỘ lịch sử khai báo của lô này, sắp theo recorded_at TĂNG DẦN (xem
  // qc_catalog.lot_qc_status) — mỗi lần bấm "Lưu giá trị đã nhập" TẠO DÒNG MỚI, KHÔNG ghi đè
  // dòng cũ (xem services/quality.py::record_result: luôn new_id()) — lô bị đưa lại on_hold để
  // duyệt lại (VD do có đề nghị điều chuyển sang kho phân xưởng) vẫn giữ đủ giá trị lần khai
  // báo trước, chỉ giá trị MỚI NHẤT (dòng cuối mỗi mã chỉ tiêu) được dùng để tính đạt/không đạt
  // và điều kiện duyệt (can_release) — group lại ở đây để hiện nút "Lịch sử" khi có ≥2 lần.
  const historyByParam = {};
  st.recorded.forEach(r => (historyByParam[r.parameter] = historyByParam[r.parameter] || []).push(r));
  // Ô "Lần 1"/"Lần 2" — hiện thẳng giá trị + kết quả + người/thời gian của TỪNG lần, không cần
  // mở modal mới cho trường hợp phổ biến (khai báo lại đúng 1 lần do điều chuyển/hold lại).
  // Lần 2 LUÔN là lần MỚI NHẤT (dùng để tính đạt/không đạt & can_release) dù thực tế đã sang lần
  // 3+ (hiếm) — kèm nhãn "(lần N)" đúng số thứ tự thật + nút "Lịch sử" để xem đủ các lần ở giữa.
  const lqcRoundCell = (p, round, tag) => !round ? '<span class="muted">—</span>' :
    `${qcValueLabel(p, round.value, round.value_text)}${tag || ""} ${badge(round.status)}${round.status}
     <div class="muted" style="font-size:12px">${esc(round.recorded_by || "—")}<br/>${round.recorded_at ? fmt(round.recorded_at) : "—"}</div>`;
  modal(`<h3>Chỉ tiêu chất lượng — lô ${esc(st.lot_code)}</h3>
    ${!editable ? '<div class="muted" style="margin-bottom:8px">Chế độ xem — việc khai báo &amp; duyệt do KCS thực hiện ở tab Chất lượng.</div>' : ""}
    ${editable ? `<div class="muted" style="margin-bottom:8px">Mỗi lần bấm "Lưu giá trị đã nhập" sẽ ghi thành 1 <b>lần khai báo mới</b> ("Lần 2", "Lần 3"...) —
      giá trị lần trước KHÔNG bị mất, vẫn xem ở cột tương ứng/nút "Lịch sử". Chỉ giá trị của lần mới nhất được dùng để tính đạt/không đạt và điều kiện duyệt lô.</div>` : ""}
    <div class="row" style="margin-bottom:10px">
      <div class="field"><label>Số lô KCS</label>
        <input id="lqc_kcslot" value="${esc(st.kcs_lot_no || "")}" placeholder="(KCS tự điền)" ${editable ? "" : "disabled"}/></div>
      <div class="field"><label>Số LOT nhà cung cấp</label>
        <input id="lqc_supplierlot" value="${esc(st.supplier_lot || "")}" placeholder="(ghi trên bao bì NCC)" ${editable ? "" : "disabled"}/></div>
      ${editable ? '<button class="btn sec sm" id="lqc_kcslot_save" style="align-self:flex-end">Lưu số lô/LOT</button>' : ""}
    </div>
    ${st.is_raw_material && st.missing_lot_no ? '<div class="muted" style="margin-bottom:10px;color:var(--red)">⚠ Nguyên liệu chính/phụ — phải nhập Số lô KCS hoặc Số LOT nhà cung cấp mới được duyệt.</div>' : ""}
    <div class="tablewrap"><table>
      <thead><tr><th>Chỉ tiêu</th><th>Min</th><th>Max</th><th>Lần 1</th><th>Lần 2</th>${st.is_raw_material ? '<th>CA đã khai báo</th>' : ""}${editable ? `<th>Nhập giá trị mới</th>${st.is_raw_material ? "<th>Nhập giá trị CA</th>" : ""}` : ""}</tr></thead>
      <tbody>${st.required.map(p => { const r = recordedByParam[p.code]; const hist = historyByParam[p.code] || [];
        const first = hist[0] || null;
        const latest = hist.length ? hist[hist.length - 1] : null;
        const lan2 = hist.length >= 2 ? latest : null;
        const lan2Tag = hist.length > 2 ? ` <span class="muted" style="font-size:11px">(lần ${hist.length})</span>` : "";
        return `<tr>
        <td>${esc(p.name)}<div class="muted">${esc(p.code)}${p.unit ? " (" + esc(p.unit) + ")" : ""}</div></td>
        <td>${p.value_type !== "numeric" ? "—" : (p.lsl ?? "—")}</td><td>${p.value_type !== "numeric" ? "—" : (p.usl ?? "—")}</td>
        <td>${lqcRoundCell(p, first)}</td>
        <td>${lqcRoundCell(p, lan2, lan2Tag)}${hist.length > 2 ? `<div><button type="button" class="btn sm sec" data-lqchist="${esc(p.code)}" style="margin-top:4px">Lịch sử (${hist.length} lần)</button></div>` : ""}</td>
        ${st.is_raw_material ? `<td>${r && r.ca_value != null ? esc(String(r.ca_value)) : "—"}</td>` : ""}
        ${editable ? `<td>${qcValueInputHtml("lqc-val", p)}</td>${st.is_raw_material ? `<td><input type="number" step="any" class="lqc-ca-val" data-code="${esc(p.code)}" style="width:110px" title="Giá trị in trên bao bì nhà cung cấp — chỉ tham khảo, không tính pass/fail"/></td>` : ""}` : ""}
        </tr>`; }).join("") || `<tr><td colspan=${editable ? (st.is_raw_material ? 8 : 6) : (st.is_raw_material ? 6 : 5)} class="muted">Nguyên liệu này không có chỉ tiêu bắt buộc.</td></tr>`}</tbody>
    </table></div>
    ${editable ? `<button class="btn" id="lqc_submit" style="margin-top:12px">Lưu giá trị đã nhập</button>
    ${canRelease ? `<button class="btn sec" id="lqc_release" style="margin-top:12px" ${st.can_release ? "" : "disabled"} ${st.missing_lot_no ? 'title="Còn thiếu Số lô KCS hoặc Số LOT nhà cung cấp"' : ""}>
      Duyệt (release)${st.can_release ? "" : (st.missing_lot_no ? " — thiếu Số lô KCS/LOT NCC" : " — còn thiếu khai báo")}</button>` :
      '<div class="muted" style="margin-top:12px">Cần quyền <code class="k">quality.release</code> (KCS/QA) để duyệt.</div>'}` : ""}`);
  document.querySelectorAll("[data-lqchist]").forEach(b => b.onclick = () => {
    const code = b.dataset.lqchist;
    openLotQcHistoryModal(st.lot_code, paramByCodeLqc[code], historyByParam[code], () => openLotQcModal(lotId, { editable }));
  });
  if (!editable) return;

  $("lqc_kcslot_save").onclick = () => guard(async () => {
    await PUT(`/lots/${lotId}`, {
      kcs_lot_no: $("lqc_kcslot").value.trim() || null,
      supplier_lot: $("lqc_supplierlot").value.trim() || null,
    });
    toast("Đã lưu số lô KCS/LOT NCC");
    openLotQcModal(lotId, { editable });
  });
  $("lqc_submit").onclick = () => guard(async () => {
    // Mỗi dòng (1 chỉ tiêu) chỉ cần điền MỘT trong hai ô — "Nhập giá trị mới" hoặc "Nhập giá
    // trị CA" — là đủ để lưu, KHÔNG bắt buộc luôn cả 2 (VD: chỉ bổ sung CA cho chỉ tiêu đã
    // pass/fail từ trước, không cần đo lại). Ô còn lại bỏ trống thì lấy lại giá trị đã lưu lần
    // trước (nếu có) để không làm mất dữ liệu cũ hay đổi status pass/fail ngoài ý muốn. Chỉ
    // nhập CA mà chỉ tiêu đó CHƯA TỪNG có giá trị đo (chưa khai báo lần nào) thì bỏ qua — không
    // tạo bản ghi value=null/status=pending, tránh bị tính nhầm là "đã khai báo" khi duyệt lô
    // (xem lot_qc_status ở qc_catalog.py).
    const caByCode = Object.fromEntries(Array.from(document.querySelectorAll(".lqc-ca-val"))
      .map(i => [i.dataset.code, i.value]));
    const rows = Array.from(document.querySelectorAll(".lqc-val")).map(inp => {
      const code = inp.dataset.code;
      const caRaw = caByCode[code];
      return { inp, code, hasVal: inp.value !== "", hasCa: caRaw !== undefined && caRaw !== "", caRaw, prev: recordedByParam[code] };
    }).filter(r => r.hasVal || (r.hasCa && r.prev));
    if (!rows.length) throw new Error("Chưa nhập giá trị nào.");
    for (const { inp, code, hasVal, hasCa, caRaw, prev } of rows) {
      // Chỉ tiêu kiểu "text" (data-text) — gửi value_text, không so target/USL/LSL, không
      // parseFloat (xem qcValueInputHtml).
      const isText = inp.dataset.text === "1";
      await POST("/quality/results", {
        scope_type: "lot", scope_id: lotId, parameter: code,
        value: isText ? null : (hasVal ? parseFloat(inp.value) : (prev ? prev.value : null)),
        value_text: isText ? (hasVal ? inp.value : (prev ? prev.value_text : null)) : null,
        ca_value: hasCa ? parseFloat(caRaw) : (prev ? prev.ca_value : null),
        lower_limit: isText ? null : (inp.dataset.lsl === "" ? null : parseFloat(inp.dataset.lsl)),
        upper_limit: isText ? null : (inp.dataset.usl === "" ? null : parseFloat(inp.dataset.usl)),
      });
    }
    toast("Đã lưu chỉ tiêu"); openLotQcModal(lotId, { editable });
  });
  if ($("lqc_release")) $("lqc_release").onclick = () => guard(async () => {
    const hasFail = st.recorded.some(r => r.status === "fail");
    if (hasFail && !confirm("Có chỉ tiêu chất lượng KHÔNG ĐẠT (FAIL). Bộ phận chất lượng có đồng ý cho nhập kho không?")) return;
    await POST("/quality/hold", { scope_type: "lot", scope_id: lotId, on_hold: false });
    closeModal(); toast("Đã duyệt lô — có thể chuyển sang kho phân xưởng");
    const v = document.querySelector("#nav button.active")?.dataset.view;
    if (v) render(v);
  });
}

// Xem lại TOÀN BỘ các lần khai báo trước đó của 1 chỉ tiêu (1 lô NVL) — chỉ đọc, không sửa được
// ở đây (sửa/thêm lần mới vẫn làm ở openLotQcModal). "Lần 1" = dòng cũ nhất; dòng cuối luôn là
// giá trị đang được dùng để tính đạt/không đạt & điều kiện duyệt lô hiện tại.
function openLotQcHistoryModal(lotCode, param, history, onBack) {
  const rows = history.slice().reverse(); // mới nhất lên đầu — dễ đối chiếu với giá trị hiện tại
  modal(`<h3>Lịch sử khai báo — ${esc(param.name)} <span class="muted">(lô ${esc(lotCode)})</span></h3>
    <div class="tablewrap"><table>
      <thead><tr><th>Lần</th><th>Giá trị</th>${param.value_type !== "text" ? "<th>CA</th>" : ""}<th>Kết quả</th><th>Người điền</th><th>Thời gian</th></tr></thead>
      <tbody>${rows.map((r, i) => { const lanNo = history.length - i; return `<tr${i === 0 ? ' style="font-weight:600"' : ""}>
        <td>Lần ${lanNo}${i === 0 ? ' <span class="muted" style="font-weight:400">(hiện tại)</span>' : ""}</td>
        <td>${qcValueLabel(param, r.value, r.value_text)}</td>
        ${param.value_type !== "text" ? `<td class="muted">${r.ca_value != null ? esc(String(r.ca_value)) : "—"}</td>` : ""}
        <td>${badge(r.status)}${r.status}</td>
        <td class="muted">${esc(r.recorded_by || "—")}</td>
        <td class="muted">${fmt(r.recorded_at)}</td></tr>`; }).join("")}</tbody>
    </table></div>`, onBack);
}

// ---- Modal: khai báo chỉ tiêu theo công đoạn sản xuất (mẻ nấu/lên men chính-phụ/lọc/chiết/thành phẩm) ----
// Cùng cơ chế openLotQcModal nhưng lưu qua /brewing/qc-results (không gắn vòng đời batch/lot) —
// duyệt/tiếp tục công đoạn (nếu có, vd Duyệt chiết) là hành động riêng, không nằm trong modal này.
async function openStageQcModal(stage, scopeType, scopeId, opts, onBack) {
  opts = opts || {};
  const title = opts.title || (STAGE_LABELS[stage] || stage);
  let qs = `stage=${encodeURIComponent(stage)}&scope_type=${encodeURIComponent(scopeType)}&scope_id=${encodeURIComponent(scopeId)}`;
  const isProductScopedStage = PRODUCT_SCOPED_STAGES.includes(stage);
  const isBeerTypeScopedStage = BEER_TYPE_SCOPED_STAGES.includes(stage);
  if (opts.productId) qs += `&product_id=${encodeURIComponent(opts.productId)}`;
  if (opts.beerTypeId) qs += `&beer_type_id=${encodeURIComponent(opts.beerTypeId)}`;
  if (opts.finishedProductId) qs += `&finished_product_id=${encodeURIComponent(opts.finishedProductId)}`;
  const st = await GET(`/brewing/qc-status?${qs}`);
  const recordedByParam = Object.fromEntries(st.recorded.map(r => [r.parameter, r]));
  modal(`<h3>Chỉ tiêu ${esc(title)} — <code class="k">${esc(opts.displayId || scopeId)}</code></h3>
    ${isProductScopedStage && !opts.productId ? '<div class="muted" style="margin-bottom:8px">⚠ Bản ghi này chưa gắn dịch bia — chỉ hiện nhóm chỉ tiêu áp dụng cho mọi dịch bia (nếu có).</div>' : ""}
    ${isBeerTypeScopedStage && !opts.beerTypeId ? '<div class="muted" style="margin-bottom:8px">⚠ Bản ghi này chưa gắn Loại bia — chỉ hiện nhóm chỉ tiêu áp dụng cho mọi loại bia (nếu có).</div>' : ""}
    ${stage === "thanh_pham" && !opts.finishedProductId ? '<div class="muted" style="margin-bottom:8px">⚠ Bản ghi này chưa gắn Sản phẩm — chỉ hiện nhóm chỉ tiêu áp dụng cho mọi sản phẩm (nếu có).</div>' : ""}
    <div class="tablewrap"><table>
      <thead><tr><th>Chỉ tiêu</th><th>Min</th><th>Max</th><th>Giá trị đã khai báo</th><th>Kết quả</th><th>Người/Thời gian điền</th><th>Nhập giá trị mới</th></tr></thead>
      <tbody>${st.required.map(p => { const r = recordedByParam[p.code]; return `<tr>
        <td>${esc(p.name)}<div class="muted">${esc(p.code)}${p.unit ? " (" + esc(p.unit) + ")" : ""}</div></td>
        <td>${p.value_type !== "numeric" ? "—" : (p.lsl ?? "—")}</td><td>${p.value_type !== "numeric" ? "—" : (p.usl ?? "—")}</td>
        <td>${r ? qcValueLabel(p, r.value, r.value_text) : "—"}</td>
        <td>${r ? badge(r.status) + r.status : '<span class="muted">chưa khai báo</span>'}</td>
        <td>${qcRecordedMetaHtml(r)}</td>
        <td>${qcValueInputHtml("sqc-val", p)}</td>
        </tr>`; }).join("") || `<tr><td colspan=7 class="muted">Chưa gán nhóm chỉ tiêu nào cho công đoạn này (gán ở tab Danh mục).</td></tr>`}</tbody>
    </table></div>
    <div class="muted" style="margin-top:8px">${st.can_release ? '<span style="color:var(--green)">✓ Đã đủ chỉ tiêu bắt buộc</span>' :
      st.pending.length ? `⚠ Còn thiếu: ${st.pending.map(esc).join(", ")}` :
      st.required.length ? '<span style="color:var(--red)">✗ Có chỉ tiêu bắt buộc không đạt (FAIL)</span>' : ""}</div>
    ${st.required.length ? `<button class="btn" id="sqc_submit" style="margin-top:12px">Lưu giá trị đã nhập</button>` : ""}`, onBack);
  if ($("sqc_submit")) $("sqc_submit").onclick = () => guard(async () => {
    const inputs = Array.from(document.querySelectorAll(".sqc-val")).filter(i => i.value !== "");
    if (!inputs.length) throw new Error("Chưa nhập giá trị nào.");
    for (const inp of inputs) {
      const isText = inp.dataset.text === "1";
      await POST("/brewing/qc-results", {
        stage, scope_type: scopeType, scope_id: scopeId, parameter: inp.dataset.code,
        value: isText ? null : parseFloat(inp.value),
        value_text: isText ? inp.value : null,
        lower_limit: isText ? null : (inp.dataset.lsl === "" ? null : parseFloat(inp.dataset.lsl)),
        upper_limit: isText ? null : (inp.dataset.usl === "" ? null : parseFloat(inp.dataset.usl)),
      });
    }
    toast("Đã lưu chỉ tiêu");
    // Bảng nền (Nấu/Lên men/Lọc/Chiết) tô màu theo trạng thái chỉ tiêu lúc load trang — sửa
    // FAIL thành PASS rồi lưu ở đây không tự cập nhật màu bảng nền vì modal render tách biệt
    // với view (xem modal() — overlay riêng trên document.body). Refresh view nền để màu đúng ngay,
    // không cần F5 mới thấy — bảng dưới vẫn bị ẩn sau modal cho tới khi đóng.
    const curView = document.querySelector("#nav button.active")?.dataset.view;
    if (curView) render(curView);
    openStageQcModal(stage, scopeType, scopeId, opts, onBack);
  });
}

// Popup nhỏ xem chi tiết chỉ tiêu đang FAIL của 1 tank lên men (bấm vào badge đỏ ở biểu đồ
// Dashboard) — chỉ đọc, không cho sửa ở đây (sửa giá trị vẫn làm qua nút CT chính/CT phụ ở
// tab Lên men, xem openStageQcModal). Gộp cả 2 giai đoạn CT chính + CT phụ vì badge đếm cả hai.
async function openFermentQcFailModal(lmCode) {
  const stages = [["len_men_chinh", "CT chính"], ["len_men_phu", "CT phụ"]];
  const histories = await Promise.all(stages.map(([stage]) =>
    GET(`/brewing/qc-samples?scope_type=ferment&scope_id=${encodeURIComponent(lmCode + "__" + stage)}`)));
  // Hiện TẤT CẢ lần lấy mẫu bị FAIL trong toàn bộ lịch sử (không chỉ lần mới nhất) — khác
  // trạng thái ĐẠT/FAIL dùng để duyệt (luôn chỉ theo lần mới nhất, xem qc_catalog.stage_qc_status)
  // — ở đây là xem lại/soát vết, nên liệt kê đủ mọi lần từng vượt giới hạn kèm ngày lấy mẫu.
  const rows = [];
  stages.forEach(([stage, label], i) => {
    (histories[i].items || []).forEach(session => {
      session.results.forEach(r => {
        if (r.status === "fail") rows.push({ label, sampledAt: session.sampled_at, recordedBy: session.recorded_by, r });
      });
    });
  });
  rows.sort((a, b) => new Date(b.sampledAt) - new Date(a.sampledAt));
  modal(`<h3>Lịch sử chỉ tiêu vượt giới hạn — tank <code class="k">${esc(lmCode)}</code></h3>
    <div class="tablewrap"><table>
      <thead><tr><th>Ngày giờ lấy mẫu</th><th>Giai đoạn</th><th>Chỉ tiêu</th><th>Min</th><th>Max</th><th>Giá trị</th><th>Người ghi</th></tr></thead>
      <tbody>${rows.length ? rows.map(x => `<tr>
        <td>${fmt(x.sampledAt)}</td>
        <td>${esc(x.label)}</td>
        <td>${esc(x.r.name)}<div class="muted">${esc(x.r.parameter)}${x.r.unit ? " (" + esc(x.r.unit) + ")" : ""}</div></td>
        <td>${x.r.lower_limit ?? "—"}</td>
        <td>${x.r.upper_limit ?? "—"}</td>
        <td style="color:var(--red);font-weight:700">${x.r.value ?? "—"}</td>
        <td>${esc(x.recordedBy || "—")}</td>
        </tr>`).join("") : `<tr><td colspan=7 class="muted">Không có chỉ tiêu nào đang fail.</td></tr>`}</tbody>
    </table></div>`);
}

// Lấy mẫu NHIỀU LẦN cho CT chính/CT phụ lên men (lần 1 ngày giờ X, lần 2 ngày giờ Y...) —
// khác openStageQcModal (1 giá trị hiện tại, ghi đè) dùng cho Nấu/Lọc/Chiết: mỗi lần lưu ở
// đây LUÔN thêm 1 bản ghi mới (POST /brewing/qc-samples), giữ nguyên lịch sử để xem lại.
// ĐẠT/FAIL để duyệt vẫn chỉ tính theo lần MỚI NHẤT (xem qc_catalog.stage_qc_status).
async function openFermentQcSampleModal(stage, scopeType, scopeId, productId, onBack) {
  const label = stage === "len_men_chinh" ? "CT chính" : "CT phụ";
  const lmCode = scopeId.split("__")[0];
  const qs = `stage=${encodeURIComponent(stage)}&scope_type=${encodeURIComponent(scopeType)}&scope_id=${encodeURIComponent(scopeId)}`
    + (productId ? `&product_id=${encodeURIComponent(productId)}` : "");
  const [status, history] = await Promise.all([
    GET(`/brewing/qc-status?${qs}`),
    GET(`/brewing/qc-samples?scope_type=${encodeURIComponent(scopeType)}&scope_id=${encodeURIComponent(scopeId)}`),
  ]);

  const formRows = status.required.map(p => `<tr>
      <td>${esc(p.name)}<div class="muted">${esc(p.code)}${p.unit ? " (" + esc(p.unit) + ")" : ""}</div></td>
      <td>${p.value_type !== "numeric" ? "—" : (p.lsl ?? "—")}</td>
      <td>${p.value_type !== "numeric" ? "—" : (p.usl ?? "—")}</td>
      <td>${qcValueInputHtml("sqc-sample-val", p)}</td>
      </tr>`).join("")
    || `<tr><td colspan=4 class="muted">Chưa gán nhóm chỉ tiêu nào cho công đoạn này (gán ở tab Danh mục).</td></tr>`;

  const historyHtml = history.items.length ? history.items.map(s => `
    <div style="margin-bottom:14px;padding:10px 12px;background:var(--panel2);border:1px solid var(--border);border-radius:8px">
      <div style="font-weight:700;margin-bottom:6px">${fmt(s.sampled_at)} <span class="muted" style="font-weight:400">— ${esc(s.recorded_by || "—")}</span></div>
      <table style="width:100%">
        <thead><tr><th>Chỉ tiêu</th><th>Min</th><th>Max</th><th>Giá trị</th><th>Kết quả</th></tr></thead>
        <tbody>${s.results.map(r => `<tr>
          <td>${esc(r.name)}${r.unit ? ` <span class="muted">(${esc(r.unit)})</span>` : ""}</td>
          <td>${r.value_type !== "numeric" ? "—" : (r.lower_limit ?? "—")}</td><td>${r.value_type !== "numeric" ? "—" : (r.upper_limit ?? "—")}</td>
          <td>${qcValueLabel({ value_type: r.value_type || "numeric" }, r.value, r.value_text)}</td>
          <td>${badge(r.status)}${r.status}</td>
          </tr>`).join("")}</tbody>
      </table>
    </div>`).join("") : `<div class="muted">Chưa có lần lấy mẫu nào.</div>`;

  modal(`<h3>${esc(label)} — tank <code class="k">${esc(lmCode)}</code></h3>
    <div class="muted" style="margin-bottom:8px">${status.can_release ? '<span style="color:var(--green)">✓ Đã đủ chỉ tiêu bắt buộc (theo lần lấy mẫu mới nhất)</span>' :
      status.pending.length ? `⚠ Còn thiếu: ${status.pending.map(esc).join(", ")}` :
      status.required.length ? '<span style="color:var(--red)">✗ Có chỉ tiêu bắt buộc không đạt (FAIL) — theo lần mới nhất</span>' : ""}</div>
    <h4 style="margin:14px 0 8px">Thêm lần lấy mẫu mới</h4>
    <div class="field" style="margin-bottom:10px"><label>Ngày giờ lấy mẫu</label>
      <input type="datetime-local" id="sqc_sample_when" value="${toDTLocal(new Date())}"/></div>
    <div class="tablewrap"><table>
      <thead><tr><th>Chỉ tiêu</th><th>Min</th><th>Max</th><th>Giá trị đo được</th></tr></thead>
      <tbody>${formRows}</tbody>
    </table></div>
    ${status.required.length ? `<button class="btn" id="sqc_sample_submit" style="margin-top:12px">Lưu lần lấy mẫu</button>` : ""}
    <h4 style="margin:18px 0 8px">Lịch sử các lần lấy mẫu</h4>
    ${historyHtml}`, onBack);

  if ($("sqc_sample_submit")) $("sqc_sample_submit").onclick = () => guard(async () => {
    const inputs = Array.from(document.querySelectorAll(".sqc-sample-val")).filter(i => i.value !== "");
    if (!inputs.length) throw new Error("Chưa nhập giá trị nào.");
    const whenLocal = $("sqc_sample_when").value;
    await POST("/brewing/qc-samples", {
      stage, scope_type: scopeType, scope_id: scopeId,
      sampled_at: whenLocal ? new Date(whenLocal).toISOString() : null,
      results: inputs.map(inp => {
        const isText = inp.dataset.text === "1";
        return {
          parameter: inp.dataset.code,
          value: isText ? null : parseFloat(inp.value),
          value_text: isText ? inp.value : null,
          lower_limit: isText ? null : (inp.dataset.lsl === "" ? null : parseFloat(inp.dataset.lsl)),
          upper_limit: isText ? null : (inp.dataset.usl === "" ? null : parseFloat(inp.dataset.usl)),
        };
      }),
    });
    toast("Đã lưu lần lấy mẫu");
    const curView = document.querySelector("#nav button.active")?.dataset.view;
    if (curView) render(curView);
    openFermentQcSampleModal(stage, scopeType, scopeId, productId, onBack);
  });
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
async function openBrewMaterialsModal(brewId, batchId, batchCode, onBack) {
  const [usage, lots, materials, brews, altGroups] = await Promise.all([
    GET(`/brewing/brews/${brewId}/batches/${batchId}/materials`), GET("/lots"), GET("/materials"),
    GET("/brewing/brews").catch(() => []), GET("/material-alt-groups").catch(() => [])]);
  const matById = Object.fromEntries(materials.map(m => [m.material_id, m]));
  const lotById = Object.fromEntries(lots.map(l => [l.lot_id, l]));
  const matForUsage = (u) => { const lot = u.lot_id ? lotById[u.lot_id] : null; return lot ? matById[lot.material_id] : null; };
  // Mã vật tư -> Nhóm vật tư thay thế chứa nó (nếu có) — dùng để: (1) cảnh báo khi mẻ này đã
  // ghi nhận >1 mã KHÁC nhau cùng 1 nhóm (thường là do nhầm, nên chỉ dùng 1 mã thay thế cho
  // nhóm đó), (2) ép ĐVT của các mã thuộc nhóm phải theo đúng MaterialAltGroup.unit (không cho
  // tự chọn uom/alt_uom riêng của từng mã) để tồn kho các mã trong nhóm cộng được với nhau,
  // (3) hỏi xác nhận trước khi thêm 1 mã KHÁC trong cùng nhóm vào mẻ đã có mã đó rồi.
  const altGroupByMaterialId = {};
  for (const g of altGroups) for (const mid of g.member_material_ids || []) altGroupByMaterialId[mid] = g;
  const groupForcedUomHtml = (mat, attrs) => {
    const grp = mat ? altGroupByMaterialId[mat.material_id] : null;
    if (grp && grp.unit) {
      const a = /=/.test(attrs) ? attrs : `id="${attrs}"`;
      return `<input ${a} value="${esc(grp.unit)}" readonly title="Bắt buộc theo đơn vị của Nhóm vật tư thay thế &quot;${esc(grp.name)}&quot;" style="width:60px;background:var(--bg2,#f2f2f2)"/>`;
    }
    return altUomFieldHtml(mat, attrs, 60);
  };
  // Số lượng đã LƯU (BrewMaterialUsage.quantity) luôn ở đơn vị GỐC (mat.uom) của vật tư — khi ép
  // hiển thị ĐVT theo đơn vị NHÓM (groupForcedUomHtml, có thể là mat.alt_uom, VD "kg" khi
  // mat.uom="lon") phải quy đổi lại số hiển thị cho khớp, nếu không số trên màn hình (đơn vị
  // gốc) sẽ bị đọc nhầm thành đơn vị nhóm — đây là lỗi cụ thể người dùng vừa báo (0.8 thay vì 4).
  const groupForcedDisplayQty = (mat, baseQty) => {
    const grp = mat ? altGroupByMaterialId[mat.material_id] : null;
    if (grp && grp.unit && grp.unit === mat.alt_uom && mat.alt_uom_ratio) return baseQty * mat.alt_uom_ratio;
    return baseQty;
  };
  // Lô cũ nhất trong Kho phân xưởng TÍNH CHUNG CẢ NHÓM vật tư thay thế (so giữa các mã thành
  // viên với nhau, giống hệt cách "Đề nghị nhận kho" đang so — xem groupFifoBestMaterialId) —
  // KHÁC workshopLots vốn chỉ sort trong phạm vi 1 mã. Vì workshopLots đã sort theo (material_id,
  // created_at) nên .find() theo từng mid trả ngay lô cũ nhất của riêng mã đó.
  const groupOldestWorkshopLot = (memberIds) => {
    let best = null;
    for (const mid of memberIds || []) {
      const l = workshopLots.find(l => l.material_id === mid);
      if (l && (!best || new Date(l.created_at) < new Date(best.created_at))) best = l;
    }
    return best;
  };
  // Badge FIFO cho 1 dòng gợi ý BOM: nếu mã thuộc Nhóm vật tư thay thế, phải so với lô cũ nhất
  // CỦA CẢ NHÓM (không chỉ so với các lô khác của riêng mã đó) — mã không thuộc nhóm thì vẫn so
  // trong phạm vi riêng mã như trước.
  const bomRowFifoHtml = (mid, matLots, chosenLotId) => {
    const grp = altGroupByMaterialId[mid];
    if (grp) {
      const groupBest = groupOldestWorkshopLot(grp.member_material_ids);
      if (groupBest && chosenLotId === groupBest.lot_id) return '<span class="badge available">✓ Lô cũ nhất (FIFO)</span>';
      const bestMat = groupBest ? matById[groupBest.material_id] : null;
      return `<span class="badge on_hold" title="Còn lô cũ hơn ở mã ${esc(bestMat ? bestMat.code : "")} trong nhóm: ${esc(groupBest ? groupBest.lot_code : "")} (${groupBest ? fmt(groupBest.created_at) : ""})">⚠ Còn mã khác cũ hơn trong nhóm</span>`;
    }
    if (!matLots.length) return '<span class="muted">—</span>';
    return matLots[0].lot_id === chosenLotId
      ? '<span class="badge available">✓ Lô cũ nhất (FIFO)</span>'
      : `<span class="badge on_hold" title="Còn lô cũ hơn: ${esc(matLots[0].lot_code)} (${fmt(matLots[0].created_at)})">⚠ Không phải lô cũ nhất</span>`;
  };
  // Mã khác (nếu có) trong CÙNG nhóm với `mat` đã được ghi nhận (Lưu thành công) cho mẻ này —
  // dùng để cảnh báo cột "Cảnh báo" của dòng đã ghi nhận, và để hỏi xác nhận lúc thêm dòng mới.
  const otherGroupMemberInUsage = (mat) => {
    if (!mat) return null;
    const grp = altGroupByMaterialId[mat.material_id];
    // Nhóm "chọn nhiều mã" (selection_mode="multi") — dùng phối hợp nhiều mã cùng lúc là hành
    // vi ĐÚNG, không phải nhầm lẫn, nên bỏ cảnh báo/hỏi xác nhận (khác nhóm "chỉ 1 mã" mặc định).
    if (!grp || grp.selection_mode === "multi") return null;
    for (const u2 of usage) {
      const m2 = matForUsage(u2);
      if (m2 && m2.material_id !== mat.material_id && grp.member_material_ids.includes(m2.material_id)) return m2;
    }
    return null;
  };

  // Gợi ý số lượng NVL/mẻ — lấy từ Định mức của Lệnh nấu (mã nấu này thuộc về), đã tự
  // chia đều cho số mẻ khai báo lúc lập lệnh (BrewOrderMaterialLine.qty_per_batch).
  // Chỉ là gợi ý — số thực tế dùng vẫn ghi ở ô SL riêng, sửa tự do được. Dòng khai theo Nhóm
  // vật tư thay thế (VD "Malt Úc") không có material_id cụ thể — thêm TỪNG material_id thành
  // viên vào sugByMaterialId (cùng gợi ý qty_per_batch) để bảng gợi ý bên dưới tự hiện đủ mọi
  // mã cụ thể (rời/bao) đang có tồn Kho phân xưởng, thủ kho chọn lô nào cũng được.
  let sugByMaterialId = {};
  const addBomLinesToSug = (lines) => {
    for (const l of lines || []) {
      if (l.is_header) continue;
      if (l.material_id) { if (l.qty_per_batch != null) sugByMaterialId[l.material_id] = l.qty_per_batch; continue; }
      // Dòng Nhóm vật tư thay thế khai định mức RIÊNG từng thành viên (Công thức ->
      // member_qty, xem services/brew_order.py::_build_group_line) — member_breakdown mang
      // sẵn qty_per_batch của TỪNG mã, dùng đúng số đó thay vì gán chung 1 số như dòng nhóm
      // khai kiểu cũ (không có member.qty_per_batch).
      const hasPerMemberQty = (l.member_breakdown || []).some(mb => mb.qty_per_batch != null);
      if (hasPerMemberQty) {
        for (const mb of l.member_breakdown) if (mb.material_id) sugByMaterialId[mb.material_id] = mb.qty_per_batch;
        continue;
      }
      if (l.qty_per_batch == null) continue;
      for (const mid of l.member_material_ids || []) sugByMaterialId[mid] = l.qty_per_batch;
    }
  };
  const brew = brews.find(b => b.brew_id === brewId);
  if (brew && brew.brew_order_id) {
    try {
      const order = await GET(`/brewing/orders/${brew.brew_order_id}`);
      addBomLinesToSug(order.lines);
      // Lệnh nấu chưa lưu định mức riêng từng dòng (VD lệnh cũ/tạo tay không qua auto-BOM)
      // — tính lại gợi ý trực tiếp từ Công thức (BOM) của dịch bia, dùng ĐÚNG planned_batch_count/
      // planned_volume_hl đã lưu ở lệnh để ra cùng 1 số/mẻ như khi lệnh có định mức sẵn.
      if (!Object.keys(sugByMaterialId).length && order.product_id && order.planned_batch_count) {
        const preview = await GET(`/brewing/orders/bom-preview?product_id=${encodeURIComponent(order.product_id)}&planned_batch_count=${order.planned_batch_count}&planned_volume_hl=${order.planned_volume_hl || 0}`);
        addBomLinesToSug(preview);
      }
    } catch (e) { /* không có lệnh nấu/định mức/công thức — bỏ qua gợi ý */ }
  }

  // Chỉ hiển thị NVL có trong định mức của lệnh nấu này — tránh chọn nhầm vật tư
  // không thuộc công thức. Nếu lệnh chưa có định mức thì mới cho chọn tự do.
  const bomMaterialIds = new Set(Object.keys(sugByMaterialId));
  const workshopLotsAll = lots.filter(l => l.quantity > 0 && l.status !== "on_hold" && /phân xưởng/i.test(l.location || ""));
  const workshopLots = sortLotsFifo(bomMaterialIds.size ? workshopLotsAll.filter(l => bomMaterialIds.has(l.material_id)) : workshopLotsAll);
  // Bảng "gợi ý" CHỈ hiện mã nào đã thực sự có tồn Kho phân xưởng — mã cùng Nhóm vật tư thay
  // thế nhưng chưa chuyển sang Kho phân xưởng (SL=0, nút Thêm vô dụng) chỉ gây rối mắt, đã có
  // cảnh báo thiếu tồn riêng ở Lệnh nấu/BOM preview rồi nên không cần lặp lại ở đây.
  const bomIdsWithStock = [...bomMaterialIds].filter(mid => workshopLots.some(l => l.material_id === mid));
  const lotOpts = `<option value="">(nhập tên tự do)</option>` + workshopLots.map(l => {
    const mat = matById[l.material_id];
    return `<option value="${esc(l.lot_id)}" data-material="${esc(l.material_id || "")}">${esc(mat ? mat.name : l.lot_code)} — lô ${esc(l.lot_code)} (còn ${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})</option>`;
  }).join("") || `<option value="">(Kho phân xưởng chưa có tồn NVL thuộc định mức lệnh nấu này)</option>`;

  modal(`<h3>Nguyên liệu dùng cho mẻ — <code class="k">${esc(batchCode)}</code></h3>
    <div class="muted" style="margin-bottom:8px">Nguyên liệu phân bổ vào mẻ nấu lấy từ tồn kho <b>Kho phân xưởng</b> — chọn lô sẽ trừ tồn kho thật ngay. Danh sách lô bên dưới đã sắp theo FIFO (cũ nhất trước) trong từng vật tư.</div>
    <div class="tablewrap"><table>
      <thead><tr><th>Nguyên liệu</th><th>Cảnh báo</th><th>Số lô PM</th><th>Ngày lô</th><th>FIFO</th><th>Số lượng</th><th>ĐVT</th><th></th></tr></thead>
      <tbody>${usage.map(u => {
        const otherMember = otherGroupMemberInUsage(matForUsage(u));
        return `<tr>
        <td>${esc(u.material_name)}</td>
        <td>${otherMember ? `<span class="badge on_hold" title="Mã ${esc(otherMember.code)} cũng thuộc Nhóm vật tư thay thế này đã được ghi nhận cho mẻ — 2 mã dùng thay thế nhau, thường chỉ nên giữ 1 mã">⚠️ Nhóm: ${esc(altGroupByMaterialId[matForUsage(u).material_id].name)}</span>` : '<span class="muted">—</span>'}</td>
        <td class="muted">${esc(u.lot_pm || "—")}</td>
        <td class="muted">${u.lot_date ? fmt(u.lot_date) : "—"}</td>
        <td>${fifoBadgeHtml(u.fifo_ok)}</td>
        <td><input type="number" step="any" class="bmu-edit-qty" data-usage="${esc(u.usage_id)}" value="${groupForcedDisplayQty(matForUsage(u), u.quantity)}" style="width:90px"/></td>
        <td>${groupForcedUomHtml(matForUsage(u), `class="bmu-edit-uom" data-usage="${esc(u.usage_id)}"`)}</td>
        <td style="white-space:nowrap">
          <button class="btn sm sec" data-saveusage="${esc(u.usage_id)}" data-name="${esc(u.material_name)}" data-lot="${esc(u.lot_pm || "")}" data-receipt="${esc(u.receipt_id || "")}" data-lotid="${esc(u.lot_id || "")}">Lưu</button>
          <button class="btn sm sec" data-delusage="${esc(u.usage_id)}">Xóa</button>
        </td></tr>`;
      }).join("") ||
        `<tr><td colspan=8 class="muted">Chưa ghi nguyên liệu nào cho mẻ này.</td></tr>`}</tbody>
    </table></div>
    ${bomIdsWithStock.length ? `<h4 style="margin-top:14px;display:flex;align-items:center;gap:10px">
      <span>Nguyên liệu gợi ý từ Lệnh nấu (theo định mức)</span>
      <button class="btn sm" id="bmu_add_all" style="margin-left:auto">+ Thêm tất cả (SL &gt; 0)</button>
    </h4>
    <div class="muted" style="font-size:12px;margin-bottom:6px">Chỉ hiện nguyên liệu ĐÃ CÓ tồn Kho phân xưởng (mã nào chưa chuyển sang Kho phân xưởng thì không hiện ở đây — xem cảnh báo thiếu tồn ở Lệnh nấu) — lô đã chọn theo FIFO (cũ nhất trước), đổi sang lô khác nếu muốn. SL đã điền theo gợi ý định mức/mẻ, sửa lại theo thực tế dùng rồi bấm Thêm cho từng dòng, hoặc "+ Thêm tất cả" để thêm 1 lần mọi dòng đang có SL &gt; 0.</div>
    <div class="tablewrap"><table>
      <thead><tr><th>Nguyên liệu</th><th>Cảnh báo</th><th>Chọn lô (Kho phân xưởng)</th><th>Tồn kho PX thực tế</th><th>FIFO</th><th>Gợi ý</th><th>SL thực tế</th><th>ĐVT</th><th></th></tr></thead>
      <tbody>${bomIdsWithStock.map(mid => {
        const mat = matById[mid];
        const matLots = workshopLots.filter(l => l.material_id === mid);
        const sug = sugByMaterialId[mid];
        const rowOpts = matLots.map((l, i) => `<option value="${esc(l.lot_id)}" data-uom="${esc(l.uom)}" ${i === 0 ? "selected" : ""}>lô ${esc(l.lot_code)} (còn ${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})</option>`).join("");
        const firstLot = matLots[0];
        const grp = altGroupByMaterialId[mid];
        return `<tr data-bomrow="${esc(mid)}">
          <td>${esc(mat ? mat.name : mid)}</td>
          <td>${grp ? `<span class="badge on_hold" title="Thuộc Nhóm vật tư thay thế &quot;${esc(grp.name)}&quot; — các mã trong nhóm dùng thay thế nhau, phải so FIFO giữa các mã trong nhóm trước khi chọn lô">⚠️ Nhóm: ${esc(grp.name)}</span>` : '<span class="muted">—</span>'}</td>
          <td><select class="bmu-row-lot" data-material="${esc(mid)}">${rowOpts}</select></td>
          <td class="bmu-row-stock">${firstLot.quantity} ${esc(firstLot.uom)}</td>
          <td class="bmu-row-fifo">${bomRowFifoHtml(mid, matLots, firstLot.lot_id)}</td>
          <td class="muted">${sug != null ? sug : "—"}</td>
          <td><input type="number" step="any" class="bmu-row-qty" value="${sug != null ? sug : 0}" style="width:90px"/></td>
          <td>${groupForcedUomHtml(mat, `class="bmu-row-uom"`)}</td>
          <td><button class="btn sm" data-bomadd="${esc(mid)}" data-name="${esc(mat ? mat.name : mid)}">Thêm</button></td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>` : ""}
    <h4 style="margin-top:14px">${bomMaterialIds.size ? "Thêm nguyên liệu khác (ngoài định mức)" : "+ Thêm nguyên liệu"}</h4>
    <div class="muted" style="font-size:12px;margin-bottom:4px">Chọn nguyên liệu ở Kho phân xưởng sẽ tự hiện "Gợi ý" (định mức/mẻ theo Lệnh nấu, đã chia đều cho số mẻ) và tự điền tạm vào ô SL — chỉ là gợi ý, sửa lại SL theo thực tế dùng.</div>
    <div class="row">
      <div class="field" style="min-width:300px"><label>Chọn từ tồn kho Kho phân xưởng</label><select id="bmu_lot">${bomMaterialIds.size ? (`<option value="">(nhập tên tự do)</option>` + sortLotsFifo(workshopLotsAll).map(l => {
        const mat = matById[l.material_id];
        return `<option value="${esc(l.lot_id)}" data-material="${esc(l.material_id || "")}">${esc(mat ? mat.name : l.lot_code)} — lô ${esc(l.lot_code)} (còn ${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})</option>`;
      }).join("")) : lotOpts}</select></div>
      <div class="field"><label>Hoặc tên tự do</label><input id="bmu_name" placeholder="(nếu không chọn ở trên)"/></div>
      <div class="field"><label>Gợi ý (định mức/mẻ)</label><input id="bmu_qty_sug" value="—" disabled style="width:100px;opacity:.7"/></div>
      <div class="field"><label>SL thực tế</label><input id="bmu_qty" type="number" value="0"/></div>
      <div class="field"><label>ĐVT</label><span id="bmu_uom_wrap"></span></div>
      <button class="btn" id="bmu_add" style="align-self:flex-end">Thêm</button>
    </div>`, onBack, true);
  // Đổi lô đã chọn ở dòng gợi ý BOM → cập nhật lại cột "Tồn kho PX thực tế" + "FIFO" theo đúng
  // lô đang chọn (không phải luôn là lô đầu tiên) — dùng chung dữ liệu matLots đã lọc theo mã.
  document.querySelectorAll(".bmu-row-lot").forEach(sel => {
    const mid = sel.dataset.material;
    const matLots = workshopLots.filter(l => l.material_id === mid);
    sel.onchange = () => {
      const row = sel.closest("tr");
      const chosen = matLots.find(l => l.lot_id === sel.value);
      row.querySelector(".bmu-row-stock").textContent = chosen ? `${chosen.quantity} ${chosen.uom}` : "0";
      row.querySelector(".bmu-row-fifo").innerHTML = bomRowFifoHtml(mid, matLots, sel.value);
    };
  });
  document.querySelectorAll("[data-bomadd]").forEach(b => b.onclick = () => guard(async () => {
    const row = b.closest("tr");
    const lotSel = row.querySelector(".bmu-row-lot");
    const mat = matById[b.dataset.bomadd];
    if (!lotSel) throw new Error(`${mat ? mat.name : b.dataset.bomadd} chưa có tồn Kho phân xưởng — không thể ghi nhận dùng cho mẻ.`);
    const lotId = lotSel.value;
    const uomVal = row.querySelector(".bmu-row-uom").value.trim() || "kg";
    const qty = altUomToBaseQty(mat, parseFloat(row.querySelector(".bmu-row-qty").value), uomVal);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    // Lô cụ thể của Kho phân xưởng đã chọn — SL dùng KHÔNG được vượt tồn thật của đúng lô đó.
    const matLots = workshopLots.filter(l => l.material_id === b.dataset.bomadd);
    const chosenLot = matLots.find(l => l.lot_id === lotId);
    if (chosenLot && qty > chosenLot.quantity) throw new Error(
      `Số lượng (${qty}${mat ? mat.uom : ""}) vượt quá tồn kho phân xưởng thực tế của lô đã chọn ` +
      `(${chosenLot.quantity}${chosenLot.uom}).`);
    // Mẻ đã ghi nhận 1 mã khác cùng Nhóm vật tư thay thế với mã đang thêm — 2 mã này dùng thay
    // thế nhau, thêm cả 2 vào cùng 1 mẻ thường là nhầm nên hỏi xác nhận trước.
    const otherMember = otherGroupMemberInUsage(mat);
    if (otherMember) {
      const grp = altGroupByMaterialId[mat.material_id];
      if (!confirm(`Mẻ này đã ghi nhận mã ${otherMember.code} thuộc Nhóm vật tư thay thế "${grp.name}". ` +
                   `Bạn có chắc chắn muốn thêm thêm mã ${mat ? mat.code : b.dataset.bomadd} (cùng nhóm) vào mẻ này không?`)) return;
    }
    await POST(`/brewing/brews/${brewId}/batches/${batchId}/materials`, {
      lot_id: lotId, material_name: lotId ? null : b.dataset.name, quantity: qty, uom: mat ? mat.uom : uomVal });
    toast("Đã thêm nguyên liệu cho mẻ" + (lotId ? " — đã trừ tồn Kho phân xưởng" : "")); openBrewMaterialsModal(brewId, batchId, batchCode, onBack);
  }));
  // "+ Thêm tất cả" — làm y hệt bấm "Thêm" từng dòng ở bảng gợi ý (đúng lô/SL/ĐVT đang hiện trên
  // mỗi dòng), chỉ khác là gộp lại 1 lần cho MỌI dòng đang có SL > 0 và có tồn Kho phân xưởng để
  // chọn — dòng nào SL = 0 hoặc chưa có tồn (nút Thêm đang disabled) thì bỏ qua, không báo lỗi.
  if ($("bmu_add_all")) $("bmu_add_all").onclick = () => guard(async () => {
    const rows = [...document.querySelectorAll("[data-bomrow]")].filter(row => {
      const qtyInp = row.querySelector(".bmu-row-qty");
      const lotSel = row.querySelector(".bmu-row-lot");
      return lotSel && qtyInp && parseFloat(qtyInp.value) > 0;
    });
    if (!rows.length) throw new Error("Không có dòng nào đang có SL > 0 và có tồn Kho phân xưởng để thêm.");
    // Hỏi 1 lần duy nhất cho mọi xung đột Nhóm vật tư thay thế thay vì hỏi từng dòng — liệt kê
    // rõ mã nào trùng nhóm với mã nào để người dùng tự quyết định thêm tất cả hay huỷ để bỏ bớt.
    const conflicts = [];
    for (const row of rows) {
      const mid = row.dataset.bomrow;
      const mat = matById[mid];
      const otherMember = otherGroupMemberInUsage(mat);
      if (otherMember) conflicts.push(`${mat ? mat.name : mid} (trùng nhóm với ${otherMember.code} đã ghi nhận)`);
    }
    if (conflicts.length && !confirm(`Có ${conflicts.length} nguyên liệu trùng Nhóm vật tư thay thế với mã đã ghi nhận cho mẻ:\n` +
        conflicts.join("\n") + "\n\nVẫn thêm tất cả?")) return;
    let added = 0;
    const failed = [];
    for (const row of rows) {
      const mid = row.dataset.bomrow;
      const mat = matById[mid];
      const lotSel = row.querySelector(".bmu-row-lot");
      const lotId = lotSel.value;
      const uomVal = row.querySelector(".bmu-row-uom").value.trim() || "kg";
      const qty = altUomToBaseQty(mat, parseFloat(row.querySelector(".bmu-row-qty").value), uomVal);
      const matLots = workshopLots.filter(l => l.material_id === mid);
      const chosenLot = matLots.find(l => l.lot_id === lotId);
      if (chosenLot && qty > chosenLot.quantity) {
        failed.push(`${mat ? mat.name : mid}: SL (${qty}${mat ? mat.uom : ""}) vượt tồn lô đã chọn (${chosenLot.quantity}${chosenLot.uom})`);
        continue;
      }
      try {
        await POST(`/brewing/brews/${brewId}/batches/${batchId}/materials`, {
          lot_id: lotId, material_name: lotId ? null : (mat ? mat.name : mid), quantity: qty, uom: mat ? mat.uom : uomVal });
        added++;
      } catch (e) {
        failed.push(`${mat ? mat.name : mid}: ${e.message || e}`);
      }
    }
    if (added) toast(`Đã thêm ${added} nguyên liệu cho mẻ — đã trừ tồn Kho phân xưởng` + (failed.length ? ` (${failed.length} dòng lỗi)` : ""));
    if (failed.length) alert(`${failed.length} dòng KHÔNG thêm được:\n` + failed.join("\n"));
    openBrewMaterialsModal(brewId, batchId, batchCode, onBack);
  });
  const refreshBmuUom = () => {
    const opt = $("bmu_lot").selectedOptions[0];
    const materialId = opt ? opt.dataset.material : "";
    $("bmu_uom_wrap").innerHTML = groupForcedUomHtml(materialId ? matById[materialId] : null, "bmu_uom");
  };
  $("bmu_lot").onchange = () => {
    const opt = $("bmu_lot").selectedOptions[0];
    const materialId = opt ? opt.dataset.material : "";
    const sug = materialId ? sugByMaterialId[materialId] : null;
    $("bmu_qty_sug").value = sug != null ? sug : "—";
    if (sug != null && (!$("bmu_qty").value || parseFloat($("bmu_qty").value) === 0)) {
      $("bmu_qty").value = sug;
    }
    refreshBmuUom();
  };
  refreshBmuUom();
  $("bmu_add").onclick = () => guard(async () => {
    const lotId = $("bmu_lot").value || null;
    const name = $("bmu_name").value.trim() || null;
    if (!lotId && !name) throw new Error("Chọn nguyên liệu từ tồn kho Kho phân xưởng, hoặc nhập tên tự do.");
    const lotOpt = $("bmu_lot").selectedOptions[0];
    const mat = lotOpt && lotOpt.dataset.material ? matById[lotOpt.dataset.material] : null;
    const qty = altUomToBaseQty(mat, parseFloat($("bmu_qty").value), $("bmu_uom").value);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    if (lotId) {
      const chosenLot = workshopLotsAll.find(l => l.lot_id === lotId);
      if (chosenLot && qty > chosenLot.quantity) throw new Error(
        `Số lượng (${qty}${mat ? mat.uom : ""}) vượt quá tồn kho phân xưởng thực tế của lô đã chọn ` +
        `(${chosenLot.quantity}${chosenLot.uom}).`);
    }
    const otherMember = otherGroupMemberInUsage(mat);
    if (otherMember) {
      const grp = altGroupByMaterialId[mat.material_id];
      if (!confirm(`Mẻ này đã ghi nhận mã ${otherMember.code} thuộc Nhóm vật tư thay thế "${grp.name}". ` +
                   `Bạn có chắc chắn muốn thêm thêm mã ${mat.code} (cùng nhóm) vào mẻ này không?`)) return;
    }
    await POST(`/brewing/brews/${brewId}/batches/${batchId}/materials`, {
      lot_id: lotId, material_name: name, quantity: qty, uom: mat ? mat.uom : ($("bmu_uom").value.trim() || "kg") });
    toast("Đã thêm nguyên liệu cho mẻ" + (lotId ? " — đã trừ tồn Kho phân xưởng" : "")); openBrewMaterialsModal(brewId, batchId, batchCode, onBack);
  });
  document.querySelectorAll("[data-saveusage]").forEach(b => b.onclick = () => guard(async () => {
    const usageId = b.dataset.saveusage;
    const mat = b.dataset.lotid ? (lotById[b.dataset.lotid] ? matById[lotById[b.dataset.lotid].material_id] : null) : null;
    const uomVal = document.querySelector(`.bmu-edit-uom[data-usage="${usageId}"]`).value.trim() || "kg";
    const qty = altUomToBaseQty(mat, parseFloat(document.querySelector(`.bmu-edit-qty[data-usage="${usageId}"]`).value), uomVal);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    await PUT(`/brewing/brews/${brewId}/batches/${batchId}/materials/${usageId}`, {
      lot_id: b.dataset.lotid || null, receipt_id: b.dataset.receipt || null, material_name: b.dataset.name,
      lot_pm: b.dataset.lot || null, quantity: qty, uom: mat ? mat.uom : uomVal });
    toast("Đã lưu"); openBrewMaterialsModal(brewId, batchId, batchCode, onBack);
  }));
  document.querySelectorAll("[data-delusage]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Xóa dòng nguyên liệu đã ghi cho mẻ này? Không thể hoàn tác.")) return;
    await DELETE(`/brewing/brews/${brewId}/batches/${batchId}/materials/${b.dataset.delusage}`);
    toast("Đã xóa"); openBrewMaterialsModal(brewId, batchId, batchCode, onBack);
  }));
}

// ---- Modal: nguyên liệu đã dùng cho 1 mẻ lọc cụ thể — lấy thật từ tồn kho Kho phân xưởng
// (mirror openBrewMaterialsModal, gợi ý số lượng lấy từ FilterOrderMaterialLine của Lệnh lọc) ----
async function openFilterMaterialsModal(filterId, filterOrderId, filterCode) {
  const [usage, lots, materials] = await Promise.all([
    GET(`/brewing/filters/${filterId}/materials`), GET("/lots"), GET("/materials")]);
  const matById = Object.fromEntries(materials.map(m => [m.material_id, m]));
  const lotById = Object.fromEntries(lots.map(l => [l.lot_id, l]));
  const matForUsage = (u) => { const lot = u.lot_id ? lotById[u.lot_id] : null; return lot ? matById[lot.material_id] : null; };

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
        <td>${altUomFieldHtml(matForUsage(u), `class="fmu-edit-uom" data-usage="${esc(u.usage_id)}"`, 60)}</td>
        <td style="white-space:nowrap">
          <button class="btn sm sec" data-savefusage="${esc(u.usage_id)}" data-name="${esc(u.material_name)}" data-lot="${esc(u.lot_pm || "")}" data-receipt="${esc(u.receipt_id || "")}" data-lotid="${esc(u.lot_id || "")}">Lưu</button>
          <button class="btn sm sec" data-delfusage="${esc(u.usage_id)}">Xóa</button>
        </td></tr>`).join("") ||
        `<tr><td colspan=7 class="muted">Chưa ghi nguyên liệu nào cho mẻ lọc này.</td></tr>`}</tbody>
    </table></div>
    ${bomMaterialIds.size ? `<h4 style="margin-top:14px">Nguyên liệu gợi ý từ Lệnh lọc (theo định mức)</h4>
    <div class="muted" style="font-size:12px;margin-bottom:6px">Hiện sẵn từng nguyên liệu trong định mức — lô đã chọn theo FIFO (cũ nhất trước), đổi sang lô khác nếu muốn. SL đã điền theo số lượng khai báo lúc lập Lệnh lọc, sửa lại theo thực tế dùng rồi bấm Thêm cho từng dòng.</div>
    <div class="tablewrap"><table>
      <thead><tr><th>Nguyên liệu</th><th>Chọn lô (Kho phân xưởng)</th><th>Gợi ý</th><th>SL thực tế</th><th>ĐVT</th><th></th></tr></thead>
      <tbody>${[...bomMaterialIds].map(mid => {
        const mat = matById[mid];
        const matLots = workshopLots.filter(l => l.material_id === mid);
        const sug = sugByMaterialId[mid];
        const rowOpts = matLots.map((l, i) => `<option value="${esc(l.lot_id)}" data-uom="${esc(l.uom)}" ${i === 0 ? "selected" : ""}>lô ${esc(l.lot_code)} (còn ${l.quantity}${l.uom}, nhập ${fmt(l.created_at)})</option>`).join("");
        return `<tr>
          <td>${esc(mat ? mat.name : mid)}</td>
          <td>${matLots.length ? `<select class="fmu-row-lot">${rowOpts}</select>` : `<span class="muted">Chưa có tồn Kho phân xưởng</span>`}</td>
          <td class="muted">${sug != null ? sug : "—"}</td>
          <td><input type="number" step="any" class="fmu-row-qty" value="${sug != null ? sug : 0}" style="width:90px" ${matLots.length ? "" : "disabled"}/></td>
          <td>${altUomFieldHtml(mat, `class="fmu-row-uom"${matLots.length ? "" : " disabled"}`, 60)}</td>
          <td><button class="btn sm" data-fmadd="${esc(mid)}" ${matLots.length ? "" : "disabled"}>Thêm</button></td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>` : `<h4 style="margin-top:14px">+ Thêm nguyên liệu</h4>
    <div class="muted" style="font-size:12px;margin-bottom:4px">Chọn nguyên liệu ở Kho phân xưởng sẽ tự hiện "Gợi ý" (số lượng đã khai báo lúc lập Lệnh lọc) và tự điền tạm vào ô SL — chỉ là gợi ý, sửa lại SL theo thực tế dùng.</div>
    <div class="row">
      <div class="field" style="min-width:300px"><label>Chọn từ tồn kho Kho phân xưởng</label><select id="fmu_lot">${lotOpts}</select></div>
      <div class="field"><label>Hoặc tên tự do</label><input id="fmu_name" placeholder="(nếu không chọn ở trên)"/></div>
      <div class="field"><label>Gợi ý (Lệnh lọc)</label><input id="fmu_qty_sug" value="—" disabled style="width:100px;opacity:.7"/></div>
      <div class="field"><label>SL thực tế</label><input id="fmu_qty" type="number" value="0"/></div>
      <div class="field"><label>ĐVT</label><span id="fmu_uom_wrap"></span></div>
      <button class="btn" id="fmu_add" style="align-self:flex-end">Thêm</button>
    </div>`}`);
  document.querySelectorAll("[data-fmadd]").forEach(b => b.onclick = () => guard(async () => {
    const row = b.closest("tr");
    const lotSel = row.querySelector(".fmu-row-lot");
    const lotId = lotSel ? lotSel.value : null;
    const mat = matById[b.dataset.fmadd];
    const uomVal = row.querySelector(".fmu-row-uom").value.trim() || "kg";
    const qty = altUomToBaseQty(mat, parseFloat(row.querySelector(".fmu-row-qty").value), uomVal);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    await POST(`/brewing/filters/${filterId}/materials`, { lot_id: lotId, material_name: null, quantity: qty, uom: mat ? mat.uom : uomVal });
    toast("Đã thêm nguyên liệu cho mẻ lọc" + (lotId ? " — đã trừ tồn Kho phân xưởng" : "")); openFilterMaterialsModal(filterId, filterOrderId, filterCode);
  }));
  const refreshFmuUom = () => {
    const opt = $("fmu_lot").selectedOptions[0];
    const materialId = opt ? opt.dataset.material : "";
    $("fmu_uom_wrap").innerHTML = altUomFieldHtml(materialId ? matById[materialId] : null, "fmu_uom", 60);
  };
  if ($("fmu_lot")) $("fmu_lot").onchange = () => {
    const opt = $("fmu_lot").selectedOptions[0];
    const materialId = opt ? opt.dataset.material : "";
    const sug = materialId ? sugByMaterialId[materialId] : null;
    $("fmu_qty_sug").value = sug != null ? sug : "—";
    if (sug != null && (!$("fmu_qty").value || parseFloat($("fmu_qty").value) === 0)) {
      $("fmu_qty").value = sug;
    }
    refreshFmuUom();
  };
  if ($("fmu_lot")) refreshFmuUom();
  if ($("fmu_add")) $("fmu_add").onclick = () => guard(async () => {
    const lotId = $("fmu_lot").value || null;
    const name = bomMaterialIds.size ? null : ($("fmu_name")?.value.trim() || null);
    if (!lotId && !name) throw new Error("Chọn nguyên liệu từ tồn kho Kho phân xưởng" + (bomMaterialIds.size ? " (đúng vật tư của Lệnh lọc)." : ", hoặc nhập tên tự do."));
    const lotOpt = $("fmu_lot").selectedOptions[0];
    const mat = lotOpt && lotOpt.dataset.material ? matById[lotOpt.dataset.material] : null;
    const qty = altUomToBaseQty(mat, parseFloat($("fmu_qty").value), $("fmu_uom").value);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    await POST(`/brewing/filters/${filterId}/materials`, {
      lot_id: lotId, material_name: name, quantity: qty, uom: mat ? mat.uom : ($("fmu_uom").value.trim() || "kg") });
    toast("Đã thêm nguyên liệu cho mẻ lọc" + (lotId ? " — đã trừ tồn Kho phân xưởng" : "")); openFilterMaterialsModal(filterId, filterOrderId, filterCode);
  });
  document.querySelectorAll("[data-savefusage]").forEach(b => b.onclick = () => guard(async () => {
    const usageId = b.dataset.savefusage;
    const mat = b.dataset.lotid ? (lotById[b.dataset.lotid] ? matById[lotById[b.dataset.lotid].material_id] : null) : null;
    const uomVal = document.querySelector(`.fmu-edit-uom[data-usage="${usageId}"]`).value.trim() || "kg";
    const qty = altUomToBaseQty(mat, parseFloat(document.querySelector(`.fmu-edit-qty[data-usage="${usageId}"]`).value), uomVal);
    if (!qty || qty <= 0) throw new Error("Số lượng phải > 0.");
    await PUT(`/brewing/filters/${filterId}/materials/${usageId}`, {
      lot_id: b.dataset.lotid || null, receipt_id: b.dataset.receipt || null, material_name: b.dataset.name,
      lot_pm: b.dataset.lot || null, quantity: qty, uom: mat ? mat.uom : uomVal });
    toast("Đã lưu"); openFilterMaterialsModal(filterId, filterOrderId, filterCode);
  }));
  document.querySelectorAll("[data-delfusage]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Xóa dòng nguyên liệu đã ghi cho mẻ lọc này? Không thể hoàn tác.")) return;
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
    if (!confirm("Xóa dòng nguyên liệu đã ghi cho mẻ chiết này? Không thể hoàn tác.")) return;
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
          <button class="btn sm sec" data-cip="brew_batch|${esc(b.batch_id)}|${esc(b.batch_code)}">CIP</button>
          ${locked ? "" : `<button class="btn sm sec" data-editbatch="${esc(b.batch_id)}">Sửa</button>
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
  // Mỗi nút mở modal con dưới đây truyền kèm goBack — bấm "‹ Quay lại" trong modal con sẽ
  // render lại đúng modal danh sách này (dữ liệu mới nhất) thay vì chỉ đóng mất ngữ cảnh.
  const goBack = () => openBrewBatchesModal(brewId, brewCode, productId, locked);
  document.querySelectorAll("[data-editbatch]").forEach(b => b.onclick = () => {
    const batch = batches.find(x => x.batch_id === b.dataset.editbatch);
    openEditBrewBatchModal(batch, async ({ code, started_at, ended_at }) => {
      if (code) await PUT(`/brewing/brews/${brewId}/batches/${batch.batch_id}/code`, { batch_code: code });
      if (started_at) await POST(`/brewing/brews/${brewId}/batches/${batch.batch_id}/start`, { started_at });
      if (ended_at) await POST(`/brewing/brews/${brewId}/batches/${batch.batch_id}/finish`, { ended_at });
      toast("Đã lưu mẻ"); render("process"); openBrewBatchesModal(brewId, brewCode, productId, locked);
    }, goBack);
  });
  document.querySelectorAll("[data-stageqc]").forEach(b => b.onclick = () => {
    const [stage, scopeType, scopeId, pid, fpid, displayOverride, beerTypeId] = b.dataset.stageqc.split("|");
    if (MULTI_SAMPLE_STAGES.includes(stage)) {
      openFermentQcSampleModal(stage, scopeType, scopeId, pid || null, goBack);
      return;
    }
    openStageQcModal(stage, scopeType, scopeId, { productId: pid || null, finishedProductId: fpid || null,
      beerTypeId: beerTypeId || null, displayId: displayOverride || scopeId.split("__")[0] }, goBack);
  });
  document.querySelectorAll("[data-nvl]").forEach(b => b.onclick = () => {
    const [bId, batchId, batchCode] = b.dataset.nvl.split("|");
    openBrewMaterialsModal(bId, batchId, batchCode, goBack);
  });
  if ($("bb_copynvl")) $("bb_copynvl").onclick = () => guard(async () => {
    const first = batches[0];
    const targetId = $("bb_copytarget").value;
    const target = batches.find(b => b.batch_id === targetId);
    await openCopyMaterialsSuggestModal(brewId, first, target, () => openBrewBatchesModal(brewId, brewCode, productId, locked));
  });
  document.querySelectorAll("[data-processlog]").forEach(b => b.onclick = () => {
    const [bId, batchId, batchCode] = b.dataset.processlog.split("|");
    openBrewProcessLogModal(bId, batchId, batchCode, goBack);
  });
  document.querySelectorAll("[data-cip]").forEach(b => b.onclick = () => {
    const [scopeType, scopeId, label] = b.dataset.cip.split("|");
    window.openCipLinkModal(scopeType, scopeId, label, goBack);
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
  { key: "order_number", label: "Order Number", kind: "text", required: true },
  { key: "batch_number", label: "Batch Number", kind: "text", required: true },
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
    <label>${esc(f.label)}${f.required ? ' <span style="color:var(--red)">*</span>' : ""}</label>${_bfInput(f.key, f.kind, data.manual?.[f.key], "fl-manual")}
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
    if (!payload.order_number || !payload.batch_number) {
      toast("Order Number và Batch Number là bắt buộc.", "err");
      return;
    }
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

async function openBrewOrderModal(orderId) {
  const o = await GET(`/brewing/orders/${orderId}`);
  const lines = o.lines || [];
  const shortageCount = lines.filter(l => l.shortage).length;
  modal(`<h3>Lệnh nấu — <code class="k">${esc(o.order_code)}</code></h3>
    <div class="muted" style="margin-bottom:8px">
      Dịch bia: <b>${esc(o.product_code || o.product_desc || "—")}</b> ·
      Công thức: <b>${o.recipe_code ? esc(o.recipe_code) + " v" + o.recipe_version_no : "—"}</b>${o.recipe_name ? ` — ${esc(o.recipe_name)}` : ""}${o.recipe_note ? ` (${esc(o.recipe_note)})` : ""} ·
      Số mẻ KH: <b>${o.planned_batch_count}</b> ·
      Sản lượng thực tế/KH: <b>${o.actual_volume_hl}/${o.planned_volume_hl} hl</b> (±${o.volume_tolerance_hl}hl)<br/>
      ${o.is_complete
        ? `<span style="color:var(--green)">✓ Hoàn thành — mã nấu ${o.records.map(r => esc(r.brew_code)).join(", ")}</span>`
        : (o.is_executed
            ? `<span class="muted">Đang nấu — mã nấu ${o.records.map(r => esc(r.brew_code)).join(", ")}</span>`
            : `<span class="muted">Chưa thực hiện nấu</span>`)}
      ${shortageCount ? ` · <span style="color:var(--red)">⚠ ${shortageCount} dòng NVL không đủ tồn (tại thời điểm lập phiếu)</span>` : ""}
      ${o.issued_by ? `<br/>Người ra lệnh: ${esc(o.issued_by)}` : ""}
    </div>
    <div class="tablewrap" style="max-height:50vh"><table>
      <thead><tr><th>STT</th><th>Tên NVL</th><th>ĐVT</th><th>Nhu cầu 1 mẻ</th><th>Nhu cầu Tổng mẻ</th>
        <th>SL lấy tại Kho công ty</th><th>SL lấy tại Kho phân xưởng</th>
        <th>Tồn Kho công ty (lúc lập)</th><th>Tồn Kho phân xưởng (lúc lập)</th><th>Đơn giá</th><th></th></tr></thead>
      <tbody>${lines.map(l => l.is_header
        ? `<tr style="font-weight:700"><td colspan=11>${esc(l.stt_label || "")} ${esc(l.material_name || "")}</td></tr>`
        : `<tr class="${l.shortage ? "row-red" : ""}"><td>${esc(l.stt_label || "")}</td><td>${esc(l.material_name || "—")}</td>
          <td>${esc(l.uom || "")}</td><td>${l.qty_per_batch ?? "—"}</td><td>${l.qty_total ?? "—"}</td>
          <td>${l.qty_from_company ?? "—"}</td><td>${l.qty_from_workshop ?? "—"}</td>
          <td>${l.stock_company_snapshot ?? "—"}</td><td>${l.stock_workshop_snapshot ?? "—"}</td>
          <td>${l.unit_price ?? "—"}</td><td>${l.shortage ? `<span style="color:var(--red)">⚠ Thiếu</span>` : `<span style="color:var(--green)">Đủ</span>`}</td></tr>${bomMemberRowsHtml(l, 3, 2, true)}`).join("") ||
        `<tr><td colspan=11 class="muted">Chưa có dòng NVL.</td></tr>`}</tbody></table></div>`);
}

// ---- Modal: xem Lệnh sản xuất (ERP) — mirror openBrewOrderModal (Lệnh nấu); o.lines
// là định mức NVL ĐÃ LƯU lúc lập/sửa lệnh (SL lấy tại 2 kho + thành viên Nhóm vật tư đã chọn)
// — xem services/orders.py::get_order. ----
async function openProductionOrderModal(orderId) {
  const o = await GET(`/orders/${orderId}`);
  const lines = o.lines || [];
  modal(`<h3>Lệnh sản xuất (ERP) — <code class="k">${esc(o.order_code)}</code></h3>
    <div class="muted" style="margin-bottom:8px">
      Sản phẩm: <b>${esc(prodName(o.product_id))}</b> · SL kế hoạch: <b>${o.planned_qty} ${esc(o.uom)}</b> · Ưu tiên: <b>${o.priority}</b> ·
      ${badge(o.status)}${esc(o.status)}
      ${o.issued_by ? `<br/>Người ra lệnh: ${esc(o.issued_by)}` : ""}
      ${o.recipe_code ? `<br/>Công thức: <b>${esc(o.recipe_code)} v${o.recipe_version_no}</b>${o.recipe_name ? " — " + esc(o.recipe_name) : ""}${o.recipe_note ? ` (${esc(o.recipe_note)})` : ""} · Số mẻ KH: <b>${o.planned_batch_count ?? "—"}</b>` : ""}
    </div>
    <div class="tablewrap" style="max-height:50vh"><table>
      <thead><tr><th>STT</th><th>Tên NVL</th><th>ĐVT</th><th>Nhu cầu 1 mẻ</th><th>Nhu cầu Tổng mẻ</th>
        <th>SL lấy tại Kho công ty</th><th>SL lấy tại Kho phân xưởng</th>
        <th>Tồn Kho công ty</th><th>Tồn Kho phân xưởng</th><th>Đơn giá</th><th></th></tr></thead>
      <tbody>${lines.map(l => l.is_header
        ? `<tr style="font-weight:700"><td colspan=11>${esc(l.stt_label || "")} ${esc(l.material_name || "")}</td></tr>`
        : `<tr class="${l.shortage ? "row-red" : ""}"><td>${esc(l.stt_label || "")}</td><td>${esc(l.material_name || "—")}</td>
          <td>${esc(l.uom || "")}</td><td>${l.qty_per_batch ?? "—"}</td><td>${l.qty_total ?? "—"}</td>
          <td>${l.qty_from_company ?? "—"}</td><td>${l.qty_from_workshop ?? "—"}</td>
          <td>${l.stock_company_snapshot ?? "—"}</td><td>${l.stock_workshop_snapshot ?? "—"}</td>
          <td>${l.unit_price ?? "—"}</td><td>${l.shortage ? `<span style="color:var(--red)">⚠ Thiếu</span>` : `<span style="color:var(--green)">Đủ</span>`}</td></tr>${bomMemberRowsHtml(l, 3, 2, true)}`).join("") ||
        `<tr><td colspan=11 class="muted">Chưa có dòng NVL${o.recipe_version_id ? "" : " (chưa chọn công thức)"}.</td></tr>`}</tbody></table></div>`);
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
      <h4 style="font-size:13px;margin:0 0 6px">Tank thành phẩm #${ci + 1}</h4>
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
        <tbody>${c.lines.map(l => `<tr><td>${esc(l.material_name || "—")}${l.material_group_code ? ' <span class="muted">(nhóm vật tư thay thế)</span>' : ""}</td><td>${esc(l.uom || "")}</td>
          <td>${l.quantity}</td><td>${l.stock_company_snapshot ?? "—"}</td>
          <td>${l.stock_workshop_snapshot ?? "—"}</td><td>${l.unit_price ?? "—"}</td></tr>${bomMemberRowsHtml(l, 3, 1)}`).join("") ||
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
      <h3 style="margin-top:0">Tank thành phẩm #${ci + 1}</h3>
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

function printBrewOrder(o) {
  const dash = (v) => (v === null || v === undefined || v === "" ? "—" : esc(String(v)));
  const blank = (v) => (v === null || v === undefined || v === "" ? "" : esc(String(v)));
  const safetyText = o.safety_note ||
    "Thực hiện đúng quy trình vận hành thiết bị, chỉ vận hành khi thống nhất thông tin giữa thợ chính và thợ phụ, các bộ phận khác có liên quan.";
  const lines = o.lines || [];
  const lineRows = lines.map(l => {
    if (l.is_header) return `<tr><td colspan=10 style="font-weight:700">${dash(l.stt_label)} ${dash(l.material_name)}</td></tr>`;
    // Cột "Tổng mẻ" (Lượng) in đúng phần SL lấy tại Kho công ty — không phải Nhu cầu Tổng mẻ đầy
    // đủ (l.qty_total): phần còn lại đã có sẵn tại Kho phân xưởng, không cần xuất thêm. Cột
    // "Thực xuất" để trống hoàn toàn cho thủ kho tự ghi tay lúc xuất thực tế.
    // Dòng Nhóm vật tư khai định mức riêng từng thành viên (member_breakdown có qty_per_batch)
    // — in thêm 1 dòng con mỗi mã ĐÃ CHỌN, kèm đúng mã + định mức riêng của mã đó, để thủ kho
    // biết chính xác cần xuất mã nào bao nhiêu (không chỉ thấy tên nhóm chung).
    const memberRows = (l.member_breakdown || []).filter(mb => mb.qty_per_batch != null).map(mb =>
      `<tr><td></td><td style="padding-left:14px">↳ ${dash(mb.material_code)} — ${dash(mb.material_name)}</td><td>${dash(l.uom)}</td>
        <td>${dash(mb.qty_per_batch)}</td><td>${dash(mb.qty_from_company)}</td><td></td><td></td>
        <td></td><td></td><td></td></tr>`).join("");
    return `<tr><td>${dash(l.stt_label)}</td><td>${dash(l.material_name)}</td><td>${dash(l.uom)}</td>
        <td>${dash(l.qty_per_batch)}</td><td>${dash(l.qty_from_company)}</td><td></td><td></td>
        <td>${blank(l.unit_price)}</td><td></td><td></td></tr>${memberRows}`;
  }).join("");
  const orderSection = `<div class="pf-section" style="border:1px solid #000;padding:6px;margin-bottom:10px">
    <div>1/ Nấu: - Bia .......................................... mã số ........................................................ Số lượng: <b>${dash(o.planned_batch_count)}</b> mẻ ≥ <b>${dash(o.planned_volume_hl)}</b> hl dịch${o.bx_min || o.bx_max ? `, với Bx: ${dash(o.bx_min)}-${dash(o.bx_max)}%` : ""}</div>
    <div>- Chuyển dịch vào Tank lên men: ...........................................................................................................</div>
    <table class="pf-tbl"><thead>
      <tr><th rowspan=2>STT</th><th rowspan=2>Tên, nhãn hiệu quy cách NVL</th><th rowspan=2>ĐVT</th>
        <th colspan=2>Lượng</th><th colspan=2>Thực xuất</th><th rowspan=2>Đơn giá</th><th colspan=2>T/Tiền (đồng)</th></tr>
      <tr><th>Nhu cầu 1 mẻ</th><th>Tổng mẻ</th><th>1 mẻ</th><th>Tổng mẻ</th><th>Nhu cầu</th><th>Thực lĩnh</th></tr>
    </thead>
    <tbody>${lineRows || '<tr><td colspan=10 style="text-align:center">—</td></tr>'}
      <tr style="font-weight:700"><td colspan=8 style="text-align:right">TỔNG GIÁ TRỊ</td><td></td><td></td></tr>
    </tbody></table>
  </div>`;
  const html = `<!doctype html><html><head><meta charset="utf-8"/><title>Lệnh nấu — ${esc(o.order_code)}</title>
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
      .pf-sign{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:30px;text-align:center;font-size:11.5px}
      .pf-sign b{display:block;margin-bottom:2px}
      .pf-sign span{display:block;color:#555;margin-bottom:40px}
    </style></head><body>
    <div class="pf-header">
      <div><b>CÔNG TY CP BIA &amp; NGK ĐÔNG MAI</b><br/>Pxsx bia ĐM<br/>Số: ${dash(o.order_code)}</div>
      <div class="right"><b>CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM</b><br/>Độc lập – Tự do – Hạnh phúc</div>
    </div>
    <h2>LỆNH NẤU BIA KIÊM PHIẾU XUẤT KHO</h2>
    <div class="pf-section"><h3>I. Người ra lệnh</h3><div>${dash(o.issued_by || o.created_by)}</div></div>
    <div class="pf-section"><h3>II. Người nhận lệnh</h3>
      <div>1/ Người T/hiện: ${dash(o.executor_unit)}</div>
      <div>2/ Người xuất hàng: ${dash(o.warehouse_keeper)}</div></div>
    <div class="pf-section"><h3>III. Nội dung thực hiện</h3>
      ${o.reference_note ? `<div>${dash(o.reference_note)}</div>` : ""}
      ${orderSection}
    </div>
    <div class="pf-section"><h3>IV. Thời gian thực hiện</h3>
      <div>Bắt đầu: Ngày ${o.start_date ? fmt(o.start_date) : "......."} — Ca: .......</div>
      <div>Kết thúc: Ngày ${o.end_date ? fmt(o.end_date) : "......."} — Ca: .......</div></div>
    <div class="pf-section"><h3>V. Biện pháp an toàn</h3><div>${dash(safetyText)}</div></div>
    <div class="pf-sign">
      <div><b>Giám đốc</b><span>(Ký, ghi rõ họ tên)</span></div>
      <div><b>Quản đốc phân xưởng sản xuất</b><span>(Ký, ghi rõ họ tên)</span></div>
      <div><b>Người nhận lệnh</b><span>${dash(o.executor_unit)}<br/>(Ký, ghi rõ họ tên)</span></div>
      <div><b>Thủ kho</b><span>${dash(o.warehouse_keeper)}<br/>(Ký, ghi rõ họ tên)</span></div>
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

// In Lệnh sản xuất (ERP) — mirror printBrewOrder nhưng KHÔNG có nhiều "lệnh nhỏ" (1 Lệnh SX =
// 1 dòng), nên chỉ có 1 khối nội dung thay vì lặp childSections.
function printProductionOrder(o, lines) {
  const dash = (v) => (v === null || v === undefined || v === "" ? "—" : esc(String(v)));
  const blank = (v) => (v === null || v === undefined || v === "" ? "" : esc(String(v)));
  const safetyText = o.safety_note ||
    "Thực hiện đúng quy trình vận hành thiết bị, chỉ vận hành khi thống nhất thông tin giữa thợ chính và thợ phụ, các bộ phận khác có liên quan.";
  const lineRows = (lines || []).map(l => {
    if (l.is_header) return `<tr><td colspan=10 style="font-weight:700">${dash(l.stt_label)} ${dash(l.material_name)}</td></tr>`;
    const memberRows = (l.member_breakdown || []).filter(mb => mb.qty_per_batch != null).map(mb =>
      `<tr><td></td><td style="padding-left:14px">↳ ${dash(mb.material_code)} — ${dash(mb.material_name)}</td><td>${dash(l.uom)}</td>
        <td>${dash(mb.qty_per_batch)}</td><td>${dash(mb.qty_from_company)}</td><td></td><td></td>
        <td></td><td></td><td></td></tr>`).join("");
    return `<tr><td>${dash(l.stt_label)}</td><td>${dash(l.material_name)}</td><td>${dash(l.uom)}</td>
        <td>${dash(l.qty_per_batch)}</td><td>${dash(l.qty_from_company)}</td><td></td><td></td>
        <td>${blank(l.unit_price)}</td><td></td><td></td></tr>${memberRows}`;
  }).join("");
  const html = `<!doctype html><html><head><meta charset="utf-8"/><title>Lệnh sản xuất — ${esc(o.order_code)}</title>
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
      .pf-sign{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:30px;text-align:center;font-size:11.5px}
      .pf-sign b{display:block;margin-bottom:2px}
      .pf-sign span{display:block;color:#555;margin-bottom:40px}
    </style></head><body>
    <div class="pf-header">
      <div><b>CÔNG TY CP BIA &amp; NGK ĐÔNG MAI</b><br/>Pxsx bia ĐM<br/>Số: ${dash(o.order_code)}</div>
      <div class="right"><b>CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM</b><br/>Độc lập – Tự do – Hạnh phúc</div>
    </div>
    <h2>LỆNH SẢN XUẤT KIÊM PHIẾU XUẤT KHO</h2>
    <div class="pf-section"><h3>I. Người ra lệnh</h3><div>${dash(o.issued_by || o.created_by)}</div></div>
    <div class="pf-section"><h3>II. Người nhận lệnh</h3>
      <div>1/ Người T/hiện: ${dash(o.executor_unit)}</div>
      <div>2/ Người xuất hàng: ${dash(o.warehouse_keeper)}</div></div>
    <div class="pf-section"><h3>III. Nội dung thực hiện</h3>
      ${o.reference_note ? `<div>${dash(o.reference_note)}</div>` : ""}
      <div class="pf-section" style="border:1px solid #000;padding:6px;margin-bottom:10px">
        <div>Sản phẩm: <b>${dash(prodName(o.product_id))}</b> · Số lượng: <b>${dash(o.planned_qty)} ${dash(o.uom)}</b>${o.planned_batch_count ? ` ≈ <b>${dash(o.planned_batch_count)}</b> mẻ` : ""}${o.recipe_code ? ` · Công thức: ${dash(o.recipe_code)} v${o.recipe_version_no}` : ""}</div>
        <table class="pf-tbl"><thead>
          <tr><th rowspan=2>STT</th><th rowspan=2>Tên, nhãn hiệu quy cách NVL</th><th rowspan=2>ĐVT</th>
            <th colspan=2>Lượng</th><th colspan=2>Thực xuất</th><th rowspan=2>Đơn giá</th><th colspan=2>T/Tiền (đồng)</th></tr>
          <tr><th>Nhu cầu 1 mẻ</th><th>Tổng mẻ</th><th>1 mẻ</th><th>Tổng mẻ</th><th>Nhu cầu</th><th>Thực lĩnh</th></tr>
        </thead>
        <tbody>${lineRows || '<tr><td colspan=10 style="text-align:center">—</td></tr>'}
          <tr style="font-weight:700"><td colspan=8 style="text-align:right">TỔNG GIÁ TRỊ</td><td></td><td></td></tr>
        </tbody></table>
      </div>
    </div>
    <div class="pf-section"><h3>IV. Thời gian thực hiện</h3>
      <div>Bắt đầu: Ngày ${o.start_date ? fmt(o.start_date) : "......."} — Ca: .......</div>
      <div>Kết thúc: Ngày ${o.end_date ? fmt(o.end_date) : "......."} — Ca: .......</div></div>
    <div class="pf-section"><h3>V. Biện pháp an toàn</h3><div>${dash(safetyText)}</div></div>
    <div class="pf-sign">
      <div><b>Giám đốc</b><span>(Ký, ghi rõ họ tên)</span></div>
      <div><b>Quản đốc phân xưởng sản xuất</b><span>(Ký, ghi rõ họ tên)</span></div>
      <div><b>Người nhận lệnh</b><span>${dash(o.executor_unit)}<br/>(Ký, ghi rõ họ tên)</span></div>
      <div><b>Thủ kho</b><span>${dash(o.warehouse_keeper)}<br/>(Ký, ghi rõ họ tên)</span></div>
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
    type_label: shipment.shipment_type === "promo" ? "Khuyến mại" : shipment.shipment_type === "return" ? "Đổi trả" :
      shipment.shipment_type === "mixed" ? "Nhiều loại (xem chi tiết dòng)" : "Bán hàng thường",
    note: shipment.note,
    driver_name: shipment.driver_name,
    vehicle_plate: shipment.vehicle_plate,
    from_location: shipment.from_location,
    delivery_place: shipment.delivery_place,
    lines: shipment.lines.map(l => ({ name: nameByCode[l.product] || l.product, code: l.product, uom: "Thùng", qty: l.quantity })),
  });
  openPrintWindow(html);
}

async function openBrewProcessLogModal(brewId, batchId, batchCode, onBack) {
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
    <button class="btn" id="pl_save" style="margin-top:12px">Lưu ghi chép</button>`, onBack);

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
    openBrewProcessLogModal(brewId, batchId, batchCode, onBack);
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
          <div style="font-size:26px;font-weight:700;color:var(--accent2)">${erpt.total_system.toLocaleString("vi-VN")} <span style="font-size:14px;font-weight:400">kWh</span></div>
        </div>
        <div class="panel" style="flex:1;min-width:220px">
          <div class="muted" style="font-size:12px">TỔNG AED TIÊU THỤ TÍNH THEO TRẠM VÀ MÁY PHÁT</div>
          <div style="font-size:26px;font-weight:700;color:var(--green)">${erpt.total_station.toLocaleString("vi-VN")} <span style="font-size:14px;font-weight:400">kWh</span></div>
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
          <div style="font-size:26px;font-weight:700;color:var(--green)">${rpt.total_kwh.toLocaleString("vi-VN")} <span style="font-size:14px;font-weight:400">kWh</span></div>
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
        <div class="tablewrap"><table id="t_elecca_${site}"><thead><tr><th>Ngày</th><th>Ca</th><th>Bắt đầu</th><th>Kết thúc</th><th>Điện (kWh)</th></tr></thead>
        <tbody>${rpt.shifts.map(s => `<tr><td>${fmt(s.date)}</td><td>Ca ${s.ca}${s.data_gap ? ' ⚠' : ""}</td>
          <td class="muted">${new Date(s.start).toLocaleString("vi-VN")}</td><td class="muted">${new Date(s.end).toLocaleString("vi-VN")}</td>
          <td${s.data_gap ? ' title="1+ hệ thống bị khoảng trống dữ liệu trong ca này — số có thể thiếu"' : ""}>${s.value.toLocaleString("vi-VN")}</td></tr>`).join("") ||
          '<tr><td colspan=5 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div></div>`;
    wirePaginate(`t_elecca_${site}`, 10);
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
      <input class="searchbox" data-tbl="t_equipment" placeholder="Tìm theo mã, tên, loại, hệ thống..."/>
      <table id="t_equipment"><thead><tr><th>Mã</th><th>Tên</th><th>Loại</th><th>Hệ thống</th><th>Vị trí</th><th>Trạng thái</th></tr></thead>
      <tbody>${eqs.map(e => `<tr><td><code class="k">${esc(e.code)}</code></td><td>${esc(e.name)}</td><td class="muted">${esc(e.eq_type || "")}</td>
        <td class="muted">${esc(e.system || "")}</td><td class="muted">${esc(e.location || "")}</td><td>${badge(e.status)}</td></tr>`).join("")}</tbody></table></div>`;
  } else if (sec === "parts") {
    const parts = await GET("/maint/parts");
    body = `<div class="panel"><h2>Danh mục phụ tùng</h2>
      <input class="searchbox" data-tbl="t_parts" placeholder="Tìm theo mã, tên..."/>
      <table id="t_parts"><thead><tr><th>Mã</th><th>Tên</th><th>Tồn</th><th>Tồn min</th><th>Cảnh báo</th></tr></thead>
      <tbody>${parts.map(p => `<tr><td><code class="k">${esc(p.code)}</code></td><td>${esc(p.name)}</td><td>${p.stock} ${p.uom}</td>
        <td>${p.stock_min}</td><td>${p.below_min ? badge("overdue") + "Dưới mức min" : badge("ok") + "OK"}</td></tr>`).join("")}</tbody></table></div>`;
  }
  $("view-maint").innerHTML = subnav("maint", sections, sec) + body;
  wireSubnav("maint"); wireSearch();
  wirePaginate("t_incidents", 10); wirePaginate("t_plans", 10);
  wirePaginate("t_equipment", 10); wirePaginate("t_parts", 10);
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
// Xác định kiểu dữ liệu của 1 cột (để sắp xếp đúng — số/ngày giờ so bằng giá trị thực,
// không phải so chuỗi) bằng cách lấy mẫu đa số ô không rỗng trong cột đó khớp mẫu nào.
// KHỚP với 2 định dạng ngày giờ duy nhất đang dùng trong app (xem hàm `fmt()` ở đầu file).
function _sortColType(texts) {
  const nonEmpty = texts.map(t => (t || "").trim()).filter(t => t && t !== "—");
  if (!nonEmpty.length) return "string";
  const dtRe = /^\d{1,2}:\d{1,2}:\d{1,2}\s+\d{1,2}\/\d{1,2}\/\d{4}$/;
  const dRe = /^\d{1,2}\/\d{1,2}\/\d{4}$/;
  const numRe = /^-?\d+(?:[.,]\d+)?(?:\s|$)/;
  const ratio = (re) => nonEmpty.filter(t => re.test(t)).length / nonEmpty.length;
  if (ratio(dtRe) >= 0.8) return "datetime";
  if (ratio(dRe) >= 0.8) return "date";
  if (ratio(numRe) >= 0.8) return "number";
  return "string";
}
// Chuyển 1 ô về giá trị so sánh được theo kiểu cột đã xác định — trả về null cho ô rỗng/"—"
// để luôn đẩy xuống CUỐI danh sách bất kể đang sắp xếp tăng hay giảm (giống Windows Explorer).
function _sortCellValue(type, raw) {
  const t = (raw || "").trim();
  if (!t || t === "—") return null;
  if (type === "datetime" || type === "date") {
    const m = t.match(type === "datetime"
      ? /^(\d{1,2}):(\d{1,2}):(\d{1,2})\s+(\d{1,2})\/(\d{1,2})\/(\d{4})$/
      : /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (!m) return null;
    const n = m.slice(1).map(Number);
    return type === "datetime" ? new Date(n[5], n[4] - 1, n[3], n[0], n[1], n[2]).getTime()
                                : new Date(n[2], n[1] - 1, n[0]).getTime();
  }
  if (type === "number") {
    const m = t.match(/^-?\d+(?:[.,](\d+))?/);
    return m ? parseFloat(m[0].replace(",", ".")) : null;
  }
  return t.toLowerCase();
}
function _sortCompare(a, b, type, dir) {
  if (a == null && b == null) return 0;
  if (a == null) return 1;   // ô rỗng luôn ở cuối
  if (b == null) return -1;
  if (type === "string") return dir * a.localeCompare(b, "vi");
  return dir * (a < b ? -1 : a > b ? 1 : 0);
}
// Cộng tổng SL theo ĐVT từ 1 danh sách <tr> có gắn data-qty/data-uom (xem sumTotalsHtml ở
// dưới) — tách riêng theo ĐVT vì các vật tư trong 1 bảng thường khác đơn vị (kg/Lon/Cái...),
// cộng lẫn sẽ ra số vô nghĩa.
function sumQtyByUom(trs) {
  const totals = {};
  trs.forEach(tr => {
    const q = parseFloat(tr.dataset.qty);
    const u = tr.dataset.uom;
    if (!isFinite(q) || !u) return;
    totals[u] = (totals[u] || 0) + q;
  });
  return totals;
}
function sumTotalsHtml(trs) {
  const totals = sumQtyByUom(trs);
  const entries = Object.entries(totals);
  if (!entries.length) return '<span class="muted">0</span>';
  return entries.map(([u, q]) => `<b>${Math.round(q * 1000) / 1000}</b> ${esc(u)}`).join(" + ");
}
function wirePaginate(tableId, defaultPageSize = 10, opts = {}) {
  const table = document.getElementById(tableId);
  if (!table) return;
  table.dataset.paginated = "1";
  const tbody = table.querySelector("tbody");
  let allRows = Array.from(tbody.children);
  const searchInput = document.querySelector(`.searchbox[data-tbl="${tableId}"]`);
  const state = _pagerState[tableId] || { page: 1, pageSize: defaultPageSize, sortCol: null, sortDir: 1 };
  if (state.sortCol === undefined) { state.sortCol = null; state.sortDir = 1; }
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
  function cellText(tr, idx) {
    const cell = tr.children[idx];
    if (!cell) return "";
    const field = cell.querySelector("input, select");
    if (field) return field.tagName === "SELECT" ? (field.selectedOptions[0]?.textContent || "") : field.value;
    return cell.textContent || "";
  }
  // Sắp xếp kiểu bấm vào tiêu đề cột như Windows Explorer — bấm lần 1 tăng dần, bấm lại đảo
  // chiều. Sắp xếp TOÀN BỘ allRows (không chỉ trang đang xem) rồi mới lọc/cắt trang ở apply(),
  // và di chuyển thẳng <tr> trong DOM (KHÔNG render lại) để giữ nguyên input đang gõ dở trên
  // các bảng danh mục cho sửa trực tiếp.
  function sortRows() {
    if (state.sortCol == null) return;
    const idx = state.sortCol;
    const type = _sortColType(allRows.map(tr => cellText(tr, idx)));
    const withVal = allRows.map(tr => [tr, _sortCellValue(type, cellText(tr, idx))]);
    withVal.sort((a, b) => _sortCompare(a[1], b[1], type, state.sortDir));
    allRows = withVal.map(p => p[0]);
    allRows.forEach(tr => tbody.appendChild(tr));
  }
  function wireSortHeaders() {
    const headRow = table.querySelector("thead tr");
    if (!headRow) return;
    // Bảng tiêu đề nhiều dòng/gộp ô (colspan/rowspan, VD ma trận CIP, dữ liệu thô Braumat) thì
    // chỉ số cột không khớp 1-1 với dữ liệu — bỏ qua, không bật sắp xếp để tránh sai lệch.
    const complex = Array.from(headRow.children).some(th => th.colSpan > 1 || th.rowSpan > 1);
    if (complex) return;
    Array.from(headRow.children).forEach((th, idx) => {
      th.querySelector(".sort-ind")?.remove();
      if (!th.textContent.trim()) return; // cột trống (nút thao tác) không cho sắp xếp
      th.classList.add("sortable-th");
      if (idx === state.sortCol) th.insertAdjacentHTML("beforeend", `<span class="sort-ind">${state.sortDir === 1 ? "▲" : "▼"}</span>`);
      th.onclick = () => {
        if (state.sortCol === idx) state.sortDir = -state.sortDir;
        else { state.sortCol = idx; state.sortDir = 1; }
        state.page = 1;
        sortRows();
        wireSortHeaders();
        apply();
      };
    });
  }
  sortRows();
  wireSortHeaders();

  function apply() {
    const q = (searchInput?.value || "").toLowerCase();
    const matched = q ? allRows.filter(tr => rowText(tr).includes(q)) : allRows;
    if (opts.onFilter) opts.onFilter(matched);
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
    const nlLotChip = (l) => `<code class="k">${lotCodeCellHtml(l)}</code> (${l.quantity}${l.uom}${l.status === "on_hold" ? ", CHỜ QC" : ""})`;
    body = `<div class="panel"><h2>Tồn kho NVL theo kho <span class="muted">(${stock.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Tồn kho thật từ hệ thống Kho NVL — nguyên liệu phân bổ vào mẻ nấu (nút "+NVL" ở tab Nấu) lấy từ <b>Kho phân xưởng</b>.</div>
      <div class="row" style="margin-bottom:8px"><div class="field"><label>Kho</label><select id="nl_loc">${whOpts}</select></div></div>
      <input class="searchbox" data-tbl="t_nlstock" placeholder="Tìm theo mã/tên vật tư..."/>
      <div class="tablewrap"><table id="t_nlstock"><thead><tr><th>Mã VT</th><th>Tên</th><th>Nhóm</th><th>Mã lô</th><th>Tồn</th><th>ĐVT</th></tr></thead>
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
    const ynNau = YEARS.nau;
    const [rows, fermentTanks, yeast, products, brewOrders] = await Promise.all([
      GET("/brewing/brews" + (ynNau ? "?" + ynNau.map(y => "years=" + y).join("&") : "")),
      GET("/brewing/ferment-tanks").catch(() => []), GET("/process/yeast").catch(() => []),
      GET("/products").catch(() => []), GET("/brewing/orders").catch(() => [])]);
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
    // Lệnh nấu CHƯA hoàn thành — chọn thẳng 1 lệnh để tạo mã nấu (đã bỏ lớp "lệnh nấu
    // lớn"/"lệnh nấu nhỏ" — mỗi Lệnh nấu giờ đứng phẳng, không còn 2 tầng dropdown).
    const openOrdersNau = brewOrders.filter(o => !o.is_complete);
    const orderOptsLn = `<option value="">(chọn Lệnh nấu — bắt buộc)</option>` + openOrdersNau.map(o =>
      `<option value="${esc(o.brew_order_id)}" data-wort="${esc(o.product_id || "")}" data-vol="${o.planned_volume_hl}" data-batchcount="${o.planned_batch_count != null ? o.planned_batch_count : ""}">${esc(o.order_code)} — ${esc(o.product_code || o.product_desc || "—")} — ${o.actual_volume_hl}/${o.planned_volume_hl} hl</option>`).join("");
    body = `<div class="panel"><h2>Thêm thông tin nấu</h2>
      <div class="muted" style="margin-bottom:6px">1 mã nấu = 1 lần nấu vào 1 tank — chọn <b>Tank lên men</b> để tự động chuyển mã nấu này sang lên men (xem ở tab "Lên men").
        Sau khi tạo, bấm "Mẻ" trên dòng đó để khai báo các mẻ cụ thể (số mẻ từ Braumat, VD 123,124,125,126) — mỗi mẻ nhập nguyên liệu &amp; chỉ tiêu riêng.
        Chọn <b>Lệnh nấu</b> (chưa hoàn thành) — <b>Dịch bia</b> trích tự động từ lệnh đã chọn (không sửa được, tránh lệch giữa mã nấu và lệnh) —
        nếu lệnh chưa gắn dịch bia thì chọn tay. Tạo lệnh mới ở tab "Lệnh SX → Lệnh nấu" nếu danh sách trống.
        <b>Tank lên men</b> chỉ hiện tank đang trống (không bị lô LM khác chiếm dụng).
        <b>Ngày KT (nạp đầy tank)</b> không nhập tay — tự tính bằng giờ kết thúc của mẻ cuối cùng khi vận hành bấm "Kết thúc" ở mẻ đó, hiển thị ở cột tương ứng bên dưới.</div>
      <div class="row">
        <div class="field"><label>Lệnh nấu</label><select id="nb_order">${orderOptsLn}</select></div>
        <div class="field"><label>Mã nấu</label><input id="nb_code" placeholder="VD: N-0715"/></div>
      </div>
      <div class="row">
        <div class="field"><label>Dịch bia</label><select id="nb_wort">${wortOpts}</select></div>
        <div class="field"><label>SL nấu/hl</label><input id="nb_vol" type="number" value="900"/></div>
        <div class="field"><label>Tank lên men</label><select id="nb_tank"><option value="">(chưa chuyển lên men)</option>${tankOptsNau}</select></div>
        <div class="field"><label>Men sử dụng</label><select id="nb_yeast">${yeastOpts}</select></div>
        <div class="field"><label>Số mẻ (KH)</label><input id="nb_batchcount" disabled style="width:70px" title="Số mẻ kế hoạch lấy từ Lệnh nấu đã chọn — chỉ để tham khảo khi khai báo Mẻ, số mẻ thực tế (Braumat) vẫn khai tay từng mẻ."/></div>
      </div>
      <div class="row">
        <div class="field" style="flex:1"><label>Ghi chú</label><input id="nb_note" placeholder="(tuỳ chọn)"/></div>
        <button class="btn" id="nb_add" style="align-self:flex-end">Thêm</button>
      </div></div>
      <div class="panel"><h2>Thông tin nấu <span class="muted">(${rows.length})</span></h2>
      ${yearFilterControl("nau", ynNau)}
      <input class="searchbox" data-tbl="t_nau" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_nau"><thead><tr><th>Mã nấu</th><th>Khóa mã nấu</th><th>Lệnh nấu</th><th>Ngày nấu</th><th>Ngày KT (nạp đầy tank)</th><th>Lô LM</th><th>Dịch nha</th><th>SL kế hoạch/hl</th><th>SL thực tế/hl</th>
        <th>Tank</th><th>Số mẻ</th><th></th></tr></thead>
      <tbody>${rows.map(b => `<tr class="row-${b.color}"><td class="code">${esc(b.brew_code)}</td>
        <td style="white-space:nowrap">${b.locked
            ? (isAdminLot ? `<button class="btn sm sec" data-unlocklot="brew|${esc(b.brew_id)}">Mở khóa</button>` : '<span class="muted">—</span>')
            : (canLockLot ? `<button class="btn sm" data-locklot="brew|${esc(b.brew_id)}">Khóa</button>` : '<span class="muted">—</span>')}</td>
        <td class="muted">${esc(b.brew_order_code || "—")}</td><td>${b.first_batch_started_at ? fmt(b.first_batch_started_at) : "—"}</td>
        <td class="muted">${b.kt_date ? fmt(b.kt_date) : "—"}</td><td class="muted">${esc(b.lm_code || "—")}</td>
        <td>${esc(b.wort_type)}</td><td>${b.volume_hl}</td>
        <td class="muted" title="Tổng &quot;Tổng lượng dịch&quot; (Ghi chép nấu) cộng dồn qua các mẻ">${b.actual_volume_hl ?? "—"}</td>
        <td class="muted">${esc(b.tank_lm || "—")}</td><td class="muted">${b.batch_count}</td>
        <td style="white-space:nowrap"><button class="btn sm" data-brewbatches="${esc(b.brew_id)}|${esc(b.brew_code)}|${esc(b.product_id || "")}|${b.locked ? "1" : "0"}">Mẻ (${b.batch_count})</button>
          <button class="btn sm sec" data-stageqc="nuoc_nau|brew|${esc(b.brew_id)}|||${esc(b.brew_code)}">Chỉ tiêu nước nấu</button>
          ${b.locked ? "" : `<button class="btn sm sec" data-delrec="brew|${esc(b.brew_id)}">Xóa</button>`}</td></tr>`).join("")}</tbody></table></div>
      <div class="legend">Bấm "Mẻ" để khai báo/xem các mẻ cụ thể của mã nấu này. Chú thích màu:
        <b class="red">Đỏ</b>: Có mẻ thiếu chỉ tiêu bắt buộc, hoặc đã nhập đủ nhưng có chỉ tiêu FAIL (ngoài khoảng min-max) — <b class="green">Xanh lá</b>: Đủ chỉ tiêu (không FAIL) nhưng có mẻ chưa nhập NVL —
        <b class="blue">Xanh dương</b>: Tất cả mẻ đầy đủ.</div></div>`;
  }

  else if (sec === "lenmen") {
    const ynLm = YEARS.lenmen;
    const data = await GET("/brewing/ferments" + (ynLm ? "?" + ynLm.map(y => "years=" + y).join("&") : ""));
    // Dòng còn CẦN thao tác (chưa duyệt LM và/hoặc chưa khóa lô) lên đầu bảng — dễ thấy ngay
    // việc cần làm thay vì phải tìm giữa các dòng đã xong (sort ổn định, giữ nguyên thứ tự
    // tương đối giữa các dòng cùng nhóm cần/không cần).
    data.items = [...data.items].sort((a, b) =>
      Number(!b.qc_approved || !b.locked) - Number(!a.qc_approved || !a.locked));
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
      ${yearFilterControl("lenmen", ynLm)}
      <input class="searchbox" data-tbl="t_lm" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_lm"><thead><tr><th>Duyệt</th><th>Khóa lô lên men</th><th>Lô LM</th><th>Mã nấu</th><th>Ngày nấu</th><th>Ngày KT</th><th>Số ngày đã lên men</th>
        <th>Dịch nha</th><th>Đời men</th><th>Tank LM</th><th>SL nấu/hl</th><th>Đang tồn CCT/hl</th><th>Trạng thái</th><th>Sẵn sàng chiết</th><th></th><th>Chỉ tiêu</th></tr></thead>
      <tbody>${data.items.map(r => `<tr class="row-${r.color}">
        <td style="white-space:nowrap">${r.locked ? lockBadgeHtml(r) : (r.qc_approved
            ? `<span style="color:var(--green)">✓ ${esc(r.qc_approved_by || "")}</span><div class="muted">${fmt(r.qc_approved_at)}</div>`
            : (canApproveLm ? `<button class="btn sm" data-lmapprove="${esc(r.ferment_id)}">Duyệt LM (KCS)</button>` : '<span class="muted">—</span>'))}</td>
        <td style="white-space:nowrap">${r.locked
            ? (isAdminLot ? `<button class="btn sm sec" data-unlocklot="ferment|${esc(r.ferment_id)}">Mở khóa</button>` : '<span class="muted">—</span>')
            : (canLockLot ? `<button class="btn sm" data-locklot="ferment|${esc(r.ferment_id)}">Khóa</button>` : '<span class="muted">—</span>')}</td>
        <td>${holdBadgeHtml(r)}${esc(r.lm_code)}</td><td>${esc(r.brew_code || "")}</td><td>${fmt(r.brew_date)}</td>
        <td>${fmt(r.kt_date)}</td><td>${daysFermentedCell(r)}</td><td>${esc(r.wort_type)}</td>
        <td class="muted">${esc(r.yeast_gen || "")}</td><td>${esc(r.tank_lm)}</td><td>${r.volume_hl.toLocaleString("vi-VN")}</td>
        <td>${r.on_hand_cct.toLocaleString("vi-VN")}</td><td>${badge(stBadge[r.status] || "planned")}${stLabel[r.status] || r.status}</td>
        <td>${readyBadge(r)}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-fermentlog="${esc(r.ferment_id)}|${esc(r.lm_code)}">Ghi chép LM</button></td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-stageqc="len_men_chinh|ferment|${esc(r.ferment_year)}-${esc(r.lm_code)}__len_men_chinh|${esc(r.product_id || "")}">CT chính</button>
          <button class="btn sm sec" data-stageqc="len_men_phu|ferment|${esc(r.ferment_year)}-${esc(r.lm_code)}__len_men_phu|${esc(r.product_id || "")}">CT phụ</button>
          <button class="btn sm sec" data-cip="ferment|${esc(r.ferment_id)}|${esc(r.lm_code)}" title="Gắn CIP liên quan">CIP</button>
          ${!r.locked && (r.on_hand_cct || 0) > 0 ? `<button class="btn sm sec" data-emptycct="${esc(r.ferment_id)}"
            title="Buộc tồn CCT (${r.on_hand_cct} hl) của cả tank ${esc(r.tank_lm)} về 0 khi tank vật lý đã lọc cạn thật nhưng số liệu còn lệch">Làm rỗng tank</button>` : ""}</td></tr>`).join("")}
      <tr style="font-weight:700"><td colspan=10 style="text-align:right">Tổng cộng:</td><td>${data.total_brew_hl.toLocaleString("vi-VN")}</td><td>${data.total_cct_hl.toLocaleString("vi-VN")}</td><td colspan=4></td></tr></tbody></table></div>
      <div class="legend">Chú thích: <b class="red">Đỏ</b>: Thiếu chỉ tiêu bắt buộc, hoặc đã đủ nhưng có chỉ tiêu FAIL — <b class="blue">Xanh dương</b>: Đầy đủ, không FAIL</div></div>`;
  }

  else if (sec === "loc") {
    const ynLoc = YEARS.loc;
    const [rows, filterOrders, lines, bbtTanksLocRaw] = await Promise.all([
      GET("/brewing/filters" + (ynLoc ? "?" + ynLoc.map(y => "years=" + y).join("&") : "")),
      GET("/brewing/filter-orders"), GET("/lines").catch(() => []),
      GET("/brewing/bbt-tanks").catch(() => [])]);
    // Tank còn CẦN thao tác (còn ít nhất 1 mẻ lọc chưa duyệt KCS và/hoặc chưa khóa lô) lên đầu
    // bảng — xem lý do tương tự ở "lenmen"/"chiet".
    const needsActionLoc = (r) => !r.qc_approved || !r.locked;
    const tankNeedsAction = (t) => rows.some(r => r.to_bbt === t.to_bbt && needsActionLoc(r));
    const bbtTanksLoc = [...bbtTanksLocRaw].sort((a, b) => Number(tankNeedsAction(b)) - Number(tankNeedsAction(a)));
    const canApproveFilter = _hasPerm("quality.release");
    const canLockLot = _hasPerm("quality.release");
    const isAdminLot = CURRENT_USER && CURRENT_USER.role === "admin";
    const ordersById = Object.fromEntries(filterOrders.map(o => [o.filter_order_id, o]));
    // Đếm số tank thành phẩm CÙNG 1 Lệnh lọc (master_order_id) — chỉ hiện "(N)" khi Lệnh lọc đó
    // thật sự có NHIỀU HƠN 1 tank (mới cần phân biệt tank nào); còn đúng 1 tank thì số lệnh đã
    // đủ rõ, không cần "(1)" thừa.
    const siblingCountByMaster = {};
    for (const o of filterOrders) {
      if (!o.master_order_id) continue;
      siblingCountByMaster[o.master_order_id] = (siblingCountByMaster[o.master_order_id] || 0) + 1;
    }
    // Đã bắt đầu chiết (có mẻ chiết tham chiếu tới 1 trong các mẻ lọc của lệnh) thì không cho
    // thêm mẻ lọc mới nữa — chỉ được thêm khi lệnh còn "Đang lọc" (xem
    // filter_order_svc._chiet_started, chặn tương ứng ở routers/brewing.py::add_filter).
    const availableOrders = filterOrders.filter(o => !o.is_complete && !o.chiet_started);
    // Nhóm các "tank thành phẩm" CHƯA hoàn thành theo Lệnh lọc (master_order_id) — chọn
    // theo 2 bước: chọn Lệnh lọc rồi chọn đúng Tank thành phẩm bên trong để thực hiện lọc.
    const mastersMap = new Map();
    for (const o of availableOrders) {
      if (!o.master_order_id) continue;
      if (!mastersMap.has(o.master_order_id)) mastersMap.set(o.master_order_id, { id: o.master_order_id, code: o.master_order_code, children: [] });
      mastersMap.get(o.master_order_id).children.push(o);
    }
    mastersLf = [...mastersMap.values()];
    mastersLf.forEach(m => m.children.sort((a, b) => (a.seq || 0) - (b.seq || 0)));
    const masterOptsLf = `<option value="">(chọn Lệnh lọc — bắt buộc)</option>` + mastersLf.map(m =>
      `<option value="${esc(m.id)}">${esc(m.code)} (${m.children.length} tank thành phẩm chưa xong)</option>`).join("");
    // Tank BBT bị khoá — mirror ĐÚNG điều kiện chặn server-side filter_order_svc._bbt_target_blocked_by:
    // (1) đang có mẻ chưa kết thúc (!all_finished, không thể vừa rót mẻ này vừa cho mẻ khác vào
    // cùng lúc) HOẶC (2) còn dịch VÀ đã có mẻ được KCS duyệt (nhiều lệnh khác nhau được phép
    // cùng đổ vào 1 tank TRƯỚC khi duyệt KCS, chỉ chặn SAU khi duyệt) — áp dụng thêm ở UI để
    // không phải bấm thử mới biết bị chặn.
    const occupiedBbtCodes = new Set(bbtTanksLoc.filter(t => !t.all_finished || (t.on_hand_bbt > 1e-6 && t.any_qc_approved)).map(t => t.to_bbt));
    const freeBbtLines = lines.filter(l => l.kind === "tank_bbt" && !occupiedBbtCodes.has(l.code));
    const bbtOpts = freeBbtLines.map(l => `<option value="${esc(l.code)}">${esc(l.code)}</option>`).join("") ||
      `<option value="">(không còn Tank BBT trống — tank khác đang lọc/còn dịch chưa chiết hết)</option>`;
    // Bảng phẳng, KHÔNG gom theo khối tank BBT nữa — mỗi dòng = 1 mẻ lọc, hiện thẳng Tank BBT/
    // Loại bia/Dịch bia (dịch nguồn của TỪNG tank, nối " + " nếu là mẻ phối >=2 tank nguồn) ngay
    // trên dòng đó. Nút cấp-tank (Làm rỗng tank/CIP) chỉ hiện 1 lần ở dòng ĐẦU TIÊN gặp mỗi
    // to_bbt (theo thứ tự lặp bbtTanksLoc rồi mẻ của tank đó) để tránh lặp nút trên mọi dòng.
    const seenTanksLoc = new Set();
    const rowsHtmlLoc = bbtTanksLoc.flatMap(t => rows.filter(r => r.to_bbt === t.to_bbt)
        .sort((a, b) => Number(needsActionLoc(b)) - Number(needsActionLoc(a))).map(r => {
      const tankCount = ordersById[r.filter_order_id]?.tanks?.length || 0;
      const ord = ordersById[r.filter_order_id];
      const lenhLocText = ord && ord.master_order_code
        ? `${esc(ord.master_order_code)}${ord.seq && (siblingCountByMaster[ord.master_order_id] || 0) > 1 ? `(${ord.seq})` : ""}`
        : "—";
      const firstOfTank = !seenTanksLoc.has(t.to_bbt);
      seenTanksLoc.add(t.to_bbt);
      const dichBia = [...new Set((r.source_products || []).filter(Boolean))].join(" + ") || r.product_code || "—";
      return `<tr class="row-${r.color}">
        <td class="code">${esc(t.to_bbt)}</td>
        <td>${esc(r.beer_type || t.beer_type || "—")}</td>
        <td>${esc(dichBia)}</td>
        <td style="white-space:nowrap">${r.locked ? lockBadgeHtml(r) : (r.qc_approved ? `<span style="color:var(--green)">✓ ${esc(r.qc_approved_by || "")}</span><div class="muted">${fmt(r.qc_approved_at)}</div>`
          : (r.exec_status !== "hoan_thanh") ? `<span class="muted" title="Chỉ duyệt được khi đã lọc xong (kết thúc hết các tank)">— (đang lọc)</span>`
          : (canApproveFilter ? `<button class="btn sm" data-filterapprove="${esc(r.filter_id)}">Duyệt KCS</button>` : '<span class="muted">—</span>'))}</td>
        <td style="white-space:nowrap">${r.locked
            ? (isAdminLot ? `<button class="btn sm sec" data-unlocklot="filter|${esc(r.filter_id)}">Mở khóa</button>` : '<span class="muted">—</span>')
            : (canLockLot ? `<button class="btn sm" data-locklot="filter|${esc(r.filter_id)}">Khóa</button>` : '<span class="muted">—</span>')}</td>
        <td class="code">${holdBadgeHtml(r)}${esc(r.filter_code)}</td>
        <td class="muted">${lenhLocText}</td>
        <td>${fmt(r.filter_date)}</td><td>${r.v_dich_hl > 0 ? r.v_dich_hl : "—"}</td><td>${r.nuoc_bai_khi_hl > 0 ? r.nuoc_bai_khi_hl : "—"}</td>
        <td>${r.v_beer_hl > 0 ? r.v_beer_hl : "—"}</td><td>${r.on_hand_bbt}</td>
        <td>${badge({ dang_loc: "in_progress", cho_duyet: "held", cho_chiet: "planned", chiet_1_phan: "due", da_chiet_het: "done" }[r.status] || "planned")}${esc(r.status_label)}</td>
        <td>${fmt(r.ended_at)}</td>
        <td>${badge(r.exec_status === "hoan_thanh" ? "completed" : "in_progress")}${esc(r.exec_status_label)}
          <button class="btn sm" data-filtertanks="${esc(r.filter_id)}" data-filterbbt="${r.on_hand_bbt || 0}" style="margin-left:6px">Tank (${tankCount})</button></td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-nvlloc="${esc(r.filter_id)}|${esc(r.filter_order_id || "")}|${esc(r.filter_code)}">NVL lọc</button>
          ${r.locked ? "" : `<button class="btn sm sec" data-delrec="filter|${esc(r.filter_id)}">Xóa</button>`}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-stageqc="loc|filter|${esc(r.filter_year)}-${esc(r.filter_code)}|${esc(r.product_id || "")}|${esc(r.finished_product_id || "")}|${""}|${esc(r.beer_type_id || "")}">Chỉ tiêu</button></td>
        <td style="white-space:nowrap">${firstOfTank ? `${t.on_hand_bbt > 0 ? `<button class="btn sm sec" data-emptybbttank="${esc(t.to_bbt)}">Làm rỗng tank</button>` : ""}<button class="btn sm sec" data-cip="bbt_tank|${esc(t.to_bbt)}|${esc(t.to_bbt)}" title="Gắn CIP liên quan cho cả tank">CIP</button>` : ""}</td>
      </tr>`;
    })).join("") || `<tr><td colspan=18 class="muted">Chưa có mẻ lọc nào — thêm ở form "Thêm thông tin lọc" phía trên.</td></tr>`;
    body = `<div class="panel"><h2>Thêm thông tin lọc (Lọc thường)</h2>
      <div class="muted" style="margin-bottom:6px">Bắt buộc chọn <b>Lệnh lọc</b> rồi chọn đúng <b>Tank thành phẩm</b> bên trong (chưa dùng hết) — tạo lệnh mới ở tab "Lệnh lọc" nếu danh sách trống; tank nguồn kế thừa từ tank đã chọn, không chọn lại.
        Dịch nha lọc/Sản lượng lọc chưa cần điền ngay — sẽ nhập khi bấm "Kết thúc" từng tank (kèm nước bài khí, sản lượng tự tính = dịch nha lọc + nước bài khí, cộng dồn nếu lọc phối). Dùng form này để thêm mẻ vào tank MỚI (chưa có mẻ nào) — tank đã có mẻ thì bấm nút "Tank (N)" trên dòng mẻ đó rồi bấm "+ Thêm mẻ" trong đó (tự dùng lại đúng tank nguồn của mẻ, không cần chọn lại).</div>
      <div class="row">
        <div class="field"><label>Lệnh lọc</label><select id="fl_master">${masterOptsLf}</select></div>
        <div class="field"><label>Tank thành phẩm</label><select id="fl_order"><option value="">(chọn Lệnh lọc trước)</option></select></div>
        <div class="field"><label>Loại bia</label><div id="fl_beer_display" class="muted" style="padding:6px 0">— (chọn Tank thành phẩm trước)</div></div>
        <div class="field"><label>Cho vào Tank BBT</label><select id="fl_bbt"><option value=""></option>${bbtOpts}</select>
          <div id="fl_bbt_locked" class="muted" style="padding:6px 0;display:none"></div></div>
        <button class="btn" id="fl_add">Thêm</button>
      </div></div>
      <h2 style="margin:16px 0 8px">Thông tin lọc <span class="muted">(${bbtTanksLoc.length} tank · ${rows.length} mẻ)</span></h2>
      ${yearFilterControl("loc", ynLoc)}
      <input class="searchbox" data-tbl="t_loc" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_loc">
        <thead><tr><th>Tank BBT</th><th>Loại bia</th><th>Dịch bia</th><th>Duyệt KCS</th><th>Khóa mã lọc</th><th>Mã lọc</th><th>Lệnh lọc</th><th>Ngày lọc</th><th>V dịch/hl</th><th>Nước bài khí/hl</th>
          <th>V Bia/hl</th><th>Đang tồn/hl</th><th>Trạng thái</th><th>Kết thúc</th><th>TH thực tế</th><th></th><th>Chỉ tiêu</th><th>Tank</th></tr></thead>
        <tbody>${rowsHtmlLoc}</tbody>
      </table></div>
      <div class="legend">Chú thích: <b class="red">Đỏ</b>: Thiếu chỉ tiêu bắt buộc, hoặc đã đủ nhưng có chỉ tiêu FAIL — <b class="green">Xanh lá</b>: Đủ chỉ tiêu (không FAIL) nhưng chưa nhập NVL — <b class="blue">Xanh dương</b>: Đầy đủ, không FAIL — <b class="cyan">Xanh nhạt</b>: Lọc vào BBT phối</div>`;
  }

  else if (sec === "chiet") {
    const ynChiet = YEARS.chiet;
    const [rows, finishedProducts, lines, bbtTanksChiet] = await Promise.all([
      GET("/brewing/bottles" + (ynChiet ? "?" + ynChiet.map(y => "years=" + y).join("&") : "")),
      GET("/finished-products").catch(() => []), GET("/lines").catch(() => []),
      GET("/brewing/bbt-tanks").catch(() => [])]);
    // Dòng còn CẦN thao tác (chưa duyệt và/hoặc chưa khóa lô) lên đầu bảng — xem lý do tương
    // tự ở "lenmen".
    rows.sort((a, b) => Number(!b.approved || !b.locked) - Number(!a.approved || !a.locked));
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
      ${yearFilterControl("chiet", ynChiet)}
      <input class="searchbox" data-tbl="t_chiet" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_chiet"><thead><tr><th>Duyệt</th><th>Khóa lô</th><th>Lô chiết</th><th>Mã lọc</th><th>Ngày chiết</th><th>Loại bia</th><th>Sản phẩm</th>
        <th>Số lô bia</th><th>V cấp chiết/hl</th><th>Chiết từ Tank BBT</th><th>SL ca 1</th><th>SL ca 2</th><th>SL ca 3</th>
        <th>Tổng Cộng</th><th>Đã nhập kho</th><th>Chiết duyệt</th><th>Ngày giờ kết thúc</th><th>TH thực tế</th><th></th><th>Chỉ tiêu</th></tr></thead>
      <tbody>${rows.map(b => `<tr class="row-${b.color}"><td style="white-space:nowrap">${b.locked ? lockBadgeHtml(b) : (b.approved ? `<span style="color:var(--green)">✓ ${esc(b.approved_by || "")}</span><div class="muted">${fmt(b.approved_at)}</div>` : `<a href="#" data-approve="${b.bottle_id}" style="color:var(--accent)">Duyệt</a>`)}</td>
        <td style="white-space:nowrap">${b.locked
            ? (isAdminLot ? `<button class="btn sm sec" data-unlocklot="bottle|${esc(b.bottle_id)}">Mở khóa</button>` : '<span class="muted">—</span>')
            : (canLockLot ? `<button class="btn sm" data-locklot="bottle|${esc(b.bottle_id)}">Khóa</button>` : '<span class="muted">—</span>')}</td>
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
          ${!b.locked && b.from_bbt && (b.source_filter_on_hand_bbt || 0) > 0 ? `<button class="btn sm sec" data-emptybbtchiet="${esc(b.from_bbt)}"
            title="Buộc tồn BBT (${b.source_filter_on_hand_bbt} hl) của cả tank ${esc(b.from_bbt)} về 0 khi tank vật lý đã chiết cạn thật nhưng số liệu còn lệch"
            style="margin-left:6px">Làm rỗng tank</button>` : ""}</td>
        <td><button class="btn sm sec" data-nvlchiet="${esc(b.bottle_id)}|${esc(b.bottle_code)}">NVL chiết</button>
          ${b.locked ? "" : `<button class="btn sm sec" data-delrec="bottle|${esc(b.bottle_id)}">Xóa</button>`}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-stageqc="thanh_pham|bottle|${esc(b.bottle_year)}-${esc(b.bottle_code)}__thanh_pham|${esc(b.product_id || "")}|${esc(b.finished_product_id || "")}|${""}|${esc(b.beer_type_id || "")}">Thành phẩm</button>
          <button class="btn sm sec" data-cip="bottle|${esc(b.bottle_id)}|${esc(b.bottle_code)}" title="Gắn CIP liên quan">CIP</button></td></tr>`).join("")}</tbody></table></div>
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
      <input class="searchbox" data-tbl="t_chemhist" placeholder="Tìm theo công đoạn, hóa chất..."/>
      <table id="t_chemhist"><thead><tr><th>Thời gian</th><th>Công đoạn</th><th>Hóa chất</th><th>SL</th><th>Ghi chú</th></tr></thead>
      <tbody>${chems.map(c => `<tr><td class="muted">${fmt(c.ts)}</td><td>${esc(stageLabel[c.stage] || c.stage)}</td>
        <td>${esc(c.chemical)}</td><td>${c.quantity} ${esc(c.uom)}</td><td class="muted">${esc(c.note || "")}</td></tr>`).join("")}</tbody></table></div>`;
  }

  else if (sec === "men") {
    const [yeast, issues, batches] = await Promise.all([GET("/process/yeast"), GET("/process/yeast/issues"), GET("/batches")]);
    const bopts = `<option value="">(không gắn mẻ)</option>` + batches.map(b => `<option value="${b.batch_id}">${esc(b.batch_code)}</option>`).join("");
    const yopts = yeast.filter(y => y.status === "available").map(y => `<option value="${y.yeast_lot_id}">${esc(y.code)} (${y.quantity}${y.uom})</option>`).join("");
    body = `<div class="split">
      <div class="panel"><h2>Lô men thu hồi</h2>
        <input class="searchbox" data-tbl="t_yeastlot" placeholder="Tìm theo mã, chủng..."/>
        <table id="t_yeastlot"><thead><tr><th>Mã</th><th>Chủng</th><th>Đời</th><th>SL</th><th>Sống %</th><th>Trạng thái</th></tr></thead>
        <tbody>${yeast.map(y => `<tr><td><code class="k">${esc(y.code)}</code></td><td>${esc(y.strain)}</td><td>${y.generation}</td>
          <td>${y.quantity} ${y.uom}</td><td>${y.viability ?? "—"}</td><td>${badge(y.status === "available" ? "available" : "obsolete")}${y.status}</td></tr>`).join("")}</tbody></table></div>
      <div class="panel"><h2>Xuất men thu hồi</h2>
        <div class="row"><div class="field"><label>Lô men</label><select id="ye_lot">${yopts}</select></div>
          <div class="field"><label>Cấy cho mẻ</label><select id="ye_batch">${bopts}</select></div>
          <div class="field"><label>SL</label><input id="ye_qty" type="number" value="20"/></div>
          <button class="btn" id="ye_issue">Xuất men</button></div>
        <h3>Lịch sử xuất men</h3>
        <table id="t_yeastissue"><thead><tr><th>Thời gian</th><th>Lô men</th><th>Mẻ</th><th>SL</th></tr></thead>
        <tbody>${issues.map(i => `<tr><td class="muted">${fmt(i.ts)}</td><td>${esc(i.yeast_code)}</td><td>${esc(i.batch || "—")}</td><td>${i.quantity} ${i.uom}</td></tr>`).join("") || '<tr><td colspan=4 class="muted">Chưa có.</td></tr>'}</tbody></table></div></div>`;
  }

  $("view-process").innerHTML = subnav("process", sections, sec) + body;
  wireSubnav("process"); wireSearch();
  wirePaginate("t_nlstock", 10);
  wirePaginate("t_chemhist", 10);
  wirePaginate("t_yeastlot", 10);
  wirePaginate("t_yeastissue", 10);
  wirePaginate("t_nau", 10);
  wirePaginate("t_lm", 10);
  wirePaginate("t_loc", 10);
  wirePaginate("t_chiet", 10);
  if (sec === "nau") wireYearFilter("nau", "process");
  if (sec === "lenmen") wireYearFilter("lenmen", "process");
  if (sec === "loc") wireYearFilter("loc", "process");
  if (sec === "chiet") wireYearFilter("chiet", "process");

  if (sec === "nguyenlieu") {
    $("nl_loc").onchange = () => { SUB.process_nl_loc = $("nl_loc").value; render("process"); };
    document.querySelectorAll("[data-viewlots]").forEach(b => b.onclick = () =>
      openMaterialLotsModal(b.dataset.matlabel, lotsByMaterial[b.dataset.viewlots] || []));
  }
  if (sec === "nau") {
    const updateNbWortFromOrder = () => {
      const opt = $("nb_order").selectedOptions[0];
      // Dịch bia trích từ Lệnh nấu đã chọn — lệnh đã chốt sẵn 1 dịch bia lúc lập, không
      // cho chọn khác đi để tránh lệch giữa mã nấu và lệnh sản xuất của nó (gợi ý NVL/BOM sẽ sai).
      if (opt && opt.value && opt.dataset.wort) {
        $("nb_wort").value = opt.dataset.wort;
        $("nb_wort").disabled = true;
      } else {
        $("nb_wort").disabled = false;
      }
      if (!opt || !opt.value) { $("nb_vol").disabled = false; $("nb_batchcount").value = ""; return; }
      // SL nấu/hl luôn LẤY THEO sản lượng kế hoạch (planned_volume_hl) của Lệnh nấu đã
      // chọn, không cho sửa tay — không chia theo số mẻ, vì planned_batch_count là số MẺ
      // (Braumat) bên trong 1 mã nấu, không phải số mã nấu chia sẻ sản lượng của lệnh (1 lệnh
      // có thể có NHIỀU mã nấu, mỗi mã nấu cộng dồn tới khi đạt kế hoạch — xem
      // services/brew_order.py::_is_complete).
      const vol = parseFloat(opt.dataset.vol) || 0;   // đã là hl (tổng kế hoạch)
      $("nb_vol").value = vol;
      $("nb_vol").disabled = true;
      // Số mẻ kế hoạch của Lệnh nấu — chỉ hiển thị để người lập biết cần khai bao nhiêu mẻ
      // (Braumat) khi bấm "Mẻ" sau khi tạo mã nấu; không auto-tạo mẻ vì số mẻ Braumat là số thật
      // do vận hành nhập, hệ thống không tự sinh ra được (xem +Thêm mẻ ở openBrewBatchesModal).
      $("nb_batchcount").value = opt.dataset.batchcount || "—";
    };
    $("nb_order").onchange = updateNbWortFromOrder;
    updateNbWortFromOrder();
    $("nb_add").onclick = () => guard(async () => {
      const orderId = $("nb_order").value;
      if (!orderId) throw new Error("Chọn Lệnh nấu trước khi thêm mã nấu.");
      const code = $("nb_code").value.trim();
      if (!code) throw new Error("Nhập mã nấu.");
      const tank = $("nb_tank").value || null;
      const lmCode = tank ? code : null;   // 1 mã nấu = 1 lô LM — dùng luôn mã nấu làm mã lô LM
      const productId = $("nb_wort").value || null;
      if (!productId) throw new Error("Chọn Dịch bia trước khi thêm mã nấu.");
      const wortName = $("nb_wort").selectedOptions[0].textContent;
      await POST("/brewing/brews", { brew_code: code, wort_type: wortName, product_id: productId,
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
      $("fl_beer_display").textContent = opt && opt.value ? (beer || "(chưa xác định — kiểm tra Loại bia của lệnh lọc)") : "— (chọn Tank thành phẩm trước)";
    };
    $("fl_master").onchange = () => {
      const master = mastersLf.find(m => m.id === $("fl_master").value);
      $("fl_order").innerHTML = master
        ? `<option value="">(chọn Tank thành phẩm — bắt buộc)</option>` + master.children.map(o => {
            const last = o.records.length ? o.records[o.records.length - 1] : null;
            const lastUnfinished = last && !last.ended_at;
            return `<option value="${esc(o.filter_order_id)}" data-beer="${esc(o.beer_type_name || "")}"
              data-lasttobbt="${esc(last ? last.to_bbt || "" : "")}" data-lastunfinished="${lastUnfinished ? "1" : ""}">Tank thành phẩm #${o.seq} — ${o.blend_mode === "phoi" ? "Phối" : "Không phối"} (${o.tanks.map(t => esc(t.tank_lm)).join(", ")}) — ${o.actual_volume_hl}/${o.planned_volume_hl} hl${o.finished_product_code ? ` — SP: ${esc(o.finished_product_code)} — ${esc(o.finished_product_name || "")}` : ""}${o.records.length ? ` — đã có ${o.records.length} mẻ` : ""}</option>`;
          }).join("")
        : `<option value="">(chọn Lệnh lọc trước)</option>`;
      updateFlBeerDisplay(); updateFlBbtLock();
    };
    // Mẻ gần nhất của tank thành phẩm còn đang lọc dở (chưa "Kết thúc") — bắt buộc tiếp tục đúng tank
    // đó, không cho đổi tank giữa chừng (xem routers/brewing.py::add_filter). Nếu mẻ gần nhất
    // đã kết thúc (tank cũ đầy/xong) thì được chọn tank khác tự do — tank cũ vẫn được gợi ý
    // chọn sẵn (tiện tiếp tục dùng lại nếu còn chỗ), nhưng có thể đổi sang tank khác.
    const updateFlBbtLock = () => {
      const opt = $("fl_order").selectedOptions[0];
      const lastTobbt = opt && opt.dataset.lasttobbt;
      const forced = !!(opt && opt.dataset.lastunfinished === "1");
      $("fl_bbt").style.display = forced ? "none" : "";
      $("fl_bbt_locked").style.display = forced ? "" : "none";
      if (forced) {
        $("fl_bbt_locked").textContent = `${lastTobbt} (đang lọc dở — kết thúc tank này trước khi đổi sang tank khác)`;
      } else if (lastTobbt) {
        for (const o of $("fl_bbt").options) { if (o.value === lastTobbt) { $("fl_bbt").value = lastTobbt; break; } }
      }
    };
    $("fl_order").onchange = () => { updateFlBeerDisplay(); updateFlBbtLock(); };
    $("fl_add").onclick = () => guard(async () => {
      const orderId = $("fl_order").value;
      if (!orderId) throw new Error("Chọn Tank thành phẩm trước khi thêm bản ghi lọc.");
      // Không gửi wort_type — backend tự suy ra đúng dịch nha từ tank nguồn của lệnh lọc
      // (xem routers/brewing.py::add_filter, "if not data.get(wort_type)"). Trước đây gửi
      // cứng "Dịch bia 14oP" ở đây khiến điều kiện đó luôn False nên giá trị đúng bị đè mất.
      const res = await POST("/brewing/filters", { filter_code: "FL-" + Date.now().toString().slice(-5), filter_order_id: orderId,
        to_bbt: $("fl_bbt").value });
      if (res.mix_warning) toast(res.mix_warning, "warn");
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
    if (MULTI_SAMPLE_STAGES.includes(stage)) {
      openFermentQcSampleModal(stage, scopeType, scopeId, productId || null);
      return;
    }
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
  document.querySelectorAll("[data-emptycct]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Buộc tồn CCT (tank lên men) của tank này về 0? Chỉ dùng khi tank vật lý đã lọc cạn thật nhưng số liệu còn lệch một khoảng nhỏ.")) return;
    const res = await POST(`/brewing/ferments/${b.dataset.emptycct}/empty-cct`, {});
    toast(`Đã làm rỗng — tồn CCT: ${res.on_hand_cct} hl`); render("process");
  }));
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
        try {
          await POST(`/brewing/bottles/${id}/finish`, payload);
        } catch (e) {
          if (/mismatch_reason/.test(e.message)) {
            const reason = prompt(e.message + "\n\nNhập lý do sai lệch để vẫn tiếp tục:");
            if (!reason || !reason.trim()) throw new Error("Đã hủy — cần nhập lý do sai lệch để tiếp tục.");
            await POST(`/brewing/bottles/${id}/finish`, { ...payload, mismatch_reason: reason.trim() });
          } else {
            throw e;
          }
        }
        closeModal(); toast("Đã lưu kết quả chiết"); render("process");
      });
  });
  document.querySelectorAll("[data-filtertanks]").forEach(b => b.onclick = () => openFilterTanksModal(b.dataset.filtertanks, parseFloat(b.dataset.filterbbt) || 0));
  document.querySelectorAll("[data-emptybbtchiet]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm(`Buộc tồn cả tank thành phẩm (BBT) ${b.dataset.emptybbtchiet} về 0? Chỉ dùng khi tank vật lý đã chiết cạn thật. Không thể hoàn tác.`)) return;
    const res = await POST(`/brewing/bbt-tanks/${b.dataset.emptybbtchiet}/empty`, {});
    toast(`Đã làm rỗng — tồn BBT: ${res.on_hand_bbt} hl`); render("process");
  }));
  document.querySelectorAll("[data-emptybbttank]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm(`Buộc tồn cả tank BBT ${b.dataset.emptybbttank} về 0? Chỉ dùng khi tank vật lý đã chiết cạn thật. Không thể hoàn tác.`)) return;
    const res = await POST(`/brewing/bbt-tanks/${b.dataset.emptybbttank}/empty`, {});
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
  document.querySelectorAll("[data-cip]").forEach(b => b.onclick = () => {
    const [scopeType, scopeId, label] = b.dataset.cip.split("|");
    window.openCipLinkModal(scopeType, scopeId, label);
  });
  // Khóa lô theo từng công đoạn — Nấu/Lên men/Lọc/Chiết mỗi bảng có nút riêng (xem
  // services/lot_lock.py) — KCS khóa xuôi (chặn nếu công đoạn nguồn chưa khóa), chỉ admin
  // mở khóa được và phải mở ngược (chặn nếu công đoạn hạ lưu còn khóa) — lỗi trả về từ
  // server hiển thị qua guard()/toast như các lỗi domain khác, không cần xử lý riêng.
  const LOCKLOT_PATH = { brew: "brews", ferment: "ferments", filter: "filters", bottle: "bottles" };
  const LOCKLOT_LABEL = { brew: "mã nấu", ferment: "lô LM", filter: "mẻ lọc", bottle: "lô chiết" };
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
const sevBadge = (s) => `<span class="badge ${s === "high" ? "critical" : s === "medium" ? "due" : "available"}">${s === "high" ? "Cao" : s === "medium" ? "Trung bình" : "Thấp"}</span>`;
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
    { key: "keg", label: "Chiết (keg)" }, { key: "lostatus", label: "Trạng thái lô" },
    { key: "yield", label: "Sản lượng lọc" }];
  let body = "";

  if (sec === "material") {
    const days = SUB.reports_days || 90;
    const tolPct = SUB.reports_tol || 5;
    const rep = await GET(`/reports/material-norm?days=${days}&tol_pct=${tolPct}`);
    const normModuleBlock = (title, hint, data, showNorm) => `
      <div class="panel"><h2>${title} <span class="muted">(${data.order_count != null ? data.order_count + " lệnh" : data.record_count + " mẻ chiết"})</span></h2>
      <div class="muted" style="margin-bottom:8px">${hint}</div>
      <input class="searchbox" data-tbl="${data._tid}" placeholder="Tìm theo tên vật tư, trạng thái..."/>
      <div class="tablewrap"><table id="${data._tid}"><thead><tr><th>Vật tư</th>${showNorm ? "<th>Số lệnh</th>" : ""}
        ${showNorm ? "<th>Định mức</th>" : ""}<th>Thực tế</th>${showNorm ? "<th>Chênh</th><th>%</th>" : ""}<th>ĐVT</th>${showNorm ? "<th>Trạng thái</th>" : ""}</tr></thead>
      <tbody>${data.materials.map(m => `<tr class="${showNorm ? `row-${{dat:"blue",vuot:"red",thieu:"green"}[m.status] || ""}` : ""}">
        <td>${esc(m.material_name || "")}</td>${showNorm ? `<td>${m.orders}</td>` : ""}
        ${showNorm ? `<td>${m.planned.toLocaleString("vi-VN")}</td>` : ""}<td>${m.actual.toLocaleString("vi-VN")}</td>
        ${showNorm ? `<td style="color:${m.diff > 0 ? "var(--red)" : m.diff < 0 ? "var(--orange)" : "var(--muted)"}">${m.diff > 0 ? "+" : ""}${m.diff.toLocaleString("vi-VN")}</td><td>${m.pct}%</td>` : ""}
        <td>${esc(m.uom || "")}</td>
        ${showNorm ? `<td>${badge((normStatus[m.status] || ["planned", m.status])[0])}${(normStatus[m.status] || ["", m.status])[1]}</td>` : ""}</tr>`).join("") ||
        `<tr><td colspan=${showNorm ? 7 : 3} class="muted">Chưa có dữ liệu.</td></tr>`}</tbody></table></div>
      ${data.orders ? `<h3 style="margin-top:14px">Theo lệnh</h3>
      <input class="searchbox" data-tbl="${data._tid}_o" placeholder="Tìm theo số lệnh, trạng thái..."/>
      <div class="tablewrap"><table id="${data._tid}_o"><thead><tr><th>Số lệnh</th><th>Tổng định mức</th><th>Tổng thực tế</th><th>Chênh</th><th>%</th><th>Trạng thái</th></tr></thead>
      <tbody>${data.orders.map(o => `<tr class="row-${{dat:"blue",vuot:"red",thieu:"green"}[o.status] || ""}">
        <td class="code">${esc(o.order_code)}</td><td>${o.planned_total.toLocaleString("vi-VN")}</td><td>${o.actual_total.toLocaleString("vi-VN")}</td>
        <td style="color:${o.diff > 0 ? "var(--red)" : o.diff < 0 ? "var(--orange)" : "var(--muted)"}">${o.diff > 0 ? "+" : ""}${o.diff.toLocaleString("vi-VN")}</td><td>${o.pct}%</td>
        <td>${badge((normStatus[o.status] || ["planned", o.status])[0])}${(normStatus[o.status] || ["", o.status])[1]}</td></tr>`).join("") ||
        '<tr><td colspan=6 class="muted">—</td></tr>'}</tbody></table></div>` : ""}
      </div>`;
    rep.nau._tid = "t_norm_nau"; rep.loc._tid = "t_norm_loc"; rep.chiet._tid = "t_norm_chiet";
    body = `<div class="panel">
      <div class="row"><div class="field"><label>Kỳ (ngày gần đây)</label>
        <select id="rp_days"><option value="30">30 ngày</option><option value="90" ${days == 90 ? "selected" : ""}>90 ngày</option><option value="365">365 ngày</option><option value="3650">Tất cả</option></select></div>
        <div class="field"><label>Ngưỡng đạt (±%)</label><input id="rp_tol" type="number" step="0.5" min="0" value="${tolPct}" style="width:90px"/></div>
      </div>
      <div class="muted">Đối chiếu định mức (đã chốt lúc lập Lệnh nấu/Lệnh lọc) ↔ thực tế tiêu thụ, theo đúng 3 khâu SX: Nấu, Lọc, Chiết. Chiết chưa có định mức đóng gói theo SKU nên chỉ hiện thực tế đã dùng.</div>
    </div>
    ${normModuleBlock("🍺 Nấu", "Định mức = BrewOrderMaterialLine (đã chốt lúc lập Lệnh nấu); thực tế = NVL đã ghi cho các mẻ (BrewMaterialUsage), cộng dồn qua mọi mã thành viên nếu là Nhóm vật tư thay thế.", rep.nau, true)}
    ${normModuleBlock("🧪 Lọc", "Định mức = FilterOrderMaterialLine (VD bột trợ lọc/diatomite); thực tế = NVL đã ghi cho các mẻ lọc (FilterMaterialUsage).", rep.loc, true)}
    ${normModuleBlock("📦 Chiết", "Chiết chưa có định mức đóng gói theo SKU — chỉ hiện thực tế đã dùng (CO2, hóa chất vệ sinh, nắp/lon...).", rep.chiet, false)}`;
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
    const lstDays = SUB.lostatus_days || 180;
    const rows = await GET("/reports/lo-status?days=" + lstDays);
    const nauBadge = { chua_co_me: "planned", dang_thuc_hien: "in_progress", hoan_thanh: "completed" };
    const lmBadge = { len_men: "running", loc_mot_phan: "due", da_loc_het: "done" };
    const locBadge = { chua_loc: "planned", dang_loc: "in_progress", da_ket_thuc: "completed" };
    const chietBadge = { chua_chiet: "planned", dang_chiet: "in_progress", da_ket_thuc: "completed" };
    body = `<div class="panel"><h2>Trạng thái lô — Nấu / Lên men / Lọc / Chiết <span class="muted">(${rows.length} mã nấu)</span></h2>
      <div class="muted" style="margin-bottom:8px">Trạng thái Nấu/Lọc/Chiết theo việc vận hành đã bấm "Kết thúc" hay chưa ở từng tab; Lên men vẫn tự động theo tồn CCT như trước.</div>
      <div class="row"><div class="field"><label>Kỳ (theo ngày nấu)</label>
        <select id="lst_days"><option value="30">30 ngày</option><option value="90">90 ngày</option>
        <option value="180" ${lstDays == 180 ? "selected" : ""}>180 ngày</option><option value="365">365 ngày</option>
        <option value="3650">Tất cả</option></select></div></div>
      <input class="searchbox" data-tbl="t_lostatus" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_lostatus"><thead><tr><th>Mã nấu</th><th>Ngày nấu</th><th>Dịch nha</th>
        <th>Nấu</th><th>Lên men</th><th>Lọc</th><th>Chiết</th></tr></thead>
      <tbody>${rows.map(r => `<tr><td class="code">${esc(r.brew_code)}</td><td>${fmt(r.brew_date)}</td><td>${esc(r.wort_type || "")}</td>
        <td>${badge(nauBadge[r.nau] || "planned")}${esc(r.nau_label)}</td>
        <td>${r.len_men ? badge(lmBadge[r.len_men] || "planned") + esc(r.len_men_label) : `${badge("planned")}${esc(r.len_men_label)}`}</td>
        <td>${badge(locBadge[r.loc] || "planned")}${esc(r.loc_label)}</td>
        <td>${badge(chietBadge[r.chiet] || "planned")}${esc(r.chiet_label)}</td></tr>`).join("") ||
        '<tr><td colspan=7 class="muted">Chưa có mã nấu nào.</td></tr>'}</tbody></table></div></div>`;
  } else if (sec === "yield") {
    const yToday = new Date();
    const yFrom90 = new Date(yToday); yFrom90.setDate(yFrom90.getDate() - 90);
    const yGroupBy = SUB.yield_group_by || "day";
    const yDateFrom = SUB.yield_date_from || toISODateLocal(yFrom90);
    const yDateTo = SUB.yield_date_to || toISODateLocal(yToday);
    SUB.yield_group_by = yGroupBy; SUB.yield_date_from = yDateFrom; SUB.yield_date_to = yDateTo;
    const yq = `date_from=${yDateFrom}&date_to=${encodeURIComponent(yDateTo + "T23:59:59")}&group_by=${yGroupBy}`;
    const yrep = await GET(`/reports/filter-yield-report?${yq}`);
    const ylq = `date_from=${yDateFrom}&date_to=${encodeURIComponent(yDateTo + "T23:59:59")}`;
    const ylrep = await GET(`/reports/filter-line-yield-report?${ylq}`);
    const yColors = { thap: "#9E2626", binh_thuong: "#1B5FA6", cao: "#1F6B41", cuoi: "#767065" };
    const yLabel = { thap: "Thấp", binh_thuong: "Bình thường", cao: "Cao", cuoi: "Mẻ cuối (không tính)" };
    const yBadge = { thap: "critical", binh_thuong: "available", cao: "done", cuoi: "planned" };
    const ySeries = [
      { label: "Thấp", color: yColors.thap, values: yrep.series.map(p => p.thap) },
      { label: "Bình thường", color: yColors.binh_thuong, values: yrep.series.map(p => p.binh_thuong) },
      { label: "Cao", color: yColors.cao, values: yrep.series.map(p => p.cao) },
    ];
    body = `<div class="panel"><h2>🧪 Sản lượng lọc theo mẻ <span class="muted">(${yrep.total} mẻ đã kết thúc)</span></h2>
      <div class="muted" style="margin-bottom:8px">Phân loại mỗi mẻ lọc (đã bấm "Kết thúc") theo V bia (hl) so với ngưỡng cấu hình ở
        Danh mục › Cài đặt vận hành (hiện tại: Thấp ≤ ${yrep.low_hl}hl, Cao &gt; ${yrep.high_hl}hl).</div>
      <div class="row">
        <div class="field"><label>Từ ngày</label><input id="yr_from" type="date" value="${yDateFrom}"/></div>
        <div class="field"><label>Đến ngày</label><input id="yr_to" type="date" value="${yDateTo}"/></div>
        <div class="field"><label>Gộp theo</label><select id="yr_gb">
          <option value="day" ${yGroupBy === "day" ? "selected" : ""}>Ngày</option>
          <option value="week" ${yGroupBy === "week" ? "selected" : ""}>Tuần</option>
          <option value="month" ${yGroupBy === "month" ? "selected" : ""}>Tháng</option></select></div>
        <button class="btn" id="yr_apply" style="align-self:flex-end">Xem báo cáo</button>
      </div></div>
      ${yrep.has_warning ? `<div class="panel" style="border-left:4px solid ${yColors.thap}">
        ⚠️ Có <b>${yrep.low_count}</b> mẻ lọc sản lượng <b>Thấp</b> (≤ ${yrep.low_hl}hl) trong kỳ này — xem danh sách bên dưới.</div>` : ""}
      <div class="split">
        <div class="panel"><h2>Tỉ lệ phân loại</h2>${yrep.total ? CH.pie([
          { label: "Thấp", value: yrep.series.reduce((s, p) => s + p.thap, 0), color: yColors.thap },
          { label: "Bình thường", value: yrep.series.reduce((s, p) => s + p.binh_thuong, 0), color: yColors.binh_thuong },
          { label: "Cao", value: yrep.series.reduce((s, p) => s + p.cao, 0), color: yColors.cao },
        ]) : '<div class="muted">Không có dữ liệu.</div>'}</div>
        <div class="panel"><h2>Theo ${yGroupBy === "day" ? "ngày" : yGroupBy === "week" ? "tuần" : "tháng"}</h2>
          ${yrep.series.length ? CH.groupedN(yrep.series.map(p => p.period), ySeries) : '<div class="muted">Không có dữ liệu.</div>'}</div>
      </div>
      <div class="panel"><h2>Chi tiết theo mẻ lọc</h2>
        <input class="searchbox" data-tbl="t_yieldrep" placeholder="Tìm theo mã lọc, batch/order number..."/>
        <div class="tablewrap"><table id="t_yieldrep"><thead><tr><th>Mã lọc</th><th>Batch number Brewmax</th>
          <th>Order number Brewmax</th><th>Ngày lọc</th><th>Kết thúc</th><th>V bia (hl)</th><th>Phân loại</th></tr></thead>
        <tbody>${yrep.items.map(it => `<tr class="row-${it.classification === "thap" ? "red" : it.classification === "cao" ? "green" : "blue"}">
          <td class="code">${esc(it.filter_code)}</td><td>${esc(it.batch_number || "—")}</td><td>${esc(it.order_number || "—")}</td>
          <td>${fmt(it.filter_date)}</td><td>${fmt(it.ended_at)}</td><td>${it.v_beer_hl}</td>
          <td>${badge(yBadge[it.classification])}${esc(yLabel[it.classification])}</td></tr>`).join("") ||
          '<tr><td colspan=7 class="muted">Chưa có mẻ lọc nào kết thúc trong kỳ này.</td></tr>'}</tbody></table></div></div>
      <div class="panel"><h2>Theo mẻ lọc số <span class="muted">(${ylrep.total} dòng)</span></h2>
        <div class="muted" style="margin-bottom:8px">Mỗi dòng = 1 "mẻ lọc số" (1 đợt rút dịch riêng, xem nút "+ Thêm mẻ" trong modal Tank) —
          cho biết mẻ đó lọc được bao nhiêu lít bia, thuộc mã lọc/tank lên men/mẻ nấu nào. Ngưỡng cảnh báo (lít) khai báo ở
          Danh mục › Cài đặt vận hành (hiện tại: Thấp ≤ ${ylrep.low_l}L, Cao &gt; ${ylrep.high_l}L).</div>
        ${ylrep.has_warning ? `<div class="panel" style="border-left:4px solid ${yColors.thap}">
          ⚠️ Có <b>${ylrep.low_count}</b> mẻ lọc số sản lượng <b>Thấp</b> (≤ ${ylrep.low_l}L) trong kỳ này.</div>` : ""}
        <input class="searchbox" data-tbl="t_yieldlinerep" placeholder="Tìm theo mẻ lọc số, mã lọc, tank lên men, mã nấu, loại dịch bia..."/>
        <div class="tablewrap"><table id="t_yieldlinerep"><thead><tr><th>Mẻ lọc số</th><th>Mã lọc</th><th>Loại dịch bia</th><th>Tank lên men</th>
          <th>Mẻ nấu</th><th>Ngày vào dịch</th><th>Ngày lọc</th><th>Kết thúc</th><th>V dịch bia (lít)</th><th>V nước DAW (lít)</th><th>V bia (lít)</th><th>Phân loại</th></tr></thead>
        <tbody>${ylrep.items.map(it => `<tr class="row-${it.classification === "thap" ? "red" : it.classification === "cao" ? "green" : it.classification === "cuoi" ? "" : "blue"}">
          <td class="code">${esc(it.batch_seq_no || "—")}</td><td>${esc(it.filter_code || "—")}</td><td>${esc(it.beer_type || "—")}</td>
          <td>${esc(it.tank_lm || "—")}</td>
          <td>${esc(it.brew_code || "—")}</td><td>${it.brew_date ? fmt(it.brew_date) : "—"}</td>
          <td>${it.filter_date ? fmt(it.filter_date) : "—"}</td><td>${fmt(it.ended_at)}</td>
          <td>${it.v_dich_l}</td><td>${it.v_daw_l}</td><td>${it.v_l}</td>
          <td>${badge(yBadge[it.classification])}${esc(yLabel[it.classification])}</td></tr>`).join("") ||
          '<tr><td colspan=12 class="muted">Chưa có mẻ lọc số nào kết thúc trong kỳ này.</td></tr>'}</tbody></table></div></div>`;
  }

  $("view-reports").innerHTML = subnav("reports", sections, sec) + body;
  wireSubnav("reports"); wireSearch();
  if (sec === "lostatus") wirePaginate("t_lostatus", 20);
  if (sec === "yield") {
    wirePaginate("t_yieldrep", 20);
    wirePaginate("t_yieldlinerep", 20);
    $("yr_apply").onclick = () => {
      SUB.yield_date_from = $("yr_from").value;
      SUB.yield_date_to = $("yr_to").value;
      SUB.yield_group_by = $("yr_gb").value;
      render("reports");
    };
  }
  if (sec === "material") {
    ["t_norm_nau", "t_norm_nau_o", "t_norm_loc", "t_norm_loc_o", "t_norm_chiet"].forEach(id => wirePaginate(id, 10));
    $("rp_days").value = String(SUB.reports_days || 90);
    $("rp_days").onchange = () => { SUB.reports_days = parseInt($("rp_days").value); render("reports"); };
    $("rp_tol").onchange = () => { SUB.reports_tol = parseFloat($("rp_tol").value) || 5; render("reports"); };
  }
  if (sec === "lostatus") {
    $("lst_days").value = String(SUB.lostatus_days || 180);
    $("lst_days").onchange = () => { SUB.lostatus_days = parseInt($("lst_days").value); render("reports"); };
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
          <div style="font-size:26px;font-weight:700;color:var(--green)">${rpt.total_cans.toLocaleString("vi-VN")} <span style="font-size:14px;font-weight:400">lon</span></div>
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
        <div class="tablewrap"><table id="t_fillingca"><thead><tr><th>Ngày</th><th>Ca</th><th>Bắt đầu</th><th>Kết thúc</th><th>Số lon</th></tr></thead>
        <tbody>${rpt.shifts.map(s => `<tr><td>${fmt(s.date)}</td><td>Ca ${s.ca}</td>
          <td class="muted">${new Date(s.start).toLocaleString("vi-VN")}</td><td class="muted">${new Date(s.end).toLocaleString("vi-VN")}</td>
          <td${s.data_gap ? ' class="muted" title="Thiếu dữ liệu — khoảng trống lớn trong CSDL nguồn"' : ""}>${s.cans != null ? s.cans.toLocaleString("vi-VN") : "— ⚠"}</td></tr>`).join("") ||
          '<tr><td colspan=5 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div></div>`;
    wirePaginate("t_fillingca", 10);
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
          <div style="font-size:26px;font-weight:700;color:var(--green)">${rpt.total_kegs.toLocaleString("vi-VN")} <span style="font-size:14px;font-weight:400">keg</span></div>
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
        <div class="tablewrap"><table id="t_kegca"><thead><tr><th>Ngày</th><th>Ca</th><th>Bắt đầu</th><th>Kết thúc</th><th>Số keg</th></tr></thead>
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
    wirePaginate("t_kegca", 10);
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
const STAGE_LABELS = { nau: "Mẻ nấu", nuoc_nau: "Nước nấu bia", len_men_chinh: "Lên men chính", len_men_phu: "Lên men phụ",
  loc: "Lọc", chiet: "Chiết", thanh_pham: "Thành phẩm" };

function lineSectionHtml(kind, title, rows, canManage, noPerm, miAttr) {
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
  const idField = isLine
    ? `<div class="field"><label>Mã nhận dạng</label><input id="ln_${p}_idcode" placeholder="VD: L03" style="width:100px"/></div>` : "";
  const rowsHtml = rows.map(l => `<tr>
      <td><code class="k">${esc(l.code)}</code></td><td>${esc(l.name)}</td>
      <td>${esc(l.area || "—")}</td>
      <td>${isLine ? (l.ideal_rate_per_min ? l.ideal_rate_per_min + (l.capacity_uom ? " " + esc(l.capacity_uom) : "/phút") : "—")
                   : (l.volume ? l.volume + " " + esc(l.volume_uom || "") : "—")}</td>
      ${isLine ? `<td>${l.identification_code ? `<code class="k">${esc(l.identification_code)}</code>` : "—"}</td>` : ""}
      <td>${badge(l.active ? "available" : "obsolete")}${l.active ? "hoạt động" : "ngừng"}</td>
      ${canManage ? `<td style="white-space:nowrap">
        <button class="btn sm sec" data-ledit="${p}|${esc(l.line_id)}">Sửa</button>
        <button class="btn sm sec" data-ltoggle="${esc(l.line_id)}">${l.active ? "Ngừng" : "Bật lại"}</button>
        <button class="btn sm sec" data-ldel="${esc(l.line_id)}">Xóa</button></td>` : ""}</tr>`).join("")
    || `<tr><td colspan="${(isLine ? 6 : 5) + (canManage ? 1 : 0)}" class="muted">Chưa có mục nào.</td></tr>`;
  return `<div class="panel" ${miAttr || ""}><h2>${title} <span class="muted">(${rows.length})</span></h2>
    ${noPerm}
    ${canManage ? `<div class="row">
      <div class="field"><label>Mã</label><input id="ln_${p}_code" placeholder="${isLine ? "Line-3 (keg)" : kind === "tank" ? "FV-05" : "BBT-01"}"/></div>
      <div class="field"><label>Tên</label><input id="ln_${p}_name" placeholder="${isLine ? "Dây chuyền keg #3" : "Tank " + (kind === "tank" ? "lên men" : "BBT") + " #5"}"/></div>
      ${kindPicker}
      <div class="field"><label>Khu vực</label><input id="ln_${p}_area" style="width:90px"/></div>
      ${capField}
      ${idField}
      <button class="btn" id="ln_${p}_add" style="align-self:flex-end">+ Thêm</button>
    </div>` : ""}
    ${isLine ? `<div class="muted" style="margin-top:6px">Mã nhận dạng — in/dập trên bao bì thực tế, giúp truy vết ngoài thị trường sản phẩm được chiết ở dây chuyền nào.</div>` : ""}
    <input class="searchbox" data-tbl="t_lines_${p}" placeholder="Tìm mã/tên..." style="margin-top:10px"/>
    <div class="tablewrap" style="margin-top:6px"><table id="t_lines_${p}">
      <thead><tr><th>Mã</th><th>Tên</th><th>Khu vực</th><th>${isLine ? "Công suất" : "Thể tích"}</th>${isLine ? "<th>Mã nhận dạng</th>" : ""}<th>Trạng thái</th>${canManage ? "<th></th>" : ""}</tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table></div>
  </div>`;
}
const PRODUCT_SCOPED_STAGES = ["nau", "len_men_chinh", "len_men_phu"];
// Loại bia — mirror qc_catalog.BEER_TYPE_SCOPED_STAGES. Stage KHÔNG nằm trong tập này lẫn
// PRODUCT_SCOPED_STAGES (VD "nuoc_nau" — chỉ tiêu nước nấu bia) luôn ẩn cả 2 picker Dịch
// bia/Loại bia — nhóm gán cho stage đó áp dụng chung cho mọi dịch bia/loại bia.
const BEER_TYPE_SCOPED_STAGES = ["loc", "thanh_pham"];
// CT chính/CT phụ lên men lấy mẫu NHIỀU LẦN (lần 1/lần 2/...) thay vì khai 1 giá trị hiện tại
// như các stage khác — xem openFermentQcSampleModal + backend qc_catalog.MULTI_SAMPLE_STAGES.
const MULTI_SAMPLE_STAGES = ["len_men_chinh", "len_men_phu"];
// Sản phẩm (SKU) chỉ có ý nghĩa ở "loc" và "thanh_pham" — mirror qc_catalog.SKU_SCOPED_STAGES.
const SKU_SCOPED_STAGES = ["loc", "thanh_pham"];
// "Bố cục kho" — admin tự xếp vị trí lên lưới hàng/cột (khác sơ đồ vẽ cứng D01-D21 cũ, mã vị
// trí thật trên server vd "DM.K01" không theo quy luật nào để tự suy ra vị trí vẽ). Biến module
// để giữ trạng thái đang chọn kho/đang "cầm" 1 vị trí xuyên suốt các lần render("master") lại
// (mỗi lần gọi VIEWS.master() là 1 hàm mới, không tự nhớ state cục bộ).
let WMS_LAYOUT_WH = null;
let WMS_LAYOUT_PICK = null;
let WMS_LAYOUT_EXTRA_ROWS = 0;
let WMS_LAYOUT_EXTRA_COLS = 0;
function renderWmsLayoutGrid(wh, locsInWh, whOptionsHtml) {
  const placed = locsInWh.filter(l => l.layout_row != null && l.layout_col != null);
  const unplaced = locsInWh.filter(l => l.layout_row == null || l.layout_col == null);
  const maxRow = placed.reduce((m, l) => Math.max(m, l.layout_row), -1);
  const maxCol = placed.reduce((m, l) => Math.max(m, l.layout_col), -1);
  const rows = Math.max(maxRow + 2, 5) + WMS_LAYOUT_EXTRA_ROWS;
  const cols = Math.max(maxCol + 2, 6) + WMS_LAYOUT_EXTRA_COLS;
  const byCell = {};
  placed.forEach(l => { byCell[`${l.layout_row}:${l.layout_col}`] = l; });
  const pickedLoc = WMS_LAYOUT_PICK ? locsInWh.find(l => l.loc_id === WMS_LAYOUT_PICK) : null;
  let grid = `<div class="tablewrap"><table style="border-collapse:separate;border-spacing:4px">`;
  for (let r = 0; r < rows; r++) {
    grid += "<tr>";
    for (let c = 0; c < cols; c++) {
      const loc = byCell[`${r}:${c}`];
      if (loc) {
        grid += `<td><div class="panel" data-layout-cell="${r}:${c}" data-layout-loc="${esc(loc.loc_id)}"
          style="min-width:90px;padding:6px;text-align:center;cursor:pointer;${loc.loc_id === WMS_LAYOUT_PICK ? "outline:2px solid var(--accent)" : ""}"
          title="Bấm để nhấc ra khỏi ô, xếp lại chỗ khác">
          <div style="font-weight:600;font-size:12px">${esc(loc.code)}</div>
          <div class="muted" style="font-size:11px">${esc(loc.name)}</div>
          <button class="btn sm sec" data-layout-unplace="${esc(loc.loc_id)}" style="margin-top:4px;padding:0 6px">Gỡ</button>
        </div></td>`;
      } else {
        grid += `<td><div data-layout-cell="${r}:${c}" style="min-width:90px;min-height:52px;border:1px dashed var(--border);border-radius:6px;cursor:pointer"
          title="${pickedLoc ? "Bấm để đặt '" + esc(pickedLoc.code) + "' vào đây" : "Chọn 1 vị trí ở danh sách bên trên trước"}"></div></td>`;
      }
    }
    grid += "</tr>";
  }
  grid += "</table></div>";
  return `<div class="row" style="align-items:flex-end;flex-wrap:wrap;margin-bottom:8px">
      <div class="field"><label>Kho thành phẩm</label><select id="wlo_wh">${whOptionsHtml}</select></div>
      <button class="btn sec" id="wlo_addrow">+ Hàng</button>
      <button class="btn sec" id="wlo_addcol">+ Cột</button>
    </div>
    <div class="muted" style="margin-bottom:8px">Bấm chọn 1 vị trí ${unplaced.length ? "chưa xếp" : "đã xếp (để dời)"} bên dưới, rồi bấm vào 1 ô trống trên lưới để đặt vào đó — lưới sẽ vẽ lại đúng như vậy trên "Sơ đồ kho".</div>
    <div style="margin-bottom:10px">${unplaced.length ? unplaced.map(l => `<button class="btn sm ${l.loc_id === WMS_LAYOUT_PICK ? "" : "sec"}" data-layout-pick="${esc(l.loc_id)}" style="margin:2px">${esc(l.code)} — ${esc(l.name)}</button>`).join("")
      : `<span class="muted">Mọi vị trí trong kho này đã được xếp bố cục.</span>`}</div>
    ${grid}`;
}
const MASTER_GROUPS = [
  { key: "sanxuat", label: "Sản xuất", items: [
    { key: "dichbia", label: "Dịch bia" }, { key: "loaibia", label: "Loại bia" },
    { key: "sanpham", label: "Sản phẩm (thành phẩm)" }, { key: "daychuyen", label: "Dây chuyền sản xuất" },
    { key: "tanklm", label: "Tank lên men" }, { key: "tankbbt", label: "Tank thành phẩm (BBT)" },
  ] },
  { key: "nvl", label: "Nguyên vật liệu", items: [
    { key: "vattu", label: "Vật tư / Nguyên liệu" }, { key: "nhomvattu", label: "Nhóm vật tư" },
    { key: "nhomvattuthaythe", label: "Nhóm vật tư thay thế" }, { key: "nhacc", label: "Nhà cung cấp" },
    { key: "vitrikho", label: "Vị trí kho" },
  ] },
  { key: "khotp", label: "Kho thành phẩm", items: [
    { key: "nhamaykhac", label: "Nhà máy khác" }, { key: "khothanhpham", label: "Kho thành phẩm" },
    { key: "vitrikhotp", label: "Vị trí kho thành phẩm" }, { key: "boccuckho", label: "Bố cục kho" },
    { key: "laixe", label: "Lái xe" }, { key: "loaidonvi", label: "Loại đơn vị tồn kho" },
  ] },
  { key: "chatluong", label: "Chất lượng", items: [
    { key: "chitieucl", label: "Danh mục chỉ tiêu chất lượng" }, { key: "nhomchitieucl", label: "Nhóm chỉ tiêu chất lượng" },
    { key: "nhomchitieucongdoan", label: "Nhóm chỉ tiêu theo công đoạn" },
  ] },
  { key: "caidat", label: "Cài đặt", items: [
    { key: "caidatvanhanh", label: "Cài đặt vận hành" },
  ] },
];
let MASTER_GROUP = "sanxuat";
VIEWS.master = async function () {
  const [products, finishedProducts, materials, plines, qcParams, qcGroups, stageGroups, beerTypes, suppliers, materialGroups, opsSettings, unitTypes, materialAltGroups, factoryLocations, wmsWarehouses, wmsLocations, wmsVehicles, materialLocations] = await Promise.all([
    GET("/products"), GET("/finished-products").catch(() => []), GET("/materials"), GET("/lines").catch(() => []),
    GET("/qc/parameters?active_only=false").catch(() => []),
    GET("/qc/groups").catch(() => []), GET("/qc/stage-groups").catch(() => []), GET("/beer-types").catch(() => []),
    GET("/suppliers").catch(() => []), GET("/material-groups").catch(() => []),
    GET("/ops-settings").catch(() => ({ empty_cct_tolerance_hl: 2, empty_bbt_tolerance_hl: 2 })),
    GET("/unit-types").catch(() => []), GET("/material-alt-groups").catch(() => []),
    GET("/factory-locations").catch(() => []),
    GET("/wms/warehouses").catch(() => []), GET("/wms/locations").catch(() => []), GET("/wms/vehicles").catch(() => []),
    GET("/warehouse/locations").catch(() => [])]);
  // Chỉ hiện loại "selectable" (bỏ "lon" — hệ thống tự sinh khi phân rã vỉ, xem services/wms.py)
  // khi khai báo SKU mới; nhưng vẫn hiện đủ mọi loại (kể cả không selectable) khi sửa 1 SKU đã
  // lỡ mang mã đó, để không xóa mất lựa chọn hiện tại khỏi dropdown.
  const selectableUnitTypes = unitTypes.filter(ut => ut.selectable && ut.active);
  const canManage = CURRENT_USER && (CURRENT_USER.permissions === "*" ||
    (Array.isArray(CURRENT_USER.permissions) && CURRENT_USER.permissions.includes("master.manage")));
  const noPerm = canManage ? "" :
    `<div class="muted" style="margin-bottom:8px">Bạn chỉ có quyền xem danh mục (cần quyền <code class="k">master.manage</code> để tạo/sửa).</div>`;
  // Kho thành phẩm/Vị trí kho/Lái xe: chuyển từ Kho TP (WMS) sang đây + khóa CHỈ ADMIN được
  // tạo/sửa/xóa (trước đây bất kỳ ai có quyền warehouse.receive đều làm được, không có gate) —
  // dùng cờ riêng theo role, KHÔNG dùng canManage (master.manage) như các panel khác trong
  // trang này, vì quyền phía backend đã đổi thành require_role(user, Role.ADMIN) (routers/wms.py).
  const isAdminWmsCatalog = CURRENT_USER && CURRENT_USER.role === "admin";
  const noPermWmsCatalog = isAdminWmsCatalog ? "" :
    `<div class="muted" style="margin-bottom:8px">Chỉ tài khoản Admin mới được tạo/sửa/xóa — bạn chỉ có quyền xem.</div>`;
  const activeGroups = materialGroups.filter(g => g.active);
  const fpCats = ["Bia chai", "Bia lon", "Bia hơi", "Bia tươi"];
  const mgroup = MASTER_GROUPS.find(g => g.key === MASTER_GROUP) || MASTER_GROUPS[0];
  const mitem = mgroup.items.some(i => i.key === SUB.master) ? SUB.master : mgroup.items[0].key;
  const mi = (key) => `data-mi="${key}"` + (key === mitem ? "" : ' style="display:none"');
  $("view-master").innerHTML = (mgroup.items.length > 1 ? subnav("master", mgroup.items, mitem) : "") + `
    <div class="master-content">
      <div class="panel" ${mi("dichbia")}><h2>🍺 Dịch bia <span class="muted">(${products.length})</span></h2>
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

      <div class="panel" ${mi("loaibia")}><h2>🏷️ Loại bia <span class="muted">(${beerTypes.length})</span></h2>
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

      <div class="panel" ${mi("vattu")}><h2>📦 Vật tư / Nguyên liệu <span class="muted">(${materials.length})</span></h2>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã VT</label><input id="mt_code" placeholder="MALT-CARA"/></div>
          <div class="field"><label>Tên vật tư</label><input id="mt_name" placeholder="Malt Caramel"/></div>
          <div class="field"><label>ĐVT</label><input id="mt_uom" value="kg" style="width:70px"/></div>
          <div class="field"><label>Nhóm</label><select id="mt_cat">${activeGroups.map(g => `<option value="${esc(g.code)}">${esc(g.name)}</option>`).join("") ||
            "<option value=''>(chưa có nhóm — khai báo ở panel Nhóm vật tư)</option>"}</select></div>
          <div class="field"><label>Tồn tối thiểu</label><input id="mt_stockmin" type="number" step="0.01" placeholder="(tuỳ chọn)" style="width:110px"/></div>
        </div>
        <div class="row" style="margin-top:8px">
          <div class="field"><label>Đơn vị phụ <span class="muted">(tuỳ chọn)</span></label><input id="mt_altuom" placeholder="VD: kg" style="width:90px"/></div>
          <div class="field"><label>Tỷ lệ quy đổi <span class="muted">(1 ĐVT = ? đơn vị phụ)</span></label><input id="mt_altratio" type="number" step="0.0001" placeholder="VD: 2" style="width:110px"/></div>
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

      <div class="panel" ${mi("nhomvattu")}><h2>🏷️ Nhóm vật tư <span class="muted">(${materialGroups.length})</span></h2>
        <div class="muted" style="margin-bottom:6px">Nhóm phân loại vật tư (malt/gạo/hoa bia/men/...) — chọn ở panel Vật tư/Nguyên liệu bên cạnh. Đánh dấu "Bao bì tiêu hao" để vật tư thuộc nhóm đó tự động xuất hiện ở báo cáo lô bao bì (tab Bao bì) — không áp dụng cho vỏ chai/két/keg tuần hoàn. Đánh dấu "Nguyên liệu (chính/phụ)" để khi khai báo chỉ tiêu chất lượng (Kho NVL) hiện thêm cột "Giá trị CA" (giá trị in trên bao bì NCC) bên cạnh giá trị nhà máy tự đo.</div>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã nhóm</label><input id="mg_code" placeholder="malt"/></div>
          <div class="field"><label>Tên nhóm</label><input id="mg_name" placeholder="Malt"/></div>
          <div class="field"><label><input type="checkbox" id="mg_packaging"/> Bao bì tiêu hao</label></div>
          <div class="field"><label><input type="checkbox" id="mg_rawmat"/> Nguyên liệu (chính/phụ)</label></div>
          <button class="btn" id="mg_add" style="align-self:flex-end">+ Tạo nhóm</button>
        </div>` : ""}
        <input class="searchbox" data-tbl="t_matgroups" placeholder="Tìm mã/tên nhóm vật tư..." style="margin-top:10px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_matgroups">
          <thead><tr><th>Mã</th><th>Tên</th><th>Trạng thái</th><th>Bao bì?</th><th>Nguyên liệu?</th>${canManage ? "<th></th>" : ""}</tr></thead>
          <tbody>${materialGroups.map(g => `<tr>
            <td><code class="k">${esc(g.code)}</code></td><td>${esc(g.name)}</td>
            <td>${g.active ? '<span style="color:var(--green)">Đang dùng</span>' : '<span class="muted">Đã ẩn</span>'}</td>
            <td>${g.is_packaging ? '<span style="color:var(--accent)">📦 Bao bì</span>' : '<span class="muted">—</span>'}</td>
            <td>${g.is_raw_material ? '<span style="color:var(--accent)">🌾 Nguyên liệu</span>' : '<span class="muted">—</span>'}</td>
            ${canManage ? `<td style="white-space:nowrap">
              <button class="btn sm sec" data-emg="${esc(g.group_id)}">Sửa</button>
              <button class="btn sm sec" data-mgdel="${esc(g.group_id)}">Xóa</button>
            </td>` : ""}</tr>`).join("") ||
            `<tr><td colspan="${canManage ? 6 : 5}" class="muted">Chưa có Nhóm vật tư nào.</td></tr>`}</tbody>
        </table></div>
      </div>

      <div class="panel" ${mi("nhomvattuthaythe")}><h2>🔀 Nhóm vật tư thay thế <span class="muted">(${materialAltGroups.length})</span></h2>
        <div class="muted" style="margin-bottom:6px">Nhiều mã vật tư CÙNG BẢN CHẤT, khác quy cách đóng gói/nhà cung cấp (VD "Malt Úc" gồm Malt Úc rời + Malt Úc bao). Công thức có thể khai NHÓM này thay vì 1 mã cụ thể — thủ kho tự chọn mã cụ thể lúc xuất kho thật, tùy tồn kho lúc đó.</div>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã nhóm</label><input id="mag_code" placeholder="MALT-UC"/></div>
          <div class="field"><label>Tên nhóm</label><input id="mag_name" placeholder="Malt Úc"/></div>
        </div>
        <div class="field" style="margin-top:8px"><label>Vật tư thành viên (giữ Ctrl/Cmd để chọn nhiều)</label>
          <input type="text" id="mag_members_search" placeholder="Tìm theo mã/tên vật tư..." style="width:100%;margin-bottom:4px"/>
          <select id="mag_members" multiple size="6" style="width:100%">${materials.map(m => `<option value="${esc(m.material_id)}">${esc(m.code)} — ${esc(m.name)}</option>`).join("")}</select>
        </div>
        <div class="field" style="margin-top:8px;max-width:260px"><label>Đơn vị nhóm <span class="muted">(mọi thành viên phải khai được đơn vị này)</span></label>
          <select id="mag_unit"><option value="">(chọn thành viên trước)</option></select>
        </div>
        <div class="field" style="margin-top:8px;max-width:340px"><label>Chế độ chọn khi ghi NVL thực tế</label>
          <select id="mag_mode">
            <option value="single">Chỉ được chọn 1 mã (mặc định)</option>
            <option value="multi">Được chọn nhiều mã cùng lúc</option>
          </select>
          <div class="muted" style="font-size:12px;margin-top:2px">"Chỉ 1 mã": các mã hoàn toàn thay thế nhau (VD Malt Úc rời/bao). "Nhiều mã": được dùng phối hợp nhiều mã cho cùng 1 mẻ (VD nhiều loại CO2 khác nồng độ) — định mức riêng từng mã khai trong Công thức.</div>
        </div>
        <button class="btn" id="mag_add" style="margin-top:10px">+ Tạo nhóm</button>` : ""}
        <input class="searchbox" data-tbl="t_matgroups_alt" placeholder="Tìm mã/tên nhóm..." style="margin-top:10px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_matgroups_alt">
          <thead><tr><th>Mã</th><th>Tên</th><th>Thành viên</th><th>ĐVT nhóm</th><th>Chế độ chọn</th><th>Trạng thái</th>${canManage ? "<th></th>" : ""}</tr></thead>
          <tbody>${materialAltGroups.map(g => {
            const memberNames = (g.member_material_ids || []).map(mid => {
              const m = materials.find(x => x.material_id === mid); return m ? `${m.code} — ${m.name}` : mid;
            }).join(", ");
            return `<tr>
            <td><code class="k">${esc(g.code)}</code></td><td>${esc(g.name)}</td>
            <td class="muted">${esc(memberNames || "—")}</td>
            <td>${esc(g.unit || "—")}</td>
            <td class="muted">${g.selection_mode === "multi" ? "Nhiều mã" : "Chỉ 1 mã"}</td>
            <td>${g.active ? '<span style="color:var(--green)">Đang dùng</span>' : '<span class="muted">Đã ẩn</span>'}</td>
            ${canManage ? `<td style="white-space:nowrap">
              <button class="btn sm sec" data-emag="${esc(g.group_id)}">Sửa</button>
              <button class="btn sm sec" data-magdel="${esc(g.group_id)}">Xóa</button>
            </td>` : ""}</tr>`; }).join("") ||
            `<tr><td colspan="${canManage ? 7 : 6}" class="muted">Chưa có nhóm vật tư thay thế nào.</td></tr>`}</tbody>
        </table></div>
      </div>

      <div class="panel" ${mi("nhacc")}><h2>🚚 Nhà cung cấp <span class="muted">(${suppliers.length})</span></h2>
        <div class="muted" style="margin-bottom:6px">Danh mục nhà cung cấp NVL — chọn ở màn hình Nhập kho (tab Kho NVL → Nhập/Xuất/Hoàn/Sang ngang).</div>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã nhà phân phối</label><input id="sp_code" placeholder="NCC-01"/></div>
          <div class="field"><label>Tên</label><input id="sp_name" placeholder="Công ty TNHH ..."/></div>
          <div class="field"><label>Địa chỉ</label><input id="sp_address" placeholder="(tuỳ chọn)"/></div>
          <div class="field"><label>Liên hệ</label><input id="sp_contact" placeholder="(tuỳ chọn)"/></div>
          <button class="btn" id="sp_add" style="align-self:flex-end">+ Tạo nhà cung cấp</button>
        </div>` : ""}
        <input class="searchbox" data-tbl="t_suppliers" placeholder="Tìm mã/tên nhà cung cấp..." style="margin-top:10px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_suppliers">
          <thead><tr><th>Mã nhà phân phối</th><th>Tên</th><th>Địa chỉ</th><th>Liên hệ</th>${canManage ? "<th></th>" : ""}</tr></thead>
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

      <div class="panel" ${mi("nhamaykhac")}><h2>🏭 Nhà máy khác <span class="muted">(${factoryLocations.length})</span></h2>
        <div class="muted" style="margin-bottom:6px">Danh mục nhà máy đích — chọn khi Điều chuyển Kho công ty → Nhà máy khác (tab Kho công ty → Điều chuyển).</div>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã</label><input id="fl_code" placeholder="NM-01"/></div>
          <div class="field"><label>Tên</label><input id="fl_name" placeholder="Nhà máy ..."/></div>
          <div class="field"><label>Địa chỉ</label><input id="fl_address" placeholder="(tuỳ chọn)"/></div>
          <div class="field"><label>Liên hệ</label><input id="fl_contact" placeholder="(tuỳ chọn)"/></div>
          <button class="btn" id="fl_add" style="align-self:flex-end">+ Tạo nhà máy</button>
        </div>` : ""}
        <input class="searchbox" data-tbl="t_factorylocs" placeholder="Tìm mã/tên nhà máy..." style="margin-top:10px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_factorylocs">
          <thead><tr><th>Mã</th><th>Tên</th><th>Địa chỉ</th><th>Liên hệ</th><th>Trạng thái</th>${canManage ? "<th></th>" : ""}</tr></thead>
          <tbody>${factoryLocations.map(fl => `<tr>
            <td><code class="k">${esc(fl.code)}</code></td><td>${esc(fl.name)}</td>
            <td class="muted">${esc(fl.address || "—")}</td><td class="muted">${esc(fl.contact || "—")}</td>
            <td>${fl.active ? '<span style="color:var(--green)">Đang dùng</span>' : '<span class="muted">Đã ẩn</span>'}</td>
            ${canManage ? `<td style="white-space:nowrap">
              <button class="btn sm sec" data-efl="${esc(fl.factory_id)}">Sửa</button>
              <button class="btn sm sec" data-efldel="${esc(fl.factory_id)}">Xóa</button>
            </td>` : ""}</tr>`).join("") ||
            `<tr><td colspan="${canManage ? 6 : 5}" class="muted">Chưa có nhà máy nào.</td></tr>`}</tbody>
        </table></div>
      </div>

      <div class="panel" ${mi("vitrikho")}><h2>📍 Vị trí kho <span class="muted">(${materialLocations.length})</span></h2>
        <div class="muted" style="margin-bottom:6px">Vị trí cất — bắt buộc chọn khi nhập kho tại Kho công ty (tab Kho công ty → Nhập kho), hoặc khi Phân xưởng duyệt nhận điều chuyển từ Kho công ty (tab Kho phân xưởng → Điều chuyển). Chọn phạm vi "Cả 2 kho" để 1 vị trí dùng chung được ở cả 2 màn chọn vị trí. Vị trí đang chứa lô còn tồn (Số lô > 0) không xóa được.</div>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã</label><input id="ml_code" placeholder="A1-01"/></div>
          <div class="field"><label>Tên</label><input id="ml_name" placeholder="Kệ A1 tầng 1"/></div>
          <div class="field"><label>Khu</label><input id="ml_zone" placeholder="(tuỳ chọn)"/></div>
          <div class="field"><label>Dùng cho</label><select id="ml_scope">${locScopeOptsHtml()}</select></div>
          <button class="btn" id="ml_add" style="align-self:flex-end">+ Thêm vị trí</button>
        </div>` : ""}
        <input class="searchbox" data-tbl="t_matlocs" placeholder="Tìm mã/tên/khu vị trí..." style="margin-top:10px"/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_matlocs">
          <thead><tr><th>Mã</th><th>Tên</th><th>Khu</th><th>Dùng cho</th><th>Số lô</th><th>Trạng thái</th>${canManage ? "<th></th>" : ""}</tr></thead>
          <tbody>${materialLocations.map(l => `<tr>
            <td><code class="k">${esc(l.code)}</code></td><td>${esc(l.name)}</td>
            <td class="muted">${esc(l.zone || "—")}</td><td class="muted">${locScopeLabel(l.scope)}</td><td>${l.lot_count}</td>
            <td>${l.active ? '<span style="color:var(--green)">Đang dùng</span>' : '<span class="muted">Đã ẩn</span>'}</td>
            ${canManage ? `<td style="white-space:nowrap">
              <button class="btn sm sec" data-eml="${esc(l.loc_id)}">Sửa</button>
              <button class="btn sm sec" data-emldel="${esc(l.loc_id)}" ${l.lot_count > 0 ? "disabled title=\"Đang chứa lô — không xóa được\"" : ""}>Xóa</button>
            </td>` : ""}</tr>`).join("") ||
            `<tr><td colspan="${canManage ? 7 : 6}" class="muted">Chưa có vị trí nào.</td></tr>`}</tbody>
        </table></div>
      </div>

    <div class="panel" ${mi("khothanhpham")}><h2>🏭 Kho thành phẩm <span class="muted">(${wmsWarehouses.length})</span></h2>
      <div class="muted" style="margin-bottom:8px">Kho thành phẩm là cấp cha của "Vị trí kho" — 1 kho có nhiều vị trí. Kho đang có vị trí (Số vị trí > 0) không xóa được. Chuyển từ Kho TP (WMS) sang đây — chỉ Admin mới tạo/sửa/xóa.</div>
      ${noPermWmsCatalog}
      <div class="tablewrap"><table id="t_wh"><thead><tr><th>Mã</th><th>Tên</th><th>Địa chỉ</th><th>Sheet Lệnh đóng hàng</th><th>Số vị trí</th><th>Hoạt động</th>${isAdminWmsCatalog ? "<th></th>" : ""}</tr></thead>
      <tbody>${wmsWarehouses.map(w => { const loOpts = [["", "(Không gắn)"], ["HL", "HL — Hạ Long"], ["ĐM", "ĐM — Đông Mai"]]
          .map(([v, l]) => `<option value="${v}" ${w.load_order_sheet_type === v || (!w.load_order_sheet_type && !v) ? "selected" : ""}>${l}</option>`).join(""); return `<tr data-wh-row="${esc(w.warehouse_id)}">
        ${isAdminWmsCatalog ? `<td><input class="wh_code" value="${esc(w.code)}" style="width:100px"/></td>
        <td><input class="wh_name" value="${esc(w.name)}" style="width:180px"/></td>
        <td><input class="wh_addr" value="${esc(w.address || "")}" style="width:200px"/></td>
        <td><select class="wh_lo_sheet">${loOpts}</select></td>` :
        `<td><code class="k">${esc(w.code)}</code></td><td>${esc(w.name)}</td><td class="muted">${esc(w.address || "—")}</td>
        <td>${w.load_order_sheet_type ? esc(w.load_order_sheet_type) : "—"}</td>`}
        <td>${w.location_count}</td>
        <td>${isAdminWmsCatalog ? `<input class="wh_active" type="checkbox" ${w.active ? "checked" : ""}/>` : (w.active ? "Có" : "Không")}</td>
        ${isAdminWmsCatalog ? `<td style="white-space:nowrap">
          <button class="btn sm" data-wh-save="${esc(w.warehouse_id)}">Lưu</button>
          <button class="btn sm sec" data-wh-del="${esc(w.warehouse_id)}" ${w.location_count > 0 ? "disabled title=\"Đang có vị trí — không xóa được\"" : ""}>Xóa</button>
        </td>` : ""}</tr>`; }).join("") || `<tr><td colspan="${isAdminWmsCatalog ? 7 : 6}" class="muted">Chưa có kho thành phẩm nào.</td></tr>`}</tbody></table></div>
      ${isAdminWmsCatalog ? `<div class="row" style="margin-top:12px;flex-wrap:wrap">
        <div class="field"><label>Mã</label><input id="wh_new_code" style="width:100px"/></div>
        <div class="field"><label>Tên</label><input id="wh_new_name" style="width:180px"/></div>
        <div class="field"><label>Địa chỉ</label><input id="wh_new_addr" style="width:200px"/></div>
        <div class="field"><label>Sheet Lệnh đóng hàng</label><select id="wh_new_lo_sheet">
          <option value="">(Không gắn)</option><option value="HL">HL — Hạ Long</option><option value="ĐM">ĐM — Đông Mai</option></select></div>
        <div class="field" style="align-self:flex-end"><button class="btn" id="wh_add">+ Thêm kho</button></div>
      </div>` : ""}
    </div>

    <div class="panel" ${mi("vitrikhotp")}><h2>📍 Vị trí kho thành phẩm <span class="muted">(${wmsLocations.length})</span></h2>
      <div class="muted" style="margin-bottom:8px">Vị trí đang chứa vỉ/keg (Sử dụng > 0) không xóa được — hãy chuyển/xuất hết trước. Chuyển từ Kho TP (WMS) sang đây — chỉ Admin mới tạo/sửa/xóa.</div>
      ${noPermWmsCatalog}
      <input class="searchbox" data-tbl="t_wmsloc" placeholder="Tìm theo mã, tên, khu..."/>
      <div class="tablewrap"><table id="t_wmsloc"><thead><tr><th>Mã</th><th>Tên</th><th>Kho thành phẩm</th><th>Khu</th><th>Loại</th><th>Sức chứa</th><th>Sử dụng</th><th>Hoạt động</th>${isAdminWmsCatalog ? "<th></th>" : ""}</tr></thead>
      <tbody>${wmsLocations.map(l => { const wh = wmsWarehouses.find(w => w.warehouse_id === l.warehouse_id);
        const kindLabel = { bin: "Kệ/ô chứa", staging: "Khu tập kết tạm", cold: "Kho lạnh", dock: "Bãi xuất/nhập hàng" };
        const whOpt = (sel) => `<option value="">(không có kho)</option>` + wmsWarehouses.map(w =>
          `<option value="${esc(w.warehouse_id)}" ${w.warehouse_id === sel ? "selected" : ""}>${esc(w.code)} — ${esc(w.name)}</option>`).join("");
        const kindOpt = (sel) => ["bin", "staging", "cold", "dock"].map(k =>
          `<option value="${k}" ${k === sel ? "selected" : ""}>${kindLabel[k]}</option>`).join("");
        return `<tr data-loc-row="${esc(l.loc_id)}">
        ${isAdminWmsCatalog ? `<td><input class="wl_code" value="${esc(l.code)}" style="width:90px"/></td>
        <td><input class="wl_name" value="${esc(l.name)}" style="width:160px"/></td>
        <td><select class="wl_wh" style="width:160px">${whOpt(l.warehouse_id)}</select></td>
        <td><input class="wl_zone" value="${esc(l.zone || "")}" style="width:60px"/></td>
        <td><select class="wl_kind">${kindOpt(l.kind)}</select></td>
        <td><input class="wl_capacity" type="number" value="${l.capacity}" style="width:100px"/></td>` :
        `<td><code class="k">${esc(l.code)}</code></td><td>${esc(l.name)}</td>
        <td class="muted">${wh ? esc(wh.code) + " — " + esc(wh.name) : "—"}</td>
        <td class="muted">${esc(l.zone || "—")}</td><td class="muted">${esc(kindLabel[l.kind] || l.kind)}</td>
        <td>${l.capacity}</td>`}
        <td>${l.used}</td>
        <td>${isAdminWmsCatalog ? `<input class="wl_active" type="checkbox" ${l.active ? "checked" : ""}/>` : (l.active ? "Có" : "Không")}</td>
        ${isAdminWmsCatalog ? `<td style="white-space:nowrap">
          <button class="btn sm" data-loc-save="${esc(l.loc_id)}">Lưu</button>
          <button class="btn sm sec" data-loc-del="${esc(l.loc_id)}" ${l.used > 0 ? "disabled title=\"Đang có vỉ/keg — không xóa được\"" : ""}>Xóa</button>
          <button class="btn sm sec" data-loc-split="${esc(l.loc_id)}" ${!l.active ? "disabled title=\"Đã ngừng hoạt động\"" : ""}>Chia ô</button>
        </td>` : ""}</tr>`; }).join("") || `<tr><td colspan="${isAdminWmsCatalog ? 9 : 8}" class="muted">Chưa có vị trí nào.</td></tr>`}</tbody></table></div>
      <div class="muted" style="font-size:12px;margin-top:6px">"Chia ô": tạo N vị trí con thật (VD "DM.K01" → "DM.K01-Ô1"…"Ô4"), mỗi ô có sức chứa/tồn kho riêng — tồn hiện có của dãy gốc dồn hết vào Ô1, dãy gốc tự ngừng hoạt động (không xóa, vẫn giữ lịch sử điều chuyển/bia gửi/cận date cũ tham chiếu tới). Xếp thêm các ô mới vào "Bố cục kho" phía dưới sau khi chia.</div>
      ${isAdminWmsCatalog ? `<div class="row" style="margin-top:12px;flex-wrap:wrap">
        <div class="field"><label>Mã</label><input id="wl_new_code" style="width:90px"/></div>
        <div class="field"><label>Tên</label><input id="wl_new_name" style="width:160px"/></div>
        <div class="field"><label>Kho thành phẩm</label><select id="wl_new_wh" style="width:160px"><option value="">(không có kho)</option>${wmsWarehouses.map(w => `<option value="${esc(w.warehouse_id)}">${esc(w.code)} — ${esc(w.name)}</option>`).join("")}</select></div>
        <div class="field"><label>Khu</label><input id="wl_new_zone" style="width:60px"/></div>
        <div class="field"><label>Loại</label><select id="wl_new_kind"><option value="bin">Kệ/ô chứa</option><option value="staging">Khu tập kết tạm</option><option value="cold">Kho lạnh</option><option value="dock">Bãi xuất/nhập hàng</option></select></div>
        <div class="field"><label>Sức chứa</label><input id="wl_new_capacity" type="number" value="10" style="width:100px"/></div>
        <div class="field" style="align-self:flex-end"><button class="btn" id="wl_add">+ Thêm vị trí</button></div>
      </div>` : ""}
    </div>

    ${isAdminWmsCatalog && wmsWarehouses.length ? (() => {
      if (!WMS_LAYOUT_WH || !wmsWarehouses.some(w => w.warehouse_id === WMS_LAYOUT_WH)) WMS_LAYOUT_WH = wmsWarehouses[0].warehouse_id;
      const locsInWh = wmsLocations.filter(l => l.warehouse_id === WMS_LAYOUT_WH && l.active);
      const whOptionsHtml = wmsWarehouses.map(w => `<option value="${esc(w.warehouse_id)}" ${w.warehouse_id === WMS_LAYOUT_WH ? "selected" : ""}>${esc(w.code)} — ${esc(w.name)}</option>`).join("");
      return `<div class="panel" ${mi("boccuckho")}><h2>🗺️ Bố cục kho</h2>
        <div class="muted" style="margin-bottom:8px">Tự xếp vị trí lên lưới hàng/cột đúng theo mặt bằng thật ngoài kho — "Sơ đồ kho" (tab Kho TP) chỉ vẽ lại đúng bố cục đã xếp ở đây, không đoán theo mã vị trí.</div>
        ${locsInWh.length ? renderWmsLayoutGrid(WMS_LAYOUT_WH, locsInWh, whOptionsHtml)
          : `<div class="row" style="margin-bottom:8px"><div class="field"><label>Kho thành phẩm</label><select id="wlo_wh">${whOptionsHtml}</select></div></div>
          <div class="muted">Kho này chưa có vị trí nào — thêm ở bảng "Vị trí kho thành phẩm" phía trên trước.</div>`}
      </div>`;
    })() : ""}

    <div class="panel" ${mi("laixe")}><h2>🚚 Lái xe <span class="muted">(${wmsVehicles.length})</span></h2>
      <div class="muted" style="margin-bottom:8px">Biển số xe kèm lái xe/tải trọng/số pallet chở được — tra cứu nhanh khi lập Lệnh đóng hàng hoặc Phiếu xuất kho. Chuyển từ Kho TP (WMS) sang đây — chỉ Admin mới tạo/sửa/xóa.</div>
      ${noPermWmsCatalog}
      <input class="searchbox" data-tbl="t_vehicle" placeholder="Tìm theo biển số, tên lái xe, tổ đội..."/>
      <div class="tablewrap"><table id="t_vehicle"><thead><tr><th>Mã xe</th><th>Biển số</th><th>Số xe</th><th>Họ và tên lái xe</th><th>Tên lái xe</th>
        <th>Khối lượng (kg)</th><th>Pallet</th><th>Số ĐT</th><th>Tổ đội</th><th>Hoạt động</th>${isAdminWmsCatalog ? "<th></th>" : ""}</tr></thead>
      <tbody>${wmsVehicles.map(v => `<tr data-vehicle-row="${esc(v.vehicle_id)}">
        <td class="muted"><code class="k">${esc(v.vehicle_code || "—")}</code></td>
        ${isAdminWmsCatalog ? `<td><input class="vh_plate" value="${esc(v.plate)}" style="width:100px"/></td>
        <td class="muted"><code class="k">${esc(plateLast5(v.plate))}</code></td>
        <td><input class="vh_driver" value="${esc(v.driver_name || "")}" style="width:180px"/></td>
        <td><input class="vh_short" value="${esc(v.driver_short_name || "")}" style="width:100px"/></td>
        <td><input class="vh_cap" type="number" value="${v.capacity_kg ?? ""}" style="width:90px"/></td>
        <td><input class="vh_pallet" type="number" value="${v.pallet_capacity ?? ""}" style="width:70px"/></td>
        <td><input class="vh_phone" value="${esc(v.phone || "")}" style="width:120px"/></td>
        <td><input class="vh_team" value="${esc(v.team || "")}" style="width:90px"/></td>` :
        `<td>${esc(v.plate)}</td><td class="muted"><code class="k">${esc(plateLast5(v.plate))}</code></td><td class="muted">${esc(v.driver_name || "—")}</td><td class="muted">${esc(v.driver_short_name || "—")}</td>
        <td class="muted">${v.capacity_kg ?? "—"}</td><td class="muted">${v.pallet_capacity ?? "—"}</td>
        <td class="muted">${esc(v.phone || "—")}</td><td class="muted">${esc(v.team || "—")}</td>`}
        <td>${isAdminWmsCatalog ? `<input class="vh_active" type="checkbox" ${v.active ? "checked" : ""}/>` : (v.active ? "Có" : "Không")}</td>
        ${isAdminWmsCatalog ? `<td style="white-space:nowrap">
          <button class="btn sm" data-vehicle-save="${esc(v.vehicle_id)}">Lưu</button>
          <button class="btn sm sec" data-vehicle-del="${esc(v.vehicle_id)}">Xóa</button>
        </td>` : ""}</tr>`).join("") || `<tr><td colspan="${isAdminWmsCatalog ? 11 : 10}" class="muted">Chưa có xe nào.</td></tr>`}</tbody></table></div>
      ${isAdminWmsCatalog ? `<div class="row" style="margin-top:12px;flex-wrap:wrap">
        <div class="field"><label>Biển số</label><input id="vh_new_plate" style="width:100px"/></div>
        <div class="field"><label>Họ và tên lái xe</label><input id="vh_new_driver" style="width:180px"/></div>
        <div class="field"><label>Tên lái xe</label><input id="vh_new_short" style="width:100px"/></div>
        <div class="field"><label>Khối lượng (kg)</label><input id="vh_new_cap" type="number" style="width:90px"/></div>
        <div class="field"><label>Pallet</label><input id="vh_new_pallet" type="number" style="width:70px"/></div>
        <div class="field"><label>Số ĐT</label><input id="vh_new_phone" style="width:120px"/></div>
        <div class="field"><label>Tổ đội</label><input id="vh_new_team" style="width:90px"/></div>
        <div class="field" style="align-self:flex-end"><button class="btn" id="vh_add">+ Thêm xe</button></div>
      </div>` : ""}
    </div>

    <div class="panel" ${mi("sanpham")}><h2>🍾 Sản phẩm (thành phẩm) <span class="muted">(${finishedProducts.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">SKU đóng gói (chai/lon/keg...) — chọn ở bước Chiết cùng tank BBT nguồn. Khác Dịch bia ở trên: cùng 1 dịch bia có thể ra nhiều Sản phẩm khác nhau.</div>
      ${noPerm}
      ${canManage ? `<div class="row">
        <div class="field"><label>Mã sản phẩm</label><input id="fp_code" placeholder="SKU-LON-330"/></div>
        <div class="field"><label>Tên sản phẩm</label><input id="fp_name" placeholder="Lon 330ml"/></div>
        <div class="field"><label>ĐVT</label><input id="fp_uom" value="lon" style="width:80px"/></div>
        <div class="field"><label>Loại đơn vị tồn kho</label><select id="fp_unittype">${selectableUnitTypes.map(ut => `<option value="${esc(ut.code)}">${esc(ut.name)}</option>`).join("")}</select></div>
        <div class="field"><label>SL/1 đơn vị</label><input id="fp_pack" type="number" value="24" style="width:80px"/></div>
        <div class="field"><label>Dung tích/1 đơn vị (lít)</label><input id="fp_volumel" type="number" step="0.01" placeholder="VD 0.33" style="width:100px"/></div>
        <div class="field"><label>Loại sản phẩm</label><select id="fp_cat"><option value="">(không chọn)</option>${fpCats.map(c => `<option>${esc(c)}</option>`).join("")}</select></div>
        <div class="field"><label>Dịch bia gốc (tuỳ chọn)</label><select id="fp_product"><option value="">(không chọn)</option>${products.map(p => `<option value="${p.product_id}">${esc(p.code)}</option>`).join("")}</select></div>
        <div class="field"><label>Khối lượng/1 đơn vị (vỉ hoặc keg) (kg)</label><input id="fp_weightcase" type="number" step="0.01" placeholder="VD 9.6" style="width:120px"/></div>
        <div class="field"><label>Khối lượng/1 lon-chai (kg)</label><input id="fp_weightunit" type="number" step="0.01" placeholder="VD 0.4" style="width:110px"/></div>
      </div>
      <div class="muted" style="font-size:12px;margin-top:4px">Vỉ: SL/1 đơn vị = số lon/vỉ (VD 24). Keg: mỗi keg tự nó là 1 đơn vị (SL/1 đơn vị = 1). Dung tích/1 đơn vị dùng để đối chiếu Ca1+Ca2+Ca3 với V cấp chiết lúc "Kết thúc chiết" — để trống thì bỏ qua đối chiếu. Khối lượng dùng cho báo cáo tải trọng xe (Báo cáo → Xe & bia gửi): "Khối lượng/1 đơn vị" = 1 vỉ HOẶC 1 keg nguyên; "Khối lượng/1 lon-chai" chỉ áp dụng khi SKU vỉ bị phân rã thành lon/chai lẻ.</div>
      <div class="field" style="margin-top:6px"><label>Mô tả</label><input id="fp_desc" placeholder="(tuỳ chọn)" style="width:100%"/></div>
      <button class="btn" id="fp_add" style="margin-top:10px">+ Tạo sản phẩm</button>` : ""}
      <input class="searchbox" data-tbl="t_fp" placeholder="Tìm theo mã, tên, loại sản phẩm..." style="margin-top:10px"/>
      <div class="tablewrap" style="margin-top:12px"><table id="t_fp">
        <thead><tr><th>Mã</th><th>Tên</th><th>ĐVT</th><th>Loại đơn vị</th><th>SL/1 đơn vị</th><th>Dung tích/1 đơn vị (l)</th><th>KL/1 vỉ-keg (kg)</th><th>KL/1 lon-chai (kg)</th><th>Loại sản phẩm</th><th>Dịch bia gốc</th><th>Mô tả</th>${canManage ? "<th></th>" : ""}</tr></thead>
        <tbody>${finishedProducts.map(fp => { const prod = products.find(p => p.product_id === fp.product_id); return `<tr>
          <td><code class="k">${esc(fp.code)}</code></td><td>${esc(fp.name)}</td><td>${esc(fp.uom)}</td>
          <td>${esc((unitTypes.find(ut => ut.code === fp.unit_type) || {}).name || fp.unit_type)}</td>
          <td>${fp.pack_size}</td>
          <td class="muted">${fp.unit_volume_l != null ? fp.unit_volume_l : "—"}</td>
          <td class="muted">${fp.weight_primary_kg != null ? fp.weight_primary_kg : "—"}</td>
          <td class="muted">${fp.weight_single_kg != null ? fp.weight_single_kg : "—"}</td>
          <td class="muted">${esc(fp.category || "—")}</td>
          <td class="muted">${prod ? esc(prod.code) : "—"}</td>
          <td class="muted">${esc(fp.description || "—")}</td>
          ${canManage ? `<td style="white-space:nowrap">
            <button class="btn sm sec" data-efp="${esc(fp.finished_product_id)}">Sửa</button>
            <button class="btn sm sec" data-efpdel="${esc(fp.finished_product_id)}">Xóa</button>
          </td>` : ""}</tr>`; }).join("") ||
          `<tr><td colspan="${canManage ? 10 : 9}" class="muted">Chưa có sản phẩm nào.</td></tr>`}</tbody>
      </table></div>
    </div>

    <div class="panel" ${mi("loaidonvi")}><h2>📐 Loại đơn vị tồn kho <span class="muted">(${unitTypes.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Cách quy đổi số lượng đóng gói (dùng ở Sản phẩm bên trên và mọi thao tác Kho TP): "Chia theo SL/1 đơn vị" giống Vỉ (VD Thùng chứa nhiều vỉ), hoặc không chia — giống Keg (1 đơn vị = 1, không nhân thêm).</div>
      ${noPerm}
      ${canManage ? `<div class="row">
        <div class="field"><label>Mã</label><input id="ut_code" placeholder="thung" style="width:100px" title="Chữ thường a-z, số, gạch dưới — KHÔNG dấu tiếng Việt (VD: thung, két). Tên tiếng Việt có dấu nhập ở ô Tên hiển thị."/></div>
        <div class="field"><label>Tên hiển thị</label><input id="ut_name" placeholder="Thùng"/></div>
        <div class="field"><label>Cách quy đổi</label><select id="ut_divide">
          <option value="0">Không chia (giống Keg — 1 đơn vị = 1)</option>
          <option value="1">Chia theo SL/1 đơn vị (giống Vỉ)</option></select></div>
        <button class="btn" id="ut_add" style="align-self:flex-end">+ Tạo loại đơn vị</button>
      </div>` : ""}
      <div class="tablewrap" style="margin-top:10px"><table id="t_unittypes">
        <thead><tr><th>Mã</th><th>Tên hiển thị</th><th>Cách quy đổi</th><th>Hiện khi khai báo SKU</th>${canManage ? "<th></th>" : ""}</tr></thead>
        <tbody>${unitTypes.map(ut => `<tr>
          <td><code class="k">${esc(ut.code)}</code></td><td>${esc(ut.name)}</td>
          <td class="muted">${ut.divide_by_pack_size ? "Chia theo SL/1 đơn vị" : "Không chia (1:1)"}</td>
          <td class="muted">${ut.selectable ? "Có" : "Không (hệ thống tự sinh)"}</td>
          ${canManage ? `<td style="white-space:nowrap">
            <button class="btn sm sec" data-eut="${esc(ut.unit_type_id)}">Sửa</button>
            <button class="btn sm sec" data-utdel="${esc(ut.unit_type_id)}">Xóa</button>
          </td>` : ""}</tr>`).join("") ||
          `<tr><td colspan="${canManage ? 5 : 4}" class="muted">Chưa có loại đơn vị nào.</td></tr>`}</tbody>
      </table></div>
    </div>

    <div class="panel" ${mi("chitieucl")}><h2>📋 Danh mục chỉ tiêu chất lượng <span class="muted">(${qcParams.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Chỉ tiêu dùng chung, tạo 1 lần ở đây rồi gán vào từng nhóm ("Chỉ tiêu trong nhóm" ở bảng bên dưới).</div>
      ${noPerm}
      ${canManage ? `<div class="row">
        <div class="field"><label>Mã CT</label><input id="qp_code" placeholder="DO_AM"/></div>
        <div class="field"><label>Tên chỉ tiêu</label><input id="qp_name" placeholder="Độ ẩm"/></div>
        <div class="field"><label>Kiểu ghi nhận</label><select id="qp_value_type">
          <option value="numeric">Nhập số (so target/USL/LSL)</option>
          <option value="pass_fail">Đạt / Không đạt</option>
          <option value="text">Nhập text (không so sánh)</option></select></div>
        <div class="field"><label>ĐVT</label><input id="qp_unit" placeholder="%" style="width:80px"/></div>
        <div class="field"><label>Phương pháp thử</label><input id="qp_method" placeholder="(tuỳ chọn)"/></div>
        <button class="btn" id="qp_add" style="align-self:flex-end">+ Tạo chỉ tiêu</button>
      </div>` : ""}
      <input class="searchbox" data-tbl="t_qcparam" placeholder="Tìm mã/tên chỉ tiêu..." style="margin-top:10px"/>
      <div class="tablewrap" style="margin-top:8px"><table id="t_qcparam">
        <thead><tr><th>Mã CT</th><th>Tên</th><th>Kiểu</th><th>ĐVT</th><th>Phương pháp thử</th><th>Trạng thái</th>${canManage ? "<th></th>" : ""}</tr></thead>
        <tbody>${qcParams.map(p => `<tr>
          <td><code class="k">${esc(p.code)}</code></td><td>${esc(p.name)}</td>
          <td class="muted">${p.value_type === "pass_fail" ? "Đạt/Không đạt" : p.value_type === "text" ? "Text" : "Số"}</td>
          <td class="muted">${esc(p.unit || "—")}</td><td class="muted">${esc(p.method || "—")}</td>
          <td>${badge(p.active ? "available" : "obsolete")}${p.active ? "hoạt động" : "ngừng"}</td>
          ${canManage ? `<td style="white-space:nowrap"><button class="btn sm sec" data-qpedit="${esc(p.param_id)}">Sửa</button>
            <button class="btn sm sec" data-qptoggle="${esc(p.param_id)}">${p.active ? "Ngừng" : "Kích hoạt"}</button>
            <button class="btn sm sec" data-qpdel="${esc(p.param_id)}">Xóa</button></td>` : ""}</tr>`).join("") ||
          `<tr><td colspan="${canManage ? 7 : 6}" class="muted">Chưa có chỉ tiêu nào.</td></tr>`}</tbody>
      </table></div>
    </div>

    <div class="panel" ${mi("nhomchitieucl")}><h2>🧪 Nhóm chỉ tiêu chất lượng <span class="muted">(${qcGroups.length})</span></h2>
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
        <thead><tr><th>Mã</th><th>Tên</th><th>Ghi chú</th><th>Trạng thái</th><th></th></tr></thead>
        <tbody>${qcGroups.map(g => `<tr>
          <td><code class="k">${esc(g.code)}</code></td><td>${esc(g.name)}</td>
          <td class="muted">${esc(g.note || "—")}</td>
          <td>${badge(g.active ? "available" : "obsolete")}${g.active ? "hoạt động" : "ngừng"}</td>
          <td style="white-space:nowrap"><button class="btn sm sec" data-qgi="${esc(g.group_id)}">Chỉ tiêu trong nhóm</button>
            ${canManage ? `<button class="btn sm sec" data-qgedit="${esc(g.group_id)}">Sửa</button>
            <button class="btn sm sec" data-qgdel="${esc(g.group_id)}">Xóa</button>` : ""}</td></tr>`).join("")}</tbody>
      </table></div>
    </div>

    <div class="panel" ${mi("nhomchitieucongdoan")}><h2>🍺 Nhóm chỉ tiêu theo công đoạn sản xuất <span class="muted">(${stageGroups.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Gán nhóm chỉ tiêu (ở bảng trên) cho một công đoạn — mẻ nấu, lên men chính/phụ, lọc,
        thành phẩm, nước nấu bia — để bắt buộc khai báo trước khi được duyệt/xuất tiếp. Nấu/Lên men tra theo <b>Dịch bia</b> (phân biệt cả độ oP);
        Lọc/Thành phẩm tra theo <b>Loại bia</b> (thương hiệu, VD Sapphire — không phân biệt oP, vì lọc phối có thể gộp nhiều
        Dịch bia cùng 1 Loại bia). Để trống Loại bia/Sản phẩm = áp dụng cho mọi loại bia/sản phẩm thuộc Loại bia đó — cùng 1 Loại bia
        vẫn có thể cần chỉ tiêu Lọc/Thành phẩm khác nhau theo hình thức đóng gói (VD Legend chai khác Legend tươi): chọn thêm
        <b>Sản phẩm</b> ở đây để gán riêng, nhóm gán riêng theo Sản phẩm luôn thắng nhóm áp dụng chung. Với Lọc, mỗi mẻ lọc biết mình
        thuộc Sản phẩm nào là do khai báo 1 lần ở Lệnh lọc (mục Lệnh SX) rồi tự kế thừa xuống — không cần chọn lại. Công đoạn "Chiết"
        dùng chung chỉ tiêu với "Thành phẩm" (không có mục riêng trong danh sách Công đoạn bên dưới). Công đoạn <b>"Nước nấu bia"</b>
        không có Dịch bia/Loại bia để chọn — nhóm gán ở đây luôn áp dụng chung cho MỌI mẻ nấu, không phân biệt loại bia.</div>
      ${noPerm}
      ${canManage ? `<div class="row">
        <div class="field"><label>Công đoạn</label><select id="sg_stage"><option value="">-- Chọn công đoạn --</option>${Object.entries(STAGE_LABELS).filter(([k]) => k !== "chiet").map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></div>
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

    ${lineSectionHtml("line", "🏭 Dây chuyền sản xuất", plines.filter(l => l.kind === "line" || l.kind === "brewhouse"), canManage, noPerm, mi("daychuyen"))}
    ${lineSectionHtml("tank", "🛢️ Tank lên men", plines.filter(l => l.kind === "tank"), canManage, noPerm, mi("tanklm"))}
    ${lineSectionHtml("tank_bbt", "🧪 Tank thành phẩm (BBT)", plines.filter(l => l.kind === "tank_bbt"), canManage, noPerm, mi("tankbbt"))}

    <div class="panel" ${mi("caidatvanhanh")}><h2>⚙️ Cài đặt vận hành</h2>
      <div class="muted" style="margin-bottom:6px">Ngưỡng dung sai thể tích (hl) cho phép nút "Làm rỗng" (tab Lọc, modal Tank) buộc tồn tank
        CCT/BBT về 0 — chỉ dùng khi tank vật lý đã cạn/chiết hết thật nhưng số liệu phần mềm còn lệch một khoảng nhỏ do hao hụt đo
        đạc. Nếu phần lệch vượt ngưỡng này, hệ thống sẽ chặn (báo lỗi) để tránh xoá nhầm sai lệch lớn do lỗi nhập liệu thật.</div>
      ${noPerm}
      <div class="row">
        <div class="field"><label>Ngưỡng làm rỗng CCT (hl)</label><input id="ops_cct_tol" type="number" step="any" value="${opsSettings.empty_cct_tolerance_hl}" ${canManage ? "" : "disabled"}/></div>
        <div class="field"><label>Ngưỡng làm rỗng BBT (hl)</label><input id="ops_bbt_tol" type="number" step="any" value="${opsSettings.empty_bbt_tolerance_hl}" ${canManage ? "" : "disabled"}/></div>
      </div>
      <div class="muted" style="margin:10px 0 6px">Ngưỡng số ngày tồn dự kiến (= tồn thực tế / lượng xuất TB 7 ngày) để đề xuất "Đóng bổ
        sung" trên báo cáo "NXT kho thành phẩm" (Kho TP) — áp dụng chung mọi SKU. Cũng dùng làm ngưỡng màu Vàng/Xanh cho cột
        "Số ngày tồn dự kiến"; dưới ngưỡng Đỏ thì hiện Đỏ.</div>
      <div class="row">
        <div class="field"><label>Ngưỡng đóng bổ sung / Đỏ-Vàng (ngày)</label><input id="ops_restock_days" type="number" step="any" value="${opsSettings.finished_goods_restock_days}" ${canManage ? "" : "disabled"}/></div>
        <div class="field"><label>Ngưỡng Đỏ — Số ngày tồn dự kiến (ngày)</label><input id="ops_fg_critical_days" type="number" step="any" value="${opsSettings.fg_days_of_stock_critical_days}" ${canManage ? "" : "disabled"}/></div>
        <div class="field"><label>Ngưỡng Vàng — Số ngày lưu kho (ngày)</label><input id="ops_fg_instock_warning_days" type="number" step="any" value="${opsSettings.fg_days_in_stock_warning_days}" ${canManage ? "" : "disabled"}/></div>
      </div>
      <div class="muted" style="margin:10px 0 6px">Giờ cắt "ngày vận hành" (0-23, giờ VN) cho báo cáo "NXT kho thành phẩm" › mục "Theo ngày" —
        1 "ngày" = từ giờ này của ngày hôm trước đến đúng giờ này của ngày hôm sau, không cố định 00h-24h (VD chọn 6 thì "ngày 9/8"
        = 06h00 9/8 đến 06h00 10/8, khớp ca đêm 22h-06h không bị cắt đôi giữa 2 ngày lịch).</div>
      <div class="row">
        <div class="field"><label>Giờ cắt ngày (0-23)</label><input id="ops_fg_cutoff_hour" type="number" min="0" max="23" step="1" value="${opsSettings.fg_day_cutoff_hour ?? 0}" style="width:100px" ${canManage ? "" : "disabled"}/></div>
      </div>
      <div class="muted" style="margin:10px 0 6px">Số ngày lùi tối đa cho phép ở "Ngày nhập" khi Nhập kho thủ công (Kho TP) hoặc khai báo
        Nhập từ nhà máy khác — tránh gõ nhầm ngày quá xa trong quá khứ (không áp dụng cho Nhập tồn đầu).</div>
      <div class="row">
        <div class="field"><label>Số ngày lùi tối đa — Ngày nhập (ngày)</label><input id="ops_fg_max_backdate_days" type="number" step="any" value="${opsSettings.finished_goods_receive_max_backdate_days}" ${canManage ? "" : "disabled"}/></div>
      </div>
      <div class="muted" style="margin:10px 0 6px">Ngưỡng sản lượng (hl) để phân loại 1 mẻ lọc đã kết thúc là Thấp/Bình thường/Cao trên báo cáo
        "Sản lượng lọc" (tab Báo cáo) — mẻ Thấp sẽ được cảnh báo trên báo cáo đó.</div>
      <div class="row">
        <div class="field"><label>Ngưỡng sản lượng Thấp (hl)</label><input id="ops_yield_low" type="number" step="any" value="${opsSettings.filter_yield_low_hl}" ${canManage ? "" : "disabled"}/></div>
        <div class="field"><label>Ngưỡng sản lượng Cao (hl)</label><input id="ops_yield_high" type="number" step="any" value="${opsSettings.filter_yield_high_hl}" ${canManage ? "" : "disabled"}/></div>
      </div>
      <div class="muted" style="margin:10px 0 6px">Ngưỡng sản lượng (lít) để phân loại TỪNG DÒNG "mẻ lọc số" (1 đợt rút dịch riêng) đã kết
        thúc là Thấp/Bình thường/Cao trên báo cáo "Sản lượng lọc" › mục "Theo mẻ lọc số" — khác đơn vị/quy mô với 2 ngưỡng ở trên
        vì đó là tổng cả bản ghi lọc, còn đây là 1 đợt rút dịch riêng lẻ.</div>
      <div class="row">
        <div class="field"><label>Ngưỡng mẻ lọc số Thấp (lít)</label><input id="ops_line_yield_low" type="number" step="any" value="${opsSettings.filter_line_yield_low_l}" ${canManage ? "" : "disabled"}/></div>
        <div class="field"><label>Ngưỡng mẻ lọc số Cao (lít)</label><input id="ops_line_yield_high" type="number" step="any" value="${opsSettings.filter_line_yield_high_l}" ${canManage ? "" : "disabled"}/></div>
      </div>
      <div class="muted" style="margin:10px 0 6px">Mã nhận dạng nhà máy — in/dập trên bao bì thực tế, giúp truy vết ngoài thị trường sản phẩm được chiết từ nhà máy nào.</div>
      <div class="row">
        <div class="field"><label>Mã nhà máy</label><input id="ops_factory_code" value="${esc(opsSettings.factory_code || "")}" placeholder="VD: DM01" style="width:120px" ${canManage ? "" : "disabled"}/></div>
      </div>
      ${canManage ? `<button class="btn" id="ops_save" style="margin-top:10px">Lưu tất cả cài đặt vận hành</button>` : ""}
      ${opsSettings.updated_by ? `<div class="muted" style="font-size:12px;margin-top:6px">Cập nhật lần cuối: ${esc(opsSettings.updated_by)} · ${fmt(opsSettings.updated_at)}</div>` : ""}
    </div>
    </div>`;

  wireSubnav("master");
  document.querySelectorAll("#nav [data-mastergrp]").forEach(b => b.classList.toggle("active", b.dataset.mastergrp === MASTER_GROUP));
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
  wirePaginate("t_matgroups_alt", 10);
  wirePaginate("t_factorylocs", 10);
  wirePaginate("t_wh", 10);
  wirePaginate("t_wmsloc", 10);
  wirePaginate("t_vehicle", 10);
  wirePaginate("t_unittypes", 10);
  wirePaginate("t_lines_line", 10);
  wirePaginate("t_lines_tank", 10);
  wirePaginate("t_lines_tank_bbt", 10);
  // Xem chỉ tiêu trong nhóm là hành động chỉ-đọc — luôn cho phép bấm dù không có quyền
  // master.manage (khối if (canManage) dưới đây chỉ chứa các hành động tạo/sửa/xóa).
  document.querySelectorAll("[data-qgi]").forEach(b => b.onclick = () => {
    const g = qcGroups.find(x => x.group_id === b.dataset.qgi);
    openQcGroupItemsModal(g);
  });
  if (canManage) {
    if ($("pr_add")) $("pr_add").onclick = () => guard(async () => {
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
        filter_yield_low_hl: parseFloat($("ops_yield_low").value) || 0,
        filter_yield_high_hl: parseFloat($("ops_yield_high").value) || 0,
        filter_line_yield_low_l: parseFloat($("ops_line_yield_low").value) || 0,
        filter_line_yield_high_l: parseFloat($("ops_line_yield_high").value) || 0,
        finished_goods_restock_days: parseFloat($("ops_restock_days").value) || 7,
        fg_days_of_stock_critical_days: parseFloat($("ops_fg_critical_days").value) || 3,
        fg_days_in_stock_warning_days: parseFloat($("ops_fg_instock_warning_days").value) || 30,
        finished_goods_receive_max_backdate_days: parseFloat($("ops_fg_max_backdate_days").value) || 15,
        fg_day_cutoff_hour: Math.min(23, Math.max(0, parseInt($("ops_fg_cutoff_hour").value, 10) || 0)),
        factory_code: $("ops_factory_code").value.trim() || null,
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
    if ($("ut_add")) $("ut_add").onclick = () => guard(async () => {
      await POST("/unit-types", { code: $("ut_code").value.trim().toLowerCase(), name: $("ut_name").value.trim(),
        divide_by_pack_size: $("ut_divide").value === "1", selectable: true, active: true });
      toast("Đã tạo loại đơn vị"); render("master");
    });
    document.querySelectorAll("[data-eut]").forEach(b => b.onclick = () => {
      const ut = unitTypes.find(x => x.unit_type_id === b.dataset.eut);
      modal(`<h3>Sửa loại đơn vị tồn kho</h3>
        <div class="field"><label>Mã</label><input id="eut_code" value="${esc(ut.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên hiển thị</label><input id="eut_name" value="${esc(ut.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>Cách quy đổi</label><select id="eut_divide">
          <option value="0" ${!ut.divide_by_pack_size ? "selected" : ""}>Không chia (giống Keg — 1 đơn vị = 1)</option>
          <option value="1" ${ut.divide_by_pack_size ? "selected" : ""}>Chia theo SL/1 đơn vị (giống Vỉ)</option></select></div>
        <div class="field" style="margin-top:8px"><label>Hiện khi khai báo SKU mới</label><select id="eut_selectable">
          <option value="1" ${ut.selectable ? "selected" : ""}>Có</option>
          <option value="0" ${!ut.selectable ? "selected" : ""}>Không</option></select></div>
        <button class="btn" id="eut_save" style="margin-top:12px">Lưu</button>`);
      $("eut_save").onclick = () => guard(async () => {
        await PUT(`/unit-types/${ut.unit_type_id}`, { code: $("eut_code").value.trim().toLowerCase(),
          name: $("eut_name").value.trim(), divide_by_pack_size: $("eut_divide").value === "1",
          selectable: $("eut_selectable").value === "1", active: true });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-utdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa loại đơn vị tồn kho này? Không thể hoàn tác.")) return;
      await DELETE(`/unit-types/${b.dataset.utdel}`);
      toast("Đã xóa loại đơn vị"); render("master");
    }));
    if ($("sp_add")) $("sp_add").onclick = () => guard(async () => {
      await POST("/suppliers", { code: $("sp_code").value.trim(), name: $("sp_name").value.trim(),
        address: $("sp_address").value.trim() || null, contact: $("sp_contact").value.trim() || null });
      toast("Đã tạo nhà cung cấp"); render("master");
    });
    document.querySelectorAll("[data-esp]").forEach(b => b.onclick = () => {
      const sp = suppliers.find(x => x.supplier_id === b.dataset.esp);
      modal(`<h3>Sửa nhà cung cấp</h3>
        <div class="field"><label>Mã nhà phân phối</label><input id="esp_code" value="${esc(sp.code)}"/></div>
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
    if ($("fl_add")) $("fl_add").onclick = () => guard(async () => {
      await POST("/factory-locations", { code: $("fl_code").value.trim(), name: $("fl_name").value.trim(),
        address: $("fl_address").value.trim() || null, contact: $("fl_contact").value.trim() || null });
      toast("Đã tạo nhà máy"); render("master");
    });
    document.querySelectorAll("[data-efl]").forEach(b => b.onclick = () => {
      const fl = factoryLocations.find(x => x.factory_id === b.dataset.efl);
      modal(`<h3>Sửa nhà máy</h3>
        <div class="field"><label>Mã</label><input id="efl_code" value="${esc(fl.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="efl_name" value="${esc(fl.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>Địa chỉ</label><input id="efl_address" value="${esc(fl.address || "")}"/></div>
        <div class="field" style="margin-top:8px"><label>Liên hệ</label><input id="efl_contact" value="${esc(fl.contact || "")}"/></div>
        <div class="field" style="margin-top:8px"><label><input type="checkbox" id="efl_active" ${fl.active ? "checked" : ""}/> Đang dùng (hiện trong danh sách chọn khi điều chuyển)</label></div>
        <button class="btn" id="efl_save" style="margin-top:12px">Lưu</button>`);
      $("efl_save").onclick = () => guard(async () => {
        await PUT(`/factory-locations/${fl.factory_id}`, { code: $("efl_code").value.trim(), name: $("efl_name").value.trim(),
          address: $("efl_address").value.trim() || null, contact: $("efl_contact").value.trim() || null,
          active: $("efl_active").checked });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-efldel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa nhà máy này? Không thể hoàn tác.")) return;
      await DELETE(`/factory-locations/${b.dataset.efldel}`);
      toast("Đã xóa nhà máy"); render("master");
    }));
    if ($("ml_add")) $("ml_add").onclick = () => guard(async () => {
      await POST("/warehouse/locations", { code: $("ml_code").value.trim(), name: $("ml_name").value.trim(),
        zone: $("ml_zone").value.trim() || null, scope: $("ml_scope").value });
      toast("Đã tạo vị trí kho"); render("master");
    });
    document.querySelectorAll("[data-eml]").forEach(b => b.onclick = () => {
      const ml = materialLocations.find(x => x.loc_id === b.dataset.eml);
      modal(`<h3>Sửa vị trí kho</h3>
        <div class="field"><label>Mã</label><input id="eml_code" value="${esc(ml.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="eml_name" value="${esc(ml.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>Khu</label><input id="eml_zone" value="${esc(ml.zone || "")}"/></div>
        <div class="field" style="margin-top:8px"><label>Dùng cho</label><select id="eml_scope">${locScopeOptsHtml(ml.scope)}</select></div>
        <div class="field" style="margin-top:8px"><label><input type="checkbox" id="eml_active" ${ml.active ? "checked" : ""}/> Đang dùng (hiện trong danh sách chọn vị trí)</label></div>
        <button class="btn" id="eml_save" style="margin-top:12px">Lưu</button>`);
      $("eml_save").onclick = () => guard(async () => {
        await PUT(`/warehouse/locations/${ml.loc_id}`, { code: $("eml_code").value.trim(), name: $("eml_name").value.trim(),
          zone: $("eml_zone").value.trim() || null, scope: $("eml_scope").value, active: $("eml_active").checked });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-emldel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa vị trí kho này? Không thể hoàn tác.")) return;
      await DELETE(`/warehouse/locations/${b.dataset.emldel}`);
      toast("Đã xóa vị trí kho"); render("master");
    }));
    if ($("mg_add")) $("mg_add").onclick = () => guard(async () => {
      const code = $("mg_code").value.trim(), name = $("mg_name").value.trim();
      if (!code || !name) throw new Error("Nhập đủ Mã nhóm và Tên nhóm.");
      await POST("/material-groups", { code, name, is_packaging: $("mg_packaging").checked,
        is_raw_material: $("mg_rawmat").checked });
      toast("Đã tạo nhóm vật tư"); render("master");
    });
    document.querySelectorAll("[data-emg]").forEach(b => b.onclick = () => {
      const g = materialGroups.find(x => x.group_id === b.dataset.emg);
      modal(`<h3>Sửa nhóm vật tư</h3>
        <div class="field"><label>Mã</label><input id="emg_code" value="${esc(g.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="emg_name" value="${esc(g.name)}"/></div>
        <div class="field" style="margin-top:8px"><label><input type="checkbox" id="emg_active" ${g.active ? "checked" : ""}/> Đang dùng (hiện trong danh sách chọn khi tạo vật tư)</label></div>
        <div class="field" style="margin-top:8px"><label><input type="checkbox" id="emg_packaging" ${g.is_packaging ? "checked" : ""}/> Bao bì tiêu hao (hiện ở báo cáo lô bao bì, tab Bao bì)</label></div>
        <div class="field" style="margin-top:8px"><label><input type="checkbox" id="emg_rawmat" ${g.is_raw_material ? "checked" : ""}/> Nguyên liệu (chính/phụ) — hiện cột "Giá trị CA" khi khai báo chỉ tiêu chất lượng</label></div>
        <button class="btn" id="emg_save" style="margin-top:12px">Lưu</button>`);
      $("emg_save").onclick = () => guard(async () => {
        await PUT(`/material-groups/${g.group_id}`, { code: $("emg_code").value.trim(),
          name: $("emg_name").value.trim(), active: $("emg_active").checked,
          is_packaging: $("emg_packaging").checked, is_raw_material: $("emg_rawmat").checked });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-mgdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa nhóm vật tư này? Không thể hoàn tác.")) return;
      await DELETE(`/material-groups/${b.dataset.mgdel}`);
      toast("Đã xóa nhóm vật tư"); render("master");
    }));
    wireMultiSelectFilter($("mag_members_search"), $("mag_members"));
    const matByIdMag = Object.fromEntries(materials.map(m => [m.material_id, m]));
    const refreshMagUnit = () => {
      const members = [...$("mag_members").selectedOptions].map(o => o.value);
      const opts = groupUnitOptions(matByIdMag, members);
      $("mag_unit").innerHTML = groupUnitSelectHtml(opts, $("mag_unit").value);
    };
    if ($("mag_members")) { $("mag_members").onchange = refreshMagUnit; refreshMagUnit(); }
    if ($("mag_add")) $("mag_add").onclick = () => guard(async () => {
      const code = $("mag_code").value.trim(), name = $("mag_name").value.trim();
      const members = [...$("mag_members").selectedOptions].map(o => o.value);
      const unit = $("mag_unit").value;
      if (!code || !name) throw new Error("Nhập đủ Mã nhóm và Tên nhóm.");
      if (!members.length) throw new Error("Chọn ít nhất 1 vật tư thành viên.");
      if (!unit) throw new Error("Các vật tư thành viên không có đơn vị chung (đơn vị chính hoặc đơn vị phụ) — không thể tạo nhóm. Kiểm tra Đơn vị phụ ở Danh mục Vật tư nếu cần.");
      await POST("/material-alt-groups", { code, name, member_material_ids: members, unit, selection_mode: $("mag_mode").value });
      toast("Đã tạo nhóm vật tư thay thế"); render("master");
    });
    document.querySelectorAll("[data-emag]").forEach(b => b.onclick = () => {
      const g = materialAltGroups.find(x => x.group_id === b.dataset.emag);
      modal(`<h3>Sửa nhóm vật tư thay thế</h3>
        <div class="field"><label>Mã</label><input id="emag_code" value="${esc(g.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="emag_name" value="${esc(g.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>Vật tư thành viên (giữ Ctrl/Cmd để chọn nhiều)</label>
          <input type="text" id="emag_members_search" placeholder="Tìm theo mã/tên vật tư..." style="width:100%;margin-bottom:4px"/>
          <select id="emag_members" multiple size="6" style="width:100%">${materials.map(m => `<option value="${esc(m.material_id)}" ${(g.member_material_ids || []).includes(m.material_id) ? "selected" : ""}>${esc(m.code)} — ${esc(m.name)}</option>`).join("")}</select>
        </div>
        <div class="field" style="margin-top:8px;max-width:260px"><label>Đơn vị nhóm <span class="muted">(mọi thành viên phải khai được đơn vị này)</span></label>
          <select id="emag_unit"></select>
        </div>
        <div class="field" style="margin-top:8px;max-width:340px"><label>Chế độ chọn khi ghi NVL thực tế</label>
          <select id="emag_mode">
            <option value="single" ${g.selection_mode !== "multi" ? "selected" : ""}>Chỉ được chọn 1 mã (mặc định)</option>
            <option value="multi" ${g.selection_mode === "multi" ? "selected" : ""}>Được chọn nhiều mã cùng lúc</option>
          </select>
        </div>
        <div class="field" style="margin-top:8px"><label><input type="checkbox" id="emag_active" ${g.active ? "checked" : ""}/> Đang dùng (hiện trong danh sách chọn khi khai công thức)</label></div>
        <button class="btn" id="emag_save" style="margin-top:12px">Lưu</button>`);
      wireMultiSelectFilter($("emag_members_search"), $("emag_members"));
      const matByIdEmag = Object.fromEntries(materials.map(m => [m.material_id, m]));
      const refreshEmagUnit = () => {
        const members = [...$("emag_members").selectedOptions].map(o => o.value);
        const opts = groupUnitOptions(matByIdEmag, members);
        $("emag_unit").innerHTML = groupUnitSelectHtml(opts, g.unit);
      };
      $("emag_members").onchange = refreshEmagUnit;
      refreshEmagUnit();
      $("emag_save").onclick = () => guard(async () => {
        const members = [...$("emag_members").selectedOptions].map(o => o.value);
        const unit = $("emag_unit").value;
        if (!members.length) throw new Error("Chọn ít nhất 1 vật tư thành viên.");
        if (!unit) throw new Error("Các vật tư thành viên không có đơn vị chung (đơn vị chính hoặc đơn vị phụ) — không thể lưu. Kiểm tra Đơn vị phụ ở Danh mục Vật tư nếu cần.");
        await PUT(`/material-alt-groups/${g.group_id}`, { code: $("emag_code").value.trim(),
          name: $("emag_name").value.trim(), member_material_ids: members, unit, active: $("emag_active").checked,
          selection_mode: $("emag_mode").value });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-magdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa nhóm vật tư thay thế này? Không thể hoàn tác.")) return;
      await DELETE(`/material-alt-groups/${b.dataset.magdel}`);
      toast("Đã xóa nhóm vật tư thay thế"); render("master");
    }));
    if ($("mt_add")) $("mt_add").onclick = () => guard(async () => {
      await POST("/materials", { code: $("mt_code").value.trim(), name: $("mt_name").value.trim(),
        uom: $("mt_uom").value.trim() || "kg", category: $("mt_cat").value,
        stock_min: $("mt_stockmin").value === "" ? null : parseFloat($("mt_stockmin").value),
        alt_uom: $("mt_altuom").value.trim() || null,
        alt_uom_ratio: $("mt_altratio").value === "" ? null : parseFloat($("mt_altratio").value) });
      toast("Đã tạo vật tư"); render("master");
    });
    if ($("ln_line_add")) $("ln_line_add").onclick = () => guard(async () => {
      await POST("/lines", { code: $("ln_line_code").value.trim(), name: $("ln_line_name").value.trim(),
        kind: $("ln_line_kind").value, area: $("ln_line_area").value.trim() || null,
        ideal_rate_per_min: parseFloat($("ln_line_rate").value) || 0,
        capacity_uom: $("ln_line_rate_uom").value.trim() || null,
        identification_code: $("ln_line_idcode").value.trim() || null });
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
        <div class="field" style="margin-top:8px"><label>Đơn vị công suất</label><input id="le_rate_uom" value="${esc(l.capacity_uom || "")}"/></div>
        <div class="field" style="margin-top:8px"><label>Mã nhận dạng</label><input id="le_idcode" value="${esc(l.identification_code || "")}" placeholder="VD: L03"/></div>` : `
        <div class="field" style="margin-top:8px"><label>Thể tích</label><input id="le_vol" type="number" value="${l.volume ?? ""}"/></div>
        <div class="field" style="margin-top:8px"><label>Đơn vị thể tích</label><input id="le_vol_uom" value="${esc(l.volume_uom || "")}"/></div>`}
        <button class="btn" id="le_save" style="margin-top:12px">Lưu</button>`);
      $("le_save").onclick = () => guard(async () => {
        const payload = { name: $("le_name").value.trim(), area: $("le_area").value.trim() || null };
        if (isLine) {
          payload.ideal_rate_per_min = parseFloat($("le_rate").value) || 0;
          payload.capacity_uom = $("le_rate_uom").value.trim() || null;
          payload.identification_code = $("le_idcode").value.trim() || null;
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
        unit_volume_l: $("fp_volumel").value === "" ? null : parseFloat($("fp_volumel").value),
        category: $("fp_cat").value || null, description: $("fp_desc").value.trim() || null,
        weight_primary_kg: $("fp_weightcase").value === "" ? null : parseFloat($("fp_weightcase").value),
        weight_single_kg: $("fp_weightunit").value === "" ? null : parseFloat($("fp_weightunit").value) });
      toast("Đã tạo sản phẩm"); render("master");
    });
    document.querySelectorAll("[data-efp]").forEach(b => b.onclick = () => {
      const fp = finishedProducts.find(x => x.finished_product_id === b.dataset.efp);
      modal(`<h3>Sửa sản phẩm</h3>
        <div class="field"><label>Mã</label><input id="efp_code" value="${esc(fp.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="efp_name" value="${esc(fp.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>ĐVT</label><input id="efp_uom" value="${esc(fp.uom)}"/></div>
        <div class="field" style="margin-top:8px"><label>Loại đơn vị tồn kho</label><select id="efp_unittype">
          ${unitTypes.filter(ut => (ut.selectable && ut.active) || ut.code === fp.unit_type).map(ut =>
            `<option value="${esc(ut.code)}" ${ut.code === fp.unit_type ? "selected" : ""}>${esc(ut.name)}</option>`).join("")}</select></div>
        <div class="field" style="margin-top:8px"><label>SL/1 đơn vị</label><input id="efp_pack" type="number" value="${fp.pack_size}"/></div>
        <div class="field" style="margin-top:8px"><label>Dung tích/1 đơn vị (lít)</label><input id="efp_volumel" type="number" step="0.01" placeholder="VD 0.33" value="${fp.unit_volume_l != null ? fp.unit_volume_l : ""}"/></div>
        <div class="field" style="margin-top:8px"><label>Loại sản phẩm</label><select id="efp_cat"><option value="">(không chọn)</option>${fpCats.map(c => `<option ${c === fp.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></div>
        <div class="field" style="margin-top:8px"><label>Dịch bia gốc</label><select id="efp_product"><option value="">(không chọn)</option>${products.map(p => `<option value="${p.product_id}" ${p.product_id === fp.product_id ? "selected" : ""}>${esc(p.code)}</option>`).join("")}</select></div>
        <div class="field" style="margin-top:8px"><label>Khối lượng/1 đơn vị (vỉ hoặc keg) (kg)</label><input id="efp_weightcase" type="number" step="0.01" value="${fp.weight_primary_kg != null ? fp.weight_primary_kg : ""}"/></div>
        <div class="field" style="margin-top:8px"><label>Khối lượng/1 lon-chai (kg)</label><input id="efp_weightunit" type="number" step="0.01" value="${fp.weight_single_kg != null ? fp.weight_single_kg : ""}"/></div>
        <div class="field" style="margin-top:8px"><label>Mô tả</label><input id="efp_desc" value="${esc(fp.description || "")}"/></div>
        <button class="btn" id="efp_save" style="margin-top:12px">Lưu</button>`);
      $("efp_save").onclick = () => guard(async () => {
        await PUT(`/finished-products/${fp.finished_product_id}`, { code: $("efp_code").value.trim(),
          name: $("efp_name").value.trim(), uom: $("efp_uom").value.trim(),
          product_id: $("efp_product").value || null, unit_type: $("efp_unittype").value,
          pack_size: parseInt($("efp_pack").value, 10) || 24,
          unit_volume_l: $("efp_volumel").value === "" ? null : parseFloat($("efp_volumel").value),
          category: $("efp_cat").value || null, description: $("efp_desc").value.trim() || null,
          weight_primary_kg: $("efp_weightcase").value === "" ? null : parseFloat($("efp_weightcase").value),
          weight_single_kg: $("efp_weightunit").value === "" ? null : parseFloat($("efp_weightunit").value) });
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
        <div class="row" style="margin-top:8px">
          <div class="field"><label>Đơn vị phụ <span class="muted">(tuỳ chọn)</span></label><input id="em_altuom" value="${esc(m.alt_uom || "")}" placeholder="VD: kg" style="width:90px"/></div>
          <div class="field"><label>Tỷ lệ quy đổi <span class="muted">(1 ${esc(m.uom)} = ? đơn vị phụ)</span></label><input id="em_altratio" type="number" step="0.0001" value="${m.alt_uom_ratio ?? ""}" placeholder="VD: 2" style="width:110px"/></div>
        </div>
        <button class="btn" id="em_save" style="margin-top:12px">Lưu</button>`);
      $("em_save").onclick = () => guard(async () => {
        await PUT(`/materials/${m.material_id}`, { code: $("em_code").value.trim(), name: $("em_name").value.trim(),
          uom: $("em_uom").value.trim(), category: $("em_cat").value || null,
          stock_min: $("em_stockmin").value === "" ? null : parseFloat($("em_stockmin").value),
          alt_uom: $("em_altuom").value.trim() || null,
          alt_uom_ratio: $("em_altratio").value === "" ? null : parseFloat($("em_altratio").value) });
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
          <option value="numeric" ${p.value_type !== "pass_fail" && p.value_type !== "text" ? "selected" : ""}>Nhập số (so target/USL/LSL)</option>
          <option value="pass_fail" ${p.value_type === "pass_fail" ? "selected" : ""}>Đạt / Không đạt</option>
          <option value="text" ${p.value_type === "text" ? "selected" : ""}>Nhập text (không so sánh)</option></select></div>
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
    document.querySelectorAll("[data-qpdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa chỉ tiêu này? Chỉ xóa được khi chưa gán vào nhóm chỉ tiêu nào. Không thể hoàn tác.")) return;
      await DELETE(`/qc/parameters/${b.dataset.qpdel}`);
      toast("Đã xóa chỉ tiêu"); render("master");
    }));

    if ($("qg_add")) $("qg_add").onclick = () => guard(async () => {
      const code = $("qg_code").value.trim(), name = $("qg_name").value.trim();
      if (!code || !name) throw new Error("Nhập đủ Mã nhóm và Tên nhóm.");
      await POST("/qc/groups", { code, name, note: $("qg_note").value.trim() || null });
      toast("Đã tạo nhóm chỉ tiêu"); render("master");
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
        const stage = $("sg_stage").value;
        const isProductScoped = PRODUCT_SCOPED_STAGES.includes(stage);
        const isBeerTypeScoped = BEER_TYPE_SCOPED_STAGES.includes(stage);
        $("sg_product_wrap").style.display = isProductScoped ? "" : "none";
        $("sg_beertype_wrap").style.display = isBeerTypeScoped ? "" : "none";
        // Sản phẩm (SKU, tuỳ chọn) có ý nghĩa ở Lọc và Thành phẩm — Lọc khai báo Sản phẩm
        // đích ở Lệnh lọc (kế thừa xuống mẻ lọc, xem FilterOrder.finished_product_id) vì
        // cùng 1 Loại bia vẫn có thể cần chỉ tiêu Lọc khác nhau theo hình thức đóng gói.
        // Stage ngoài cả 2 tập trên (VD "nuoc_nau") ẩn cả Dịch bia lẫn Loại bia — nhóm gán
        // luôn áp dụng chung cho mọi dịch bia/loại bia.
        $("sg_fproduct_wrap").style.display = SKU_SCOPED_STAGES.includes(stage) ? "" : "none";
      };
      $("sg_stage").onchange = toggleSgScope;
      toggleSgScope();
    }
    if ($("sg_add")) $("sg_add").onclick = () => guard(async () => {
      const groupId = $("sg_group").value;
      if (!groupId) throw new Error("Chưa có nhóm chỉ tiêu nào để gán — tạo nhóm ở bảng trên trước.");
      const stage = $("sg_stage").value;
      if (!stage) throw new Error("Chọn công đoạn trước khi gán.");
      const isProductScoped = PRODUCT_SCOPED_STAGES.includes(stage);
      const isBeerTypeScoped = BEER_TYPE_SCOPED_STAGES.includes(stage);
      await POST("/qc/stage-groups", { stage, group_id: groupId,
        product_id: isProductScoped ? ($("sg_product").value || null) : null,
        beer_type_id: isBeerTypeScoped ? ($("sg_beertype").value || null) : null,
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
        const stage = $("sge_stage").value;
        const isProductScoped = PRODUCT_SCOPED_STAGES.includes(stage);
        const isBeerTypeScoped = BEER_TYPE_SCOPED_STAGES.includes(stage);
        $("sge_product_wrap").style.display = isProductScoped ? "" : "none";
        $("sge_beertype_wrap").style.display = isBeerTypeScoped ? "" : "none";
        $("sge_fproduct_wrap").style.display = SKU_SCOPED_STAGES.includes(stage) ? "" : "none";
      };
      $("sge_stage").onchange = toggleSgeScope;
      toggleSgeScope();
      $("sge_save").onclick = () => guard(async () => {
        const groupId = $("sge_group").value;
        if (!groupId) throw new Error("Chưa có nhóm chỉ tiêu nào để gán — tạo nhóm ở bảng trên trước.");
        const stage = $("sge_stage").value;
        const isProductScoped = PRODUCT_SCOPED_STAGES.includes(stage);
        const isBeerTypeScoped = BEER_TYPE_SCOPED_STAGES.includes(stage);
        await PUT(`/qc/stage-groups/${sg.link_id}`, { stage, group_id: groupId,
          product_id: isProductScoped ? ($("sge_product").value || null) : null,
          beer_type_id: isBeerTypeScoped ? ($("sge_beertype").value || null) : null,
          finished_product_id: SKU_SCOPED_STAGES.includes(stage) ? ($("sge_fproduct").value || null) : null,
          mandatory: $("sge_mandatory").checked });
        closeModal(); toast("Đã cập nhật gán nhóm chỉ tiêu"); render("master");
      });
    });
    document.querySelectorAll("[data-sgdel]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa gán nhóm chỉ tiêu này khỏi công đoạn? Không thể hoàn tác.")) return;
      await DELETE(`/qc/stage-groups/${b.dataset.sgdel}`);
      toast("Đã xóa gán"); render("master");
    }));
  }

  // Kho thành phẩm/Vị trí kho/Lái xe — CHỈ ADMIN mới tạo/sửa/xóa (gate riêng isAdminWmsCatalog,
  // khác canManage/master.manage ở trên — xem ghi chú tại khai báo cờ này phía đầu VIEWS.master).
  if (isAdminWmsCatalog) {
    document.querySelectorAll("[data-wh-save]").forEach(b => b.onclick = () => guard(async () => {
      const tr = b.closest("tr");
      await PUT(`/wms/warehouses/${b.dataset.whSave}`, {
        code: tr.querySelector(".wh_code").value,
        name: tr.querySelector(".wh_name").value,
        address: tr.querySelector(".wh_addr").value || null,
        active: tr.querySelector(".wh_active").checked,
        // Gửi "" (không phải null) khi chọn "(Không gắn)" — update_warehouse bỏ qua giá trị
        // None (coi như "không đổi"), nên phải dùng chuỗi rỗng mới XOÁ được gán cũ.
        load_order_sheet_type: tr.querySelector(".wh_lo_sheet").value,
      });
      toast("Đã lưu kho"); render("master");
    }));
    document.querySelectorAll("[data-wh-del]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa kho này? Không thể hoàn tác.")) return;
      await DELETE(`/wms/warehouses/${b.dataset.whDel}`);
      toast("Đã xóa kho"); render("master");
    }));
    if ($("wh_add")) $("wh_add").onclick = () => guard(async () => {
      if (!$("wh_new_code").value || !$("wh_new_name").value) { toast("Nhập mã và tên kho", "err"); return; }
      await POST("/wms/warehouses", { code: $("wh_new_code").value, name: $("wh_new_name").value,
        address: $("wh_new_addr").value || null,
        load_order_sheet_type: $("wh_new_lo_sheet").value || null });
      toast("Đã thêm kho"); render("master");
    });
    document.querySelectorAll("[data-loc-save]").forEach(b => b.onclick = () => guard(async () => {
      const tr = b.closest("tr");
      await PUT(`/wms/locations/${b.dataset.locSave}`, {
        code: tr.querySelector(".wl_code").value,
        name: tr.querySelector(".wl_name").value,
        warehouse_id: tr.querySelector(".wl_wh").value || null,
        zone: tr.querySelector(".wl_zone").value || null,
        kind: tr.querySelector(".wl_kind").value,
        capacity: parseInt(tr.querySelector(".wl_capacity").value) || 1,
        active: tr.querySelector(".wl_active").checked,
      });
      toast("Đã lưu vị trí"); render("master");
    }));
    document.querySelectorAll("[data-loc-del]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa vị trí này? Không thể hoàn tác.")) return;
      await DELETE(`/wms/locations/${b.dataset.locDel}`);
      toast("Đã xóa vị trí"); render("master");
    }));
    document.querySelectorAll("[data-loc-split]").forEach(b => b.onclick = () => guard(async () => {
      const tr = b.closest("tr");
      const code = tr.querySelector(".wl_code") ? tr.querySelector(".wl_code").value : "";
      const raw = prompt(`Chia vị trí ${code} thành mấy ô?`, "4");
      if (raw === null) return;
      const parts = parseInt(raw);
      if (!parts || parts < 2 || parts > 20) { toast("Số ô phải từ 2 đến 20.", "err"); return; }
      if (!confirm(`Chia thành ${parts} ô con — vị trí gốc sẽ ngừng hoạt động, tồn hiện có dồn hết vào Ô1. Tiếp tục?`)) return;
      await POST(`/wms/locations/${b.dataset.locSplit}/split`, { parts });
      toast(`Đã chia thành ${parts} ô — nhớ xếp các ô mới vào Bố cục kho`); render("master");
    }));
    if ($("wl_add")) $("wl_add").onclick = () => guard(async () => {
      if (!$("wl_new_code").value || !$("wl_new_name").value) { toast("Nhập mã và tên vị trí", "err"); return; }
      if (!$("wl_new_wh").value) { toast("Vui lòng chọn kho thành phẩm cho vị trí mới", "err"); return; }
      await POST("/wms/locations", { code: $("wl_new_code").value, name: $("wl_new_name").value,
        warehouse_id: $("wl_new_wh").value || null,
        zone: $("wl_new_zone").value || null, kind: $("wl_new_kind").value,
        capacity: parseInt($("wl_new_capacity").value) || 10 });
      toast("Đã thêm vị trí"); render("master");
    });
    if ($("wlo_wh")) {
      $("wlo_wh").onchange = () => {
        WMS_LAYOUT_WH = $("wlo_wh").value; WMS_LAYOUT_PICK = null;
        WMS_LAYOUT_EXTRA_ROWS = 0; WMS_LAYOUT_EXTRA_COLS = 0; render("master");
      };
      if ($("wlo_addrow")) $("wlo_addrow").onclick = () => { WMS_LAYOUT_EXTRA_ROWS++; render("master"); };
      if ($("wlo_addcol")) $("wlo_addcol").onclick = () => { WMS_LAYOUT_EXTRA_COLS++; render("master"); };
      document.querySelectorAll("[data-layout-pick]").forEach(b => b.onclick = () => {
        WMS_LAYOUT_PICK = b.dataset.layoutPick === WMS_LAYOUT_PICK ? null : b.dataset.layoutPick;
        render("master");
      });
      document.querySelectorAll("[data-layout-unplace]").forEach(b => b.onclick = (e) => guard(async () => {
        e.stopPropagation();
        await PUT(`/wms/locations/${b.dataset.layoutUnplace}/layout`, { row: null, col: null });
        if (WMS_LAYOUT_PICK === b.dataset.layoutUnplace) WMS_LAYOUT_PICK = null;
        toast("Đã gỡ khỏi bố cục"); render("master");
      }));
      document.querySelectorAll("[data-layout-cell]").forEach(td => td.onclick = (e) => guard(async () => {
        if (e.target.closest("[data-layout-unplace]")) return;   // nút Gỡ tự xử lý riêng
        const occupiedLocId = td.dataset.layoutLoc;
        if (occupiedLocId) {
          // Bấm vào ô đã có vị trí (không phải nút Gỡ) → chọn/bỏ chọn để chuẩn bị dời đi nơi khác.
          WMS_LAYOUT_PICK = occupiedLocId === WMS_LAYOUT_PICK ? null : occupiedLocId;
          render("master");
          return;
        }
        if (!WMS_LAYOUT_PICK) { toast("Chọn 1 vị trí ở danh sách bên trên trước", "err"); return; }
        const [row, col] = td.dataset.layoutCell.split(":").map(Number);
        await PUT(`/wms/locations/${WMS_LAYOUT_PICK}/layout`, { row, col });
        WMS_LAYOUT_PICK = null;
        toast("Đã xếp vào bố cục"); render("master");
      }));
    }
    document.querySelectorAll("[data-vehicle-save]").forEach(b => b.onclick = () => guard(async () => {
      const tr = b.closest("tr");
      await PUT(`/wms/vehicles/${b.dataset.vehicleSave}`, {
        plate: tr.querySelector(".vh_plate").value,
        driver_name: tr.querySelector(".vh_driver").value || null,
        driver_short_name: tr.querySelector(".vh_short").value || null,
        capacity_kg: tr.querySelector(".vh_cap").value === "" ? null : parseFloat(tr.querySelector(".vh_cap").value),
        pallet_capacity: tr.querySelector(".vh_pallet").value === "" ? null : parseInt(tr.querySelector(".vh_pallet").value, 10),
        phone: tr.querySelector(".vh_phone").value || null,
        team: tr.querySelector(".vh_team").value || null,
        active: tr.querySelector(".vh_active").checked,
      });
      toast("Đã lưu xe"); render("master");
    }));
    document.querySelectorAll("[data-vehicle-del]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa xe này? Không thể hoàn tác.")) return;
      await DELETE(`/wms/vehicles/${b.dataset.vehicleDel}`);
      toast("Đã xóa xe"); render("master");
    }));
    if ($("vh_add")) $("vh_add").onclick = () => guard(async () => {
      if (!$("vh_new_plate").value) { toast("Nhập biển số", "err"); return; }
      await POST("/wms/vehicles", { plate: $("vh_new_plate").value,
        driver_name: $("vh_new_driver").value || null, driver_short_name: $("vh_new_short").value || null,
        capacity_kg: $("vh_new_cap").value === "" ? null : parseFloat($("vh_new_cap").value),
        pallet_capacity: $("vh_new_pallet").value === "" ? null : parseInt($("vh_new_pallet").value, 10),
        phone: $("vh_new_phone").value || null, team: $("vh_new_team").value || null });
      toast("Đã thêm xe"); render("master");
    });
  }

  // ---- Modal: chỉ tiêu trong 1 nhóm ----
  async function openQcGroupItemsModal(group) {
    const [items, allParams] = await Promise.all([GET(`/qc/groups/${group.group_id}/items`), GET("/qc/parameters?active_only=false")]);
    // Chỉ hiển thị chỉ tiêu NVL do người dùng tự tạo (stage rỗng) — không lẫn chỉ tiêu SPC quy trình sản xuất có sẵn (stage=nau/len_men/loc/chiet).
    const params = allParams.filter(p => !p.stage);
    const paramOpts = params.map(p => `<option value="${esc(p.param_id)}">${esc(p.code)} — ${esc(p.name)}${p.unit ? " (" + esc(p.unit) + ")" : ""}</option>`).join("");
    modal(`<h3>Chỉ tiêu trong nhóm — ${esc(group.name)}</h3>
      ${canManage ? "" : `<div class="muted" style="margin-bottom:8px">Bạn chỉ có quyền xem (cần quyền <code class="k">master.manage</code> để thêm/sửa/xóa chỉ tiêu trong nhóm).</div>`}
      <div class="tablewrap"><table>
        <thead><tr><th>Mã CT</th><th>Tên</th><th>ĐVT</th><th>Min</th><th>Max</th><th>Bắt buộc</th>${canManage ? "<th></th>" : ""}</tr></thead>
        <tbody>${items.map(it => `<tr>
          <td><code class="k">${esc(it.param_code || "—")}</code></td><td>${esc(it.param_name || "—")}</td>
          <td>${esc(it.param_unit || "—")}</td>
          ${canManage ? `<td><input type="number" step="any" class="qgi-lsl-edit" data-item="${esc(it.item_id)}" value="${it.lsl_override ?? ""}" style="width:85px"/></td>
          <td><input type="number" step="any" class="qgi-usl-edit" data-item="${esc(it.item_id)}" value="${it.usl_override ?? ""}" style="width:85px"/></td>
          <td><input type="checkbox" class="qgi-mand-edit" data-item="${esc(it.item_id)}" ${it.mandatory ? "checked" : ""}/></td>
          <td style="white-space:nowrap"><button class="btn sm sec" data-saveitem="${esc(it.item_id)}">Lưu</button>
            <button class="btn sm sec" data-delitem="${esc(it.item_id)}">Xóa</button></td>` : `<td>${it.lsl_override ?? "—"}</td>
          <td>${it.usl_override ?? "—"}</td>
          <td>${it.mandatory ? "Có" : "Không"}</td>`}</tr>`).join("") ||
          `<tr><td colspan="${canManage ? 7 : 6}" class="muted">Chưa có chỉ tiêu nào trong nhóm.</td></tr>`}</tbody>
      </table></div>
      ${canManage ? `<h4 style="margin-top:14px">+ Thêm chỉ tiêu vào nhóm</h4>
      <div class="row">
        <div class="field" style="min-width:220px"><label>Chỉ tiêu</label><select id="qgi_param">${paramOpts || "<option value=''>(chưa có chỉ tiêu nào — tạo ở Danh mục chỉ tiêu chất lượng)</option>"}</select></div>
        <div class="field"><label>Min (LSL)</label><input id="qgi_lsl" type="number" step="any" style="width:90px"/></div>
        <div class="field"><label>Max (USL)</label><input id="qgi_usl" type="number" step="any" style="width:90px"/></div>
        <div class="field"><label>Bắt buộc</label><input id="qgi_mandatory" type="checkbox" checked/></div>
        <button class="btn" id="qgi_add" style="align-self:flex-end">Thêm</button>
      </div>
      <div class="muted" style="margin-top:10px">Chưa thấy chỉ tiêu cần dùng? Tạo mới ở panel "📋 Danh mục chỉ tiêu chất lượng" (phía trên bảng Nhóm chỉ tiêu), rồi quay lại đây để thêm vào nhóm.</div>
      <h4 style="margin-top:14px">↪ Copy chỉ tiêu từ nhóm khác</h4>
      ${items.length ? `<div class="muted">Nhóm này đã có chỉ tiêu — chỉ có thể copy vào nhóm đang rỗng. Xóa hết chỉ tiêu hiện tại (bảng phía trên) nếu muốn copy nguyên bộ từ nhóm khác.</div>` : `<div class="row">
        <div class="field" style="min-width:220px"><label>Nhóm nguồn</label><select id="qgi_copysrc">${
          qcGroups.filter(g => g.group_id !== group.group_id)
            .map(g => `<option value="${esc(g.group_id)}">${esc(g.code)} — ${esc(g.name)}</option>`).join("") ||
          "<option value=''>(không có nhóm nào khác)</option>"}</select></div>
        <button class="btn sec" id="qgi_copy" style="align-self:flex-end">Copy vào nhóm này</button>
      </div>
      <div class="muted" style="margin-top:6px">Copy toàn bộ chỉ tiêu (kèm Min/Max/Bắt buộc) từ nhóm nguồn sang nhóm "${esc(group.name)}".</div>`}` : ""}`);

    if (!canManage) return;
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
    if ($("qgi_copy")) $("qgi_copy").onclick = () => guard(async () => {
      const sourceGroupId = $("qgi_copysrc").value;
      if (!sourceGroupId) throw new Error("Chưa có nhóm nguồn để copy.");
      await POST(`/qc/groups/${group.group_id}/items/copy`, { source_group_id: sourceGroupId });
      toast("Đã copy chỉ tiêu vào nhóm"); openQcGroupItemsModal(group);
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
      if (!confirm("Xóa chỉ tiêu này khỏi nhóm? Không thể hoàn tác.")) return;
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
  const [users, pcat, scat, rtpls] = await Promise.all([
    GET("/auth/users"), GET("/auth/permissions"),
    GET("/auth/scope-catalog").catch(() => ({ areas: [], lines: [], qc_params: [], warehouse_locations: [], wms_warehouses: [] })),
    GET("/auth/role-templates").catch(() => [])]);
  const roleOpts = Object.keys(ROLE_DESC).map(r => `<option value="${r}">${r} — ${ROLE_DESC[r]}</option>`).join("");
  const permBoxesHtml = (cls, checkedSet) => `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:8px 18px">${pcat.catalog.map(p =>
    `<label style="display:flex;align-items:flex-start;gap:6px;font-size:12px;line-height:1.35">
       <input type="checkbox" class="${cls}" value="${p.key}" style="margin-top:3px;flex-shrink:0" ${checkedSet.has(p.key) ? "checked" : ""}/>
       <span>${esc(p.label)}<br><code class="k" style="font-size:11px">${esc(p.key)}</code></span></label>`).join("")}</div>`;
  const scopeFieldsHtml = (prefix, current) => `<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px 20px">
      <div class="field" style="color:var(--text)"><label>Line</label>${scopePickerHtml(`${prefix}_lines`, scat.lines, current ? current.scope_lines : "*")}</div>
      <div class="field" style="color:var(--text)"><label>Khu vực</label>${scopePickerHtml(`${prefix}_areas`, scat.areas, current ? current.scope_areas : "*")}</div>
      <div class="field" style="color:var(--text)"><label>Loại test QC</label>${scopePickerHtml(`${prefix}_qc`, scat.qc_params, current ? current.scope_qc : "*")}</div>
      <div class="field" style="color:var(--text)"><label>Địa điểm kho (NVL)</label>${scopePickerHtml(`${prefix}_wh`, scat.warehouse_locations, current ? current.scope_warehouse : "*")}</div>
      <div class="field" style="color:var(--text)"><label>Kho thành phẩm (WMS)</label>${scopePickerHtml(`${prefix}_wmswh`, scat.wms_warehouses, current ? current.wms_warehouse_scope : "*")}
        <div class="muted" style="font-size:11px">Chặn Xuất kho/Điều chuyển/Nhập kho/Cất vào vị trí ngoài kho được chọn — khác "Địa điểm kho" (chỉ áp dụng kho NVL công ty/phân xưởng)</div></div>
    </div>`;
  const wireScopeFields = (prefix) => ["lines", "areas", "qc", "wh", "wmswh"].forEach(d => wireScopePicker(`${prefix}_${d}`));
  const readScopeFields = (prefix) => ({
    scope_lines: readScopePicker(`${prefix}_lines`), scope_areas: readScopePicker(`${prefix}_areas`),
    scope_qc: readScopePicker(`${prefix}_qc`), scope_warehouse: readScopePicker(`${prefix}_wh`),
    wms_warehouse_scope: readScopePicker(`${prefix}_wmswh`) });
  $("view-users").innerHTML = `
    <div class="panel"><h2>Tạo tài khoản</h2>
      <div class="field"><label>Áp dụng mẫu chức danh (tuỳ chọn)</label>
        <select id="nu_tpl"><option value="">— Không áp dụng —</option>${rtpls.map(t => `<option value="${esc(t.role_template_id)}">${esc(t.name)}</option>`).join("")}</select>
        <div class="muted" style="font-size:11px">Chọn để tự điền vai trò/menu/quyền/phạm vi — vẫn có thể sửa lại bên dưới trước khi tạo.</div></div>
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
      ${scopeFieldsHtml("nu", null)}
      <h3>Quyền thao tác (ma trận quyền)</h3>
      <div style="background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:10px;max-height:220px;overflow-y:auto">${permBoxesHtml("nu_perm", new Set())}</div>
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
        <td style="white-space:nowrap"><button class="btn sm sec" data-editperm="${esc(u.username)}">Sửa quyền</button>
          <button class="btn sm sec" data-scope="${esc(u.username)}">Phạm vi</button>
          <button class="btn sm sec" data-copyperm="${esc(u.username)}">Copy quyền</button>
          ${u.username !== CURRENT_USER.username ? `<button class="btn sm sec" data-toggle="${esc(u.username)}">${u.active ? "Khoá" : "Mở"}</button>` : ""}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="panel"><h2>Mẫu chức danh</h2>
      <div class="muted" style="margin-bottom:8px">Khai báo tên chức danh gắn với 1 vai trò hệ thống + menu/quyền/phạm vi mặc định, để chọn nhanh khi tạo tài khoản mới thay vì soạn tay từng trường.</div>
      <div class="tablewrap"><table id="t_rtpl"><thead><tr><th>Tên chức danh</th><th>Vai trò</th><th>Menu</th><th>Quyền</th><th></th></tr></thead>
      <tbody>${rtpls.map(t => `<tr><td>${esc(t.name)}</td>
        <td>${badge(t.role === "admin" ? "critical" : "available")}${esc(t.role)}</td>
        <td style="font-size:12px">${esc(t.allowed_views)}</td>
        <td style="font-size:12px">${t.permissions === "*" ? '<span class="badge critical">toàn quyền</span>' : (t.permissions ? t.permissions.split(",").map(p => `<span class="badge planned" style="margin:1px">${esc(p)}</span>`).join(" ") : '<span class="muted">chỉ xem</span>')}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-rtpl-edit="${esc(t.role_template_id)}">Sửa</button>
          <button class="btn sm sec" data-rtpl-del="${esc(t.role_template_id)}">Xóa</button></td></tr>`).join("") || `<tr><td colspan="5" class="muted">Chưa có mẫu chức danh nào.</td></tr>`}</tbody></table></div>
      <h3 style="margin-top:14px">Thêm mẫu chức danh mới</h3>
      <div class="row">
        <div class="field"><label>Tên chức danh</label><input id="rt_name" placeholder="VD: Trưởng ca trực"/></div>
        <div class="field"><label>Vai trò hệ thống</label><select id="rt_role">${roleOpts}</select></div>
      </div>
      <div class="field"><label>Menu được phép (cách nhau dấu phẩy, hoặc * = tất cả)</label>
        <input id="rt_views" value="dashboard" style="width:100%"/></div>
      <h4 style="margin-top:10px">Phạm vi dữ liệu mặc định</h4>
      ${scopeFieldsHtml("rt", null)}
      <h4 style="margin-top:10px">Quyền thao tác mặc định</h4>
      <div style="background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:10px;max-height:220px;overflow-y:auto">${permBoxesHtml("rt_perm", new Set())}</div>
      <button class="btn" id="rt_add" style="margin-top:12px">Thêm mẫu chức danh</button>
    </div>`;
  wireSearch(); wirePaginate("t_users", 10); wirePaginate("t_rtpl", 10);
  wireScopeFields("nu"); wireScopeFields("rt");
  $("nu_tpl").onchange = () => {
    const t = rtpls.find(x => x.role_template_id === $("nu_tpl").value);
    if (!t) return;
    $("nu_role").value = t.role; $("nu_views").value = t.allowed_views;
    if (!$("nu_title").value) $("nu_title").value = t.name;
    const permSet = t.permissions === "*" ? new Set() : new Set((t.permissions || "").split(",").filter(Boolean));
    document.querySelectorAll(".nu_perm").forEach(c => c.checked = permSet.has(c.value));
    setScopePicker("nu_lines", t.scope_lines); setScopePicker("nu_areas", t.scope_areas);
    setScopePicker("nu_qc", t.scope_qc); setScopePicker("nu_wh", t.scope_warehouse);
    setScopePicker("nu_wmswh", t.wms_warehouse_scope);
  };
  $("nu_add").onclick = () => guard(async () => {
    const weak = passwordPolicyMsg($("nu_pass").value, $("nu_user").value);
    if (weak) { toast(weak, "err"); return; }
    const perms = [...document.querySelectorAll(".nu_perm:checked")].map(c => c.value).join(",");
    await POST("/auth/users", { username: $("nu_user").value, password: $("nu_pass").value,
      full_name: $("nu_name").value, job_title: $("nu_title").value, role: $("nu_role").value,
      allowed_views: $("nu_views").value, permissions: perms, ...readScopeFields("nu") });
    toast("Đã tạo tài khoản"); render("users");
  });
  document.querySelectorAll("[data-toggle]").forEach(b => b.onclick = () => guard(async () => {
    await POST(`/auth/users/${b.dataset.toggle}/toggle`); toast("Đã đổi trạng thái"); render("users");
  }));
  document.querySelectorAll("[data-scope]").forEach(b => b.onclick = () => {
    const u = users.find(x => x.username === b.dataset.scope);
    modal(`<h3>Phạm vi dữ liệu: ${esc(u.username)}</h3>
      <div class="muted" style="margin-bottom:8px">Tích "Toàn bộ" = không giới hạn (toàn nhà máy), hoặc tích chọn cụ thể để giới hạn phạm vi.</div>
      ${scopeFieldsHtml("sc", u)}
      <button class="btn" id="sc_save" style="margin-top:12px">Lưu phạm vi</button>`);
    wireScopeFields("sc");
    $("sc_save").onclick = () => guard(async () => {
      await PUT(`/auth/users/${u.username}/scope`, readScopeFields("sc"));
      closeModal(); toast("Đã cập nhật phạm vi"); render("users");
    });
  });
  document.querySelectorAll("[data-editperm]").forEach(b => b.onclick = () => {
    const u = users.find(x => x.username === b.dataset.editperm);
    const curPerms = new Set(u.permissions === "*" ? [] : (u.permissions ? u.permissions.split(",") : []));
    modal(`<h3>Sửa quyền: ${esc(u.username)}</h3>
      <div class="muted" style="margin-bottom:8px">Sửa trực tiếp vai trò, menu và tick/bỏ tick từng quyền thao tác cho tài khoản này. Mật khẩu, trạng thái khoá/mở và phạm vi dữ liệu (line/khu vực/QC/kho) không đổi ở đây.</div>
      <div class="row">
        <div class="field"><label>Họ tên</label><input id="ep_name" value="${esc(u.full_name)}"/></div>
        <div class="field"><label>Chức danh</label><input id="ep_title" value="${esc(u.job_title)}"/></div>
        <div class="field"><label>Vai trò</label><select id="ep_role">${Object.keys(ROLE_DESC).map(r => `<option value="${r}" ${r === u.role ? "selected" : ""}>${r} — ${ROLE_DESC[r]}</option>`).join("")}</select></div>
      </div>
      <div class="field"><label>Menu được phép (cách nhau dấu phẩy, hoặc * = tất cả)</label>
        <input id="ep_views" value="${esc(u.allowed_views)}" style="width:100%"/></div>
      <h3 style="margin-top:14px">Quyền thao tác (ma trận quyền)</h3>
      ${u.permissions === "*" ? '<div class="muted" style="margin-bottom:6px">Tài khoản đang có <span class="badge critical">toàn quyền (*)</span> — tick quyền bên dưới sẽ CHUYỂN sang danh sách quyền cụ thể thay vì *.</div>' : ""}
      <div style="background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:10px;max-height:220px;overflow-y:auto">${permBoxesHtml("ep_perm", curPerms)}</div>
      <button class="btn" id="ep_save" style="margin-top:12px">Lưu quyền</button>`);
    $("ep_save").onclick = () => guard(async () => {
      const perms = [...document.querySelectorAll(".ep_perm:checked")].map(c => c.value).join(",");
      await PUT(`/auth/users/${u.username}`, {
        full_name: $("ep_name").value, job_title: $("ep_title").value,
        role: $("ep_role").value, allowed_views: $("ep_views").value, permissions: perms });
      closeModal(); toast("Đã cập nhật quyền"); render("users");
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
  $("rt_add").onclick = () => guard(async () => {
    if (!$("rt_name").value.trim()) { toast("Nhập tên chức danh", "err"); return; }
    const perms = [...document.querySelectorAll(".rt_perm:checked")].map(c => c.value).join(",");
    await POST("/auth/role-templates", { name: $("rt_name").value, role: $("rt_role").value,
      allowed_views: $("rt_views").value, permissions: perms, ...readScopeFields("rt") });
    toast("Đã thêm mẫu chức danh"); render("users");
  });
  document.querySelectorAll("[data-rtpl-del]").forEach(b => b.onclick = () => guard(async () => {
    if (!confirm("Xóa mẫu chức danh này? Không ảnh hưởng tài khoản đã tạo trước đó.")) return;
    await api(`/auth/role-templates/${b.dataset.rtplDel}`, { method: "DELETE" });
    toast("Đã xóa mẫu chức danh"); render("users");
  }));
  document.querySelectorAll("[data-rtpl-edit]").forEach(b => b.onclick = () => {
    const t = rtpls.find(x => x.role_template_id === b.dataset.rtplEdit);
    const curPerms = new Set(t.permissions === "*" ? [] : (t.permissions ? t.permissions.split(",") : []));
    modal(`<h3>Sửa mẫu chức danh: ${esc(t.name)}</h3>
      <div class="field"><label>Tên chức danh</label><input id="rte_name" value="${esc(t.name)}"/></div>
      <div class="field" style="margin-top:8px"><label>Vai trò hệ thống</label><select id="rte_role">${Object.keys(ROLE_DESC).map(r => `<option value="${r}" ${r === t.role ? "selected" : ""}>${r} — ${ROLE_DESC[r]}</option>`).join("")}</select></div>
      <div class="field" style="margin-top:8px"><label>Menu được phép</label><input id="rte_views" value="${esc(t.allowed_views)}" style="width:100%"/></div>
      <h4 style="margin-top:12px">Phạm vi dữ liệu mặc định</h4>
      ${scopeFieldsHtml("rte", t)}
      <h4 style="margin-top:12px">Quyền thao tác mặc định</h4>
      <div style="background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:10px;max-height:220px;overflow-y:auto">${permBoxesHtml("rte_perm", curPerms)}</div>
      <button class="btn" id="rte_save" style="margin-top:12px">Lưu mẫu chức danh</button>`);
    wireScopeFields("rte");
    $("rte_save").onclick = () => guard(async () => {
      const perms = [...document.querySelectorAll(".rte_perm:checked")].map(c => c.value).join(",");
      await PUT(`/auth/role-templates/${t.role_template_id}`, {
        name: $("rte_name").value, role: $("rte_role").value, allowed_views: $("rte_views").value,
        permissions: perms, ...readScopeFields("rte") });
      closeModal(); toast("Đã cập nhật mẫu chức danh"); render("users");
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
  document.querySelectorAll("#nav button[data-view]").forEach(b => {
    const ok = !allowed || allowed.has(b.dataset.view) || b.dataset.view === "profile" || b.dataset.view === "flowmap";
    b.style.display = ok ? "" : "none";
    if (ok && b.dataset.view !== "profile" && !first) first = b;
  });
  // Ẩn hẳn tiêu đề 1 trong 5 nhóm domain nếu không còn view nào bên trong được phép xem.
  document.querySelectorAll("#nav .nav-topgroup").forEach(g => {
    const box = $("nav-group-" + g.dataset.navgrp);
    const anyVisible = !!box && Array.from(box.querySelectorAll("button[data-view]")).some(x => x.style.display !== "none");
    g.style.display = anyVisible ? "" : "none";
    if (!anyVisible) box.classList.remove("open");
  });
  $("u_name").textContent = CURRENT_USER.full_name;
  $("u_title").textContent = CURRENT_USER.job_title + " · " + CURRENT_USER.role;
  // chọn tab đầu tiên được phép
  document.querySelectorAll("#nav button").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".view").forEach(x => x.classList.remove("active"));
  if (first) {
    first.classList.add("active");
    $("view-" + first.dataset.view).classList.add("active");
    openNavGroup(GROUP_OF_VIEW[first.dataset.view]);
    $("nav-master-groups").classList.toggle("open", first.dataset.view === "master");
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
  // Máy dùng chung tại xưởng/kho — người dùng kế tiếp đăng nhập KHÔNG được thấy/kế thừa dữ
  // liệu của người trước: giỏ hàng yêu cầu xuất kho đang soạn dở (có thể vô tình bị gửi đi dưới
  // danh tính người mới), và các cờ "điều hướng 1 lần" từ Dashboard (mở thẳng CAPA/Deviation/
  // Hold-Release theo scope đã chọn) — nếu còn sót sẽ tự mở nhầm màn cho người dùng kế tiếp.
  REQUEST_CART = []; REQUEST_SOURCE = null;
  PENDING_QUALITY_SCOPE = null; PENDING_CAPA_DEVIATION = null;
  PENDING_OPEN_CAPA_ID = null; PENDING_OPEN_DEVIATION_ID = null;
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
