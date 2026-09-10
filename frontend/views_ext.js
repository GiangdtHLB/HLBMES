"use strict";
// ============================================================================
// Views mở rộng (phân hệ chiều sâu) — nạp SAU app.js, dùng chung helper toàn cục:
// GET/POST/PUT, $, esc, badge, fmt, toast, guard, modal, closeModal, CH, render,
// CURRENT_USER. Đăng ký vào VIEWS + ALL_VIEWS toàn cục.
//   recipeadv (#3) · dispense (#6) · qclab (#7) · oee (#8)
// ============================================================================
(function () {
  ["recipeadv", "dispense", "qclab", "oee", "isa88", "schedule", "wms", "packaging", "cip"].forEach(v => { if (!ALL_VIEWS.includes(v)) ALL_VIEWS.push(v); });

  const num = (id) => { const x = $(id).value; return x === "" ? null : parseFloat(x); };
  const opt = (arr, val, lab, sel) => arr.map(o =>
    `<option value="${esc(val(o))}" ${String(val(o)) === String(sel) ? "selected" : ""}>${esc(lab(o))}</option>`).join("");
  const panel = (title, body) => `<div class="panel"><h2>${title}</h2>${body}</div>`;

  // Tem mã vạch: chọn Code39 (render client) hoặc QR (segno từ /api/label/qr) + in.
  function labelModal(code) {
    const c39 = (typeof code39SVG === "function") ? code39SVG(code, { height: 70 })
      : `<div style="font-family:monospace">${esc(code)}</div>`;
    modal(`<h3>Tem: ${esc(code)}</h3>
      <div class="row" style="margin-bottom:8px">
        <button class="btn sm" id="lb_c39">Code39</button>
        <button class="btn sm sec" id="lb_qr">QR code</button>
        <button class="btn sm sec" id="lb_print" style="margin-left:auto">🖨️ In</button></div>
      <div id="lb_view" style="text-align:center;padding:12px;background:#fff;border-radius:8px;min-height:90px">${c39}</div>`);
    $("lb_c39").onclick = () => { $("lb_view").innerHTML = c39; };
    $("lb_qr").onclick = () => guard(async () => {
      const r = await fetch("/api/label/qr?data=" + encodeURIComponent(code) + "&scale=5",
        { headers: { "Authorization": "Bearer " + TOKEN } });
      if (!r.ok) { toast("Lỗi sinh QR", "err"); return; }
      $("lb_view").innerHTML = await r.text();
    });
    $("lb_print").onclick = () => window.print();
  }

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
        <input class="searchbox" data-tbl="t_recipechanges" placeholder="Tìm theo mã thay đổi, lý do, trạng thái, người duyệt..."/>
        <div class="tablewrap"><table id="t_recipechanges"><thead><tr><th>Mã thay đổi</th><th>Lý do</th><th>Trạng thái</th><th>Người duyệt</th><th>Thời điểm</th><th></th></tr></thead>
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
    wireSearch(); wirePaginate("t_recipechanges", 10);

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
        <div class="row">
          <div class="field"><label>Mẻ (bấm để chọn)</label>
            <input type="text" id="dp_batch_txt" readonly autocomplete="off" placeholder="Chưa chọn mẻ — bấm để chọn"
              value="${running ? esc(running.batch_code + " · " + running.state) : ""}" style="cursor:pointer"/>
            <input type="hidden" id="dp_batch" value="${running ? esc(running.batch_id) : ""}"/></div>
          <div class="field"><label>Hoặc gõ mã mẻ để tìm</label>
            <input type="text" id="dp_batch_search" autocomplete="off" placeholder="Nhập mã mẻ..."/></div>
        </div>
        <div id="dp_bom" class="muted" style="margin-top:8px">Đang tải định mức…</div>
        <h3 style="margin-top:12px">Cấp 1 vật tư (tự chọn lô theo FEFO — hết hạn trước xuất trước)</h3>
        <div class="row">
          <div class="field"><label>Vật tư</label><select id="dp_mat"></select></div>
          <div class="field"><label>Số lượng</label><input id="dp_qty" style="width:110px"/></div>
          <div class="field" style="align-self:flex-end"><label style="display:flex;gap:4px;align-items:center"><input type="checkbox" id="dp_over"/> cho vượt ĐM</label></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="dp_go">Cấp liệu</button></div>
        </div>`)}
      ${panel("💡 Gợi ý cấp liệu (tự động, FEFO — Kho phân xưởng)", `
        <div class="muted" style="margin-bottom:8px">Tính vật tư còn thiếu theo Định mức (BOM) của mẻ, tự chọn lô theo FEFO ở Kho phân xưởng — chỉ xem trước, chưa trừ tồn.</div>
        <div class="row"><div class="field" style="align-self:flex-end"><button class="btn sec" id="sg_go">Xem gợi ý</button></div></div>
        <div id="sg_result" class="muted" style="margin-top:8px">Bấm "Xem gợi ý" để xem vật tư còn thiếu và lô sẽ dùng.</div>`)}
      ${panel("♻️ Backflush (tự khấu trừ theo định mức)", `
        <div class="muted">⚠ Tính năng này tạm thời tắt.</div>`)}
      ${panel("📜 Lịch sử cấp liệu", `<div id="dp_hist" class="muted">Đang tải…</div>`)}
    `;

    async function refresh() {
      const bid = $("dp_batch").value;
      if (!bid) { $("dp_bom").innerHTML = '<div class="muted">Chưa có mẻ nào để cấp liệu.</div>'; return; }
      const [batch, bom, hist, summary] = await Promise.all([
        GET(`/batches/${bid}`), GET(`/batches/${bid}/bom`), GET(`/dispense?batch_id=${bid}`),
        GET(`/dispense/${bid}/summary`)]);
      const canEdit = !batch.ebr_locked;
      // Bảng đối chiếu tách THEO MÃ VẬT TƯ THẬT đã cấp (không gộp theo mã Nhóm vật tư thay thế
      // như bom.lines — xem services/dispense.py::batch_dispense_summary), kèm mã lô + có đúng
      // FIFO không. CHỈ hiện vật tư ĐÃ thực sự cấp — không tự liệt kê sẵn toàn bộ định mức công
      // thức khi chưa cấp gì, để người dùng tự chủ động cấp qua "Gợi ý cấp liệu"/"Cấp 1 vật tư"
      // bên dưới thay vì bị gợi ý sẵn (theo yêu cầu người dùng).
      $("dp_bom").innerHTML = summary.length ? `<div class="tablewrap"><table>
        <thead><tr><th>Vật tư</th><th>Mã lô</th><th>FIFO?</th><th>Định mức</th><th>Thực tế</th><th>Chênh</th><th>Trạng thái</th><th></th></tr></thead>
        <tbody>${summary.map(l => `<tr data-bomrow="${esc(l.material_code)}">
          <td>${esc(l.material_code)}${l.material_name ? ` ${esc(l.material_name)}` : ""}</td>
          <td>${esc((l.lot_codes || []).join(", ") || "—")}</td>
          <td>${l.fifo_ok === false ? '<span style="color:var(--red)">⚠ khác FIFO</span>' : '<span style="color:var(--green)">✔ FIFO</span>'}</td>
          <td>${l.planned != null ? l.planned + " " + esc(l.uom || "") : ""}</td>
          <td class="bom-actual">${l.actual}</td><td>${l.diff != null ? l.diff : ""}</td>
          <td>${l.status != null ? badge(l.status === "dat" ? "available" : l.status === "vuot" ? "critical" : "planned") + esc(l.status) : ""}</td>
          <td>${canEdit ? `<button class="btn sm sec" data-bomedit="${esc(l.material_code)}">Sửa</button>
            <button class="btn sm sec" data-bomdel="${esc(l.material_code)}" style="color:var(--red)">Xóa</button>` : ""}</td></tr>`).join("")}</tbody></table></div>
        <div class="muted" style="margin-top:6px">${canEdit ? "" : "Hồ sơ mẻ (EBR) đã khóa — không thể sửa Thực tế."}</div>`
        : '<div class="muted">Chưa cấp vật tư nào cho mẻ này — dùng "Gợi ý cấp liệu" hoặc "Cấp 1 vật tư" bên dưới.</div>';
      $("dp_mat").innerHTML = (bom.lines || []).map(l => `<option value="${esc(l.material_code)}">${esc(l.material_code)}${l.material_name ? " — " + esc(l.material_name) : ""} (ĐM ${l.planned})</option>`).join("");
      // Mỗi phiếu cấp liệu (Dispense) — dp_go ("Cấp 1 vật tư") và sg_apply ("Áp dụng gợi ý")
      // đều gọi CHUNG endpoint POST /dispense/{bid} nên chỉ phân biệt được nguồn gốc qua `note`
      // ("Cấp tự do"/"Cấp theo gợi ý (FEFO)") — luôn hiện `note` rõ ràng, kèm dịch `mode` sang
      // tiếng Việt và nhãn "Vật tư đã cấp" cho dòng chi tiết bên dưới (yêu cầu người dùng
      // 2026-09-05: "Lịch sử cấp liệu không rõ là gì").
      const DISPENSE_MODE_LABEL = { dispense: "Cấp liệu", backflush: "Backflush (tự động theo định mức)", adjust: "Sửa Thực tế" };
      $("dp_hist").innerHTML = hist.length ? hist.map(d => `<div style="margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid var(--border)">
        <div><b>${esc(d.dispense_code)}</b> ${badge(d.mode === "backflush" ? "planned" : d.mode === "adjust" ? "critical" : "available")}${esc(DISPENSE_MODE_LABEL[d.mode] || d.mode)}
          <span class="muted">— ${fmt(d.created_at)} · ${esc(d.created_by || "")}</span></div>
        ${d.note ? `<div style="margin-top:2px">${esc(d.note)}</div>` : ""}
        <div class="muted" style="margin-top:2px">Vật tư đã cấp: ${d.lines.map(l => `${esc(l.material_code)}: ${l.quantity} ${esc(l.uom)}${l.lot_code ? " (lô " + esc(l.lot_code) + ")" : ""}${l.fifo_ok === false ? " ⚠ khác FIFO" : ""}${l.reason ? " — " + esc(l.reason) : ""}`).join(" · ") || "không có dòng nào"}</div></div>`).join("")
        : '<div class="muted">Chưa có phiếu cấp liệu nào cho mẻ này.</div>';
      document.querySelectorAll("[data-bomedit]").forEach(btn => btn.onclick = () => {
        const code = btn.dataset.bomedit;
        const row = document.querySelector(`[data-bomrow="${CSS.escape(code)}"]`);
        const actualCell = row.querySelector(".bom-actual");
        const current = actualCell.textContent.trim();
        actualCell.innerHTML = `<input type="number" class="bom-actual-input" value="${esc(current)}" style="width:90px"/>
          <input class="bom-reason-input" placeholder="Lý do sửa (bắt buộc)" style="width:200px;margin-top:4px;display:block"/>
          <button class="btn sm" data-bomsave="${esc(code)}" style="margin-top:4px">Lưu</button>
          <button class="btn sm sec" data-bomcancel style="margin-top:4px">Hủy</button>`;
        row.querySelector("[data-bomcancel]").onclick = refresh;
        row.querySelector("[data-bomsave]").onclick = () => guard(async () => {
          const newActual = parseFloat(row.querySelector(".bom-actual-input").value);
          const reason = row.querySelector(".bom-reason-input").value.trim();
          if (!Number.isFinite(newActual)) throw new Error("Nhập số Thực tế hợp lệ.");
          if (!reason) throw new Error("Bắt buộc nhập lý do khi sửa Thực tế.");
          await POST(`/dispense/${bid}/adjust`, { material_code: code, new_actual: newActual, reason });
          toast("Đã sửa Thực tế"); refresh();
        });
      });
      document.querySelectorAll("[data-bomdel]").forEach(btn => btn.onclick = () => guard(async () => {
        const code = btn.dataset.bomdel;
        if (!confirm(`Xóa toàn bộ Thực tế đã cấp cho "${code}"? Sẽ hoàn lại lô/tồn kho tương ứng.`)) return;
        const reason = prompt("Lý do xóa (bắt buộc):", "Cấp nhầm / không dùng");
        if (reason === null) return;
        if (!reason.trim()) throw new Error("Bắt buộc nhập lý do khi xóa.");
        await POST(`/dispense/${bid}/adjust`, { material_code: code, new_actual: 0, reason: reason.trim() });
        toast("Đã xóa dòng cấp liệu"); refresh();
      }));
    }
    // 2 cách chọn mẻ (yêu cầu người dùng 2026-09-06): (1) bấm thẳng vào ô "Mẻ" — mở popup duyệt
    // toàn bộ danh sách qua openSearchPickerModal; (2) gõ mã mẻ vào ô tìm riêng bên cạnh — gợi ý
    // hiện ngay dưới ô đó (wireSearchableSelect), chọn xong tự điền lại vào ô "Mẻ" bên trái +
    // xóa ô tìm để gõ lần sau.
    const batchItems = (batches || []).map(b => ({ value: b.batch_id, label: b.batch_code + " · " + b.state }));
    const onBatchPicked = (item) => {
      $("dp_batch").value = item.value; $("dp_batch_txt").value = item.label;
      $("dp_batch_search").value = "";
      $("sg_result").innerHTML = 'Bấm "Xem gợi ý" để xem vật tư còn thiếu và lô sẽ dùng.'; refresh();
    };
    $("dp_batch_txt").onclick = () => openSearchPickerModal("Chọn mẻ", batchItems, onBatchPicked);
    wireSearchableSelect("dp_batch_search", "dp_batch", batchItems, onBatchPicked);
    $("dp_go").onclick = () => guard(async () => {
      const bid = $("dp_batch").value;
      await POST(`/dispense/${bid}`, { lines: [{ material_code: $("dp_mat").value, quantity: num("dp_qty") || 0, allow_over: $("dp_over").checked }],
        note: "Cấp tự do" });
      toast("Đã cấp liệu"); $("dp_qty").value = ""; refresh();
    });
    $("sg_go").onclick = () => guard(async () => {
      const bid = $("dp_batch").value;
      const sug = await GET(`/dispense/${bid}/suggest`);
      if (!sug.lines.length) {
        $("sg_result").innerHTML = '<div class="muted">Đã đủ định mức — không còn vật tư nào cần cấp thêm.</div>';
        return;
      }
      const rows = [];
      sug.lines.forEach((l, li) => {
        const statusCell = l.shortfall > 0
          ? `<span style="color:var(--red)">thiếu ${l.shortfall} ${esc(l.uom || "")}</span>`
          : '<span style="color:var(--green)">đủ</span>';
        const matLabel = l.material_name ? `${esc(l.material_code)} ${esc(l.material_name)}` : esc(l.material_code);
        const stockCells = `<td>${l.stock_company} ${esc(l.uom || "")}</td><td>${l.stock_workshop} ${esc(l.uom || "")}</td>`;
        if (!l.picks.length && !l.alternatives.length) {
          // Không có lô nào của vật tư này (kể cả tự chọn tay) — thật sự không có gì để cấp.
          rows.push(`<tr>
            <td>${matLabel}</td>${stockCells}<td>${l.planned} ${esc(l.uom || "")}</td><td>${l.need} ${esc(l.uom || "")}</td>
            <td colspan="4" class="muted">Không có lô khả dụng (Kho phân xưởng)</td>
            <td>${statusCell}</td></tr>`);
          return;
        }
        const altOpts = l.alternatives.map(a =>
          `<option value="${a.lot_id}">${esc(a.lot_code)} (còn ${a.quantity}${a.expiry ? ", HSD " + fmt(a.expiry) : ""})</option>`).join("");
        // Nếu gợi ý tự động không phân bổ gì cho vật tư này (VD 1 vật tư khác trong CÙNG nhóm
        // đã đủ đáp ứng qua FIFO) nhưng vẫn có lô khả dụng — vẫn hiện dòng này (không ẩn), NHƯNG
        // làm mờ + khóa nhập nếu nhóm ĐÃ đủ tồn qua thành viên khác rồi (không cần lấy thêm mã
        // này nữa, tránh người dùng lỡ nhập cộng thêm vượt định mức chung của nhóm).
        const isRedundantGroupMember = !!l.group_code && l.picks.length === 0 && l.shortfall === 0;
        const rowPicks = l.picks.length ? l.picks
          : [{ lot_id: l.alternatives[0].lot_id, lot_code: l.alternatives[0].lot_code, quantity: 0, uom: l.uom }];
        rowPicks.forEach((p, pi) => {
          rows.push(`<tr${isRedundantGroupMember ? ' style="opacity:.5"' : ""}>
            <td>${pi === 0 ? matLabel : ""}</td>
            ${pi === 0 ? stockCells : "<td></td><td></td>"}
            <td>${pi === 0 ? l.planned + " " + esc(l.uom || "") : ""}</td>
            <td>${pi === 0 ? l.need + " " + esc(l.uom || "") : ""}</td>
            <td><input type="number" class="sg-qty" data-li="${li}" data-pi="${pi}" value="${p.quantity}" style="width:80px"${isRedundantGroupMember ? " disabled" : ""}/></td>
            <td><select class="sg-lot" data-li="${li}" data-pi="${pi}" data-orig="${p.lot_id}"${isRedundantGroupMember ? " disabled" : ""}>${altOpts}</select></td>
            <td class="sg-fifo" data-li="${li}" data-pi="${pi}"></td>
            <td><input class="sg-note" data-li="${li}" data-pi="${pi}" placeholder="Bắt buộc nếu chọn khác FIFO" style="width:170px;display:none"/></td>
            <td>${pi === 0 ? (isRedundantGroupMember ? '<span class="muted">nhóm đã đủ</span>' : statusCell) : ""}</td>
          </tr>`);
        });
      });
      $("sg_result").innerHTML = `<div class="tablewrap"><table>
        <thead><tr><th>Vật tư</th><th>Tồn kho công ty</th><th>Tồn kho phân xưởng</th><th>Định mức</th><th>Còn thiếu</th><th>SL thực tế</th><th>Lô sẽ dùng</th><th>FIFO?</th><th>Ghi chú (nếu khác FIFO)</th><th>Tình trạng</th></tr></thead>
        <tbody>${rows.join("")}</tbody></table></div>
        <div class="row" style="margin-top:8px;align-items:center">
          <button class="btn" id="sg_apply">✔ Áp dụng gợi ý</button>
          <label style="display:flex;gap:4px;align-items:center"><input type="checkbox" id="sg_over"/> cho phép cấp vượt định mức</label>
        </div>`;
      document.querySelectorAll(".sg-lot").forEach(sel => {
        sel.value = sel.dataset.orig;
        const updateFifo = () => {
          const noteInput = document.querySelector(`.sg-note[data-li="${sel.dataset.li}"][data-pi="${sel.dataset.pi}"]`);
          const fifoCell = document.querySelector(`.sg-fifo[data-li="${sel.dataset.li}"][data-pi="${sel.dataset.pi}"]`);
          const isFifo = sel.value === sel.dataset.orig;
          fifoCell.innerHTML = isFifo ? '<span style="color:var(--green)">✔ FIFO</span>' : '<span style="color:var(--red)">⚠ khác FIFO</span>';
          noteInput.style.display = isFifo ? "none" : "";
          if (isFifo) noteInput.value = "";
        };
        sel.onchange = updateFifo;
        updateFifo();
      });
      $("sg_apply").onclick = () => guard(async () => {
        if (sug.lines.some(l => l.shortfall > 0)) {
          toast("Còn vật tư thiếu tồn kho — bổ sung đủ tồn trước khi áp dụng cấp liệu", "err");
          return;
        }
        const lotSels = Array.from(document.querySelectorAll(".sg-lot"));
        for (const sel of lotSels) {
          if (sel.value !== sel.dataset.orig) {
            const note = document.querySelector(`.sg-note[data-li="${sel.dataset.li}"][data-pi="${sel.dataset.pi}"]`).value.trim();
            if (!note) { toast("Chọn lô khác FIFO phải nhập ghi chú lý do", "err"); sel.focus(); return; }
          }
        }
        const lines = lotSels.map(sel => {
          const qty = parseFloat(document.querySelector(`.sg-qty[data-li="${sel.dataset.li}"][data-pi="${sel.dataset.pi}"]`).value) || 0;
          const note = document.querySelector(`.sg-note[data-li="${sel.dataset.li}"][data-pi="${sel.dataset.pi}"]`).value.trim();
          return { material_code: sug.lines[sel.dataset.li].material_code, lot_id: sel.value, quantity: qty, reason: note || null,
                  allow_over: $("sg_over").checked };
        }).filter(l => l.quantity > 0);
        if (!lines.length) { toast("Không có dòng nào để áp dụng", "err"); return; }
        await POST(`/dispense/${bid}`, { lines, note: "Cấp theo gợi ý (FEFO)" });
        toast("Đã áp dụng gợi ý cấp liệu");
        $("sg_result").innerHTML = 'Bấm "Xem gợi ý" để xem vật tư còn thiếu và lô sẽ dùng.';
        refresh();
      });
    });
    // Backflush tạm thời tắt (yêu cầu người dùng 2026-09-01) — bỏ HTML nút/ô nhập ở trên nhưng
    // giữ nguyên hàm xử lý, chỉ gắn khi nút còn tồn tại, để bật lại dễ dàng.
    if ($("bf_go")) $("bf_go").onclick = () => guard(async () => {
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
    const [params, capas, samples, batches, devs, lots, brewBatches, fermentsData, filtersData, bottlesData] = await Promise.all([
      GET("/qc/parameters"), GET("/qc/capa"), GET("/qc/samples"), GET("/batches"),
      GET("/quality/deviations").catch(() => []), GET("/lots").catch(() => []),
      GET("/brewing/brew-batches").catch(() => []),
      GET("/brewing/ferments").catch(() => ({ items: [] })),
      GET("/brewing/filters").catch(() => []),
      GET("/brewing/bottles").catch(() => [])]);
    const devById = Object.fromEntries(devs.map(d => [d.deviation_id, d]));
    const openDevOpts = devs.filter(d => d.state !== "closed")
      .map(d => `<option value="${esc(d.deviation_id)}" data-scope="${esc(d.scope_type)}:${esc(d.scope_id)}">${esc(d.deviation_code)} — ${badge(d.severity)}${esc(d.reason)}</option>`).join("");
    // Phạm vi CAPA (lô NVL/mẻ nấu/lô LM/mẻ lọc/mã chiết/mẻ SX) — CHỌN TRỰC TIẾP lúc mở CAPA,
    // không phụ thuộc Deviation liên kết (mirror cơ chế "Phạm vi (theo công đoạn)" ở
    // VIEWS.quality, nhưng không cần optgroup FAIL/OK — chỉ cần liệt kê để chọn).
    const ferments = fermentsData.items || [];
    const batchById = Object.fromEntries(batches.map(b => [b.batch_id, b]));
    const lotById = Object.fromEntries(lots.map(l => [l.lot_id, l]));
    const fermentById = Object.fromEntries(ferments.map(f => [f.ferment_id, f]));
    const filterById = Object.fromEntries(filtersData.map(f => [f.filter_id, f]));
    const bottleById = Object.fromEntries(bottlesData.map(b => [b.bottle_id, b]));
    const brewBatchByKey = {};
    brewBatches.forEach(r => {
      const info = { batch_code: r.batch_code, brew_id: r.brew_id, brew_code: r.brew_code };
      brewBatchByKey[r.batch_id] = info;
      brewBatchByKey[r.batch_code] = info;
    });
    const capaScopeLabel = (scopeType, scopeId) => {
      if (!scopeType || !scopeId) return null;
      if (scopeType === "batch") return `Mẻ SX ${batchById[scopeId] ? esc(batchById[scopeId].batch_code) : scopeId}`;
      if (scopeType === "lot") return `Lô NVL ${lotById[scopeId] ? esc(lotById[scopeId].lot_code) : scopeId}`;
      if (scopeType === "brew_batch") { const b = brewBatchByKey[scopeId];
        return b ? `Mẻ nấu ${esc(b.batch_code)} (mã nấu ${esc(b.brew_code || "?")})` : `Mẻ nấu ${scopeId}`; }
      if (scopeType === "ferment") return `Lô LM ${fermentById[scopeId] ? esc(fermentById[scopeId].lm_code) : scopeId}`;
      if (scopeType === "filter") return `Mẻ lọc ${filterById[scopeId] ? esc(filterById[scopeId].filter_code) : scopeId}`;
      if (scopeType === "bottle") return `Mã chiết ${bottleById[scopeId] ? esc(bottleById[scopeId].bottle_code) : scopeId}`;
      return `${esc(scopeType)} ${scopeId}`;
    };
    const capaScopeStages = [
      { tag: "Mẻ SX", items: batches, keyFn: b => `batch:${b.batch_id}`, optFn: b => `mẻ ${esc(b.batch_code)}` },
      { tag: "Nấu", items: brewBatches, keyFn: b => `brew_batch:${b.batch_id}`,
        optFn: b => `mẻ ${esc(b.batch_code)} (mã nấu ${esc(b.brew_code || "?")})` },
      { tag: "Lên men", items: ferments, keyFn: f => `ferment:${f.ferment_id}`, optFn: f => `lô LM ${esc(f.lm_code)}` },
      { tag: "Lọc", items: filtersData, keyFn: f => `filter:${f.filter_id}`, optFn: f => `mẻ lọc ${esc(f.filter_code)}` },
      { tag: "Chiết", items: bottlesData, keyFn: b => `bottle:${b.bottle_id}`, optFn: b => `mã chiết ${esc(b.bottle_code)}` },
      { tag: "NVL", items: lots, keyFn: l => `lot:${l.lot_id}`, optFn: l => `lô ${esc(l.lot_code)}` },
    ];
    const capaScopeOpts = `<option value="">— Không chọn —</option>` + capaScopeStages.flatMap(({ tag, items, keyFn, optFn }) =>
      items.map(item => `<option value="${keyFn(item)}">[${tag}] ${optFn(item)}</option>`)).join("");
    // Nhãn tiếng Việt cho từng giai đoạn CAPA (khớp CAPA_TRANSITIONS backend, services/quality_adv.py) —
    // khai báo trước root.innerHTML vì bảng danh sách CAPA bên dưới cũng cần dùng.
    const CAPA_PHASE_LABEL = { open: "Mở CAPA", investigation: "Điều tra nguyên nhân gốc",
      action: "Kế hoạch hành động", verification: "Xác nhận hiệu lực",
      kcs_approval: "Chờ duyệt — Trưởng phòng KCS", director_approval: "Chờ duyệt — Giám đốc/Phó GĐ SX-KT",
      closed: "Đã đóng" };
    root.innerHTML = `
      ${panel("📈 SPC — Biểu đồ kiểm soát", `
        <div class="row"><div class="field"><label>Chỉ tiêu</label>
          <select id="sp_param">${opt(params, p => p.name, p => p.name)}</select></div></div>
        <div id="sp_box" class="muted" style="margin-top:8px">Đang tải…</div>`)}
      ${panel("🛠️ CAPA — Hành động khắc phục/phòng ngừa", `
        <div class="row">
          <div class="field"><label>Tiêu đề</label><input id="ca_title" style="width:280px"/></div>
          <div class="field"><label>Loại</label><select id="ca_type"><option value="corrective">Khắc phục</option><option value="preventive">Phòng ngừa</option></select></div>
          <div class="field"><label>Liên kết Deviation</label><select id="ca_dev"><option value="">— Không liên kết —</option>${openDevOpts}</select></div>
          <div class="field"><label>Hạn xử lý</label><input id="ca_due" type="date"/></div>
        </div>
        <div class="row">
          <div class="field" style="flex:1"><label>Phạm vi (lô/mẻ/công đoạn liên quan)</label>
            <input id="ca_scope_q" placeholder="Tìm nhanh (gõ mã lô/mẻ)..." style="margin-bottom:2px"/>
            <select id="ca_scope">${capaScopeOpts}</select></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="ca_add">+ Mở CAPA</button></div>
        </div>
        <input class="searchbox" data-tbl="t_capa" placeholder="Tìm theo mã, tiêu đề, loại, trạng thái, phụ trách..."/>
        <div class="tablewrap" style="margin-top:8px"><table id="t_capa"><thead><tr><th>Mã</th><th>Tiêu đề</th><th>Phạm vi</th><th>Loại</th><th>Deviation liên kết</th><th>Hạn xử lý</th><th>Trạng thái</th><th>Phụ trách</th><th></th></tr></thead>
        <tbody>${capas.map(c => `<tr><td><code class="k">${esc(c.capa_code)}</code></td><td>${esc(c.title)}</td>
          <td class="muted">${capaScopeLabel(c.scope_type, c.scope_id) || "—"}</td>
          <td>${esc(c.capa_type)}</td><td>${c.deviation_id && devById[c.deviation_id]
            ? `<button class="btn sm sec" data-opendev="${esc(c.deviation_id)}">${esc(devById[c.deviation_id].deviation_code)}</button>`
            : `<span class="muted">—</span>`}</td>
          <td class="muted">${c.due_date ? esc(c.due_date) : "—"}</td>
          <td><span class="badge ${["kcs_approval", "director_approval"].includes(c.state) ? "due" : c.state === "closed" ? "available" : "planned"}">${esc(CAPA_PHASE_LABEL[c.state] || c.state)}</span></td>
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
        <input class="searchbox" data-tbl="t_samples" placeholder="Tìm theo mã mẫu, công đoạn, trạng thái..."/>
        <div class="tablewrap" style="margin-top:8px"><table id="t_samples"><thead><tr><th>Mã mẫu</th><th>Công đoạn</th><th>Trạng thái</th><th>KQ</th><th>Đăng ký</th><th></th></tr></thead>
        <tbody>${samples.map(s => `<tr><td><code class="k">${esc(s.sample_code)}</code></td><td>${esc(s.stage || "—")}</td>
          <td><span class="badge ${s.status === "completed" ? "available" : s.status === "in_test" ? "due" : "planned"}">${{registered:"Đã đăng ký",in_test:"Đang test",completed:"Hoàn thành"}[s.status] || esc(s.status)}</span></td><td>${s.result_count}</td>
          <td class="muted">${fmt(s.registered_at)}</td>
          <td>${s.status !== "completed" ? `<button class="btn sm sec" data-smp="${esc(s.sample_id)}" data-next="${s.status === "registered" ? "in_test" : "completed"}">${s.status === "registered" ? "Bắt đầu test" : "Hoàn thành"}</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`)}
    `;

    async function loadSPC() {
      try {
        const spc = await GET(`/qc/spc?parameter=${encodeURIComponent($("sp_param").value)}`);
        const cap = (spc.cp != null) ? `Cp <b>${spc.cp}</b> · Cpk <b>${spc.cpk}</b>` : "—";
        $("sp_box").innerHTML = controlChart(spc) +
          `<div style="margin-top:6px">n=${spc.n} · Mean ${spc.mean} · σ ${spc.sigma} · UCL ${spc.ucl} · LCL ${spc.lcl} · ${cap}
            · ${spc.in_control ? '<span class="badge available">Trong kiểm soát</span>' : `<span class="badge critical">${spc.out_of_control} điểm vi phạm</span>`}</div>`;
      } catch (e) { $("sp_box").innerHTML = `<div class="muted">Lỗi: ${esc(e.message)}</div>`; }
    }
    $("sp_param").onchange = loadSPC;
    // Mặc định chọn chỉ tiêu có dữ liệu SPC để demo trực quan.
    if ([...$("sp_param").options].some(o => o.value === "Độ đường (°P)")) $("sp_param").value = "Độ đường (°P)";
    wireSearch(); wirePaginate("t_capa", 10); wirePaginate("t_samples", 10);
    wireSelectSearch("ca_scope", "ca_scope_q");
    // Chọn Deviation liên kết -> tự đồng bộ Phạm vi theo đúng phạm vi của Deviation đó (người
    // dùng vẫn sửa lại được sau nếu muốn) — tránh phải chọn lại phạm vi 2 lần cho cùng 1 việc.
    $("ca_dev").onchange = () => {
      const opt = $("ca_dev").selectedOptions[0];
      const scopeKey = opt && opt.dataset.scope;
      if (scopeKey && scopeKey !== "undefined:undefined" && [...$("ca_scope").options].some(o => o.value === scopeKey)) {
        $("ca_scope").value = scopeKey;
      }
    };
    if (PENDING_CAPA_DEVIATION) {
      if ([...$("ca_dev").options].some(o => o.value === PENDING_CAPA_DEVIATION)) { $("ca_dev").value = PENDING_CAPA_DEVIATION; $("ca_dev").onchange(); }
      PENDING_CAPA_DEVIATION = null;
      $("ca_dev").closest(".panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    $("ca_add").onclick = () => guard(async () => {
      const [scopeType, scopeId] = ($("ca_scope").value || "").split(":");
      await POST("/qc/capa", { title: $("ca_title").value, capa_type: $("ca_type").value,
        deviation_id: $("ca_dev").value || null, due_date: $("ca_due").value || null,
        scope_type: scopeType || null, scope_id: scopeId || null });
      toast("Đã mở CAPA"); render("qclab");
    });
    // Thứ tự đầy đủ 7 giai đoạn CAPA (khớp CAPA_TRANSITIONS backend, services/quality_adv.py) —
    // dùng để tính giai đoạn đã qua/hiện tại/chưa tới khi vẽ modal chi tiết dạng stepper.
    const CAPA_PHASES = ["open", "investigation", "action", "verification", "kcs_approval", "director_approval", "closed"];
    const CAPA_NEXT = { open: "investigation", investigation: "action", action: "verification",
                        verification: "kcs_approval", kcs_approval: "director_approval", director_approval: "closed" };

    // Tách thành hàm named để tái dùng cho PENDING_OPEN_CAPA_ID (điều hướng từ Deviations ->
    // CAPA, bấm mã CAPA ở cột "CAPA liên kết") — không chỉ gọi từ click trực tiếp trên bảng.
    function openCapaDetailModal(c) {
      const curIdx = CAPA_PHASES.indexOf(c.state);
      const nx = CAPA_NEXT[c.state];
      const phaseHtml = CAPA_PHASES.map((phase, i) => {
        if (phase === "closed" && i > curIdx) return "";  // "closed" chỉ hiện khi đã đóng, không phải 1 giai đoạn "chưa tới" riêng
        const title = `<b>${i + 1}. ${esc(CAPA_PHASE_LABEL[phase])}</b>`;
        if (i < curIdx) {
          // Đã qua — tóm tắt read-only.
          let summary = "";
          if (phase === "open") summary = `Đã mở — ${esc(c.opened_by || "—")} · ${fmt(c.opened_at)}`;
          else if (phase === "investigation") summary = `Nguyên nhân gốc: ${esc(c.root_cause || "—")}`;
          else if (phase === "action") summary = `Kế hoạch hành động: ${esc(c.action_plan || "—")}`;
          else if (phase === "verification") summary = `Hiệu lực: ${esc(c.effectiveness || "—")} · Ngày kiểm tra: ${esc(c.effectiveness_checked_at || "—")}`;
          else if (phase === "kcs_approval") summary = c.kcs_approved_by
            ? `✓ Trưởng phòng KCS đã duyệt — ${esc(c.kcs_approved_by)} · ${fmt(c.kcs_approved_at)}${c.kcs_approval_note ? `<br>Nhận xét: ${esc(c.kcs_approval_note)}` : ""}`
            : `Đã qua bước này — không có dữ liệu duyệt (CAPA đóng trước khi có bước duyệt KCS).`;
          else if (phase === "director_approval") summary = c.director_approved_by
            ? `✓ Giám đốc/Phó GĐ SX-KT đã duyệt — ${esc(c.director_approved_by)} · ${fmt(c.director_approved_at)}`
            : `Đã qua bước này — không có dữ liệu duyệt (CAPA đóng trước khi có bước duyệt Giám đốc).`;
          return `<div class="panel" style="margin-top:6px;padding:8px 12px;border:1px solid var(--border)">${title}<div class="muted" style="margin-top:2px">${summary}</div></div>`;
        }
        if (i === curIdx) {
          if (phase === "closed") return `<div class="panel" style="margin-top:6px;padding:8px 12px;border:1px solid var(--border)">${title}<div class="muted" style="margin-top:2px">Ghi chú đóng: ${esc(c.close_note || "—")}</div></div>`;
          let fieldsHtml = "";
          if (phase === "investigation") fieldsHtml = `<div class="field" style="margin-top:6px"><label>Nguyên nhân gốc</label><input id="cd_rc" value="${esc(c.root_cause || "")}"/></div>`;
          else if (phase === "action") fieldsHtml = `<div class="field" style="margin-top:6px"><label>Kế hoạch hành động</label><input id="cd_ap" value="${esc(c.action_plan || "")}"/></div>`;
          else if (phase === "verification") fieldsHtml = `<div class="field" style="margin-top:6px"><label>Hiệu lực (verification)</label><input id="cd_ef" value="${esc(c.effectiveness || "")}"/></div>
              <div class="field" style="margin-top:6px"><label>Ngày kiểm tra hiệu lực</label><input id="cd_eff_date" type="date" value="${esc(c.effectiveness_checked_at || "")}"/></div>`;
          else if (phase === "kcs_approval") fieldsHtml = `<div class="field" style="margin-top:6px"><label>Nhận xét của Trưởng phòng KCS <span style="color:var(--red)">*</span></label><input id="cd_kcs_note" placeholder="Bắt buộc — đánh giá của Trưởng phòng KCS khi duyệt"/></div>`;
          else if (phase === "director_approval") fieldsHtml = `<div class="field" style="margin-top:6px"><label>Ghi chú đóng <span style="color:var(--red)">*</span></label><input id="cd_close" placeholder="Bắt buộc — bằng chứng đóng CAPA"/></div>
              <div class="muted" style="margin-top:4px">Người đóng phải khác người mở (${esc(c.opened_by || "—")}), trừ admin.</div>`;
          const btnLabel = phase === "director_approval" ? "→ Duyệt & Đóng CAPA (Giám đốc/Phó GĐ SX-KT)"
            : phase === "kcs_approval" ? "→ Duyệt (Trưởng phòng KCS)"
            : `Chuyển sang: ${nx}`;
          return `<div class="panel" style="margin-top:6px;padding:8px 12px;border:1px solid var(--accent)">${title}${fieldsHtml}
              <button class="btn" id="cd_go" style="margin-top:10px">${esc(btnLabel)}</button></div>`;
        }
        // Chưa tới — xám, không input.
        return `<div class="panel muted" style="margin-top:6px;padding:8px 12px;border:1px dashed var(--border);opacity:.6">${title}</div>`;
      }).join("");

      modal(`<h3>${esc(c.capa_code)} — ${esc(c.title)}</h3>
        <div>Trạng thái hiện tại: <span class="badge ${["kcs_approval", "director_approval"].includes(c.state) ? "due" : c.state === "closed" ? "available" : "planned"}">${esc(CAPA_PHASE_LABEL[c.state] || c.state)}</span></div>
        ${phaseHtml}
        <div id="cd_attach_box" style="margin-top:14px"><h4 style="margin:0 0 6px">📎 Tài liệu đính kèm</h4><div class="muted">Đang tải…</div></div>`, null, true);

      if (nx) $("cd_go").onclick = () => guard(async () => {
        const payload = { target: nx };
        if ($("cd_rc")) payload.root_cause = $("cd_rc").value;
        if ($("cd_ap")) payload.action_plan = $("cd_ap").value;
        if ($("cd_ef")) payload.effectiveness = $("cd_ef").value;
        if ($("cd_eff_date")) payload.effectiveness_checked_at = $("cd_eff_date").value || null;
        if ($("cd_kcs_note")) {
          const note = $("cd_kcs_note").value.trim();
          if (!note) throw new Error("Nhập nhận xét của Trưởng phòng KCS trước khi duyệt.");
          payload.kcs_approval_note = note;
        }
        if ($("cd_close")) {
          const note = $("cd_close").value.trim();
          if (!note) throw new Error("Nhập ghi chú đóng trước khi đóng CAPA.");
          payload.close_note = note;
        }
        await POST(`/qc/capa/${c.capa_id}/transition`, payload);
        closeModal(); toast("Đã cập nhật CAPA"); render("qclab");
      });

      async function refreshAttachments() {
        const box = $("cd_attach_box");
        if (!box) return;
        const atts = await GET(`/qc/capa/${c.capa_id}/attachments`).catch(() => []);
        const canDelete = CURRENT_USER && (CURRENT_USER.username === c.opened_by || CURRENT_USER.role === "admin");
        box.innerHTML = `<h4 style="margin:0 0 6px">📎 Tài liệu đính kèm</h4>
          <div class="tablewrap"><table><thead><tr><th>Tên file</th><th>Ghi chú</th><th>Người tải lên</th><th>Lúc</th><th></th></tr></thead>
          <tbody>${atts.map(a => `<tr>
            <td>${esc(a.file_name)}</td><td class="muted">${esc(a.note || "—")}</td>
            <td class="muted">${esc(a.uploaded_by || "—")}</td><td class="muted">${fmt(a.uploaded_at)}</td>
            <td style="white-space:nowrap">
              <button class="btn sm sec" data-dlatt="${esc(a.attachment_id)}" data-fname="${esc(a.file_name)}">Tải xuống</button>
              ${canDelete ? `<button class="btn sm sec" data-rmatt="${esc(a.attachment_id)}">Xóa</button>` : ""}
            </td></tr>`).join("") || `<tr><td colspan=5 class="muted">Chưa có tài liệu nào.</td></tr>`}</tbody></table></div>
          <div class="row" style="margin-top:8px">
            <input type="file" id="cd_att_file"/>
            <div class="field"><input id="cd_att_note" placeholder="Ghi chú (tuỳ chọn)"/></div>
            <button class="btn sec" id="cd_att_upload">Tải lên</button>
          </div>`;
        box.querySelectorAll("[data-dlatt]").forEach(b => b.onclick = () => guard(async () => {
          await downloadFile(`/qc/capa/attachments/${b.dataset.dlatt}/download`, b.dataset.fname);
        }));
        box.querySelectorAll("[data-rmatt]").forEach(b => b.onclick = () => guard(async () => {
          if (!confirm("Xóa tài liệu đính kèm này?")) return;
          await DELETE(`/qc/capa/attachments/${b.dataset.rmatt}`);
          toast("Đã xóa tài liệu"); refreshAttachments();
        }));
        $("cd_att_upload").onclick = () => guard(async () => {
          const file = $("cd_att_file").files[0];
          if (!file) throw new Error("Chọn 1 file trước khi tải lên.");
          const fd = new FormData();
          fd.append("file", file);
          fd.append("note", $("cd_att_note").value || "");
          await POST_FORM(`/qc/capa/${c.capa_id}/attachments`, fd);
          toast("Đã tải lên tài liệu"); refreshAttachments();
        });
      }
      refreshAttachments();
    }
    document.querySelectorAll("[data-capa]").forEach(b => b.onclick = () => {
      openCapaDetailModal(capas.find(x => x.capa_id === b.dataset.capa));
    });
    document.querySelectorAll("[data-opendev]").forEach(b => b.onclick = () => {
      PENDING_OPEN_DEVIATION_ID = b.dataset.opendev;
      gotoView("quality");
    });
    if (PENDING_OPEN_CAPA_ID) {
      const targetCapaId = PENDING_OPEN_CAPA_ID;
      PENDING_OPEN_CAPA_ID = null;
      const c = capas.find(x => x.capa_id === targetCapaId);
      if (c) openCapaDetailModal(c);
    }
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
  // #8 — OEE & DỪNG MÁY — mirror nghiệp vụ file vận hành thật
  //   "OPI - CAN L3 (KHS 30K).xlsx": Dashboard OPI (thác nước A→R + target %),
  //   Nhập ca, Ghi dừng máy (danh mục 8 nhóm), RCFA + 5 Whys, Dừng lắt nhắt
  //   (MS&SL, đếm SỐ LẦN theo tuần), MTBF/MTTR, Danh mục lý do & Target.
  //   Công thức thác nước đầy đủ: backend/app/services/oee_waterfall.py.
  // ======================================================================
  const OEE_CAT_LABELS = {
    bao_tri_ngoai: "Bảo trì ngoài", nona: "NONA", ke_hoach: "Dừng có kế hoạch",
    chuyen_may: "Chuyển máy", thieu_vat_tu: "Dừng nguyên vật liệu",
    breakdown: "Breakdown", dung_lat_nhat: "Dừng lắt nhắt", sp_loi: "Sản phẩm lỗi",
  };
  const OEE_5WHY_CATS = [
    ["qua_tai", "Quá tải"], ["hu_hong_theo_thoi_gian", "Hư hỏng theo thời gian"],
    ["hong_dot_ngot", "Hỏng đột ngột"], ["ap_luc_tang_dan", "Áp lực tăng dần"],
    ["dieu_kien_co_ban", "Điều kiện cơ bản"], ["dieu_kien_van_hanh", "Điều kiện vận hành"],
    ["hu_hong_do_quen", "Hư hỏng do quên"], ["diem_yeu_thiet_ke", "Điểm yếu thiết kế"],
    ["loi_tho_van_hanh", "Lỗi thợ vận hành"], ["loi_tho_bao_duong", "Lỗi thợ bảo dưỡng"],
  ];
  const OEE_4M1E = [["method", "Phương pháp"], ["material", "Nguyên vật liệu"],
    ["machine", "Máy móc"], ["man", "Con người"]];
  const OEE_SHIFTS = ["Ca1", "Ca2", "Ca3", "Kip1", "Kip2"];
  let OEE_SEL = { line: "", year: new Date().getFullYear(), month: new Date().getMonth() + 1,
    msYear: new Date().getFullYear() };
  let OEE_MS_WEEK = { week: 1, shift: "Ca1" };
  let OEE_CATALOG_CACHE = null;   // { line, rows } — cache danh mục lý do theo dây chuyền đang chọn

  async function oeeLineOptions() {
    const lns = await GET("/lines?active_only=true&kind=line").catch(() => []);
    if ((!OEE_SEL.line || !lns.some(l => l.code === OEE_SEL.line)) && lns.length) {
      OEE_SEL.line = (lns.find(l => l.code === "CAN30K") || lns[0]).code;
    }
    return lns;
  }
  async function oeeCatalogForLine() {
    if (OEE_CATALOG_CACHE && OEE_CATALOG_CACHE.line === OEE_SEL.line) return OEE_CATALOG_CACHE.rows;
    const rows = await GET(`/downtime/reason-catalog?line_code=${encodeURIComponent(OEE_SEL.line)}`);
    OEE_CATALOG_CACHE = { line: OEE_SEL.line, rows };
    return rows;
  }

  VIEWS.oee = async function () {
    const root = $("view-oee");
    const sec = SUB.oee || "dashboard";
    const sections = [
      { key: "dashboard", label: "📊 Dashboard OPI" }, { key: "summary", label: "📈 Summary" },
      { key: "ca", label: "📝 Nhập ca" },
      { key: "dungmay", label: "⏱️ Ghi dừng máy" }, { key: "rcfa", label: "🔧 RCFA" },
      { key: "mssl", label: "📉 Dừng lắt nhắt (MS&SL)" }, { key: "mtbf", label: "🔩 MTBF/MTTR" },
      { key: "danhmuc", label: "🗂️ Danh mục lý do & Target" },
    ];
    const lns = await oeeLineOptions();
    const lineBar = panel("Dây chuyền OEE", `<div class="row">
      <div class="field"><label>Chọn dây chuyền</label><select id="oee_line_sel">
        ${lns.map(l => `<option value="${esc(l.code)}" ${l.code === OEE_SEL.line ? "selected" : ""}>${esc(l.code)}</option>`).join("")
          || `<option value="">(chưa có — thêm ở Danh mục chung)</option>`}</select></div>
      <div class="muted" style="align-self:flex-end;padding-bottom:8px">Áp dụng cho tất cả các tab OEE bên dưới (trừ MTBF/MTTR — theo mọi thiết bị).</div>
    </div>`);

    let body = "";
    if (sec === "dashboard") body = await renderOeeDashboard();
    else if (sec === "summary") body = await renderOeeSummary();
    else if (sec === "ca") body = renderOeeShiftForm(lns);
    else if (sec === "dungmay") body = await renderOeeDowntimeForm();
    else if (sec === "rcfa") body = await renderOeeRcfa();
    else if (sec === "mssl") body = await renderOeeMinorStop();
    else if (sec === "mtbf") body = await renderOeeMtbf();
    else if (sec === "danhmuc") body = await renderOeeCatalog();

    root.innerHTML = (sec === "mtbf" ? "" : lineBar) + subnav("oee", sections, sec) + body;
    wireSubnav("oee");
    if (sec !== "mtbf") {
      const lineSel = $("oee_line_sel");
      if (lineSel) lineSel.onchange = () => { OEE_SEL.line = lineSel.value; render("oee"); };
    }
    if (sec === "dashboard") wireOeeDashboard();
    else if (sec === "summary") wireOeeSummary();
    else if (sec === "ca") wireOeeShiftForm();
    else if (sec === "dungmay") wireOeeDowntimeForm();
    else if (sec === "rcfa") wireOeeRcfa();
    else if (sec === "mssl") wireOeeMinorStop();
    else if (sec === "danhmuc") wireOeeCatalog();
  };

  // ---- Tab 1: Dashboard OPI (thác nước A→R + OPI/OPI NONA/Efficiency so target) ----
  async function renderOeeDashboard() {
    if (!OEE_SEL.line) return panel("📊 Dashboard OPI", `<div class="muted">Chưa có dây chuyền active.</div>`);
    const q = `line_code=${encodeURIComponent(OEE_SEL.line)}&year=${OEE_SEL.year}&month=${OEE_SEL.month}`;
    const [summary, pareto] = await Promise.all([
      GET(`/downtime/opi-summary?${q}`).catch(() => null),
      GET(`/downtime/pareto-by-category?line=${encodeURIComponent(OEE_SEL.line)}`).catch(() => ({ items: [] })),
    ]);
    if (!summary) return panel("📊 Dashboard OPI", `<div class="muted">Không tải được dữ liệu cho dây chuyền này.</div>`);
    const yearOpts = Array.from({ length: 6 }, (_, i) => new Date().getFullYear() + 1 - i)
      .map(y => `<option value="${y}" ${y === OEE_SEL.year ? "selected" : ""}>${y}</option>`).join("");
    const monthOpts = Array.from({ length: 12 }, (_, i) => i + 1)
      .map(m => `<option value="${m}" ${m === OEE_SEL.month ? "selected" : ""}>Tháng ${m}</option>`).join("");
    const catRows = summary.by_category.map(c => `<tr><td>${esc(c.label)}</td>
      <td>${(c.actual_pct * 100).toFixed(2)}%</td><td>${(c.target_pct * 100).toFixed(2)}%</td>
      <td>${c.actual_pct > c.target_pct ? `<span class="badge critical">Vượt target</span>` : `<span class="badge available">Đạt</span>`}</td>
      <td>${c.actual_minutes.toLocaleString("vi-VN")}</td></tr>`).join("");
    const wfRows = summary.waterfall.map(r => `<tr><td><b>${esc(r.code)}</b></td><td>${esc(r.label)}</td>
      <td>${r.minutes.toLocaleString("vi-VN")}</td></tr>`).join("");
    return `
      ${panel("Kỳ báo cáo", `<div class="row" style="align-items:flex-end">
        <div class="field"><label>Năm</label><select id="oe_d_year">${yearOpts}</select></div>
        <div class="field"><label>Tháng</label><select id="oe_d_month">${monthOpts}</select></div>
        <button class="btn" id="oe_d_go">Xem</button>
      </div>`)}
      ${panel("OPI / OPI NONA / Efficiency so Target", `<div class="split">
        <div style="text-align:center"><h3>OPI</h3>${CH.donut(summary.opi, {})}
          <div class="muted" style="font-size:12px">Target ${(summary.opi_target * 100).toFixed(1)}%</div></div>
        <div style="text-align:center"><h3>OPI NONA</h3>${CH.donut(summary.opi_nona, {})}
          <div class="muted" style="font-size:12px">Target ${(summary.opi_nona_target * 100).toFixed(1)}%</div></div>
        <div style="text-align:center"><h3>Efficiency</h3>${CH.donut(summary.efficiency, {})}
          <div class="muted" style="font-size:12px">Target ${(summary.efficiency_target * 100).toFixed(1)}%</div></div>
      </div>`)}
      ${panel("Tổn thất 8 nhóm so Target", `<div class="tablewrap"><table><thead><tr>
        <th>Nhóm</th><th>Thực tế %</th><th>Target %</th><th>Trạng thái</th><th>Phút</th></tr></thead>
        <tbody>${catRows}</tbody></table></div>`)}
      ${panel("Thác nước tổn thất tháng (A → R)", `<div class="tablewrap"><table><thead><tr>
        <th>Mã</th><th>Diễn giải</th><th>Phút</th></tr></thead><tbody>${wfRows}</tbody></table></div>`)}
      ${panel("Pareto theo nhóm lý do (toàn thời gian đã ghi nhận)", `
        ${CH.vbars((pareto.items || []).map(i => ({ label: i.label, value: i.minutes })), { unit: "phút", color: "#e67e22" })}
        <div class="tablewrap" style="margin-top:8px"><table><thead><tr><th>Nhóm</th><th>Phút</th><th>%</th><th>Tích lũy %</th><th>Số lần</th></tr></thead>
        <tbody>${(pareto.items || []).map(i => `<tr><td>${esc(i.label)}</td><td>${i.minutes}</td><td>${i.pct}%</td><td>${i.cum_pct}%</td><td>${i.count}</td></tr>`).join("")}</tbody></table></div>`)}
    `;
  }
  function wireOeeDashboard() {
    if (!$("oe_d_go")) return;
    $("oe_d_go").onclick = () => {
      OEE_SEL.year = parseInt($("oe_d_year").value) || OEE_SEL.year;
      OEE_SEL.month = parseInt($("oe_d_month").value) || OEE_SEL.month;
      render("oee");
    };
  }

  // ---- Tab 1b: Summary — mirror 16 biểu đồ sheet Summary của file OPI Excel gốc, nhưng lấy
  // target sống từ Danh mục lý do & Target đang dùng (không hardcode lại số target cũ trong Excel).
  const OEE_CAT_ORDER = ["bao_tri_ngoai", "nona", "ke_hoach", "chuyen_may", "thieu_vat_tu", "breakdown", "dung_lat_nhat", "sp_loi"];
  function oeeCatVsTargetItems(byCategory) {
    const byKey = {}; (byCategory || []).forEach(c => byKey[c.category] = c);
    return OEE_CAT_ORDER.filter(k => byKey[k]).map(k => ({
      label: byKey[k].label, a: +(byKey[k].actual_pct * 100).toFixed(2), b: +(byKey[k].target_pct * 100).toFixed(2),
    }));
  }
  function oeeParetoChart(items) {
    if (!items || !items.length) return `<div class="muted">Không có dữ liệu trong kỳ này.</div>`;
    return CH.vbars(items.map(i => ({ label: i.label, value: i.minutes })), { unit: "phút", color: "#e67e22" });
  }
  async function renderOeeSummary() {
    if (!OEE_SEL.line) return panel("📈 Summary", `<div class="muted">Chưa có dây chuyền active.</div>`);
    const q = `line_code=${encodeURIComponent(OEE_SEL.line)}&year=${OEE_SEL.year}&month=${OEE_SEL.month}`;
    const d = await GET(`/downtime/summary-dashboard?${q}`).catch(() => null);
    if (!d) return panel("📈 Summary", `<div class="muted">Không tải được dữ liệu cho dây chuyền này.</div>`);
    const yearOpts = Array.from({ length: 6 }, (_, i) => new Date().getFullYear() + 1 - i)
      .map(y => `<option value="${y}" ${y === OEE_SEL.year ? "selected" : ""}>${y}</option>`).join("");
    const monthOpts = Array.from({ length: 12 }, (_, i) => i + 1)
      .map(m => `<option value="${m}" ${m === OEE_SEL.month ? "selected" : ""}>Tháng ${m}</option>`).join("");
    const monthly = d.monthly, quarterly = d.quarterly, weekly = d.weekly;
    const lmCat = monthly[d.month - 1].by_category, tqCat = quarterly[d.quarter - 1].by_category;

    const weeklyCatSeries = OEE_CAT_ORDER.map(k => ({
      label: (weekly[0].by_category.find(c => c.category === k) || {}).label || k,
      values: weekly.map(w => +(((w.by_category.find(c => c.category === k) || {}).actual_pct || 0) * 100).toFixed(2)),
    }));

    const chart = (title, sub, inner) => panel(`📊 ${esc(title)}`, `<div class="muted" style="font-size:12px;margin-bottom:6px">${esc(sub)}</div>${inner}`);

    return `
      ${panel("Kỳ báo cáo", `<div class="row" style="align-items:flex-end">
        <div class="field"><label>Năm</label><select id="os_year">${yearOpts}</select></div>
        <div class="field"><label>Tháng</label><select id="os_month">${monthOpts}</select></div>
        <button class="btn" id="os_go">Xem</button>
        <div class="muted" style="align-self:flex-end;padding-bottom:8px">"Tháng" quyết định luôn quý chứa nó (dùng cho các biểu đồ THIS QUARTER/LAST MONTH). Target lấy trực tiếp từ tab Danh mục lý do & Target.</div>
      </div>`)}

      ${chart("OPI CAN LINE MONTHLY", "OPI thực tế và Target theo từng tháng trong năm.",
        CH.grouped(monthly.map(p => ({ label: p.label, a: +(p.opi * 100).toFixed(2), b: +(p.opi_target * 100).toFixed(2) })),
          { labelA: "OPI thực tế", labelB: "Target", colorA: "#3498db", colorB: "#e74c3c" }))}

      ${chart("MSSL & BREAKDOWN CAN LINE MONTHLY", "Dừng lắt nhắt (MS&SL) và Breakdown theo từng tháng.",
        CH.grouped(monthly.map(p => ({ label: p.label, a: +(p.ms_sl_pct * 100).toFixed(2), b: +(p.breakdown_pct * 100).toFixed(2) })),
          { labelA: "MS & SL", labelB: "Breakdown", colorA: "#e67e22", colorB: "#9b59b6" }))}

      ${chart("WEEKLY CAN LINE OPI", "OPI thực tế và Target — 13 tuần ISO gần nhất.",
        CH.grouped(weekly.map(p => ({ label: p.label, a: +(p.opi * 100).toFixed(2), b: +(p.opi_target * 100).toFixed(2) })),
          { labelA: "OPI thực tế", labelB: "Target", colorA: "#3498db", colorB: "#e74c3c" }))}

      ${chart("WEEKLY CAN LINE PLANNED DOWNTIME", "Dừng có kế hoạch thực tế và Target — 13 tuần gần nhất.",
        CH.grouped(weekly.map(p => ({ label: p.label, a: +(p.planned_pct * 100).toFixed(2), b: +(p.planned_target * 100).toFixed(2) })),
          { labelA: "Thực tế", labelB: "Target", colorA: "#16a085", colorB: "#e74c3c" }))}

      ${chart("WEEKLY CAN LINE MINOR STOP AND SPEED LOSS", "Dừng lắt nhắt (% thời gian làm) — 13 tuần gần nhất.",
        CH.vbars(weekly.map(p => ({ label: p.label, value: +(p.ms_sl_pct * 100).toFixed(2) })), { unit: "%", color: "#e67e22" }))}

      ${chart("WEEKLY CAN LINE BREAKDOWN", "Cơ cấu 8 nhóm tổn thất (% thời gian làm) theo tuần — thay cho phân rã theo vị trí máy vì dữ liệu vị trí máy chỉ có cho nhóm Breakdown.",
        CH.groupedN(weekly.map(p => p.label), weeklyCatSeries, { unit: "%" }))}

      ${chart("OPI CAN LINE QUARTERLY", "OPI thực tế và Target theo từng quý trong năm.",
        CH.grouped(quarterly.map(p => ({ label: p.label, a: +(p.opi * 100).toFixed(2), b: +(p.opi_target * 100).toFixed(2) })),
          { labelA: "OPI thực tế", labelB: "Target", colorA: "#3498db", colorB: "#e74c3c" }))}

      ${chart("DOWNTIME QUARTERLY", "Dừng có kế hoạch và Dừng ngoài kế hoạch (thiếu NVL + Breakdown + Dừng lắt nhắt) theo từng quý.",
        CH.grouped(quarterly.map(p => ({ label: p.label, a: +(p.planned_pct * 100).toFixed(2), b: +(p.unplanned_pct * 100).toFixed(2) })),
          { labelA: "Có kế hoạch", labelB: "Ngoài kế hoạch", colorA: "#16a085", colorB: "#c0392b" }))}

      ${chart(`DOWNTIME CAN LINE LAST MONTH (Tháng ${d.month}/${d.year})`, "8 nhóm tổn thất thực tế so Target — tháng vừa chọn.",
        CH.grouped(oeeCatVsTargetItems(lmCat), { labelA: "Thực tế", labelB: "Target", colorA: "#3498db", colorB: "#e74c3c" }))}

      ${chart(`BREAKDOWN CAN LINE LAST MONTH (Tháng ${d.month}/${d.year})`, "Pareto phút Breakdown theo vị trí máy.",
        oeeParetoChart(d.last_month_breakdowns.breakdown))}

      ${chart(`PLANNED DOWNTIME CAN LINE LAST MONTH (Tháng ${d.month}/${d.year})`, "Pareto phút dừng có kế hoạch theo lý do con.",
        oeeParetoChart(d.last_month_breakdowns.planned_downtime))}

      ${chart(`MINOR STOP CAN LINE LAST MONTH (Tháng ${d.month}/${d.year})`, "Pareto phút dừng lắt nhắt theo lý do con.",
        oeeParetoChart(d.last_month_breakdowns.minor_stop))}

      ${chart(`DOWNTIME CAN LINE THIS QUARTER (Q${d.quarter}/${d.year})`, "8 nhóm tổn thất thực tế so Target — quý chứa tháng vừa chọn.",
        CH.grouped(oeeCatVsTargetItems(tqCat), { labelA: "Thực tế", labelB: "Target", colorA: "#3498db", colorB: "#e74c3c" }))}

      ${chart(`BREAKDOWN CAN LINE THIS QUARTER (Q${d.quarter}/${d.year})`, "Pareto phút Breakdown theo vị trí máy.",
        oeeParetoChart(d.this_quarter_breakdowns.breakdown))}

      ${chart(`PLANNED DOWNTIME CAN LINE THIS QUARTER (Q${d.quarter}/${d.year})`, "Pareto phút dừng có kế hoạch theo lý do con.",
        oeeParetoChart(d.this_quarter_breakdowns.planned_downtime))}

      ${chart(`MINOR STOP CAN LINE THIS QUARTER (Q${d.quarter}/${d.year})`, "Pareto phút dừng lắt nhắt theo lý do con.",
        oeeParetoChart(d.this_quarter_breakdowns.minor_stop))}
    `;
  }
  function wireOeeSummary() {
    if (!$("os_go")) return;
    $("os_go").onclick = () => {
      OEE_SEL.year = parseInt($("os_year").value) || OEE_SEL.year;
      OEE_SEL.month = parseInt($("os_month").value) || OEE_SEL.month;
      render("oee");
    };
  }

  // ---- Tab 2: Nhập ca (SP tốt/SP lỗi tách riêng đúng cách nhập file gốc) ----
  function renderOeeShiftForm(lns) {
    const line = lns.find(l => l.code === OEE_SEL.line);
    const rate = line ? line.ideal_rate_per_min : 0;
    return panel("📝 Nhập ca — " + esc(OEE_SEL.line || "—"), `
      <div class="row">
        <div class="field"><label>Ca</label><select id="oe_shift">${OEE_SHIFTS.map(s => `<option>${s}</option>`).join("")}</select></div>
        <div class="field"><label>TG kế hoạch (phút)</label><input id="oe_plan" value="480" style="width:100px"/></div>
        <div class="field"><label>Dừng (phút)</label><input id="oe_dt" value="0" style="width:90px"/></div>
        <div class="field"><label>Tốc độ lý tưởng (SP/phút)</label><input id="oe_rate" value="${rate}" style="width:120px"/></div>
        <div class="field"><label>SP tốt</label><input id="oe_good" value="0" style="width:100px"/></div>
        <div class="field"><label>SP lỗi</label><input id="oe_reject" value="0" style="width:100px"/></div>
        <div class="field" style="align-self:flex-end"><button class="btn" id="oe_go">Ghi OEE</button></div>
      </div>
      <div class="muted" style="margin-top:4px">Đổi dây chuyền ở ô "Dây chuyền OEE" phía trên. Thêm/ngừng dây chuyền ở Danh mục chung.</div>`);
  }
  function wireOeeShiftForm() {
    $("oe_go").onclick = () => guard(async () => {
      if (!OEE_SEL.line) { toast("Chưa có dây chuyền", "err"); return; }
      await POST("/oee", { line: OEE_SEL.line, shift: $("oe_shift").value,
        planned_time_min: num("oe_plan") || 0, downtime_min: num("oe_dt") || 0,
        ideal_rate_per_min: num("oe_rate") || 0, good_count: num("oe_good") || 0,
        reject_count: num("oe_reject") || 0 });
      toast("Đã ghi OEE ca"); render("oee");
    });
  }

  // ---- Tab 3: Ghi dừng máy (cascading Nhóm → Lý do theo danh mục DB, hiện hẳn ra dạng tích chọn) ----
  const OEE_PICK_LABEL = "display:flex;align-items:center;gap:6px;font-size:13px;padding:4px 10px;border:1px solid var(--border);border-radius:16px;cursor:pointer;background:var(--panel)";
  const OEE_PICK_BOX = "display:flex;flex-wrap:wrap;gap:6px;background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:8px";
  async function renderOeeDowntimeForm() {
    if (!OEE_SEL.line) return panel("⏱️ Ghi dừng máy", `<div class="muted">Chưa có dây chuyền.</div>`);
    const rows = await oeeCatalogForLine();
    const cats = [...new Set(rows.map(r => r.category))];
    const events = await GET(`/downtime?line=${encodeURIComponent(OEE_SEL.line)}&limit=30`).catch(() => []);
    const nowLocal = toDTLocal(new Date());
    return `
      ${panel("⏱️ Ghi sự kiện dừng máy — " + esc(OEE_SEL.line), `
        <div class="row">
          <div class="field" style="flex:1"><label>Nhóm lý do</label>
            <div id="dt_cat_box" style="${OEE_PICK_BOX}">${cats.map((c, i) => `<label style="${OEE_PICK_LABEL}">
              <input type="radio" name="dt_cat" value="${esc(c)}" ${i === 0 ? "checked" : ""}/> ${esc(OEE_CAT_LABELS[c] || c)}</label>`).join("")}</div></div>
        </div>
        <div class="row">
          <div class="field" style="flex:1"><label>Lý do</label>
            <div id="dt_reason_box" style="${OEE_PICK_BOX}"></div></div>
          <div class="field" id="dt_err_wrap" style="display:none"><label>Mã lỗi</label><input id="dt_err" style="width:100px"/></div>
        </div>
        <div class="row">
          <div class="field"><label>Ca</label><select id="dt_shift">${OEE_SHIFTS.map(s => `<option>${s}</option>`).join("")}</select></div>
          <div class="field"><label>Dừng từ</label><input type="datetime-local" id="dt_from" value="${nowLocal}"/></div>
          <div class="field"><label>Dừng đến</label><input type="datetime-local" id="dt_to" value="${nowLocal}"/></div>
          <div class="field"><label>Phút (tự tính)</label><input id="dt_min_preview" value="0" style="width:80px" disabled/></div>
        </div>
        <div class="row"><div class="field" style="flex:1"><label>Ghi chú</label><input id="dt_note" style="width:100%"/></div></div>
        <div class="row">
          <button class="btn" id="dt_go">Ghi</button>
          <button class="btn sec" id="dt_rcfa" style="display:none">🔧 Tạo RCFA từ sự kiện này</button>
        </div>`)}
      ${panel("Lịch sử gần đây", `<div class="tablewrap"><table><thead><tr>
        <th>Ca</th><th>Nhóm</th><th>Lý do</th><th>Từ</th><th>Đến</th><th>Phút</th><th>Ghi chú</th></tr></thead>
        <tbody>${events.map(e => `<tr><td>${esc(e.shift)}</td><td>${esc(OEE_CAT_LABELS[e.reason_group] || e.reason_group)}</td>
          <td>${esc(e.reason_label || e.reason_code || "")}</td><td>${e.start_at ? fmt(e.start_at) : "—"}</td>
          <td>${e.end_at ? fmt(e.end_at) : "—"}</td><td>${e.minutes}</td><td>${esc(e.note || "")}</td></tr>`).join("")
          || `<tr><td colspan="7" class="muted">Chưa có sự kiện nào.</td></tr>`}</tbody></table></div>`)}
    `;
  }
  function wireOeeDowntimeForm() {
    if (!OEE_SEL.line || !OEE_CATALOG_CACHE) return;
    const rows = OEE_CATALOG_CACHE.rows;
    const catChecked = () => document.querySelector('input[name="dt_cat"]:checked');
    const reasonChecked = () => document.querySelector('input[name="dt_reason"]:checked');
    function fillReasons() {
      const cat = catChecked() ? catChecked().value : "";
      const opts = rows.filter(r => r.category === cat);
      $("dt_reason_box").innerHTML = opts.map((r, i) => `<label style="${OEE_PICK_LABEL}">
        <input type="radio" name="dt_reason" value="${r.reason_id}" ${i === 0 ? "checked" : ""}/> ${esc(r.sub_label)}${r.machine_position ? " — " + esc(r.machine_position) : ""}</label>`).join("")
        || `<span class="muted" style="font-size:12px">(Nhóm này chưa có lý do nào)</span>`;
      $("dt_err_wrap").style.display = cat === "breakdown" ? "" : "none";
    }
    document.querySelectorAll('input[name="dt_cat"]').forEach(r => r.onchange = fillReasons);
    fillReasons();
    function previewMinutes() {
      const from = $("dt_from").value, to = $("dt_to").value;
      let mins = 0;
      if (from && to) mins = Math.max(0, Math.round((new Date(to) - new Date(from)) / 60000));
      $("dt_min_preview").value = mins;
      $("dt_rcfa").style.display = mins >= 30 ? "" : "none";
    }
    $("dt_from").oninput = previewMinutes; $("dt_to").oninput = previewMinutes; previewMinutes();
    $("dt_go").onclick = () => guard(async () => {
      const reasonId = reasonChecked() ? reasonChecked().value : "";
      if (!reasonId) { toast("Chưa chọn lý do", "err"); return; }
      await POST("/downtime", { line: OEE_SEL.line, reason_catalog_id: reasonId,
        shift: $("dt_shift").value, from_time: $("dt_from").value, to_time: $("dt_to").value,
        error_code: catChecked() && catChecked().value === "breakdown" ? ($("dt_err").value || null) : null,
        note: $("dt_note").value || null });
      toast("Đã ghi sự kiện dừng máy"); render("oee");
    });
    $("dt_rcfa").onclick = () => {
      const opt = reasonChecked();
      openOeeRcfaModal(null, { line_code: OEE_SEL.line, machine: opt ? opt.parentElement.textContent.trim() : "",
        stop_at: $("dt_from").value, duration_min: num("dt_min_preview") || 0 });
    };
  }

  // ---- Tab 4: RCFA + 5 Whys ----
  async function renderOeeRcfa() {
    const rows = OEE_SEL.line ? await GET(`/rcfa?line_code=${encodeURIComponent(OEE_SEL.line)}`) : [];
    return panel("🔧 RCFA — Phân tích nguyên nhân gốc (" + esc(OEE_SEL.line || "—") + ")", `
      <button class="btn" id="rcfa_add">+ Thêm RCFA</button>
      <div class="tablewrap" style="margin-top:8px"><table><thead><tr>
        <th>Số RCFA</th><th>Máy</th><th>Bộ phận</th><th>Dừng lúc</th><th>Phút</th><th>Mô tả</th>
        <th>Khắc phục</th><th>Ngày hoàn thành</th><th>Recheck</th><th></th></tr></thead>
        <tbody>${rows.map(r => `<tr>
          <td>${esc(r.rcfa_no)}</td><td>${esc(r.machine)}</td><td>${esc(r.part || "")}</td>
          <td>${r.stop_at ? fmt(r.stop_at) : "—"}</td><td>${r.duration_min}</td>
          <td>${esc(r.description || "")}</td><td>${esc(r.corrective_action || "")}</td>
          <td>${r.complete_date ? fmt(r.complete_date) : "—"}</td>
          <td>${r.recheck_done}/${r.recheck_total}</td>
          <td style="white-space:nowrap"><button class="btn sm sec" data-rcfa-edit="${r.rcfa_id}">Sửa</button>
              <button class="btn sm sec" data-rcfa-recheck="${r.rcfa_id}">Recheck</button></td>
        </tr>`).join("") || `<tr><td colspan="10" class="muted">Chưa có RCFA nào.</td></tr>`}</tbody></table></div>`);
  }
  function wireOeeRcfa() {
    $("rcfa_add").onclick = () => openOeeRcfaModal(null, { line_code: OEE_SEL.line });
    document.querySelectorAll("[data-rcfa-edit]").forEach(b => b.onclick = () => guard(async () => {
      const rec = await GET(`/rcfa/${b.dataset.rcfaEdit}`);
      openOeeRcfaModal(rec.rcfa_id, rec);
    }));
    document.querySelectorAll("[data-rcfa-recheck]").forEach(b => b.onclick = () => guard(async () => {
      const rec = await GET(`/rcfa/${b.dataset.rcfaRecheck}`);
      openOeeRecheckModal(rec);
    }));
  }
  function openOeeRcfaModal(rcfaId, data) {
    data = data || {};
    const fiveWhys = (data.five_whys && data.five_whys.length) ? data.five_whys
      : [1, 2, 3, 4, 5].map(l => ({ level: l, text: "", category: "" }));
    const toLocal = (v) => v ? toDTLocal(new Date(v)) : "";
    modal(`<h3>${rcfaId ? "Sửa" : "Thêm"} RCFA${data.rcfa_no ? " — " + esc(data.rcfa_no) : ""}</h3>
      <div class="row">
        <div class="field"><label>Dây chuyền</label><input id="rc_line" value="${esc(data.line_code || OEE_SEL.line || "")}"/></div>
        <div class="field"><label>Máy</label><input id="rc_machine" value="${esc(data.machine || "")}"/></div>
        <div class="field"><label>Bộ phận</label><input id="rc_part" value="${esc(data.part || "")}"/></div>
      </div>
      <div class="row">
        <div class="field"><label>Dừng lúc</label><input type="datetime-local" id="rc_stop" value="${toLocal(data.stop_at) || toDTLocal(new Date())}"/></div>
        <div class="field"><label>Thời gian dừng (phút)</label><input id="rc_dur" value="${data.duration_min || 0}" style="width:100px"/></div>
        <div class="field"><label>Kỹ thuật viên</label><input id="rc_tech" value="${esc(data.technician || "")}"/></div>
        <div class="field"><label>Phút sửa</label><input id="rc_repair" value="${data.repair_min ?? ""}" style="width:90px"/></div>
        <div class="field"><label>Phút chờ</label><input id="rc_wait" value="${data.wait_min ?? ""}" style="width:90px"/></div>
      </div>
      <div class="field"><label>Chức năng lỗi</label><input id="rc_func" value="${esc(data.failure_function || "")}" style="width:100%"/></div>
      <div class="field"><label>Dấu hiệu trước đó</label><input id="rc_prior" value="${esc(data.prior_signs || "")}" style="width:100%"/></div>
      <div class="field"><label>Mô tả phát hiện + xử lý</label><textarea id="rc_desc" rows="2" style="width:100%">${esc(data.description || "")}</textarea></div>
      <div class="field"><label>Vật tư thay thế (cách nhau bởi dấu phẩy)</label><input id="rc_parts" value="${esc((data.replaced_parts || []).join(", "))}" style="width:100%"/></div>
      <div class="field"><label>Nguyên lý hoạt động</label><textarea id="rc_wp" rows="2" style="width:100%">${esc(data.working_principle || "")}</textarea></div>
      <div class="field"><label>Cơ chế hư hỏng</label><textarea id="rc_fm" rows="2" style="width:100%">${esc(data.failure_mechanism || "")}</textarea></div>
      <div class="row">
        <div class="field"><label>Người phân tích</label><input id="rc_analyst" value="${esc(data.analyst || "")}"/></div>
        <div class="field"><label>Yếu tố</label><input id="rc_factor" value="${esc(data.factor || "")}"/></div>
        <div class="field"><label>Phân loại 4M1E</label><select id="rc_4m1e">
          <option value="">—</option>${OEE_4M1E.map(([v, l]) => `<option value="${v}" ${data.category_4m1e === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      </div>
      <h4>5 Whys</h4>
      ${fiveWhys.map((w, i) => `<div class="row" data-why-row="${i}">
        <div class="field" style="width:56px"><label>Why ${w.level || i + 1}</label></div>
        <div class="field" style="flex:2"><input class="why-text" value="${esc(w.text || "")}" placeholder="Diễn giải" style="width:100%"/></div>
        <div class="field"><select class="why-cat"><option value="">—</option>
          ${OEE_5WHY_CATS.map(([v, l]) => `<option value="${v}" ${w.category === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      </div>`).join("")}
      <div class="field"><label>Hành động khắc phục</label><textarea id="rc_corr" rows="2" style="width:100%">${esc(data.corrective_action || "")}</textarea></div>
      <div class="field"><label>Hành động phòng ngừa</label><textarea id="rc_prev" rows="2" style="width:100%">${esc(data.preventive_action || "")}</textarea></div>
      <div class="row">
        <div class="field"><label>Người thực hiện</label><input id="rc_exec" value="${esc(data.executor || "")}"/></div>
        <div class="field"><label>Ngày hoàn thành</label><input type="datetime-local" id="rc_complete" value="${toLocal(data.complete_date)}"/></div>
        <div class="field"><label>Người kiểm tra</label><input id="rc_checker" value="${esc(data.checker || "")}"/></div>
      </div>
      <div class="row" style="margin-top:8px"><button class="btn" id="rc_save">Lưu</button></div>`, null, true);
    $("rc_save").onclick = () => guard(async () => {
      const five_whys = Array.from(document.querySelectorAll("[data-why-row]")).map((row, i) => ({
        level: i + 1, text: row.querySelector(".why-text").value, category: row.querySelector(".why-cat").value || null,
      })).filter(w => w.text);
      const payload = {
        line_code: $("rc_line").value, machine: $("rc_machine").value, part: $("rc_part").value || null,
        stop_at: $("rc_stop").value || null, duration_min: parseFloat($("rc_dur").value) || 0,
        failure_function: $("rc_func").value || null, prior_signs: $("rc_prior").value || null,
        technician: $("rc_tech").value || null, repair_min: $("rc_repair").value ? parseFloat($("rc_repair").value) : null,
        wait_min: $("rc_wait").value ? parseFloat($("rc_wait").value) : null, description: $("rc_desc").value || null,
        replaced_parts: $("rc_parts").value.split(",").map(s => s.trim()).filter(Boolean),
        working_principle: $("rc_wp").value || null, failure_mechanism: $("rc_fm").value || null,
        analyst: $("rc_analyst").value || null, factor: $("rc_factor").value || null, five_whys,
        category_4m1e: $("rc_4m1e").value || null, corrective_action: $("rc_corr").value || null,
        preventive_action: $("rc_prev").value || null, executor: $("rc_exec").value || null,
        complete_date: $("rc_complete").value || null, checker: $("rc_checker").value || null,
      };
      if (rcfaId) await PUT(`/rcfa/${rcfaId}`, payload);
      else await POST("/rcfa", payload);
      toast("Đã lưu RCFA"); closeModal(); render("oee");
    });
  }
  function openOeeRecheckModal(rec) {
    modal(`<h3>Theo dõi tái diễn — ${esc(rec.rcfa_no)}</h3>
      <div class="tablewrap"><table><thead><tr><th>Tuần</th><th>Đã kiểm tra</th><th>Ghi chú</th><th></th></tr></thead>
      <tbody>${rec.recheck_schedule.map(w => `<tr>
        <td>W+${w.week_offset}</td>
        <td><input type="checkbox" data-week="${w.week_offset}" ${w.checked ? "checked" : ""}/></td>
        <td><input data-week-note="${w.week_offset}" value="${esc(w.note || "")}" style="width:100%"/></td>
        <td><button class="btn sm sec" data-week-save="${w.week_offset}">Lưu</button></td>
      </tr>`).join("")}</tbody></table></div>`, null, true);
    document.querySelectorAll("[data-week-save]").forEach(b => b.onclick = () => guard(async () => {
      const wk = b.dataset.weekSave;
      const checked = document.querySelector(`[data-week="${wk}"]`).checked;
      const note = document.querySelector(`[data-week-note="${wk}"]`).value;
      await PUT(`/rcfa/${rec.rcfa_id}/recheck`, { week_offset: parseInt(wk), checked, note: note || null });
      toast(`Đã lưu W+${wk}`);
    }));
  }

  // ---- Tab 5: Dừng lắt nhắt (MS&SL) — đếm số lần theo tuần/ca ----
  async function renderOeeMinorStop() {
    if (!OEE_SEL.line) return panel("📉 Dừng lắt nhắt (MS&SL)", `<div class="muted">Chưa có dây chuyền.</div>`);
    const [grid, pareto] = await Promise.all([
      GET(`/downtime/minor-stop-tally?line_code=${encodeURIComponent(OEE_SEL.line)}&iso_year=${OEE_SEL.msYear}`),
      GET(`/downtime/minor-stop-pareto?line_code=${encodeURIComponent(OEE_SEL.line)}&iso_year=${OEE_SEL.msYear}`),
    ]);
    const weekEntry = (row) => (row.by_week || []).find(w => w.iso_week === OEE_MS_WEEK.week && w.shift === OEE_MS_WEEK.shift);
    const weekOpts = Array.from({ length: 53 }, (_, i) => i + 1)
      .map(w => `<option value="${w}" ${w === OEE_MS_WEEK.week ? "selected" : ""}>Tuần ${w}</option>`).join("");
    return `
      ${panel("📉 Nhập số lần dừng lắt nhắt theo tuần — " + esc(OEE_SEL.line), `
        <div class="row">
          <div class="field"><label>Năm ISO</label><input id="ms_year" value="${OEE_SEL.msYear}" style="width:90px"/></div>
          <div class="field"><label>Tuần</label><select id="ms_week">${weekOpts}</select></div>
          <div class="field"><label>Ca</label><select id="ms_shift">
            ${OEE_SHIFTS.map(s => `<option value="${s}" ${s === OEE_MS_WEEK.shift ? "selected" : ""}>${s}</option>`).join("")}</select></div>
          <button class="btn sec" id="ms_reload" style="align-self:flex-end">Tải lại</button>
        </div>
        <div class="tablewrap" style="margin-top:8px"><table><thead><tr><th>Lý do</th><th>Số lần (tuần đã chọn)</th><th>Tổng lũy kế cả năm</th></tr></thead>
        <tbody>${grid.rows.map(r => { const e = weekEntry(r); return `<tr>
          <td>${esc(r.sub_label)}</td>
          <td><input class="ms-count" data-reason="${r.reason_id}" value="${e ? e.count : 0}" style="width:70px"/></td>
          <td>${r.total}</td></tr>`; }).join("") || `<tr><td colspan="3" class="muted">Chưa có danh mục lắt nhắt.</td></tr>`}</tbody></table></div>
        <button class="btn" id="ms_save" style="margin-top:8px">Lưu số liệu tuần</button>`)}
      ${panel("Pareto lũy kế cả năm", `
        ${CH.vbars((pareto.items || []).map(i => ({ label: i.sub_label, value: i.count })), { unit: "lần", color: "#9b59b6" })}
        <div class="tablewrap" style="margin-top:8px"><table><thead><tr><th>Lý do</th><th>Số lần</th><th>%</th><th>Tích lũy %</th></tr></thead>
        <tbody>${(pareto.items || []).map(i => `<tr><td>${esc(i.sub_label)}</td><td>${i.count}</td><td>${i.pct}%</td><td>${i.cum_pct}%</td></tr>`).join("")}</tbody></table></div>`)}
    `;
  }
  function wireOeeMinorStop() {
    $("ms_reload").onclick = () => {
      OEE_SEL.msYear = parseInt($("ms_year").value) || OEE_SEL.msYear;
      OEE_MS_WEEK.week = parseInt($("ms_week").value) || 1;
      OEE_MS_WEEK.shift = $("ms_shift").value;
      render("oee");
    };
    $("ms_save").onclick = () => guard(async () => {
      const week = parseInt($("ms_week").value) || 1, shift = $("ms_shift").value,
        year = parseInt($("ms_year").value) || OEE_SEL.msYear;
      for (const inp of document.querySelectorAll(".ms-count")) {
        await PUT("/downtime/minor-stop-tally", { reason_id: inp.dataset.reason, iso_year: year,
          iso_week: week, shift, count: parseInt(inp.value) || 0 });
      }
      OEE_SEL.msYear = year; OEE_MS_WEEK = { week, shift };
      toast("Đã lưu MS&SL tuần " + week); render("oee");
    });
  }

  // ---- Tab 6: MTBF/MTTR (giữ nguyên — không đổi công thức) ----
  async function renderOeeMtbf() {
    const mtbf = await GET("/downtime/mtbf");
    return panel("🔧 MTBF / MTTR theo thiết bị", `
      <div class="muted" style="margin-bottom:6px">Cửa sổ ${mtbf.window_days} ngày.</div>
      <div class="tablewrap"><table><thead><tr><th>Thiết bị</th><th>Số lần hỏng</th><th>MTBF (giờ)</th><th>MTTR (phút)</th><th>Khả dụng</th><th>Dừng (phút)</th></tr></thead>
      <tbody>${(mtbf.equipment || []).map(e => `<tr><td>${esc(e.name)}</td><td>${e.failures}</td>
        <td>${e.mtbf_hours ?? "—"}</td><td>${e.mttr_min ?? "—"}</td><td>${e.availability_pct}%</td><td>${e.downtime_min}</td></tr>`).join("")}</tbody></table></div>`);
  }

  // ---- Tab 7: Danh mục lý do & Target (CRUD OeeReasonCatalog, quyền master.manage) ----
  async function renderOeeCatalog() {
    if (!OEE_SEL.line) return panel("🗂️ Danh mục lý do & Target", `<div class="muted">Chưa có dây chuyền.</div>`);
    const canManage = _hasPerm("master.manage");
    const rows = await GET(`/downtime/reason-catalog?line_code=${encodeURIComponent(OEE_SEL.line)}`);
    const byCategory = {};
    rows.forEach(r => (byCategory[r.category] = byCategory[r.category] || []).push(r));
    const catBlocks = Object.keys(OEE_CAT_LABELS).map(cat => {
      const list = byCategory[cat] || [];
      const totalTarget = list.reduce((s, r) => s + (r.target_pct || 0), 0);
      return `<h4>${esc(OEE_CAT_LABELS[cat])} <span class="muted" style="font-weight:400">(tổng target ${(totalTarget * 100).toFixed(2)}%)</span></h4>
        <div class="tablewrap"><table><thead><tr><th>Lý do</th><th>Vị trí máy</th><th>Target %</th><th>Kích hoạt</th>
          ${canManage ? "<th></th>" : ""}</tr></thead>
        <tbody>${list.map(r => `<tr>
          <td>${esc(r.sub_label)}</td><td>${esc(r.machine_position || "")}</td>
          <td>${(r.target_pct * 100).toFixed(2)}%</td><td>${r.active ? "Có" : "Không"}</td>
          ${canManage ? `<td style="white-space:nowrap"><button class="btn sm sec" data-cat-edit="${r.reason_id}">Sửa</button>
            <button class="btn sm sec" style="color:var(--red)" data-cat-del="${r.reason_id}">Xóa</button></td>` : ""}
        </tr>`).join("") || `<tr><td colspan="${canManage ? 5 : 4}" class="muted">Chưa có.</td></tr>`}</tbody></table></div>`;
    }).join("");
    return `
      ${!canManage ? `<div class="muted" style="margin-bottom:8px">Bạn chỉ có quyền xem danh mục (cần quyền <code class="k">master.manage</code> để thêm/sửa/xóa).</div>` : ""}
      ${canManage ? panel("+ Thêm lý do mới — " + esc(OEE_SEL.line), `
        <div class="row">
          <div class="field"><label>Nhóm</label><select id="oc_cat">
            ${Object.entries(OEE_CAT_LABELS).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></div>
          <div class="field"><label>Mã lý do</label><input id="oc_code" style="width:140px"/></div>
          <div class="field"><label>Tên hiển thị</label><input id="oc_label" style="width:220px"/></div>
          <div class="field"><label>Vị trí máy (breakdown)</label><input id="oc_pos" style="width:140px"/></div>
          <div class="field"><label>Target %</label><input id="oc_target" value="0" style="width:80px"/></div>
          <button class="btn" id="oc_add" style="align-self:flex-end">Thêm</button>
        </div>`) : ""}
      ${panel("Danh sách lý do & target theo nhóm", catBlocks)}
    `;
  }
  function wireOeeCatalog() {
    if (!_hasPerm("master.manage")) return;
    $("oc_add").onclick = () => guard(async () => {
      await POST("/downtime/reason-catalog", { line_code: OEE_SEL.line, category: $("oc_cat").value,
        sub_code: $("oc_code").value, sub_label: $("oc_label").value,
        machine_position: $("oc_pos").value || null, target_pct: (parseFloat($("oc_target").value) || 0) / 100 });
      toast("Đã thêm lý do"); render("oee");
    });
    document.querySelectorAll("[data-cat-edit]").forEach(b => b.onclick = () => guard(async () => {
      const label = prompt("Tên hiển thị mới:"); if (label === null) return;
      const targetPct = prompt("Target % mới (vd 2.5):"); if (targetPct === null) return;
      await PUT(`/downtime/reason-catalog/${b.dataset.catEdit}`,
        { sub_label: label, target_pct: (parseFloat(targetPct) || 0) / 100 });
      toast("Đã cập nhật"); render("oee");
    }));
    document.querySelectorAll("[data-cat-del]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xóa lý do này?")) return;
      await DELETE(`/downtime/reason-catalog/${b.dataset.catDel}`);
      toast("Đã xóa"); render("oee");
    }));
  }

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
      // So giá trị thực tế với ngưỡng dưới/trên đã khai (lsl/usl, mới thêm — yêu cầu người dùng
      // 2026-09-05: "tiêu chuẩn để làm so sánh sau này" — trước đây ISA-88 chỉ có Setpoint,
      // không có ngưỡng nào để so Đạt/Vượt). null/undefined ở lsl hoặc usl = không giới hạn phía đó.
      const i8OutOfRange = (param, val) => {
        const num = Number(val);
        if (!Number.isFinite(num)) return false;
        if (param.lsl != null && num < param.lsl) return true;
        if (param.usl != null && num > param.usl) return true;
        return false;
      };
      // Mỗi Setpoint 1 CỘT riêng (không gộp chung 1 ô như trước), mỗi cột 2 dòng: dòng trên là
      // setpoint cài đặt, dòng dưới là giá trị thực tế — mirror đúng cách trình bày file Step
      // Protocol Braumat (mỗi Setpoint 1/2/3/4 là 1 cột) — yêu cầu người dùng 2026-09-05:
      // "làm giống như file pdf tôi gửi đó phù hợp hơn mỗi cột là 1 setpoint, mỗi giá trị có 2
      // dòng, dòng trên là setpoint, dòng dưới là thực tế". Số cột = số setpoint NHIỀU NHẤT
      // trong toàn bộ thủ tục đang xem (phase nào ít hơn thì để trống ô thừa).
      const allPhasesI8 = st.unit_procedures.flatMap(u => u.operations.flatMap(o => o.phases));
      const maxParams = Math.max(0, ...allPhasesI8.map(ph => (ph.params || []).length));
      const totalCols = 4 + maxParams;
      const paramCell = (p, x) => {
        if (!x) return "<td></td>";
        const range = (x.lsl != null || x.usl != null) ? ` [${x.lsl ?? "-∞"}–${x.usl ?? "+∞"}]` : "";
        const setpointLine = `<div class="muted" style="font-size:11px">${esc(x.name)}=${esc(x.setpoint)}${esc(x.unit || "")}${esc(range)}</div>`;
        const editable = p.state === "running" || p.state === "held";
        let actualLine;
        if (editable) {
          actualLine = `<input type="text" class="i8-val" data-run="${p.run_id}" data-pname="${esc(x.name)}"
            value="${esc(p.values && p.values[x.name] != null ? p.values[x.name] : "")}" placeholder="thực tế" style="width:70px"/>`;
        } else {
          const v = p.values ? p.values[x.name] : null;
          if (v == null) {
            actualLine = '<span class="muted">—</span>';
          } else {
            const hasRange = x.lsl != null || x.usl != null;
            // Hiện kèm luôn khoảng ngưỡng ngay trong nhãn Đạt/Vượt — yêu cầu người dùng
            // 2026-09-05: "sao biết vượt ngưỡng vậy, thêm cho tôi giá trị ngưỡng vào để biết".
            const statusBadge = hasRange ? (i8OutOfRange(x, v) ? ` ${badge("critical")}Vượt` : ` ${badge("available")}Đạt`) : "";
            actualLine = `${esc(v)}${esc(x.unit || "")}${statusBadge}`;
          }
        }
        return `<td style="font-size:12px">${setpointLine}<div style="margin-top:2px">${actualLine}</div></td>`;
      };
      const phaseRow = (up, op, p) => {
        const b = PHASE_BADGE[p.state] || "planned";
        const started = p.started_at ? new Date(p.started_at) : null;
        const ended = p.ended_at ? new Date(p.ended_at) : null;
        const elapsedMin = started ? Math.round(((ended || new Date()) - started) / 60000) : null;
        // Ngày giờ THẬT bắt đầu/kết thúc của từng phase (mirror cột Date/Time trong file Step
        // Protocol Braumat — yêu cầu người dùng 2026-09-05: "thêm ngày giờ bắt đầu, ngày giờ kết
        // thúc của phase vào") — hiện bên cạnh thời lượng cài đặt/thực tế, không thay thế nó.
        const timeLine = started
          ? `<br><span class="muted">${fmt(p.started_at)}${ended ? " → " + fmt(p.ended_at) : " (đang chạy)"}</span>` : "";
        const durCell = `${p.duration_min ? esc(p.duration_min) + "' (cài đặt)" : "—"}${elapsedMin != null ? `<br><span class="muted">${elapsedMin}' thực tế</span>` : ""}${timeLine}`;
        const paramCells = Array.from({ length: maxParams }, (_, i) => paramCell(p, (p.params || [])[i])).join("");
        // Cho nhập tay giờ bắt đầu/kết thúc THẬT (để trống = giờ hiện tại, như trước) — dùng khi
        // nạp lại lịch sử theo file export Braumat thay vì đúng lúc bấm nút (xem services/
        // isa88.py::start_phase/transition_phase, tham số started_at/ended_at mới thêm).
        let btns = "";
        if (p.state === "idle") btns = `<input type="datetime-local" class="i8-started" data-up="${esc(up)}" data-op="${esc(op)}" data-ph="${esc(p.phase)}"
            title="Giờ bắt đầu thật (để trống = giờ hiện tại)" style="width:150px;margin-bottom:3px;display:block"/>
          <button class="btn sm" data-act="start" data-up="${esc(up)}" data-op="${esc(op)}" data-ph="${esc(p.phase)}">Bắt đầu</button>`;
        else if (p.state === "running") btns = `<input type="datetime-local" class="i8-ended" data-run="${p.run_id}"
            title="Giờ kết thúc thật khi Hoàn thành/Hủy (để trống = giờ hiện tại)" style="width:150px;margin-bottom:3px;display:block"/>
          <button class="btn sm" data-act="complete" data-run="${p.run_id}">Hoàn thành</button> <button class="btn sm sec" data-act="held" data-run="${p.run_id}">Giữ</button>`;
        else if (p.state === "held") btns = `<input type="datetime-local" class="i8-ended" data-run="${p.run_id}"
            title="Giờ kết thúc thật khi Hủy (để trống = giờ hiện tại)" style="width:150px;margin-bottom:3px;display:block"/>
          <button class="btn sm" data-act="running" data-run="${p.run_id}">Tiếp</button> <button class="btn sm sec" data-act="aborted" data-run="${p.run_id}">Hủy</button>`;
        return `<tr><td style="padding-left:24px">${esc(p.phase)}</td>
          <td class="muted" style="font-size:12px">${durCell}</td>
          ${paramCells}
          <td>${badge(b)}${esc(p.state)}</td><td>${esc(p.operator || "")}</td><td>${btns}</td></tr>`;
      };
      const rows = st.unit_procedures.map(u => {
        const head = `<tr style="background:var(--panel2)"><td colspan="${totalCols}"><b>▸ ${esc(u.unit_procedure)}</b>
          ${u.unit_class === "cip" ? badge("critical") + "CIP" : badge("available") + esc(u.unit_class || "")}</td></tr>`;
        const ops = u.operations.map(o =>
          `<tr><td colspan="${totalCols}" style="padding-left:12px"><i>${esc(o.operation)}</i></td></tr>` +
          o.phases.map(p => phaseRow(u.unit_procedure, o.operation, p)).join("")).join("");
        return head + ops;
      }).join("");
      const setpointHeaders = Array.from({ length: maxParams }, (_, i) => `<th>Setpoint ${i + 1}</th>`).join("");
      $("i8_box").innerHTML = `
        <div style="margin-bottom:8px">Tiến độ: <b>${st.completion_pct}%</b>
          (${st.phases_done}/${st.phases_total} phase) ${CH.donut(st.completion_pct / 100, { label: "phase", size: 96 })}</div>
        ${maxParams ? `<div class="muted" style="margin-bottom:6px;font-size:12px">Mỗi cột Setpoint gồm 2 dòng — <b>dòng 1: Cài đặt</b> (setpoint + ngưỡng theo công thức), <b>dòng 2: Actual</b> (giá trị thực tế đã ghi, kèm Đạt/Vượt nếu có khai ngưỡng).</div>` : ""}
        <div class="tablewrap"><table><thead><tr><th>Unit procedure / Operation / Phase</th><th>Thời gian</th>${setpointHeaders}<th>Trạng thái</th><th>Người</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div>`;
      const bid2 = bid;
      document.querySelectorAll("#i8_box [data-act]").forEach(btn => btn.onclick = () => guard(async () => {
        const act = btn.dataset.act;
        if (act === "start") {
          const startedInp = document.querySelector(`.i8-started[data-up="${CSS.escape(btn.dataset.up)}"][data-op="${CSS.escape(btn.dataset.op)}"][data-ph="${CSS.escape(btn.dataset.ph)}"]`);
          const started_at = startedInp && startedInp.value ? new Date(startedInp.value).toISOString() : undefined;
          await POST(`/isa88/batch/${bid2}/start`, { up: btn.dataset.up, op: btn.dataset.op, phase: btn.dataset.ph, started_at });
        } else {
          const values = {};
          document.querySelectorAll(`.i8-val[data-run="${btn.dataset.run}"]`).forEach(inp => {
            const v = inp.value.trim();
            if (v === "") return;
            const num = Number(v);
            values[inp.dataset.pname] = Number.isFinite(num) ? num : v;
          });
          const endedInp = document.querySelector(`.i8-ended[data-run="${btn.dataset.run}"]`);
          const ended_at = (act === "complete" || act === "aborted") && endedInp && endedInp.value
            ? new Date(endedInp.value).toISOString() : undefined;
          await POST(`/isa88/phase/${btn.dataset.run}/transition`, { target: act, values, ended_at });
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
      svg += `<line x1="${xx.toFixed(1)}" y1="${padT - 4}" x2="${xx.toFixed(1)}" y2="${H - 4}" stroke="var(--border)" stroke-dasharray="2 3"/>
        <text x="${(xx + 2).toFixed(1)}" y="14" fill="var(--muted)" font-size="9">${new Date(t).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" })}</text>`;
    }
    res.forEach((r, i) => {
      const y = padT + i * laneH;
      svg += `<text x="6" y="${y + 18}" fill="var(--text)" font-size="11">${esc(r)}</text>
        <line x1="${padL}" y1="${y + laneH - 1}" x2="${W - 12}" y2="${y + laneH - 1}" stroke="var(--border)"/>`;
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
    const canReceive = _hasPerm("warehouse.receive");
    const canIssue = _hasPerm("warehouse.issue");
    const isAdmin = CURRENT_USER && CURRENT_USER.role === "admin";
    const [sm, locs, pallets] = await Promise.all([GET("/wms/summary"), GET("/wms/locations"), GET("/wms/pallets")]);

    const locOpt = () => locs.map(l => `<option value="${esc(l.loc_id)}">${esc(l.code)} — ${esc(l.name)}${l.used >= l.capacity ? " (đầy)" : ""}</option>`).join("");

    const fillPct = sm.fill_pct || 0;
    const overview = panel("📊 Tổng quan kho thành phẩm", `
      <div class="cards">
        <div class="card"><div class="n">${sm.pallets_total}</div><div class="l">Tổng pallet</div>
          <div class="muted" style="font-size:11px;margin-top:2px">${Object.entries(sm.by_status || {}).map(([k, v]) => `${esc(k)}: ${v}`).join(" · ") || "—"}</div></div>
        <div class="card"><div class="n">${sm.pallets_stored}</div><div class="l">Đang lưu kho</div>
          <div class="muted" style="font-size:11px;margin-top:2px">Sức chứa ${sm.capacity_pallets} pallet</div></div>
        <div class="card"><div class="n">${fillPct}%</div><div class="l">Mức lấp đầy</div>
          <div class="muted" style="font-size:11px;margin-top:2px">${sm.locations} vị trí</div></div>
        <div class="card"><div class="n">${sm.cases}</div><div class="l">Tổng thùng (case)</div></div>
        <div class="card"><div class="n">${sm.units}</div><div class="l">Tổng lon/chai</div></div>
      </div>
      <div style="height:8px;background:var(--panel2);border-radius:4px;margin-top:10px;overflow:hidden">
        <div style="height:100%;width:${Math.min(fillPct, 100)}%;background:${fillPct >= 90 ? "var(--red)" : "var(--blue)"}"></div>
      </div>`);

    const locRows = locs.map(l => `<tr>
      <td><code class="k">${esc(l.code)}</code></td><td>${esc(l.name)}</td><td class="muted">${esc(l.zone || "—")}</td>
      <td class="muted">${esc(l.kind)}</td><td>${l.used}/${l.capacity}${l.used >= l.capacity ? " " + badge("obsolete") + "đầy" : ""}</td>
      ${isAdmin ? `<td><button class="btn sm sec" data-editloc="${l.loc_id}">✎</button> <button class="btn sm sec" data-delloc="${l.loc_id}">🗑️</button></td>` : ""}
    </tr>`).join("");

    const locations = panel("📍 Vị trí kho thành phẩm", `
      <div class="tablewrap"><table><thead><tr><th>Mã</th><th>Tên</th><th>Khu</th><th>Loại</th><th>Sử dụng</th>${isAdmin ? "<th></th>" : ""}</tr></thead>
      <tbody>${locRows || `<tr><td colspan="${isAdmin ? 6 : 5}" class="muted">Chưa khai báo vị trí.</td></tr>`}</tbody></table></div>
      ${isAdmin ? `<div class="row" style="margin-top:10px;flex-wrap:wrap">
        <div class="field"><label>Mã</label><input id="wl_code" style="width:110px"/></div>
        <div class="field"><label>Tên</label><input id="wl_name" style="width:180px"/></div>
        <div class="field"><label>Khu</label><input id="wl_zone" style="width:100px"/></div>
        <div class="field"><label>Loại</label><select id="wl_kind">
          <option value="bin">bin</option><option value="staging">staging</option><option value="cold">cold</option><option value="dock">dock</option></select></div>
        <div class="field"><label>Sức chứa</label><input id="wl_cap" value="10" style="width:80px"/></div>
        <div class="field" style="align-self:flex-end"><button class="btn" id="wl_add">+ Thêm vị trí</button></div>
      </div>` : ""}`);

    const buildForm = canReceive ? panel("📦 Đóng pallet (tự sinh case + barcode)", `
      <div class="row" style="flex-wrap:wrap">
        <div class="field"><label>Sản phẩm</label><input id="pl_prod" style="width:160px"/></div>
        <div class="field"><label>Lô TP</label><input id="pl_lot" style="width:160px"/></div>
        <div class="field"><label>Số case</label><input id="pl_n" value="40" style="width:80px"/></div>
        <div class="field"><label>Lon/case</label><input id="pl_u" value="24" style="width:80px"/></div>
        <div class="field" style="align-self:flex-end"><button class="btn" id="pl_build">+ Đóng pallet</button></div>
      </div>`) : "";

    const PALLET_STATUS_LABEL = { building: "Đang đóng", stored: "Đang lưu kho", shipped: "Đã xuất" };
    const statusBadge = (s) => {
      const cls = s === "stored" ? "available" : s === "shipped" ? "obsolete" : "planned";
      return `<span class="badge ${cls}">${esc(PALLET_STATUS_LABEL[s] || s)}</span>`;
    };
    const palletRows = pallets.map(p => `<tr>
      <td><code class="k">${esc(p.pallet_code)}</code></td><td>${esc(p.product || "—")}</td><td class="muted">${esc(p.lot_code || "—")}</td>
      <td style="text-align:right">${p.case_count}</td><td style="text-align:right">${p.total_units}</td>
      <td>${statusBadge(p.status)}</td><td class="muted">${esc(p.location || "—")}</td>
      <td style="white-space:nowrap">${p.status !== "shipped" ? `<select class="pl_loc" data-pallet="${p.pallet_id}" style="width:120px">
        <option value="">— vị trí —</option>${locOpt()}</select>
        ${canIssue ? `<button class="btn sm" data-putaway="${p.pallet_id}">Cất</button> <button class="btn sm sec" data-ship="${p.pallet_id}">Xuất</button>` : ""}` : ""}
        <button class="btn sm sec" data-label="${esc(p.pallet_code)}">🖨️ Tem</button></td>
    </tr>`).join("");

    const palletsPanel = panel("🟦 Pallet", `
      <div class="tablewrap"><table><thead><tr><th>Mã pallet</th><th>SP</th><th>Lô</th>
        <th style="text-align:right">Case</th><th style="text-align:right">Lon</th><th>Trạng thái</th><th>Vị trí</th><th></th></tr></thead>
      <tbody>${palletRows || '<tr><td colspan="8" class="muted">Chưa có pallet nào.</td></tr>'}</tbody></table></div>`);

    root.innerHTML = overview + locations + buildForm + palletsPanel;

    if (isAdmin) {
      $("wl_add").onclick = () => guard(async () => {
        await POST("/wms/locations", {
          code: $("wl_code").value, name: $("wl_name").value,
          zone: $("wl_zone").value || null, kind: $("wl_kind").value, capacity: parseInt($("wl_cap").value) || 10,
        });
        toast("Đã thêm vị trí"); render("wms");
      });
      root.querySelectorAll("[data-editloc]").forEach(b => b.onclick = () => {
        const l = locs.find(x => x.loc_id === b.dataset.editloc);
        modal(`<h3>Sửa vị trí ${esc(l.code)}</h3>
          <div class="field"><label>Tên</label><input id="el_name" value="${esc(l.name)}"/></div>
          <div class="field"><label>Khu</label><input id="el_zone" value="${esc(l.zone || "")}"/></div>
          <div class="field"><label>Sức chứa</label><input id="el_cap" value="${l.capacity}"/></div>
          <div class="field"><label><input type="checkbox" id="el_active" ${l.active ? "checked" : ""}/> Đang hoạt động</label></div>
          <button class="btn" id="el_save" style="margin-top:10px">Lưu</button>`);
        $("el_save").onclick = () => guard(async () => {
          await PUT(`/wms/locations/${l.loc_id}`, {
            name: $("el_name").value, zone: $("el_zone").value || null,
            capacity: parseInt($("el_cap").value) || 10, active: $("el_active").checked,
          });
          closeModal(); toast("Đã lưu"); render("wms");
        });
      });
      root.querySelectorAll("[data-delloc]").forEach(b => b.onclick = () => guard(async () => {
        if (!confirm("Xóa vị trí này?")) return;
        await DELETE(`/wms/locations/${b.dataset.delloc}`);
        toast("Đã xóa vị trí"); render("wms");
      }));
    }

    if (canReceive) {
      $("pl_build").onclick = () => guard(async () => {
        await POST("/wms/pallets", {
          product: $("pl_prod").value || null, lot_code: $("pl_lot").value || null,
          case_count: parseInt($("pl_n").value) || 0, units_per_case: parseInt($("pl_u").value) || 24,
        });
        toast("Đã đóng pallet (kèm case + barcode)"); render("wms");
      });
    }

    root.querySelectorAll("[data-putaway]").forEach(b => b.onclick = () => guard(async () => {
      const sel = root.querySelector(`.pl_loc[data-pallet="${b.dataset.putaway}"]`);
      if (!sel || !sel.value) { toast("Chọn vị trí trước", "err"); return; }
      await POST(`/wms/pallets/${b.dataset.putaway}/putaway`, { loc_id: sel.value });
      toast("Đã cất vào vị trí"); render("wms");
    }));
    root.querySelectorAll("[data-ship]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Xuất pallet này?")) return;
      await POST(`/wms/pallets/${b.dataset.ship}/ship`, {});
      toast("Đã xuất pallet"); render("wms");
    }));
    root.querySelectorAll("[data-label]").forEach(b => b.onclick = () => labelModal(b.dataset.label));
  };


  // ======================================================================
  // #D — BAO BÌ TUẦN HOÀN (vỏ chai · két/gông · keg inox)
  // ======================================================================
  const PKG_ICON = { vo_chai: "🍾", ket_gong: "🧺", keg: "🛢️" };
  const hasPerm = (p) => CURRENT_USER && (CURRENT_USER.permissions === "*" ||
    (Array.isArray(CURRENT_USER.permissions) && CURRENT_USER.permissions.includes(p)));
  VIEWS.packaging = async function () {
    const root = $("view-packaging");
    const [data, history, lotReport] = await Promise.all([GET("/packaging"), GET("/packaging/moves"),
      GET("/packaging/lot-report").catch(() => [])]);
    const { summary: sm, types, categories, moves: moveKinds } = data;
    const moves = history;
    const canManage = hasPerm("master.manage");
    const canMove = hasPerm("warehouse.issue");
    const fmtN = (n) => (n == null ? "—" : Number(n).toLocaleString("vi-VN"));

    // Thẻ tổng hợp theo nhóm.
    const cards = (sm.by_category || []).map(c => `<div class="card">
      <div class="n">${PKG_ICON[c.category] || "📦"} ${fmtN(c.on_hand + c.in_circulation)}</div>
      <div class="l">${esc(c.label)} (${c.types} loại)</div>
      <div class="muted" style="font-size:11px;margin-top:2px">Tồn kho ${fmtN(c.on_hand)} · Lưu hành ${fmtN(c.in_circulation)}</div>
    </div>`).join("") || '<div class="muted">Chưa khai báo bao bì.</div>';

    // Bảng loại bao bì.
    const rows = types.map(p => `<tr>
      <td><code class="k">${esc(p.code)}</code></td>
      <td>${PKG_ICON[p.category] || ""} ${esc(p.name)}</td>
      <td>${esc(p.category_label)}</td>
      <td class="muted">${esc(p.material || "—")}${p.volume_l != null ? " · " + p.volume_l + "L" : ""}</td>
      <td style="text-align:right">${fmtN(p.on_hand)}</td>
      <td style="text-align:right">${fmtN(p.in_circulation)}</td>
      <td style="text-align:right"><b>${fmtN(p.total)}</b></td>
      <td style="text-align:right" class="muted">${fmtN(p.deposit)}</td>
      <td>${p.active ? badge("available") + "đang dùng" : badge("obsolete") + "ngừng"}</td>
    </tr>`).join("");

    // Bao bì TIÊU HAO (nắp, thùng carton, tem nhãn...) — lấy trực tiếp từ Kho NVL theo lô,
    // khác hẳn vỏ chai/két/keg tuần hoàn ở trên (đặt cọc/lưu hành). Xem services/packaging.py::lot_report.
    const lotRows = lotReport.map(l => {
      const usedFor = l.usages.length
        ? l.usages.map(u => `${esc(u.bottle_code || "—")} (${fmtN(u.quantity)} ${esc(u.uom)})`).join(", ")
        : '<span class="muted">Chưa dùng</span>';
      return `<tr>
        <td><code class="k">${esc(l.lot_code)}</code></td>
        <td>${esc(l.material_code || "—")} — ${esc(l.material_name || "")}</td>
        <td style="text-align:right">${fmtN(l.quantity)} ${esc(l.uom)}</td>
        <td class="muted">${esc(l.location || "")}</td>
        <td class="muted">${fmt(l.received_at)}</td>
        <td>${usedFor}</td>
        <td class="muted">${l.last_issued_at ? fmt(l.last_issued_at) : "—"}</td>
      </tr>`;
    }).join("");

    root.innerHTML = `
      ${panel("📊 Tổng quan bao bì tuần hoàn", `
        <div class="cards">${cards}</div>
        <div class="muted" style="margin-top:4px">Tổng tồn kho <b>${fmtN(sm.total_on_hand)}</b> · Tổng đang lưu hành (ngoài thị trường) <b>${fmtN(sm.total_in_circulation)}</b></div>`)}
      ${panel(`📦 Bao bì tiêu hao theo lô (từ Kho NVL) <span class="muted">(${lotReport.length})</span>`, `
        <div class="muted" style="margin-bottom:6px">Nắp, thùng carton, tem nhãn... — nhập kho qua Kho NVL (Nhập kho) như vật tư thường, tự động hiện ở đây nếu Nhóm vật tư được đánh dấu "Bao bì tiêu hao" (Danh mục → Nhóm vật tư). Xuất dùng cho mẻ chiết qua nút NVL trên dòng Chiết (tab Nấu-Lọc-Chiết). Khác với vỏ chai/két/keg tuần hoàn ở trên.</div>
        <input class="searchbox" data-tbl="t_pkg_lot" placeholder="Tìm mã lô/vật tư/mã chiết..."/>
        <div class="tablewrap" style="margin-top:6px"><table id="t_pkg_lot">
          <thead><tr><th>Mã lô</th><th>Vật tư</th><th>Tồn kho</th><th>Vị trí</th><th>Ngày nhập</th><th>Đã dùng cho mẻ chiết</th><th>Ngày xuất gần nhất</th></tr></thead>
          <tbody>${lotRows || '<tr><td colspan="7" class="muted">Chưa có lô bao bì tiêu hao nào — khai báo vật tư thuộc Nhóm "Bao bì tiêu hao" rồi nhập kho ở Kho NVL.</td></tr>'}</tbody></table></div>`)}
      ${panel("📋 Danh mục loại bao bì", `
        <input class="searchbox" data-tbl="t_pkgtype" placeholder="Tìm theo mã, tên, nhóm..."/>
        <div class="tablewrap"><table id="t_pkgtype">
          <thead><tr><th>Mã</th><th>Tên</th><th>Nhóm</th><th>Vật liệu</th>
            <th style="text-align:right">Tồn kho</th><th style="text-align:right">Lưu hành</th>
            <th style="text-align:right">Tổng</th><th style="text-align:right">Đặt cọc</th><th>Trạng thái</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="9" class="muted">Chưa có loại bao bì.</td></tr>'}</tbody></table></div>`)}
      ${canManage ? panel("➕ Khai báo loại bao bì mới", `
        <div class="row">
          <div class="field"><label>Mã</label><input id="pk_code" placeholder="VOCHAI-450" style="width:130px"/></div>
          <div class="field"><label>Tên</label><input id="pk_name" placeholder="Vỏ chai 450ml" style="width:220px"/></div>
          <div class="field"><label>Nhóm</label><select id="pk_cat">${Object.entries(categories).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select></div>
          <div class="field"><label>Vật liệu</label><input id="pk_mat" placeholder="glass/steel/plastic" style="width:120px"/></div>
          <div class="field"><label>Dung tích (L)</label><input id="pk_vol" style="width:90px"/></div>
          <div class="field"><label>Đặt cọc (đ)</label><input id="pk_dep" value="0" style="width:100px"/></div>
          <div class="field"><label>Tồn kho đầu</label><input id="pk_on" value="0" style="width:100px"/></div>
          <div class="field"><label>Đang lưu hành</label><input id="pk_circ" value="0" style="width:100px"/></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="pk_add">Khai báo</button></div>
        </div>`) : ""}
      ${canMove ? panel("🔄 Ghi biến động bao bì", `
        <div class="row">
          <div class="field"><label>Loại bao bì</label><select id="mv_pkg">${opt(types, p => p.pkg_id, p => p.code + " · " + p.name)}</select></div>
          <div class="field"><label>Biến động</label><select id="mv_kind">${Object.entries(moveKinds).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select></div>
          <div class="field"><label>Số lượng</label><input id="mv_qty" style="width:110px"/></div>
          <div class="field"><label>Chứng từ</label><input id="mv_ref" placeholder="PX/PN…" style="width:120px"/></div>
          <div class="field"><label>Ghi chú</label><input id="mv_note" style="width:180px"/></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="mv_go">Ghi</button></div>
        </div>
        <div class="muted" id="mv_hint" style="margin-top:2px"></div>`) : ""}
      ${panel("📜 Lịch sử biến động (100 gần nhất)", `
        <input class="searchbox" data-tbl="t_pkg_moves" placeholder="Tìm theo loại, chứng từ, ghi chú, người..."/>
        <div class="tablewrap"><table id="t_pkg_moves">
          <thead><tr><th>Thời điểm</th><th>Loại</th><th>Biến động</th><th style="text-align:right">SL</th><th>Chứng từ</th><th>Ghi chú</th><th>Người</th></tr></thead>
          <tbody>${moves.length ? moves.map(m => {
            const t = types.find(x => x.pkg_id === m.pkg_id);
            return `<tr><td class="muted">${fmt(m.ts)}</td><td>${esc(t ? t.code : m.pkg_id)}</td>
              <td>${badge(m.kind === "nhap" || m.kind === "thu_hoi" ? "available" : m.kind === "loai_bo" ? "critical" : "planned")}${esc(m.kind_label)}</td>
              <td style="text-align:right">${fmtN(m.qty)}</td><td>${esc(m.ref || "—")}</td>
              <td>${esc(m.note || "")}</td><td class="muted">${esc(m.by || "")}</td></tr>`;
          }).join("") : '<tr><td colspan="7" class="muted">Chưa có biến động.</td></tr>'}</tbody></table></div>`)}
    `;

    wireSearch();
    wirePaginate("t_pkg_lot", 10);
    wirePaginate("t_pkg_moves", 10);
    wirePaginate("t_pkgtype", 10);

    if (canManage) $("pk_add").onclick = () => guard(async () => {
      await POST("/packaging", { code: $("pk_code").value, name: $("pk_name").value,
        category: $("pk_cat").value, material: $("pk_mat").value || null,
        volume_l: num("pk_vol"), deposit: num("pk_dep") || 0,
        on_hand: num("pk_on") || 0, in_circulation: num("pk_circ") || 0 });
      toast("Đã khai báo loại bao bì"); render("packaging");
    });

    if (canMove) {
      const HINTS = {
        nhap: "Nhập vỏ/két/keg mới về kho → tăng tồn kho.",
        xuat: "Xuất theo hàng đi (gắn bia) → chuyển từ tồn kho sang đang lưu hành.",
        thu_hoi: "Khách trả vỏ/két/keg về → chuyển từ lưu hành về tồn kho.",
        loai_bo: "Vỏ/két/keg hỏng, thanh lý → giảm tồn kho.",
        kiem_ke: "Đặt lại tồn kho theo số đếm kiểm kê thực tế.",
      };
      const hint = () => { $("mv_hint").textContent = HINTS[$("mv_kind").value] || ""; };
      $("mv_kind").onchange = hint; hint();
      $("mv_go").onclick = () => guard(async () => {
        if (!$("mv_pkg").value) { toast("Chưa có loại bao bì", "err"); return; }
        const r = await POST("/packaging/move", { pkg_id: $("mv_pkg").value, kind: $("mv_kind").value,
          qty: num("mv_qty") || 0, ref: $("mv_ref").value || null, note: $("mv_note").value || null });
        toast(`Đã ghi · tồn ${fmtN(r.on_hand)} · lưu hành ${fmtN(r.in_circulation)}`); render("packaging");
      });
    }
  };

  // ======================================================================
  // CIP (vệ sinh thiết bị) — Danh mục loại biểu mẫu/thiết bị + Khai báo (bước
  // linh hoạt dạng bảng, thêm/bớt tự do) + Lịch sử/nghiệm thu. Gắn CIP với mẻ/lô
  // sản xuất luôn làm TAY từ phía mẻ/lô (xem openCipLinkModal, gọi từ app.js) —
  // suggest_for_scope() chỉ gợi ý theo thiết bị+khu vực, không tự động gán.
  // ======================================================================
  const CIP_AREA_LABEL = { nau: "Nấu", len_men: "Lên men", loc: "Lọc", chiet: "Chiết/Kho TP" };
  const cipResultBadge = (result) => result === "dat" ? badge("available") + "Đạt"
    : result === "khong_dat" ? badge("critical") + "Không đạt" : badge("planned") + "Chờ nghiệm thu";
  let CIP_MAU_FT = null; // form_type_id đang chọn ở tab "Khai báo biểu mẫu" — giữ khi render lại

  // Bảng bước dùng chung cho cả "Khai báo biểu mẫu" (sửa bảng MẪU) và "Khai báo CIP" (nhập 1
  // lần CIP thật, tự điền từ bảng mẫu của loại biểu mẫu đã chọn) — cùng 1 cơ chế thêm/bớt dòng.
  // Ô "Không áp dụng" (N/A) cho từng cột Thời gian/Nhiệt độ/Nồng độ ở Khai báo biểu mẫu —
  // tick N/A khi bước này không có tiêu chí đó (vd VS thô không kiểm tra nồng độ hoá chất);
  // khi na=true, ô Thực tế tương ứng ở Khai báo CIP sẽ bị khoá thay vì để trống cho gõ tự do.
  function _cipMauCell(valueAttr, value, naAttr, na, width) {
    return `<td><input ${valueAttr} value="${esc(value || "")}" style="width:${width}"/>
      <label class="muted" style="font-size:10px;white-space:nowrap;display:block;margin-top:2px">
        <input type="checkbox" ${naAttr} ${na ? "checked" : ""} style="width:auto;vertical-align:middle"/> N/A</label></td>`;
  }
  function cipStepRowHtml(seq, step) {
    step = step || {};
    return `<td><input data-step-no value="${esc(step.step_no != null ? step.step_no : seq)}" style="width:44px"/></td>
      <td><input data-step-content value="${esc(step.content || "")}" style="width:100%"/></td>
      ${_cipMauCell("data-step-time", step.time_spec, "data-step-time-na", step.time_na, "80px")}
      ${_cipMauCell("data-step-temp", step.temp, "data-step-temp-na", step.temp_na, "65px")}
      ${_cipMauCell("data-step-conc", step.concentration, "data-step-conc-na", step.conc_na, "65px")}
      <td><input data-step-result value="${esc(step.check_result || "")}" style="width:80px"/></td>
      <td><input data-step-by value="${esc(step.performed_by || "")}" style="width:110px"/></td>
      <td><input data-step-note value="${esc(step.note || "")}" style="width:110px"/></td>
      <td><button class="btn sm sec" data-step-del>✕</button></td>`;
  }
  function cipAddStepRow(tbodyId, seqRef, step) {
    seqRef.n++;
    const tr = document.createElement("tr");
    tr.innerHTML = cipStepRowHtml(seqRef.n, step);
    $(tbodyId).appendChild(tr);
    tr.querySelector("[data-step-del]").onclick = () => tr.remove();
  }
  function cipFillSteps(tbodyId, seqRef, steps) {
    $(tbodyId).innerHTML = "";
    seqRef.n = 0;
    (steps && steps.length ? steps : [null]).forEach(s => cipAddStepRow(tbodyId, seqRef, s));
  }
  function cipCollectSteps(tbodyId) {
    return Array.from(document.querySelectorAll(`#${tbodyId} tr`)).map(tr => ({
      step_no: tr.querySelector("[data-step-no]").value || null,
      content: tr.querySelector("[data-step-content]").value || "",
      time_spec: tr.querySelector("[data-step-time]").value || null,
      temp: tr.querySelector("[data-step-temp]").value || null,
      concentration: tr.querySelector("[data-step-conc]").value || null,
      time_na: tr.querySelector("[data-step-time-na]").checked,
      temp_na: tr.querySelector("[data-step-temp-na]").checked,
      conc_na: tr.querySelector("[data-step-conc-na]").checked,
      check_result: tr.querySelector("[data-step-result]").value || null,
      performed_by: tr.querySelector("[data-step-by]").value || null,
      note: tr.querySelector("[data-step-note]").value || null,
    })).filter(s => s.content || s.time_spec || s.temp || s.concentration || s.check_result || s.note
                 || s.time_na || s.temp_na || s.conc_na);
  }

  // Bảng bước dùng RIÊNG cho "Khai báo CIP" (tạo 1 lần CIP thật) — TIÊU CHUẨN (4 cột đầu)
  // khoá — chép nguyên từ bảng mẫu, chỉ sửa được ở "Khai báo biểu mẫu"; THỰC TẾ là 4 cột
  // người vận hành tự nhập khi thực hiện (được gõ tự do, kể cả %).
  // Cột TC (tiêu chuẩn) hiển thị dạng text tự xuống dòng thay vì input hẹp — tránh bị cắt bớt
  // khi giá trị dài (VD "150s – nghỉ 30s – lặp 3 lần"); vẫn giữ input ẩn để cipRecordCollectSteps
  // đọc đúng giá trị khi submit (giá trị TC không đổi trong màn Khai báo CIP, chỉ đổi ở Khai báo
  // biểu mẫu), value hiển thị cho người dùng xem đầy đủ nội dung tiêu chuẩn.
  function _cipSpecCell(dataAttr, value, naAttr, na) {
    return `<td style="min-width:130px">
      <input type="hidden" ${dataAttr} value="${esc(value || "")}"/>
      ${naAttr ? `<input type="hidden" ${naAttr} value="${na ? "1" : "0"}"/>` : ""}
      <div class="muted" style="white-space:normal;word-break:break-word;line-height:1.3" title="Tiêu chuẩn — sửa ở Khai báo biểu mẫu">${esc(value || "—")}</div>
    </td>`;
  }
  // Ô Thực tế (TH) — khoá lại (disabled, hiện "—") khi bước này được đánh dấu N/A ở Khai báo
  // biểu mẫu cho đúng cột đó, tránh vận hành gõ số liệu vào cột không áp dụng.
  function _cipActualCell(dataAttr, value, na, width) {
    return `<td><input ${dataAttr} value="${na ? "" : esc(value || "")}" style="width:${width}"
      ${na ? 'disabled placeholder="—"' : ""}/></td>`;
  }
  function cipRecordStepRowHtml(seq, step) {
    step = step || {};
    return `<td><input data-step-no value="${esc(step.step_no != null ? step.step_no : seq)}" style="width:44px"/></td>
      <td><input data-step-content value="${esc(step.content || "")}" style="width:160px"/></td>
      ${_cipSpecCell("data-step-time", step.time_spec, "data-step-time-na", step.time_na)}
      ${_cipSpecCell("data-step-temp", step.temp, "data-step-temp-na", step.temp_na)}
      ${_cipSpecCell("data-step-conc", step.concentration, "data-step-conc-na", step.conc_na)}
      ${_cipSpecCell("data-step-check", step.check_result)}
      ${_cipActualCell("data-step-time-actual", step.time_actual, step.time_na, "90px")}
      ${_cipActualCell("data-step-temp-actual", step.temp_actual, step.temp_na, "80px")}
      ${_cipActualCell("data-step-conc-actual", step.conc_actual, step.conc_na, "80px")}
      <td><select data-step-check-actual style="width:100px">
        <option value="">— chọn —</option>
        <option value="Đạt" ${step.check_actual === "Đạt" ? "selected" : ""}>Đạt</option>
        <option value="Không đạt" ${step.check_actual === "Không đạt" ? "selected" : ""}>Không đạt</option>
      </select></td>
      <td><input data-step-by value="${esc(step.performed_by || "")}" style="width:110px"/></td>
      <td><input data-step-note value="${esc(step.note || "")}" style="width:110px"/></td>
      <td><button class="btn sm sec" data-step-del>✕</button></td>`;
  }
  function cipRecordAddStepRow(tbodyId, seqRef, step) {
    seqRef.n++;
    const tr = document.createElement("tr");
    tr.innerHTML = cipRecordStepRowHtml(seqRef.n, step);
    $(tbodyId).appendChild(tr);
    tr.querySelector("[data-step-del]").onclick = () => tr.remove();
  }
  function cipRecordFillSteps(tbodyId, seqRef, steps) {
    $(tbodyId).innerHTML = "";
    seqRef.n = 0;
    (steps && steps.length ? steps : [null]).forEach(s => cipRecordAddStepRow(tbodyId, seqRef, s));
  }
  function cipRecordCollectSteps(tbodyId) {
    return Array.from(document.querySelectorAll(`#${tbodyId} tr`)).map(tr => ({
      step_no: tr.querySelector("[data-step-no]").value || null,
      content: tr.querySelector("[data-step-content]").value || "",
      time_spec: tr.querySelector("[data-step-time]").value || null,
      temp: tr.querySelector("[data-step-temp]").value || null,
      concentration: tr.querySelector("[data-step-conc]").value || null,
      time_na: tr.querySelector("[data-step-time-na]").value === "1",
      temp_na: tr.querySelector("[data-step-temp-na]").value === "1",
      conc_na: tr.querySelector("[data-step-conc-na]").value === "1",
      check_result: tr.querySelector("[data-step-check]").value || null,
      time_actual: tr.querySelector("[data-step-time-actual]").value || null,
      temp_actual: tr.querySelector("[data-step-temp-actual]").value || null,
      conc_actual: tr.querySelector("[data-step-conc-actual]").value || null,
      check_actual: tr.querySelector("[data-step-check-actual]").value || null,
      performed_by: tr.querySelector("[data-step-by]").value || null,
      note: tr.querySelector("[data-step-note]").value || null,
    })).filter(s => s.content || s.time_spec || s.temp || s.concentration || s.check_result
                 || s.time_actual || s.temp_actual || s.conc_actual || s.check_actual || s.note);
  }

  async function openCipDetailModal(cipId) {
    const [r, formTypes, equipment] = await Promise.all([
      GET(`/cip/records/${cipId}`), GET("/cip/form-types"), GET("/cip/equipment")]);
    const ft = formTypes.find(f => f.form_type_id === r.form_type_id);
    const eq = equipment.find(e => e.equipment_id === r.equipment_id);
    const stepRows = (r.steps || []).map(s => `<tr><td>${esc(s.step_no || "")}</td><td>${esc(s.content || "")}</td>
      <td class="muted">${esc(s.time_spec || "")}</td><td class="muted">${esc(s.temp || "")}</td><td class="muted">${esc(s.concentration || "")}</td><td class="muted">${esc(s.check_result || "")}</td>
      <td>${esc(s.time_actual || "")}</td><td>${esc(s.temp_actual || "")}</td><td>${esc(s.conc_actual || "")}</td><td>${esc(s.check_actual || "")}</td>
      <td>${esc(s.performed_by || "")}</td><td>${esc(s.note || "")}</td></tr>`).join("");
    modal(`<h3>CIP <code class="k">${esc(r.cip_code)}</code></h3>
      <div class="muted" style="margin-bottom:4px">Batch Number <b>${esc(r.batch_number || "—")}</b> · Order Number <b>${esc(r.order_number || "—")}</b></div>
      <div class="muted" style="margin-bottom:8px">Bắt đầu ${fmt(r.started_at)}${r.ended_at ? " · Kết thúc " + fmt(r.ended_at) : ""}
        ${r.performed_by ? " · Người thực hiện " + esc(r.performed_by) : ""}${r.duty_officer ? " · Trực ca " + esc(r.duty_officer) : ""}</div>
      <div class="tablewrap"><table><thead><tr><th>Bước</th><th>Nội dung</th>
        <th>TC: Thời gian</th><th>TC: Nhiệt độ</th><th>TC: Nồng độ</th><th>TC: Kết quả</th>
        <th>TH: Thời gian</th><th>TH: Nhiệt độ</th><th>TH: Nồng độ</th><th>TH: Kết quả</th>
        <th>Người làm</th><th>Ghi chú</th></tr></thead>
        <tbody>${stepRows || '<tr><td colspan="12" class="muted">Không có bước.</td></tr>'}</tbody></table></div>
      ${r.note ? `<div class="muted" style="margin-top:8px">Ghi chú: ${esc(r.note)}</div>` : ""}
      ${r.result ? `<div style="margin-top:8px">${cipResultBadge(r.result)} · KCS ${esc(r.checked_by || "")} · ${fmt(r.approved_at)}</div>` : ""}
      <button class="btn sm sec" id="cip_print_btn" style="margin-top:10px">🖨️ In biểu mẫu</button>`);
    $("cip_print_btn").onclick = () => printCipRecord(r, ft, eq);
  }

  // In biểu mẫu CIP — 1 lần vệ sinh, so sánh Tiêu chuẩn (TC, khoá theo mẫu) vs Thực tế (TH).
  function printCipRecord(r, ft, eq) {
    const dash = (v) => (v === null || v === undefined || v === "" ? "—" : esc(String(v)));
    const timeUnit = (ft && ft.time_unit) || "phút", tempUnit = (ft && ft.temp_unit) || "°C", concUnit = (ft && ft.conc_unit) || "%";
    const stepRows = (r.steps || []).map(s => `<tr>
      <td>${dash(s.step_no)}</td><td style="text-align:left">${dash(s.content)}</td>
      <td>${dash(s.time_spec)}</td><td>${dash(s.temp)}</td><td>${dash(s.concentration)}</td><td>${dash(s.check_result)}</td>
      <td>${dash(s.time_actual)}</td><td>${dash(s.temp_actual)}</td><td>${dash(s.conc_actual)}</td><td>${dash(s.check_actual)}</td>
      <td>${dash(s.performed_by)}</td><td>${dash(s.note)}</td></tr>`).join("");
    const html = `<!doctype html><html><head><meta charset="utf-8"/><title>CIP — ${esc(r.cip_code)}</title>
      <style>
        @page { size: A4 landscape; margin: 10mm; }
        * { box-sizing: border-box; }
        body{font-family:Arial,Helvetica,sans-serif;color:#000;background:#fff;margin:0;font-size:11.5px;line-height:1.3}
        h2{font-size:15px;margin:6px 0 10px;text-align:center;font-weight:700;text-transform:uppercase}
        .pf-header{display:flex;justify-content:space-between;margin-bottom:6px;font-size:11px}
        .pf-header .right{text-align:center}
        .pf-meta{margin-bottom:8px}
        .pf-meta div{margin-bottom:2px}
        table.pf-tbl{border-collapse:collapse;width:100%;margin-bottom:6px}
        table.pf-tbl th, table.pf-tbl td{border:1px solid #000;padding:3px 5px;text-align:center;font-size:10.5px}
        table.pf-tbl th{background:#eee;font-weight:700}
        .pf-sign{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:30px;text-align:center;font-size:11px}
        .pf-sign b{display:block;margin-bottom:2px}
        .pf-sign span{display:block;color:#555;margin-bottom:40px}
      </style></head><body>
      <div class="pf-header">
        <div><b>CÔNG TY CP BIA &amp; NGK ĐÔNG MAI</b><br/>Pxsx bia ĐM<br/>Số: ${dash(r.cip_code)}</div>
        <div class="right"><b>CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM</b><br/>Độc lập – Tự do – Hạnh phúc</div>
      </div>
      <h2>BIÊN BẢN VỆ SINH THIẾT BỊ (CIP)${ft ? " — " + esc(ft.code) : ""}</h2>
      <div class="pf-meta">
        <div>Batch Number: <b>${dash(r.batch_number)}</b> &nbsp; Order Number: <b>${dash(r.order_number)}</b></div>
        <div>Loại biểu mẫu: <b>${dash(ft && ft.name)}</b> &nbsp; Thiết bị: <b>${dash(eq && (eq.code + " — " + eq.name))}</b></div>
        <div>Ca làm việc: ${dash(r.shift)} &nbsp; Bắt đầu: ${r.started_at ? fmt(r.started_at) : "......."} &nbsp; Kết thúc: ${r.ended_at ? fmt(r.ended_at) : "......."}</div>
        <div>Người thực hiện: ${dash(r.performed_by)} &nbsp; Người trực ca: ${dash(r.duty_officer)}</div>
      </div>
      <table class="pf-tbl"><thead>
        <tr><th rowspan=2>Bước</th><th rowspan=2>Nội dung</th>
          <th colspan=4>Tiêu chuẩn</th><th colspan=4>Thực tế</th><th rowspan=2>Người làm</th><th rowspan=2>Ghi chú</th></tr>
        <tr><th>T.gian (${esc(timeUnit)})</th><th>N.độ (${esc(tempUnit)})</th><th>N.độ dd (${esc(concUnit)})</th><th>Kết quả</th>
          <th>T.gian (${esc(timeUnit)})</th><th>N.độ (${esc(tempUnit)})</th><th>N.độ dd (${esc(concUnit)})</th><th>Kết quả</th></tr>
      </thead>
      <tbody>${stepRows || '<tr><td colspan=12>—</td></tr>'}</tbody></table>
      ${r.note ? `<div>Ghi chú chung: ${dash(r.note)}</div>` : ""}
      <div style="margin-top:8px">Kết quả nghiệm thu: <b>${r.result === "dat" ? "ĐẠT" : r.result === "khong_dat" ? "KHÔNG ĐẠT" : "......."}</b></div>
      <div class="pf-sign">
        <div><b>Người thực hiện</b><span>${dash(r.performed_by)}<br/>(Ký, ghi rõ họ tên)</span></div>
        <div><b>Người trực ca</b><span>${dash(r.duty_officer)}<br/>(Ký, ghi rõ họ tên)</span></div>
        <div><b>KCS nghiệm thu</b><span>${dash(r.checked_by)}<br/>(Ký, ghi rõ họ tên)</span></div>
      </div>
      </body></html>`;
    const w = window.open("", "_blank");
    if (!w) { toast("Trình duyệt chặn cửa sổ in — vui lòng cho phép popup.", "err"); return; }
    w.document.write(html);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 300);
  }

  function openCipApproveModal(cipId) {
    modal(`<h3>Nghiệm thu CIP</h3>
      <div class="field"><label>Kết quả</label><select id="ap_result"><option value="dat">Đạt</option><option value="khong_dat">Không đạt</option></select></div>
      <div class="field"><label>Người kiểm tra (KCS)</label><input id="ap_checked_by" value="${esc((CURRENT_USER && (CURRENT_USER.full_name || CURRENT_USER.username)) || "")}"/></div>
      <div class="field"><label>Ghi chú</label><input id="ap_note"/></div>
      <button class="btn" id="ap_go" style="margin-top:8px">Xác nhận nghiệm thu</button>`);
    $("ap_go").onclick = () => guard(async () => {
      if (!$("ap_checked_by").value) { toast("Nhập người kiểm tra", "err"); return; }
      await POST(`/cip/records/${cipId}/approve`, { result: $("ap_result").value,
        checked_by: $("ap_checked_by").value, note: $("ap_note").value || null });
      closeModal(); toast("Đã nghiệm thu CIP"); render("cip");
    });
  }

  // Gọi từ app.js (data-cip="scopeType|scopeId|label" trên dòng mẻ nấu/lô LM/mẻ lọc/mã chiết) —
  // "gán ngược": người dùng luôn tự chọn/xác nhận, server chỉ gợi ý theo thiết bị+khu vực.
  window.openCipLinkModal = async function (scopeType, scopeId, label, onBack) {
    const [suggestions, linked] = await Promise.all([
      GET(`/cip/suggest?scope_type=${encodeURIComponent(scopeType)}&scope_id=${encodeURIComponent(scopeId)}`),
      GET(`/cip/links?scope_type=${encodeURIComponent(scopeType)}&scope_id=${encodeURIComponent(scopeId)}`),
    ]);
    const linkedIds = new Set(linked.map(l => l.cip_id));
    const groups = suggestions.map(g => {
      const rows = g.records.map(r => {
        const isLinked = linkedIds.has(r.cip_id);
        return `<label style="display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid var(--border);flex-wrap:wrap">
          <input type="checkbox" data-cip-check value="${esc(r.cip_id)}" ${isLinked ? "checked disabled" : ""}/>
          <code class="k">${esc(r.cip_code)}</code>
          <span class="muted">Batch ${esc(r.batch_number || "—")} · Order ${esc(r.order_number || "—")}</span>
          <span class="muted">${fmt(r.started_at)} → ${r.ended_at ? fmt(r.ended_at) : "(chưa kết thúc)"}</span>
          ${cipResultBadge(r.result)}
          <span class="muted" style="margin-left:auto">đã gắn cho ${r.linked_count} mẻ/lô</span>
        </label>`;
      }).join("") || '<div class="muted" style="padding:4px 0">Chưa có lần CIP nào cho thiết bị này.</div>';
      return `<div style="margin-bottom:12px"><b>${esc(g.equipment_code)}</b> — ${esc(g.equipment_name)}<div style="margin-top:4px">${rows}</div></div>`;
    }).join("") || '<div class="muted">Không có thiết bị CIP phù hợp cho công đoạn này — khai báo ở Danh mục CIP trước.</div>';
    const currentRows = linked.map(l => `<tr><td><code class="k">${esc(l.cip_code)}</code></td>
      <td class="muted">${esc(l.equipment_name || "")}</td>
      <td class="muted">Batch ${esc(l.batch_number || "—")} · Order ${esc(l.order_number || "—")}</td>
      <td class="muted">${fmt(l.started_at)} → ${l.ended_at ? fmt(l.ended_at) : "(chưa kết thúc)"}</td>
      <td><button class="btn sm sec" data-cip-unlink="${l.link_id}">Hủy gắn</button></td></tr>`).join("");
    modal(`<h3>Gắn CIP liên quan — ${esc(label)}</h3>
      ${linked.length ? `<div class="muted" style="margin-bottom:4px">Đã gắn (${linked.length}):</div>
        <div class="tablewrap" style="margin-bottom:12px"><table><tbody>${currentRows}</tbody></table></div>` : ""}
      <div class="muted" style="margin-bottom:8px">Chọn (các) lần CIP tương ứng đã thực hiện cho mẻ/lô này — theo thiết bị, thời gian gần nhất trước. Bạn tự xác nhận đúng lần nào, hệ thống không tự gán:</div>
      <div style="max-height:50vh;overflow:auto">${groups}</div>
      <button class="btn" id="cip_link_save" style="margin-top:10px">Lưu gắn kết</button>`, onBack);
    document.querySelectorAll("[data-cip-unlink]").forEach(b => b.onclick = () => guard(async () => {
      if (!confirm("Hủy gắn lần CIP này khỏi mẻ/lô? Không thể hoàn tác.")) return;
      await DELETE(`/cip/links/${b.dataset.cipUnlink}`);
      toast("Đã hủy gắn"); closeModal(); window.openCipLinkModal(scopeType, scopeId, label, onBack);
    }));
    $("cip_link_save").onclick = () => guard(async () => {
      const ids = Array.from(document.querySelectorAll("[data-cip-check]:not(:disabled):checked")).map(c => c.value);
      if (!ids.length) { toast("Chưa chọn lần CIP nào mới", "err"); return; }
      await POST("/cip/links", { scope_type: scopeType, scope_id: scopeId, cip_ids: ids });
      toast("Đã gắn CIP"); closeModal();
    });
  };

  VIEWS.cip = async function () {
    const sec = SUB.cip || "mau";
    const sections = [{ key: "mau", label: "📐 Khai báo biểu mẫu" }, { key: "khaibao", label: "📝 Khai báo CIP" },
      { key: "lichsu", label: "📜 Lịch sử CIP" }, { key: "danhmuc", label: "Danh mục" }];
    const root = $("view-cip");
    const canManage = hasPerm("cip.manage");
    const canApprove = hasPerm("quality.release");
    const [formTypes, equipment] = await Promise.all([GET("/cip/form-types"), GET("/cip/equipment")]);
    let body = "";

    if (sec === "mau") {
      if (!CIP_MAU_FT || !formTypes.some(f => f.form_type_id === CIP_MAU_FT)) {
        CIP_MAU_FT = formTypes.length ? formTypes[0].form_type_id : null;
      }
      const ft = formTypes.find(f => f.form_type_id === CIP_MAU_FT);
      const ftOpt = formTypes.map(f => `<option value="${esc(f.form_type_id)}" ${f.form_type_id === CIP_MAU_FT ? "selected" : ""}>${esc(f.code)} — ${esc(f.name)}</option>`).join("");
      body = !canManage ? '<div class="muted">Bạn không có quyền khai báo biểu mẫu CIP.</div>'
        : !ft ? '<div class="muted">Chưa có loại biểu mẫu nào — thêm ở tab Danh mục trước.</div>'
        : panel("📐 Khai báo biểu mẫu — bảng bước MẪU", `
        <div class="muted" style="margin-bottom:8px">Khai báo trước bảng bước theo ĐÚNG biểu mẫu giấy gốc cho từng loại — khi khai báo 1 lần CIP mới ở tab "Khai báo CIP", chọn đúng loại biểu mẫu sẽ tự điền bảng bước từ đây (vẫn sửa/thêm/bớt tự do được, không khoá cứng).</div>
        <div class="row">
          <div class="field" style="flex:1">
            <label>Loại biểu mẫu</label>
            <input id="mau_ft_q" placeholder="Tìm theo mã/tên..." style="width:100%;margin-bottom:2px"/>
            <select id="mau_ft" style="width:100%">${ftOpt}</select>
          </div>
        </div>
        <div class="row">
          <div class="field"><label>Đơn vị thời gian</label><select id="mau_time_unit">
            ${["giây", "phút", "giờ"].map(u => `<option value="${u}" ${ft.time_unit === u ? "selected" : ""}>${u}</option>`).join("")}</select></div>
          <div class="field"><label>Đơn vị nhiệt độ</label><input id="mau_temp_unit" value="${esc(ft.temp_unit)}" style="width:80px"/></div>
          <div class="field"><label>Đơn vị nồng độ</label><input id="mau_conc_unit" value="${esc(ft.conc_unit)}" style="width:80px"/></div>
        </div>
        <div class="tablewrap" style="margin-top:8px"><table id="mau_steps_tbl">
          <thead><tr><th style="width:50px">Bước</th><th>Nội dung</th><th style="width:100px">Thời gian (${esc(ft.time_unit)})</th>
            <th style="width:80px">Nhiệt độ (${esc(ft.temp_unit)})</th><th style="width:80px">Nồng độ (${esc(ft.conc_unit)})</th><th style="width:110px">Phương pháp kiểm tra</th>
            <th style="width:120px">Người làm</th><th style="width:120px">Ghi chú</th><th style="width:36px"></th></tr></thead>
          <tbody id="mau_steps_body"></tbody></table></div>
        <button class="btn sm sec" id="mau_step_add" style="margin-top:6px">+ Thêm bước</button>
        <div class="row" style="margin-top:10px">
          <button class="btn" id="mau_save">Lưu bảng bước mẫu (tiêu chuẩn)</button>
          <button class="btn sec" id="mau_copy">📋 Copy sang biểu mẫu khác</button>
        </div>`);
    } else if (sec === "khaibao") {
      const ftOpt = formTypes.map(f => `<option value="${esc(f.form_type_id)}" data-area="${esc(f.area)}">${esc(f.code)} — ${esc(f.name)}</option>`).join("");
      const eqOpt = equipment.map(e => `<option value="${esc(e.equipment_id)}" data-area="${esc(e.area)}">${esc(e.code)} — ${esc(e.name)}</option>`).join("");
      body = !canManage ? '<div class="muted">Bạn không có quyền khai báo CIP.</div>' : panel("📝 Khai báo CIP mới", `
        <div class="row">
          <div class="field"><label>Khu vực</label><select id="cip_area">
            <option value="">(tất cả)</option>
            ${Object.entries(CIP_AREA_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}
          </select></div>
          <div class="field" style="flex:1"><label>Loại biểu mẫu</label>
            <input id="cip_ft_q" placeholder="Tìm theo mã/tên..." style="width:100%;margin-bottom:2px"/>
            <select id="cip_ft" style="width:100%">${ftOpt}</select></div>
          <div class="field" style="flex:1"><label>Thiết bị</label>
            <input id="cip_eq_q" placeholder="Tìm theo mã/tên..." style="width:100%;margin-bottom:2px"/>
            <select id="cip_eq" style="width:100%">${eqOpt}</select></div>
        </div>
        <div class="row">
          <div class="field"><label>Batch Number *</label><input id="cip_batch" placeholder="Batch Number (Braumat)" style="width:150px"/></div>
          <div class="field"><label>Order Number *</label><input id="cip_order" placeholder="Order Number (Braumat)" style="width:150px"/></div>
        </div>
        <div class="row">
          <div class="field"><label>Ca làm việc</label><select id="cip_shift" style="width:100px">
            <option value="">(chọn ca)</option><option value="Ca 1">Ca 1</option><option value="Ca 2">Ca 2</option><option value="Ca 3">Ca 3</option>
          </select></div>
          <div class="field"><label>Bắt đầu</label><input id="cip_start" type="datetime-local" value="${toDTLocal(new Date())}"/></div>
          <div class="field"><label>Kết thúc</label><input id="cip_end" type="datetime-local"/></div>
          <div class="field"><label>Người thực hiện</label><input id="cip_by" style="width:150px"/></div>
          <div class="field"><label>Người trực ca</label><input id="cip_duty" style="width:150px"/></div>
        </div>
        <div class="muted" style="margin:6px 0 2px">Cột "TC" = tiêu chuẩn (khoá, sửa ở Khai báo biểu mẫu) — cột "TH" = thực tế, tự nhập khi thực hiện (gõ tự do, kể cả %):</div>
        <div class="tablewrap"><table id="cip_steps_tbl">
          <thead><tr><th style="width:50px">Bước</th><th>Nội dung</th>
            <th style="width:90px">TC: Thời gian</th><th style="width:80px">TC: Nhiệt độ</th><th style="width:80px">TC: Nồng độ</th><th style="width:100px">TC: Kết quả</th>
            <th style="width:90px">TH: Thời gian</th><th style="width:80px">TH: Nhiệt độ</th><th style="width:80px">TH: Nồng độ</th><th style="width:100px">TH: Kết quả</th>
            <th style="width:110px">Người làm</th><th style="width:110px">Ghi chú</th><th style="width:36px"></th></tr></thead>
          <tbody id="cip_steps_body"></tbody></table></div>
        <div class="row" style="margin-top:10px">
          <div class="field" style="flex:1"><label>Ghi chú chung</label><input id="cip_note" style="width:100%"/></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="cip_submit">Khai báo CIP</button></div>
        </div>`);
    } else if (sec === "lichsu") {
      const records = await GET("/cip/records");
      const rows = records.map(r => `<tr>
        <td><code class="k">${esc(r.cip_code)}</code></td>
        <td>${esc(r.batch_number || "—")}</td>
        <td>${esc(r.order_number || "—")}</td>
        <td>${esc(r.form_type_name || "—")}</td>
        <td>${esc(r.equipment_name || "—")}</td>
        <td class="muted">${fmt(r.started_at)}</td>
        <td class="muted">${r.ended_at ? fmt(r.ended_at) : "—"}</td>
        <td>${esc(r.performed_by || "—")}</td>
        <td>${cipResultBadge(r.result)}</td>
        <td style="text-align:right">${r.linked_count}</td>
        <td><button class="btn sm sec" data-cip-view="${r.cip_id}">Xem</button>
          ${canApprove && !r.result ? ` <button class="btn sm" data-cip-approve="${r.cip_id}">Nghiệm thu</button>` : ""}</td>
      </tr>`).join("");
      body = panel(`📜 Lịch sử CIP <span class="muted">(${records.length})</span>`, `
        <input class="searchbox" data-tbl="t_cip_hist" placeholder="Tìm mã CIP/batch/order/thiết bị/biểu mẫu..."/>
        <div class="tablewrap"><table id="t_cip_hist">
          <thead><tr><th>Mã CIP</th><th>Batch</th><th>Order</th><th>Biểu mẫu</th><th>Thiết bị</th><th>Bắt đầu</th><th>Kết thúc</th>
            <th>Người thực hiện</th><th>Kết quả</th><th style="text-align:right">Đã gắn</th><th></th></tr></thead>
          <tbody>${rows || '<tr><td colspan="11" class="muted">Chưa có bản ghi CIP.</td></tr>'}</tbody></table></div>`);
    } else if (sec === "danhmuc") {
      const lines = canManage ? await GET("/lines") : [];
      const ftRows = formTypes.map(f => `<tr><td><code class="k">${esc(f.code)}</code></td><td>${esc(f.name)}</td>
        <td>${esc(CIP_AREA_LABEL[f.area] || f.area)}</td><td class="muted">${esc(f.kind)}</td>
        <td>${f.active ? '<span class="badge available">Dùng</span>' : '<span class="badge obsolete">Ngừng</span>'}</td>
        ${canManage ? `<td style="white-space:nowrap"><button class="btn sm sec" data-ft-edit="${f.form_type_id}">Sửa</button>
          <button class="btn sm sec" data-ft-del="${f.form_type_id}">Xóa</button></td>` : "<td></td>"}</tr>`).join("");
      const eqRows = equipment.map(e => `<tr><td><code class="k">${esc(e.code)}</code></td><td>${esc(e.name)}</td>
        <td>${esc(CIP_AREA_LABEL[e.area] || e.area)}</td>
        <td class="muted">${e.production_line_id ? "Gắn tank/dây chuyền cụ thể" : "Dùng chung"}</td>
        <td>${e.active ? '<span class="badge available">Dùng</span>' : '<span class="badge obsolete">Ngừng</span>'}</td>
        ${canManage ? `<td style="white-space:nowrap"><button class="btn sm sec" data-eq-edit="${e.equipment_id}">Sửa</button>
          <button class="btn sm sec" data-eq-del="${e.equipment_id}">Xóa</button></td>` : "<td></td>"}</tr>`).join("");
      body = `
        ${panel(`📋 Loại biểu mẫu CIP <span class="muted">(${formTypes.length})</span>`, `
          <div class="tablewrap"><table id="t_ciptypes"><thead><tr><th>Mã</th><th>Tên</th><th>Khu vực</th><th>Loại</th><th>Trạng thái</th><th></th></tr></thead>
            <tbody>${ftRows || '<tr><td colspan="6" class="muted">Chưa có loại biểu mẫu.</td></tr>'}</tbody></table></div>
          ${canManage ? `<div class="row" style="margin-top:10px">
            <div class="field"><label>Mã</label><input id="ft_code" placeholder="QT-KCS-QT-BM-22" style="width:170px"/></div>
            <div class="field"><label>Tên</label><input id="ft_name" style="width:260px"/></div>
            <div class="field"><label>Khu vực</label><select id="ft_area">${Object.entries(CIP_AREA_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
            <div class="field"><label>Loại</label><select id="ft_kind"><option value="full">Đầy đủ</option><option value="light">Nhẹ (vd tráng nước)</option></select></div>
            <div class="field" style="align-self:flex-end"><button class="btn" id="ft_add">Thêm</button></div>
          </div>` : ""}`)}
        ${panel(`🛠️ Thiết bị CIP <span class="muted">(${equipment.length})</span>`, `
          <div class="tablewrap"><table id="t_cipequip"><thead><tr><th>Mã</th><th>Tên</th><th>Khu vực</th><th>Loại gắn</th><th>Trạng thái</th><th></th></tr></thead>
            <tbody>${eqRows || '<tr><td colspan="6" class="muted">Chưa có thiết bị.</td></tr>'}</tbody></table></div>
          ${canManage ? `<div class="row" style="margin-top:10px">
            <div class="field"><label>Mã</label><input id="eq_code" placeholder="EQ-..." style="width:150px"/></div>
            <div class="field"><label>Tên</label><input id="eq_name" style="width:220px"/></div>
            <div class="field"><label>Khu vực</label><select id="eq_area">${Object.entries(CIP_AREA_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
            <div class="field"><label>Gắn tank/dây chuyền (tùy chọn)</label><select id="eq_line"><option value="">(dùng chung — luôn hiện)</option>${lines.map(l => `<option value="${esc(l.line_id)}">${esc(l.code)} — ${esc(l.name)}</option>`).join("")}</select></div>
            <div class="field" style="align-self:flex-end"><button class="btn" id="eq_add">Thêm</button></div>
          </div>` : ""}`)}
      `;
    }

    root.innerHTML = subnav("cip", sections, sec) + body;
    wireSubnav("cip");
    wireSearch();
    wirePaginate("t_cip_hist", 15);
    wirePaginate("t_ciptypes", 10);
    wirePaginate("t_cipequip", 10);

    if (sec === "mau" && canManage) {
      const seqRef = { n: 0 };
      const ft = formTypes.find(f => f.form_type_id === CIP_MAU_FT);
      cipFillSteps("mau_steps_body", seqRef, ft ? ft.default_steps : []);
      $("mau_step_add").onclick = () => cipAddStepRow("mau_steps_body", seqRef, null);
      wireSelectSearch("mau_ft", "mau_ft_q");
      $("mau_ft").onchange = () => { CIP_MAU_FT = $("mau_ft").value; render("cip"); };
      $("mau_save").onclick = () => guard(async () => {
        const steps = cipCollectSteps("mau_steps_body");
        await PUT(`/cip/form-types/${ft.form_type_id}`, {
          code: ft.code, name: ft.name, area: ft.area, kind: ft.kind,
          time_unit: $("mau_time_unit").value, temp_unit: $("mau_temp_unit").value, conc_unit: $("mau_conc_unit").value,
          default_steps: steps,
        });
        toast("Đã lưu bảng bước mẫu"); render("cip");
      });
      $("mau_copy").onclick = () => {
        const others = formTypes.filter(f => f.form_type_id !== ft.form_type_id);
        const emptyOthers = others.filter(f => !f.default_steps.length);
        if (!others.length) { toast("Chưa có biểu mẫu nào khác để copy sang.", "err"); return; }
        const opts = others.map(f => `<option value="${esc(f.form_type_id)}" ${f.default_steps.length ? "disabled" : ""}>
          ${esc(f.code)} — ${esc(f.name)}${f.default_steps.length ? " (đã có bước — không copy được)" : " (trống)"}</option>`).join("");
        modal(`
          <h3>📋 Copy bảng bước sang biểu mẫu khác</h3>
          <div class="muted" style="margin-bottom:8px">Chép nguyên bảng bước + đơn vị thời gian/nhiệt độ/nồng độ từ
            <b>${esc(ft.code)}</b> sang 1 biểu mẫu KHÁC — chỉ thực hiện được khi biểu mẫu đích đang TRỐNG (chưa khai báo bước nào).</div>
          ${!emptyOthers.length ? '<div class="muted" style="color:var(--red)">Mọi biểu mẫu khác đều đã có bảng bước — không còn biểu mẫu trống để copy sang.</div>'
            : `<div class="field"><label>Biểu mẫu đích</label><select id="copy_target" style="width:100%">${opts}</select></div>
          <div class="row" style="margin-top:12px"><button class="btn" id="copy_confirm">Copy</button></div>`}`);
        if (emptyOthers.length) {
          $("copy_target").value = emptyOthers[0].form_type_id;
          $("copy_confirm").onclick = () => guard(async () => {
            await POST(`/cip/form-types/${ft.form_type_id}/copy-steps`, { target_form_type_id: $("copy_target").value });
            toast("Đã copy bảng bước"); closeModal();
            CIP_MAU_FT = $("copy_target").value; render("cip");
          });
        }
      };
    } else if (sec === "khaibao" && canManage) {
      const seqRef = { n: 0 };
      const fillFromFormType = () => {
        const ft = formTypes.find(f => f.form_type_id === $("cip_ft").value);
        cipRecordFillSteps("cip_steps_body", seqRef, ft ? ft.default_steps : []);
      };
      fillFromFormType();
      $("cip_ft").onchange = fillFromFormType;
      const applyFilter = () => {
        const area = $("cip_area").value;
        const ftQ = ($("cip_ft_q").value || "").toLowerCase();
        const eqQ = ($("cip_eq_q").value || "").toLowerCase();
        document.querySelectorAll("#cip_ft option").forEach(o => o.hidden =
          (!!area && o.dataset.area !== area) || (!!ftQ && !o.textContent.toLowerCase().includes(ftQ)));
        document.querySelectorAll("#cip_eq option").forEach(o => o.hidden =
          (!!area && o.dataset.area !== area) || (!!eqQ && !o.textContent.toLowerCase().includes(eqQ)));
      };
      $("cip_area").onchange = applyFilter;
      $("cip_ft_q").oninput = applyFilter;
      $("cip_eq_q").oninput = applyFilter;
      $("cip_submit").onclick = () => guard(async () => {
        if (!$("cip_ft").value || !$("cip_eq").value) { toast("Chọn loại biểu mẫu và thiết bị", "err"); return; }
        if (!$("cip_batch").value.trim() || !$("cip_order").value.trim()) { toast("Nhập Batch Number và Order Number (bắt buộc)", "err"); return; }
        if (!$("cip_start").value) { toast("Nhập thời gian bắt đầu", "err"); return; }
        const steps = cipRecordCollectSteps("cip_steps_body");
        await POST("/cip/records", {
          form_type_id: $("cip_ft").value, equipment_id: $("cip_eq").value,
          batch_number: $("cip_batch").value.trim(), order_number: $("cip_order").value.trim(),
          shift: $("cip_shift").value || null,
          started_at: new Date($("cip_start").value).toISOString(),
          ended_at: $("cip_end").value ? new Date($("cip_end").value).toISOString() : null,
          performed_by: $("cip_by").value || null, duty_officer: $("cip_duty").value || null,
          steps, note: $("cip_note").value || null,
        });
        toast("Đã khai báo CIP"); render("cip");
      });
    } else if (sec === "lichsu") {
      document.querySelectorAll("[data-cip-view]").forEach(b => b.onclick = () => openCipDetailModal(b.dataset.cipView));
      document.querySelectorAll("[data-cip-approve]").forEach(b => b.onclick = () => openCipApproveModal(b.dataset.cipApprove));
    } else if (sec === "danhmuc" && canManage) {
      document.querySelectorAll("[data-ft-del]").forEach(b => b.onclick = () => guard(async () => {
        if (!confirm("Xóa loại biểu mẫu này? Không thể hoàn tác.")) return;
        await DELETE(`/cip/form-types/${b.dataset.ftDel}`);
        toast("Đã xóa"); render("cip");
      }));
      document.querySelectorAll("[data-eq-del]").forEach(b => b.onclick = () => guard(async () => {
        if (!confirm("Xóa thiết bị này? Không thể hoàn tác.")) return;
        await DELETE(`/cip/equipment/${b.dataset.eqDel}`);
        toast("Đã xóa"); render("cip");
      }));
      document.querySelectorAll("[data-ft-edit]").forEach(b => b.onclick = () => {
        const f = formTypes.find(x => x.form_type_id === b.dataset.ftEdit);
        modal(`<h3>Sửa loại biểu mẫu CIP</h3>
          <div class="field"><label>Mã</label><input id="ft_e_code" value="${esc(f.code)}"/></div>
          <div class="field" style="margin-top:8px"><label>Tên</label><input id="ft_e_name" value="${esc(f.name)}"/></div>
          <div class="field" style="margin-top:8px"><label>Khu vực</label><select id="ft_e_area">${Object.entries(CIP_AREA_LABEL).map(([k, v]) => `<option value="${k}" ${k === f.area ? "selected" : ""}>${v}</option>`).join("")}</select></div>
          <div class="field" style="margin-top:8px"><label>Loại</label><select id="ft_e_kind">
            <option value="full" ${f.kind === "full" ? "selected" : ""}>Đầy đủ</option>
            <option value="light" ${f.kind === "light" ? "selected" : ""}>Nhẹ (vd tráng nước)</option></select></div>
          <button class="btn" id="ft_e_save" style="margin-top:12px">Lưu</button>`);
        $("ft_e_save").onclick = () => guard(async () => {
          if (!$("ft_e_code").value || !$("ft_e_name").value) { toast("Nhập mã và tên", "err"); return; }
          await PUT(`/cip/form-types/${f.form_type_id}`, {
            code: $("ft_e_code").value, name: $("ft_e_name").value, area: $("ft_e_area").value, kind: $("ft_e_kind").value,
            time_unit: f.time_unit, temp_unit: f.temp_unit, conc_unit: f.conc_unit, default_steps: f.default_steps || [],
          });
          closeModal(); toast("Đã lưu"); render("cip");
        });
      });
      document.querySelectorAll("[data-eq-edit]").forEach(b => b.onclick = () => guard(async () => {
        const e = equipment.find(x => x.equipment_id === b.dataset.eqEdit);
        const lines = await GET("/lines");
        modal(`<h3>Sửa thiết bị CIP</h3>
          <div class="field"><label>Mã</label><input id="eq_e_code" value="${esc(e.code)}"/></div>
          <div class="field" style="margin-top:8px"><label>Tên</label><input id="eq_e_name" value="${esc(e.name)}"/></div>
          <div class="field" style="margin-top:8px"><label>Khu vực</label><select id="eq_e_area">${Object.entries(CIP_AREA_LABEL).map(([k, v]) => `<option value="${k}" ${k === e.area ? "selected" : ""}>${v}</option>`).join("")}</select></div>
          <div class="field" style="margin-top:8px"><label>Gắn tank/dây chuyền (tùy chọn)</label><select id="eq_e_line">
            <option value="">(dùng chung — luôn hiện)</option>
            ${lines.map(l => `<option value="${esc(l.line_id)}" ${l.line_id === e.production_line_id ? "selected" : ""}>${esc(l.code)} — ${esc(l.name)}</option>`).join("")}</select></div>
          <button class="btn" id="eq_e_save" style="margin-top:12px">Lưu</button>`);
        $("eq_e_save").onclick = () => guard(async () => {
          if (!$("eq_e_code").value || !$("eq_e_name").value) { toast("Nhập mã và tên", "err"); return; }
          await PUT(`/cip/equipment/${e.equipment_id}`, {
            code: $("eq_e_code").value, name: $("eq_e_name").value, area: $("eq_e_area").value,
            production_line_id: $("eq_e_line").value || null,
          });
          closeModal(); toast("Đã lưu"); render("cip");
        });
      }));
      $("ft_add").onclick = () => guard(async () => {
        if (!$("ft_code").value || !$("ft_name").value) { toast("Nhập mã và tên", "err"); return; }
        await POST("/cip/form-types", { code: $("ft_code").value, name: $("ft_name").value,
          area: $("ft_area").value, kind: $("ft_kind").value });
        toast("Đã thêm loại biểu mẫu"); render("cip");
      });
      $("eq_add").onclick = () => guard(async () => {
        if (!$("eq_code").value || !$("eq_name").value) { toast("Nhập mã và tên", "err"); return; }
        await POST("/cip/equipment", { code: $("eq_code").value, name: $("eq_name").value,
          area: $("eq_area").value, production_line_id: $("eq_line").value || null });
        toast("Đã thêm thiết bị"); render("cip");
      });
    }
  };
})();
