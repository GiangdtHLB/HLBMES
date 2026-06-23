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

// ---------- utils ----------
const $ = (id) => document.getElementById(id);
const el = (html) => { const d = document.createElement("div"); d.innerHTML = html.trim(); return d.firstChild; };
const badge = (s) => `<span class="badge ${s}">${s}</span>`;
const scopeBadge = (raw) => (raw === "*" || raw == null || raw === "")
  ? '<span class="badge available">Toàn nhà máy</span>'
  : String(raw).split(",").map(s => `<span class="badge planned" style="margin:2px">${esc(s.trim())}</span>`).join(" ");
const fmt = (t) => t ? new Date(t).toLocaleString("vi-VN") : "—";
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));
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
  const bg = el(`<div class="modal-bg" id="modalbg"><div class="modal">${html}</div></div>`);
  bg.onclick = (e) => { if (e.target === bg) closeModal(); };
  document.body.appendChild(bg);
}
function closeModal() { const m = $("modalbg"); if (m) m.remove(); }

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
  guard(VIEWS[view]);
}

// ================= DASHBOARD =================
VIEWS.dashboard = async function () {
  const safe = async (p) => { try { return await GET(p); } catch (e) { return null; } };
  const [orders, batches, devs, lots, audit, oee, energy, norm, stock, ins, woBoard] = await Promise.all([
    GET("/orders"), GET("/batches"), GET("/quality/deviations"), GET("/lots"),
    GET("/audit?limit=10"), GET("/oee"),
    safe("/energy/monthly"), safe("/reports/material-norm"), safe("/warehouse/stock"),
    safe("/ai/insights"), safe("/workorders"),
  ]);
  const fvTag = "brewery/site01/fermentation/FV07/temperature";
  const fvSeries = await safe("/historian/series?tag=" + encodeURIComponent(fvTag) + "&hours=6&buckets=40");

  const byState = {};
  batches.forEach(b => byState[b.state] = (byState[b.state] || 0) + 1);
  const onHold = lots.filter(l => l.status === "on_hold").length
              + batches.filter(b => b.quality_status === "on_hold").length;
  const openDev = devs.filter(d => d.state !== "closed").length;
  const woActive = (woBoard || []).filter(w => ["released", "in_progress"].includes(w.status)).length;

  const stateColors = { planned: "#8aa0b2", ready: "#3498db", running: "#2ecc71",
    held: "#e67e22", completed: "#17a2b8", closed: "#1c5a7a", cancelled: "#e74c3c" };
  const statePie = Object.keys(byState).map(s => ({ label: s, value: byState[s], color: stateColors[s] }));

  // OEE donuts (giữ)
  const byLine = {};
  oee.forEach(r => { if (!byLine[r.line]) byLine[r.line] = r; });
  const oeeCards = Object.values(byLine).map(r => `
    <div class="panel" style="text-align:center">
      <h2>${esc(r.line)} · ca ${esc(r.shift)}</h2>${CH.donut(r.oee, { label: "OEE" })}
      <div style="margin-top:10px">${CH.hbars([
        { label: "Khả dụng (A)", value: r.availability, pct: true, color: "#3498db" },
        { label: "Hiệu suất (P)", value: r.performance, pct: true, color: "#f5a623" },
        { label: "Chất lượng (Q)", value: r.quality, pct: true, color: "#2ecc71" }])}</div>
      <div class="muted" style="margin-top:8px;font-size:12px">${r.good_count.toLocaleString("vi-VN")}/${r.total_count.toLocaleString("vi-VN")} đạt · dừng ${r.downtime_min}'</div>
    </div>`).join("");

  // Năng lượng Điện theo tháng
  const elec = (energy || []).filter(e => (e.group || "").toLowerCase().includes("điện"))
    .map(e => ({ label: e.month.slice(5), value: Math.round(e.value) }));
  // Sản lượng đóng gói theo ca (OEE good_count)
  const prod = oee.map(r => ({ label: r.line.split(" ")[0] + "/" + r.shift, value: r.good_count,
    color: r.oee >= 0.85 ? "#2ecc71" : r.oee >= 0.65 ? "#f5a623" : "#e74c3c" }));
  // Định mức vs thực tế NVL
  const normItems = (norm && norm.materials || []).map(m => ({ label: m.material_code, a: m.planned, b: m.actual }));
  // Cơ cấu tồn kho
  const stockPie = (stock || []).map(s => ({ label: s.material_code, value: Math.round(s.on_hand) }));
  // Cảnh báo theo mức
  const insSum = (ins && ins.summary) || { high: 0, medium: 0, low: 0 };
  const insBars = [{ label: "Cao", value: insSum.high, color: "#e74c3c" },
                   { label: "TB", value: insSum.medium, color: "#f5a623" },
                   { label: "Thấp", value: insSum.low, color: "#2ecc71" }];
  const fvPts = (fvSeries && fvSeries.points || []).map(p => ({ ts: p.ts, value: p.value }));

  const chartPanel = (title, body) => `<div class="panel"><h2>${title}</h2>${body}</div>`;

  $("view-dashboard").innerHTML = `
    <div class="cards">
      <div class="card"><div class="n">${orders.length}</div><div class="l">Lệnh ERP</div></div>
      <div class="card"><div class="n">${woActive}</div><div class="l">WO đang chạy/chờ</div></div>
      <div class="card"><div class="n">${byState.running || 0}</div><div class="l">Mẻ đang chạy</div></div>
      <div class="card"><div class="n" style="color:${onHold ? 'var(--orange)' : 'var(--green)'}">${onHold}</div><div class="l">Đang HOLD</div></div>
      <div class="card"><div class="n" style="color:${openDev ? 'var(--red)' : 'var(--green)'}">${openDev}</div><div class="l">Deviation mở</div></div>
      <div class="card"><div class="n" style="color:${insSum.high ? 'var(--red)' : 'var(--green)'}">${insSum.high}</div><div class="l">Cảnh báo cao</div></div>
    </div>
    <h3 style="color:var(--muted);text-transform:uppercase;letter-spacing:.5px;font-size:12px;margin:4px 2px 10px">OEE đóng gói (ca gần nhất)</h3>
    <div class="cards">${oeeCards || '<div class="panel muted">Chưa có dữ liệu OEE.</div>'}</div>
    <div class="split">
      ${chartPanel("🍺 Nhiệt độ lên men FV07 (6h, realtime)", CH.line(fvPts, { color: "#e74c3c", unit: "°C", label: "FV07", height: 150 }))}
      ${chartPanel("⚡ Điện tiêu thụ theo tháng", CH.vbars(elec, { unit: "kWh", color: "#f5a623" }))}
    </div>
    <div class="split">
      ${chartPanel("📦 Phân bố trạng thái mẻ", CH.pie(statePie))}
      ${chartPanel("🏭 Sản lượng đóng gói theo ca", CH.vbars(prod, { unit: "đv" }))}
    </div>
    <div class="split">
      ${chartPanel("📋 Định mức ↔ Thực tế NVL", CH.grouped(normItems, { labelA: "Định mức", labelB: "Thực tế" }))}
      ${chartPanel("🗄️ Cơ cấu tồn kho", CH.pie(stockPie))}
    </div>
    <div class="split">
      ${chartPanel("🚨 Cảnh báo vận hành (AI)", CH.vbars(insBars, { unit: "" }))}
      <div class="panel"><h2>Audit gần đây</h2>${tableAudit(audit)}</div>
    </div>
    <div class="panel"><h2>Mẻ gần đây</h2>${tableBatches(batches.slice(0, 8))}</div>`;
};

