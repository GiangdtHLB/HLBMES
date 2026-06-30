/* Import Mapping Explorer (Phase 1.1) — wizard CSV/Excel → bảng MES master,
   có Rule Engine, warning/conflict, export report, mapping profile.
   Helper toàn cục từ app.js: VIEWS, GET, POST, esc, toast, $, TOKEN. */
(function () {
  const B = "/integration/import";
  const RULES = ["", "trim", "uppercase", "lowercase", "normalize_uom", "boolean_map",
    "enum_map", "date_parse", "number_parse", "regex_validate", "default_if_empty", "required_if", "lookup"];
  const NEEDS_PARAM = { date_parse: "format dd/MM/yyyy", regex_validate: "pattern regex",
    enum_map: 'JSON map {"src":"tgt"}', lookup: 'JSON map', default_if_empty: "giá trị default" };
  let S = {};
  const reset = () => { S = { step: 1, tab: "wizard", file: null, columns: [], preview: [], targets: [], table: "", schema: null, mappings: {}, defaults: {}, rules: {}, key_field: "code", source_system: "brawmart", vr: null, run: null }; };
  reset();
  const host = () => $("view-import");

  async function uploadFile(f) {
    const fd = new FormData(); fd.append("file", f);
    const res = await fetch("/api" + B + "/upload", { method: "POST", headers: TOKEN ? { Authorization: "Bearer " + TOKEN } : {}, body: fd });
    const t = await res.text(); const d = t ? JSON.parse(t) : null;
    if (!res.ok) throw new Error(d && d.detail ? d.detail : "HTTP " + res.status);
    return d;
  }
  async function downloadExport(runId, fmt) {
    const res = await fetch(`/api${B}/export/${runId}?fmt=${fmt}`, { headers: { Authorization: "Bearer " + TOKEN } });
    if (!res.ok) return toast("Export lỗi", "err");
    const blob = await res.blob(); const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = `import_report.${fmt === "xlsx" ? "xlsx" : "csv"}`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }

  function tabbar() {
    const tabs = [["wizard", "Trình import"], ["history", "Lịch sử"], ["profiles", "Mapping Profiles"]];
    return `<div class="subnav">${tabs.map(([k, l]) => `<a href="#" data-itab="${k}" class="${S.tab === k ? "active" : ""}">${l}</a>`).join("")}</div>`;
  }
  function stepper() {
    const steps = ["1.Upload", "2.Bảng đích", "3.Map+Rule", "4.Validate", "5.Confirm", "6.Kết quả"];
    return `<div style="display:flex;gap:6px;flex-wrap:wrap;margin:8px 0">${steps.map((s, i) => `<span class="badge ${i + 1 === S.step ? "running" : (i + 1 < S.step ? "available" : "planned")}">${esc(s)}</span>`).join("")}</div>`;
  }
  function previewTable(cols, rows, n) {
    if (!cols.length) return "<div class='muted'>(trống)</div>";
    return `<div style="overflow:auto;max-height:300px"><table><thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows.slice(0, n || 20).map(r => `<tr>${cols.map(c => `<td>${esc(String(r[c] ?? ""))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function viewStep1() {
    return `<div class="panel"><h2>Bước 1 — Upload file (.csv/.xlsx, ≤10MB)</h2>
      <div class="field"><input type="file" id="imp_file" accept=".csv,.xlsx"/></div>
      <div class="field" style="max-width:280px">Profile (tùy chọn): <select id="imp_prof"><option value="">— không dùng —</option></select></div>
      <button class="btn" id="imp_up">Tải lên & đọc</button>
      ${S.file ? `<div style="margin-top:10px">✅ <b>${esc(S.file.filename)}</b> — ${S.file.row_count} dòng · ${S.columns.length} cột
        <div class="muted">Cột: ${S.columns.map(esc).join(", ")}</div><h3>Xem trước (≤50 dòng)</h3>${previewTable(S.columns, S.preview, 50)}
        <button class="btn" id="imp_next1" style="margin-top:8px">Tiếp →</button></div>` : ""}</div>`;
  }
  function viewStep2() {
    return `<div class="panel"><h2>Bước 2 — Chọn bảng đích (whitelist master)</h2>
      <div class="field" style="max-width:200px">Source system: <input id="imp_src" value="${esc(S.source_system)}"/></div>
      <div class="field"><select id="imp_tbl"><option value="">— chọn bảng —</option>${S.targets.map(t => `<option value="${t.table}" ${S.table === t.table ? "selected" : ""}>${esc(t.table)} — ${esc(t.description)}</option>`).join("")}</select></div>
      ${S.schema ? `<h3>Cột bảng ${esc(S.table)}</h3><table><thead><tr><th>Cột</th><th>Kiểu</th><th>Bắt buộc</th><th>Unique</th><th>Max</th></tr></thead>
        <tbody>${S.schema.columns.map(c => `<tr><td><code>${esc(c.name)}</code></td><td>${c.type}</td><td>${c.required ? "<b style='color:#e74c3c'>✓</b>" : ""}</td><td>${c.unique ? "✓" : ""}</td><td>${c.max_length ?? ""}</td></tr>`).join("")}</tbody></table>
        <button class="btn sec" id="imp_back2">← Back</button> <button class="btn" id="imp_next2">Tiếp →</button>` : ""}</div>`;
  }
  function viewStep3() {
    const opts = (sel) => `<option value="">— bỏ qua —</option>` + S.columns.map(c => `<option ${sel === c ? "selected" : ""}>${esc(c)}</option>`).join("");
    const ropts = (sel) => RULES.map(r => `<option value="${r}" ${sel === r ? "selected" : ""}>${r || "(không)"}</option>`).join("");
    const keyCands = S.schema.key_candidates || ["code"];
    return `<div class="panel"><h2>Bước 3 — Map cột + Rule (file → ${esc(S.table)})</h2>
      <div class="field" style="max-width:280px">Khóa upsert: <select id="imp_key">${keyCands.map(k => `<option ${S.key_field === k ? "selected" : ""}>${esc(k)}</option>`).join("")}</select></div>
      <table><thead><tr><th>Cột MES</th><th>BB</th><th>← Cột file</th><th>Rule</th><th>Tham số rule</th><th>Default</th></tr></thead>
      <tbody>${S.schema.columns.filter(c => !c.primary_key).map(c => { const ru = S.rules[c.name] || {}; return `<tr>
        <td><code>${esc(c.name)}</code> <span class="muted">(${c.type})</span></td>
        <td>${c.required ? "<b style='color:#e74c3c'>✓</b>" : ""}</td>
        <td><select data-map="${esc(c.name)}">${opts(S.mappings[c.name] || "")}</select></td>
        <td><select data-rule="${esc(c.name)}">${ropts(ru.type || "")}</select></td>
        <td><input data-rp="${esc(c.name)}" value="${esc(ru.params ? JSON.stringify(ru.params) : (ru._raw || ""))}" placeholder="${NEEDS_PARAM[ru.type] || ""}" style="width:170px"/></td>
        <td><input data-def="${esc(c.name)}" value="${esc(S.defaults[c.name] || "")}" style="width:120px"/></td></tr>`; }).join("")}</tbody></table>
      <div style="margin-top:8px"><button class="btn sec" id="imp_back3">← Back</button>
        <button class="btn" id="imp_valid">Validate →</button> <button class="btn sec" id="imp_saveprof">💾 Lưu profile</button></div></div>`;
  }
  function issueTable(list) {
    return `<div style="overflow:auto;max-height:240px"><table><thead><tr><th>Dòng</th><th>Loại</th><th>Cột</th><th>Giá trị</th><th>Thông báo</th></tr></thead>
      <tbody>${list.map(e => `<tr><td>${e.row_index + 1}</td><td>${badgeKind(e.kind)}</td><td>${esc(e.column || "")}</td><td>${esc(String(e.value || ""))}</td><td>${esc(e.message)}</td></tr>`).join("")}</tbody></table></div>`;
  }
  const badgeKind = (k) => `<span class="badge ${k === "warning" ? "due" : "overdue"}">${k}</span>`;
  function viewStep4() {
    const s = S.vr.summary;
    return `<div class="panel"><h2>Bước 4 — Validate (chưa ghi DB)</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
        <span class="badge available">Insert ${s.insert}</span><span class="badge running">Update ${s.update}</span>
        <span class="badge planned">Skip ${s.skip}</span><span class="badge ${s.error ? "overdue" : "available"}">Error ${s.error}</span>
        <span class="badge ${s.conflict ? "overdue" : "available"}">Conflict ${s.conflict}</span><span class="badge ${s.warning ? "due" : "available"}">Warning ${s.warning}</span>
        <span class="badge">Tổng ${s.total}</span></div>
      ${(S.vr.errors.length || S.vr.conflicts.length) ? `<h3>Conflict / Error (chặn import)</h3>${issueTable([...S.vr.conflicts, ...S.vr.errors])}` : "<div class='muted'>Không có conflict/error.</div>"}
      ${S.vr.warnings.length ? `<h3>Warning (không chặn)</h3>${issueTable(S.vr.warnings)}` : ""}
      <div style="margin-top:8px"><button class="btn sec" id="imp_back4">← Back</button>
        <button class="btn" id="imp_confirm" ${s.insert + s.update === 0 ? "disabled" : ""}>✅ CONFIRM IMPORT (${s.insert + s.update} dòng)</button></div></div>`;
  }
  function viewStep6() {
    const r = S.run;
    return `<div class="panel"><h2>Bước 6 — Kết quả</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><span class="badge available">Inserted ${r.inserted}</span><span class="badge running">Updated ${r.updated}</span>
        <span class="badge planned">Skipped ${r.skipped}</span><span class="badge ${r.errored ? "overdue" : "available"}">Errored ${r.errored}</span>
        <span class="badge ${r.warning ? "due" : "available"}">Warning ${r.warning || 0}</span><span class="badge">${r.duration_ms}ms · ${esc(r.status)}</span></div>
      <div style="margin-top:10px"><button class="btn" id="imp_new">Import file mới</button>
        <button class="btn sec" id="imp_expcsv">⬇ Export CSV</button> <button class="btn sec" id="imp_expx">⬇ Export Excel</button>
        <button class="btn sec" id="imp_gohist">Lịch sử</button></div></div>`;
  }

  function renderWizard() {
    let body = "";
    if (S.step === 1) body = viewStep1(); else if (S.step === 2) body = viewStep2(); else if (S.step === 3) body = viewStep3();
    else if (S.step === 4) body = viewStep4(); else if (S.step === 6) body = viewStep6();
    host().innerHTML = tabbar() + `<div class="panel"><div class="muted">UAT/Test — chỉ import master data; cột dư→raw_payload; rule cấu hình động (không hardcode).</div></div>` + stepper() + body;
    wireTabs(); wireWizard();
    if (S.step === 1) loadProfilesInto();
  }
  async function loadProfilesInto() {
    if (!$("imp_prof")) return;
    try {
      const ps = (await GET(B + "/profiles")).profiles;
      $("imp_prof").innerHTML = `<option value="">— không dùng —</option>` + ps.map(p => `<option value="${p.profile_id}">${esc(p.name)} (${esc(p.target_table)})</option>`).join("");
    } catch (e) { /* im lặng */ }
  }

  function collectMap() {
    document.querySelectorAll("[data-map]").forEach(s => { if (s.value) S.mappings[s.dataset.map] = s.value; else delete S.mappings[s.dataset.map]; });
    document.querySelectorAll("[data-def]").forEach(i => { if (i.value) S.defaults[i.dataset.def] = i.value; else delete S.defaults[i.dataset.def]; });
    document.querySelectorAll("[data-rule]").forEach(sel => {
      const col = sel.dataset.rule; const type = sel.value;
      if (!type) { delete S.rules[col]; return; }
      const rp = document.querySelector(`[data-rp="${col}"]`); const raw = rp ? rp.value.trim() : "";
      const rule = { type }; rule._raw = raw;
      if (raw) {
        if (type === "date_parse") rule.params = { format: raw };
        else if (type === "regex_validate") rule.params = { pattern: raw };
        else if (type === "default_if_empty") rule.params = { value: raw };
        else if (type === "enum_map" || type === "lookup") { try { rule.params = { map: JSON.parse(raw) }; } catch (e) { toast(`Param ${col} không phải JSON`, "err"); } }
      }
      S.rules[col] = rule;
    });
  }

  function wireWizard() {
    const up = $("imp_up");
    if (up) up.onclick = async () => {
      const f = $("imp_file").files[0]; if (!f) return toast("Chọn file", "err");
      try {
        const d = await uploadFile(f); S.file = d; S.columns = d.columns; S.preview = d.preview;
        const pid = $("imp_prof") && $("imp_prof").value;
        if (pid) await applyProfile(pid);
        renderWizard(); toast("Đã đọc " + d.row_count + " dòng");
      } catch (e) { toast(e.message, "err"); }
    };
    if ($("imp_next1")) $("imp_next1").onclick = async () => {
      if (!S.targets.length) { try { S.targets = (await GET(B + "/targets")).targets; } catch (e) { return toast(e.message, "err"); } }
      S.step = 2; renderWizard();
    };
    if ($("imp_src")) $("imp_src").onchange = (e) => { S.source_system = e.target.value; };
    const tbl = $("imp_tbl");
    if (tbl) tbl.onchange = async () => {
      S.table = tbl.value; S.schema = null;
      if (S.table) { try { S.schema = await GET(B + "/targets/" + S.table); if (!S.key_field) S.key_field = (S.schema.key_candidates || ["code"])[0]; } catch (e) { toast(e.message, "err"); } }
      renderWizard();
    };
    if ($("imp_back2")) $("imp_back2").onclick = () => { S.step = 1; renderWizard(); };
    if ($("imp_next2")) $("imp_next2").onclick = () => {
      S.schema.columns.forEach(c => { if (!S.mappings[c.name]) { const m = S.columns.find(x => x.toLowerCase().replace(/[^a-z]/g, "") === c.name.toLowerCase().replace(/[^a-z]/g, "")); if (m) S.mappings[c.name] = m; } });
      S.step = 3; renderWizard();
    };
    if ($("imp_back3")) $("imp_back3").onclick = () => { S.step = 2; renderWizard(); };
    if ($("imp_key")) $("imp_key").onchange = (e) => { S.key_field = e.target.value; };
    if ($("imp_valid")) $("imp_valid").onclick = async () => {
      collectMap();
      try { S.vr = await POST(B + "/validate", { file_id: S.file.file_id, target_table: S.table, mappings: S.mappings, defaults: S.defaults, rules: cleanRules(), key_field: S.key_field }); S.step = 4; renderWizard(); }
      catch (e) { toast(e.message, "err"); }
    };
    if ($("imp_saveprof")) $("imp_saveprof").onclick = async () => {
      collectMap(); const name = prompt("Tên profile:", (S.source_system || "") + " " + S.table); if (!name) return;
      try { await POST(B + "/profiles", { name, target_table: S.table, source_system: S.source_system, source_type: S.file.source_type, key_field: S.key_field, mappings: S.mappings, defaults: S.defaults, rules: cleanRules() }); toast("Đã lưu profile"); }
      catch (e) { toast(e.message, "err"); }
    };
    if ($("imp_back4")) $("imp_back4").onclick = () => { S.step = 3; renderWizard(); };
    if ($("imp_confirm")) $("imp_confirm").onclick = async () => {
      if (!confirm("Xác nhận import vào " + S.table + "?")) return;
      try { S.run = await POST(B + "/run", { file_id: S.file.file_id, target_table: S.table, mappings: S.mappings, defaults: S.defaults, rules: cleanRules(), key_field: S.key_field, source_system: S.source_system }); S.step = 6; renderWizard(); toast("Import xong"); }
      catch (e) { toast(e.message, "err"); }
    };
    if ($("imp_new")) $("imp_new").onclick = () => { reset(); renderWizard(); };
    if ($("imp_expcsv")) $("imp_expcsv").onclick = () => downloadExport(S.run.run_id, "csv");
    if ($("imp_expx")) $("imp_expx").onclick = () => downloadExport(S.run.run_id, "xlsx");
    if ($("imp_gohist")) $("imp_gohist").onclick = () => { S.tab = "history"; renderTab(); };
  }
  const cleanRules = () => { const o = {}; Object.entries(S.rules).forEach(([k, v]) => { const c = { type: v.type }; if (v.params) c.params = v.params; o[k] = c; }); return o; };

  async function applyProfile(pid) {
    const p = await GET(B + "/profiles/" + pid);
    if (!S.targets.length) S.targets = (await GET(B + "/targets")).targets;
    S.table = p.target_table; S.source_system = p.source_system || S.source_system; S.key_field = p.key_field || "code";
    S.mappings = { ...p.mappings }; S.defaults = { ...p.defaults }; S.rules = {};
    Object.entries(p.rules || {}).forEach(([k, v]) => { S.rules[k] = { ...v, _raw: v.params ? JSON.stringify(v.params).replace(/[{}"]/g, m => m) : "" }; });
    S.schema = await GET(B + "/targets/" + S.table);
    toast("Đã áp profile: " + p.name);
  }

  async function renderHistory() {
    let runs = []; try { runs = (await GET(B + "/history")).runs; } catch (e) { host().innerHTML = tabbar() + `<div class="panel">${esc(e.message)}</div>`; wireTabs(); return; }
    host().innerHTML = tabbar() + `<div class="panel"><h2>Lịch sử import</h2>
      <table><thead><tr><th>Bảng</th><th>Trạng thái</th><th>Tổng</th><th>Ins</th><th>Upd</th><th>Skip</th><th>Err</th><th>ms</th><th>Người</th><th></th></tr></thead>
      <tbody>${runs.map(r => `<tr><td>${esc(r.target_table)}</td><td>${esc(r.status)}</td><td>${r.total}</td><td>${r.inserted}</td><td>${r.updated}</td><td>${r.skipped}</td>
        <td>${r.errored ? `<b style='color:#e74c3c'>${r.errored}</b>` : 0}</td><td>${r.duration_ms}</td><td>${esc(r.run_by || "")}</td>
        <td><a href="#" data-err="${r.run_id}">xem</a> · <a href="#" data-exp="${r.run_id}">CSV</a></td></tr>`).join("")}</tbody></table><div id="imp_errbox"></div></div>`;
    wireTabs();
    document.querySelectorAll("[data-err]").forEach(a => a.onclick = async (e) => { e.preventDefault(); const errs = (await GET(B + "/errors/" + a.dataset.err)).errors;
      $("imp_errbox").innerHTML = `<h3>Chi tiết</h3>${issueTable(errs.map(x => ({ row_index: x.row_index, kind: x.severity, column: x.column, value: x.value, message: x.message })))}`; });
    document.querySelectorAll("[data-exp]").forEach(a => a.onclick = (e) => { e.preventDefault(); downloadExport(a.dataset.exp, "csv"); });
  }
  async function renderProfiles() {
    let profs = []; try { profs = (await GET(B + "/profiles")).profiles; } catch (e) { host().innerHTML = tabbar() + `<div class="panel">${esc(e.message)}</div>`; wireTabs(); return; }
    host().innerHTML = tabbar() + `<div class="panel"><h2>Mapping Profiles</h2>
      <div class="muted">Lưu mapping + rule để tái dùng khi Brawmart đổi cấu trúc file (không sửa code).</div>
      <table><thead><tr><th>Tên</th><th>Bảng</th><th>Source</th><th>Key</th><th></th></tr></thead>
      <tbody>${profs.map(p => `<tr><td>${esc(p.name)}</td><td>${esc(p.target_table)}</td><td>${esc(p.source_type)}</td><td>${esc(p.key_field)}</td>
        <td><a href="#" data-apply="${p.profile_id}">Áp dụng</a></td></tr>`).join("")}</tbody></table></div>`;
    wireTabs();
    document.querySelectorAll("[data-apply]").forEach(a => a.onclick = async (e) => { e.preventDefault(); try { await applyProfile(a.dataset.apply); S.tab = "wizard"; S.step = S.file ? 3 : 1; renderWizard(); } catch (err) { toast(err.message, "err"); } });
  }
  function wireTabs() { document.querySelectorAll("[data-itab]").forEach(a => a.onclick = (e) => { e.preventDefault(); S.tab = a.dataset.itab; renderTab(); }); }
  function renderTab() { if (S.tab === "history") renderHistory(); else if (S.tab === "profiles") renderProfiles(); else renderWizard(); }

  VIEWS.import = function () { renderTab(); };
})();
