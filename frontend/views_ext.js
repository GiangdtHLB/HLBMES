"use strict";
// ============================================================================
// Views mở rộng (phân hệ chiều sâu) — nạp SAU app.js, dùng chung helper toàn cục:
// GET/POST/PUT, $, esc, badge, fmt, toast, guard, modal, closeModal, CH, render,
// CURRENT_USER. Đăng ký vào VIEWS + ALL_VIEWS toàn cục.
//   recipeadv (#3) · dispense (#6) · qclab (#7) · oee (#8)
// ============================================================================
(function () {
  ["recipeadv", "dispense", "qclab", "oee", "isa88", "schedule", "wms"].forEach(v => { if (!ALL_VIEWS.includes(v)) ALL_VIEWS.push(v); });

  const num = (id) => { const x = $(id).value; return x === "" ? null : parseFloat(x); };
  const opt = (arr, val, lab, sel) => arr.map(o =>
    `<option value="${esc(val(o))}" ${String(val(o)) === String(sel) ? "selected" : ""}>${esc(lab(o))}</option>`).join("");
  const panel = (title, body) => `<div class="panel"><h2>${title}</h2>${body}</div>`;

  // ---------- Biểu đồ kiểm soát SPC (control chart) ----------
  function controlChart(spc) {
    const pts = spc.points || [];
    if (!pts.length) return '<div class="muted">Chưa có dữ liệu cho chỉ tiêu này.</div>';
    const W = 720, H = 250, pad = { l: 48, r: 14, t: 16, b: 26 };
    const ys = pts.map(p => p.value);
    let cand = [spc.ucl, spc.lcl, spc.mean, ...ys];
    if (spc.usl != null) cand.push(spc.usl);
    if (spc.lsl != null) cand.push(spc.lsl);
    cand = cand.filter(v => typeof v === "number" && isFinite(v));  // loại NaN/Infinity
    if (!cand.length) return '<div class="muted">Dữ liệu SPC không hợp lệ.</div>';
    let lo = Math.min(...cand), hi = Math.max(...cand);
    if (lo === hi) { lo -= 1; hi += 1; }
    const dy = (hi - lo) * 0.08; lo -= dy; hi += dy;
    const px = (i) => pad.l + (pts.length === 1 ? 0.5 : i / (pts.length - 1)) * (W - pad.l - pad.r);
    const py = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
    const hline = (v, color, dash, label) => v == null ? "" :
      `<line x1="${pad.l}" y1="${py(v).toFixed(1)}" x2="${W - pad.r}" y2="${py(v).toFixed(1)}" stroke="${color}" stroke-width="1" ${dash ? 'stroke-dasharray="5 4"' : ""}/>
       <text x="${W - pad.r}" y="${(py(v) - 3).toFixed(1)}" fill="${color}" font-size="10" text-anchor="end">${label} ${v.toFixed(2)}</text>`;
    const poly = pts.map((p, i) => `${px(i).toFixed(1)},${py(p.value).toFixed(1)}`).join(" ");
    const dots = pts.map((p, i) => {
      const bad = p.violations && p.violations.length;
      return `<circle cx="${px(i).toFixed(1)}" cy="${py(p.value).toFixed(1)}" r="${bad ? 4.5 : 3}" fill="${bad ? "#e74c3c" : "#3498db"}">
        <title>${esc(p.value)}${bad ? " — " + esc(p.violations.join("; ")) : ""}</title></circle>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
      ${hline(spc.usl, "#8a6d3b", true, "USL")}${hline(spc.lsl, "#8a6d3b", true, "LSL")}
      ${hline(spc.ucl, "#e74c3c", false, "UCL")}${hline(spc.lcl, "#e74c3c", false, "LCL")}
      ${hline(spc.mean, "#2ecc71", false, "CL")}
      <polyline points="${poly}" fill="none" stroke="#3498db" stroke-width="1.5"/>${dots}</svg>`;
  }

  // ======================================================================
  // #3 — CÔNG THỨC NÂNG CAO (yield + change-control + alternates)
  // ======================================================================
  VIEWS.recipeadv = async function () {
    const root = $("view-recipeadv");
    const [recipes, batches, changes] = await Promise.all([
      GET("/recipes"), GET("/batches"), GET("/recipes/changes").catch(() => [])]);
    root.innerHTML = `
      ${panel("🔧 Hiệu suất theo công đoạn (Yield)", `
        <div class="row"><div class="field"><label>Chọn mẻ</label>
          <select id="ry_batch">${opt(batches, b => b.batch_id, b => b.batch_code + " · " + b.state)}</select></div></div>
        <div id="ry_box" class="muted" style="margin-top:8px">Đang tải…</div>`)}
      ${panel("📑 Kiểm soát thay đổi công thức (change-control)", `
        <div class="tablewrap"><table><thead><tr><th>Mã thay đổi</th><th>Lý do</th><th>Trạng thái</th><th>Người duyệt</th><th>Thời điểm</th><th></th></tr></thead>
        <tbody>${changes.length ? changes.map((c, i) => `<tr>
          <td><code class="k">${esc(c.change_code)}</code></td><td>${esc(c.reason)}</td>
          <td>${badge(c.state === "approved" ? "available" : "planned")}${esc(c.state)}</td>
          <td>${esc(c.approved_by || "—")}</td><td class="muted">${fmt(c.approved_at)}</td>
          <td><button class="btn sm sec" data-diff="${i}">Xem diff</button></td></tr>`).join("")
          : '<tr><td colspan="6" class="muted">Chưa có thay đổi nào.</td></tr>'}</tbody></table></div>`)}
      ${panel("🧪 Ký duyệt thay đổi (e-signature, re-auth)", `
        <div class="muted" style="margin-bottom:6px">Chỉ version đang ở trạng thái <b>review</b> mới ký duyệt được (yêu cầu nhập lại mật khẩu + lý do).</div>
        <div id="rc_approve">Đang tải…</div>`)}
      ${panel("📦 Kiểm tra tồn & nguyên liệu thay thế", `
        <div class="row">
          <div class="field"><label>Công thức</label><select id="ra_recipe">${opt(recipes, r => r.recipe_id, r => r.code + " · " + r.name)}</select></div>
          <div class="field"><label>SL kế hoạch (L)</label><input id="ra_qty" value="50000" style="width:120px"/></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="ra_go">Kiểm tra</button></div>
        </div>
        <div id="ra_box" class="muted" style="margin-top:8px">Chọn công thức và bấm Kiểm tra.</div>`)}
    `;

    // --- Yield ---
    async function loadYield() {
      const bid = $("ry_batch").value;
      if (!bid) { $("ry_box").innerHTML = '<div class="muted">Chưa có mẻ nào.</div>'; return; }
      try {
        const y = await GET(`/batches/${bid}/yield`);
        const rows = (y.steps || []).map(s => `<tr>
          <td>${esc(s.label)}</td><td>${s.input_qty}</td><td>${s.output_qty}</td>
          <td>${s.step_pct}%</td><td class="muted">${s.expected_pct != null ? s.expected_pct + "%" : "—"}</td>
          <td>${s.cumulative_pct}%</td><td>${s.warn ? badge("critical") + "thấp" : badge("available") + "đạt"}</td></tr>`).join("");
        const chart = (y.steps && y.steps.length)
          ? CH.grouped(y.steps.map(s => ({ label: s.label, a: s.expected_pct || 0, b: s.step_pct })),
              { labelA: "Kỳ vọng %", labelB: "Thực tế %", height: 170 })
          : '<div class="muted">Chưa ghi hiệu suất công đoạn.</div>';
        $("ry_box").innerHTML = `
          <div class="split">
            <div>${chart}</div>
            <div><div class="tablewrap"><table><thead><tr><th>Công đoạn</th><th>Vào</th><th>Ra</th><th>HS</th><th>KV</th><th>Tích lũy</th><th></th></tr></thead>
              <tbody>${rows || '<tr><td colspan=7 class="muted">—</td></tr>'}</tbody></table></div>
            <div style="margin-top:8px">Hiệu suất tổng: <b>${y.overall_yield_pct ?? "—"}%</b> · Tổn thất: <b>${y.overall_loss_pct ?? "—"}%</b>
              · Kỳ vọng: ${y.expected_overall_pct ?? "—"}% ${y.warn ? badge("critical") + "có cảnh báo" : ""}</div></div>
          </div>
          <h3 style="margin-top:10px">Ghi hiệu suất công đoạn</h3>
          <div class="row">
            <div class="field"><label>Công đoạn</label><select id="ry_step">
              <option value="nau">Nấu</option><option value="len_men">Lên men</option>
              <option value="loc">Lọc</option><option value="chiet">Chiết</option></select></div>
            <div class="field"><label>Đầu vào</label><input id="ry_in" style="width:100px"/></div>
            <div class="field"><label>Đầu ra</label><input id="ry_out" style="width:100px"/></div>
            <div class="field" style="align-self:flex-end"><button class="btn" id="ry_save">Ghi</button></div>
          </div>`;
        $("ry_save").onclick = () => guard(async () => {
          await POST(`/batches/${bid}/yield`, { step_key: $("ry_step").value,
            input_qty: num("ry_in") || 0, output_qty: num("ry_out") || 0 });
          toast("Đã ghi hiệu suất"); loadYield();
        });
      } catch (e) { $("ry_box").innerHTML = `<div class="muted">Lỗi: ${esc(e.message)}</div>`; }
    }
    // Mặc định chọn mẻ đã có ghi nhận hiệu suất (mẻ closed) để demo.
    const yb = batches.find(b => b.state === "closed"); if (yb) $("ry_batch").value = yb.batch_id;
    $("ry_batch").onchange = loadYield;

    // --- diff modal ---
    document.querySelectorAll("[data-diff]").forEach(b => b.onclick = () => {
      const c = changes[+b.dataset.diff]; const d = c.diff || {};
      const mat = (d.materials || []).map(m => `<tr><td>${esc(m.material_code)}</td><td>${esc(m.type)}</td>
        <td>${esc(m.old_qty ?? "—")}</td><td>${esc(m.new_qty ?? "—")}</td></tr>`).join("");
      modal(`<h3>Diff: ${esc(c.change_code)}</h3>
        <div class="muted" style="margin-bottom:6px">${esc(c.reason)}</div>
        <table><thead><tr><th>Vật tư</th><th>Loại</th><th>ĐM cũ</th><th>ĐM mới</th></tr></thead>
        <tbody>${mat || '<tr><td colspan=4 class="muted">Không đổi định mức.</td></tr>'}</tbody></table>
        ${d.base_qty ? `<div style="margin-top:6px">base_qty: ${esc(d.base_qty.old)} → ${esc(d.base_qty.new)}</div>` : ""}`);
    });

    // --- approve (e-sign) list of review versions ---
    (async () => {
      let reviewVers = [];
      for (const r of recipes) {
        const vers = await GET(`/recipes/${r.recipe_id}/versions`).catch(() => []);
        vers.filter(v => v.state === "review").forEach(v => reviewVers.push({ ...v, code: r.code }));
      }
      if (!reviewVers.length) { $("rc_approve").innerHTML = '<div class="muted">Không có version nào đang chờ duyệt (review).</div>'; return; }
      $("rc_approve").innerHTML = `
        <div class="row">
          <div class="field"><label>Version (review)</label><select id="rc_ver">${opt(reviewVers, v => v.version_id, v => v.code + " v" + v.version_no)}</select></div>
          <div class="field"><label>Mật khẩu của bạn</label><input id="rc_pw" type="password"/></div>
        </div>
        <div class="field"><label>Lý do thay đổi (bắt buộc)</label><input id="rc_reason" style="width:100%"/></div>
        <button class="btn" id="rc_go" style="margin-top:8px">Ký duyệt</button>`;
      $("rc_go").onclick = () => guard(async () => {
        const r = await POST(`/recipes/versions/${$("rc_ver").value}/change-approve`,
          { password: $("rc_pw").value, change_reason: $("rc_reason").value });
        toast("Đã ký duyệt: " + r.change_code); render("recipeadv");
      });
    })();

    // --- alternates ---
    $("ra_go").onclick = () => guard(async () => {
      const rid = $("ra_recipe").value;
      const vers = await GET(`/recipes/${rid}/versions`);
      const eff = vers.find(v => v.state === "effective") || vers[vers.length - 1];
      if (!eff) { $("ra_box").innerHTML = '<div class="muted">Công thức chưa có version.</div>'; return; }
      const a = await GET(`/batches/availability-alt?recipe_version_id=${eff.version_id}&planned_qty=${num("ra_qty") || 0}`);
      $("ra_box").innerHTML = `<div class="tablewrap"><table>
        <thead><tr><th>Vật tư</th><th>Cần</th><th>Tồn</th><th>Trạng thái</th><th>Gợi ý thay thế</th></tr></thead>
        <tbody>${a.rows.map(r => `<tr><td>${esc(r.material_code)}</td><td>${r.required} ${esc(r.uom || "")}</td>
          <td>${r.available}</td><td>${r.ok ? badge("available") + "đủ" : badge("critical") + "thiếu " + r.short}</td>
          <td>${(r.alternates && r.alternates.length) ? r.alternates.map(s =>
            `${esc(s.material_code)} (×${s.factor}, cần ${s.need}, tồn ${s.available}) ${s.covers ? badge("available") + "đủ" : badge("obsolete") + "thiếu"}`).join("<br>")
            : '<span class="muted">—</span>'}</td></tr>`).join("")}</tbody></table></div>`;
    });

    loadYield();
  };

  // ======================================================================
  // #6 — CẤP LIỆU (dispense / backflush)
  // ======================================================================
  VIEWS.dispense = async function () {
    const root = $("view-dispense");
    const batches = await GET("/batches");
    const running = batches.find(b => b.state === "running") || batches[0];
    root.innerHTML = `
      ${panel("🚚 Cấp liệu cho mẻ", `
        <div class="row"><div class="field"><label>Mẻ</label>
          <select id="dp_batch">${opt(batches, b => b.batch_id, b => b.batch_code + " · " + b.state, running && running.batch_id)}</select></div></div>
        <div id="dp_bom" class="muted" style="margin-top:8px">Đang tải định mức…</div>
        <h3 style="margin-top:12px">Cấp 1 vật tư (tự chọn lô theo FEFO — hết hạn trước xuất trước)</h3>
        <div class="row">
          <div class="field"><label>Vật tư</label><select id="dp_mat"></select></div>
          <div class="field"><label>Số lượng</label><input id="dp_qty" style="width:110px"/></div>
          <div class="field" style="align-self:flex-end"><label style="display:flex;gap:4px;align-items:center"><input type="checkbox" id="dp_over"/> cho vượt ĐM</label></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="dp_go">Cấp liệu</button></div>
        </div>`)}
      ${panel("♻️ Backflush (tự khấu trừ theo định mức)", `
        <div class="row">
          <div class="field"><label>Sản lượng đã SX (L)</label><input id="bf_qty" value="48000" style="width:140px"/></div>
          <div class="field" style="align-self:flex-end"><button class="btn sec" id="bf_go">Chạy backflush</button></div>
        </div>
        <div class="muted" style="margin-top:6px">Khấu trừ NVL = định mức BOM × (SL/ base_qty), trừ phần đã tiêu thụ trước đó.</div>`)}
      ${panel("📜 Lịch sử cấp liệu", `<div id="dp_hist" class="muted">Đang tải…</div>`)}
    `;

    async function refresh() {
      const bid = $("dp_batch").value;
      if (!bid) { $("dp_bom").innerHTML = '<div class="muted">Chưa có mẻ nào để cấp liệu.</div>'; return; }
      const [bom, hist] = await Promise.all([
        GET(`/batches/${bid}/bom`), GET(`/dispense?batch_id=${bid}`)]);
      $("dp_bom").innerHTML = `<div class="tablewrap"><table>
        <thead><tr><th>Vật tư</th><th>Định mức</th><th>Thực tế</th><th>Chênh</th><th>Trạng thái</th></tr></thead>
        <tbody>${(bom.lines || []).map(l => `<tr><td>${esc(l.material_code)}</td><td>${l.planned} ${esc(l.uom || "")}</td>
          <td>${l.actual}</td><td>${l.diff}</td><td>${badge(l.status === "dat" ? "available" : l.status === "vuot" ? "critical" : "planned")}${esc(l.status)}</td></tr>`).join("")}</tbody></table></div>`;
      $("dp_mat").innerHTML = (bom.lines || []).map(l => `<option value="${esc(l.material_code)}">${esc(l.material_code)} (ĐM ${l.planned})</option>`).join("");
      $("dp_hist").innerHTML = hist.length ? hist.map(d => `<div style="margin-bottom:8px">
        <b>${esc(d.dispense_code)}</b> ${badge(d.mode === "backflush" ? "planned" : "available")}${esc(d.mode)} <span class="muted">${fmt(d.created_at)} · ${esc(d.created_by || "")}</span>
        <div class="muted">${d.lines.map(l => `${esc(l.material_code)}: ${l.quantity} ${esc(l.uom)} ${l.lot_code ? "(" + esc(l.lot_code) + ")" : ""}`).join(" · ") || "—"}</div></div>`).join("")
        : '<div class="muted">Chưa có phiếu cấp liệu.</div>';
    }
    $("dp_batch").onchange = refresh;
    $("dp_go").onclick = () => guard(async () => {
      const bid = $("dp_batch").value;
      await POST(`/dispense/${bid}`, { lines: [{ material_code: $("dp_mat").value, quantity: num("dp_qty") || 0, allow_over: $("dp_over").checked }] });
      toast("Đã cấp liệu"); $("dp_qty").value = ""; refresh();
    });
    $("bf_go").onclick = () => guard(async () => {
      const bid = $("dp_batch").value;
      const r = await POST(`/dispense/${bid}/backflush`, { produced_qty: num("bf_qty") || 0 });
      toast(`Backflush ${r.dispense_code}: ${r.lines.length} dòng` + (r.skipped.length ? `, ${r.skipped.length} bỏ qua` : "")); refresh();
    });
    refresh();
  };

  // ======================================================================
  // #7 — QC LAB (SPC / CAPA / COA / LIMS)
  // ======================================================================
  VIEWS.qclab = async function () {
    const root = $("view-qclab");
    const [params, capas, samples, batches] = await Promise.all([
      GET("/qc/parameters"), GET("/qc/capa"), GET("/qc/samples"), GET("/batches")]);
    root.innerHTML = `
      ${panel("📈 SPC — Biểu đồ kiểm soát", `
        <div class="row"><div class="field"><label>Chỉ tiêu</label>
          <select id="sp_param">${opt(params, p => p.name, p => p.name)}</select></div></div>
        <div id="sp_box" class="muted" style="margin-top:8px">Đang tải…</div>`)}
      ${panel("🛠️ CAPA — Hành động khắc phục/phòng ngừa", `
        <div class="row">
          <div class="field"><label>Tiêu đề</label><input id="ca_title" style="width:280px"/></div>
          <div class="field"><label>Loại</label><select id="ca_type"><option value="corrective">Khắc phục</option><option value="preventive">Phòng ngừa</option></select></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="ca_add">+ Mở CAPA</button></div>
        </div>
        <div class="tablewrap" style="margin-top:8px"><table><thead><tr><th>Mã</th><th>Tiêu đề</th><th>Loại</th><th>Trạng thái</th><th>Phụ trách</th><th></th></tr></thead>
        <tbody>${capas.map(c => `<tr><td><code class="k">${esc(c.capa_code)}</code></td><td>${esc(c.title)}</td>
          <td>${esc(c.capa_type)}</td><td>${badge(c.state === "closed" ? "available" : "planned")}${esc(c.state)}</td>
          <td>${esc(c.owner || "—")}</td><td><button class="btn sm sec" data-capa="${esc(c.capa_id)}">Chi tiết</button></td></tr>`).join("")}</tbody></table></div>`)}
      ${panel("📄 COA — Phiếu phân tích (Certificate of Analysis)", `
        <div class="row"><div class="field"><label>Mẻ</label><select id="co_batch">${opt(batches, b => b.batch_id, b => b.batch_code)}</select></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="co_go">Xuất COA</button></div></div>
        <div id="co_box" class="muted" style="margin-top:8px">Chọn mẻ và bấm Xuất COA.</div>`)}
      ${panel("🧫 LIMS — Phiếu mẫu", `
        <div class="row">
          <div class="field"><label>Mẻ</label><select id="sm_batch">${opt(batches, b => b.batch_id, b => b.batch_code)}</select></div>
          <div class="field"><label>Công đoạn</label><input id="sm_stage" placeholder="len_men" style="width:120px"/></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="sm_add">+ Đăng ký mẫu</button></div>
        </div>
        <div class="tablewrap" style="margin-top:8px"><table><thead><tr><th>Mã mẫu</th><th>Công đoạn</th><th>Trạng thái</th><th>KQ</th><th>Đăng ký</th><th></th></tr></thead>
        <tbody>${samples.map(s => `<tr><td><code class="k">${esc(s.sample_code)}</code></td><td>${esc(s.stage || "—")}</td>
          <td>${badge(s.status === "completed" ? "available" : "planned")}${esc(s.status)}</td><td>${s.result_count}</td>
          <td class="muted">${fmt(s.registered_at)}</td>
          <td>${s.status !== "completed" ? `<button class="btn sm sec" data-smp="${esc(s.sample_id)}" data-next="${s.status === "registered" ? "in_test" : "completed"}">${s.status === "registered" ? "Bắt đầu test" : "Hoàn thành"}</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`)}
    `;

    async function loadSPC() {
      try {
        const spc = await GET(`/qc/spc?parameter=${encodeURIComponent($("sp_param").value)}`);
        const cap = (spc.cp != null) ? `Cp <b>${spc.cp}</b> · Cpk <b>${spc.cpk}</b>` : "—";
        $("sp_box").innerHTML = controlChart(spc) +
          `<div style="margin-top:6px">n=${spc.n} · Mean ${spc.mean} · σ ${spc.sigma} · UCL ${spc.ucl} · LCL ${spc.lcl} · ${cap}
            · ${spc.in_control ? badge("available") + "trong kiểm soát" : badge("critical") + spc.out_of_control + " điểm vi phạm"}</div>`;
      } catch (e) { $("sp_box").innerHTML = `<div class="muted">Lỗi: ${esc(e.message)}</div>`; }
    }
    $("sp_param").onchange = loadSPC;
    // Mặc định chọn chỉ tiêu có dữ liệu SPC để demo trực quan.
    if ([...$("sp_param").options].some(o => o.value === "Độ đường (°P)")) $("sp_param").value = "Độ đường (°P)";
    $("ca_add").onclick = () => guard(async () => {
      await POST("/qc/capa", { title: $("ca_title").value, capa_type: $("ca_type").value });
      toast("Đã mở CAPA"); render("qclab");
    });
    document.querySelectorAll("[data-capa]").forEach(b => b.onclick = () => {
      const c = capas.find(x => x.capa_id === b.dataset.capa);
      const nexts = { open: "investigation", investigation: "action", action: "verification", verification: "closed" };
      const nx = nexts[c.state];
      modal(`<h3>${esc(c.capa_code)} — ${esc(c.title)}</h3>
        <div>Trạng thái: ${badge("planned")}${esc(c.state)}</div>
        <div class="field" style="margin-top:8px"><label>Nguyên nhân gốc</label><input id="cd_rc" value="${esc(c.root_cause || "")}"/></div>
        <div class="field" style="margin-top:8px"><label>Kế hoạch hành động</label><input id="cd_ap" value="${esc(c.action_plan || "")}"/></div>
        <div class="field" style="margin-top:8px"><label>Hiệu lực (verification)</label><input id="cd_ef" value="${esc(c.effectiveness || "")}"/></div>
        ${nx ? `<button class="btn" id="cd_go" style="margin-top:12px">Chuyển sang: ${nx}</button>` : '<div class="muted" style="margin-top:8px">Đã đóng.</div>'}`);
      if (nx) $("cd_go").onclick = () => guard(async () => {
        await POST(`/qc/capa/${c.capa_id}/transition`, { target: nx, root_cause: $("cd_rc").value,
          action_plan: $("cd_ap").value, effectiveness: $("cd_ef").value });
        closeModal(); toast("Đã cập nhật CAPA"); render("qclab");
      });
    });
    $("co_go").onclick = () => guard(async () => {
      const c = await GET(`/qc/coa/${$("co_batch").value}`);
      $("co_box").innerHTML = `
        <div><b>COA</b> · Mẻ ${esc(c.batch_code)} · CT v${c.version_no} · SL ${c.actual_qty ?? c.planned_qty} ${esc(c.uom)}
          · Kết luận: ${badge(c.overall_verdict === "PASS" ? "available" : c.overall_verdict.includes("FAIL") ? "critical" : "planned")}${esc(c.overall_verdict)}</div>
        <div class="tablewrap" style="margin-top:8px"><table><thead><tr><th>Chỉ tiêu</th><th>Giá trị</th><th>Giới hạn</th><th>KQ</th><th>Người</th></tr></thead>
        <tbody>${c.results.map(r => `<tr><td>${esc(r.parameter)}</td><td>${r.value ?? "—"} ${esc(r.unit || "")}</td>
          <td class="muted">${r.lower ?? "—"} … ${r.upper ?? "—"}</td><td>${badge(r.verdict === "pass" ? "available" : "critical")}${esc(r.verdict)}</td>
          <td class="muted">${esc(r.by || "—")}</td></tr>`).join("")}</tbody></table></div>
        ${c.missing_mandatory.length ? `<div style="margin-top:6px">${badge("critical")}Thiếu chỉ tiêu bắt buộc: ${c.missing_mandatory.map(esc).join(", ")}</div>` : ""}`;
    });
    $("sm_add").onclick = () => guard(async () => {
      await POST("/qc/samples", { scope_id: $("sm_batch").value, stage: $("sm_stage").value || null });
      toast("Đã đăng ký mẫu"); render("qclab");
    });
    document.querySelectorAll("[data-smp]").forEach(b => b.onclick = () => guard(async () => {
      await POST(`/qc/samples/${b.dataset.smp}/transition`, { target: b.dataset.next });
      toast("Đã cập nhật mẫu"); render("qclab");
    }));
    loadSPC();
  };

  // ======================================================================
  // #8 — OEE & DỪNG MÁY (reason-tree / Pareto / big losses / MTBF)
  // ======================================================================
  VIEWS.oee = async function () {
    const root = $("view-oee");
    const [oee, tree, pareto, losses, mtbf] = await Promise.all([
      GET("/oee"), GET("/downtime/reason-tree"), GET("/downtime/pareto"),
      GET("/downtime/big-losses"), GET("/downtime/mtbf")]);
    const donuts = oee.map(r => `<div class="panel" style="text-align:center">
      <h3>${esc(r.line)} · ca ${esc(r.shift)}</h3>${CH.donut(r.oee, { label: "OEE" })}
      <div class="muted" style="font-size:12px">A ${(r.availability * 100).toFixed(0)}% · P ${(r.performance * 100).toFixed(0)}% · Q ${(r.quality * 100).toFixed(0)}%</div></div>`).join("");
    const groups = Object.keys(tree);
    root.innerHTML = `
      ${panel("⚙️ OEE đóng gói", `<div class="split">${donuts || '<div class="muted">—</div>'}</div>`)}
      ${panel("⏱️ Ghi sự kiện dừng máy (reason-tree)", `
        <div class="row">
          <div class="field"><label>Line</label><input id="dt_line" value="Line-1 (chai)" style="width:140px"/></div>
          <div class="field"><label>Nhóm lý do</label><select id="dt_grp">${groups.map(g => `<option value="${g}">${esc(tree[g].label)}</option>`).join("")}</select></div>
          <div class="field"><label>Lý do</label><select id="dt_code"></select></div>
          <div class="field"><label>Phút</label><input id="dt_min" value="15" style="width:80px"/></div>
          <div class="field"><label>Ca</label><select id="dt_shift"><option>A</option><option>B</option><option>C</option></select></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="dt_go">Ghi</button></div>
        </div>`)}
      ${panel("📊 Pareto thời gian dừng theo lý do", `
        ${CH.vbars((pareto.items || []).map(i => ({ label: i.label, value: i.minutes })), { unit: "phút", color: "#e67e22" })}
        <div class="tablewrap" style="margin-top:8px"><table><thead><tr><th>Lý do</th><th>Phút</th><th>%</th><th>Tích lũy %</th><th>Số lần</th></tr></thead>
        <tbody>${(pareto.items || []).map(i => `<tr><td>${esc(i.label)}</td><td>${i.minutes}</td><td>${i.pct}%</td><td>${i.cum_pct}%</td><td>${i.count}</td></tr>`).join("")}</tbody></table></div>`)}
      ${panel("🥧 Phân rã 6 big losses", `<div class="split">
        <div>${CH.pie(Object.entries(losses.by_category).map(([k, v]) => ({ label: k, value: v })))}</div>
        <div>${CH.pie(Object.entries(losses.by_group).map(([k, v]) => ({ label: k, value: v })))}</div></div>`)}
      ${panel("🔧 MTBF / MTTR theo thiết bị", `
        <div class="muted" style="margin-bottom:6px">Cửa sổ ${mtbf.window_days} ngày.</div>
        <div class="tablewrap"><table><thead><tr><th>Thiết bị</th><th>Số lần hỏng</th><th>MTBF (giờ)</th><th>MTTR (phút)</th><th>Khả dụng</th><th>Dừng (phút)</th></tr></thead>
        <tbody>${(mtbf.equipment || []).map(e => `<tr><td>${esc(e.name)}</td><td>${e.failures}</td>
          <td>${e.mtbf_hours ?? "—"}</td><td>${e.mttr_min ?? "—"}</td><td>${e.availability_pct}%</td><td>${e.downtime_min}</td></tr>`).join("")}</tbody></table></div>`)}
    `;
    function fillCodes() {
      const g = $("dt_grp").value;
      $("dt_code").innerHTML = Object.entries(tree[g].reasons).map(([c, l]) => `<option value="${c}">${esc(l)}</option>`).join("");
    }
    $("dt_grp").onchange = fillCodes; fillCodes();
    $("dt_go").onclick = () => guard(async () => {
      await POST("/downtime", { line: $("dt_line").value, reason_group: $("dt_grp").value,
        reason_code: $("dt_code").value, minutes: num("dt_min") || 0, shift: $("dt_shift").value });
      toast("Đã ghi sự kiện dừng"); render("oee");
    });
  };

  // ======================================================================
  // #P3-1 — ISA-88 procedural (thực thi phase theo mẻ)
  // ======================================================================
  const PHASE_BADGE = { idle: "planned", running: "due", held: "critical", complete: "available", aborted: "obsolete" };
  VIEWS.isa88 = async function () {
    const root = $("view-isa88");
    const batches = await GET("/batches");
    const running = batches.find(b => b.state === "running") || batches[0];
    root.innerHTML = `
      ${panel("🏭 Thực thi thủ tục ISA-88", `
        <div class="row"><div class="field"><label>Mẻ</label>
          <select id="i8_batch">${opt(batches, b => b.batch_id, b => b.batch_code + " · " + b.state, running && running.batch_id)}</select></div></div>
        <div id="i8_box" class="muted" style="margin-top:8px">Đang tải…</div>`)}
    `;
    async function load() {
      const bid = $("i8_batch").value;
      if (!bid) { $("i8_box").innerHTML = '<div class="muted">Chưa có mẻ.</div>'; return; }
      const st = await GET(`/isa88/batch/${bid}`);
      const phaseRow = (up, op, p) => {
        const b = PHASE_BADGE[p.state] || "planned";
        const sp = (p.params || []).map(x => `${esc(x.name)}=${esc(x.setpoint)}${esc(x.unit || "")}`).join(", ");
        let btns = "";
        if (p.state === "idle") btns = `<button class="btn sm" data-act="start" data-up="${esc(up)}" data-op="${esc(op)}" data-ph="${esc(p.phase)}">Bắt đầu</button>`;
        else if (p.state === "running") btns = `<button class="btn sm" data-act="complete" data-run="${p.run_id}">Hoàn thành</button> <button class="btn sm sec" data-act="held" data-run="${p.run_id}">Giữ</button>`;
        else if (p.state === "held") btns = `<button class="btn sm" data-act="running" data-run="${p.run_id}">Tiếp</button> <button class="btn sm sec" data-act="aborted" data-run="${p.run_id}">Hủy</button>`;
        return `<tr><td style="padding-left:24px">${esc(p.phase)} ${p.duration_min ? `<span class="muted">(${p.duration_min}')</span>` : ""}</td>
          <td class="muted" style="font-size:12px">${sp || "—"}</td>
          <td>${badge(b)}${esc(p.state)}</td><td>${esc(p.operator || "")}</td><td>${btns}</td></tr>`;
      };
      const rows = st.unit_procedures.map(u => {
        const head = `<tr style="background:var(--panel2)"><td colspan="5"><b>▸ ${esc(u.unit_procedure)}</b>
          ${u.unit_class === "cip" ? badge("critical") + "CIP" : badge("available") + esc(u.unit_class || "")}</td></tr>`;
        const ops = u.operations.map(o =>
          `<tr><td colspan="5" style="padding-left:12px"><i>${esc(o.operation)}</i></td></tr>` +
          o.phases.map(p => phaseRow(u.unit_procedure, o.operation, p)).join("")).join("");
        return head + ops;
      }).join("");
      $("i8_box").innerHTML = `
        <div style="margin-bottom:8px">Tiến độ: <b>${st.completion_pct}%</b>
          (${st.phases_done}/${st.phases_total} phase) ${CH.donut(st.completion_pct / 100, { label: "phase", size: 96 })}</div>
        <div class="tablewrap"><table><thead><tr><th>Unit procedure / Operation / Phase</th><th>Setpoint</th><th>Trạng thái</th><th>Người</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div>`;
      const bid2 = bid;
      document.querySelectorAll("#i8_box [data-act]").forEach(btn => btn.onclick = () => guard(async () => {
        const act = btn.dataset.act;
        if (act === "start") {
          await POST(`/isa88/batch/${bid2}/start`, { up: btn.dataset.up, op: btn.dataset.op, phase: btn.dataset.ph });
        } else {
          await POST(`/isa88/phase/${btn.dataset.run}/transition`, { target: act });
        }
        toast("Đã cập nhật phase"); load();
      }));
    }
    $("i8_batch").onchange = load;
    load();
  };

  // ======================================================================
  // #P3-2 — Scheduling (Gantt theo tank + CIP + bảo trì)
  // ======================================================================
  function gantt(board) {
    const res = board.resources || [];
    const from = board.from ? new Date(board.from).getTime() : 0;
    const to = board.to ? new Date(board.to).getTime() : 0;
    if (!from || !to || to <= from) return '<div class="muted">Chưa có lịch. Bấm "Tự lập lịch".</div>';
    const W = 900, laneH = 30, padL = 92, padT = 26, H = padT + res.length * laneH + 8, span = to - from;
    const KIND = { production: "#3498db", cip: "#e67e22", maintenance: "#e74c3c" };
    const x = (t) => padL + (new Date(t).getTime() - from) / span * (W - padL - 12);
    let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block;background:var(--panel2);border-radius:8px">`;
    // vạch ngày
    const day = 86400000;
    for (let t = Math.ceil(from / day) * day; t <= to; t += day) {
      const xx = x(t);
      svg += `<line x1="${xx.toFixed(1)}" y1="${padT - 4}" x2="${xx.toFixed(1)}" y2="${H - 4}" stroke="#2b3a47" stroke-dasharray="2 3"/>
        <text x="${(xx + 2).toFixed(1)}" y="14" fill="#8aa0b2" font-size="9">${new Date(t).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" })}</text>`;
    }
    res.forEach((r, i) => {
      const y = padT + i * laneH;
      svg += `<text x="6" y="${y + 18}" fill="#cdd9e3" font-size="11">${esc(r)}</text>
        <line x1="${padL}" y1="${y + laneH - 1}" x2="${W - 12}" y2="${y + laneH - 1}" stroke="#2b3a47"/>`;
      (board.lanes[r] || []).forEach(s => {
        const x1 = x(s.start_at), w = Math.max(x(s.end_at) - x1, 3);
        const col = s.status === "material_short" ? "#c0392b" : (KIND[s.kind] || "#7f8c8d");
        const lbl = s.kind === "cip" ? "CIP" : s.kind === "maintenance" ? "BẢO TRÌ" : (s.wo_code || "");
        svg += `<rect x="${x1.toFixed(1)}" y="${y + 4}" width="${w.toFixed(1)}" height="${laneH - 9}" rx="3" fill="${col}">
          <title>${esc(r)} · ${esc(lbl)}${s.product ? " · " + esc(s.product) : ""} (${fmt(s.start_at)} → ${fmt(s.end_at)})${s.status === "material_short" ? " · THIẾU NVL" : ""}</title></rect>`;
        if (w > 34) svg += `<text x="${(x1 + 4).toFixed(1)}" y="${y + 18}" fill="#fff" font-size="9">${esc(lbl)}</text>`;
      });
    });
    return svg + "</svg>";
  }

  VIEWS.schedule = async function () {
    const root = $("view-schedule");
    const legend = `<span style="font-size:12px"><span style="color:#3498db">■</span> Sản xuất
      <span style="color:#e67e22">■</span> CIP <span style="color:#e74c3c">■</span> Bảo trì
      <span style="color:#c0392b">■</span> Thiếu NVL</span>`;
    root.innerHTML = `
      ${panel("🗓️ Lập lịch sản xuất (tank · CIP · bảo trì · vật tư)", `
        <div class="row" style="align-items:flex-end">
          <div class="field"><label>Số ngày</label><input id="sc_days" value="12" style="width:80px"/></div>
          <div><button class="btn" id="sc_auto">⚙️ Tự lập lịch tối ưu</button></div>
          <div style="margin-left:auto">${legend}</div>
        </div>
        <div id="sc_gantt" class="muted" style="margin-top:10px">Đang tải…</div>`)}
      ${panel("⚠️ Xung đột & cảnh báo", `<div id="sc_conf" class="muted">Đang tải…</div>`)}
    `;
    async function load() {
      const [b, c] = await Promise.all([GET("/schedule"), GET("/schedule/conflicts")]);
      $("sc_gantt").innerHTML = gantt(b);
      const ovl = c.overlaps.map(o => `<li>Chồng lịch trên <b>${esc(o.resource)}</b>: ${esc(o.a)} ↔ ${esc(o.b)}</li>`).join("");
      const sh = c.material_short.map(s => `<li>${esc(s.wo_code)} trên ${esc(s.resource)}: ${badge("critical")}thiếu NVL theo BOM</li>`).join("");
      $("sc_conf").innerHTML = (c.ok)
        ? `${badge("available")}Không có xung đột — lịch khả thi.`
        : `<ul style="margin:4px 0 0 18px">${ovl}${sh}</ul>`;
    }
    $("sc_auto").onclick = () => guard(async () => {
      const r = await POST("/schedule/auto", { days: num("sc_days") || 12 });
      toast(`Đã xếp ${r.placed} mẻ lên ${r.tanks} tank` + (r.shortages ? `, ${r.shortages} thiếu NVL` : ""));
      load();
    });
    load();
  };

  // ======================================================================
  // #P3-4 — WMS kho thành phẩm (pallet/case + barcode)
  // ======================================================================
  VIEWS.wms = async function () {
    const root = $("view-wms");
    const [locs, pals] = await Promise.all([GET("/wms/locations"), GET("/wms/pallets")]);
    const locOpt = locs.map(l => `<option value="${esc(l.loc_id)}">${esc(l.code)} (${l.used}/${l.capacity})</option>`).join("");
    root.innerHTML = `
      ${panel("📍 Vị trí kho thành phẩm", `
        <div class="tablewrap"><table><thead><tr><th>Mã</th><th>Tên</th><th>Khu</th><th>Loại</th><th>Sử dụng</th></tr></thead>
        <tbody>${locs.map(l => `<tr><td><code class="k">${esc(l.code)}</code></td><td>${esc(l.name)}</td>
          <td>${esc(l.zone || "")}</td><td>${esc(l.kind)}</td>
          <td>${l.used}/${l.capacity} ${l.used >= l.capacity ? badge("critical") + "đầy" : ""}</td></tr>`).join("")}</tbody></table></div>`)}
      ${panel("📦 Đóng pallet (tự sinh case + barcode)", `
        <div class="row">
          <div class="field"><label>Sản phẩm</label><input id="pl_prod" value="BIA-LAGER" style="width:120px"/></div>
          <div class="field"><label>Lô TP</label><input id="pl_lot" value="PKG-2406-0001" style="width:150px"/></div>
          <div class="field"><label>Số case</label><input id="pl_n" value="40" style="width:80px"/></div>
          <div class="field"><label>Lon/case</label><input id="pl_u" value="24" style="width:80px"/></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="pl_build">+ Đóng pallet</button></div>
        </div>`)}
      ${panel("🟦 Pallet", `<div id="pl_box" class="muted">Đang tải…</div>`)}
    `;
    function renderPallets(list) {
      $("pl_box").innerHTML = `<div class="tablewrap"><table>
        <thead><tr><th>Mã pallet</th><th>SP</th><th>Lô</th><th>Case</th><th>Lon</th><th>Trạng thái</th><th>Vị trí</th><th></th></tr></thead>
        <tbody>${list.map(p => `<tr>
          <td><code class="k">${esc(p.pallet_code)}</code></td><td>${esc(p.product || "")}</td><td>${esc(p.lot_code || "")}</td>
          <td>${p.case_count}</td><td>${p.total_units}</td>
          <td>${badge(p.status === "stored" ? "available" : p.status === "shipped" ? "obsolete" : "planned")}${esc(p.status)}</td>
          <td>${esc(p.location || "—")}</td>
          <td style="white-space:nowrap">
            ${p.status !== "shipped" ? `<select class="pl_loc" data-id="${esc(p.pallet_id)}" style="width:auto"><option value="">— vị trí —</option>${locOpt}</select>
              <button class="btn sm" data-putaway="${esc(p.pallet_id)}">Cất</button>
              <button class="btn sm sec" data-ship="${esc(p.pallet_id)}">Xuất</button>` : ""}
            <button class="btn sm sec" data-label="${esc(p.pallet_code)}">🖨️ Tem</button></td></tr>`).join("")}</tbody></table></div>`;
      document.querySelectorAll("[data-putaway]").forEach(b => b.onclick = () => guard(async () => {
        const sel = document.querySelector(`.pl_loc[data-id="${b.dataset.putaway}"]`);
        if (!sel.value) { toast("Chọn vị trí", "err"); return; }
        await POST(`/wms/pallets/${b.dataset.putaway}/putaway`, { loc_id: sel.value });
        toast("Đã cất pallet"); render("wms");
      }));
      document.querySelectorAll("[data-ship]").forEach(b => b.onclick = () => guard(async () => {
        await POST(`/wms/pallets/${b.dataset.ship}/ship`, {}); toast("Đã xuất pallet"); render("wms");
      }));
      document.querySelectorAll("[data-label]").forEach(b => b.onclick = () => {
        const svg = (typeof code39SVG === "function") ? code39SVG(b.dataset.label, { height: 70 })
          : `<div style="font-family:monospace">${esc(b.dataset.label)}</div>`;
        modal(`<h3>Tem pallet</h3><div style="text-align:center;padding:10px">${svg}</div>
          <button class="btn" onclick="window.print()">In</button>`);
      });
    }
    renderPallets(pals);
    $("pl_build").onclick = () => guard(async () => {
      await POST("/wms/pallets", { product: $("pl_prod").value, lot_code: $("pl_lot").value,
        case_count: num("pl_n") || 1, units_per_case: num("pl_u") || 24 });
      toast("Đã đóng pallet (kèm case + barcode)"); render("wms");
    });
  };
})();