// ================= ORDERS =================
VIEWS.orders = async function () {
  const [orders, products] = await Promise.all([GET("/orders"), GET("/products")]);
  CACHE.products = products;
  const opts = products.map(p => `<option value="${p.product_id}">${esc(p.code)} — ${esc(p.name)}</option>`).join("");
  $("view-orders").innerHTML = `
    <div class="panel">
      <h2>Tạo lệnh sản xuất</h2>
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
      <table><thead><tr><th>Mã</th><th>Sản phẩm</th><th>SL</th><th>Ưu tiên</th><th>Trạng thái</th><th>Tạo lúc</th></tr></thead>
      <tbody>${orders.map(o => `<tr><td><code class="k">${esc(o.order_code)}</code></td>
        <td>${esc(prodName(o.product_id))}</td><td>${o.planned_qty} ${o.uom}</td>
        <td>${o.priority}</td><td>${badge(o.status)}</td><td class="muted">${fmt(o.created_at)}</td></tr>`).join("")}</tbody></table>
    </div>`;
  $("o_save").onclick = () => guard(async () => {
    await POST("/orders", { order_code: $("o_code").value, product_id: $("o_prod").value,
      planned_qty: parseFloat($("o_qty").value), uom: $("o_uom").value, priority: parseInt($("o_pri").value) });
    toast("Đã tạo lệnh sản xuất"); render("orders");
  });
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
  const today = new Date().toISOString().slice(0, 10);
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
      <div class="tablewrap"><table><thead><tr><th>Mã WO</th><th>Ngày</th><th>Ca</th><th>Line</th><th>Sản phẩm</th><th>KH</th><th>Thực tế</th><th>% HT</th><th>Mẻ</th><th>Ưu tiên</th><th>Trạng thái</th><th>Hành động</th></tr></thead>
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
  return (CACHE.materials || []).map(m =>
    `<option value="${esc(m.code)}" data-uom="${esc(m.uom)}" ${m.code === sel ? "selected" : ""}>${esc(m.code)} — ${esc(m.name)}</option>`).join("");
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
    <div class="row" style="margin-top:12px">
      <button class="btn" id="vf_save">${v.version_id ? "Lưu version" : "Tạo version (draft)"}</button>
      <button class="btn sec" id="vf_cancel">Hủy</button>
    </div></div>`;
}
function newVersionForm(recipeId) {
  $("rv_detail").innerHTML = versionFormHTML(null);
  wireBomEditor();
  $("vf_cancel").onclick = () => { $("rv_detail").innerHTML = ""; };
  $("vf_save").onclick = () => guard(async () => {
    await POST(`/recipes/${recipeId}/versions`, _versionPayload());
    toast("Đã tạo version + BOM (draft)"); render("recipes");
  });
}
function editVersionForm(v) {
  $("rv_detail").innerHTML = versionFormHTML(v);
  wireBomEditor();
  $("vf_cancel").onclick = () => showVersion(v.version_id);
  $("vf_save").onclick = () => guard(async () => {
    await PUT(`/recipes/versions/${v.version_id}`, _versionPayload());
    toast("Đã lưu version + BOM"); render("recipes");
  });
}
function _versionPayload() {
  return {
    base_qty: parseFloat($("vf_base").value) || 0,
    base_uom: $("vf_baseu").value,
    materials: collectBom(),
    parameters: JSON.parse($("vf_params").value || "[]"),
    quality_checks: JSON.parse($("vf_qc").value || "[]"),
  };
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
  modal(`<span class="close" id="ebr_close">✕</span>
    <h2>📄 Hồ sơ mẻ điện tử (EBR) — ${esc(c.batch_code)} ${lockBadge}</h2>
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
  $("ebr_close").onclick = closeModal;
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
  const [results, devs, batches, lots] = await Promise.all([
    GET("/quality/results"), GET("/quality/deviations"), GET("/batches"), GET("/lots")]);
  const scopeOpts = batches.map(b => `<option value="batch:${b.batch_id}">mẻ ${esc(b.batch_code)}</option>`).join("")
    + lots.map(l => `<option value="lot:${l.lot_id}">lô ${esc(l.lot_code)}</option>`).join("");
  $("view-quality").innerHTML = `
    <div class="split">
      <div class="panel"><h2>Ghi kết quả QC</h2>
        <div class="row">
          <div class="field"><label>Phạm vi</label><select id="q_scope">${scopeOpts}</select></div>
          <div class="field"><label>Tham số</label><input id="q_param" placeholder="pH" /></div>
        </div>
        <div class="row">
          <div class="field"><label>Giá trị</label><input id="q_val" type="number" /></div>
          <div class="field"><label>ĐVT</label><input id="q_unit" size="5" /></div>
          <div class="field"><label>Lower</label><input id="q_lo" type="number" /></div>
          <div class="field"><label>Upper</label><input id="q_hi" type="number" /></div>
          <button class="btn" id="q_save">Ghi KQ</button>
        </div>
        <div class="muted">Pass/Fail tính tự động theo limit. FAIL tự đưa scope về ON HOLD.</div>
      </div>
      <div class="panel"><h2>Hold / Release</h2>
        <div class="row">
          <div class="field"><label>Phạm vi</label><select id="h_scope">${scopeOpts}</select></div>
          <button class="btn sec" id="h_hold">HOLD (qa/supervisor)</button>
          <button class="btn" id="h_rel">RELEASE (qa)</button>
        </div>
        <div class="muted">Release bị chặn nếu còn FAIL chưa đóng deviation.</div>
        <h3>Mở deviation</h3>
        <div class="row">
          <div class="field"><label>Phạm vi</label><select id="d_scope">${scopeOpts}</select></div>
          <div class="field"><label>Mức</label><select id="d_sev"><option>minor</option><option>major</option><option>critical</option></select></div>
          <div class="field"><label>Lý do</label><input id="d_reason" /></div>
          <button class="btn sec" id="d_open">Mở</button>
        </div>
      </div>
    </div>
    <div class="panel"><h2>Kết quả QC gần đây</h2>
      <table><thead><tr><th>Tham số</th><th>Giá trị</th><th>Giới hạn</th><th>KQ</th><th>Người ghi</th><th>Lúc</th></tr></thead>
      <tbody>${results.map(r => `<tr><td>${esc(r.parameter)}</td><td>${r.value ?? "—"} ${esc(r.unit || "")}</td>
        <td class="muted">${r.lower_limit ?? "−∞"} … ${r.upper_limit ?? "+∞"}</td><td>${badge(r.status)}</td>
        <td class="muted">${esc(r.recorded_by || "")}</td><td class="muted">${fmt(r.recorded_at)}</td></tr>`).join("")}</tbody></table></div>
    <div class="panel"><h2>Deviations</h2>
      <table><thead><tr><th>Mã</th><th>Mức</th><th>Lý do</th><th>Trạng thái</th><th>Hành động</th></tr></thead>
      <tbody>${devs.map(devRow).join("") || '<tr><td colspan=5 class="muted">Chưa có</td></tr>'}</tbody></table></div>`;
  const parseScope = (v) => { const [t, i] = v.split(":"); return { scope_type: t, scope_id: i }; };
  $("q_save").onclick = () => guard(async () => {
    await POST("/quality/results", { ...parseScope($("q_scope").value), parameter: $("q_param").value,
      value: $("q_val").value === "" ? null : parseFloat($("q_val").value), unit: $("q_unit").value,
      lower_limit: $("q_lo").value === "" ? null : parseFloat($("q_lo").value),
      upper_limit: $("q_hi").value === "" ? null : parseFloat($("q_hi").value) });
    toast("Đã ghi kết quả QC"); render("quality");
  });
  $("h_hold").onclick = () => guard(async () => { await POST("/quality/hold", { ...parseScope($("h_scope").value), on_hold: true }); toast("Đã HOLD"); render("quality"); });
  $("h_rel").onclick = () => guard(async () => { await POST("/quality/hold", { ...parseScope($("h_scope").value), on_hold: false }); toast("Đã RELEASE"); render("quality"); });
  $("d_open").onclick = () => guard(async () => {
    await POST("/quality/deviations", { ...parseScope($("d_scope").value), severity: $("d_sev").value, reason: $("d_reason").value });
    toast("Đã mở deviation"); render("quality");
  });
  document.querySelectorAll("[data-dt]").forEach(b => b.onclick = () => guard(async () => {
    await POST(`/quality/deviations/${b.dataset.did}/transition`, { target: b.dataset.dt });
    toast("Deviation → " + b.dataset.dt); render("quality");
  }));
};
function devRow(d) {
  const next = { open: ["triage"], triage: ["investigation"], investigation: ["disposition"],
    disposition: ["approval"], approval: ["closed"], closed: [] }[d.state] || [];
  const btns = next.map(n => `<button class="btn sm sec" data-dt="${n}" data-did="${d.deviation_id}">→ ${n}</button>`).join(" ");
  return `<tr><td><code class="k">${esc(d.deviation_code)}</code></td><td>${badge(d.severity)}</td>
    <td>${esc(d.reason)}</td><td>${badge(d.state)}</td><td>${btns || "—"}</td></tr>`;
}

