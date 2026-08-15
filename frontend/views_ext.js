"use strict";
// ============================================================================
// Views mở rộng (phân hệ chiều sâu) — nạp SAU app.js, dùng chung helper toàn cục:
// GET/POST/PUT, $, esc, badge, fmt, toast, guard, modal, closeModal, CH, render,
// CURRENT_USER. Đăng ký vào VIEWS + ALL_VIEWS toàn cục.
//   recipeadv (#3) · dispense (#6) · qclab (#7) · oee (#8)
// ============================================================================
(function () {
  ["recipeadv", "dispense", "qclab", "oee", "isa88", "schedule", "wms", "packaging", "cip"].forEach(v => { if (!ALL_VIEWS.includes(v)) ALL_VIEWS.push(v); });

  let XK_CART = [];   // {product_name, lot_code, unit_type, quantity} — Xuất kho: nhiều dòng, gửi 1 lần
  let DC_CART = [];   // {product_name, lot_code, unit_type, quantity} — Điều chuyển: mirror XK_CART

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

  // ---------- Lệnh đóng hàng → Biên bản bàn giao hàng hóa (theo xe) ----------
  async function openLoadSlipModal(loadSlipId) {
    const s = await GET(`/wms/load-slips/${loadSlipId}`);
    const lineRows = s.lines.map(l => `<tr class="${l.is_promo ? "row-cyan" : ""}">
      <td>${l.seq + 1}</td><td>${esc(l.product_name)}</td><td>${l.quantity}</td><td>${esc(l.uom)}</td>
      <td class="muted">${l.is_promo ? "Khuyến mại — hàng lẻ" : ""}</td><td class="muted">${esc(l.note || "")}</td></tr>`).join("");
    modal(`<h3>Biên bản bàn giao hàng hóa — <code class="k">${esc(s.slip_code)}</code></h3>
      <div class="muted" style="margin-bottom:8px">
        Sheet ${esc(s.sheet_type)} · ${esc(s.shift_label || "")} ${s.order_date ? new Date(s.order_date).toLocaleDateString("vi-VN") : ""} ·
        Xe <b>${esc(s.vehicle_plate)}</b> · Lái xe <b>${esc(s.driver_name || "—")}</b><br/>
        Tuyến: ${esc(s.routes || "—")}${s.note ? ` · Ghi chú: ${esc(s.note)}` : ""}</div>
      <div class="row">
        <div class="field"><label>Bên giao — Họ tên</label><input id="ld_issuer_name" value="${esc(s.issuer_name || "")}"/></div>
        <div class="field"><label>Chức danh</label><input id="ld_issuer_title" value="${esc(s.issuer_title || "")}"/></div>
        <div class="field"><label>Phòng ban</label><input id="ld_issuer_dept" value="${esc(s.issuer_dept || "")}"/></div>
      </div>
      <div class="row">
        <div class="field"><label>Bên nhận — Họ tên</label><input id="ld_recipient_name" value="${esc(s.recipient_name || "")}"/></div>
        <div class="field"><label>Chức danh</label><input id="ld_recipient_title" value="${esc(s.recipient_title || "")}"/></div>
        <div class="field"><label>Đơn vị</label><input id="ld_recipient_unit" value="${esc(s.recipient_unit || "")}"/></div>
      </div>
      <div class="tablewrap" style="max-height:45vh"><table>
        <thead><tr><th>TT</th><th>Hàng hóa</th><th>SL</th><th>ĐVT</th><th>Loại</th><th>Ghi chú</th></tr></thead>
        <tbody>${lineRows || '<tr><td colspan=6 class="muted">Chưa có dòng hàng hóa.</td></tr>'}</tbody></table></div>
      <div class="row" style="margin-top:10px">
        <button class="btn sec" id="ld_save">Lưu</button>
        <button class="btn" id="ld_print">🖨️ In biên bản</button>
      </div>`);
    $("ld_save").onclick = () => guard(async () => {
      const updated = await PUT(`/wms/load-slips/${loadSlipId}`, {
        issuer_name: $("ld_issuer_name").value.trim() || null,
        issuer_title: $("ld_issuer_title").value.trim() || null,
        issuer_dept: $("ld_issuer_dept").value.trim() || null,
        recipient_name: $("ld_recipient_name").value.trim() || null,
        recipient_title: $("ld_recipient_title").value.trim() || null,
        recipient_unit: $("ld_recipient_unit").value.trim() || null,
      });
      Object.assign(s, updated);
      toast("Đã lưu");
    });
    $("ld_print").onclick = () => printLoadSlip(s);
  }

  // Danh mục hàng hóa cố định đúng theo mẫu giấy in sẵn (BIÊN BẢN BÀN GIAO HÀNG HÓA, mẫu số
  // .../20YY/BBBG-BHL) — 15 dòng luôn in đủ (kể cả SL trống) giống hệt sổ giấy đóng quyển,
  // khớp với danh mục SKU thật trong Danh mục Sản phẩm thành phẩm. Cột SL khớp theo từ khóa
  // trong product_name (lấy từ tiêu đề cột file Excel lệnh đóng hàng) — không phân biệt hoa/
  // thường/dấu; nếu 1 dòng dữ liệu không khớp dòng cố định nào, dòng đó vẫn được in thêm vào
  // cuối bảng (không âm thầm bỏ sót số liệu).
  const LOADSLIP_FIXED_GOODS = [
    { label: "Bia chai 330ml Classic", dvt: "Ket", mota: "Đóng thùng (1 thùng x 24 chai)", must: ["chai", "classic"], not: ["450"] },
    { label: "Bia chai 450ml Classic", dvt: "Ket", mota: "Đóng thùng (1 thùng x 20 chai)", must: ["chai", "classic", "450"] },
    { label: "Bia chai 330ml Legend", dvt: "Ket", mota: "Đóng thùng (1 thùng x 24 chai)", must: ["chai", "legend"] },
    { label: "Bia chai 330ml Sapphire", dvt: "Ket", mota: "Đóng thùng (1 thùng x 24 chai)", must: ["chai", "sapphire"], not: ["golden"] },
    { label: "Bia chai 330ml Sapphire Golden", dvt: "Ket", mota: "Đóng thùng (1 thùng x 24 chai)", must: ["chai", "sapphire", "golden"] },
    { label: "Bia lon 330ml Legend", dvt: "Hộp", mota: "Đóng thùng (1 thùng x 24 lon)", must: ["lon", "legend"], not: ["sleek"] },
    { label: "Bia lon 330ml Sapphire", dvt: "Hộp", mota: "Đóng thùng (1 thùng x 24 lon)", must: ["lon", "sapphire"], not: ["golden", "sleek"] },
    { label: "Bia lon 330ml Legend - Sleek", dvt: "Hộp", mota: "Đóng thùng (1 thùng x 24 lon)", must: ["lon", "legend", "sleek"] },
    { label: "Bia lon 330ml Sapphire - Sleek", dvt: "Hộp", mota: "Đóng thùng (1 thùng x 24 lon)", must: ["lon", "sapphire", "sleek"], not: ["golden"] },
    { label: "Bia lon 330ml Sapphire Golden (ít béo)", dvt: "Hộp", mota: "Đóng thùng (1 thùng x 24 lon)", must: ["lon", "sapphire", "golden"], not: ["sleek"] },
    { label: "Bia lon 330ml Hạ Long IDOL", dvt: "Hộp", mota: "Đóng thùng (1 thùng x 24 lon)", must: ["lon", "idol"] },
    { label: "Bia tươi Sapphire 20L", dvt: "Keg", mota: "Nguyên bình", must: ["sapphire"], must_any: ["tươi", "20"] },
    { label: "Bia tươi HẠ LONG 20L", dvt: "Keg", mota: "Nguyên bình", must: ["tươi", "long"], not: ["legend", "sapphire"] },
    { label: "Bia hơi 30L", dvt: "Keg", mota: "Nguyên Bom 30L, đóng nắp bạc", must: ["hơi"] },
    { label: "Bia tươi 2L", dvt: "Keg", mota: "Nguyên Keg, đóng nắp bạc", must: ["tươi", "2l"] },
  ];
  const _normKey = (s) => (s || "").toLowerCase()
    .normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d");
  function matchLoadSlipLines(lines) {
    const norm = lines.map(l => ({ ...l, _n: _normKey(l.product_name) }));
    const used = new Set();
    const fixedRows = LOADSLIP_FIXED_GOODS.map(g => {
      const gMust = (g.must || []).map(_normKey);
      const gNot = (g.not || []).map(_normKey);
      const gAny = (g.must_any || []).map(_normKey);
      const hit = norm.find(l => !used.has(l.line_id)
        && gMust.every(k => l._n.includes(k))
        && !gNot.some(k => l._n.includes(k))
        && (gAny.length === 0 || gAny.some(k => l._n.includes(k))));
      if (hit) used.add(hit.line_id);
      return { ...g, qty: hit ? hit.quantity : null, note: hit ? hit.note : null, matched: hit || null };
    });
    const extra = norm.filter(l => !used.has(l.line_id));
    return { fixedRows, extra };
  }

  // HTML "BIÊN BẢN BÀN GIAO HÀNG HÓA" dùng chung cho cả Lệnh đóng hàng (printLoadSlip) và
  // Xuất kho thành phẩm (printShipmentHandoverSlip) — cùng 1 mẫu giấy in sẵn, khác nguồn dữ liệu.
  // opts: {code, dateObj, issuer:{name,title,dept}, recipient:{name,title,unit,dept}, rowsHtml}
  function bienBanBanGiaoHtml(opts) {
    const dash = (v) => (v === null || v === undefined || v === "" ? "" : esc(String(v)));
    const year = (opts.dateObj || new Date()).getFullYear();
    const issuer = opts.issuer || {}, recipient = opts.recipient || {};
    const recipientUnitLabel = opts.recipientUnitLabel || "Đơn vị";
    return `<!doctype html><html><head><meta charset="utf-8"/><title>Biên bản bàn giao — ${esc(opts.code)}</title>
      <style>
        @page { size: A4; margin: 14mm; }
        * { box-sizing: border-box; }
        body{font-family:"Times New Roman",Times,serif;color:#000;background:#fff;margin:0;font-size:13px;line-height:1.35}
        .bg-head{display:flex;justify-content:space-between;font-weight:700;text-align:center;margin-bottom:2px}
        .bg-head .r{font-weight:400}
        .bg-head .u{text-decoration:underline;height:0;border:none;border-top:1px solid #000;width:70%;margin:2px auto 0}
        .bg-no{margin:4px 0 6px}
        .bg-dest{margin:0 0 8px;font-weight:700}
        h2{font-size:17px;margin:6px 0 2px;text-align:center}
        .bg-sub{text-align:center;font-style:italic;font-size:12px;margin-bottom:10px}
        table.bg-parties{border-collapse:collapse;width:100%;margin-bottom:8px}
        table.bg-parties th, table.bg-parties td{border:1px solid #000;padding:4px 8px;vertical-align:top;font-size:12.5px}
        table.bg-parties th{background:#eee;text-align:center}
        .bg-note{margin-bottom:8px}
        h3{font-size:13.5px;margin:0 0 4px;text-align:center}
        table.bg-tbl{border-collapse:collapse;width:100%;margin-bottom:6px}
        table.bg-tbl th, table.bg-tbl td{border:1px solid #000;padding:3px 6px;font-size:12px}
        table.bg-tbl th{background:#eee;text-align:center}
      </style></head><body>
      <div class="bg-head"><div style="text-align:left">CÔNG TY CỔ PHẦN<br/>BIA &amp; NGK HẠ LONG</div>
        <div class="r">CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM<br/><b>Độc lập – Tự do – Hạnh phúc</b></div></div>
      <div class="bg-no">Số: ${dash(opts.code)}</div>
      ${opts.destination ? `<div class="bg-dest">Nơi xuất đến: ${dash(opts.destination)}</div>` : ""}
      <h2>BIÊN BẢN BÀN GIAO HÀNG HÓA</h2>
      <div class="bg-sub">(Theo (Hợp đồng/PO/Phụ lục…….) số …………của Hợp đồng phân phối số…………/BHL/${year})</div>
      <table class="bg-parties">
        <thead><tr><th style="width:50%">BÊN GIAO (NỘI BỘ BHL)</th><th style="width:50%">BÊN NHẬN</th></tr></thead>
        <tbody>
          <tr><td>Họ và tên: <b>${dash(issuer.name)}</b></td><td>Họ và tên: <b>${dash(recipient.name)}</b></td></tr>
          <tr><td>Chức danh: ${dash(issuer.title)}</td><td>Chức danh: ${dash(recipient.title)}</td></tr>
          <tr><td>Phòng/ban: ${dash(issuer.dept)}</td><td>${esc(recipientUnitLabel)}: ${dash(recipient.unit)}</td></tr>
          <tr><td>&nbsp;</td><td>Phòng/ban: ${dash(recipient.dept)}</td></tr>
          <tr><td>Chữ ký:</td><td>Chữ ký:</td></tr>
          <tr><td>SĐT:</td><td>SĐT:</td></tr>
          <tr><td>Giờ giao:.......h.......phút, ngày ....../....../${year}</td>
            <td>Giờ nhận:.......h.......phút, ngày ....../....../${year}</td></tr>
        </tbody>
      </table>
      <div class="bg-note">Hai bên xác nhận đã giao, nhận đầy đủ số lượng và chủng loại hàng hóa như liệt kê dưới đây.<br/>
        Biên bản này được lập thành hai (02) bản, mỗi bên giữ một (01) bản có giá trị pháp lý như nhau.</div>
      <h3>DANH MỤC HÀNG HÓA BÀN GIAO</h3>
      <table class="bg-tbl">
        <thead><tr><th>TT</th><th>Hàng hóa bàn giao</th><th>SL</th><th>ĐVT</th><th>Mô tả</th><th>Ghi chú</th></tr></thead>
        <tbody>${opts.rowsHtml}</tbody>
      </table>
      </body></html>`;
  }

  function printLoadSlip(s) {
    const dash = (v) => (v === null || v === undefined || v === "" ? "" : esc(String(v)));
    const { fixedRows, extra } = matchLoadSlipLines(s.lines);
    // Chỉ in dòng có số lượng thật — hàng hóa cố định nào không xuất trong phiếu này thì bỏ
    // hẳn khỏi bảng in (không để dòng trống), giữ nguyên nội dung Mô tả cho các dòng còn lại.
    const keptFixed = fixedRows.filter(g => g.qty != null);
    const fixedHtml = keptFixed.map((g, i) => `<tr>
      <td style="text-align:center">${i + 1}</td><td>${esc(g.label)}</td>
      <td style="text-align:center">${g.qty}</td><td style="text-align:center">${esc(g.dvt)}</td>
      <td>${esc(g.mota)}</td><td>${dash(g.note)}</td></tr>`).join("");
    const extraHtml = extra.map((l, i) => `<tr>
      <td style="text-align:center">${keptFixed.length + i + 1}</td><td>${dash(l.product_name)}</td>
      <td style="text-align:center">${l.quantity}</td><td style="text-align:center">${dash(l.uom)}</td>
      <td>${l.is_promo ? "Khuyến mại — hàng lẻ, chưa đủ vỉ/thùng" : ""}</td><td>${dash(l.note)}</td></tr>`).join("");
    const html = bienBanBanGiaoHtml({
      code: s.slip_code, dateObj: s.order_date ? new Date(s.order_date) : new Date(),
      issuer: { name: s.issuer_name, title: s.issuer_title, dept: s.issuer_dept },
      recipient: { name: s.recipient_name, title: s.recipient_title, unit: s.recipient_unit, dept: s.recipient_dept },
      rowsHtml: fixedHtml + extraHtml,
    });
    const w = window.open("", "_blank");
    if (!w) { toast("Trình duyệt chặn cửa sổ in — vui lòng cho phép popup.", "err"); return; }
    w.document.write(html);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 300);
  }

  // ---------- Xuất kho thành phẩm (Shipment) → cùng mẫu Biên bản bàn giao hàng hóa ----------
  // Shipment.lines chỉ có mã SKU (product) + count (số vỉ/keg), không có tên hiển thị — tra
  // /finished-products để lấy tên tiếng Việt làm căn cứ khớp từ khóa vào 15 dòng cố định
  // (matchLoadSlipLines vốn khớp theo product_name, xem LOADSLIP_FIXED_GOODS ở trên).
  async function printShipmentHandoverSlip(shipment) {
    let nameByCode = {}, utNameByCode = {};
    try {
      const fps = await GET("/finished-products");
      nameByCode = Object.fromEntries(fps.map(p => [p.code, p.name]));
    } catch (e) { /* vẫn in được — chỉ thiếu tên đầy đủ, dùng tạm mã SKU */ }
    try {
      const uts = await GET("/unit-types");
      utNameByCode = Object.fromEntries(uts.map(u => [u.code, u.name]));
    } catch (e) { /* vẫn in được — chỉ thiếu tên loại đơn vị cho dòng ngoài danh mục cố định */ }
    const dash = (v) => (v === null || v === undefined || v === "" ? "" : esc(String(v)));
    const linesForMatch = (shipment.lines || []).map((l, i) =>
      ({ line_id: i, product_name: nameByCode[l.product] || l.product, quantity: l.count,
         consigned: l.consigned, near_expiry: l.near_expiry, type: l.type, unit_type: l.unit_type }));
    // Ghi chú theo loại xuất: CHỈ ghi khi là khuyến mại/xuất tặng/đổi trả — đây là những lô cần
    // bên nhận đối chiếu đúng bản chất để không tính vào công nợ/đơn hàng thường. Bia cận date
    // VÀ bia gửi thì KHÔNG ghi gì thêm (theo yêu cầu người dùng — bàn giao như hàng thường,
    // không cần lộ 2 thông tin nội bộ này ra biên bản giấy). "Loại xuất" (promo/return) RIÊNG
    // TỪNG DÒNG (xem services/wms.py::list_shipments, FinishedGoodsUnit.shipment_line_type).
    const lineNoteFor = (l) => {
      if (!l || l.near_expiry) return null;
      if (l.type === "promo") return "Bia khuyến mại";
      if (l.type === "return") return "Bia đổi trả";
      return null;
    };
    const { fixedRows, extra } = matchLoadSlipLines(linesForMatch);
    // Chỉ in dòng có số lượng thật — hàng hóa cố định nào không xuất trong phiếu này thì bỏ
    // hẳn khỏi bảng in (không để dòng trống), giữ nguyên nội dung Mô tả cho các dòng còn lại.
    const keptFixed = fixedRows.filter(g => g.qty != null);
    const fixedHtml = keptFixed.map((g, i) => `<tr>
      <td style="text-align:center">${i + 1}</td><td>${esc(g.label)}</td>
      <td style="text-align:center">${g.qty}</td><td style="text-align:center">${esc(g.dvt)}</td>
      <td>${esc(g.mota)}</td><td>${dash(lineNoteFor(g.matched))}</td></tr>`).join("");
    const extraHtml = extra.map((l, i) => `<tr>
      <td style="text-align:center">${keptFixed.length + i + 1}</td><td>${dash(l.product_name)}</td>
      <td style="text-align:center">${l.quantity}</td>
      <td style="text-align:center">${dash(utNameByCode[l.unit_type] || l.unit_type)}</td>
      <td></td><td>${dash(lineNoteFor(l))}</td></tr>`).join("");
    const html = bienBanBanGiaoHtml({
      code: shipment.shipment_code, dateObj: new Date(shipment.created_at),
      destination: shipment.ship_to_name || shipment.ship_to_address || shipment.delivery_place,
      issuer: { name: null, title: null, dept: "Kho thành phẩm" },
      // Bên nhận ký thực tế là người trực tiếp lên xe chở hàng (lái xe), không phải nơi xuất
      // đến (đã hiện riêng ở dòng "Nơi xuất đến" phía trên) — recipient_name/dept vẫn có thể
      // là NPP/khách hàng nên không dùng ở khối ký nhận này nữa.
      recipient: { name: shipment.driver_name, title: "Lái xe", unit: shipment.vehicle_plate, dept: null },
      recipientUnitLabel: "Biển số xe",
      rowsHtml: fixedHtml + extraHtml,
    });
    openPrintWindow(html);
  }

  // ---------- Điều chuyển nội bộ (WmsTransfer) → cùng mẫu Biên bản bàn giao hàng hóa, đích là
  // 1 vị trí kho (không phải nhà phân phối) — mirror printShipmentHandoverSlip ----------
  async function printTransferHandoverSlip(transfer) {
    let nameByCode = {}, utNameByCode = {};
    try {
      const fps = await GET("/finished-products");
      nameByCode = Object.fromEntries(fps.map(p => [p.code, p.name]));
    } catch (e) { /* vẫn in được — chỉ thiếu tên đầy đủ, dùng tạm mã SKU */ }
    try {
      const uts = await GET("/unit-types");
      utNameByCode = Object.fromEntries(uts.map(u => [u.code, u.name]));
    } catch (e) { /* vẫn in được — chỉ thiếu tên loại đơn vị cho dòng ngoài danh mục cố định */ }
    const dash = (v) => (v === null || v === undefined || v === "" ? "" : esc(String(v)));
    const linesForMatch = (transfer.lines || []).map((l, i) =>
      ({ line_id: i, product_name: nameByCode[l.product] || l.product, quantity: l.count, unit_type: l.unit_type }));
    const { fixedRows, extra } = matchLoadSlipLines(linesForMatch);
    const keptFixed = fixedRows.filter(g => g.qty != null);
    const fixedHtml = keptFixed.map((g, i) => `<tr>
      <td style="text-align:center">${i + 1}</td><td>${esc(g.label)}</td>
      <td style="text-align:center">${g.qty}</td><td style="text-align:center">${esc(g.dvt)}</td>
      <td>${esc(g.mota)}</td><td></td></tr>`).join("");
    const extraHtml = extra.map((l, i) => `<tr>
      <td style="text-align:center">${keptFixed.length + i + 1}</td><td>${dash(l.product_name)}</td>
      <td style="text-align:center">${l.quantity}</td>
      <td style="text-align:center">${dash(utNameByCode[l.unit_type] || l.unit_type)}</td>
      <td></td><td></td></tr>`).join("");
    const html = bienBanBanGiaoHtml({
      code: transfer.transfer_code, dateObj: new Date(transfer.created_at),
      destination: transfer.to_location_name || transfer.to_location_code,
      issuer: { name: null, title: null, dept: "Kho thành phẩm" },
      recipient: { name: transfer.driver_name, title: "Lái xe", unit: transfer.vehicle_plate, dept: null },
      recipientUnitLabel: "Biển số xe",
      rowsHtml: fixedHtml + extraHtml,
    });
    openPrintWindow(html);
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
          <td>${badge(["kcs_approval", "director_approval"].includes(c.state) ? "due" : c.state === "closed" ? "available" : "planned")}${esc(c.state)}</td>
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
    const CAPA_PHASE_LABEL = { open: "Mở CAPA", investigation: "Điều tra nguyên nhân gốc",
      action: "Kế hoạch hành động", verification: "Xác nhận hiệu lực",
      kcs_approval: "Chờ duyệt — Trưởng phòng KCS", director_approval: "Chờ duyệt — Giám đốc/Phó GĐ SX-KT",
      closed: "Đã đóng" };

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
        <div>Trạng thái hiện tại: ${badge(["kcs_approval", "director_approval"].includes(c.state) ? "due" : c.state === "closed" ? "available" : "planned")}${esc(c.state)}</div>
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

  // Tải báo cáo xuất thành phẩm theo ca (DB nội bộ WMS, không phải SCADA ngoài — không có khái
  // niệm "khoảng trống dữ liệu" như filling/keg) SAU khi khung màn hình đã hiện. Chuyển từ
  // VIEWS.reports sang đây cùng với tab "Xuất TP theo ca" (sec === "fgship" trong VIEWS.wms).
  async function loadFinishedGoodsShiftData() {
    const stillHere = () => $("view-wms").classList.contains("active") && $("gp_data");
    try {
      let dateFrom, dateTo;
      if (SUB.fgship_mode === "month") {
        const [y, m] = SUB.fgship_month.split("-").map(Number);
        dateFrom = toDTLocal(new Date(y, m - 1, 1, 6, 0, 0));
        dateTo = toDTLocal(new Date(y, m, 1, 6, 0, 0));
      } else {
        const start = new Date(SUB.fgship_date + "T06:00:00");
        const end = new Date(start); end.setDate(end.getDate() + 1);
        dateFrom = toDTLocal(start); dateTo = toDTLocal(end);
      }

      const rpt = await GET(`/reports/finished-goods-shift-report?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}`);
      if (!stillHere()) return;
      const caColors = ["#3498db", "#f5a623", "#9b59b6"];
      const dayLabels = rpt.by_day.map(d => d.date.slice(5));
      const barSeries = [
        { label: "Ca 1 (06h-14h)", color: caColors[0], values: rpt.by_day.map(d => d.ca1) },
        { label: "Ca 2 (14h-22h)", color: caColors[1], values: rpt.by_day.map(d => d.ca2) },
        { label: "Ca 3 (22h-06h)", color: caColors[2], values: rpt.by_day.map(d => d.ca3) },
      ];
      const pieItems = rpt.by_ca.map((c, i) => ({ label: c.label, value: c.liters, color: caColors[i] }));

      $("gp_data").innerHTML = `<div class="muted" style="margin-bottom:8px">📅 Đang xem dữ liệu từ <b>${fmt(rpt.date_from)}</b> đến <b>${fmt(rpt.date_to)}</b></div>
        ${rpt.unmatched_products.length ? `<div style="color:var(--orange,#f5a623);margin-bottom:8px">⚠ ${rpt.unmatched_products.length} SKU không suy được dung tích từ tên (thiếu "ml"/"L" trong tên sản phẩm) — chưa tính vào tổng lít: ${rpt.unmatched_products.map(u => `${esc(u.product_name)} (${u.units.toLocaleString("vi-VN")} đơn vị)`).join(", ")}. Sửa tên SKU ở Danh mục › Sản phẩm để báo cáo tính đúng.</div>` : ""}
        <div class="row" style="gap:10px;flex-wrap:wrap">
          <div class="panel" style="flex:1;min-width:180px">
            <div class="muted" style="font-size:12px">TỔNG LÍT XUẤT</div>
            <div style="font-size:26px;font-weight:700;color:var(--green)">${rpt.total_liters.toLocaleString("vi-VN")} <span style="font-size:14px;font-weight:400">lít</span></div>
          </div>
          ${rpt.by_ca.map((c, i) => `<div class="panel" style="flex:1;min-width:160px">
            <div class="muted" style="font-size:12px">${esc(c.label.toUpperCase())}</div>
            <div style="font-size:22px;font-weight:700;color:${caColors[i]}">${c.liters.toLocaleString("vi-VN")} <span style="font-size:13px;font-weight:400">lít</span></div>
          </div>`).join("")}
        </div>
        <div class="split">
          <div class="panel"><h2>Tỉ lệ theo ca</h2>${pieItems.some(p => p.value > 0) ? CH.pie(pieItems) : '<div class="muted">Không có dữ liệu.</div>'}</div>
          <div class="panel"><h2>Theo ngày — từng ca</h2>${dayLabels.length ? CH.groupedN(dayLabels, barSeries) : '<div class="muted">Không có dữ liệu.</div>'}</div>
        </div>
        <div class="panel"><h2>Theo loại bia</h2>
          <div class="muted" style="margin-bottom:8px">Lít xuất theo từng loại (Bia chai/Bia lon/Bia hơi/Bia tươi...), chia theo ca.</div>
          ${rpt.by_category.some(c => c.total > 0) ? CH.groupedN(rpt.by_category.map(c => c.category), [
            { label: "Ca 1 (06h-14h)", color: caColors[0], values: rpt.by_category.map(c => c.ca1) },
            { label: "Ca 2 (14h-22h)", color: caColors[1], values: rpt.by_category.map(c => c.ca2) },
            { label: "Ca 3 (22h-06h)", color: caColors[2], values: rpt.by_category.map(c => c.ca3) },
          ]) : '<div class="muted">Không có dữ liệu.</div>'}
          <div class="tablewrap" style="margin-top:12px"><table><thead><tr><th>Loại bia</th><th>Ca 1</th><th>Ca 2</th><th>Ca 3</th><th>Tổng (lít)</th></tr></thead>
          <tbody>${rpt.by_category.map(c => `<tr><td>${esc(c.category)}</td>
            <td>${c.ca1.toLocaleString("vi-VN")}</td><td>${c.ca2.toLocaleString("vi-VN")}</td><td>${c.ca3.toLocaleString("vi-VN")}</td>
            <td><b>${c.total.toLocaleString("vi-VN")}</b></td></tr>`).join("") ||
            '<tr><td colspan=5 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div></div>
        <div class="panel"><h2>Xuất theo từng SKU</h2>
          <div class="muted" style="margin-bottom:8px">Số lượng xuất theo từng mã sản phẩm (SKU) cụ thể — đơn vị tính theo loại đơn vị tồn kho của SKU đó (vỉ/keg/lon/...), không quy đổi lít.</div>
          <div class="tablewrap"><table id="t_gp_sku"><thead><tr><th>SKU</th><th>Nhóm</th><th>Loại ĐVT</th><th>Số lượng</th><th>Tổng SL nhỏ</th></tr></thead>
          <tbody>${(rpt.by_sku || []).map(s => `<tr><td>${esc(s.display_name)}</td><td class="muted">${esc(s.category)}</td>
            <td>${esc(s.unit_label)}</td><td><b>${s.count.toLocaleString("vi-VN")}</b></td>
            <td class="muted">${s.quantity.toLocaleString("vi-VN")}</td></tr>`).join("") ||
            '<tr><td colspan=5 class="muted">Không có dữ liệu.</td></tr>'}</tbody>
          ${(rpt.unit_totals || []).length ? `<tfoot><tr>
            <td colspan=3 style="text-align:right"><b>Tổng theo loại ĐVT</b></td>
            <td colspan=2>${rpt.unit_totals.map(u => `<b>${u.total_count.toLocaleString("vi-VN")}</b> ${esc(u.unit_label)}`).join(" · ")}</td>
          </tr></tfoot>` : ""}</table></div></div>
        <div class="panel"><h2>Chi tiết theo ca</h2>
          <div class="tablewrap"><table id="t_gp_ca"><thead><tr><th>Ngày</th><th>Ca</th><th>Bắt đầu</th><th>Kết thúc</th><th>Lít</th></tr></thead>
          <tbody>${rpt.shifts.map(s => `<tr><td>${fmt(s.date)}</td><td>Ca ${s.ca}</td>
            <td class="muted">${new Date(s.start).toLocaleString("vi-VN")}</td><td class="muted">${new Date(s.end).toLocaleString("vi-VN")}</td>
            <td>${s.liters.toLocaleString("vi-VN")}</td></tr>`).join("") ||
            '<tr><td colspan=5 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div></div>`;
      wirePaginate("t_gp_sku", 10);
      wirePaginate("t_gp_ca", 10);
    } catch (e) {
      if (!stillHere()) return;
      $("gp_data").innerHTML = `<div class="panel muted">Chưa xem được báo cáo xuất thành phẩm: ${esc(e.message)}</div>`;
    }
  }

  // Tải báo cáo phân loại xuất kho (khuyến mại/đổi trả/cận date/gửi) — mirror
  // loadFinishedGoodsShiftData ở trên, cùng quy ước mốc ngày 06h-06h hôm sau (đồng bộ với
  // _bucket_shift phía backend) để "ngày" hiển thị khớp với các báo cáo theo ca khác.
  async function loadShipmentClassificationData() {
    const stillHere = () => $("view-wms").classList.contains("active") && $("pl_data");
    try {
      let dateFrom, dateTo;
      if (SUB.phanloai_mode === "month") {
        const [y, m] = SUB.phanloai_month.split("-").map(Number);
        dateFrom = toDTLocal(new Date(y, m - 1, 1, 6, 0, 0));
        dateTo = toDTLocal(new Date(y, m, 1, 6, 0, 0));
      } else {
        const start = new Date(SUB.phanloai_date + "T06:00:00");
        const end = new Date(start); end.setDate(end.getDate() + 1);
        dateFrom = toDTLocal(start); dateTo = toDTLocal(end);
      }

      const rpt = await GET(`/reports/shipment-classification-report?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}&group_by=day`);
      if (!stillHere()) return;
      const rows = rpt.rows || [];
      const sum = (key) => rows.reduce((s, r) => s + (r[key] || 0), 0);
      const colors = { promo: "#3498db", return: "#f5a623", near_expiry: "#9b59b6", consigned: "#2ecc71" };
      const labels = { promo: "Khuyến mại", return: "Đổi trả", near_expiry: "Cận date", consigned: "Gửi" };
      const dayLabels = rows.map(r => r.period.slice(5));
      const barSeries = ["promo", "return", "near_expiry", "consigned"].map(k =>
        ({ label: labels[k], color: colors[k], values: rows.map(r => r[k] || 0) }));

      $("pl_data").innerHTML = `<div class="muted" style="margin-bottom:8px">📅 Đang xem dữ liệu từ <b>${fmt(rpt.date_from)}</b> đến <b>${fmt(rpt.date_to)}</b></div>
        <div class="row" style="gap:10px;flex-wrap:wrap">
          ${["promo", "return", "near_expiry", "consigned"].map(k => `<div class="panel" style="flex:1;min-width:160px">
            <div class="muted" style="font-size:12px">${esc(labels[k].toUpperCase())}</div>
            <div style="font-size:22px;font-weight:700;color:${colors[k]}">${sum(k).toLocaleString("vi-VN")} <span style="font-size:13px;font-weight:400">đơn vị</span></div>
          </div>`).join("")}
        </div>
        <div class="panel"><h2>Theo ngày</h2>
          ${dayLabels.length ? CH.groupedN(dayLabels, barSeries) : '<div class="muted">Không có dữ liệu.</div>'}
          <div class="tablewrap" style="margin-top:12px"><table id="t_pl_days"><thead><tr><th>Ngày</th><th>Khuyến mại</th><th>Đổi trả</th><th>Cận date</th><th>Gửi</th></tr></thead>
          <tbody>${rows.map(r => `<tr><td>${fmt(r.period)}</td>
            <td>${(r.promo || 0).toLocaleString("vi-VN")}</td><td>${(r.return || 0).toLocaleString("vi-VN")}</td>
            <td>${(r.near_expiry || 0).toLocaleString("vi-VN")}</td><td>${(r.consigned || 0).toLocaleString("vi-VN")}</td></tr>`).join("") ||
            '<tr><td colspan=5 class="muted">Không có dữ liệu.</td></tr>'}</tbody></table></div></div>`;
      wirePaginate("t_pl_days", 10);
    } catch (e) {
      if (!stillHere()) return;
      $("pl_data").innerHTML = `<div class="panel muted">Chưa xem được báo cáo: ${esc(e.message)}</div>`;
    }
  }

  // ======================================================================
  // #P3-4 — WMS kho thành phẩm (vỉ/keg + barcode)
  // ======================================================================
  VIEWS.wms = async function () {
    // "[mã kho] mã vị trí - tên vị trí" — hiện cả kho thành phẩm lẫn vị trí trong kho đó.
    const locWhPrefix = (l) => l.warehouse_name ? `[${esc(l.warehouse_name)}] ` : "";
    const locZoneSuffix = (l) => l.zone ? ` - Khu ${esc(l.zone)}` : "";
    function locationCell(g) {
      const parts = (g.locations || []).map(l => `${locWhPrefix(l)}${l.name ? `${esc(l.code || "?")} - ${esc(l.name)}` : esc(l.code || "?")}${locZoneSuffix(l)}`);
      if (g.unplaced > 0) parts.push(`chưa cất×${g.unplaced}`);
      return parts.join(", ") || "—";
    }
    // Chỉ liệt kê các vị trí ĐÃ CẤT thật (không gồm "chưa cất") — dùng cho giỏ Xuất kho vì
    // hàng chưa cất không còn được phép chọn xuất (xem renderLots sellable/exclude_unplaced).
    function placedLocationLabel(g) {
      const parts = (g.locations || []).map(l => `${locWhPrefix(l)}${l.name ? `${esc(l.code || "?")} - ${esc(l.name)}` : esc(l.code || "?")}${locZoneSuffix(l)}`);
      return parts.join(", ") || "—";
    }
    const sec = SUB.wms || "kho";
    const sections = [{ key: "factoryimport", label: "🏭 Nhập từ nhà máy khác" },
      { key: "kho", label: "Kho TP" }, { key: "xuatkho", label: "Xuất kho" },
      { key: "dieuchuyen", label: "🔀 Điều chuyển" },
      { key: "capvao", label: "🚚 Cất vào vị trí" }, { key: "tudo", label: "🚫 Xuất tự do" },
      { key: "lenhdonghang", label: "Lệnh đóng hàng" }, { key: "aging", label: "📦 Tồn kho theo tuổi" },
      { key: "canexpiry", label: "🕒 Bia cận date" }, { key: "consigned", label: "🎁 Bia gửi" },
      { key: "fgship", label: "Xuất TP theo ca" }, { key: "phanloai", label: "KM/Đổi trả/Cận date/Gửi" },
      { key: "netship", label: "Xuất ròng theo kỳ" }, { key: "vehiclegs", label: "🚚 Xe & bia gửi" },
      { key: "fgstock", label: "📦 NXT kho thành phẩm" }];
    const root = $("view-wms");
    // "Nơi xuất đến" dùng chung danh mục Nhà cung cấp (không còn catalog ship_to_location riêng —
    // xem models/wms.py, migration 9a0b1c2d3e4f_ship_to_supplier_merge) — biến `shipTos` giữ tên cũ
    // để đỡ đổi các chỗ dùng bên dưới, nhưng nguồn dữ liệu giờ là /api/suppliers.
    const [locs, shipTos, finishedProducts, vehicles, unitTypes, gsEligible, warehouses, factoryLocations, fpGroups] = await Promise.all([
      GET("/wms/locations"), GET("/suppliers"), GET("/finished-products").catch(() => []),
      GET("/wms/vehicles").catch(() => []), GET("/unit-types").catch(() => []),
      GET("/wms/vehicles/consigned-eligible").catch(() => []),
      GET("/wms/warehouses").catch(() => []),
      GET("/factory-locations").catch(() => []),
      sec === "fgstock" ? GET("/finished-product-groups").catch(() => []) : Promise.resolve([])]);
    // "Kho thành phẩm" (WmsWarehouse) là cấp cha mới của vị trí kho — 1 kho có nhiều vị trí.
    // Nhãn hiển thị ưu tiên "[mã kho] mã vị trí - tên vị trí" để biết ngay lô đang ở kho nào.
    const whLabel = (l) => `${l.warehouse_name ? `[${esc(l.warehouse_name)}] ` : ""}${esc(l.code)}${l.name ? ` - ${esc(l.name)}` : ""}${locZoneSuffix(l)}`;
    const utByCode = Object.fromEntries(unitTypes.map(ut => [ut.code, ut]));
    // FinishedGoodsUnit.product_name lưu mã SKU (VD "FLGN200"), không phải tên — tra thêm tên
    // để hiển thị "Mã — Tên" cho dễ nhận biết, chỉ dùng ở lớp hiển thị (mọi key gom nhóm/FIFO/
    // payload gửi server vẫn giữ nguyên product_name = mã, không đổi).
    const fpByCode = Object.fromEntries(finishedProducts.map(fp => [fp.code, fp]));
    const fpLabel = (code) => { const fp = fpByCode[code]; return fp ? `${code} — ${fp.name}` : (code || ""); };
    // "lon" là mã hệ thống dùng chung cho MỌI đơn vị phân rã rời (không riêng lon nhôm) — tra
    // theo tên sản phẩm để hiển thị đúng danh từ thực tế (Lon/Chai/Keg), tránh hiển thị "Lon"
    // sai cho bia chai/keg đã phân rã hoặc nhập lẻ. Dùng chung cho mọi bảng hiển thị unit_type.
    const smallUnitNoun = (prodText) => {
      const t = (prodText || "").toLowerCase();
      if (t.includes("lon")) return "Lon";
      if (t.includes("chai")) return "Chai";
      if (t.includes("keg")) return "Keg";
      return "SL nhỏ";
    };
    const unitTypeLabel = (g) => {
      if (g.unit_type === "lon") return smallUnitNoun(fpLabel(g.product));
      const ut = utByCode[g.unit_type];
      return ut ? ut.name : (g.unit_type === "keg" ? "Keg" : "Vỉ");
    };
    // Sơ đồ kho Đông Mai — vẽ ĐỘNG theo layout_row/layout_col mà admin tự xếp ở Danh mục ›
    // 🗺️ Bố cục kho (không hard-code danh sách mã vị trí — mã thật trên server, vd "DM.K01",
    // không theo quy luật cố định nào để tự suy ra vị trí vẽ). Vị trí chưa được xếp bố cục vẫn
    // phải hiện (dạng danh sách rời bên dưới lưới) để không lặp lại lỗi cũ: dữ liệu có thật
    // nhưng biến mất khỏi sơ đồ chỉ vì mã không khớp danh sách hard-code.
    // Mỗi khay chiếm NỬA bề ngang màn hình (2 khay/hàng, chữ to) — theo yêu cầu người dùng vì
    // chữ quá bé khi vẽ nhiều khay nhỏ chen nhau trên 1 hàng phải cuộn ngang mới đọc được. Thứ
    // tự khay đọc theo layout_row rồi layout_col (đúng thứ tự đã xếp ở Bố cục kho) — không còn
    // giữ đúng hình dạng lưới hàng/cột thật, đổi lấy chữ đọc được trên màn hình nhỏ (tablet kho).
    function floorMapCell(loc, fallbackCode) {
      const code = loc ? loc.code : fallbackCode;
      const lotDot = (l) => `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${l.fifo_ready ? "#2ecc71" : "#95a5a6"};margin-right:6px;flex:none"></span>`;
      const lotLine = (l) => `<div style="font-size:15px;line-height:1.6;display:flex;align-items:center" title="${esc(fpLabel(l.product_name))} — ${esc(l.lot_code || "")} — ${l.count}">${lotDot(l)}<span>${esc(fpLabel(l.product_name))} · ${esc(l.lot_code || "—")} · ${l.count}</span></div>`;
      const lots = (loc && loc.lots) || [];
      const shown = lots.slice(0, 3).map(lotLine).join("");
      const more = lots.length > 3
        ? `<details><summary style="cursor:pointer;font-size:14px;color:var(--muted)">+${lots.length - 3} lô khác</summary>${lots.slice(3).map(lotLine).join("")}</details>` : "";
      const body = lots.length ? shown + more : `<div class="muted" style="font-size:14px">Trống</div>`;
      return `<div style="border:1px solid var(--border);border-radius:8px;padding:12px 14px;min-height:64px;background:var(--panel2)">
        <div style="font-weight:700;font-size:19px;margin-bottom:6px">${esc(code || "?")}</div>${body}</div>`;
    }
    function renderDongMaiFloorMap(rows) {
      const all = rows || [];
      const placed = (all.filter(r => r.layout_row != null && r.layout_col != null))
        .sort((a, b) => a.layout_row - b.layout_row || a.layout_col - b.layout_col);
      const unplaced = all.filter(r => r.layout_row == null || r.layout_col == null);
      const grid = "display:grid;grid-template-columns:1fr 1fr;gap:10px";
      const unplacedBlock = unplaced.length ? `<div style="margin-top:14px">
        <div class="muted" style="margin-bottom:6px;font-size:14px">Chưa xếp vào bố cục (${unplaced.length}) — vào Danh mục › 🗺️ Bố cục kho để xếp:</div>
        <div style="${grid}">${unplaced.map(l => floorMapCell(l)).join("")}</div>
      </div>` : "";
      if (!placed.length) {
        return `<div class="muted">Kho này chưa được xếp bố cục — vào Danh mục › 🗺️ Bố cục kho để xếp vị trí lên lưới hàng/cột.</div>${unplacedBlock}`;
      }
      return `<div style="${grid}">${placed.map(l => floorMapCell(l)).join("")}</div>${unplacedBlock}`;
    }
    let body = "";
    if (sec === "kho") {
      const sm = await GET("/wms/summary");
      const locOpt = myAllowedLocations(locs).map(l => `<option value="${esc(l.loc_id)}">${whLabel(l)} (${l.used}/${l.capacity})</option>`).join("");
      const fpOpt = finishedProducts.map(fp => `<option value="${esc(fp.finished_product_id)}" data-code="${esc(fp.code)}" data-pack="${fp.pack_size}" data-unittype="${esc(fp.unit_type)}">${esc(fp.code)} — ${esc(fp.name)}</option>`).join("");
      // DHLN300/FHLN020 (bia hơi/tươi Hạ Long) chỉ do nhà máy khác sản xuất — chặn khỏi "Nhập
      // kho thủ công" (chỉ nhập được qua tab "Nhập từ nhà máy khác"), KHÔNG áp dụng cho "Nhập
      // tồn đầu" (fpOpt giữ nguyên, dùng wob_prod bên dưới) vì đó là chỉnh số liệu gốc khi triển khai.
      const fpOptNoFactory = finishedProducts.filter(fp => !["DHLN300", "FHLN020"].includes(fp.code))
        .map(fp => `<option value="${esc(fp.finished_product_id)}" data-code="${esc(fp.code)}" data-pack="${fp.pack_size}" data-unittype="${esc(fp.unit_type)}">${esc(fp.code)} — ${esc(fp.name)}</option>`).join("");
      const card = (val, label, sub) => `<div class="card"><div class="n">${val}</div><div class="l">${label}</div>${sub ? `<div class="muted" style="font-size:11px;margin-top:2px">${sub}</div>` : ""}</div>`;
      const fmtN = (v) => (v || 0).toLocaleString("vi-VN", { maximumFractionDigits: 2 });
      const byStatus = Object.entries(sm.by_status || {}).map(([k, v]) => `${esc(k)}: <b>${fmtN(v)}</b>`).join(" · ") || "—";
      // "lon" gộp NHIỀU sản phẩm khác nhau (có thể vừa lon vừa chai đã phân rã) — không có 1
      // danh từ vật lý đúng cho MỌI sản phẩm trong tổng này, nên dùng nhãn trung lập "Lẻ". Các
      // loại khác (vi/keg/loc/ket/...) tra tên thật từ danh mục loại đơn vị thay vì hardcode
      // 3 nhánh — nếu không thì mọi loại ngoài keg/lon đều bị gộp nhầm chung nhãn "Vỉ".
      const byType = Object.entries(sm.by_type || {}).map(([k, v]) => `${k === "lon" ? "Lẻ" : (utByCode[k] ? utByCode[k].name : k)}: <b>${fmtN(v)}</b>`).join(" · ") || "—";
      const isAdminWms = CURRENT_USER && CURRENT_USER.role === "admin";
      body = `
        ${panel("📊 Tổng quan kho thành phẩm", `
          <div class="cards" style="margin-bottom:10px">
            ${card(fmtN(sm.units_total), "Tổng vỉ/keg", byType)}
            ${card(fmtN(sm.units_stored), "Đang lưu kho", byStatus)}
            ${card((sm.fill_pct ?? 0) + "%", "Mức lấp đầy", `${sm.locations} vị trí, sức chứa ${sm.capacity_units}`)}
          </div>
          <div style="height:14px;background:var(--panel2);border-radius:7px;overflow:hidden" title="Mức lấp đầy ${sm.fill_pct ?? 0}%">
            <div style="height:100%;width:${Math.min(sm.fill_pct || 0, 100)}%;background:${(sm.fill_pct || 0) >= 90 ? "#e74c3c" : "#3498db"}"></div>
          </div>`)}
        ${panel("📦 Nhập kho thủ công", `
          <div class="row">
            <div class="field"><label>Sản phẩm</label>
              <input id="wu_prod_q" placeholder="Tìm sản phẩm..." style="width:220px;margin-bottom:2px"/>
              <select id="wu_prod" style="width:220px"><option value="">(chọn sản phẩm)</option>${fpOptNoFactory}</select></div>
            <div class="field"><label>Lô TP</label><input id="wu_lot" placeholder="để trống = tự sinh" style="width:150px"/></div>
            <div class="field"><label>Ngày nhập</label><input id="wu_received_at" type="datetime-local" value="${toDTLocal(new Date())}" style="width:180px"/></div>
            <div class="field" id="wu_lonmode_wrap" style="align-self:flex-end">
              <label style="display:flex;align-items:center;gap:4px;cursor:pointer;white-space:nowrap">
                <input type="checkbox" id="wu_lonmode"/> Nhập lẻ (bỏ qua vỉ)</label></div>
            <div class="field" id="wu_total_wrap"><label id="wu_total_label">Số Lon</label><input id="wu_total" value="240" style="width:90px"/></div>
            <div class="field" id="wu_count_wrap"><label id="wu_count_label">Số Vỉ</label><input id="wu_count" type="number" value="10" style="width:80px"/></div>
            <div class="field"><label>SL/1 đơn vị</label><input id="wu_pack" value="24" style="width:80px" readonly title="Lấy tự động từ Danh mục Sản phẩm — không sửa được"/></div>
            <div class="field"><label>Vị trí kho</label><select id="wu_loc" style="width:160px"><option value="">(chọn vị trí)</option>${locOpt}</select></div>
            <div class="field" style="align-self:flex-end"><button class="btn" id="wu_build">+ Nhập kho</button></div>
          </div>
          <div class="muted" style="font-size:12px;margin-top:4px">Để trống Lô TP để hệ thống tự sinh mã tăng dần theo năm, hoặc tự nhập mã lô riêng. Loại đơn vị (vỉ/keg) và SL/1 đơn vị tự điền theo sản phẩm — quản lý ở Danh mục › Sản phẩm. Nhập lon hoặc nhập vỉ đều được — 2 ô tự quy đổi theo nhau. Tick "Nhập lẻ" nếu chỉ có lon rời (không đủ vỉ) — tồn kho sẽ lưu thẳng theo Lon, không quy đổi ra vỉ. Bắt buộc chọn Vị trí kho trước khi nhập. Sau khi nhập, cần Trưởng bộ phận kho duyệt trước khi được xuất kho.</div>`)}
        ${panel("🏁 Nhập tồn đầu", isAdminWms ? `
          <div class="row">
            <div class="field"><label>Sản phẩm</label>
              <input id="wob_prod_q" placeholder="Tìm sản phẩm..." style="width:220px;margin-bottom:2px"/>
              <select id="wob_prod" style="width:220px"><option value="">(chọn sản phẩm)</option>${fpOpt}</select></div>
            <div class="field"><label>Lô TP</label><input id="wob_lot" value="PKG-2406-0001" style="width:150px"/></div>
            <div class="field"><label>Ngày nhập</label><input id="wob_received_at" type="datetime-local" value="${toDTLocal(new Date())}" style="width:180px"/></div>
            <div class="field" id="wob_lonmode_wrap" style="align-self:flex-end">
              <label style="display:flex;align-items:center;gap:4px;cursor:pointer;white-space:nowrap">
                <input type="checkbox" id="wob_lonmode"/> Nhập lẻ (bỏ qua vỉ)</label></div>
            <div class="field" id="wob_total_wrap"><label id="wob_total_label">Số Lon</label><input id="wob_total" value="240" style="width:90px"/></div>
            <div class="field" id="wob_count_wrap"><label id="wob_count_label">Số Vỉ</label><input id="wob_count" type="number" value="10" style="width:80px"/></div>
            <div class="field"><label>SL/1 đơn vị</label><input id="wob_pack" value="24" style="width:80px" readonly title="Lấy tự động từ Danh mục Sản phẩm — không sửa được"/></div>
            <div class="field"><label>Vị trí kho</label><select id="wob_loc" style="width:160px"><option value="">(chọn vị trí)</option>${locOpt}</select></div>
            <div class="field" style="align-self:flex-end"><button class="btn" id="wob_build">+ Nhập tồn đầu</button></div>
          </div>
          <div class="muted" style="font-size:12px;margin-top:4px">Nạp số dư tồn kho thành phẩm ban đầu khi triển khai hệ thống (không qua chiết thật) — giúp phân biệt trong lịch sử. Bắt buộc chọn Vị trí kho trước khi nhập.</div>
          <div class="row" style="margin-top:10px;border-top:1px solid var(--border);padding-top:10px">
            <div class="field" style="flex:1"><label>Hoặc import Excel (cột: Ngày nhập, Mã sản phẩm, Lô, Số lượng, Vị trí — bắt buộc)</label>
              <input type="file" id="wob_file" accept=".xlsx"/></div>
            <button class="btn sec" id="wob_import" style="align-self:flex-end">📥 Import Excel</button>
          </div>`
          : '<div class="muted">Chỉ tài khoản Admin mới được thực hiện nhập tồn đầu.</div>')}
        ${panel("🟦 Vỉ/Keg tồn kho", `<div id="pl_box" class="muted">Đang tải…</div>`)}
        ${panel("🔨 Lịch sử phân rã", `<input class="searchbox" data-tbl="t_dp_history" placeholder="Tìm theo sản phẩm, lô, người..."/><div id="dp_history" class="muted">Đang tải…</div>`)}
        ${panel("🗺️ Sơ đồ kho Đông Mai", `
          <div class="muted" style="margin-bottom:8px">Chỉ hiển thị vị trí thuộc Kho Đông Mai. Chấm xanh = lô cũ nhất của (sản phẩm, loại đơn vị) đó TRONG Kho Đông Mai — sẵn sàng xuất trước theo FIFO.</div>
          <div id="floor_map_box" class="muted">Đang tải…</div>`)}
      `;
    } else if (sec === "xuatkho") {
      const shipToOpt = shipTos.filter(s => s.active).map(s => `<option value="${esc(s.supplier_id)}">${esc(s.code)} — ${esc(s.name)}</option>`).join("");
      const activeVehicles = vehicles.filter(v => v.active);
      const driverOpt = activeVehicles.map(v =>
        `<option value="${esc(v.vehicle_id)}">${esc(v.driver_name || v.driver_short_name || "(chưa rõ tên)")} — ${esc(v.plate)}</option>`).join("");
      // "Kho xuất": tài khoản bị giới hạn kho thành phẩm (wms_warehouse_scope) BẮT BUỘC chọn 1
      // kho cụ thể trước khi được xem/chọn lô (BE cũng tự chặn nếu thiếu, xem
      // services/wms.py::create_shipment) — tài khoản không bị giới hạn có thêm lựa chọn
      // "(Tất cả kho — FIFO toàn công ty)" để giữ nguyên hành vi cũ.
      const myWh = myAllowedWarehouses(warehouses);
      const whRestricted = isWhScopeRestricted();
      const xkWhOpt = myWh.map(w => `<option value="${esc(w.code)}">${esc(w.name)}</option>`).join("");
      body = `<div class="panel"><h2>🚚 Xuất kho</h2>
        <div class="muted" style="margin-bottom:8px">Chọn nơi xuất đến, sau đó thêm từng dòng sản phẩm/lô/loại đơn vị + số lượng cần xuất vào "Sản phẩm đã chọn" (thêm được nhiều lô/sản phẩm khác nhau trong cùng 1 phiếu), rồi bấm "Tạo phiếu xuất kho". Hệ thống tự chọn đúng vỉ/keg/lon cũ nhất (FIFO) trong mỗi lô — không cần liệt kê/chọn từng đơn vị.</div>
        <div class="row">
          <div class="field"><label>Kho xuất${whRestricted ? " (bắt buộc)" : ""}</label>
            <select id="xk_wh">${whRestricted ? "" : '<option value="">(Tất cả kho — FIFO toàn công ty)</option>'}${xkWhOpt}</select></div>
          <div class="field"><label>Nơi xuất đến</label>
            <input id="xk_shipto_q" placeholder="Tìm nơi xuất đến..." style="margin-bottom:2px"/>
            <select id="xk_shipto"><option value="">(chọn nơi xuất đến)</option>${shipToOpt}</select></div>
          <div class="field"><label>Lọc lô</label><select id="xk_lotfilter">
            <option value="">(tất cả lô)</option>
            <option value="has_lon">Lô có lon phân rã</option>
            <option value="no_lon">Lô không có lon phân rã</option></select></div>
          <div class="field" style="flex:1"><label>Tìm sản phẩm/lô</label><input id="xk_search" placeholder="Gõ để lọc…"/></div>
          <div class="field"><label>Nhân viên lái xe</label>
            <input id="xk_driver_q" placeholder="Tìm lái xe/biển số..." style="margin-bottom:2px"/>
            <select id="xk_driver"><option value="">(chưa chọn — xem Danh mục lái xe nếu chưa có)</option>${driverOpt}</select></div>
        </div>
        <div class="muted" style="margin-top:-4px;margin-bottom:8px">Người nhận hàng trên phiếu in sẽ lấy theo tên "Nơi xuất đến" đã chọn; lái xe/biển số lấy theo Danh mục lái xe đã chọn ở trên. Chọn "Kho xuất" để chỉ xem/xuất hàng đang cất tại đúng kho đó — tránh chọn nhầm lô đang ở kho khác.</div>
        <div id="xk_lots"></div>
        <div class="panel" style="margin-top:10px"><h3 style="font-size:14px">🛒 Sản phẩm đã chọn</h3><div id="xk_cart"></div></div>
      </div>
      <div class="panel"><h2>Lịch sử xuất kho</h2><input class="searchbox" data-tbl="t_xk_history" placeholder="Tìm theo mã phiếu, nơi xuất đến, người xuất..."/><div id="xk_history" class="muted">Đang tải…</div></div>`;
    } else if (sec === "dieuchuyen") {
      const locOptDc = otherWarehouseLocations(locs).map(l => `<option value="${esc(l.loc_id)}">${whLabel(l)} (${l.used}/${l.capacity})</option>`).join("");
      const activeVehiclesDc = vehicles.filter(v => v.active);
      const driverOptDc = activeVehiclesDc.map(v =>
        `<option value="${esc(v.vehicle_id)}">${esc(v.driver_name || v.driver_short_name || "(chưa rõ tên)")} — ${esc(v.plate)}</option>`).join("");
      body = `<div class="panel"><h2>🔀 Điều chuyển nội bộ</h2>
        <div class="muted" style="margin-bottom:8px">Y hệt Xuất kho — chọn vị trí đích (tuỳ chọn — bỏ trống nếu chưa biết chính xác ô/kệ, hàng sẽ vào hàng đợi "Cất vào vị trí"), sau đó thêm từng dòng sản phẩm/lô/loại đơn vị + số lượng cần chuyển vào "Sản phẩm đã chọn" (thêm được nhiều lô/sản phẩm khác nhau trong cùng 1 phiếu), rồi bấm "Tạo phiếu điều chuyển". Hệ thống tự chọn đúng vỉ/keg/lon cũ nhất (FIFO) trong mỗi lô — không đúng FIFO chỉ là CẢNH BÁO, không chặn tạo phiếu. Khác Xuất kho: KHÔNG làm giảm tổng tồn kho công ty (chỉ đổi vị trí) và giữ nguyên lô/mã chiết để truy xuất nguồn gốc không đứt.</div>
        <div class="row">
          <div class="field"><label>Vị trí đích (tuỳ chọn)</label>
            <select id="dc_to"><option value="">(chưa cất vị trí)</option>${locOptDc}</select></div>
          <div class="field"><label>Lọc lô</label><select id="dc_lotfilter">
            <option value="">(tất cả lô)</option>
            <option value="has_lon">Lô có lon phân rã</option>
            <option value="no_lon">Lô không có lon phân rã</option></select></div>
          <div class="field" style="flex:1"><label>Tìm sản phẩm/lô</label><input id="dc_search" placeholder="Gõ để lọc…"/></div>
          <div class="field"><label>Nhân viên lái xe</label>
            <input id="dc_driver_q" placeholder="Tìm lái xe/biển số..." style="margin-bottom:2px"/>
            <select id="dc_driver"><option value="">(chưa chọn — xem Danh mục lái xe nếu chưa có)</option>${driverOptDc}</select></div>
        </div>
        <div id="dc_lots"></div>
        <div class="panel" style="margin-top:10px"><h3 style="font-size:14px">🛒 Sản phẩm đã chọn</h3><div id="dc_cart"></div></div>
      </div>
      <div class="panel"><h2>Lịch sử điều chuyển</h2><input class="searchbox" data-tbl="t_dc_history" placeholder="Tìm theo mã phiếu, vị trí đích, người tạo..."/><div id="dc_history" class="muted">Đang tải…</div></div>`;
    } else if (sec === "capvao") {
      const locOpt3 = myAllowedLocations(locs).map(l => `<option value="${esc(l.loc_id)}">${whLabel(l)} (${l.used}/${l.capacity})</option>`).join("");
      body = `<div class="panel"><h2>🚚 Cất vào vị trí</h2>
        <div class="muted" style="margin-bottom:8px">Gán vị trí kho cho các vỉ/keg/lon CHƯA có vị trí (mới nhập kho) — chọn vị trí đích rồi tick các dòng
          sản phẩm/lô cần cất, không cần chọn từng đơn vị.</div>
        <div class="row"><div class="field"><label>Vị trí đích</label><select id="cv_to"><option value="">(chọn vị trí đích)</option>${locOpt3}</select></div></div>
        <div id="cv_pick" class="muted" style="margin-top:10px">Đang tải danh sách chưa cất vị trí…</div>
      </div>
      <div class="panel"><h2>🔁 Chuyển vị trí trong kho</h2>
        <div class="muted" style="margin-bottom:8px">Chuyển hàng ĐÃ CẤT sang vị trí khác (VD từ khu 1 sang khu 2, từ kệ này sang kệ khác) — chỉ
          chuyển được trong CÙNG 1 kho thành phẩm, không chuyển sang kho khác (dùng tab "🔀 Điều chuyển" cho việc đó).</div>
        <div class="row"><div class="field"><label>Vị trí nguồn</label><select id="cvm_from"><option value="">(chọn vị trí nguồn)</option>${locOpt3}</select></div></div>
        <div id="cvm_pick" class="muted" style="margin-top:10px">Chọn vị trí nguồn để xem tồn kho ở đó.</div>
      </div>`;
    } else if (sec === "tudo") {
      const isAdminTudo = CURRENT_USER && CURRENT_USER.role === "admin";
      body = `<div class="panel"><h2>🚫 Xuất tự do</h2>
        <div class="muted" style="margin-bottom:8px">Xuất không qua phiếu xuất kho (hao hụt nội bộ/hủy hàng/kiểm tra chất lượng) — chỉ admin.
          Chọn đúng lô cần xuất, lấy đơn vị cũ nhất (FIFO) trước trong lô đó; bắt buộc nêu lý do. Có thể "Hoàn tác" nếu xuất nhầm.</div>
        ${isAdminTudo
          ? `<div id="fi_pick" class="muted">Đang tải danh sách lô tồn kho…</div>`
          : '<div class="muted">Chỉ tài khoản Admin mới được thực hiện xuất tự do.</div>'}
      </div>
      <div class="panel"><h2>Lịch sử xuất tự do</h2><input class="searchbox" data-tbl="t_fi_history" placeholder="Tìm theo sản phẩm, lô, người..."/><div id="fi_history" class="muted">Đang tải…</div></div>`;
    } else if (sec === "lenhdonghang") {
      const slips = await GET("/wms/load-slips").catch(() => []);
      const renderTbl = (rows, tableId) => `<input class="searchbox" data-tbl="${tableId}" placeholder="Tìm theo số phiếu, số xe, lái xe, tuyến..."/>
        <div class="tablewrap"><table id="${tableId}">
        <thead><tr><th>Số phiếu</th><th>Ca/Ngày</th><th>Số xe</th><th>Lái xe</th><th>Tuyến (NPP)</th><th>Số dòng</th><th></th></tr></thead>
        <tbody>${rows.map(s => `<tr>
          <td class="code">${esc(s.slip_code)}</td>
          <td class="muted">${esc(s.shift_label || "")} ${s.order_date ? new Date(s.order_date).toLocaleDateString("vi-VN") : ""}</td>
          <td>${esc(s.vehicle_plate)}</td><td>${esc(s.driver_name || "—")}</td>
          <td class="muted" style="max-width:260px">${esc(s.routes || "—")}</td>
          <td>${s.line_count}</td>
          <td style="white-space:nowrap"><button class="btn sm sec" data-viewload="${esc(s.load_slip_id)}">Xem/In</button>
            <button class="btn sm sec" data-delload="${esc(s.load_slip_id)}">Xóa</button></td></tr>`).join("") ||
          `<tr><td colspan=7 class="muted">Chưa có phiếu nào.</td></tr>`}</tbody></table></div>`;
      const hlSlips = slips.filter(s => s.sheet_type === "HL");
      const dmSlips = slips.filter(s => s.sheet_type === "ĐM");
      body = `<div class="panel"><h2>📥 Nhập lệnh đóng hàng</h2>
        <div class="muted" style="margin-bottom:8px">Tải lên file Excel "Lệnh đóng hàng" (2 sheet HL/ĐM) do bộ phận điều vận lập —
          hệ thống tự gộp các dòng theo <b>Số xe</b> thành từng "Biên bản bàn giao hàng hóa" riêng (khuyến mại rời không đủ vỉ/thùng
          sẽ tự tách thành dòng Lon/Lốc riêng), sẵn sàng xem/sửa và in ký khi giao hàng cho xe.</div>
        <div class="row">
          <div class="field" style="flex:1"><label>File Excel</label><input type="file" id="ld_file" accept=".xlsx"/></div>
          <button class="btn" id="ld_import" style="align-self:flex-end">Nhập file</button>
        </div></div>
        <div class="panel"><h2>Sheet HL <span class="muted">(${hlSlips.length} xe)</span></h2>${renderTbl(hlSlips, "t_loadslip_hl")}</div>
        <div class="panel"><h2>Sheet ĐM <span class="muted">(${dmSlips.length} xe)</span></h2>${renderTbl(dmSlips, "t_loadslip_dm")}</div>`;
    } else if (sec === "aging") {
      const [rows, agingOps] = await Promise.all([
        GET("/reports/inventory-aging"),
        GET("/ops-settings").catch(() => ({ aging_caution_days: 30, aging_warning_days: 60, aging_critical_days: 90 }))]);
      const canManageAging = CURRENT_USER && (CURRENT_USER.permissions === "*" ||
        (Array.isArray(CURRENT_USER.permissions) && CURRENT_USER.permissions.includes("master.manage")));
      const bucketLabel = { critical: `⛔ >${agingOps.aging_critical_days} ngày`, warning: `⚠ >${agingOps.aging_warning_days} ngày`,
        caution: `🟡 >${agingOps.aging_caution_days} ngày`, ok: "🟢 Bình thường" };
      const bucketColor = { critical: "var(--red)", warning: "var(--orange)", caution: "#e0c341", ok: "var(--green)" };
      const unitLabel = { vi: "Vỉ", keg: "Keg", lon: "Lon" };
      // Mỗi dòng backend (lot_aging_report) giờ đã tách riêng theo KHO THÀNH PHẨM (warehouse_id)
      // — cùng 1 lô ở 2 kho khác nhau ra 2 dòng riêng; trong CÙNG 1 kho mà rải nhiều vị trí thì
      // gói trong <details> để bấm mở rộng xem từng vị trí, mirror whUnitsLocationCell (Kho TP).
      const agLocLabel = (l) => `${esc(l.name ? `${l.code || "?"} - ${l.name}` : (l.code || "?"))}${locZoneSuffix(l)}`;
      const agLocCell = (r) => {
        if (r.unplaced > 0 && !r.locations.length) return `<span class="muted">(chưa cất vị trí) ×${r.unplaced}</span>`;
        const whLabel = r.warehouse_name ? `${locWhPrefix({ warehouse_name: r.warehouse_name })}` : "";
        if (r.locations.length <= 1) {
          const l = r.locations[0];
          return `${whLabel}${l ? `${agLocLabel(l)}×${l.count}` : "—"}`;
        }
        return `<details><summary style="cursor:pointer;display:inline">${whLabel}${r.locations.length} vị trí</summary>
          <table style="margin-top:4px;font-size:12px"><tbody>${r.locations.map(l =>
            `<tr><td>${agLocLabel(l)}</td><td style="padding-left:8px">${l.count}</td></tr>`).join("")}
          </tbody></table></details>`;
      };
      // Tách theo Kho thành phẩm (warehouse_id) thành từng khối riêng — mỗi kho 1 bảng độc lập
      // (search/phân trang riêng), thay vì 1 bảng chung lẫn lộn nhiều kho.
      const whBuckets = warehouses.map(w => ({ id: w.warehouse_id, label: `${esc(w.code)} — ${esc(w.name)}`, rows: [] }));
      const whBucketById = Object.fromEntries(whBuckets.map(b => [b.id, b]));
      const unknownBucket = { id: "__unknown", label: "Chưa xác định kho", rows: [] };
      rows.forEach(r => (whBucketById[r.warehouse_id] || unknownBucket).rows.push(r));
      if (unknownBucket.rows.length) whBuckets.push(unknownBucket);
      const agTableId = (i) => `t_aging_${i}`;
      const agTable = (bucket, i) => `<div class="panel"><h2>📦 ${bucket.label} <span class="muted">(${bucket.rows.length} dòng)</span></h2>
        <input class="searchbox" data-tbl="${agTableId(i)}" placeholder="Tìm theo sản phẩm/lô..."/>
        <div class="tablewrap" style="margin-top:6px"><table id="${agTableId(i)}">
          <thead><tr><th>Sản phẩm</th><th>Lô</th><th>Loại</th><th>Số lượng</th><th>Vị trí kho</th>
            <th>Ngày nhập sớm nhất</th><th>Số ngày tồn</th><th>Mức cảnh báo</th></tr></thead>
          <tbody>${bucket.rows.map(r => `<tr>
            <td>${esc(r.product_name || "—")}</td><td>${esc(r.lot_code || "—")}</td>
            <td>${unitLabel[r.unit_type] || esc(r.unit_type)}</td>
            <td>${r.count} <span class="muted">(${r.quantity})</span></td>
            <td class="muted">${agLocCell(r)}</td>
            <td class="muted">${r.received_at ? fmt(r.received_at) : "—"}</td>
            <td style="font-weight:600">${r.age_days ?? "—"}</td>
            <td style="color:${bucketColor[r.age_bucket] || "var(--muted)"}">${bucketLabel[r.age_bucket] || r.age_bucket}</td>
            </tr>`).join("") || '<tr><td colspan=8 class="muted">Kho này chưa có tồn.</td></tr>'}</tbody>
        </table></div>
      </div>`;
      body = `<div class="panel"><h2>📦 Tồn kho thành phẩm theo tuổi lô <span class="muted">(${rows.length} dòng)</span></h2>
        <div class="muted" style="margin-bottom:8px">Mỗi dòng là 1 (sản phẩm, lô, loại đơn vị) còn tồn kho — số ngày tồn tính từ đơn vị nhập sớm nhất trong nhóm.
          Dùng để báo khối kinh doanh đẩy nhanh tiến độ bán các lô tồn lâu. Sắp xếp giảm dần theo số ngày tồn (lô cũ nhất lên đầu).
          Chia riêng theo từng kho thành phẩm bên dưới.</div>
        <div class="row" style="align-items:flex-end;gap:12px;margin-bottom:10px;padding:10px;border:1px solid var(--border);border-radius:8px">
          <div class="field"><label>🟡 Chú ý từ (ngày)</label><input id="ag_caution" type="number" min="0" step="any" style="width:90px" value="${agingOps.aging_caution_days}" ${canManageAging ? "" : "disabled"}/></div>
          <div class="field"><label>⚠ Cảnh báo từ (ngày)</label><input id="ag_warning" type="number" min="0" step="any" style="width:90px" value="${agingOps.aging_warning_days}" ${canManageAging ? "" : "disabled"}/></div>
          <div class="field"><label>⛔ Nghiêm trọng từ (ngày)</label><input id="ag_critical" type="number" min="0" step="any" style="width:90px" value="${agingOps.aging_critical_days}" ${canManageAging ? "" : "disabled"}/></div>
          ${canManageAging ? `<button class="btn sec sm" id="ag_save">Lưu ngưỡng</button>` : ""}
          ${!canManageAging ? `<div class="muted" style="font-size:12px">Cần quyền <code class="k">master.manage</code> để đổi ngưỡng.</div>` : ""}
        </div>
      </div>` + whBuckets.map((b, i) => agTable(b, i)).join("");
    } else if (sec === "fgship") {
      // Chuyển từ VIEWS.reports (app.js) sang đây — nội dung báo cáo xuất kho thành phẩm hợp
      // lý hơn khi nằm cạnh các tab vận hành Kho TP. Giữ nguyên logic gốc (hiện khung màn hình
      // NGAY, mặc định NGÀY HÔM QUA, tải dữ liệu lazy qua loadFinishedGoodsShiftData()).
      const gYesterday = new Date(); gYesterday.setDate(gYesterday.getDate() - 1);
      const gMode = SUB.fgship_mode || "day";
      const gDate = SUB.fgship_date || toISODateLocal(gYesterday);
      const gMonth = SUB.fgship_month || toISODateLocal(gYesterday).slice(0, 7);
      SUB.fgship_mode = gMode; SUB.fgship_date = gDate; SUB.fgship_month = gMonth;
      body = `<div class="panel"><h2>🚚 Xuất thành phẩm theo ca</h2>
        <div class="muted" style="margin-bottom:8px">Tổng lít xuất kho (kho TP/WMS), quy đổi từ số lon/chai/keg đã xuất theo dung tích ghi trong tên SKU (VD 330ml=0.33L, 20L/30L=20/30L). Chọn 1 ngày để xem 3 ca của ngày đó, hoặc chọn cả tháng để xem theo từng ngày trong tháng.</div>
        <div class="row">
          <div class="field"><label>Xem theo</label><select id="gp_mode">
            <option value="day" ${gMode === "day" ? "selected" : ""}>Ngày cụ thể</option>
            <option value="month" ${gMode === "month" ? "selected" : ""}>Cả tháng</option></select></div>
          <div class="field" id="gp_day_field" style="${gMode === "month" ? "display:none" : ""}"><label>Ngày</label><input id="gp_date" type="date" value="${gDate}"/></div>
          <div class="field" id="gp_month_field" style="${gMode === "day" ? "display:none" : ""}"><label>Tháng</label><input id="gp_month" type="month" value="${gMonth}"/></div>
          <button class="btn" id="gp_apply">Xem báo cáo</button>
        </div></div>
        <div id="gp_data"><div class="panel muted">⏳ Đang tải dữ liệu...</div></div>`;
    } else if (sec === "phanloai") {
      // Lượng bia khuyến mại/đổi trả (theo Loại xuất của phiếu) + cận date/gửi (theo cờ trên
      // chính lô) theo ngày hoặc tháng — 4 chỉ số ĐỘC LẬP, không loại trừ nhau (1 đơn vị có thể
      // vừa khuyến mại vừa cận date). Mirror giao diện day/month của Xuất TP theo ca.
      const pYesterday = new Date(); pYesterday.setDate(pYesterday.getDate() - 1);
      const pMode = SUB.phanloai_mode || "month";
      const pDate = SUB.phanloai_date || toISODateLocal(pYesterday);
      const pMonth = SUB.phanloai_month || toISODateLocal(pYesterday).slice(0, 7);
      SUB.phanloai_mode = pMode; SUB.phanloai_date = pDate; SUB.phanloai_month = pMonth;
      body = `<div class="panel"><h2>🏷️ Khuyến mại / Đổi trả / Cận date / Gửi</h2>
        <div class="muted" style="margin-bottom:8px">4 chỉ số ĐỘC LẬP (không loại trừ nhau — 1 lô xuất có thể vừa là khuyến mại vừa là cận date): Khuyến mại/Đổi trả tính theo "Loại xuất" của phiếu (Xuất kho), Cận date/Gửi tính theo cờ trên chính lô (Nhập bia cận date/Nhập bia gửi). Đơn vị: vỉ/keg/lon quy đổi (giống Kho TP).</div>
        <div class="row">
          <div class="field"><label>Xem theo</label><select id="pl_mode">
            <option value="day" ${pMode === "day" ? "selected" : ""}>Ngày cụ thể</option>
            <option value="month" ${pMode === "month" ? "selected" : ""}>Cả tháng (theo từng ngày)</option></select></div>
          <div class="field" id="pl_day_field" style="${pMode === "month" ? "display:none" : ""}"><label>Ngày</label><input id="pl_date" type="date" value="${pDate}"/></div>
          <div class="field" id="pl_month_field" style="${pMode === "day" ? "display:none" : ""}"><label>Tháng</label><input id="pl_month" type="month" value="${pMonth}"/></div>
          <button class="btn" id="pl_apply">Xem báo cáo</button>
        </div></div>
        <div id="pl_data"><div class="panel muted">⏳ Đang tải dữ liệu...</div></div>`;
    } else if (sec === "netship") {
      // Tổng lít xuất theo (ngày, loại bia) trong 1 kỳ tùy chọn — tổng GỘP (gồm cả bia gửi),
      // tách riêng cận date/gửi, cột cuối tự trừ bia gửi (Thực xuất = Tổng lít - Gửi, KHÔNG trừ
      // cận date). Mirror giao diện từ-đến ngày của "Sản lượng lọc" (VIEWS.reports).
      const nsToday = new Date();
      const nsFrom30 = new Date(nsToday); nsFrom30.setDate(nsFrom30.getDate() - 30);
      const nsDateFrom = SUB.netship_date_from || toISODateLocal(nsFrom30);
      const nsDateTo = SUB.netship_date_to || toISODateLocal(nsToday);
      SUB.netship_date_from = nsDateFrom; SUB.netship_date_to = nsDateTo;
      const nsStart = new Date(nsDateFrom + "T06:00:00");
      const nsEnd = new Date(nsDateTo + "T06:00:00"); nsEnd.setDate(nsEnd.getDate() + 1);
      const nsQ = `date_from=${encodeURIComponent(toDTLocal(nsStart))}&date_to=${encodeURIComponent(toDTLocal(nsEnd))}`;
      const nsrep = await GET(`/reports/shipment-net-liters-report?${nsQ}`);
      const nsSeries = [
        { label: "Tổng lít", color: "#767065", values: nsrep.by_day.map(d => d.total_liters) },
        { label: "Cận date", color: "#9E6B26", values: nsrep.by_day.map(d => d.near_expiry_liters) },
        { label: "Gửi", color: "#1B5FA6", values: nsrep.by_day.map(d => d.consigned_liters) },
        { label: "Thực xuất", color: "#1F6B41", values: nsrep.by_day.map(d => d.net_liters) },
      ];
      body = `<div class="panel"><h2>🚛 Xuất ròng theo kỳ <span class="muted">(${esc(nsDateFrom)} → ${esc(nsDateTo)})</span></h2>
        <div class="muted" style="margin-bottom:8px">Tổng lít xuất theo từng loại bia, theo ngày, trong khoảng thời gian tùy chọn. "Tổng lít" gồm CẢ bia gửi; "Cận date"/"Gửi" hiện riêng để biết cấu thành (không loại trừ nhau); cột cuối "Thực xuất" = Tổng lít − Gửi (KHÔNG trừ cận date, vì cận date không phải xuất trùng của cùng 1 chuyến).</div>
        <div class="row">
          <div class="field"><label>Từ ngày</label><input id="ns_from" type="date" value="${nsDateFrom}"/></div>
          <div class="field"><label>Đến ngày</label><input id="ns_to" type="date" value="${nsDateTo}"/></div>
          <button class="btn" id="ns_apply" style="align-self:flex-end">Xem báo cáo</button>
        </div></div>
        <div class="row" style="gap:10px;flex-wrap:wrap">
          ${[["Tổng lít", nsrep.totals.total_liters, "#767065"], ["Cận date", nsrep.totals.near_expiry_liters, "#9E6B26"],
             ["Gửi", nsrep.totals.consigned_liters, "#1B5FA6"], ["Thực xuất", nsrep.totals.net_liters, "#1F6B41"]]
            .map(([label, val, color]) => `<div class="panel" style="flex:1;min-width:160px">
            <div class="muted" style="font-size:12px">${esc(label.toUpperCase())}</div>
            <div style="font-size:22px;font-weight:700;color:${color}">${val.toLocaleString("vi-VN")} <span style="font-size:13px;font-weight:400">lít</span></div>
          </div>`).join("")}
        </div>
        <div class="panel"><h2>Theo ngày</h2>
          ${nsrep.by_day.length ? CH.groupedN(nsrep.by_day.map(d => d.date.slice(5)), nsSeries) : '<div class="muted">Không có dữ liệu.</div>'}</div>
        <div class="panel"><h2>Chi tiết theo ngày × loại bia <span class="muted">(${nsrep.rows.length} dòng)</span></h2>
          <input class="searchbox" data-tbl="t_netship" placeholder="Tìm theo ngày, loại bia..."/>
          <div class="tablewrap"><table id="t_netship"><thead><tr><th>Ngày</th><th>Loại bia</th>
            <th>Tổng lít</th><th>Cận date</th><th>Gửi</th><th>Thực xuất</th></tr></thead>
          <tbody>${nsrep.rows.map(r => `<tr><td>${fmt(r.date)}</td><td>${esc(r.category)}</td>
            <td>${r.total_liters}</td><td>${r.near_expiry_liters}</td><td>${r.consigned_liters}</td>
            <td><b>${r.net_liters}</b></td></tr>`).join("") ||
            '<tr><td colspan=6 class="muted">Không có dữ liệu xuất trong kỳ này.</td></tr>'}</tbody></table></div></div>
        ${nsrep.unmatched_products.length ? `<div class="panel muted">⚠️ ${nsrep.unmatched_products.length} SKU không suy được dung tích (tên không có ml/L) nên bị loại khỏi tổng lít: ${nsrep.unmatched_products.map(u => esc(u.product_name)).join(", ")}</div>` : ""}`;
    } else if (sec === "vehiclegs") {
      // 3 báo cáo: lượt xe & tải trọng (Shipment.vehicle_id, created_at), tổng hợp bia gửi
      // (ConsignedEntry direction="in", declared_at), định mức nhiên liệu (Shipment.km/fuel_liters,
      // confirmed_at) — mirror khung từ-đến ngày của "netship".
      const vgToday = new Date();
      const vgFrom30 = new Date(vgToday); vgFrom30.setDate(vgFrom30.getDate() - 30);
      const vgDateFrom = SUB.vehiclegs_date_from || toISODateLocal(vgFrom30);
      const vgDateTo = SUB.vehiclegs_date_to || toISODateLocal(vgToday);
      SUB.vehiclegs_date_from = vgDateFrom; SUB.vehiclegs_date_to = vgDateTo;
      const vgStart = new Date(vgDateFrom + "T06:00:00");
      const vgEnd = new Date(vgDateTo + "T06:00:00"); vgEnd.setDate(vgEnd.getDate() + 1);
      const vgQ = `date_from=${encodeURIComponent(toDTLocal(vgStart))}&date_to=${encodeURIComponent(toDTLocal(vgEnd))}`;
      const [vgTrip, vgConsigned, vgFuel] = await Promise.all([
        GET(`/reports/vehicle-trip-report?${vgQ}`), GET(`/reports/consigned-summary-report?${vgQ}`),
        GET(`/reports/fuel-efficiency-report?${vgQ}`)]);
      body = `<div class="panel"><h2>🚚 Xe & bia gửi <span class="muted">(${esc(vgDateFrom)} → ${esc(vgDateTo)})</span></h2>
        <div class="muted" style="margin-bottom:8px">3 báo cáo: (1) số lượt mỗi xe đã chở đi + tổng tải trọng so với khối lượng cho phép (chỉ tính phiếu xuất kho đã gắn xe từ Danh mục lái xe); (2) tổng bia gửi đã nhận về trong kỳ; (3) định mức lít xăng/lít bia + km/lít xăng (chỉ tính phiếu đã duyệt VÀ đã điền km + lít xăng).</div>
        <div class="row">
          <div class="field"><label>Từ ngày</label><input id="vg_from" type="date" value="${vgDateFrom}"/></div>
          <div class="field"><label>Đến ngày</label><input id="vg_to" type="date" value="${vgDateTo}"/></div>
          <button class="btn" id="vg_apply" style="align-self:flex-end">Xem báo cáo</button>
        </div></div>
        <div class="panel"><h2>Lượt xe & tải trọng <span class="muted">(${vgTrip.rows.length} xe)</span></h2>
          <input class="searchbox" data-tbl="t_vg_trip" placeholder="Tìm theo mã xe, biển số, lái xe..."/>
          <div class="tablewrap"><table id="t_vg_trip"><thead><tr><th>Mã xe</th><th>Biển số</th><th>Lái xe</th>
            <th>KL cho phép (kg)</th><th>Số lượt</th><th>Tổng kg</th><th>TB tấn/lượt</th><th>Số lượt vượt tải</th></tr></thead>
          <tbody>${vgTrip.rows.map(r => `<tr>
            <td><code class="k">${esc(r.vehicle_code || "—")}</code></td><td>${esc(r.plate || "—")}</td>
            <td class="muted">${esc(r.driver_name || "—")}</td>
            <td class="muted">${r.capacity_kg != null ? r.capacity_kg.toLocaleString("vi-VN") : "—"}</td>
            <td>${r.trip_count}</td><td>${r.total_kg.toLocaleString("vi-VN")}</td><td>${r.avg_tons_per_trip}</td>
            <td style="color:${r.over_capacity_trip_count > 0 ? "var(--red)" : "var(--muted)"}">${r.over_capacity_trip_count}</td></tr>`).join("") ||
            '<tr><td colspan=8 class="muted">Không có phiếu xuất kho nào gắn xe trong kỳ này.</td></tr>'}</tbody></table></div></div>
        <div class="panel"><h2>Tổng hợp bia gửi <span class="muted">(${vgConsigned.rows.length} dòng)</span></h2>
          <input class="searchbox" data-tbl="t_vg_consigned" placeholder="Tìm theo sản phẩm..."/>
          <div class="tablewrap"><table id="t_vg_consigned"><thead><tr><th>Sản phẩm</th><th>Loại ĐV</th><th>Tổng SL</th><th>Số lần nhập</th></tr></thead>
          <tbody>${vgConsigned.rows.map(r => `<tr><td>${esc(r.product_name)}</td>
            <td>${r.unit_type === "keg" ? "Keg" : "Vỉ"}</td><td>${r.total_quantity}</td><td>${r.entry_count}</td></tr>`).join("") ||
            '<tr><td colspan=4 class="muted">Không có bia gửi nào được nhập trong kỳ này.</td></tr>'}</tbody></table></div></div>
        <div class="panel"><h2>Định mức nhiên liệu <span class="muted">(${vgFuel.rows.length} phiếu)</span></h2>
          <input class="searchbox" data-tbl="t_vg_fuel" placeholder="Tìm theo mã phiếu, biển số..."/>
          <div class="tablewrap"><table id="t_vg_fuel"><thead><tr><th>Phiếu</th><th>Mã xe</th><th>Biển số</th><th>Lái xe</th>
            <th>Km</th><th>Lít xăng</th><th>Lít bia</th><th>Lít xăng/lít bia</th><th>Km/lít xăng</th></tr></thead>
          <tbody>${vgFuel.rows.map(r => `<tr><td><code class="k">${esc(r.shipment_code)}</code></td>
            <td class="muted">${esc(r.vehicle_code || "—")}</td><td>${esc(r.plate || "—")}</td>
            <td class="muted">${esc(r.driver_name || "—")}</td><td>${r.km}</td><td>${r.fuel_liters}</td>
            <td>${r.liters_beer}</td><td>${r.l_fuel_per_l_beer != null ? r.l_fuel_per_l_beer : "—"}</td>
            <td>${r.km_per_l_fuel != null ? r.km_per_l_fuel : "—"}</td></tr>`).join("") ||
            '<tr><td colspan=9 class="muted">Chưa có phiếu nào đã duyệt VÀ đã điền km + lít xăng trong kỳ này.</td></tr>'}</tbody></table></div></div>`;
    } else if (sec === "fgstock") {
      // Chuyển từ VIEWS.reports (app.js) sang đây — hợp lý hơn khi nằm cạnh dữ liệu tồn kho TP
      // khác. Thêm bộ lọc sản phẩm/nhóm sản phẩm (chọn 1 hoặc nhiều, lưu lại cho lần sau bằng
      // localStorage — thuần hiển thị phía client, không cần lưu server) để tránh bảng quá dài
      // khi danh mục có nhiều SKU. "Nhóm sản phẩm" (FinishedProductGroup) do người dùng tự đặt
      // tên + chọn thành viên, quản lý ngay trong tab này (không tách sang Danh mục riêng).
      const FS_SEL_KEY = "mes_fgstock_selection";
      let fsSel = [];
      try { fsSel = JSON.parse(localStorage.getItem(FS_SEL_KEY) || "[]"); } catch (e) { fsSel = []; }
      const fsToday = new Date();
      const fsFrom7 = new Date(fsToday); fsFrom7.setDate(fsFrom7.getDate() - 7);
      // Từ/Đến ngày có kèm giờ (datetime-local) để lọc chính xác theo ca khi cần, không chỉ
      // theo ngày như trước.
      const fsDateFrom = SUB.fgstock_date_from || toDTLocal(fsFrom7);
      const fsDateTo = SUB.fgstock_date_to || toDTLocal(fsToday);
      SUB.fgstock_date_from = fsDateFrom; SUB.fgstock_date_to = fsDateTo;
      // Quy đổi lựa chọn (mã token "g:<group_id>" hoặc "p:<finished_product_id>") thành danh
      // sách finished_product_id thật để gửi lên server — rỗng = không lọc (hiện tất cả).
      const fpGroupById = Object.fromEntries(fpGroups.map(g => [g.group_id, g]));
      const resolvedProductIds = [...new Set(fsSel.flatMap(tok => {
        if (tok.startsWith("g:")) return (fpGroupById[tok.slice(2)]?.product_ids) || [];
        if (tok.startsWith("p:")) return [tok.slice(2)];
        return [];
      }))];
      const fsQ = `date_from=${encodeURIComponent(fsDateFrom)}&date_to=${encodeURIComponent(fsDateTo)}` +
        (resolvedProductIds.length ? `&product_ids=${resolvedProductIds.map(encodeURIComponent).join(",")}` : "");
      const fsrep = await GET(`/reports/finished-goods-stock-report?${fsQ}`);
      const fsDaysBadge = (d) => d == null ? badge("planned") :
        d < fsrep.days_of_stock_critical_days ? badge("critical") : d < fsrep.restock_days ? badge("due") : badge("available");
      const fsInStockBadge = (d) => d == null ? "" : d > fsrep.days_in_stock_warning_days ? badge("due") : badge("available");
      const fsRow = (r) => `<tr data-fprow="${esc(r.finished_product_id)}">
          <td class="code">${esc(r.code)}</td><td>${esc(r.name)}</td><td>${esc(r.uom)}</td>
          <td>${r.opening_stock.toLocaleString("vi-VN")}</td><td>${r.produced.toLocaleString("vi-VN")}</td>
          <td>${r.shipped.toLocaleString("vi-VN")}</td><td><b>${r.on_hand.toLocaleString("vi-VN")}</b></td>
          <td class="muted">${r.avg_daily_shipped_7d.toLocaleString("vi-VN")}</td>
          <td>${fsDaysBadge(r.days_of_stock)}${r.days_of_stock != null ? r.days_of_stock.toLocaleString("vi-VN") : "—"}</td>
          <td>${r.restock_suggested ? '<b style="color:var(--red)">Đóng bổ sung</b>' : '<span class="muted">—</span>'}</td>
          <td class="muted">${r.last_production_at ? fmt(r.last_production_at) : "—"}</td>
          <td class="${r.days_in_stock == null ? "muted" : ""}">${fsInStockBadge(r.days_in_stock)}${r.days_in_stock != null ? r.days_in_stock.toLocaleString("vi-VN") : "—"}</td>
          <td class="muted" title="Lấy từ Khai báo kế hoạch tiêu thụ tháng — kế hoạch điều chỉnh nếu có, không thì kế hoạch ban đầu">${r.monthly_target_stock != null ? r.monthly_target_stock.toLocaleString("vi-VN") : "—"}</td></tr>`;
      const fsFilterOpts = `<optgroup label="Nhóm sản phẩm">${fpGroups.map(g =>
          `<option value="g:${g.group_id}" ${fsSel.includes("g:" + g.group_id) ? "selected" : ""}>📁 ${esc(g.name)} (${g.product_ids.length})</option>`).join("") ||
          '<option disabled>Chưa có nhóm nào</option>'}</optgroup>
        <optgroup label="Sản phẩm">${finishedProducts.map(fp =>
          `<option value="p:${fp.finished_product_id}" ${fsSel.includes("p:" + fp.finished_product_id) ? "selected" : ""}>${esc(fp.code)} — ${esc(fp.name)}</option>`).join("")}</optgroup>`;
      // Nếu đã chọn ≥1 Nhóm sản phẩm, hiển thị bảng chia theo ĐÚNG nhóm người dùng đã đặt tên
      // (mỗi nhóm 1 khối, kể cả khi nhóm gồm nhiều category khác nhau — VD "Bia hơi, bia tươi")
      // thay vì luôn chia cứng theo category như báo cáo Excel gốc — vì người dùng đã tự định
      // nghĩa nhóm để xem gộp, chia lại theo category sẽ vô nghĩa với nhóm của họ. Sản phẩm chọn
      // riêng (không qua nhóm) mà không thuộc nhóm nào đã chọn thì gộp vào 1 khối "Sản phẩm
      // khác" ở cuối. Không chọn nhóm nào (chỉ chọn sản phẩm riêng, hoặc để trống = tất cả) thì
      // giữ đúng hành vi cũ, chia theo category.
      const fsSum = (rows, k) => Math.round(rows.reduce((s, r) => s + r[k], 0) * 100) / 100;
      const fsSubtotal = (rows) => ({ opening_stock: fsSum(rows, "opening_stock"), produced: fsSum(rows, "produced"),
        shipped: fsSum(rows, "shipped"), on_hand: fsSum(rows, "on_hand") });
      const fsSelectedGroups = fsSel.filter(t => t.startsWith("g:")).map(t => fpGroupById[t.slice(2)]).filter(Boolean);
      let fsDisplayGroups = fsrep.groups;
      if (fsSelectedGroups.length) {
        const fsRowById = Object.fromEntries(fsrep.groups.flatMap(g => g.rows).map(r => [r.finished_product_id, r]));
        fsDisplayGroups = fsSelectedGroups.map(g => {
          const rows = g.product_ids.map(id => fsRowById[id]).filter(Boolean).sort((a, b) => a.name.localeCompare(b.name));
          return { category: g.name, rows, subtotal: fsSubtotal(rows) };
        });
        const groupedIds = new Set(fsSelectedGroups.flatMap(g => g.product_ids));
        const leftoverIds = fsSel.filter(t => t.startsWith("p:")).map(t => t.slice(2)).filter(id => !groupedIds.has(id));
        if (leftoverIds.length) {
          const rows = leftoverIds.map(id => fsRowById[id]).filter(Boolean).sort((a, b) => a.name.localeCompare(b.name));
          fsDisplayGroups.push({ category: "Sản phẩm khác (không thuộc nhóm)", rows, subtotal: fsSubtotal(rows) });
        }
      }
      body = `<div class="panel"><h2>📦 NXT kho thành phẩm <span class="muted">(${esc(fmt(fsDateFrom))} → ${esc(fmt(fsDateTo))})</span></h2>
        <div class="muted" style="margin-bottom:8px">Theo mẫu báo cáo Excel thủ công đang dùng — số liệu Nhập/Xuất trong kỳ chọn; Tồn thực tế/Lượng xuất TB 7 ngày/Ngày sản xuất luôn tính tới hiện tại (không phụ thuộc kỳ chọn), dùng để dự báo tồn kho tới hạn. Ngưỡng "Đóng bổ sung" (số ngày tồn dự kiến) chỉnh ở Danh mục › Cài đặt vận hành (hiện tại: ≤ ${fsrep.restock_days} ngày). "Tồn mục tiêu tháng" lấy từ kế hoạch tiêu thụ tháng khai báo bên dưới (kế hoạch điều chỉnh nếu có, không thì kế hoạch ban đầu).</div>
        <div class="row">
          <div class="field"><label>Từ ngày (kèm giờ)</label><input id="fs_from" type="datetime-local" value="${fsDateFrom}"/></div>
          <div class="field"><label>Đến ngày (kèm giờ)</label><input id="fs_to" type="datetime-local" value="${fsDateTo}"/></div>
          <button class="btn" id="fs_apply" style="align-self:flex-end">Xem báo cáo</button>
        </div>
        <div class="row">
          <div class="field" style="flex:1"><label>Báo cáo cho (để trống = tất cả sản phẩm — chọn 1 hoặc nhiều nhóm/sản phẩm, tự lưu cho lần sau)</label>
            <select id="fs_filter" multiple size="4" style="width:100%">${fsFilterOpts}</select></div>
        </div></div>
        <div class="panel"><h3 style="margin:0 0 6px;cursor:pointer" id="fs_grp_toggle">📁 Quản lý nhóm sản phẩm ▾</h3>
          <div id="fs_grp_box" style="display:none">
            <div class="tablewrap"><table><thead><tr><th>Tên nhóm</th><th>Số sản phẩm</th><th></th></tr></thead>
            <tbody>${fpGroups.map(g => `<tr><td>${esc(g.name)}</td><td>${g.product_ids.length}</td>
              <td><button class="btn sm sec" data-editfpgroup="${esc(g.group_id)}">Sửa</button>
                  <button class="btn sm sec" data-delfpgroup="${esc(g.group_id)}">Xóa</button></td></tr>`).join("") ||
              '<tr><td colspan=3 class="muted">Chưa có nhóm nào.</td></tr>'}</tbody></table></div>
            <div class="row" style="margin-top:8px">
              <div class="field"><label>Tên nhóm mới</label><input id="fs_grp_name" placeholder="VD: Bia chai chủ lực" style="width:220px"/></div>
              <div class="field" style="flex:1"><label>Sản phẩm trong nhóm</label>
                <select id="fs_grp_members" multiple size="5" style="width:100%">${finishedProducts.map(fp =>
                  `<option value="${esc(fp.finished_product_id)}">${esc(fp.code)} — ${esc(fp.name)}</option>`).join("")}</select></div>
              <div class="field" style="align-self:flex-end"><button class="btn sec" id="fs_grp_add">+ Tạo nhóm</button></div>
            </div>
          </div>
        </div>
        <div class="panel"><h3 style="margin:0 0 6px;cursor:pointer" id="fs_mp_toggle">📅 Khai báo kế hoạch tiêu thụ tháng ▾</h3>
          <div id="fs_mp_box" style="display:none">
            <div class="muted" style="margin-bottom:8px">Mỗi SKU/tháng có 3 giá trị: "Ban đầu" (kế hoạch lập từ đầu), "Điều chỉnh" (sửa lại giữa/cuối kỳ, để trống nếu không điều chỉnh) và "SX dự kiến" (kế hoạch đóng bia dự kiến trong tháng đó). Cột "Tồn mục tiêu tháng" ở báo cáo trên lấy Điều chỉnh của THÁNG HIỆN TẠI nếu có, ngược lại lấy Ban đầu.</div>
            <div class="row" style="margin-bottom:8px">
              <div class="field"><label>Năm</label><input id="fs_mp_year" type="number" style="width:100px" value="${new Date().getFullYear()}"/></div>
              <div class="field" style="align-self:flex-end"><button class="btn sec" id="fs_mp_load">Tải bảng</button></div>
            </div>
            <div id="fs_mp_grid"><div class="muted">Bấm "Tải bảng" để xem/sửa kế hoạch.</div></div>
          </div>
        </div>
        <div class="panel"><div class="tablewrap"><table>
          <thead><tr><th>Mã số</th><th>Mặt hàng</th><th>Đvt</th><th>Tồn đầu</th><th>Nhập sản xuất</th>
            <th>Xuất ĐL &amp; KM</th><th>Tồn thực tế (TT)</th><th>Xuất TB 7 ngày</th><th>Số ngày tồn dự kiến</th>
            <th>Đề xuất</th><th>Ngày SX gần nhất</th><th>Số ngày lưu kho</th><th>Tồn mục tiêu tháng</th></tr></thead>
          <tbody>${fsDisplayGroups.map(g => `
            <tr style="background:var(--panel2);font-weight:700"><td colspan=13>${esc(g.category)}</td></tr>
            ${g.rows.map(fsRow).join("")}
            <tr style="background:var(--panel2)"><td colspan=3 class="muted">Tổng ${esc(g.category)}</td>
              <td>${g.subtotal.opening_stock.toLocaleString("vi-VN")}</td><td>${g.subtotal.produced.toLocaleString("vi-VN")}</td>
              <td>${g.subtotal.shipped.toLocaleString("vi-VN")}</td><td><b>${g.subtotal.on_hand.toLocaleString("vi-VN")}</b></td>
              <td colspan=6></td></tr>`).join("") ||
            '<tr><td colspan=13 class="muted">Chưa có Sản phẩm (thành phẩm) nào trong Danh mục, hoặc không khớp bộ lọc đã chọn.</td></tr>'}</tbody>
        </table></div></div>`;
    } else if (sec === "canexpiry") {
      const ceFpOpt = finishedProducts.map(fp => `<option value="${esc(fp.finished_product_id)}" data-code="${esc(fp.code)}">${esc(fp.code)} — ${esc(fp.name)}</option>`).join("");
      const ceLocOpt = myAllowedLocations(locs).map(l => `<option value="${esc(l.loc_id)}">${whLabel(l)} (${l.used}/${l.capacity})</option>`).join("");
      body = `<div class="panel"><h2>🕒 Nhập bia cận date</h2>
        <div class="muted" style="margin-bottom:8px">Khai báo trực tiếp Sản phẩm + Số lượng bia gần hết hạn được nhập lại kho (tăng tồn kho công ty) — không cần chọn lô chiết gốc, vì tồn cận date thực tế thường gộp từ nhiều lô khác nhau. Hệ thống tự sinh 1 lô cận date riêng cho mỗi lần khai báo — luôn hiện thành dòng riêng ở Xuất kho (không gộp chung với tồn thường của sản phẩm) và được ưu tiên xuất trước. Lịch sử nhập/xuất bia cận date được tách riêng khỏi Xuất kho thông thường (xem bảng bên dưới); khi Xuất kho tick "Chỉ bia cận date" cho 1 dòng, lượt xuất đó cũng tự động ghi vào lịch sử này.</div>
        <div class="row" style="flex-wrap:wrap">
          <div class="field"><label>Sản phẩm</label>
            <input id="ce_prod_q" placeholder="Tìm sản phẩm..." style="width:220px;margin-bottom:2px"/>
            <select id="ce_prod" style="width:220px"><option value="">(chọn sản phẩm)</option>${ceFpOpt}</select></div>
          <div class="field"><label>Số lượng</label><input id="ce_qty" type="number" min="1" style="width:100px"/></div>
          <div class="field"><label>Vị trí kho nhận</label><select id="ce_loc" style="width:180px"><option value="">(chưa cất)</option>${ceLocOpt}</select></div>
          <div class="field" style="flex:1;min-width:160px"><label>Ghi chú</label><input id="ce_note" placeholder="Tùy chọn"/></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="ce_submit">+ Nhập bia cận date</button></div>
        </div>
        <h3 style="margin-top:20px">Lịch sử bia cận date</h3>
        <input class="searchbox" data-tbl="t_ce_hist" placeholder="Tìm theo sản phẩm/lô..." style="margin-bottom:8px"/>
        <div id="ce_hist"><div class="muted">Đang tải…</div></div>
      </div>`;
    } else if (sec === "consigned") {
      const gsLocOpt = myAllowedLocations(locs).map(l => `<option value="${esc(l.loc_id)}">${whLabel(l)} (${l.used}/${l.capacity})</option>`).join("");
      // Chỉ cho chọn xe có phiếu xuất kho trong khoảng [Ca 2 ngày hôm trước 14h VN, hiện tại] —
      // khớp yêu cầu chặn khai khống bia gửi không đúng chuyến xe/sản phẩm/số lượng đã xuất
      // thật (xem services/wms.py::consigned_eligible_vehicles + _consigned_available_qty).
      // `gsEligible` được fetch cùng đợt với locs/finishedProducts/vehicles ở đầu hàm — dùng
      // biến scope ngoài để khối wire (if (sec === "consigned") { ... } phía dưới, tách khỏi
      // khối render này) cũng đọc được, tránh ReferenceError.
      const gsVehicleOpt = gsEligible.map(v =>
        `<option value="${esc(v.vehicle_id)}">${esc(v.plate)} — ${esc(v.driver_name || v.driver_short_name || "(chưa rõ tên)")}</option>`).join("");
      body = `<div class="panel"><h2>🎁 Nhập bia gửi</h2>
        <div class="muted" style="margin-bottom:8px">Dùng khi xe đã xuất phiếu đi giao trong ngày nhưng giao không hết, mang phần dư về GỬI lại kho (khác bia cận date, khác đổi trả nhà phân phối). Khai báo trực tiếp Sản phẩm + Số lượng + Biển số xe đã mang về — hệ thống tự sinh 1 lô gửi riêng cho mỗi lần khai báo, luôn hiện thành dòng riêng ở Xuất kho và được ưu tiên xuất TRƯỚC cả bia cận date. Lịch sử nhập/xuất bia gửi được tách riêng khỏi Xuất kho thông thường; khi Xuất kho tick "Chỉ bia gửi" cho 1 dòng, lượt xuất đó tự động ghi vào lịch sử này. Lưu ý: lượng xuất lại này KHÔNG tính vào báo cáo "Xuất TP theo ca" (đã tính vào phiếu xuất gốc buổi sáng, tránh đếm trùng).
        <br>Chỉ hiện xe có phiếu xuất kho từ 14h Ca 2 ngày hôm trước đến hiện tại; chọn xe xong hệ thống chỉ cho chọn đúng (những) sản phẩm xe đó đã xuất, và số lượng nhập gửi không được vượt số lượng còn lại có thể nhận gửi.</div>
        <div class="row" style="flex-wrap:wrap">
          <div class="field"><label>Biển số xe mang về</label>
            <input id="gs_vehicle_q" placeholder="Tìm xe/biển số..." style="width:200px;margin-bottom:2px"/>
            <select id="gs_vehicle" style="width:200px"><option value="">(chọn xe)</option>${gsVehicleOpt}</select></div>
          <div class="field"><label>Sản phẩm</label>
            <select id="gs_prod" style="width:220px" disabled><option value="">(chọn xe trước)</option></select></div>
          <div class="field"><label>Số lượng</label><input id="gs_qty" type="number" min="1" style="width:100px" disabled/>
            <div class="muted" id="gs_qty_hint" style="font-size:11px"></div></div>
          <div class="field"><label>Vị trí kho nhận</label><select id="gs_loc" style="width:180px"><option value="">(chọn vị trí)</option>${gsLocOpt}</select></div>
          <div class="field" style="flex:1;min-width:160px"><label>Ghi chú</label><input id="gs_note" placeholder="Tùy chọn"/></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="gs_submit">+ Nhập bia gửi</button></div>
        </div>
        ${gsEligible.length ? "" : '<div class="muted" style="margin-top:6px">⚠ Không có xe nào có phiếu xuất kho trong khoảng cho phép (từ 14h Ca 2 ngày hôm trước đến hiện tại) — chưa thể khai báo bia gửi.</div>'}
        <h3 style="margin-top:20px">Lịch sử bia gửi</h3>
        <input class="searchbox" data-tbl="t_gs_hist" placeholder="Tìm theo sản phẩm/lô..." style="margin-bottom:8px"/>
        <div id="gs_hist"><div class="muted">Đang tải…</div></div>
      </div>`;
    } else if (sec === "factoryimport") {
      // Chỉ DHLN300/FHLN020 (bia hơi/tươi Hạ Long) do nhà máy khác sản xuất — 2 mã này KHÔNG
      // được nhập qua "Nhập kho thủ công" (xem fpOptNoFactory), chỉ nhập ở đây.
      const nmkFpOpt = finishedProducts.filter(fp => ["DHLN300", "FHLN020"].includes(fp.code))
        .map(fp => `<option value="${esc(fp.finished_product_id)}" data-code="${esc(fp.code)}">${esc(fp.code)} — ${esc(fp.name)}</option>`).join("");
      const nmkLocOpt = myAllowedLocations(locs).map(l => `<option value="${esc(l.loc_id)}">${whLabel(l)} (${l.used}/${l.capacity})</option>`).join("");
      const nmkFactoryOpt = factoryLocations.filter(f => f.active).map(f => `<option value="${esc(f.factory_id)}">${esc(f.code)} — ${esc(f.name)}</option>`).join("");
      body = `<div class="panel"><h2>🏭 Nhập từ nhà máy khác</h2>
        <div class="muted" style="margin-bottom:8px">Dùng khi bia thực tế KHÔNG do nhà máy đang chạy hệ thống này sản xuất, mà nhận từ 1 nhà máy khác
          (Danh mục Nhà máy) để lưu/bán tiếp qua kho này. Khai báo Sản phẩm + Số lượng + Vị trí kho nhận + Nhà máy nguồn — sau khi Trưởng bộ phận kho
          duyệt, tồn kho tăng và lô này được xử lý HOÀN TOÀN giống bia thường (không ưu tiên xuất, không tách dòng riêng ở Xuất kho/Điều chuyển) —
          Nhà máy nguồn chỉ là dấu hiệu ghi lại để nhận biết xuất xứ, dành cho báo cáo riêng sau này.</div>
        <div class="row" style="flex-wrap:wrap">
          <div class="field"><label>Sản phẩm</label>
            <input id="nmk_prod_q" placeholder="Tìm sản phẩm..." style="width:220px;margin-bottom:2px"/>
            <select id="nmk_prod" style="width:220px"><option value="">(chọn sản phẩm)</option>${nmkFpOpt}</select></div>
          <div class="field"><label>Số lượng</label><input id="nmk_qty" type="number" min="1" style="width:100px"/></div>
          <div class="field"><label>Ngày nhập</label><input id="nmk_received_at" type="datetime-local" value="${toDTLocal(new Date())}" style="width:180px"/></div>
          <div class="field"><label>Vị trí kho nhận</label><select id="nmk_loc" style="width:180px"><option value="">(chọn vị trí)</option>${nmkLocOpt}</select></div>
          <div class="field"><label>Nhà máy nguồn</label><select id="nmk_factory" style="width:200px"><option value="">(chọn nhà máy)</option>${nmkFactoryOpt}</select></div>
          <div class="field" style="flex:1;min-width:160px"><label>Ghi chú</label><input id="nmk_note" placeholder="Tùy chọn"/></div>
          <div class="field" style="align-self:flex-end"><button class="btn" id="nmk_submit">+ Nhập từ nhà máy khác</button></div>
        </div>
        ${factoryLocations.length ? "" : '<div class="muted" style="margin-top:6px">⚠ Chưa có nhà máy nào trong Danh mục Nhà máy — khai báo ở đó trước.</div>'}
        <h3 style="margin-top:20px">Lịch sử nhập từ nhà máy khác</h3>
        <input class="searchbox" data-tbl="t_nmk_hist" placeholder="Tìm theo sản phẩm/lô..." style="margin-bottom:8px"/>
        <div id="nmk_hist"><div class="muted">Đang tải…</div></div>
      </div>`;
    }
    root.innerHTML = subnav("wms", sections, sec) + body;
    wireSubnav("wms");
    wireSearch();
    if (sec === "aging") root.querySelectorAll('table[id^="t_aging_"]').forEach(t => wirePaginate(t.id, 20));
    if (sec === "lenhdonghang") { wirePaginate("t_loadslip_hl", 10); wirePaginate("t_loadslip_dm", 10); }

    if (sec === "fgstock") {
      const FS_SEL_KEY = "mes_fgstock_selection";
      $("fs_apply").onclick = () => {
        SUB.fgstock_date_from = $("fs_from").value;
        SUB.fgstock_date_to = $("fs_to").value;
        render("wms");
      };
      $("fs_filter").onchange = () => {
        const sel = [...$("fs_filter").selectedOptions].map(o => o.value);
        localStorage.setItem(FS_SEL_KEY, JSON.stringify(sel));
        render("wms");
      };
      $("fs_grp_toggle").onclick = () => {
        const box = $("fs_grp_box");
        box.style.display = box.style.display === "none" ? "" : "none";
      };
      $("fs_grp_add").onclick = () => guard(async () => {
        const name = $("fs_grp_name").value.trim();
        if (!name) { toast("Nhập tên nhóm", "err"); return; }
        const memberIds = [...$("fs_grp_members").selectedOptions].map(o => o.value);
        if (!memberIds.length) { toast("Chọn ít nhất 1 sản phẩm cho nhóm", "err"); return; }
        await POST("/finished-product-groups", { name, product_ids: memberIds });
        toast("Đã tạo nhóm sản phẩm"); render("wms");
      });
      document.querySelectorAll("[data-delfpgroup]").forEach(b => b.onclick = () => guard(async () => {
        const gid = b.dataset.delfpgroup;
        if (!confirm("Xóa nhóm sản phẩm này?")) return;
        await DELETE(`/finished-product-groups/${gid}`);
        let sel = [];
        try { sel = JSON.parse(localStorage.getItem(FS_SEL_KEY) || "[]"); } catch (e) { sel = []; }
        localStorage.setItem(FS_SEL_KEY, JSON.stringify(sel.filter(t => t !== `g:${gid}`)));
        toast("Đã xóa nhóm sản phẩm"); render("wms");
      }));
      document.querySelectorAll("[data-editfpgroup]").forEach(b => b.onclick = () => {
        const g = fpGroups.find(x => x.group_id === b.dataset.editfpgroup);
        if (!g) return;
        modal(`<h3>Sửa nhóm sản phẩm — ${esc(g.name)}</h3>
          <div class="row"><div class="field" style="flex:1"><label>Tên nhóm</label><input id="efg_name" value="${esc(g.name)}"/></div></div>
          <div class="row"><div class="field" style="flex:1"><label>Sản phẩm trong nhóm</label>
            <select id="efg_members" multiple size="8" style="width:100%">${finishedProducts.map(fp =>
              `<option value="${esc(fp.finished_product_id)}" ${g.product_ids.includes(fp.finished_product_id) ? "selected" : ""}>${esc(fp.code)} — ${esc(fp.name)}</option>`).join("")}</select></div></div>
          <div class="row" style="margin-top:8px"><button class="btn" id="efg_save">Lưu</button></div>`);
        $("efg_save").onclick = () => guard(async () => {
          const name = $("efg_name").value.trim();
          if (!name) { toast("Nhập tên nhóm", "err"); return; }
          const memberIds = [...$("efg_members").selectedOptions].map(o => o.value);
          if (!memberIds.length) { toast("Chọn ít nhất 1 sản phẩm cho nhóm", "err"); return; }
          await PUT(`/finished-product-groups/${g.group_id}`, { name, product_ids: memberIds });
          toast("Đã lưu nhóm sản phẩm"); closeModal(); render("wms");
        });
      });
      $("fs_mp_toggle").onclick = () => {
        const box = $("fs_mp_box");
        box.style.display = box.style.display === "none" ? "" : "none";
      };
      const fsMpMonthNames = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11", "T12"];
      // Mỗi tháng gộp thành 1 ô to (.mp-box) chứa 3 ô nhỏ (KH ban đầu/KH điều chỉnh/SL SX dự
      // kiến) thay vì 3 cột riêng dùng colspan — dễ đọc hơn khi có đủ 12 tháng x 3 giá trị.
      const fsMpMonthBox = (c) => `<td><div class="mp-box">
          <div class="mp-field"><span>Ban đầu</span><input type="number" step="any" class="no-spin fs-mp-initial"
            data-month="${c.month}" value="${c.initial_qty ?? ""}"/></div>
          <div class="mp-field"><span>Điều chỉnh</span><input type="number" step="any" class="no-spin fs-mp-adjusted"
            data-month="${c.month}" value="${c.adjusted_qty ?? ""}"/></div>
          <div class="mp-field"><span>SX dự kiến</span><input type="number" step="any" class="no-spin fs-mp-expected"
            data-month="${c.month}" value="${c.expected_production_qty ?? ""}"/></div>
        </div></td>`;
      const fsMpRenderGrid = (year, grid) => {
        const head = `<thead><tr><th>Mã số</th><th>Mặt hàng</th>${fsMpMonthNames.map(m =>
          `<th>${m}</th>`).join("")}<th></th></tr></thead>`;
        const rows = grid.map(row => `<tr data-fpmprow="${esc(row.finished_product_id)}">
            <td class="code">${esc(row.code)}</td><td>${esc(row.name)}</td>
            ${row.months.map(fsMpMonthBox).join("")}
            <td><button class="btn sm sec" data-savefpmp="${esc(row.finished_product_id)}">Lưu</button></td></tr>`).join("") ||
          `<tr><td colspan=${2 + fsMpMonthNames.length + 1} class="muted">Chưa có Sản phẩm (thành phẩm) nào trong Danh mục.</td></tr>`;
        $("fs_mp_grid").innerHTML = `<div class="tablewrap"><table>${head}<tbody>${rows}</tbody></table></div>`;
        document.querySelectorAll("[data-savefpmp]").forEach(b => b.onclick = () => guard(async () => {
          const fpid = b.dataset.savefpmp;
          const tr = document.querySelector(`tr[data-fpmprow="${fpid}"]`);
          const cells = [...tr.querySelectorAll(".fs-mp-initial")].map(inp => {
            const month = parseInt(inp.dataset.month, 10);
            const adj = tr.querySelector(`.fs-mp-adjusted[data-month="${month}"]`).value;
            const exp = tr.querySelector(`.fs-mp-expected[data-month="${month}"]`).value;
            return { month, initial_qty: inp.value === "" ? null : parseFloat(inp.value),
                     adjusted_qty: adj === "" ? null : parseFloat(adj),
                     expected_production_qty: exp === "" ? null : parseFloat(exp) };
          });
          await PUT(`/finished-products/${fpid}/monthly-plan`, { year, cells });
          toast("Đã lưu kế hoạch tiêu thụ tháng"); render("wms");
        }));
      };
      $("fs_mp_load").onclick = () => guard(async () => {
        const year = parseInt($("fs_mp_year").value, 10) || new Date().getFullYear();
        const grid = await GET(`/finished-products/monthly-plan?year=${year}`);
        fsMpRenderGrid(year, grid);
      });
    }

    if (sec === "canexpiry") {
      const canApproveCe = _hasPerm("wms.confirm_receipt");
      const canEditCe = _hasPerm("warehouse.receive");
      wireSelectSearch("ce_prod", "ce_prod_q");
      $("ce_submit").onclick = () => guard(async () => {
        if (!$("ce_prod").value) { toast("Chọn sản phẩm", "err"); return; }
        const qty = parseInt($("ce_qty").value, 10) || 0;
        if (qty <= 0) { toast("Nhập số lượng > 0", "err"); return; }
        const res = await POST("/wms/near-expiry", { finished_product_id: $("ce_prod").value, quantity: qty,
          location_id: $("ce_loc").value || null, note: $("ce_note").value || null });
        toast(`Đã khai báo ${qty} ${res.unit_type === "keg" ? "keg" : "vỉ"} bia cận date — lô riêng ${res.lot_code} (chờ Trưởng bộ phận kho duyệt trước khi tăng tồn kho)`);
        render("wms");
      });
      GET("/wms/near-expiry").then(entries => {
        $("ce_hist").innerHTML = entries.length ? `<div class="tablewrap"><table id="t_ce_hist">
          <thead><tr><th>Chiều</th><th>Sản phẩm</th><th>Lô</th><th>Loại ĐV</th><th>SL</th><th>Vị trí</th><th>Ngày khai báo</th><th>Phiếu xuất</th><th>Ghi chú</th><th>Người tạo</th><th>Thời gian</th><th>Duyệt</th><th></th></tr></thead>
          <tbody>${entries.map(e => `<tr>
            <td>${e.direction === "in" ? '<span class="badge available">Nhập</span>' : '<span class="badge on_hold">Xuất</span>'}</td>
            <td>${esc(fpLabel(e.product_name))}</td><td class="muted">${esc(e.lot_code || "")}</td>
            <td>${e.unit_type === "keg" ? "Keg" : "Vỉ"}</td><td>${e.quantity}</td>
            <td class="muted">${esc(e.location_code || "—")}</td>
            <td class="muted">${e.declared_at ? fmt(e.declared_at) : "—"}</td>
            <td class="muted">${esc(e.shipment_code || "—")}</td>
            <td class="muted">${esc(e.note || "")}</td>
            <td class="muted">${esc(e.created_by || "")}</td><td class="muted">${fmt(e.created_at)}</td>
            <td>${e.direction !== "in" ? "" : e.approved_by ? `<span class="badge available">✓ ${esc(e.approved_by)}</span>` : '<span class="muted">Chờ duyệt</span>'}</td>
            <td style="white-space:nowrap">${e.reversed ? '<span class="muted">Đã hoàn tác</span>' : `
                  ${e.can_edit && canEditCe ? `<button class="btn sm sec" data-edit-ce="${esc(e.entry_id)}">Sửa</button>` : ""}
                  ${e.can_approve && canApproveCe ? `<button class="btn sm" data-approve-ce="${esc(e.entry_id)}">Duyệt</button>` : ""}
                  ${e.can_undo ? `<button class="btn sm sec" data-undo-ce="${esc(e.entry_id)}">Hoàn tác</button>` : ""}`}</td></tr>`).join("")}</tbody></table></div>`
          : `<div class="muted">Chưa có lịch sử bia cận date nào.</div>`;
        wireSearch(); wirePaginate("t_ce_hist", 10);
        document.querySelectorAll("[data-undo-ce]").forEach(b => b.onclick = () => guard(async () => {
          if (!confirm("Hoàn tác bản khai \"Nhập bia cận date\" này?")) return;
          await POST(`/wms/near-expiry/${b.dataset.undoCe}/undo`);
          toast("Đã hoàn tác bản khai bia cận date");
          render("wms");
        }));
        document.querySelectorAll("[data-approve-ce]").forEach(b => b.onclick = () => guard(async () => {
          if (!confirm("Duyệt bản khai \"Nhập bia cận date\" này? Sau khi duyệt, tồn kho sẽ tăng ngay và KHÔNG thể sửa/hoàn tác được nữa.")) return;
          await POST(`/wms/near-expiry/${b.dataset.approveCe}/approve`);
          toast("Đã duyệt — tồn kho đã tăng");
          render("wms");
        }));
        document.querySelectorAll("[data-edit-ce]").forEach(b => b.onclick = () => {
          const e = entries.find(x => x.entry_id === b.dataset.editCe);
          if (!e) return;
          modal(`<h3>Sửa bản khai bia cận date — lô ${esc(e.lot_code || "")}</h3>
            <div class="row"><div class="field"><label>Sản phẩm</label>
              <select id="ece_prod">${finishedProducts.map(fp => `<option value="${esc(fp.finished_product_id)}">${esc(fp.code)} — ${esc(fp.name)}</option>`).join("")}</select></div></div>
            <div class="row"><div class="field"><label>Số lượng</label><input id="ece_qty" type="number" min="1" value="${e.quantity}"/></div>
              <div class="field"><label>Vị trí kho nhận</label><select id="ece_loc"><option value="">(chưa cất)</option>${myAllowedLocations(locs).map(l => `<option value="${esc(l.loc_id)}">${esc(l.code)} (${l.used}/${l.capacity})</option>`).join("")}</select></div></div>
            <div class="row"><div class="field" style="flex:1"><label>Ghi chú</label><input id="ece_note" value="${esc(e.note || "")}"/></div>
              <button class="btn" id="ece_save" style="align-self:flex-end">Lưu</button></div>`);
          if ($("ece_prod")) $("ece_prod").value = e.finished_product_id || "";
          if ($("ece_loc") && e.location_code) { const o = [...$("ece_loc").options].find(op => op.textContent.startsWith(e.location_code)); if (o) $("ece_loc").value = o.value; }
          $("ece_save").onclick = () => guard(async () => {
            const qty = parseInt($("ece_qty").value, 10) || 0;
            if (qty <= 0) { toast("Nhập số lượng > 0", "err"); return; }
            await PUT(`/wms/near-expiry/${e.entry_id}`, { finished_product_id: $("ece_prod").value || null,
              quantity: qty, location_id: $("ece_loc").value || null, note: $("ece_note").value || null });
            toast("Đã lưu"); closeModal(); render("wms");
          });
        });
      }).catch(() => { $("ce_hist").innerHTML = `<div class="muted">Không tải được lịch sử.</div>`; });
    }

    if (sec === "consigned") {
      const canApproveGs = _hasPerm("wms.confirm_receipt");
      const canEditGs = _hasPerm("warehouse.receive");
      wireSelectSearch("gs_vehicle", "gs_vehicle_q");
      const gsRemainingOf = (fpid) => {
        const v = gsEligible.find(x => x.vehicle_id === $("gs_vehicle").value);
        const p = v && v.products.find(x => x.finished_product_id === fpid);
        return p ? p.remaining : 0;
      };
      $("gs_vehicle").onchange = () => {
        const v = gsEligible.find(x => x.vehicle_id === $("gs_vehicle").value);
        const prodSel = $("gs_prod"); const qtyInp = $("gs_qty");
        if (!v || !v.products.length) {
          prodSel.innerHTML = '<option value="">(chọn xe trước)</option>'; prodSel.disabled = true;
          qtyInp.disabled = true; qtyInp.value = ""; $("gs_qty_hint").textContent = "";
          return;
        }
        prodSel.innerHTML = '<option value="">(chọn sản phẩm)</option>' + v.products
          .filter(p => p.remaining > 0)
          .map(p => `<option value="${esc(p.finished_product_id)}">${esc(fpLabel(p.code))} — còn ${p.remaining} ${p.unit_type === "keg" ? "keg" : "vỉ"}</option>`).join("");
        prodSel.disabled = false; qtyInp.disabled = true; qtyInp.value = ""; $("gs_qty_hint").textContent = "";
      };
      $("gs_prod").onchange = () => {
        const remaining = gsRemainingOf($("gs_prod").value);
        const qtyInp = $("gs_qty");
        qtyInp.disabled = !$("gs_prod").value;
        qtyInp.max = remaining || "";
        $("gs_qty_hint").textContent = $("gs_prod").value ? `Tối đa ${remaining} (số lượng xe đã xuất còn lại có thể nhận gửi)` : "";
      };
      $("gs_submit").onclick = () => guard(async () => {
        if (!$("gs_vehicle").value) { toast("Chọn biển số xe đã mang bia gửi về", "err"); return; }
        if (!$("gs_prod").value) { toast("Chọn sản phẩm", "err"); return; }
        const qty = parseInt($("gs_qty").value, 10) || 0;
        if (qty <= 0) { toast("Nhập số lượng > 0", "err"); return; }
        const remaining = gsRemainingOf($("gs_prod").value);
        if (qty > remaining) { toast(`Số lượng vượt quá số xe đã xuất còn lại có thể nhận gửi (tối đa ${remaining})`, "err"); return; }
        if (!$("gs_loc").value) { toast("Chọn vị trí kho nhận", "err"); return; }
        const res = await POST("/wms/consigned", { finished_product_id: $("gs_prod").value, quantity: qty,
          location_id: $("gs_loc").value, vehicle_id: $("gs_vehicle").value, note: $("gs_note").value || null });
        toast(`Đã khai báo ${qty} ${res.unit_type === "keg" ? "keg" : "vỉ"} bia gửi — lô riêng ${res.lot_code} (chờ Trưởng bộ phận kho duyệt trước khi tăng tồn kho)`);
        render("wms");
      });
      GET("/wms/consigned").then(entries => {
        $("gs_hist").innerHTML = entries.length ? `<div class="tablewrap"><table id="t_gs_hist">
          <thead><tr><th>Chiều</th><th>Sản phẩm</th><th>Lô</th><th>Loại ĐV</th><th>SL</th><th>Vị trí</th><th>Xe gửi</th><th>Ngày khai báo</th><th>Phiếu xuất</th><th>Ghi chú</th><th>Người tạo</th><th>Thời gian</th><th>Duyệt</th><th></th></tr></thead>
          <tbody>${entries.map(e => `<tr>
            <td>${e.direction === "in" ? '<span class="badge available">Nhập</span>' : '<span class="badge on_hold">Xuất</span>'}</td>
            <td>${esc(fpLabel(e.product_name))}</td><td class="muted">${esc(e.lot_code || "")}</td>
            <td>${e.unit_type === "keg" ? "Keg" : "Vỉ"}</td><td>${e.quantity}</td>
            <td class="muted">${esc(e.location_code || "—")}</td>
            <td class="muted">${esc(e.vehicle_plate || "—")}</td>
            <td class="muted">${e.declared_at ? fmt(e.declared_at) : "—"}</td>
            <td class="muted">${esc(e.shipment_code || "—")}</td>
            <td class="muted">${esc(e.note || "")}</td>
            <td class="muted">${esc(e.created_by || "")}</td><td class="muted">${fmt(e.created_at)}</td>
            <td>${e.direction !== "in" ? "" : e.approved_by ? `<span class="badge available">✓ ${esc(e.approved_by)}</span>` : '<span class="muted">Chờ duyệt</span>'}</td>
            <td style="white-space:nowrap">${e.reversed ? '<span class="muted">Đã hoàn tác</span>' : `
                  ${e.can_edit && canEditGs ? `<button class="btn sm sec" data-edit-gs="${esc(e.entry_id)}">Sửa</button>` : ""}
                  ${e.can_approve && canApproveGs ? `<button class="btn sm" data-approve-gs="${esc(e.entry_id)}">Duyệt</button>` : ""}
                  ${e.can_undo ? `<button class="btn sm sec" data-undo-gs="${esc(e.entry_id)}">Hoàn tác</button>` : ""}`}</td></tr>`).join("")}</tbody></table></div>`
          : `<div class="muted">Chưa có lịch sử bia gửi nào.</div>`;
        wireSearch(); wirePaginate("t_gs_hist", 10);
        document.querySelectorAll("[data-undo-gs]").forEach(b => b.onclick = () => guard(async () => {
          if (!confirm("Hoàn tác bản khai \"Nhập bia gửi\" này?")) return;
          await POST(`/wms/consigned/${b.dataset.undoGs}/undo`);
          toast("Đã hoàn tác bản khai bia gửi");
          render("wms");
        }));
        document.querySelectorAll("[data-approve-gs]").forEach(b => b.onclick = () => guard(async () => {
          if (!confirm("Duyệt bản khai \"Nhập bia gửi\" này? Sau khi duyệt, tồn kho sẽ tăng ngay và KHÔNG thể sửa/hoàn tác được nữa.")) return;
          await POST(`/wms/consigned/${b.dataset.approveGs}/approve`);
          toast("Đã duyệt — tồn kho đã tăng");
          render("wms");
        }));
        document.querySelectorAll("[data-edit-gs]").forEach(b => b.onclick = () => {
          const e = entries.find(x => x.entry_id === b.dataset.editGs);
          if (!e) return;
          modal(`<h3>Sửa bản khai bia gửi — lô ${esc(e.lot_code || "")}</h3>
            <div class="row"><div class="field"><label>Sản phẩm</label>
              <select id="egs_prod">${finishedProducts.map(fp => `<option value="${esc(fp.finished_product_id)}">${esc(fp.code)} — ${esc(fp.name)}</option>`).join("")}</select></div></div>
            <div class="row"><div class="field"><label>Số lượng</label><input id="egs_qty" type="number" min="1" value="${e.quantity}"/></div>
              <div class="field"><label>Vị trí kho nhận</label><select id="egs_loc"><option value="">(chưa cất)</option>${myAllowedLocations(locs).map(l => `<option value="${esc(l.loc_id)}">${esc(l.code)} (${l.used}/${l.capacity})</option>`).join("")}</select></div></div>
            <div class="row"><div class="field" style="flex:1"><label>Ghi chú</label><input id="egs_note" value="${esc(e.note || "")}"/></div>
              <button class="btn" id="egs_save" style="align-self:flex-end">Lưu</button></div>`);
          if ($("egs_prod")) $("egs_prod").value = e.finished_product_id || "";
          if ($("egs_loc") && e.location_code) { const o = [...$("egs_loc").options].find(op => op.textContent.startsWith(e.location_code)); if (o) $("egs_loc").value = o.value; }
          $("egs_save").onclick = () => guard(async () => {
            const qty = parseInt($("egs_qty").value, 10) || 0;
            if (qty <= 0) { toast("Nhập số lượng > 0", "err"); return; }
            await PUT(`/wms/consigned/${e.entry_id}`, { finished_product_id: $("egs_prod").value || null,
              quantity: qty, location_id: $("egs_loc").value || null, note: $("egs_note").value || null });
            toast("Đã lưu"); closeModal(); render("wms");
          });
        });
      }).catch(() => { $("gs_hist").innerHTML = `<div class="muted">Không tải được lịch sử.</div>`; });
    }

    if (sec === "factoryimport") {
      const canApproveNmk = _hasPerm("wms.confirm_receipt");
      const canEditNmk = _hasPerm("warehouse.receive");
      wireSelectSearch("nmk_prod", "nmk_prod_q");
      if ($("nmk_submit")) $("nmk_submit").onclick = () => guard(async () => {
        if (!$("nmk_prod").value) { toast("Chọn sản phẩm", "err"); return; }
        const qty = parseInt($("nmk_qty").value, 10) || 0;
        if (qty <= 0) { toast("Nhập số lượng > 0", "err"); return; }
        if (!$("nmk_loc").value) { toast("Chọn vị trí kho nhận", "err"); return; }
        if (!$("nmk_factory").value) { toast("Chọn nhà máy nguồn", "err"); return; }
        const res = await POST("/wms/factory-import", { finished_product_id: $("nmk_prod").value, quantity: qty,
          location_id: $("nmk_loc").value, factory_id: $("nmk_factory").value, note: $("nmk_note").value || null,
          received_at: $("nmk_received_at").value ? new Date($("nmk_received_at").value).toISOString() : undefined });
        toast(`Đã khai báo ${qty} ${res.unit_type === "keg" ? "keg" : "vỉ"} nhập từ nhà máy khác (chờ Trưởng bộ phận kho duyệt trước khi tăng tồn kho)`);
        render("wms");
      });
      GET("/wms/factory-import").then(entries => {
        $("nmk_hist").innerHTML = entries.length ? `<div class="tablewrap"><table id="t_nmk_hist">
          <thead><tr><th>Sản phẩm</th><th>Lô</th><th>Loại ĐV</th><th>SL</th><th>Vị trí</th><th>Nhà máy nguồn</th><th>Ngày nhập</th><th>Ghi chú</th><th>Người tạo</th><th>Thời gian</th><th>Duyệt</th><th></th></tr></thead>
          <tbody>${entries.map(e => `<tr>
            <td>${esc(fpLabel(e.product_name))}</td><td class="muted">${esc(e.lot_code || "—")}</td>
            <td>${e.unit_type === "keg" ? "Keg" : "Vỉ"}</td><td>${e.quantity}</td>
            <td class="muted">${e.location_code ? `${locWhPrefix({warehouse_name: e.warehouse_name})}${e.location_name ? `${esc(e.location_code)} - ${esc(e.location_name)}` : esc(e.location_code)}${locZoneSuffix({zone: e.location_zone})}` : "—"}</td>
            <td class="muted">${esc(e.factory_name || "—")}</td>
            <td class="muted">${e.declared_at ? fmt(e.declared_at) : "—"}</td>
            <td class="muted">${esc(e.note || "")}</td>
            <td class="muted">${esc(e.created_by || "")}</td><td class="muted">${fmt(e.created_at)}</td>
            <td>${e.approved_by ? `<span class="badge available">✓ ${esc(e.approved_by)}</span>` : '<span class="muted">Chờ duyệt</span>'}</td>
            <td style="white-space:nowrap">${e.reversed ? '<span class="muted">Đã hoàn tác</span>' : `
                  ${e.can_edit && canEditNmk ? `<button class="btn sm sec" data-edit-nmk="${esc(e.entry_id)}">Sửa</button>` : ""}
                  ${e.can_approve && canApproveNmk ? `<button class="btn sm" data-approve-nmk="${esc(e.entry_id)}">Duyệt</button>` : ""}
                  ${e.can_undo ? `<button class="btn sm sec" data-undo-nmk="${esc(e.entry_id)}">Hoàn tác</button>` : ""}`}</td></tr>`).join("")}</tbody></table></div>`
          : `<div class="muted">Chưa có lịch sử nhập từ nhà máy khác nào.</div>`;
        wireSearch(); wirePaginate("t_nmk_hist", 10);
        document.querySelectorAll("[data-undo-nmk]").forEach(b => b.onclick = () => guard(async () => {
          if (!confirm("Hoàn tác bản khai \"Nhập từ nhà máy khác\" này?")) return;
          await POST(`/wms/factory-import/${b.dataset.undoNmk}/undo`);
          toast("Đã hoàn tác bản khai");
          render("wms");
        }));
        document.querySelectorAll("[data-approve-nmk]").forEach(b => b.onclick = () => guard(async () => {
          if (!confirm("Duyệt bản khai \"Nhập từ nhà máy khác\" này? Sau khi duyệt, tồn kho sẽ tăng ngay và KHÔNG thể sửa/hoàn tác được nữa.")) return;
          await POST(`/wms/factory-import/${b.dataset.approveNmk}/approve`);
          toast("Đã duyệt — tồn kho đã tăng");
          render("wms");
        }));
        document.querySelectorAll("[data-edit-nmk]").forEach(b => b.onclick = () => {
          const e = entries.find(x => x.entry_id === b.dataset.editNmk);
          if (!e) return;
          modal(`<h3>Sửa bản khai nhập từ nhà máy khác</h3>
            <div class="row"><div class="field"><label>Sản phẩm</label>
              <select id="enmk_prod">${finishedProducts.map(fp => `<option value="${esc(fp.finished_product_id)}">${esc(fp.code)} — ${esc(fp.name)}</option>`).join("")}</select></div></div>
            <div class="row"><div class="field"><label>Số lượng</label><input id="enmk_qty" type="number" min="1" value="${e.quantity}"/></div>
              <div class="field"><label>Ngày nhập</label><input id="enmk_received_at" type="datetime-local" value="${e.declared_at ? toDTLocal(new Date(e.declared_at)) : ""}"/></div>
              <div class="field"><label>Vị trí kho nhận</label><select id="enmk_loc">${myAllowedLocations(locs).map(l => `<option value="${esc(l.loc_id)}">${esc(l.code)} (${l.used}/${l.capacity})</option>`).join("")}</select></div></div>
            <div class="row"><div class="field"><label>Nhà máy nguồn</label><select id="enmk_factory">${factoryLocations.map(f => `<option value="${esc(f.factory_id)}">${esc(f.code)} — ${esc(f.name)}</option>`).join("")}</select></div></div>
            <div class="row"><div class="field" style="flex:1"><label>Ghi chú</label><input id="enmk_note" value="${esc(e.note || "")}"/></div>
              <button class="btn" id="enmk_save" style="align-self:flex-end">Lưu</button></div>`);
          if ($("enmk_prod")) $("enmk_prod").value = e.finished_product_id || "";
          if ($("enmk_loc") && e.location_code) { const o = [...$("enmk_loc").options].find(op => op.textContent.startsWith(e.location_code)); if (o) $("enmk_loc").value = o.value; }
          if ($("enmk_factory")) $("enmk_factory").value = e.factory_id || "";
          $("enmk_save").onclick = () => guard(async () => {
            const qty = parseInt($("enmk_qty").value, 10) || 0;
            if (qty <= 0) { toast("Nhập số lượng > 0", "err"); return; }
            await PUT(`/wms/factory-import/${e.entry_id}`, { finished_product_id: $("enmk_prod").value || null,
              quantity: qty, location_id: $("enmk_loc").value || null, factory_id: $("enmk_factory").value || null,
              note: $("enmk_note").value || null, received_at: $("enmk_received_at").value ? new Date($("enmk_received_at").value).toISOString() : undefined });
            toast("Đã lưu"); closeModal(); render("wms");
          });
        });
      }).catch(() => { $("nmk_hist").innerHTML = `<div class="muted">Không tải được lịch sử.</div>`; });
    }

    if (sec === "kho") {
      // Tổng hợp theo (sản phẩm, lô, loại) qua GROUP BY ở SQL (list_lot_summaries) — KHÔNG
      // tải từng đơn vị riêng lẻ về trình duyệt, vì 1 lô có thể có tới hàng trăm ngàn vỉ
      // (bug thực tế từng làm trang này treo hàng chục giây/không tải được do tải hết mọi
      // đơn vị toàn kho chỉ để gộp hiển thị bằng JS).
      const lotSummaries = await GET("/wms/units/by-lot");
      const groupRows = [];
      lotSummaries.forEach(g => {
        // unit_types: danh sách loại đơn vị THẬT SỰ có ở lô này (backend trả theo dữ liệu thực,
        // không hardcode vi/keg/lon nữa) — nếu thiếu (dữ liệu cũ) mới fallback 3 loại mặc định.
        (g.unit_types || ["vi", "keg", "lon"]).forEach(t => {
          const totalCount = g[`${t}_count`] || 0;
          if (totalCount <= 0) return;
          const totalQty = g[`${t}_qty`] || 0;
          const unplaced = g[`${t}_unplaced`] || 0;
          const totalPending = g[`${t}_pending_count`] || 0, totalConfirmed = g[`${t}_confirmed_count`] || 0;
          // Cùng 1 lô nằm ở 2 KHO THÀNH PHẨM khác nhau phải hiện thành 2 DÒNG riêng (tồn kho vật
          // lý thực sự tách biệt) — gộp theo warehouse_id trước khi tạo dòng. Trong cùng 1 kho mà
          // rải nhiều VỊ TRÍ thì vẫn 1 dòng, chỉ mở rộng xem chi tiết qua <details> ở ô "Vị trí kho"
          // (renderUnits) — không tách dòng vì vẫn là cùng 1 lô vật lý trong cùng 1 kho.
          const byWh = new Map();
          (g[`${t}_locations`] || []).forEach(l => {
            const whKey = l.warehouse_id || "";
            if (!byWh.has(whKey)) byWh.set(whKey, { warehouse_id: l.warehouse_id,
              warehouse_name: l.warehouse_name, locations: [], count: 0 });
            const b = byWh.get(whKey);
            b.locations.push(l);
            b.count += l.count;
          });
          const perUnitQty = totalCount > 0 ? totalQty / totalCount : 0;
          const pushRow = (whBucket) => {
            const count = whBucket ? whBucket.count : unplaced;
            groupRows.push({
              product: g.product_name, lot_code: g.lot_code, bottle_codes: g.bottle_codes, unit_type: t,
              count, qty: Math.round(count * perUnitQty),
              warehouse_id: whBucket ? whBucket.warehouse_id : null,
              warehouse_name: whBucket ? whBucket.warehouse_name : null,
              locations: whBucket ? whBucket.locations : [], unplaced: whBucket ? 0 : unplaced,
              oldest_at: g[`${t}_oldest_at`],
              // pending/confirmed KHÔNG tách được theo kho (backend chỉ lưu tổng theo lô+loại,
              // không theo từng vị trí) — hiện tổng toàn lô trên mọi dòng tách kho, mirror cách
              // dieuchuyen picker đã làm khi tách theo vị trí (xem filteredDcLotRows).
              pending: totalPending, confirmed: totalConfirmed,
              total_count: totalCount, total_qty: totalQty,
            });
          };
          byWh.forEach(pushRow);
          if (unplaced > 0) pushRow(null);
        });
      });
      function openUnitGroupModal(g0) {
        // Phân rã áp dụng cho MỌI loại đơn vị đóng gói (không riêng "vi") — đọc cờ
        // divide_by_pack_size từ Danh mục Loại đơn vị tồn kho thay vì hardcode 1 mã cố định
        // (xem services/wms.py::decompose_batch).
        const ut0 = utByCode[g0.unit_type];
        const canDecompose = g0.unit_type === "vi" || !!(ut0 && ut0.divide_by_pack_size);
        // Lô này còn tồn ở kho/vị trí khác nữa (dòng đang xem chỉ là 1 phần đã tách theo kho ở
        // bảng Kho TP) — Xóa/Phân rã dưới đây vẫn thao tác trên TOÀN BỘ lô ở MỌI kho (backend
        // delete-by-lot/decompose-batch chỉ lọc theo product+lot+loại đơn vị, không theo vị trí/
        // kho) nên phải cảnh báo rõ, tránh hiểu nhầm chỉ ảnh hưởng riêng dòng/kho đang xem.
        const spansMultipleWh = g0.total_count != null && g0.total_count !== g0.count;
        const spanWarning = spansMultipleWh
          ? `<div class="muted" style="color:var(--accent);margin-bottom:10px">⚠ Lô này còn tồn ở kho/vị trí khác nữa (tổng toàn bộ lô ${g0.total_count} đơn vị, dòng đang xem chỉ ${g0.count}) — các thao tác dưới đây áp dụng cho TOÀN BỘ lô ở MỌI kho, không chỉ riêng dòng này.</div>`
          : "";
        modal(`<h3>${unitTypeLabel(g0)} — ${esc(fpLabel(g0.product))} ${esc(g0.lot_code || "")}</h3>
          <div class="muted" style="margin-bottom:10px">${badge("available")}stored ·
            Tổng <b>${g0.count}</b> đơn vị · Tổng SL nhỏ <b>${g0.qty}</b></div>
          ${spanWarning}
          <div class="row" style="margin-bottom:12px"><button class="btn sec" id="ugm_label">🖨️ Tem lô (${esc(g0.lot_code || g0.product || "")})</button></div>
          ${canDecompose ? `<div class="panel" style="margin-bottom:12px"><h3 style="font-size:14px">🔨 Phân rã theo số lượng</h3>
            <div class="muted" style="font-size:12px;margin-bottom:6px">Chọn số ${esc(unitTypeLabel(g0).toLowerCase())} cần phân rã tại lô này (cũ nhất phân rã trước) — không cần chọn từng đơn vị, phù hợp cả khi tồn hàng trăm ngàn đơn vị.</div>
            <div class="row"><div class="field"><label>Số ${esc(unitTypeLabel(g0).toLowerCase())} cần phân rã (tối đa ${g0.total_count ?? g0.count})</label>
              <input id="dpq_count" type="number" min="1" max="${g0.total_count ?? g0.count}" value="${g0.total_count ?? g0.count}" style="width:110px"/></div>
              <button class="btn" id="dpq_do" style="align-self:flex-end">Phân rã</button></div></div>` : ""}`);

        $("ugm_label").onclick = () => labelModal(g0.lot_code || g0.product || "");
        if (canDecompose) {
          $("dpq_do").onclick = () => guard(async () => {
            const count = parseInt($("dpq_count").value, 10) || 0;
            const noun = unitTypeLabel(g0).toLowerCase();
            if (count <= 0) { toast(`Nhập số ${noun} cần phân rã`, "err"); return; }
            if (!confirm(`Phân rã ${count} ${noun} (cũ nhất trước) của ${g0.product || ""} ${g0.lot_code || ""}`
              + (spansMultipleWh ? ` — lấy từ CẢ lô ở mọi kho, không chỉ riêng kho đang xem` : "") + ` thành lon? Không thể hoàn tác.`)) return;
            const res = await POST("/wms/units/decompose-batch",
              { product_name: g0.product, lot_code: g0.lot_code, unit_type: g0.unit_type, count });
            closeModal();
            toast(`Đã phân rã ${res.vi_decomposed} ${noun} thành ${res.lon_created} lon`
              + (res.vi_decomposed < res.requested ? ` (chỉ còn ${res.vi_decomposed} ${noun} tồn kho, ít hơn ${res.requested} yêu cầu)` : ""));
            render("wms");
          });
        }
      }
      // Sửa/Xóa lô đã nhập THEO TIÊU CHÍ nhóm (product+lot+loại đơn vị+kho đang xem dòng này) —
      // mirror hệt cách "Duyệt nhập kho"/decompose/relocate đã thao tác trên cả nhóm, KHÔNG theo
      // từng unit_id riêng lẻ. Chỉ cho sửa/xóa khi CHƯA duyệt nhập kho (g.confirmed === 0) —
      // sau khi Trưởng bộ phận kho duyệt, coi như đã chốt số liệu (chặn ở cả 2 lớp FE/BE).
      function openEditUnitGroupModal(g) {
        const whLocs = locs.filter(l => l.warehouse_id === g.warehouse_id && l.active);
        const locOpts = `<option value="">(giữ nguyên vị trí)</option>` + whLocs.map(l =>
          `<option value="${esc(l.loc_id)}">${esc(l.code)}${l.name ? " - " + esc(l.name) : ""}</option>`).join("");
        modal(`<h3>Sửa lô đã nhập — ${esc(fpLabel(g.product))} ${esc(g.lot_code || "")}</h3>
          <div class="muted" style="margin-bottom:10px">Chỉ sửa được khi lô CHƯA được Trưởng bộ phận kho duyệt nhập kho. Áp dụng cho toàn bộ ${g.count} ${unitTypeLabel(g).toLowerCase()} của dòng đang xem.</div>
          <div class="row"><div class="field"><label>Lô TP</label><input id="egu_lot" value="${esc(g.lot_code || "")}"/></div></div>
          <div class="row"><div class="field"><label>Vị trí kho</label><select id="egu_loc">${locOpts}</select></div>
            <div class="field"><label>Ngày nhập</label><input id="egu_dt" type="datetime-local" value="${toDTLocal(new Date(g.oldest_at || Date.now()))}"/></div></div>
          <div class="muted" style="font-size:12px;margin-top:4px">Nếu dòng này gồm nhiều lượt nhập (nhiều ngày khác nhau), sửa Ngày nhập sẽ đặt lại TẤT CẢ về đúng 1 ngày.</div>
          <button class="btn" id="egu_save" style="margin-top:10px">Lưu</button>`);
        $("egu_save").onclick = () => guard(async () => {
          await PUT("/wms/units/by-lot", {
            product_name: g.product, lot_code: g.lot_code, unit_type: g.unit_type, warehouse_id: g.warehouse_id,
            new_lot_code: $("egu_lot").value.trim() || null,
            location_id: $("egu_loc").value || null,
            received_at: $("egu_dt").value ? new Date($("egu_dt").value).toISOString() : null,
          });
          toast("Đã lưu"); closeModal(); render("wms");
        });
      }
      const canConfirmReceipt = _hasPerm("wms.confirm_receipt");
      // Ô "Vị trí kho" cho bảng Kho TP — mỗi dòng ở đây đã được tách riêng theo KHO (xem
      // groupRows ở trên) nên chỉ còn vị trí trong CÙNG 1 kho; nếu kho đó rải nhiều vị trí,
      // gói trong <details> để bấm mở rộng xem từng vị trí + số lượng (không tách thành <tr>
      // riêng vì wirePaginate/sort coi mỗi <tr> con của tbody là 1 dòng độc lập — thêm <tr> phụ
      // sẽ vỡ phân trang/sắp xếp).
      function whUnitsLocationCell(g) {
        if (g.warehouse_id === null) return `<span class="muted">(chưa cất vị trí) ×${g.unplaced}</span>`;
        const whLabel = locWhPrefix({ warehouse_name: g.warehouse_name });
        if (g.locations.length <= 1) {
          const l = g.locations[0];
          return `${whLabel}${l ? `${esc(l.code || "?")}${l.name ? " - " + esc(l.name) : ""}${locZoneSuffix(l)}` : "—"}`;
        }
        return `<details><summary style="cursor:pointer;display:inline">${whLabel}${g.locations.length} vị trí</summary>
          <table style="margin-top:4px;font-size:12px"><tbody>${g.locations.map(l =>
            `<tr><td>${esc(l.code || "?")}${l.name ? " - " + esc(l.name) : ""}${locZoneSuffix(l)}</td><td style="padding-left:8px">${l.count}</td></tr>`).join("")}
          </tbody></table></details>`;
      }
      function unitConfirmCell(g, i) {
        return g.pending > 0
          ? (canConfirmReceipt ? `<button class="btn sm sec" data-confirmreceipt="${i}">Duyệt</button>` : '<span class="muted">Chờ duyệt</span>')
          : g.confirmed > 0 ? '<span class="badge available">✓ đã duyệt</span>' : '<span class="muted">—</span>';
      }
      // 1 LÔ = 1 <tr> cha (bắt buộc, KHÔNG được tách <tr> con riêng — wirePaginate/sort coi mỗi
      // <tr> trong tbody là 1 dòng độc lập, xem ghi chú ở whUnitsLocationCell) — nếu lô này có
      // nhiều hơn 1 (loại đơn vị, kho) thì gói TOÀN BỘ chi tiết (loại/SL/vị trí/duyệt/xem từng
      // dòng) vào 1 <details> trong ô "Vị trí kho", mirror đúng cách whUnitsLocationCell đã làm
      // cho riêng chiều vị trí — giờ mở rộng thêm chiều loại đơn vị.
      function renderUnits(rows) {
        const lotGroups = [];
        const byLotKey = new Map();
        rows.forEach((g, i) => {
          const key = `${g.product} ${g.lot_code}`;
          let grp = byLotKey.get(key);
          if (!grp) { grp = { product: g.product, lot_code: g.lot_code, items: [] }; byLotKey.set(key, grp); lotGroups.push(grp); }
          grp.items.push({ g, i });
        });
        const rowsHtml = lotGroups.map(lg => {
          const items = lg.items;
          if (items.length === 1) {
            const { g, i } = items[0];
            return `<tr>
              <td>${esc(fpLabel(g.product))}</td><td>${esc(g.lot_code || "")}</td>
              <td class="muted">${esc((g.bottle_codes || []).join(", ") || "—")}</td>
              <td>${unitTypeLabel(g)}</td>
              <td>${g.count}</td><td>${g.qty}</td>
              <td>${badge("available")}stored</td>
              <td class="muted">${whUnitsLocationCell(g)}</td>
              <td class="muted">${fmt(g.oldest_at)}</td>
              <td>${unitConfirmCell(g, i)}</td>
              <td style="white-space:nowrap">${g.confirmed > 0 ? "" : `<button class="btn sm sec" data-editgroup="${i}">Sửa</button>
                <button class="btn sm sec" data-delgroup="${i}" style="color:var(--red)">Xóa</button>`}
                <button class="btn sm sec" data-viewgroup="${i}">Xem</button></td></tr>`;
          }
          // Nhiều (loại, kho) cho CÙNG 1 lô (VD vừa còn Két vừa đã phân rã lẻ Chai, hoặc cùng lô
          // nằm ở 2 kho thành phẩm) — trước đây mỗi tổ hợp ra HẲN 1 dòng riêng khiến 1 lô vật lý
          // duy nhất trông như nhiều lô khác nhau. Giờ gộp về 1 dòng cha, liệt kê từng tổ hợp
          // (loại/SL/vị trí/duyệt/xem riêng) trong bảng con thu gọn được.
          const totalQty = items.reduce((s, it) => s + (it.g.qty || 0), 0);
          const oldestAt = items.reduce((min, it) => (!min || (it.g.oldest_at && it.g.oldest_at < min)) ? it.g.oldest_at : min, null);
          const typesLabel = [...new Set(items.map(it => unitTypeLabel(it.g)))].join(", ");
          const detailRows = items.map(it => `<tr>
            <td style="padding:2px 10px 2px 0">${unitTypeLabel(it.g)}</td>
            <td style="padding:2px 10px">${it.g.count} <span class="muted">(${it.g.qty} lẻ)</span></td>
            <td style="padding:2px 10px">${whUnitsLocationCell(it.g)}</td>
            <td style="padding:2px 10px">${unitConfirmCell(it.g, it.i)}</td>
            <td style="padding:2px 0;white-space:nowrap">${it.g.confirmed > 0 ? "" : `<button class="btn sm sec" data-editgroup="${it.i}">Sửa</button>
              <button class="btn sm sec" data-delgroup="${it.i}" style="color:var(--red)">Xóa</button>`}
              <button class="btn sm sec" data-viewgroup="${it.i}">Xem</button></td></tr>`).join("");
          return `<tr>
            <td>${esc(fpLabel(lg.product))}</td><td>${esc(lg.lot_code || "")}</td>
            <td class="muted">${esc((items[0].g.bottle_codes || []).join(", ") || "—")}</td>
            <td>${esc(typesLabel)}</td>
            <td class="muted">—</td><td>${totalQty}</td>
            <td>${badge("available")}stored</td>
            <td class="muted"><details><summary style="cursor:pointer">${items.length} loại/vị trí</summary>
              <table style="margin-top:4px;font-size:12px"><tbody>${detailRows}</tbody></table></details></td>
            <td class="muted">${fmt(oldestAt)}</td>
            <td class="muted">— (xem trong chi tiết)</td>
            <td></td></tr>`;
        }).join("") || '<tr><td colspan=11 class="muted">Chưa có vỉ/keg nào trong kho.</td></tr>';
        $("pl_box").innerHTML = `<input class="searchbox" data-tbl="t_units" placeholder="Tìm theo sản phẩm, lô..."/>
          <div class="tablewrap"><table id="t_units">
          <thead><tr><th>SP</th><th>Lô</th><th>Mã chiết</th><th>Loại</th><th>Số lượng</th><th>Tổng SL nhỏ</th><th>Trạng thái</th>
            <th>Vị trí kho</th><th>Nhập sớm nhất</th><th>Duyệt nhập kho</th><th></th></tr></thead>
          <tbody>${rowsHtml}</tbody></table></div>`;
        document.querySelectorAll("[data-viewgroup]").forEach(b => b.onclick = () => {
          openUnitGroupModal(rows[parseInt(b.dataset.viewgroup, 10)]);
        });
        document.querySelectorAll("[data-editgroup]").forEach(b => b.onclick = () => {
          openEditUnitGroupModal(rows[parseInt(b.dataset.editgroup, 10)]);
        });
        document.querySelectorAll("[data-delgroup]").forEach(b => b.onclick = () => guard(async () => {
          const g = rows[parseInt(b.dataset.delgroup, 10)];
          if (!confirm(`Xóa ${g.count} ${unitTypeLabel(g).toLowerCase()} đã nhập kho của ${g.product || ""} ${g.lot_code || ""} (tại vị trí đang xem)? Bản ghi Chiết nguồn sẽ được mở lại (bỏ duyệt KCS) để có thể sửa/duyệt lại. Không thể hoàn tác.`)) return;
          const res = await POST("/wms/units/delete-by-lot",
            { product_name: g.product, lot_code: g.lot_code, unit_type: g.unit_type, warehouse_id: g.warehouse_id });
          toast(`Đã xóa ${res.deleted} đơn vị đã nhập kho`
            + (res.bottles_reset.length ? ` — đã mở lại duyệt KCS cho: ${res.bottles_reset.join(", ")}` : ""));
          render("wms");
        }));
        document.querySelectorAll("[data-confirmreceipt]").forEach(b => b.onclick = () => guard(async () => {
          const g = rows[parseInt(b.dataset.confirmreceipt, 10)];
          // Duyệt nhập kho thao tác trên TOÀN BỘ lô+loại đơn vị (mọi kho), không riêng dòng đã
          // tách theo kho ở bảng này — xem ghi chú tương tự ở openUnitGroupModal.
          const warn = g.total_count != null && g.total_count !== g.count
            ? ` (áp dụng cho TOÀN BỘ lô ở mọi kho, tổng ${g.total_count} đơn vị — không chỉ riêng dòng này)` : "";
          if (!confirm(`Duyệt nhập kho cho ${g.product || ""} ${g.lot_code || ""}${warn}? Sau khi duyệt, lô này không thể xóa được nữa — với lô "Nhập kho thủ công" còn được phép xuất kho.`)) return;
          const res = await POST("/wms/units/confirm-receipt-by-lot",
            { product_name: g.product, lot_code: g.lot_code, unit_type: g.unit_type });
          toast(`Đã duyệt nhập kho cho ${res.confirmed} dòng`); render("wms");
        }));
        wireSearch();
        wirePaginate("t_units", 10);
      }
      renderUnits(groupRows);
      const productDivides = (prefix) => {
        const prodEl = $(`${prefix}_prod`);
        const opt = prodEl && prodEl.selectedOptions[0];
        const unitType = opt && opt.value ? (opt.dataset.unittype || "vi") : "vi";
        const ut = utByCode[unitType];
        return ut ? ut.divide_by_pack_size : unitType === "vi";
      };
      const buildDivisor = (prefix) => {
        const prodEl = $(`${prefix}_prod`);
        const opt = prodEl && prodEl.selectedOptions[0];
        const unitType = opt && opt.value ? (opt.dataset.unittype || "vi") : "vi";
        const ut = utByCode[unitType];
        const pack = num(`${prefix}_pack`) || 1;
        const divides = productDivides(prefix);
        const lonModeEl = $(`${prefix}_lonmode`);
        const lonMode = divides && !!(lonModeEl && lonModeEl.checked);
        const packLabel = `Số ${ut ? ut.name : (unitType === "keg" ? "Keg" : "Vỉ")}`;
        const smallLabel = divides ? `Số ${smallUnitNoun(opt && opt.textContent)}` : packLabel;
        return { divisor: lonMode ? 1 : (divides ? pack : 1), divides, lonMode, packLabel, smallLabel };
      };
      const updateBuildLabels = (prefix) => {
        const { divides, lonMode, packLabel, smallLabel } = buildDivisor(prefix);
        const countLabelEl = $(`${prefix}_count_label`);
        const totalLabelEl = $(`${prefix}_total_label`);
        const totalWrapEl = $(`${prefix}_total_wrap`);
        const countWrapEl = $(`${prefix}_count_wrap`);
        const lonModeWrapEl = $(`${prefix}_lonmode_wrap`);
        if (countLabelEl) countLabelEl.textContent = packLabel;
        if (totalLabelEl) totalLabelEl.textContent = smallLabel;
        // Số SL nhỏ chỉ cần hiện khi "Nhập lẻ" bật (nhập trực tiếp theo lon/đơn vị nhỏ) — bình
        // thường chỉ cần nhập Số Vỉ, SL nhỏ tự quy đổi ngầm nên không cần chiếm chỗ trên form.
        if (totalWrapEl) totalWrapEl.style.display = lonMode ? "" : "none";
        if (countWrapEl) countWrapEl.style.display = lonMode ? "none" : "";
        if (lonModeWrapEl) lonModeWrapEl.style.display = divides ? "" : "none";
      };
      const syncBuildFromCount = (prefix) => {
        const { divisor } = buildDivisor(prefix);
        const count = num(`${prefix}_count`) || 0;
        $(`${prefix}_total`).value = Math.round(count * divisor * 100) / 100;
        updateBuildLabels(prefix);
      };
      const syncBuildFromTotal = (prefix) => {
        const { divisor } = buildDivisor(prefix);
        const total = num(`${prefix}_total`) || 0;
        $(`${prefix}_count`).value = Math.round((total / divisor) * 10000) / 10000;
        updateBuildLabels(prefix);
      };
      wireSelectSearch("wu_prod", "wu_prod_q");
      if ($("wu_prod")) $("wu_prod").onchange = () => {
        const opt = $("wu_prod").selectedOptions[0];
        if (opt && opt.dataset.pack) $("wu_pack").value = opt.dataset.pack;
        if (!productDivides("wu") && $("wu_lonmode")) $("wu_lonmode").checked = false;
        syncBuildFromCount("wu");
      };
      if ($("wu_count")) $("wu_count").oninput = () => syncBuildFromCount("wu");
      if ($("wu_total")) $("wu_total").oninput = () => syncBuildFromTotal("wu");
      if ($("wu_lonmode")) $("wu_lonmode").onchange = () => syncBuildFromTotal("wu");
      if ($("wu_build")) $("wu_build").onclick = () => guard(async () => {
        if (!$("wu_prod").value) { toast("Chọn sản phẩm", "err"); return; }
        if (!$("wu_loc").value) { toast("Chọn vị trí kho trước khi nhập", "err"); return; }
        const opt = $("wu_prod").selectedOptions[0];
        const { lonMode } = buildDivisor("wu");
        await POST("/wms/units", { finished_product_id: $("wu_prod").value, product_name: opt.dataset.code,
          lot_code: $("wu_lot").value.trim() || undefined, total: num("wu_total") || 0,
          pack_size: lonMode ? 1 : (num("wu_pack") || 24), unit_type: lonMode ? "lon" : (opt.dataset.unittype || "vi"),
          loc_id: $("wu_loc").value, reason: "Nhập kho thủ công",
          received_at: $("wu_received_at").value ? new Date($("wu_received_at").value).toISOString() : undefined });
        toast("Đã nhập kho (kèm mã vạch từng vỉ/keg)"); render("wms");
      });
      wireSelectSearch("wob_prod", "wob_prod_q");
      if ($("wob_prod")) $("wob_prod").onchange = () => {
        const opt = $("wob_prod").selectedOptions[0];
        if (opt && opt.dataset.pack) $("wob_pack").value = opt.dataset.pack;
        if (!productDivides("wob") && $("wob_lonmode")) $("wob_lonmode").checked = false;
        syncBuildFromCount("wob");
      };
      if ($("wob_count")) $("wob_count").oninput = () => syncBuildFromCount("wob");
      if ($("wob_total")) $("wob_total").oninput = () => syncBuildFromTotal("wob");
      if ($("wob_lonmode")) $("wob_lonmode").onchange = () => syncBuildFromTotal("wob");
      // Ẩn/hiện ô Số SL nhỏ/Số Vỉ chỉ được set trong các handler onchange/oninput ở trên — nếu
      // không gọi ngay 1 lần ở đây, lúc mới vào trang (chưa bấm gì) cả 2 ô đều hiện mặc định
      // theo HTML gốc, chỉ ẩn đúng sau khi người dùng tương tác lần đầu (chọn SP/gõ số lượng).
      updateBuildLabels("wu");
      updateBuildLabels("wob");
      if ($("wob_build")) $("wob_build").onclick = () => guard(async () => {
        if (!$("wob_prod").value) { toast("Chọn sản phẩm", "err"); return; }
        if (!$("wob_loc").value) { toast("Chọn vị trí kho trước khi nhập", "err"); return; }
        const opt = $("wob_prod").selectedOptions[0];
        const { lonMode } = buildDivisor("wob");
        await POST("/wms/units", { finished_product_id: $("wob_prod").value, product_name: opt.dataset.code,
          lot_code: $("wob_lot").value, total: num("wob_total") || 0,
          pack_size: lonMode ? 1 : (num("wob_pack") || 24), unit_type: lonMode ? "lon" : (opt.dataset.unittype || "vi"),
          loc_id: $("wob_loc").value, reason: "Nhập tồn đầu", is_opening_balance: true,
          received_at: $("wob_received_at").value ? new Date($("wob_received_at").value).toISOString() : undefined });
        toast("Đã nhập tồn đầu (kèm mã vạch từng vỉ/keg)"); render("wms");
      });
      if ($("wob_import")) $("wob_import").onclick = () => guard(async () => {
        const f = $("wob_file").files[0];
        if (!f) throw new Error("Chọn file Excel trước.");
        const fd = new FormData();
        fd.append("file", f);
        const headers = {};
        if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
        const res = await fetch("/api/wms/units/opening-balance/import", { method: "POST", headers, body: fd });
        const result = await res.json();
        if (!res.ok) throw new Error(result && result.detail ? result.detail : "HTTP " + res.status);
        if (result.failed && result.failed.length) {
          alert(`Đã nhập ${result.created.length}/${result.total} dòng. ${result.failed.length} dòng lỗi:\n` +
            result.failed.map(x => `Dòng ${x.row}: ${x.reason}`).join("\n"));
        } else {
          toast(`Đã nhập tồn đầu từ Excel: ${result.created.length}/${result.total} dòng`);
        }
        render("wms");
      });
      GET("/audit?entity_type=finished_goods_unit").then(entries => {
        const rows = entries.filter(e => e.action === "decompose_batch");
        // Chỉ hoàn tác được lượt phân rã (a) chưa từng hoàn tác trước đó và (b) có lưu
        // source_unit_ids/lon_unit_ids (lượt phân rã cũ trước khi có tính năng này thì không).
        const undone = new Set(entries.filter(e => e.action === "undo_decompose_batch")
          .map(e => e.before?.decompose_audit_id).filter(Boolean));
        $("dp_history").innerHTML = rows.length ? `<div class="tablewrap"><table id="t_dp_history">
          <thead><tr><th>SP</th><th>Lô</th><th>Số vỉ đã phân rã</th><th>Số lon sinh ra</th><th>Thời gian</th><th>Người</th><th></th></tr></thead>
          <tbody>${rows.map(e => `<tr><td>${esc(fpLabel(e.before?.product_name))}</td>
            <td class="muted">${esc(e.before?.lot_code || "")}</td>
            <td>${e.after?.vi_decomposed ?? ""}</td><td>${e.after?.lon_created ?? ""}</td>
            <td class="muted">${fmt(e.ts)}</td><td class="muted">${esc(e.actor || "")}</td>
            <td>${undone.has(e.audit_id) ? '<span class="muted">Đã hoàn tác</span>' :
              (e.after?.lon_unit_ids ? `<button class="btn sm sec" data-undodecompose="${esc(e.audit_id)}">Hoàn tác</button>` : '<span class="muted">—</span>')}</td></tr>`).join("")}</tbody></table></div>`
          : `<div class="muted">Chưa có lượt phân rã nào.</div>`;
        wireSearch(); wirePaginate("t_dp_history", 10);
        document.querySelectorAll("[data-undodecompose]").forEach(b => b.onclick = () => guard(async () => {
          if (!confirm("Hoàn tác lượt phân rã này? Chỉ thực hiện được nếu chưa có lon nào xuất kho.")) return;
          const res = await POST(`/wms/units/decompose-batch/${b.dataset.undodecompose}/undo`, {});
          toast(`Đã hoàn tác: khôi phục ${res.vi_restored} vỉ, xóa ${res.lon_removed} lon`);
          render("wms");
        }));
      }).catch(() => { $("dp_history").innerHTML = `<div class="muted">Không tải được lịch sử.</div>`; });
      // Sơ đồ kho Đông Mai — CHỈ kho có code "KH01" (fallback: tên chứa "Đông Mai" nếu code lỡ
      // đổi) vì đây là sơ đồ mặt bằng thật của 1 nhà máy cụ thể, không áp dụng cho kho khác.
      const dongMai = warehouses.find(w => w.code === "KH01") || warehouses.find(w => (w.name || "").includes("Đông Mai"));
      if (dongMai) {
        GET(`/wms/warehouses/${dongMai.warehouse_id}/floor-map`).then(floorRows => {
          $("floor_map_box").innerHTML = renderDongMaiFloorMap(floorRows);
        }).catch(() => { $("floor_map_box").innerHTML = `<div class="muted">Không tải được sơ đồ kho.</div>`; });
      } else {
        $("floor_map_box").innerHTML = `<div class="muted">Chưa khai báo Kho Đông Mai (mã KH01).</div>`;
      }
    } else if (sec === "xuatkho") {
      const lots = await GET("/wms/units/by-lot");
      const shipmentTypeLabel = (t) => t === "promo" ? "Khuyến mại" : t === "return" ? "Đổi trả" : "Thường";
      const XK_TYPE_OPTIONS = `<option value=""></option><option value="promo">Khuyến mại</option><option value="return">Đổi trả</option>`;

      function filteredLotRows() {
        const filter = $("xk_lotfilter").value;
        const search = $("xk_search").value.trim().toLowerCase();
        const whFilter = $("xk_wh") ? $("xk_wh").value : "";
        const rows = [];
        lots.forEach(g => {
          if (filter === "has_lon" && !g.has_lon) return;
          if (filter === "no_lon" && g.has_lon) return;
          if (search && !`${g.product_name || ""} ${g.lot_code || ""}`.toLowerCase().includes(search)) return;
          (g.unit_types || ["vi", "keg", "lon"]).forEach(t => {
            let locations = g[`${t}_locations`] || [];
            let unplaced = g[`${t}_unplaced`] || 0;
            let count = g[`${t}_count`];
            // Đã chọn "Kho xuất" cụ thể — chỉ tính hàng ĐANG CẤT ĐÚNG kho đó (hàng "chưa cất" bỏ
            // qua vì chưa xác định được thuộc kho nào, xem docstring _assert_wh_scope).
            if (whFilter) {
              locations = locations.filter(l => l.warehouse_code === whFilter);
              count = locations.reduce((s, l) => s + (l.count || 0), 0);
              unplaced = 0;
            }
            if (count) rows.push({ product_name: g.product_name, lot_code: g.lot_code, unit_type: t, count,
                                   fifo_ok: g[`${t}_fifo_ok`], oldest_at: g[`${t}_oldest_at`], bottle_codes: g.bottle_codes,
                                   locations, unplaced,
                                   near_expiry_count: g[`${t}_near_expiry_count`] || 0,
                                   consigned_count: g[`${t}_consigned_count`] || 0,
                                   consigned_vehicle_plate: g.consigned_vehicle_plate });
          });
        });
        // Lô có bia GỬI lên đầu bảng TRƯỚC CẢ cận date (xe đã xuất phiếu buổi sáng giao không
        // hết, mang về gửi — cần xuất lại sớm nhất); sau đó tới lô có bia CẬN DATE; trong cùng
        // nhóm mới sắp theo tên sản phẩm, rồi tới lô/loại cũ nhất (FIFO) — giúp người xuất dễ
        // tìm và luôn thấy dòng nào nên chọn trước.
        rows.sort((a, b) => (((b.consigned_count || 0) > 0 ? 1 : 0) - ((a.consigned_count || 0) > 0 ? 1 : 0)) ||
          (((b.near_expiry_count || 0) > 0 ? 1 : 0) - ((a.near_expiry_count || 0) > 0 ? 1 : 0)) ||
          (a.product_name || "").localeCompare(b.product_name || "") ||
          new Date(a.oldest_at || 0) - new Date(b.oldest_at || 0));
        return rows;
      }

      // Chỉ hàng ĐÃ CẤT vào 1 vị trí kho cụ thể mới được phép chọn xuất — hàng "chưa cất"
      // (unplaced) vẫn hiển thị để người dùng biết mà đi cất trước, nhưng không tính vào SL
      // được phép chọn (khớp exclude_unplaced ở backend create_shipment).
      function sellableOf(r) { return Math.max(0, r.count - (r.unplaced || 0)); }

      function renderLots() {
        const rows = filteredLotRows();
        $("xk_lots").innerHTML = rows.length ? `<div class="tablewrap" style="margin-top:10px"><table id="t_xk_lots">
          <thead><tr><th>Sản phẩm</th><th>Lô</th><th>Mã chiết</th><th>Loại</th><th>Tồn</th><th>Vị trí kho</th><th>FIFO</th><th>Biển số xe gửi</th><th>SL cần xuất</th><th>Loại xuất</th><th>Bia gửi</th><th>Cận date</th><th></th></tr></thead>
          <tbody>${rows.map((r, i) => { const sellable = sellableOf(r); const neAvailable = (r.near_expiry_count || 0) > 0;
            const neFull = neAvailable && r.count === r.near_expiry_count;
            const gsAvailable = (r.consigned_count || 0) > 0;
            const gsFull = gsAvailable && r.count === r.consigned_count;
            return `<tr${gsFull ? ' class="row-cyan"' : neFull ? ' class="row-cyan"' : ""}>
            <td>${esc(fpLabel(r.product_name))}</td><td>${esc(r.lot_code || "")}</td>
            <td class="muted">${esc((r.bottle_codes || []).join(", ") || "—")}</td>
            <td>${unitTypeLabel({ product: r.product_name, unit_type: r.unit_type })}</td><td>${r.count}</td>
            <td class="muted">${r.locations.length > 1 ? `<details>
                <summary style="cursor:pointer;display:inline">${r.locations.length} vị trí — bấm để chọn xuất riêng</summary>
                <table style="margin-top:4px;font-size:12px;width:100%"><tbody>${r.locations.map((l, li) => `
                  <tr><td style="padding-right:6px">${whLabel(l)}</td><td style="padding-right:6px">${l.count}</td>
                    <td style="padding-right:6px"><input type="number" min="1" max="${l.count}" value="${l.count}" style="width:60px" data-xk-locqty="${i}_${li}"/></td>
                    <td><button class="btn sm" data-xk-locadd="${i}_${li}">+ Thêm</button></td></tr>`).join("")}
                </tbody></table>
              </details>` : locationCell(r)}</td>
            <td>${r.fifo_ok ? '<span class="badge available">✓ FIFO</span>' : '<span class="badge on_hold">⚠ Không phải lô cũ nhất</span>'}</td>
            <td class="muted">${gsAvailable ? esc(r.consigned_vehicle_plate || "—") : "—"}</td>
            <td><input type="number" min="1" max="${sellable}" value="${sellable}" style="width:80px" data-xk-qty="${i}" ${sellable > 0 ? "" : "disabled"}
              title="${sellable > 0 ? "" : "Chưa cất vào vị trí kho — không thể xuất"}"/></td>
            <td><select data-xk-type="${i}">${XK_TYPE_OPTIONS}</select></td>
            <td title="${gsFull ? "Toàn bộ lô này là bia gửi — luôn xuất là bia gửi" : gsAvailable ? "Chỉ chọn vỉ/keg từ Nhập bia gửi" : "Lô/loại này chưa có bia gửi nào được khai báo"}">
              ${gsFull ? '<span class="badge on_hold">🎁 Bia gửi</span>' : `<input type="checkbox" data-xk-gs="${i}" ${gsAvailable ? "" : "disabled"}/>`}</td>
            <td title="${neFull ? "Toàn bộ lô này là bia cận date — luôn xuất là bia cận date" : neAvailable ? "Chỉ chọn vỉ/keg từ Nhập bia cận date" : "Lô/loại này chưa có bia cận date nào được khai báo"}">
              ${neFull ? '<span class="badge on_hold">🕒 Cận date</span>' : `<input type="checkbox" data-xk-ne="${i}" ${neAvailable ? "" : "disabled"}/>`}</td>
            <td><button class="btn sm" data-xk-add="${i}">+ Thêm</button></td></tr>`; }).join("")}</tbody></table></div>`
          : `<div class="muted" style="margin-top:10px">Không còn lô nào tồn kho khớp bộ lọc.</div>`;
        wirePaginate("t_xk_lots", 10);
        rows.forEach((r, i) => {
          const btn = document.querySelector(`[data-xk-add="${i}"]`);
          if (!btn) return;
          btn.onclick = () => {
            const sellable = sellableOf(r);
            if (sellable <= 0) { toast("Lô/loại này chưa được cất vào vị trí kho nào — không thể chọn xuất. Hãy cất hàng vào vị trí trước.", "err"); return; }
            const qty = parseInt(document.querySelector(`[data-xk-qty="${i}"]`).value, 10) || 0;
            if (qty <= 0) { toast("Nhập số lượng > 0", "err"); return; }
            if (qty > sellable) { toast(`Chỉ có ${sellable} đã cất vào vị trí kho (còn ${r.unplaced} chưa cất, không thể chọn xuất phần chưa cất)`, "err"); return; }
            const neFull = (r.near_expiry_count || 0) > 0 && r.count === r.near_expiry_count;
            const neCheckbox = document.querySelector(`[data-xk-ne="${i}"]`);
            const near_expiry_only = neFull || (neCheckbox ? neCheckbox.checked : false);
            const gsFull = (r.consigned_count || 0) > 0 && r.count === r.consigned_count;
            const gsCheckbox = document.querySelector(`[data-xk-gs="${i}"]`);
            const consigned_only = gsFull || (gsCheckbox ? gsCheckbox.checked : false);
            if (near_expiry_only && consigned_only) { toast("Chỉ được chọn 1 trong 2 — bia cận date HOẶC bia gửi.", "err"); return; }
            if (near_expiry_only && !((r.near_expiry_count || 0) > 0)) { toast("Lô/loại này chưa có bia cận date nào được khai báo.", "err"); return; }
            if (near_expiry_only && qty > r.near_expiry_count) { toast(`Chỉ còn ${r.near_expiry_count} bia cận date cho lô/loại này`, "err"); return; }
            if (consigned_only && !((r.consigned_count || 0) > 0)) { toast("Lô/loại này chưa có bia gửi nào được khai báo.", "err"); return; }
            if (consigned_only && qty > r.consigned_count) { toast(`Chỉ còn ${r.consigned_count} bia gửi cho lô/loại này`, "err"); return; }
            const shipment_type = document.querySelector(`[data-xk-type="${i}"]`).value;
            XK_CART.push({ product_name: r.product_name, lot_code: r.lot_code, unit_type: r.unit_type,
                          quantity: qty, shipment_type, near_expiry_only, consigned_only, fifo_ok: r.fifo_ok,
                          location_label: placedLocationLabel(r) });
            renderCart();
            toast(`Đã thêm ${qty} ${unitTypeLabel({ product: r.product_name, unit_type: r.unit_type }).toLowerCase()} vào phiếu${consigned_only ? " (chỉ bia gửi)" : near_expiry_only ? " (chỉ bia cận date)" : ""}`);
          };
          // Lô/loại rải nhiều vị trí — cho chọn xuất riêng TỪNG vị trí (thay vì chỉ có nút gộp
          // ở trên tự FIFO xuyên vị trí) bằng cách gắn location_id lên từng dòng gửi lên server
          // (xem ShipmentLineIn.location_id + _consume_lot_rows(location_id=...)).
          (r.locations || []).forEach((l, li) => {
            const locBtn = document.querySelector(`[data-xk-locadd="${i}_${li}"]`);
            if (!locBtn) return;
            locBtn.onclick = () => {
              const qty = parseInt(document.querySelector(`[data-xk-locqty="${i}_${li}"]`).value, 10) || 0;
              if (qty <= 0) { toast("Nhập số lượng > 0", "err"); return; }
              if (qty > l.count) { toast(`Vị trí này chỉ còn ${l.count}`, "err"); return; }
              const neFull = (r.near_expiry_count || 0) > 0 && r.count === r.near_expiry_count;
              const gsFull = (r.consigned_count || 0) > 0 && r.count === r.consigned_count;
              const shipment_type = document.querySelector(`[data-xk-type="${i}"]`).value;
              XK_CART.push({ product_name: r.product_name, lot_code: r.lot_code, unit_type: r.unit_type,
                            quantity: qty, shipment_type, near_expiry_only: neFull, consigned_only: gsFull,
                            fifo_ok: r.fifo_ok, location_id: l.loc_id, location_label: whLabel(l) });
              renderCart();
              toast(`Đã thêm ${qty} ${unitTypeLabel({ product: r.product_name, unit_type: r.unit_type }).toLowerCase()} từ vị trí ${l.code} vào phiếu`);
            };
          });
        });
      }

      // Mọi lô/loại đơn vị khác đang có tồn "stored" cho CÙNG sản phẩm — dùng để đổi lô ngay
      // trong giỏ (VD người xuất muốn lấy lô mới hơn lô hệ thống gợi ý theo FIFO).
      function lotOptionsFor(productName, unitType) {
        const out = [];
        lots.forEach(g => {
          if (g.product_name !== productName) return;
          const count = g[`${unitType}_count`];
          const unplaced = g[`${unitType}_unplaced`] || 0;
          if (count) out.push({ lot_code: g.lot_code, count, fifo_ok: g[`${unitType}_fifo_ok`], unplaced,
                                sellable: Math.max(0, count - unplaced),
                                locations: g[`${unitType}_locations`] || [] });
        });
        return out;
      }

      function renderCart() {
        $("xk_cart").innerHTML = XK_CART.length ? `<div class="tablewrap"><table>
          <thead><tr><th>Sản phẩm</th><th>Lô</th><th>Vị trí kho</th><th>Loại</th><th>SL</th><th>FIFO</th><th>Lý do (nếu không đúng FIFO)</th><th>Loại xuất</th><th>Bia gửi/Cận date</th><th></th></tr></thead>
          <tbody>${XK_CART.map((c, i) => { const lotOpts = lotOptionsFor(c.product_name, c.unit_type); return `<tr><td>${esc(fpLabel(c.product_name))}</td>
            <td>${lotOpts.length ? `<select data-xk-lot="${i}">${lotOpts.map(o => `<option value="${esc(o.lot_code || "")}" ${o.lot_code === c.lot_code ? "selected" : ""}>${esc(o.lot_code || "(không lô)")} — còn ${o.sellable}${o.fifo_ok ? " · FIFO" : ""}</option>`).join("")}</select>`
              : esc(c.lot_code || "")}</td>
            <td class="muted">${esc(c.location_label || "—")}</td>
            <td>${unitTypeLabel({ product: c.product_name, unit_type: c.unit_type })}</td><td>${c.quantity}</td>
            <td>${c.fifo_ok ? '<span class="badge available">✓ FIFO</span>' : '<span class="badge on_hold">⚠ Không phải lô cũ nhất</span>'}</td>
            <td>${c.fifo_ok ? '<span class="muted">—</span>' : `<input data-xk-reason="${i}" placeholder="Bắt buộc nhập lý do" value="${esc(c.fifo_reason || "")}" style="width:180px;border-color:var(--red)"/>`}</td>
            <td><span class="badge ${c.shipment_type === "promo" ? "planned" : c.shipment_type === "return" ? "on_hold" : "available"}">${shipmentTypeLabel(c.shipment_type)}</span></td>
            <td>${c.consigned_only ? '<span class="badge on_hold">🎁 Bia gửi</span>' : c.near_expiry_only ? '<span class="badge on_hold">🕒 Cận date</span>' : '<span class="muted">—</span>'}</td>
            <td><button class="btn sm sec" data-xk-del="${i}">Xoá</button></td></tr>`; }).join("")}</tbody></table></div>
          <div class="row" style="margin-top:10px;align-items:center">
            <div class="muted">Tổng: <b>${XK_CART.length}</b> dòng</div>
            <button class="btn" id="xk_submit" style="align-self:flex-end;margin-left:auto">Tạo phiếu xuất kho</button>
          </div>`
          : `<div class="muted">Chưa có dòng nào — thêm sản phẩm/lô ở bảng trên.</div>`;
        document.querySelectorAll("[data-xk-del]").forEach(b => b.onclick = () => {
          XK_CART.splice(parseInt(b.dataset.xkDel, 10), 1);
          renderCart();
        });
        document.querySelectorAll("[data-xk-reason]").forEach(inp => inp.oninput = () => {
          XK_CART[parseInt(inp.dataset.xkReason, 10)].fifo_reason = inp.value;
        });
        document.querySelectorAll("[data-xk-lot]").forEach(sel => sel.onchange = () => {
          const idx = parseInt(sel.dataset.xkLot, 10);
          const c = XK_CART[idx];
          const chosen = lotOptionsFor(c.product_name, c.unit_type).find(o => o.lot_code === sel.value);
          c.lot_code = sel.value || null;
          c.fifo_ok = chosen ? chosen.fifo_ok : false;
          if (c.fifo_ok) c.fifo_reason = null;
          // Đổi lô thì bỏ ghim vị trí cũ (vị trí thuộc lô trước, không còn khớp lô mới) — quay
          // lại FIFO tự do trên mọi vị trí của lô mới, như hành vi trước khi có tính năng ghim.
          c.location_id = null;
          c.location_label = chosen ? placedLocationLabel(chosen) : "—";
          if (chosen && c.quantity > chosen.sellable) {
            toast(`Lô ${chosen.lot_code || ""} chỉ có ${chosen.sellable} đã cất vào vị trí kho — đã giảm SL cho khớp`, "err");
            c.quantity = chosen.sellable;
          }
          renderCart();
        });
        if ($("xk_submit")) $("xk_submit").onclick = () => guard(async () => {
          // isWhScopeRestricted() gọi lại tại đây (không dùng biến `whRestricted` khai báo ở
          // block `sec === "xuatkho"` PHÍA TRÊN — đây là 1 block if/else khác, JS block-scope
          // không lộ ra ngoài, dùng biến đó ở đây sẽ ném "not defined").
          if (isWhScopeRestricted() && !$("xk_wh").value) { toast("Vui lòng chọn Kho xuất (tài khoản bị giới hạn kho thành phẩm)", "err"); return; }
          if (!$("xk_shipto").value) { toast("Chọn nơi xuất đến", "err"); return; }
          if (!XK_CART.length) { toast("Chưa có dòng nào trong phiếu", "err"); return; }
          // Dòng nào lấy lô không đúng FIFO (không phải lô cũ nhất) bắt buộc phải giải trình lý
          // do trước khi được phép tạo phiếu — tránh xuất sai FIFO mà không ai biết vì sao.
          const missingReason = XK_CART.find(c => !c.fifo_ok && !(c.fifo_reason || "").trim());
          if (missingReason) {
            toast(`Dòng ${fpLabel(missingReason.product_name)} — lô ${missingReason.lot_code || "(không lô)"} không đúng FIFO: phải nhập lý do trước khi tạo phiếu`, "err");
            return;
          }
          // Mỗi dòng trong giỏ có thể mang 1 Loại xuất riêng (thường/khuyến mại/đổi trả) —
          // giờ TẤT CẢ dòng cùng 1 nơi xuất đến gộp vào ĐÚNG 1 phiếu duy nhất (Loại xuất lưu
          // riêng từng dòng ở backend, xem FinishedGoodsUnit.shipment_line_type), không tách
          // nhiều phiếu theo loại như trước nữa.
          const shipTo = shipTos.find(s => s.supplier_id === $("xk_shipto").value);
          // Lái xe/biển số chọn từ Danh mục lái xe (không gõ tay) — tự điền cả 2 vào phiếu in
          // từ cùng 1 dòng danh mục, tránh gõ sai/lệch giữa tên lái xe và biển số thật.
          const vehicle = vehicles.find(v => v.vehicle_id === $("xk_driver").value);
          // Gộp lý do của các dòng không đúng FIFO vào note của Shipment — note vốn đã có sẵn
          // ở model/schema (Lý do xuất kho) nhưng Xuất kho chưa dùng tới.
          const fifoNotes = XK_CART.filter(c => !c.fifo_ok)
            .map(c => `${fpLabel(c.product_name)} lô ${c.lot_code || "(không lô)"}: ${c.fifo_reason.trim()}`);
          const res = await POST("/wms/shipments", {
            ship_to_id: $("xk_shipto").value,
            warehouse_id: $("xk_wh").value || null,
            lines: XK_CART.map(c => ({ product_name: c.product_name, lot_code: c.lot_code,
                                       unit_type: c.unit_type, quantity: c.quantity,
                                       near_expiry_only: c.near_expiry_only || false,
                                       consigned_only: c.consigned_only || false,
                                       shipment_type: c.shipment_type || "normal",
                                       location_id: c.location_id || undefined })),
            note: fifoNotes.length ? `Xuất không đúng FIFO — ${fifoNotes.join("; ")}` : null,
            recipient_name: shipTo ? shipTo.name : null,
            driver_name: vehicle ? (vehicle.driver_name || vehicle.driver_short_name) : null,
            vehicle_plate: vehicle ? vehicle.plate : null,
            vehicle_id: vehicle ? vehicle.vehicle_id : null });
          XK_CART = [];
          renderCart();
          toast(`Đã tạo phiếu xuất kho ${res.shipment_code}${!res.fifo_ok ? " (⚠ không đúng FIFO)" : ""}`);
          render("wms");
        });
      }

      renderLots();
      renderCart();
      wireSelectSearch("xk_shipto", "xk_shipto_q");
      wireSelectSearch("xk_driver", "xk_driver_q");
      $("xk_lotfilter").onchange = renderLots;
      $("xk_search").oninput = renderLots;
      $("xk_wh").onchange = () => { XK_CART = []; renderLots(); renderCart(); };
      GET("/wms/shipments").then(ships => {
        const isAdminXk = CURRENT_USER && CURRENT_USER.role === "admin";
        const canConfirmShip = _hasPerm("wms.confirm_shipment");
        // Sửa thông tin đầu phiếu (người nhận/lái xe/biển số/địa điểm/lý do) chỉ khi CHƯA duyệt —
        // sau khi Trưởng bộ phận kho "Duyệt" (confirmed_by), phiếu coi như chốt, không sửa được nữa.
        const canEditShip = _hasPerm("warehouse.issue");
        $("xk_history").innerHTML = ships.length ? `<div class="tablewrap"><table id="t_xk_history">
          <thead><tr><th>Mã phiếu</th><th>Từ kho</th><th>Nơi xuất đến</th><th>Thời gian</th><th>Người xuất</th><th>FIFO</th><th>Biển số xe</th><th>Km</th><th>Lít xăng</th><th>Chi tiết</th><th>Duyệt</th><th></th></tr></thead>
          <tbody>${ships.map((s, i) => { const undone = s.unit_count === 0;
            const confirmCell = s.confirmed_by ? `<span class="badge available">✓ ${esc(s.confirmed_by)}</span><div class="muted" style="font-size:11px">${fmt(s.confirmed_at)}</div>` :
              canConfirmShip && !undone ? `<button class="btn sm sec" data-confirmship="${i}">Duyệt</button>` :
              '<span class="muted">Chưa duyệt</span>';
            const canUndoShip = !undone && (!s.confirmed_by || isAdminXk);
            const tripEditable = s.confirmed_by && !undone;
            return `<tr><td><code class="k">${esc(s.shipment_code)}</code></td>
            <td class="muted">${esc(s.from_location || "—")}</td>
            <td>${esc(s.ship_to_name || s.ship_to_code || "—")}</td><td class="muted">${fmt(s.created_at)}</td>
            <td class="muted">${esc(s.created_by || "—")}</td>
            <td>${undone ? '<span class="badge obsolete">Đã hoàn tác</span>' : s.fifo_ok ? '<span class="badge available">✓ Đúng FIFO</span>' :
              `<span class="badge on_hold">⚠ Không đúng FIFO</span>${s.note ? `<div class="muted" style="font-size:11px;max-width:220px;white-space:normal">${esc(s.note)}</div>` : ""}`}</td>
            <td class="muted">${esc(s.vehicle_plate || "—")}</td>
            <td>${tripEditable ? `<input type="number" min="0" step="0.1" value="${s.km != null ? s.km : ""}" style="width:70px" data-xk-km="${i}"/>` : '<span class="muted">—</span>'}</td>
            <td>${tripEditable ? `<input type="number" min="0" step="0.1" value="${s.fuel_liters != null ? s.fuel_liters : ""}" style="width:70px" data-xk-fuel="${i}"/> <button class="btn sm sec" data-savetrip="${i}">Lưu</button>` : '<span class="muted">—</span>'}</td>
            <td class="muted">${s.lines.map(l => `${esc(fpLabel(l.product))} ${esc(l.lot_code || "")}: ${l.count} ${unitTypeLabel(l).toLowerCase()}`).join("; ")}</td>
            <td style="white-space:nowrap">${confirmCell}</td>
            <td style="white-space:nowrap"><button class="btn sm sec" data-viewship="${i}">Xem</button>
              ${s.confirmed_by ? `<button class="btn sm sec" data-printship="${i}">🖨️ In phiếu</button>` : ""}
              ${canEditShip && !s.confirmed_by ? `<button class="btn sm sec" data-editship="${i}">Sửa</button>` : ""}
              ${canUndoShip ? `<button class="btn sm sec" data-undoship="${i}">Hoàn tác</button>` : ""}</td></tr>`; }).join("")}</tbody></table></div>`
          : `<div class="muted">Chưa có phiếu xuất kho nào.</div>`;
        wireSearch(); wirePaginate("t_xk_history", 10);
        document.querySelectorAll("[data-savetrip]").forEach(b => b.onclick = () => guard(async () => {
          const i = parseInt(b.dataset.savetrip, 10);
          const s = ships[i];
          const kmVal = document.querySelector(`[data-xk-km="${i}"]`).value;
          const fuelVal = document.querySelector(`[data-xk-fuel="${i}"]`).value;
          await POST(`/wms/shipments/${s.shipment_id}/trip`, {
            km: kmVal === "" ? null : parseFloat(kmVal),
            fuel_liters: fuelVal === "" ? null : parseFloat(fuelVal) });
          toast("Đã lưu km/lít xăng"); render("wms");
        }));
        document.querySelectorAll("[data-printship]").forEach(b => b.onclick = () => guard(() =>
          printShipmentHandoverSlip(ships[parseInt(b.dataset.printship, 10)])));
        document.querySelectorAll("[data-editship]").forEach(b => b.onclick = () => {
          const s = ships[parseInt(b.dataset.editship, 10)];
          modal(`<h3>Sửa thông tin phiếu — ${esc(s.shipment_code)}</h3>
            <div class="row"><div class="field" style="flex:1"><label>Người nhận hàng</label><input id="es_recipient" value="${esc(s.recipient_name || "")}"/></div>
              <div class="field" style="flex:1"><label>Địa chỉ (bộ phận)</label><input id="es_dept" value="${esc(s.recipient_dept || "")}"/></div></div>
            <div class="row"><div class="field" style="flex:1"><label>Lái xe</label><input id="es_driver" value="${esc(s.driver_name || "")}"/></div>
              <div class="field" style="flex:1"><label>Biển số xe</label><input id="es_plate" value="${esc(s.vehicle_plate || "")}"/></div></div>
            <div class="row"><div class="field" style="flex:1"><label>Xuất tại kho (ngăn lô)</label><input id="es_from" value="${esc(s.from_location || "")}"/></div>
              <div class="field" style="flex:1"><label>Địa điểm giao</label><input id="es_place" value="${esc(s.delivery_place || "")}"/></div></div>
            <div class="field"><label>Lý do xuất kho</label><input id="es_note" value="${esc(s.note || "")}"/></div>
            <button class="btn" id="es_save">Lưu</button>`);
          $("es_save").onclick = () => guard(async () => {
            await PUT(`/wms/shipments/${s.shipment_id}`, {
              recipient_name: $("es_recipient").value, recipient_dept: $("es_dept").value,
              driver_name: $("es_driver").value, vehicle_plate: $("es_plate").value,
              from_location: $("es_from").value, delivery_place: $("es_place").value,
              note: $("es_note").value });
            toast("Đã lưu"); closeModal(); render("wms");
          });
        });
        document.querySelectorAll("[data-viewship]").forEach(b => b.onclick = () => {
          const s = ships[parseInt(b.dataset.viewship, 10)];
          modal(`<h3>Sản phẩm trong phiếu — ${esc(s.shipment_code)}</h3>
            <div class="muted" style="margin-bottom:6px">Xuất từ kho: <b>${esc(s.from_location || "—")}</b></div>
            <div class="tablewrap"><table>
              <thead><tr><th>Sản phẩm</th><th>Lô</th><th>Loại</th><th>SL</th><th>Loại xuất</th><th>Bia gửi/Cận date</th></tr></thead>
              <tbody>${s.lines.map(l => `<tr><td>${esc(fpLabel(l.product))}</td><td>${esc(l.lot_code || "—")}</td>
                <td>${unitTypeLabel(l)}</td><td>${l.count}</td>
                <td><span class="badge ${l.type === "promo" ? "planned" : l.type === "return" ? "on_hold" : "available"}">${shipmentTypeLabel(l.type)}</span></td>
                <td>${l.consigned ? '<span class="badge on_hold">🎁 Bia gửi</span>' : l.near_expiry ? '<span class="badge on_hold">🕒 Cận date</span>' : '<span class="muted">—</span>'}</td></tr>`).join("") ||
                '<tr><td colspan=6 class="muted">Không còn dòng nào (đã hoàn tác).</td></tr>'}</tbody>
            </table></div>`);
        });
        document.querySelectorAll("[data-confirmship]").forEach(b => b.onclick = () => guard(async () => {
          const s = ships[parseInt(b.dataset.confirmship, 10)];
          if (!confirm(`Duyệt phiếu xuất kho ${s.shipment_code}? Sau khi duyệt, chỉ ADMIN mới "Hoàn tác" được nữa.`)) return;
          await POST(`/wms/shipments/${s.shipment_id}/confirm`, {});
          toast("Đã duyệt phiếu xuất kho"); render("wms");
        }));
        document.querySelectorAll("[data-undoship]").forEach(b => b.onclick = () => guard(async () => {
          const s = ships[parseInt(b.dataset.undoship, 10)];
          if (!confirm(`Hoàn tác phiếu xuất kho ${s.shipment_code}? Toàn bộ vỉ/keg/lon trong phiếu sẽ trả lại tồn kho (chưa xếp vị trí).`)) return;
          const res = await POST(`/wms/shipments/${s.shipment_id}/undo`, {});
          toast(`Đã hoàn tác — khôi phục ${res.restored} đơn vị`); render("wms");
        }));
      }).catch(() => { $("xk_history").innerHTML = `<div class="muted">Không tải được lịch sử.</div>`; });
    } else if (sec === "dieuchuyen") {
      // Mirror y hệt sec === "xuatkho" ở trên (picker/cart/lịch sử) — chỉ khác đích là 1
      // WmsLocation (không phải nhà phân phối) và KHÔNG có Loại xuất/Bia gửi/Cận date (không có
      // ý nghĩa cho luồng nội bộ — 2 cờ is_near_expiry/is_consigned trên đơn vị vẫn giữ nguyên
      // qua điều chuyển, không cần lọc/đánh dấu riêng ở đây).
      const dcLots = await GET("/wms/units/by-lot");

      // Mỗi dòng picker giờ ứng với ĐÚNG 1 (sản phẩm, lô, loại đơn vị, VỊ TRÍ KHO) — không gộp
      // nhiều vị trí vào 1 dòng như trước (locationCell) nữa, vì FIFO điều chuyển phải lấy đúng
      // đơn vị đang ở vị trí NGUỒN hiển thị trên dòng đó (xem location_id truyền xuống
      // create_transfer), không lẫn qua vị trí khác cùng lô — 1 lô nằm ở 2 kho phải hiện 2 dòng
      // riêng, giữ nguyên lot_code ở cả hai để truy xuất nguồn gốc không đứt. Khi đã chọn vị
      // trí đích, ẨN LUÔN các dòng đang ở đúng vị trí đó (điều chuyển về chính nó là vô nghĩa).
      function filteredDcLotRows() {
        const filter = $("dc_lotfilter").value;
        const search = $("dc_search").value.trim().toLowerCase();
        const destId = $("dc_to").value;
        const rows = [];
        dcLots.forEach(g => {
          if (filter === "has_lon" && !g.has_lon) return;
          if (filter === "no_lon" && g.has_lon) return;
          if (search && !`${g.product_name || ""} ${g.lot_code || ""}`.toLowerCase().includes(search)) return;
          (g.unit_types || ["vi", "keg", "lon"]).forEach(t => {
            (g[`${t}_locations`] || []).forEach(loc => {
              if (!loc.count) return;
              if (destId && loc.loc_id === destId) return;
              if (!isWarehouseAllowed(loc.warehouse_code)) return;
              rows.push({ product_name: g.product_name, lot_code: g.lot_code, unit_type: t,
                         count: loc.count, total_count: g[`${t}_count`] || 0,
                         loc_id: loc.loc_id, loc_code: loc.code, loc_name: loc.name, loc_zone: loc.zone,
                         loc_warehouse_name: loc.warehouse_name,
                         fifo_ok: g[`${t}_fifo_ok`], oldest_at: g[`${t}_oldest_at`], bottle_codes: g.bottle_codes,
                         near_expiry_count: g[`${t}_near_expiry_count`] || 0,
                         consigned_count: g[`${t}_consigned_count`] || 0,
                         consigned_vehicle_plate: g.consigned_vehicle_plate });
            });
          });
        });
        // Cùng thứ tự ưu tiên như Xuất kho: bia gửi trước, rồi cận date, rồi tên SP, rồi FIFO cũ
        // nhất — để người điều chuyển thấy ngay dòng nào nên xử lý trước (mirror filteredLotRows).
        rows.sort((a, b) => (((b.consigned_count || 0) > 0 ? 1 : 0) - ((a.consigned_count || 0) > 0 ? 1 : 0)) ||
          (((b.near_expiry_count || 0) > 0 ? 1 : 0) - ((a.near_expiry_count || 0) > 0 ? 1 : 0)) ||
          (a.product_name || "").localeCompare(b.product_name || "") ||
          new Date(a.oldest_at || 0) - new Date(b.oldest_at || 0));
        return rows;
      }

      function renderDcLots() {
        const rows = filteredDcLotRows();
        const destChosen = !!$("dc_to").value;
        $("dc_lots").innerHTML = rows.length ? `<div class="tablewrap" style="margin-top:10px"><table id="t_dc_lots">
          <thead><tr><th>Sản phẩm</th><th>Lô</th><th>Mã chiết</th><th>Loại</th><th>Tồn</th><th>Vị trí kho</th><th>FIFO</th><th>Bia gửi/Cận date</th><th>SL cần chuyển</th><th></th></tr></thead>
          <tbody>${rows.map((r, i) => { const neAvailable = (r.near_expiry_count || 0) > 0;
            const neFull = neAvailable && r.total_count === r.near_expiry_count;
            const gsAvailable = (r.consigned_count || 0) > 0;
            const gsFull = gsAvailable && r.total_count === r.consigned_count;
            return `<tr${gsFull || neFull ? ' class="row-cyan"' : ""}>
            <td>${esc(fpLabel(r.product_name))}</td><td>${esc(r.lot_code || "")}</td>
            <td class="muted">${esc((r.bottle_codes || []).join(", ") || "—")}</td>
            <td>${unitTypeLabel({ product: r.product_name, unit_type: r.unit_type })}</td><td>${r.count}</td>
            <td class="muted">${r.loc_warehouse_name ? `[${esc(r.loc_warehouse_name)}] ` : ""}${esc(r.loc_name ? `${r.loc_code} - ${r.loc_name}` : (r.loc_code || "—"))}${r.loc_zone ? ` - Khu ${esc(r.loc_zone)}` : ""}</td>
            <td>${r.fifo_ok ? '<span class="badge available">✓ FIFO</span>' : '<span class="badge on_hold">⚠ Không phải lô cũ nhất</span>'}</td>
            <td>${gsFull ? '<span class="badge on_hold">🎁 Bia gửi</span>' : neFull ? '<span class="badge on_hold">🕒 Cận date</span>' :
              gsAvailable ? '<span class="muted">🎁 một phần</span>' : neAvailable ? '<span class="muted">🕒 một phần</span>' : '<span class="muted">—</span>'}</td>
            <td><input type="number" min="1" max="${r.count}" value="${r.count}" style="width:80px" data-dc-qty="${i}"/></td>
            <td><button class="btn sm" data-dc-add="${i}">+ Thêm</button></td></tr>`; }).join("")}</tbody></table></div>`
          : `<div class="muted" style="margin-top:10px">${destChosen ? "Không còn lô nào ở vị trí khác vị trí đích khớp bộ lọc." : "Không còn lô nào tồn kho khớp bộ lọc."}</div>`;
        wirePaginate("t_dc_lots", 10);
        rows.forEach((r, i) => {
          const btn = document.querySelector(`[data-dc-add="${i}"]`);
          if (!btn) return;
          btn.onclick = () => {
            const qty = parseInt(document.querySelector(`[data-dc-qty="${i}"]`).value, 10) || 0;
            if (qty <= 0) { toast("Nhập số lượng > 0", "err"); return; }
            if (qty > r.count) { toast(`Chỉ có ${r.count} tại vị trí ${r.loc_code}`, "err"); return; }
            DC_CART.push({ product_name: r.product_name, lot_code: r.lot_code, unit_type: r.unit_type,
                          quantity: qty, fifo_ok: r.fifo_ok, location_id: r.loc_id,
                          location_label: r.loc_name ? `${r.loc_code} - ${r.loc_name}` : r.loc_code });
            renderDcCart();
            toast(`Đã thêm ${qty} ${unitTypeLabel({ product: r.product_name, unit_type: r.unit_type }).toLowerCase()} vào phiếu điều chuyển`);
          };
        });
      }

      // Cùng nguyên tắc split-theo-vị-trí như filteredDcLotRows — đổi lô trong giỏ cũng phải
      // chọn đúng 1 vị trí nguồn, không gộp.
      function dcLotOptionsFor(productName, unitType) {
        const destId = $("dc_to").value;
        const out = [];
        dcLots.forEach(g => {
          if (g.product_name !== productName) return;
          (g[`${unitType}_locations`] || []).forEach(loc => {
            if (!loc.count) return;
            if (destId && loc.loc_id === destId) return;
            out.push({ lot_code: g.lot_code, count: loc.count, fifo_ok: g[`${unitType}_fifo_ok`],
                      loc_id: loc.loc_id, loc_code: loc.code, loc_name: loc.name });
          });
        });
        return out;
      }

      function renderDcCart() {
        $("dc_cart").innerHTML = DC_CART.length ? `<div class="tablewrap"><table>
          <thead><tr><th>Sản phẩm</th><th>Lô</th><th>Vị trí kho</th><th>Loại</th><th>SL</th><th>FIFO</th><th>Lý do (tuỳ chọn)</th><th></th></tr></thead>
          <tbody>${DC_CART.map((c, i) => { const lotOpts = dcLotOptionsFor(c.product_name, c.unit_type); return `<tr><td>${esc(fpLabel(c.product_name))}</td>
            <td>${lotOpts.length ? `<select data-dc-lot="${i}">${lotOpts.map(o => `<option value="${esc(o.lot_code || "")}|${esc(o.loc_id || "")}" ${o.lot_code === c.lot_code && o.loc_id === c.location_id ? "selected" : ""}>${esc(o.lot_code || "(không lô)")} (${esc(o.loc_code || "?")}) — còn ${o.count}${o.fifo_ok ? " · FIFO" : ""}</option>`).join("")}</select>`
              : esc(c.lot_code || "")}</td>
            <td class="muted">${esc(c.location_label || "—")}</td>
            <td>${unitTypeLabel({ product: c.product_name, unit_type: c.unit_type })}</td><td>${c.quantity}</td>
            <td>${c.fifo_ok ? '<span class="badge available">✓ FIFO</span>' : '<span class="badge on_hold">⚠ Không phải lô cũ nhất</span>'}</td>
            <td>${c.fifo_ok ? '<span class="muted">—</span>' : `<input data-dc-reason="${i}" placeholder="(tuỳ chọn)" value="${esc(c.fifo_reason || "")}" style="width:180px"/>`}</td>
            <td><button class="btn sm sec" data-dc-del="${i}">Xoá</button></td></tr>`; }).join("")}</tbody></table></div>
          <div class="row" style="margin-top:10px;align-items:center">
            <div class="muted">Tổng: <b>${DC_CART.length}</b> dòng</div>
            <button class="btn" id="dc_submit" style="align-self:flex-end;margin-left:auto">Tạo phiếu điều chuyển</button>
          </div>`
          : `<div class="muted">Chưa có dòng nào — thêm sản phẩm/lô ở bảng trên.</div>`;
        document.querySelectorAll("[data-dc-del]").forEach(b => b.onclick = () => {
          DC_CART.splice(parseInt(b.dataset.dcDel, 10), 1);
          renderDcCart();
        });
        document.querySelectorAll("[data-dc-reason]").forEach(inp => inp.oninput = () => {
          DC_CART[parseInt(inp.dataset.dcReason, 10)].fifo_reason = inp.value;
        });
        document.querySelectorAll("[data-dc-lot]").forEach(sel => sel.onchange = () => {
          const idx = parseInt(sel.dataset.dcLot, 10);
          const c = DC_CART[idx];
          const [lotCode, locId] = sel.value.split("|");
          const chosen = dcLotOptionsFor(c.product_name, c.unit_type).find(o => (o.lot_code || "") === lotCode && (o.loc_id || "") === locId);
          c.lot_code = lotCode || null;
          c.location_id = locId || null;
          c.fifo_ok = chosen ? chosen.fifo_ok : false;
          if (c.fifo_ok) c.fifo_reason = null;
          c.location_label = chosen ? (chosen.loc_name ? `${chosen.loc_code} - ${chosen.loc_name}` : chosen.loc_code) : "—";
          if (chosen && c.quantity > chosen.count) {
            toast(`Lô ${chosen.lot_code || ""} tại ${chosen.loc_code} chỉ còn ${chosen.count} — đã giảm SL cho khớp`, "err");
            c.quantity = chosen.count;
          }
          renderDcCart();
        });
        if ($("dc_submit")) $("dc_submit").onclick = () => guard(async () => {
          if (!DC_CART.length) { toast("Chưa có dòng nào trong phiếu", "err"); return; }
          if ($("dc_to").value && DC_CART.some(c => c.location_id === $("dc_to").value)) {
            toast("Có dòng đang ở đúng vị trí đích — không thể điều chuyển, hãy xoá dòng đó hoặc đổi vị trí đích", "err");
            return;
          }
          const vehicleDc = vehicles.find(v => v.vehicle_id === $("dc_driver").value);
          const fifoNotesDc = DC_CART.filter(c => !c.fifo_ok && (c.fifo_reason || "").trim())
            .map(c => `${fpLabel(c.product_name)} lô ${c.lot_code || "(không lô)"}: ${c.fifo_reason.trim()}`);
          const res = await POST("/wms/transfers", {
            to_location_id: $("dc_to").value || null,
            lines: DC_CART.map(c => ({ product_name: c.product_name, lot_code: c.lot_code,
                                       unit_type: c.unit_type, quantity: c.quantity, location_id: c.location_id })),
            note: fifoNotesDc.length ? `Điều chuyển không đúng FIFO — ${fifoNotesDc.join("; ")}` : null,
            driver_name: vehicleDc ? (vehicleDc.driver_name || vehicleDc.driver_short_name) : null,
            vehicle_plate: vehicleDc ? vehicleDc.plate : null,
            vehicle_id: vehicleDc ? vehicleDc.vehicle_id : null });
          DC_CART = [];
          renderDcCart();
          toast(`Đã tạo phiếu điều chuyển ${res.transfer_code}${!res.fifo_ok ? " (⚠ không đúng FIFO)" : ""}`);
          render("wms");
        });
      }

      renderDcLots();
      renderDcCart();
      wireSelectSearch("dc_driver", "dc_driver_q");
      $("dc_to").onchange = renderDcLots;
      $("dc_lotfilter").onchange = renderDcLots;
      $("dc_search").oninput = renderDcLots;
      GET("/wms/transfers").then(transfers => {
        const isAdminDc = CURRENT_USER && CURRENT_USER.role === "admin";
        const canConfirmDc = _hasPerm("wms.confirm_shipment");
        const canEditDc = _hasPerm("warehouse.issue");
        $("dc_history").innerHTML = transfers.length ? `<div class="tablewrap"><table id="t_dc_history">
          <thead><tr><th>Mã phiếu</th><th>Từ kho</th><th>Đến vị trí</th><th>Thời gian</th><th>Người tạo</th><th>FIFO</th><th>Biển số xe</th><th>Km</th><th>Lít xăng</th><th>Chi tiết</th><th>Duyệt</th><th></th></tr></thead>
          <tbody>${transfers.map((t, i) => { const undone = t.unit_count === 0;
            const confirmCellDc = t.confirmed_by ? `<span class="badge available">✓ ${esc(t.confirmed_by)}</span><div class="muted" style="font-size:11px">${fmt(t.confirmed_at)}</div>` :
              canConfirmDc && !undone ? `<button class="btn sm sec" data-confirmdc="${i}">Duyệt</button>` :
              '<span class="muted">Chưa duyệt</span>';
            const canUndoDc = !undone && (!t.confirmed_by || isAdminDc);
            const tripEditableDc = t.confirmed_by && !undone;
            return `<tr><td><code class="k">${esc(t.transfer_code)}</code></td>
            <td class="muted">${esc(t.from_location || "—")}</td>
            <td>${esc(t.to_location_name || t.to_location_code || "—")}</td><td class="muted">${fmt(t.created_at)}</td>
            <td class="muted">${esc(t.created_by || "—")}</td>
            <td>${undone ? '<span class="badge obsolete">Đã hoàn tác</span>' : t.fifo_ok ? '<span class="badge available">✓ Đúng FIFO</span>' :
              `<span class="badge on_hold">⚠ Không đúng FIFO</span>${t.note ? `<div class="muted" style="font-size:11px;max-width:220px;white-space:normal">${esc(t.note)}</div>` : ""}`}</td>
            <td class="muted">${esc(t.vehicle_plate || "—")}</td>
            <td>${tripEditableDc ? `<input type="number" min="0" step="0.1" value="${t.km != null ? t.km : ""}" style="width:70px" data-dc-km="${i}"/>` : '<span class="muted">—</span>'}</td>
            <td>${tripEditableDc ? `<input type="number" min="0" step="0.1" value="${t.fuel_liters != null ? t.fuel_liters : ""}" style="width:70px" data-dc-fuel="${i}"/> <button class="btn sm sec" data-savedctrip="${i}">Lưu</button>` : '<span class="muted">—</span>'}</td>
            <td class="muted">${t.lines.map(l => `${esc(fpLabel(l.product))} ${esc(l.lot_code || "")}: ${l.count} ${unitTypeLabel(l).toLowerCase()}`).join("; ")}</td>
            <td style="white-space:nowrap">${confirmCellDc}</td>
            <td style="white-space:nowrap"><button class="btn sm sec" data-viewdc="${i}">Xem</button>
              ${t.confirmed_by ? `<button class="btn sm sec" data-printdc="${i}">🖨️ In phiếu</button>` : ""}
              ${canEditDc && !t.confirmed_by ? `<button class="btn sm sec" data-editdc="${i}">Sửa</button>` : ""}
              ${canUndoDc ? `<button class="btn sm sec" data-undodc="${i}">Hoàn tác</button>` : ""}</td></tr>`; }).join("")}</tbody></table></div>`
          : `<div class="muted">Chưa có phiếu điều chuyển nào.</div>`;
        wireSearch(); wirePaginate("t_dc_history", 10);
        document.querySelectorAll("[data-savedctrip]").forEach(b => b.onclick = () => guard(async () => {
          const i = parseInt(b.dataset.savedctrip, 10);
          const t = transfers[i];
          const kmVal = document.querySelector(`[data-dc-km="${i}"]`).value;
          const fuelVal = document.querySelector(`[data-dc-fuel="${i}"]`).value;
          await POST(`/wms/transfers/${t.transfer_id}/trip`, {
            km: kmVal === "" ? null : parseFloat(kmVal),
            fuel_liters: fuelVal === "" ? null : parseFloat(fuelVal) });
          toast("Đã lưu km/lít xăng"); render("wms");
        }));
        document.querySelectorAll("[data-printdc]").forEach(b => b.onclick = () => guard(() =>
          printTransferHandoverSlip(transfers[parseInt(b.dataset.printdc, 10)])));
        document.querySelectorAll("[data-editdc]").forEach(b => b.onclick = () => {
          const t = transfers[parseInt(b.dataset.editdc, 10)];
          modal(`<h3>Sửa thông tin phiếu — ${esc(t.transfer_code)}</h3>
            <div class="row"><div class="field" style="flex:1"><label>Lái xe</label><input id="edc_driver" value="${esc(t.driver_name || "")}"/></div>
              <div class="field" style="flex:1"><label>Biển số xe</label><input id="edc_plate" value="${esc(t.vehicle_plate || "")}"/></div></div>
            <div class="field"><label>Ghi chú</label><input id="edc_note" value="${esc(t.note || "")}"/></div>
            <button class="btn" id="edc_save">Lưu</button>`);
          $("edc_save").onclick = () => guard(async () => {
            await PUT(`/wms/transfers/${t.transfer_id}`, {
              driver_name: $("edc_driver").value, vehicle_plate: $("edc_plate").value,
              note: $("edc_note").value });
            toast("Đã lưu"); closeModal(); render("wms");
          });
        });
        document.querySelectorAll("[data-viewdc]").forEach(b => b.onclick = () => {
          const t = transfers[parseInt(b.dataset.viewdc, 10)];
          modal(`<h3>Sản phẩm trong phiếu — ${esc(t.transfer_code)}</h3>
            <div class="muted" style="margin-bottom:6px">Điều chuyển từ kho: <b>${esc(t.from_location || "—")}</b></div>
            <div class="tablewrap"><table>
              <thead><tr><th>Sản phẩm</th><th>Lô</th><th>Loại</th><th>SL</th></tr></thead>
              <tbody>${t.lines.map(l => `<tr><td>${esc(fpLabel(l.product))}</td><td>${esc(l.lot_code || "—")}</td>
                <td>${unitTypeLabel(l)}</td><td>${l.count}</td></tr>`).join("") ||
                '<tr><td colspan=4 class="muted">Không còn dòng nào (đã hoàn tác).</td></tr>'}</tbody>
            </table></div>`);
        });
        document.querySelectorAll("[data-confirmdc]").forEach(b => b.onclick = () => guard(async () => {
          const t = transfers[parseInt(b.dataset.confirmdc, 10)];
          if (!confirm(`Duyệt phiếu điều chuyển ${t.transfer_code}? Sau khi duyệt, chỉ ADMIN mới "Hoàn tác" được nữa.`)) return;
          await POST(`/wms/transfers/${t.transfer_id}/confirm`, {});
          toast("Đã duyệt phiếu điều chuyển"); render("wms");
        }));
        document.querySelectorAll("[data-undodc]").forEach(b => b.onclick = () => guard(async () => {
          const t = transfers[parseInt(b.dataset.undodc, 10)];
          if (!confirm(`Hoàn tác phiếu điều chuyển ${t.transfer_code}? Các vỉ/keg/lon trong phiếu sẽ trả về đúng vị trí trước khi chuyển.`)) return;
          const res = await POST(`/wms/transfers/${t.transfer_id}/undo`, {});
          toast(`Đã hoàn tác — khôi phục ${res.restored} đơn vị${res.skipped ? ` (bỏ qua ${res.skipped} đơn vị đã bị thao tác khác thay đổi)` : ""}`); render("wms");
        }));
      }).catch(() => { $("dc_history").innerHTML = `<div class="muted">Không tải được lịch sử.</div>`; });
    } else if (sec === "capvao") {
      const lotSummariesCv = await GET("/wms/units/by-lot");
      const cvRows = [];
      lotSummariesCv.forEach(g => {
        (g.unit_types || ["vi", "keg", "lon"]).forEach(t => {
          if (g[`${t}_unplaced`] > 0) cvRows.push({
            product: g.product_name, lot_code: g.lot_code, unit_type: t, unplaced: g[`${t}_unplaced`],
            bottle_date: g.bottle_date, lines: g.lines || [],
          });
        });
      });
      $("cv_pick").innerHTML = cvRows.length ? `
        <div class="tablewrap" style="margin-top:6px"><table id="t_cv_pick">
        <thead><tr><th></th><th>SP</th><th>Lô</th><th>Loại</th><th>Thời gian chiết</th><th>Dây chuyền</th><th>Chưa cất</th><th>SL cần cất</th></tr></thead>
        <tbody>${cvRows.map((g, i) => `<tr data-cvgroup="${i}">
          <td><input class="cv_pick" type="checkbox"/></td>
          <td>${esc(fpLabel(g.product))}</td><td>${esc(g.lot_code || "")}</td>
          <td>${unitTypeLabel(g)}</td>
          <td class="muted">${g.bottle_date ? fmt(g.bottle_date) : "—"}</td>
          <td class="muted">${esc(g.lines.join(", ") || "—")}</td>
          <td>${g.unplaced}</td>
          <td><input class="cv_qty" type="number" min="1" max="${g.unplaced}" value="${g.unplaced}" style="width:80px"/></td></tr>`).join("")}</tbody></table></div>
        <div class="row" style="margin-top:10px"><button class="btn" id="cv_submit">Cất</button></div>`
        : `<div class="muted">Không còn vỉ/keg/lon nào chưa cất vị trí.</div>`;
      wirePaginate("t_cv_pick", 10);
      if ($("cv_submit")) {
        $("cv_submit").onclick = () => guard(async () => {
          const toId = $("cv_to").value;
          if (!toId) { toast("Chọn vị trí đích", "err"); return; }
          const picked = Array.from(document.querySelectorAll("[data-cvgroup]"))
            .filter(tr => tr.querySelector(".cv_pick").checked)
            .map(tr => ({ g: cvRows[parseInt(tr.dataset.cvgroup, 10)], qty: parseInt(tr.querySelector(".cv_qty").value, 10) || 0 }));
          if (!picked.length) { toast("Chọn ít nhất 1 dòng để cất", "err"); return; }
          for (const { g, qty } of picked) {
            if (qty <= 0 || qty > g.unplaced) throw new Error(`Số lượng cất của lô "${g.lot_code || g.product}" không hợp lệ (tối đa ${g.unplaced}).`);
          }
          for (const { g, qty } of picked) {
            await POST("/wms/units/relocate-batch", {
              product_name: g.product, lot_code: g.lot_code || null, unit_type: g.unit_type,
              from_loc_id: null, to_loc_id: toId, count: qty,
            });
          }
          const total = picked.reduce((s, x) => s + x.qty, 0);
          toast(`Đã cất ${total} đơn vị`); render("wms");
        });
      }
      if ($("cvm_from")) {
        const locById = Object.fromEntries(locs.map(l => [l.loc_id, l]));
        $("cvm_from").onchange = () => guard(async () => {
          const fromId = $("cvm_from").value;
          if (!fromId) { $("cvm_pick").innerHTML = `<div class="muted">Chọn vị trí nguồn để xem tồn kho ở đó.</div>`; return; }
          const fromLoc = locById[fromId];
          const rows = (await GET(`/wms/units/by-location?loc_id=${fromId}`))
            .map(r => ({ product: r.product_name, lot_code: r.lot_code, unit_type: r.unit_type, count: r.count }))
            .filter(r => r.count > 0);
          const destOpt = locs.filter(l => l.loc_id !== fromId && l.warehouse_id === fromLoc.warehouse_id)
            .map(l => `<option value="${esc(l.loc_id)}">${whLabel(l)} (${l.used}/${l.capacity})</option>`).join("");
          $("cvm_pick").innerHTML = rows.length ? `
            <div class="row"><div class="field"><label>Vị trí đích (cùng kho ${esc(fromLoc.warehouse_name || "")})</label>
              <select id="cvm_to"><option value="">(chọn vị trí đích)</option>${destOpt}</select></div></div>
            <div class="tablewrap" style="margin-top:6px"><table id="t_cvm_pick">
            <thead><tr><th></th><th>SP</th><th>Lô</th><th>Loại</th><th>Đang có</th><th>SL cần chuyển</th></tr></thead>
            <tbody>${rows.map((g, i) => `<tr data-cvmrow="${i}">
              <td><input class="cvm_pick" type="checkbox"/></td>
              <td>${esc(fpLabel(g.product))}</td><td>${esc(g.lot_code || "")}</td>
              <td>${unitTypeLabel(g)}</td>
              <td>${g.count}</td>
              <td><input class="cvm_qty" type="number" min="0.01" step="any" max="${g.count}" value="${g.count}" style="width:80px"/></td></tr>`).join("")}</tbody></table></div>
            <div class="row" style="margin-top:10px"><button class="btn" id="cvm_submit">Chuyển</button></div>`
            : `<div class="muted">Vị trí này không còn tồn kho nào.</div>`;
          wirePaginate("t_cvm_pick", 10);
          if ($("cvm_submit")) {
            $("cvm_submit").onclick = () => guard(async () => {
              const toId = $("cvm_to").value;
              if (!toId) { toast("Chọn vị trí đích", "err"); return; }
              const picked = Array.from(document.querySelectorAll("[data-cvmrow]"))
                .filter(tr => tr.querySelector(".cvm_pick").checked)
                .map(tr => ({ g: rows[parseInt(tr.dataset.cvmrow, 10)], qty: parseFloat(tr.querySelector(".cvm_qty").value) || 0 }));
              if (!picked.length) { toast("Chọn ít nhất 1 dòng để chuyển", "err"); return; }
              for (const { g, qty } of picked) {
                if (qty <= 0 || qty > g.count + 1e-9) throw new Error(`Số lượng chuyển của lô "${g.lot_code || g.product}" không hợp lệ (tối đa ${g.count}).`);
              }
              for (const { g, qty } of picked) {
                await POST("/wms/units/relocate-batch", {
                  product_name: g.product, lot_code: g.lot_code || null, unit_type: g.unit_type,
                  from_loc_id: fromId, to_loc_id: toId, count: qty,
                });
              }
              const total = picked.reduce((s, x) => s + x.qty, 0);
              toast(`Đã chuyển ${total} đơn vị`); render("wms");
            });
          }
        });
      }
    } else if (sec === "tudo") {
      const isAdminTudo = CURRENT_USER && CURRENT_USER.role === "admin";
      if (isAdminTudo && $("fi_pick")) {
        const lotSummariesFi = await GET("/wms/units/by-lot");
        const fiRows = [];
        lotSummariesFi.forEach(g => {
          (g.unit_types || ["vi", "keg", "lon"]).forEach(t => {
            if (g[`${t}_count`] > 0) fiRows.push({
              product: g.product_name, lot_code: g.lot_code, unit_type: t, count: g[`${t}_count`],
            });
          });
        });
        const fiOpt = fiRows.map((g, i) => `<option value="${i}">${esc(fpLabel(g.product))} — ${esc(g.lot_code || "(không lô)")} (${g.count} ${unitTypeLabel(g).toLowerCase()})</option>`).join("");
        $("fi_pick").innerHTML = fiRows.length ? `
          <div class="row">
            <div class="field" style="flex:1"><label>Chọn lô cần xuất</label><select id="fi_group">${fiOpt}</select></div>
            <div class="field"><label>Số lượng</label><input id="fi_qty" type="number" min="0.01" step="any" value="1" style="width:100px"/></div>
          </div>
          <div class="row"><div class="field" style="flex:1"><label>Lý do (bắt buộc)</label><input id="fi_reason" placeholder="VD: hàng hỏng, hủy do kiểm tra chất lượng..."/></div>
            <button class="btn sec" id="fi_do" style="align-self:flex-end">Xuất tự do</button></div>`
          : `<div class="muted">Kho thành phẩm chưa có tồn kho khả dụng.</div>`;
        if ($("fi_group")) {
          // parseInt cắt cụt số thập phân — lô đã bị phân rã 1 phần thường có count lẻ (VD 0.625
          // vỉ), dùng parseInt sẽ luôn ra 0 và báo sai "số lượng không hợp lệ". Dùng parseFloat +
          // dung sai nhỏ (số dấu phẩy động có thể lệch vài phần tỷ khi so sánh bằng g.count).
          const syncMax = () => {
            const g = fiRows[parseInt($("fi_group").value, 10)];
            $("fi_qty").max = g.count;
            if (parseFloat($("fi_qty").value) > g.count) $("fi_qty").value = g.count;
          };
          $("fi_group").onchange = syncMax;
          syncMax();
          $("fi_do").onclick = () => guard(async () => {
            const g = fiRows[parseInt($("fi_group").value, 10)];
            const qty = parseFloat($("fi_qty").value) || 0;
            const reason = $("fi_reason").value.trim();
            if (qty <= 0 || qty > g.count + 1e-9) { toast(`Số lượng không hợp lệ (tối đa ${g.count})`, "err"); return; }
            if (!reason) { toast("Phải nhập lý do xuất tự do", "err"); return; }
            if (!confirm(`Xuất tự do ${qty} ${unitTypeLabel(g).toLowerCase()} (cũ nhất trước) của ${g.product || ""} ${g.lot_code || ""}?`)) return;
            const res = await POST("/wms/units/free-issue", { product_name: g.product, lot_code: g.lot_code,
              unit_type: g.unit_type, count: qty, reason });
            toast(`Đã xuất tự do ${res.issued} đơn vị`
              + (res.issued < res.requested ? ` (chỉ còn ${res.issued} tồn kho, ít hơn ${res.requested} yêu cầu)` : ""));
            render("wms");
          });
        }
      }
      GET("/wms/units/free-issue-history").then(rows => {
        $("fi_history").innerHTML = rows.length ? `<div class="tablewrap"><table id="t_fi_history">
          <thead><tr><th>SP</th><th>Lô</th><th>Loại</th><th>SL yêu cầu</th><th>Đã xuất</th><th>Lý do</th>
            <th>Thời gian</th><th>Người</th><th></th></tr></thead>
          <tbody>${rows.map(e => `<tr><td>${esc(fpLabel(e.product_name))}</td>
            <td class="muted">${esc(e.lot_code || "")}</td>
            <td>${unitTypeLabel({ product: e.product_name, unit_type: e.unit_type })}</td>
            <td>${e.requested ?? ""}</td><td>${e.issued ?? ""}</td>
            <td class="muted">${esc(e.reason || "")}</td>
            <td class="muted">${fmt(e.ts)}</td><td class="muted">${esc(e.actor || "")}</td>
            <td>${e.undone ? '<span class="muted">Đã hoàn tác</span>' :
              (isAdminTudo ? `<button class="btn sm sec" data-undofi="${esc(e.audit_id)}">Hoàn tác</button>` : '<span class="muted">—</span>')}</td></tr>`).join("")}</tbody></table></div>`
          : `<div class="muted">Chưa có lượt xuất tự do nào.</div>`;
        wireSearch(); wirePaginate("t_fi_history", 10);
        document.querySelectorAll("[data-undofi]").forEach(b => b.onclick = () => guard(async () => {
          if (!confirm("Hoàn tác lượt xuất tự do này? Chỉ thực hiện được nếu đơn vị chưa bị thao tác gì khác.")) return;
          const res = await POST(`/wms/units/free-issue/${b.dataset.undofi}/undo`, {});
          toast(`Đã hoàn tác: khôi phục ${res.restored} đơn vị`);
          render("wms");
        }));
      }).catch(() => { $("fi_history").innerHTML = `<div class="muted">Không tải được lịch sử.</div>`; });
    } else if (sec === "lenhdonghang") {
      $("ld_import").onclick = () => guard(async () => {
        const f = $("ld_file").files[0];
        if (!f) throw new Error("Chọn file Excel trước.");
        const fd = new FormData();
        fd.append("file", f);
        const headers = {};
        if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
        const res = await fetch("/api/wms/load-slips/import", { method: "POST", headers, body: fd });
        const result = await res.json();
        if (!res.ok) throw new Error(result && result.detail ? result.detail : "HTTP " + res.status);
        const total = (result.HL || []).length + (result["ĐM"] || []).length;
        toast(`Đã nhập ${total} xe (HL: ${(result.HL || []).length}, ĐM: ${(result["ĐM"] || []).length})`);
        render("wms");
      });
      document.querySelectorAll("[data-viewload]").forEach(b => b.onclick = () => openLoadSlipModal(b.dataset.viewload));
      document.querySelectorAll("[data-delload]").forEach(b => b.onclick = () => guard(async () => {
        if (!confirm("Xóa biên bản bàn giao này? Không thể hoàn tác.")) return;
        await DELETE(`/wms/load-slips/${b.dataset.delload}`);
        toast("Đã xóa"); render("wms");
      }));
    } else if (sec === "aging") {
      if ($("ag_save")) $("ag_save").onclick = () => guard(async () => {
        const current = await GET("/ops-settings").catch(() => ({ empty_cct_tolerance_hl: 2, empty_bbt_tolerance_hl: 2 }));
        await PUT("/ops-settings", {
          empty_cct_tolerance_hl: current.empty_cct_tolerance_hl,
          empty_bbt_tolerance_hl: current.empty_bbt_tolerance_hl,
          aging_caution_days: parseFloat($("ag_caution").value) || 30,
          aging_warning_days: parseFloat($("ag_warning").value) || 60,
          aging_critical_days: parseFloat($("ag_critical").value) || 90,
          factory_code: current.factory_code || null,
        });
        toast("Đã lưu ngưỡng cảnh báo tuổi lô"); render("wms");
      });
    } else if (sec === "fgship") {
      $("gp_mode").onchange = () => {
        const isMonth = $("gp_mode").value === "month";
        $("gp_day_field").style.display = isMonth ? "none" : "";
        $("gp_month_field").style.display = isMonth ? "" : "none";
      };
      $("gp_apply").onclick = () => {
        SUB.fgship_mode = $("gp_mode").value;
        SUB.fgship_date = $("gp_date").value;
        SUB.fgship_month = $("gp_month").value;
        render("wms");
      };
      loadFinishedGoodsShiftData();
    } else if (sec === "phanloai") {
      $("pl_mode").onchange = () => {
        const isMonth = $("pl_mode").value === "month";
        $("pl_day_field").style.display = isMonth ? "none" : "";
        $("pl_month_field").style.display = isMonth ? "" : "none";
      };
      $("pl_apply").onclick = () => {
        SUB.phanloai_mode = $("pl_mode").value;
        SUB.phanloai_date = $("pl_date").value;
        SUB.phanloai_month = $("pl_month").value;
        render("wms");
      };
      loadShipmentClassificationData();
    } else if (sec === "netship") {
      wirePaginate("t_netship", 20);
      $("ns_apply").onclick = () => {
        SUB.netship_date_from = $("ns_from").value;
        SUB.netship_date_to = $("ns_to").value;
        render("wms");
      };
    } else if (sec === "vehiclegs") {
      wirePaginate("t_vg_trip", 20);
      wirePaginate("t_vg_consigned", 20);
      wirePaginate("t_vg_fuel", 20);
      $("vg_apply").onclick = () => {
        SUB.vehiclegs_date_from = $("vg_from").value;
        SUB.vehiclegs_date_to = $("vg_to").value;
        render("wms");
      };
    }
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
        <td>${f.active ? badge("available") + "Dùng" : badge("obsolete") + "Ngừng"}</td>
        ${canManage ? `<td style="white-space:nowrap"><button class="btn sm sec" data-ft-edit="${f.form_type_id}">Sửa</button>
          <button class="btn sm sec" data-ft-del="${f.form_type_id}">Xóa</button></td>` : "<td></td>"}</tr>`).join("");
      const eqRows = equipment.map(e => `<tr><td><code class="k">${esc(e.code)}</code></td><td>${esc(e.name)}</td>
        <td>${esc(CIP_AREA_LABEL[e.area] || e.area)}</td>
        <td class="muted">${e.production_line_id ? "Gắn tank/dây chuyền cụ thể" : "Dùng chung"}</td>
        <td>${e.active ? badge("available") + "Dùng" : badge("obsolete") + "Ngừng"}</td>
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