// ================= TRACEABILITY =================
VIEWS.trace = async function () {
  $("view-trace").innerHTML = `
    <div class="panel"><h2>Truy xuất nguồn gốc & Recall</h2>
      <div class="row">
        <div class="field"><label>Mã lô / mã mẻ</label><input id="t_code" placeholder="PKG-2406-0001" /></div>
        <button class="btn" id="t_back">Truy ngược ↑</button>
        <button class="btn sec" id="t_fwd">Truy xuôi ↓</button>
        <button class="btn sec" id="t_recall">Recall simulation</button>
      </div>
      <div class="muted">Truy ngược: thành phẩm → nguyên liệu. Truy xuôi/Recall: nguyên liệu → các lô bị ảnh hưởng.</div>
    </div>
    <div class="panel" id="t_out"><div class="muted">Nhập mã và chọn hướng truy xuất.</div></div>`;
  const code = () => $("t_code").value.trim();
  $("t_back").onclick = () => guard(async () => renderTree(await GET("/trace/backward?code=" + encodeURIComponent(code())), "Truy ngược"));
  $("t_fwd").onclick = () => guard(async () => renderTree(await GET("/trace/forward?code=" + encodeURIComponent(code())), "Truy xuôi"));
  $("t_recall").onclick = () => guard(async () => {
    const r = await GET("/trace/recall?code=" + encodeURIComponent(code()));
    $("t_out").innerHTML = `<h2>Recall: ${r.affected_count} lô/mẻ bị ảnh hưởng <span class="muted">(${r.elapsed_ms} ms)</span></h2>
      <table><thead><tr><th>Loại</th><th>Mã</th></tr></thead><tbody>${r.affected.map(a => `<tr><td>${a.type}</td><td><code class="k">${esc(a.code)}</code></td></tr>`).join("")}</tbody></table>`;
  });
};
function renderTree(tree, title) {
  const node = (n) => `<div class="node">${n.type === "batch" ? "🍺" : "📦"} <code class="k">${esc(n.code)}</code>
    ${n.relation ? `<span class="rel">[${n.relation}${n.quantity ? " " + n.quantity + (n.uom || "") : ""}]</span>` : ""}
    ${(n.children || []).map(node).join("")}</div>`;
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
      <div id="au_table"></div>
    </div>`;
  const load = () => guard(async () => {
    const q = $("au_entity").value ? "?entity_id=" + encodeURIComponent($("au_entity").value) : "?limit=200";
    $("au_table").innerHTML = tableAudit(await GET("/audit" + q));
  });
  $("au_load").onclick = load; load();
};
function tableAudit(rows) {
  return `<table><thead><tr><th>#</th><th>Đối tượng</th><th>Hành động</th><th>Người</th><th>Vai trò</th><th>Lúc</th></tr></thead>
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
    .map(l => `<option value="${l.lot_id}">${esc(l.lot_code)} (${l.quantity}${l.uom})</option>`).join("");
}

// ================= KHO NVL =================
VIEWS.warehouse = async function () {
  const sec = SUB.warehouse || "ton";
  const sections = [
    { key: "ton", label: "Xem tồn kho" }, { key: "the", label: "Thẻ kho" },
    { key: "han", label: "Hạn sử dụng" }, { key: "bc", label: "BC nhập-xuất-tồn" },
    { key: "giao", label: "Nhập / Xuất / Hoàn / Sang ngang" },
  ];
  let body = "";
  if (sec === "ton") {
    const stock = await GET("/warehouse/stock");
    body = `<div class="panel"><h2>Tồn kho hiện tại</h2>
      <table><thead><tr><th>Mã VT</th><th>Tên</th><th>Nhóm</th><th>Tồn</th><th>ĐVT</th></tr></thead>
      <tbody>${stock.map(s => `<tr><td><code class="k">${esc(s.material_code)}</code></td><td>${esc(s.material_name)}</td>
        <td class="muted">${esc(s.category || "")}</td><td>${s.on_hand}</td><td>${s.uom}</td></tr>`).join("")}</tbody></table></div>`;
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
      <table><thead><tr><th>Lô</th><th>SL</th><th>Hạn</th><th>Còn (ngày)</th><th>Trạng thái</th><th>Vị trí</th></tr></thead>
      <tbody>${exp.map(e => `<tr><td><code class="k">${esc(e.lot_code)}</code></td><td>${e.quantity} ${e.uom}</td>
        <td class="muted">${fmt(e.expiry)}</td><td>${e.days_left}</td><td>${badge(e.status)}</td><td class="muted">${esc(e.location || "")}</td></tr>`).join("") || '<tr><td colspan=6 class="muted">Không có lô có hạn dùng.</td></tr>'}</tbody></table></div>`;
  } else if (sec === "bc") {
    const rep = await GET("/warehouse/report?days=60");
    body = `<div class="panel"><h2>Báo cáo nhập-xuất-tồn (60 ngày)</h2>
      <table><thead><tr><th>Mã VT</th><th>Tên</th><th>Nhập</th><th>Xuất</th><th>Tồn cuối</th><th>ĐVT</th></tr></thead>
      <tbody>${rep.map(r => `<tr><td><code class="k">${esc(r.material_code)}</code></td><td>${esc(r.material_name)}</td>
        <td style="color:var(--green)">${r.received}</td><td style="color:var(--orange)">${r.issued}</td>
        <td>${r.on_hand}</td><td>${r.uom}</td></tr>`).join("")}</tbody></table></div>`;
  } else if (sec === "giao") {
    const [lotsAvail, mats] = await Promise.all([lotOptions(null, false), GET("/materials")]);
    const matOpts = mats.map(m => `<option value="${m.material_id}">${esc(m.code)}</option>`).join("");
    body = `<div class="split">
      <div class="panel"><h2>Nhập kho</h2>
        <div class="row"><div class="field"><label>Mã lô</label><input id="rc_code" placeholder="MALT-..."/></div>
          <div class="field"><label>Vật tư</label><select id="rc_mat">${matOpts}</select></div></div>
        <div class="row"><div class="field"><label>SL</label><input id="rc_qty" type="number" value="500"/></div>
          <div class="field"><label>ĐVT</label><input id="rc_uom" value="kg" size="4"/></div>
          <div class="field"><label>Hạn dùng</label><input id="rc_exp" type="date"/></div>
          <button class="btn" id="rc_do">Nhập</button></div></div>
      <div class="panel"><h2>Xuất / Hoàn / Sang ngang</h2>
        <div class="row"><div class="field"><label>Lô</label><select id="wi_lot">${lotsAvail}</select></div>
          <div class="field"><label>SL</label><input id="wi_qty" type="number" value="50"/></div></div>
        <div class="row">
          <button class="btn" id="wi_issue">Xuất (đề nghị)</button>
          <button class="btn sec" id="wi_return">Nhập hoàn</button>
          <div class="field"><label>→ Vị trí</label><input id="wi_loc" placeholder="Kho B"/></div>
          <button class="btn sec" id="wi_transfer">Sang ngang</button>
        </div></div></div>`;
  }
  $("view-warehouse").innerHTML = subnav("warehouse", sections, sec) + body;
  wireSubnav("warehouse");
  if (sec === "the") $("wc_load").onclick = () => guard(async () => {
    const card = await GET("/warehouse/card?material_id=" + $("wc_mat").value);
    $("wc_table").innerHTML = `<table><thead><tr><th>Thời gian</th><th>Loại</th><th>Lô</th><th>Nhập</th><th>Xuất</th><th>Tồn</th><th>Lý do</th></tr></thead>
      <tbody>${card.map(c => `<tr><td class="muted">${fmt(c.ts)}</td><td>${badge(c.type === "receipt" ? "available" : c.type === "issue" ? "on_hold" : "planned")}${c.type}</td>
        <td>${esc(c.lot_code || "")}</td><td style="color:var(--green)">${c.in || ""}</td><td style="color:var(--orange)">${c.out || ""}</td>
        <td><b>${c.balance}</b> ${c.uom}</td><td class="muted">${esc(c.reason || "")}</td></tr>`).join("") || '<tr><td colspan=7 class="muted">Chưa có giao dịch.</td></tr>'}</tbody></table>`;
  });
  if (sec === "giao") {
    $("rc_do").onclick = () => guard(async () => {
      await POST("/warehouse/receive", { lot_code: $("rc_code").value, material_id: $("rc_mat").value,
        quantity: parseFloat($("rc_qty").value), uom: $("rc_uom").value,
        expiry: $("rc_exp").value || null, reason: "Nhập kho" });
      toast("Đã nhập kho"); render("warehouse");
    });
    $("wi_issue").onclick = () => guard(async () => { await POST("/warehouse/issue", { lot_id: $("wi_lot").value, quantity: parseFloat($("wi_qty").value), mode: "de_nghi" }); toast("Đã xuất"); render("warehouse"); });
    $("wi_return").onclick = () => guard(async () => { await POST("/warehouse/return", { lot_id: $("wi_lot").value, quantity: parseFloat($("wi_qty").value) }); toast("Đã nhập hoàn"); render("warehouse"); });
    $("wi_transfer").onclick = () => guard(async () => { await POST("/warehouse/transfer", { lot_id: $("wi_lot").value, quantity: parseFloat($("wi_qty").value), location_to: $("wi_loc").value }); toast("Đã chuyển vị trí"); render("warehouse"); });
  }
};

// ================= NĂNG LƯỢNG =================
VIEWS.energy = async function () {
  const sec = SUB.energy || "daily";
  const sections = [
    { key: "daily", label: "Biểu đồ ngày" }, { key: "month", label: "Tổng hợp tháng" },
    { key: "update", label: "Cập nhật số liệu" }, { key: "dm", label: "Danh mục" },
  ];
  const groups = await GET("/energy/groups");
  let body = "";
  if (sec === "daily") {
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
      <table><thead><tr><th>Tháng</th><th>Nhóm</th><th>Sản lượng</th><th>ĐVT</th></tr></thead>
      <tbody>${m.map(r => `<tr><td>${esc(r.month)}</td><td>${esc(r.group)}</td><td>${r.value.toLocaleString("vi-VN")}</td><td>${esc(r.unit)}</td></tr>`).join("")}</tbody></table></div>`;
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
  wireSubnav("energy");
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
      <table><thead><tr><th>Mã</th><th>Thiết bị</th><th>Tiêu đề</th><th>Mức</th><th>Trạng thái</th><th>Dừng (phút)</th><th></th></tr></thead>
      <tbody>${incs.map(i => { const eq = eqs.find(e => e.equipment_id === i.equipment_id);
        return `<tr><td><code class="k">${esc(i.incident_code)}</code></td><td>${esc(eq ? eq.code : "")}</td>
        <td>${esc(i.title)}</td><td>${badge(i.severity)}</td><td>${badge(i.status)}</td><td>${i.downtime_min}</td>
        <td>${i.status === "open" || i.status === "in_progress" ? `<button class="btn sm sec" data-resolve="${i.incident_id}">Xử lý xong</button>` : ""}</td></tr>`; }).join("")}</tbody></table></div>`;
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
      <table><thead><tr><th>Thiết bị</th><th>Loại</th><th>Ngày</th><th>Trạng thái</th><th>Ghi chú</th><th></th></tr></thead>
      <tbody>${plans.map(p => `<tr><td>${esc(p.equipment)}</td><td>${esc(typeLabel[p.plan_type] || p.plan_type)}</td>
        <td>${fmt(p.scheduled_date)}</td><td>${badge(p.status)}</td><td class="muted">${esc(p.note || "")}</td>
        <td>${p.status !== "done" ? `<button class="btn sm sec" data-plandone="${p.plan_id}">Hoàn thành</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
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
  wireSubnav("maint");
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
      <table><thead><tr><th>Tên</th><th>Loại</th><th>Thiết bị</th><th>Lần cuối</th><th>Hạn</th><th>Còn (ngày)</th><th>Trạng thái</th></tr></thead>
      <tbody>${items.map(c => `<tr><td>${esc(c.name)}</td><td>${esc(typeLabel[c.calib_type] || c.calib_type)}</td>
        <td class="muted">${esc(c.equipment || "")}</td><td class="muted">${fmt(c.last_date)}</td><td>${fmt(c.due_date)}</td>
        <td>${c.days_left}</td><td>${badge(c.status)}</td></tr>`).join("")}</tbody></table></div>`;
  $("cb_add").onclick = () => guard(async () => {
    await POST("/maint/calibrations", { name: $("cb_name").value, calib_type: $("cb_type").value,
      equipment_id: $("cb_eq").value || null, due_date: $("cb_due").value });
    toast("Đã thêm kiểm định"); render("calib");
  });
};

// ================= NẤU-LỌC-CHIẾT (chi tiết theo công đoạn) =================
function wireSearch() {
  document.querySelectorAll(".searchbox[data-tbl]").forEach(inp => inp.oninput = () => {
    const q = inp.value.toLowerCase();
    document.querySelectorAll(`#${inp.dataset.tbl} tbody tr`).forEach(tr =>
      tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none");
  });
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

  if (sec === "nguyenlieu") {
    const rows = await GET("/brewing/materials");
    body = `<div class="panel"><h2>Thông tin nguyên liệu <span class="muted">(${rows.length})</span></h2>
      <input class="searchbox" data-tbl="t_nl" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_nl"><thead><tr><th>Chỉ tiêu</th><th>MSKT</th><th>Ngày nhập</th><th>Nguyên liệu</th>
        <th>Số lô PM</th><th>Số lô KCS</th><th>Số lượng</th><th>ĐVT</th><th>Nơi nhập</th><th>Nhà cung cấp</th></tr></thead>
      <tbody>${rows.map(r => `<tr class="row-${r.color}"><td>Xem</td><td>${esc(r.mskt)}</td><td>${fmt(r.receipt_date)}</td>
        <td>${esc(r.material_name)}</td><td>${esc(r.lot_pm || "")}</td><td>${esc(r.lot_kcs || "")}</td>
        <td>${r.quantity.toLocaleString("vi-VN")}</td><td>${esc(r.uom)}</td><td class="muted">${esc(r.location || "")}</td>
        <td class="muted">${esc(r.supplier || "")}</td></tr>`).join("")}</tbody></table></div>
      <div class="legend">Chú thích: <b class="red">Đỏ</b>: Chưa nhập số lô — <b class="green">Xanh lá</b>: Chưa nhập chỉ tiêu — <b class="blue">Xanh dương</b>: Đã nhập đầy đủ</div></div>`;
  }

  else if (sec === "nau") {
    const rows = await GET("/brewing/brews");
    body = `<div class="panel"><h2>Thêm thông tin nấu</h2>
      <div class="row">
        <div class="field"><label>Mã nấu</label><input id="nb_code"/></div>
        <div class="field"><label>Dịch nha</label><input id="nb_wort" value="Dịch bia Sapphire 14oP"/></div>
        <div class="field"><label>SL nấu/hl</label><input id="nb_vol" type="number" value="900"/></div>
        <div class="field"><label>Độ hòa tan NT</label><input id="nb_oe" type="number" step="0.1"/></div>
        <div class="field"><label>Plato</label><input id="nb_plato" type="number" step="0.1"/></div>
        <button class="btn" id="nb_add">Thêm</button>
      </div></div>
      <div class="panel"><h2>Thông tin nấu <span class="muted">(${rows.length})</span></h2>
      <input class="searchbox" data-tbl="t_nau" placeholder="Enter text to search..."/>
      <table id="t_nau"><thead><tr><th>Mã nấu</th><th>Ngày nấu</th><th>Dịch nha</th><th>SL nấu/hl</th><th>Độ hòa tan NT</th><th>Plato</th></tr></thead>
      <tbody>${rows.map(b => `<tr class="row-${b.color}"><td class="code">${esc(b.brew_code)}</td><td>${fmt(b.brew_date)}</td>
        <td>${esc(b.wort_type)}</td><td>${b.volume_hl}</td><td>${b.original_extract ?? '<span style="color:var(--red)">trống</span>'}</td>
        <td>${b.plato ?? '<span style="color:var(--red)">trống</span>'}</td></tr>`).join("")}</tbody></table>
      <div class="legend">Mẻ thiếu Độ hòa tan/Plato sẽ sinh cảnh báo (tab Cảnh báo chỉ tiêu).</div></div>`;
  }

  else if (sec === "lenmen") {
    const data = await GET("/brewing/ferments");
    const stLabel = { len_men: "Đang lên men", cho_loc: "Chờ lọc", da_loc: "Đã lọc" };
    body = `<div class="panel"><h2>Thông tin quá trình lên men <span class="muted">(${data.items.length})</span></h2>
      <input class="searchbox" data-tbl="t_lm" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_lm"><thead><tr><th>Lô LM</th><th>Mã nấu</th><th>Ngày nấu</th><th>Ngày KT</th><th>Số mẻ</th>
        <th>Dịch nha</th><th>Đời men</th><th>Tank LM</th><th>SL nấu/hl</th><th>Đang tồn CCT/hl</th><th>Trạng thái</th><th>Số ngày LM</th></tr></thead>
      <tbody>${data.items.map(r => `<tr><td>${esc(r.lm_code)}</td><td>${esc(r.brew_code || "")}</td><td>${fmt(r.brew_date)}</td>
        <td>${fmt(r.kt_date)}</td><td class="muted">${esc(r.batch_numbers || "")}</td><td>${esc(r.wort_type)}</td>
        <td class="muted">${esc(r.yeast_gen || "")}</td><td>${esc(r.tank_lm)}</td><td>${r.volume_hl.toLocaleString("vi-VN")}</td>
        <td>${r.on_hand_cct.toLocaleString("vi-VN")}</td><td>${badge("running")}${stLabel[r.status] || r.status}</td>
        <td class="muted">${esc(r.ferment_days || "")}</td></tr>`).join("")}
      <tr style="font-weight:700"><td colspan=8 style="text-align:right">Tổng cộng:</td><td>${data.total_brew_hl.toLocaleString("vi-VN")}</td><td>${data.total_cct_hl.toLocaleString("vi-VN")}</td><td colspan=2></td></tr></tbody></table></div></div>`;
  }

  else if (sec === "loc") {
    const rows = await GET("/brewing/filters");
    const ferments = (await GET("/brewing/ferments")).items;
    const tankOpts = [...new Set(ferments.map(f => f.tank_lm))].map(t => `<option>${esc(t)}</option>`).join("");
    body = `<div class="panel"><h2>Thêm thông tin lọc (Lọc thường)</h2>
      <div class="row">
        <div class="field"><label>Từ Tank LM</label><select id="fl_cct"><option value=""></option>${tankOpts}</select></div>
        <div class="field"><label>Loại bia</label><input id="fl_beer" value="Bia lon Sapphire"/></div>
        <div class="field"><label>Mã lô lọc</label><input id="fl_lot" value="701"/></div>
        <div class="field"><label>Dịch nha lọc/hl</label><input id="fl_vdich" type="number" value="200"/></div>
        <div class="field"><label>Sản lượng lọc/hl</label><input id="fl_vbia" type="number" value="240"/></div>
        <div class="field"><label>Cho vào Tank BBT</label><input id="fl_bbt" value="T1"/></div>
        <button class="btn" id="fl_add">Thêm</button>
      </div></div>
      <div class="panel"><h2>Thông tin lọc <span class="muted">(${rows.length})</span></h2>
      <input class="searchbox" data-tbl="t_loc" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_loc"><thead><tr><th>Chi tiết</th><th>Mã lọc</th><th>Mã nấu</th><th>Ngày lọc</th>
        <th>Loại dịch nha lọc</th><th>Lọc từ CCT</th><th>V dịch/hl</th><th>Loại bia lọc</th><th>V Bia/hl</th><th>Lọc cho vào</th>
        <th>Trạng thái</th><th>Đang tồn BBT/hl</th></tr></thead>
      <tbody>${rows.map(r => `<tr class="row-${r.color}"><td>Xem</td><td class="code">${esc(r.filter_code)}</td><td>${esc(r.brew_code || "")}</td>
        <td>${fmt(r.filter_date)}</td><td>${esc(r.wort_type || "")}</td><td>${esc(r.from_cct || "")}</td><td>${r.v_dich_hl}</td>
        <td>${esc(r.beer_type)}</td><td>${r.v_beer_hl}</td><td>${esc(r.to_bbt || "")}</td><td>${esc(r.status_label)}</td>
        <td>${r.on_hand_bbt}</td></tr>`).join("")}</tbody></table></div>
      <div class="legend">Chú thích: <b class="red">Đỏ</b>: Chưa nhập chỉ tiêu — <b class="green">Xanh lá</b>: Chưa nhập NVL — <b class="blue">Xanh dương</b>: Đầy đủ — <b class="cyan">Xanh nhạt</b>: Lọc vào BBT phối</div></div>`;
  }

  else if (sec === "chiet") {
    const rows = await GET("/brewing/bottles");
    const filters = await GET("/brewing/filters");
    const bbtOpts = [...new Set(filters.map(f => f.to_bbt).filter(Boolean))].map(t => `<option>${esc(t)}</option>`).join("");
    body = `<div class="panel"><h2>Thêm thông tin chiết</h2>
      <div class="row">
        <div class="field"><label>Chiết từ tank BBT</label><select id="bo_bbt"><option value=""></option>${bbtOpts}</select></div>
        <div class="field"><label>Dây chuyền</label><input id="bo_line" value="Lon Sapphire"/></div>
        <div class="field"><label>Loại bia</label><input id="bo_beer" value="Bia lon Sapphire(sleek can)"/></div>
        <div class="field"><label>Số lô</label><input id="bo_lot" value="700"/></div>
        <div class="field"><label>V cấp chiết/hl</label><input id="bo_v" type="number" value="200"/></div>
      </div>
      <div class="row">
        <div class="field"><label>Ca 1/két,thùng</label><input id="bo_ca1" type="number" value="0"/></div>
        <div class="field"><label>Ca 2/két,thùng</label><input id="bo_ca2" type="number" value="0"/></div>
        <div class="field"><label>Ca 3/két,thùng</label><input id="bo_ca3" type="number" value="0"/></div>
        <button class="btn" id="bo_add">Thêm</button>
      </div></div>
      <div class="panel"><h2>Thông tin chiết <span class="muted">(${rows.length})</span></h2>
      <input class="searchbox" data-tbl="t_chiet" placeholder="Enter text to search..."/>
      <div class="tablewrap"><table id="t_chiet"><thead><tr><th>Chi tiết</th><th>Mã chiết</th><th>Mã lọc</th><th>Ngày chiết</th><th>Loại bia</th>
        <th>Số lô bia</th><th>V cấp chiết/hl</th><th>Chiết từ Tank BBT</th><th>SL ca 1</th><th>SL ca 2</th><th>SL ca 3</th>
        <th>Tổng Cộng</th><th>Đã nhập kho</th><th>Chiết duyệt</th></tr></thead>
      <tbody>${rows.map(b => `<tr class="row-${b.color}"><td>${b.approved ? "Xem" : `<a href="#" data-approve="${b.bottle_id}" style="color:var(--accent)">Duyệt</a>`}</td>
        <td class="code">${esc(b.bottle_code)}</td><td>${esc(b.filter_code || "")}</td><td>${fmt(b.bottle_date)}</td><td>${esc(b.beer_type)}</td>
        <td>${esc(b.lot_no || "")}</td><td>${b.v_cap_chiet_hl}</td><td>${esc(b.from_bbt || "")}</td>
        <td>${b.ca1 ? b.ca1.toLocaleString("vi-VN") : ""}</td><td>${b.ca2 ? b.ca2.toLocaleString("vi-VN") : ""}</td>
        <td>${b.ca3 ? b.ca3.toLocaleString("vi-VN") : ""}</td><td>${b.total.toLocaleString("vi-VN")}</td>
        <td style="text-align:center">${chk(b.stocked)}</td><td style="text-align:center">${chk(b.approved)}</td></tr>`).join("")}</tbody></table></div>
      <div class="legend">Chú thích: <b class="red">Đỏ</b>: Chưa nhập đủ chỉ tiêu — <b class="green">Xanh lá</b>: Chưa nhập NVL — <b class="blue">Xanh dương</b>: Đầy đủ</div></div>`;
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

  if (sec === "nau") $("nb_add").onclick = () => guard(async () => {
    await POST("/brewing/brews", { brew_code: $("nb_code").value, wort_type: $("nb_wort").value,
      volume_hl: parseFloat($("nb_vol").value), original_extract: $("nb_oe").value === "" ? null : parseFloat($("nb_oe").value),
      plato: $("nb_plato").value === "" ? null : parseFloat($("nb_plato").value) });
    toast("Đã thêm mẻ nấu"); render("process");
  });
  if (sec === "loc") $("fl_add").onclick = () => guard(async () => {
    await POST("/brewing/filters", { filter_code: "FL-" + Date.now().toString().slice(-5), from_cct: $("fl_cct").value,
      beer_type: $("fl_beer").value, lot_loc: $("fl_lot").value, v_dich_hl: parseFloat($("fl_vdich").value),
      v_beer_hl: parseFloat($("fl_vbia").value), to_bbt: $("fl_bbt").value, wort_type: "Dịch bia 14oP" });
    toast("Đã thêm bản ghi lọc"); render("process");
  });
  if (sec === "chiet") {
    $("bo_add").onclick = () => guard(async () => {
      await POST("/brewing/bottles", { bottle_code: "CH-" + Date.now().toString().slice(-5), from_bbt: $("bo_bbt").value,
        line: $("bo_line").value, beer_type: $("bo_beer").value, lot_no: $("bo_lot").value,
        v_cap_chiet_hl: parseFloat($("bo_v").value), ca1: parseFloat($("bo_ca1").value), ca2: parseFloat($("bo_ca2").value), ca3: parseFloat($("bo_ca3").value) });
      toast("Đã thêm bản ghi chiết"); render("process");
    });
    document.querySelectorAll("[data-approve]").forEach(a => a.onclick = (e) => { e.preventDefault(); guard(async () => {
      await POST(`/brewing/bottles/${a.dataset.approve}/approve`); toast("Đã duyệt chiết"); render("process");
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
};

// ================= REALTIME / HISTORIAN =================
const shortTag = (t) => t.split("/").slice(-2).join("/");
const RT_COLORS = ["#f5a623", "#3498db", "#e74c3c", "#2ecc71", "#9b59b6", "#1abc9c", "#e67e22", "#e84393"];
VIEWS.realtime = async function () {
  const tags = await GET("/historian/tags");
  if (!SUB.rt_tag || !tags.includes(SUB.rt_tag)) SUB.rt_tag = tags[0];
  const tOpts = tags.map(t => `<option value="${t}" ${t === SUB.rt_tag ? "selected" : ""}>${esc(shortTag(t))}</option>`).join("");
  $("view-realtime").innerHTML = `
    <div class="panel"><h2>📡 Realtime — Telemetry từ edge <span id="rt_clock" class="muted"></span></h2>
      <div class="muted">Dữ liệu sensor (nhiệt độ/áp suất/°P/DO/flow/năng lượng) đẩy từ edge gateway qua <code class="k">POST /api/historian/ingest</code> (OPC UA/MQTT giả lập). Tự cập nhật mỗi 4 giây.</div>
      <div class="cards" id="rt_cards" style="margin-top:12px"></div>
      <div class="row"><button class="btn sec" id="rt_tick">⚙ Mô phỏng 1 nhịp</button>
        <span class="muted" style="align-self:center">hoặc chạy liên tục: <code class="k">python -m app.edge_sim</code> (key <code class="k">mes_edge_writer_key_0001</code>)</span></div>
    </div>
    <div class="panel"><h2>Biểu đồ xu hướng (6 giờ)</h2>
      <div class="row"><div class="field"><label>Tag</label><select id="rt_tag">${tOpts}</select></div></div>
      <div id="rt_chart"></div>
    </div>`;
  const refresh = () => guard(async () => {
    const [latest, ser] = await Promise.all([GET("/historian/latest"), GET("/historian/series?tag=" + encodeURIComponent(SUB.rt_tag) + "&hours=6&buckets=70")]);
    $("rt_clock").textContent = "· cập nhật " + new Date().toLocaleTimeString("vi-VN");
    $("rt_cards").innerHTML = latest.filter(Boolean).map((l, i) => `<div class="card">
      <div class="n" style="color:${RT_COLORS[i % RT_COLORS.length]};font-size:22px">${l.value}<span style="font-size:12px;color:var(--muted)"> ${esc(l.unit || "")}</span></div>
      <div class="l">${esc(shortTag(l.tag))}</div>
      <div class="l" style="font-size:10px">${badge(l.quality === "good" ? "available" : "overdue")}${fmt(l.ts).slice(-8)}</div></div>`).join("");
    const pts = (ser.points || []).map(p => ({ ts: p.ts, value: p.value }));
    $("rt_chart").innerHTML = CH.line(pts, { color: RT_COLORS[tags.indexOf(SUB.rt_tag) % RT_COLORS.length], unit: ser.unit, label: shortTag(SUB.rt_tag), height: 200 });
  });
  $("rt_tag").onchange = () => { SUB.rt_tag = $("rt_tag").value; refresh(); };
  $("rt_tick").onclick = () => guard(async () => { await POST("/historian/simulate", {}); refresh(); });
  await refresh();
  window.__rt = setInterval(refresh, 4000);
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
  let keys = [], hooks = [];
  if (isAdmin) { [keys, hooks] = await Promise.all([GET("/integration/keys"), GET("/integration/webhooks")]); }
  const manifest = await GET("/ai/tools");
  $("view-integration").innerHTML = `
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
        <table><thead><tr><th>Tên</th><th>Token</th><th>Scope</th><th>Gọi</th><th>Trạng thái</th><th></th></tr></thead>
        <tbody>${keys.map(k => `<tr><td>${esc(k.name)}</td><td><code class="k">${esc(k.token_preview)}</code></td><td>${esc(k.scopes)}</td>
          <td>${k.call_count}</td><td>${badge(k.active ? "available" : "obsolete")}${k.active ? "active" : "revoked"}</td>
          <td>${k.active ? `<button class="btn sm sec" data-revoke="${k.key_id}">Khoá</button>` : ""}</td></tr>`).join("")}</tbody></table></div>
      <div class="panel"><h2>Webhooks</h2>
        <div class="row"><div class="field" style="flex:1"><label>URL nhận sự kiện</label><input id="w_url" placeholder="https://..." style="width:100%"/></div>
          <button class="btn" id="w_add">Đăng ký</button></div>
        <table><thead><tr><th>URL</th><th>Loại</th><th>Đã gửi</th><th>Trạng thái</th></tr></thead>
        <tbody>${hooks.map(w => `<tr><td class="muted">${esc(w.target_url)}</td><td>${esc(w.event_types)}</td><td>${w.delivered_count}</td>
          <td>${badge(w.active ? "available" : "obsolete")}${w.active ? "active" : "off"}</td></tr>`).join("") || '<tr><td colspan=4 class="muted">Chưa có webhook.</td></tr>'}</tbody></table></div>
    </div>` : `<div class="panel muted">Đăng nhập vai trò <code class="k">admin</code> (góc phải) để quản trị API key & webhook.</div>`}`;
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
  }
};

// ================= BÁO CÁO SẢN XUẤT =================
const normStatus = { dat: ["available", "đạt"], vuot: ["critical", "vượt định mức"], thieu: ["due", "thiếu"] };
VIEWS.reports = async function () {
  const days = SUB.reports_days || 3650;
  const rep = await GET("/reports/material-norm?days=" + days);
  $("view-reports").innerHTML = `
    <div class="panel"><h2>BC định mức nguyên vật liệu <span class="muted">(${rep.batch_count} mẻ)</span></h2>
      <div class="row"><div class="field"><label>Kỳ (ngày gần đây)</label>
        <select id="rp_days"><option value="30">30 ngày</option><option value="90">90 ngày</option><option value="365">365 ngày</option><option value="3650" selected>Tất cả</option></select></div>
      </div>
      <h3>Tổng hợp theo vật tư (định mức scale ↔ thực tế)</h3>
      <div class="tablewrap"><table><thead><tr><th>Vật tư</th><th>Số mẻ</th><th>Định mức</th><th>Thực tế</th><th>Chênh</th><th>%</th><th>ĐVT</th><th>Trạng thái</th></tr></thead>
      <tbody>${rep.materials.map(m => `<tr class="row-${{dat:"blue",vuot:"red",thieu:"green"}[m.status] || ""}">
        <td><code class="k">${esc(m.material_code)}</code></td><td>${m.batches}</td>
        <td>${m.planned.toLocaleString("vi-VN")}</td><td>${m.actual.toLocaleString("vi-VN")}</td>
        <td style="color:${m.diff > 0 ? "var(--red)" : m.diff < 0 ? "var(--orange)" : "var(--muted)"}">${m.diff > 0 ? "+" : ""}${m.diff.toLocaleString("vi-VN")}</td>
        <td>${m.pct}%</td><td>${esc(m.uom || "")}</td>
        <td>${badge((normStatus[m.status] || ["planned", m.status])[0])}${(normStatus[m.status] || ["", m.status])[1]}</td></tr>`).join("") || '<tr><td colspan=8 class="muted">Chưa có dữ liệu.</td></tr>'}</tbody></table></div>
      <h3>Theo mẻ</h3>
      <div class="tablewrap"><table><thead><tr><th>Mã mẻ</th><th>Trạng thái</th><th>SL kế hoạch</th><th>Tổng định mức</th><th>Tổng thực tế</th></tr></thead>
      <tbody>${rep.batches.map(b => `<tr><td><code class="k">${esc(b.batch_code)}</code></td><td>${badge(b.state)}</td>
        <td>${b.planned_qty.toLocaleString("vi-VN")} ${esc(b.uom)}</td><td>${b.planned_total.toLocaleString("vi-VN")}</td>
        <td>${b.actual_total.toLocaleString("vi-VN")}</td></tr>`).join("") || '<tr><td colspan=5 class="muted">—</td></tr>'}</tbody></table></div>
      <div class="muted" style="margin-top:8px">Định mức = BOM của từng mẻ đã scale theo SL kế hoạch; thực tế = tiêu thụ thật (genealogy). Ngưỡng đạt: ±5%.</div>
    </div>`;
  $("rp_days").value = String(days);
  $("rp_days").onchange = () => { SUB.reports_days = parseInt($("rp_days").value); render("reports"); };
};

// ================= QUẢN TRỊ TÀI KHOẢN (admin) =================
const ROLE_DESC = { operator: "Vận hành (ghi nhận)", supervisor: "Trưởng ca/Quản đốc",
  qa: "QA/KCS (release)", engineer: "Kỹ sư (recipe)", admin: "Quản trị" };
const ALL_VIEWS = ["dashboard","orders","dispatch","recipes","batches","quality","process","trace",
  "warehouse","energy","realtime","maint","calib","reports","ai","integration","master","users","audit"];

// ================= DANH MỤC (master data: sản phẩm + vật tư) =================
VIEWS.master = async function () {
  const [products, materials, plines] = await Promise.all([
    GET("/products"), GET("/materials"), GET("/lines").catch(() => [])]);
  const canManage = CURRENT_USER && (CURRENT_USER.permissions === "*" ||
    (Array.isArray(CURRENT_USER.permissions) && CURRENT_USER.permissions.includes("master.manage")));
  const noPerm = canManage ? "" :
    `<div class="muted" style="margin-bottom:8px">Bạn chỉ có quyền xem danh mục (cần quyền <code class="k">master.manage</code> để tạo/sửa).</div>`;
  const cats = ["malt", "hop", "yeast", "adjunct", "packaging", "chemical", "other"];
  $("view-master").innerHTML = `
    <div class="split">
      <div class="panel"><h2>🍺 Sản phẩm <span class="muted">(${products.length})</span></h2>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã SP</label><input id="pr_code" placeholder="BIA-IPA"/></div>
          <div class="field"><label>Tên sản phẩm</label><input id="pr_name" placeholder="Bia IPA 5.5%"/></div>
          <div class="field"><label>ĐVT</label><input id="pr_uom" value="L" style="width:70px"/></div>
        </div>
        <div class="field"><label>Mô tả</label><input id="pr_desc" placeholder="(tuỳ chọn)" style="width:100%"/></div>
        <button class="btn" id="pr_add" style="margin-top:10px">+ Tạo sản phẩm</button>` : ""}
        <div class="tablewrap" style="margin-top:12px"><table>
          <thead><tr><th>Mã</th><th>Tên</th><th>ĐVT</th><th>Mô tả</th>${canManage ? "<th></th>" : ""}</tr></thead>
          <tbody>${products.map(p => `<tr>
            <td><code class="k">${esc(p.code)}</code></td><td>${esc(p.name)}</td><td>${esc(p.uom)}</td>
            <td class="muted">${esc(p.description || "—")}</td>
            ${canManage ? `<td><button class="btn sm sec" data-ep="${esc(p.product_id)}">Sửa</button></td>` : ""}</tr>`).join("")}</tbody>
        </table></div>
      </div>

      <div class="panel"><h2>📦 Vật tư / Nguyên liệu <span class="muted">(${materials.length})</span></h2>
        ${noPerm}
        ${canManage ? `<div class="row">
          <div class="field"><label>Mã VT</label><input id="mt_code" placeholder="MALT-CARA"/></div>
          <div class="field"><label>Tên vật tư</label><input id="mt_name" placeholder="Malt Caramel"/></div>
          <div class="field"><label>ĐVT</label><input id="mt_uom" value="kg" style="width:70px"/></div>
          <div class="field"><label>Nhóm</label><select id="mt_cat">${cats.map(c => `<option>${c}</option>`).join("")}</select></div>
        </div>
        <button class="btn" id="mt_add" style="margin-top:10px">+ Tạo vật tư</button>` : ""}
        <div class="tablewrap" style="margin-top:12px"><table>
          <thead><tr><th>Mã</th><th>Tên</th><th>ĐVT</th><th>Nhóm</th>${canManage ? "<th></th>" : ""}</tr></thead>
          <tbody>${materials.map(m => `<tr>
            <td><code class="k">${esc(m.code)}</code></td><td>${esc(m.name)}</td><td>${esc(m.uom)}</td>
            <td>${esc(m.category || "—")}</td>
            ${canManage ? `<td><button class="btn sm sec" data-em="${esc(m.material_id)}">Sửa</button></td>` : ""}</tr>`).join("")}</tbody>
        </table></div>
      </div>
    </div>
    <div class="panel"><h2>🏭 Dây chuyền & Tank (tài nguyên SX) <span class="muted">(${plines.length})</span></h2>
      <div class="muted" style="margin-bottom:6px">Dây chuyền dùng cho OEE đóng gói; Tank lên men (FV) dùng chung cho bộ lập lịch.</div>
      ${noPerm}
      ${canManage ? `<div class="row">
        <div class="field"><label>Mã</label><input id="ln_code" placeholder="Line-3 (keg) / FV-05"/></div>
        <div class="field"><label>Tên</label><input id="ln_name" placeholder="Dây chuyền keg #3"/></div>
        <div class="field"><label>Loại</label><select id="ln_kind">
          <option value="line">Dây chuyền (đóng gói)</option>
          <option value="tank">Tank lên men (FV)</option>
          <option value="brewhouse">Nhà nấu (brewhouse)</option></select></div>
        <div class="field"><label>Khu vực</label><input id="ln_area" value="chiet" style="width:90px"/></div>
        <div class="field"><label>Tốc độ lý tưởng</label><input id="ln_rate" value="200" style="width:110px"/></div>
        <button class="btn" id="ln_add" style="align-self:flex-end">+ Thêm tài nguyên</button>
      </div>` : ""}
      <div class="tablewrap" style="margin-top:12px"><table>
        <thead><tr><th>Mã</th><th>Tên</th><th>Loại</th><th>Khu vực</th><th>Tốc độ lý tưởng</th><th>Trạng thái</th>${canManage ? "<th></th>" : ""}</tr></thead>
        <tbody>${plines.map(l => `<tr>
          <td><code class="k">${esc(l.code)}</code></td><td>${esc(l.name)}</td>
          <td>${l.kind === "tank" ? badge("planned") + "Tank" : l.kind === "brewhouse" ? badge("due") + "Nhà nấu" : badge("available") + "Dây chuyền"}</td>
          <td>${esc(l.area || "—")}</td>
          <td>${l.ideal_rate_per_min ? l.ideal_rate_per_min + "/phút" : "—"}</td>
          <td>${badge(l.active ? "available" : "obsolete")}${l.active ? "hoạt động" : "ngừng"}</td>
          ${canManage ? `<td><button class="btn sm sec" data-ltoggle="${esc(l.line_id)}">${l.active ? "Ngừng" : "Bật lại"}</button></td>` : ""}</tr>`).join("")}</tbody>
      </table></div>
    </div>`;

  if (canManage) {
    $("pr_add").onclick = () => guard(async () => {
      await POST("/products", { code: $("pr_code").value.trim(), name: $("pr_name").value.trim(),
        uom: $("pr_uom").value.trim() || "L", description: $("pr_desc").value.trim() || null });
      toast("Đã tạo sản phẩm"); render("master");
    });
    $("mt_add").onclick = () => guard(async () => {
      await POST("/materials", { code: $("mt_code").value.trim(), name: $("mt_name").value.trim(),
        uom: $("mt_uom").value.trim() || "kg", category: $("mt_cat").value });
      toast("Đã tạo vật tư"); render("master");
    });
    if ($("ln_add")) $("ln_add").onclick = () => guard(async () => {
      await POST("/lines", { code: $("ln_code").value.trim(), name: $("ln_name").value.trim(),
        kind: $("ln_kind").value, area: $("ln_area").value.trim() || null,
        ideal_rate_per_min: parseFloat($("ln_rate").value) || 0 });
      toast("Đã thêm tài nguyên"); render("master");
    });
    document.querySelectorAll("[data-ltoggle]").forEach(b => b.onclick = () => guard(async () => {
      await POST(`/lines/${b.dataset.ltoggle}/toggle`); toast("Đã đổi trạng thái dây chuyền"); render("master");
    }));
    document.querySelectorAll("[data-ep]").forEach(b => b.onclick = () => {
      const p = products.find(x => x.product_id === b.dataset.ep);
      modal(`<h3>Sửa sản phẩm</h3>
        <div class="field"><label>Mã</label><input id="ep_code" value="${esc(p.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="ep_name" value="${esc(p.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>ĐVT</label><input id="ep_uom" value="${esc(p.uom)}"/></div>
        <div class="field" style="margin-top:8px"><label>Mô tả</label><input id="ep_desc" value="${esc(p.description || "")}"/></div>
        <button class="btn" id="ep_save" style="margin-top:12px">Lưu</button>`);
      $("ep_save").onclick = () => guard(async () => {
        await PUT(`/products/${p.product_id}`, { code: $("ep_code").value.trim(), name: $("ep_name").value.trim(),
          uom: $("ep_uom").value.trim(), description: $("ep_desc").value.trim() || null });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
    document.querySelectorAll("[data-em]").forEach(b => b.onclick = () => {
      const m = materials.find(x => x.material_id === b.dataset.em);
      modal(`<h3>Sửa vật tư</h3>
        <div class="field"><label>Mã</label><input id="em_code" value="${esc(m.code)}"/></div>
        <div class="field" style="margin-top:8px"><label>Tên</label><input id="em_name" value="${esc(m.name)}"/></div>
        <div class="field" style="margin-top:8px"><label>ĐVT</label><input id="em_uom" value="${esc(m.uom)}"/></div>
        <div class="field" style="margin-top:8px"><label>Nhóm</label><input id="em_cat" value="${esc(m.category || "")}"/></div>
        <button class="btn" id="em_save" style="margin-top:12px">Lưu</button>`);
      $("em_save").onclick = () => guard(async () => {
        await PUT(`/materials/${m.material_id}`, { code: $("em_code").value.trim(), name: $("em_name").value.trim(),
          uom: $("em_uom").value.trim(), category: $("em_cat").value.trim() || null });
        closeModal(); toast("Đã cập nhật"); render("master");
      });
    });
  }
};
VIEWS.users = async function () {
  if (!CURRENT_USER || CURRENT_USER.role !== "admin") {
    $("view-users").innerHTML = '<div class="panel muted">Chỉ quản trị viên (admin) xem được trang này.</div>';
    return;
  }
  const [users, pcat, scat] = await Promise.all([
    GET("/auth/users"), GET("/auth/permissions"), GET("/auth/scope-catalog").catch(() => ({ areas: [], lines: [], qc_params: [] }))]);
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
      </div>
      <div class="muted" style="margin:4px 0">Khu vực: ${scat.areas.map(a => esc(a.key)).join(", ") || "—"} · Line: ${scat.lines.map(esc).join(", ") || "(chưa có)"}</div>
      <h3>Quyền thao tác (ma trận quyền)</h3>
      <div style="background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:10px">${permBoxes}</div>
      <button class="btn" id="nu_add" style="margin-top:12px">Tạo tài khoản</button>
    </div>
    <div class="panel"><h2>Danh sách tài khoản <span class="muted">(${users.length})</span></h2>
      <div class="tablewrap"><table><thead><tr><th>Đăng nhập</th><th>Họ tên</th><th>Vai trò</th><th>Quyền thao tác</th><th>Phạm vi (line)</th><th>Đăng nhập gần nhất</th><th>Trạng thái</th><th></th></tr></thead>
      <tbody>${users.map(u => `<tr><td><code class="k">${esc(u.username)}</code></td><td>${esc(u.full_name)}<div class="muted" style="font-size:11px">${esc(u.job_title)}</div></td>
        <td>${badge(u.role === "admin" ? "critical" : "available")}${esc(u.role)}</td>
        <td style="font-size:12px">${u.permissions === "*" ? '<span class="badge critical">toàn quyền</span>' : (u.permissions ? u.permissions.split(",").map(p => `<span class="badge planned" style="margin:1px">${esc(p)}</span>`).join(" ") : '<span class="muted">chỉ xem</span>')}</td>
        <td style="font-size:12px">${scopeBadge(u.scope_lines)}</td>
        <td class="muted">${fmt(u.last_login_at)}</td>
        <td>${badge(u.active ? "available" : "obsolete")}${u.active ? "hoạt động" : "khoá"}</td>
        <td style="white-space:nowrap"><button class="btn sm sec" data-scope="${esc(u.username)}">Phạm vi</button>
          ${u.username !== CURRENT_USER.username ? `<button class="btn sm sec" data-toggle="${u.username}">${u.active ? "Khoá" : "Mở"}</button>` : ""}</td></tr>`).join("")}</tbody></table></div></div>`;
  $("nu_add").onclick = () => guard(async () => {
    const weak = passwordPolicyMsg($("nu_pass").value, $("nu_user").value);
    if (weak) { toast(weak, "err"); return; }
    const perms = [...document.querySelectorAll(".nu_perm:checked")].map(c => c.value).join(",");
    await POST("/auth/users", { username: $("nu_user").value, password: $("nu_pass").value,
      full_name: $("nu_name").value, job_title: $("nu_title").value, role: $("nu_role").value,
      allowed_views: $("nu_views").value, permissions: perms,
      scope_lines: $("nu_lines").value || "*", scope_areas: $("nu_areas").value || "*", scope_qc: $("nu_qc").value || "*" });
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
      <button class="btn" id="sc_save" style="margin-top:12px">Lưu phạm vi</button>`);
    $("sc_save").onclick = () => guard(async () => {
      await PUT(`/auth/users/${u.username}/scope`, { scope_lines: $("sc_lines").value,
        scope_areas: $("sc_areas").value, scope_qc: $("sc_qc").value });
      closeModal(); toast("Đã cập nhật phạm vi"); render("users");
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
    const ok = !allowed || allowed.has(b.dataset.view) || b.dataset.view === "profile";
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
