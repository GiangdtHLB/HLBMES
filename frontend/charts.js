"use strict";
// ---------- Thư viện biểu đồ SVG (zero-dependency) — tách từ app.js (P2 modular) ----------
// Nạp TRƯỚC app.js. Dùng `esc()` (định nghĩa trong app.js) ở thời điểm gọi (runtime) nên
// thứ tự nạp charts.js→app.js→views_ext.js là đủ. CH là global, app.js + views_ext.js dùng chung.
const CH = {
  // Biểu đồ đường 1 series, tự co giãn theo min/max của chính nó.
  line(points, { color = "#f5a623", unit = "", label = "", height = 120 } = {}) {
    if (!points || !points.length) return `<div class="muted">Không có dữ liệu.</div>`;
    const W = 600, H = height, pad = { l: 44, r: 12, t: 12, b: 22 };
    const xs = points.map(p => new Date(p.ts).getTime());
    const ys = points.map(p => p.value);
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    let ymin = Math.min(...ys), ymax = Math.max(...ys);
    if (ymin === ymax) { ymin -= 1; ymax += 1; }
    const pdy = (ymax - ymin) * 0.1; ymin -= pdy; ymax += pdy;
    const px = (x) => pad.l + (xmax === xmin ? 0 : (x - xmin) / (xmax - xmin)) * (W - pad.l - pad.r);
    const py = (y) => pad.t + (1 - (y - ymin) / (ymax - ymin)) * (H - pad.t - pad.b);
    const pts = points.map(p => `${px(new Date(p.ts).getTime()).toFixed(1)},${py(p.value).toFixed(1)}`).join(" ");
    const area = `${pad.l},${(H - pad.b).toFixed(1)} ${pts} ${px(xmax).toFixed(1)},${(H - pad.b).toFixed(1)}`;
    const fmtT = (t) => new Date(t).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
    const gid = "g" + Math.random().toString(36).slice(2, 8);
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
      <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity="0.35"/><stop offset="100%" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
      <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${H - pad.b}" stroke="var(--border)"/>
      <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="var(--border)"/>
      <text x="4" y="${py(ymax) + 4}" fill="var(--muted)" font-size="11">${ymax.toFixed(1)}</text>
      <text x="4" y="${py(ymin) + 4}" fill="var(--muted)" font-size="11">${ymin.toFixed(1)}</text>
      <text x="${pad.l}" y="${H - 6}" fill="var(--muted)" font-size="11">${fmtT(xmin)}</text>
      <text x="${W - pad.r}" y="${H - 6}" fill="var(--muted)" font-size="11" text-anchor="end">${fmtT(xmax)}</text>
      <polygon points="${area}" fill="url(#${gid})"/>
      <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2"/>
      <text x="${W - pad.r}" y="${pad.t + 12}" fill="${color}" font-size="12" text-anchor="end" font-weight="700">${label} ${unit}</text>
    </svg>`;
  },
  // Vòng gauge (donut) thể hiện phần trăm.
  donut(pct, { label = "", size = 120 } = {}) {
    const p = Math.max(0, Math.min(1, pct));
    const r = size / 2 - 10, c = 2 * Math.PI * r, off = c * (1 - p);
    const color = p >= 0.85 ? "#2ecc71" : p >= 0.65 ? "#f5a623" : "#e74c3c";
    const cx = size / 2;
    return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">
      <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="var(--border)" stroke-width="10"/>
      <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="${color}" stroke-width="10"
        stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"
        stroke-linecap="round" transform="rotate(-90 ${cx} ${cx})"/>
      <text x="${cx}" y="${cx - 2}" fill="var(--text)" font-size="22" font-weight="700" text-anchor="middle">${(p * 100).toFixed(1)}%</text>
      <text x="${cx}" y="${cx + 18}" fill="var(--muted)" font-size="11" text-anchor="middle">${label}</text>
    </svg>`;
  },
  // Thanh ngang cho các thành phần (A/P/Q hoặc phân bố trạng thái).
  hbars(items) {
    const max = Math.max(...items.map(i => i.value), 1e-9);
    return `<div style="display:flex;flex-direction:column;gap:8px">${items.map(i => {
      const w = (i.value / max) * 100;
      const col = i.color || "#17a2b8";
      const disp = i.disp || (i.pct ? (i.value * 100).toFixed(1) + "%" : i.value);
      return `<div><div style="display:flex;justify-content:space-between;font-size:12px;color:var(--muted)"><span>${esc(i.label)}</span><span>${esc(String(disp))}</span></div>
        <div style="background:var(--panel2);border-radius:4px;height:10px;overflow:hidden"><div style="width:${w}%;height:100%;background:${col}"></div></div></div>`;
    }).join("")}</div>`;
  },
  // Thanh ngang có trục số (gridline + tick) và đầu thanh bo tròn — dùng cho báo cáo dạng
  // "điểm số/thang đo" (vd số ngày tồn kho so với ngưỡng cảnh báo). Khác hbars() ở chỗ trục X
  // dùng chung 1 thang đo cố định (max) cho mọi thanh thay vì co giãn theo thanh dài nhất, để
  // có thể so trực quan với các mốc ngưỡng vẽ trên cùng trục.
  agingBars(items, { max, height, axisLabel = "" } = {}) {
    if (!items || !items.length) return '<div class="muted">Không có dữ liệu.</div>';
    // Nhãn từng dòng nằm trên 1 hàng riêng phía trên thanh (không còn ở cột trái cố định) — để
    // tên dài (VD "Bia chai Classic 330ml · lô OBLIVE-FPTEST-01") không bị cắt cụt ở mép trái SVG.
    const rowH = 40, barH = 14, labelH = 16;
    const W = 700;
    // pad.b cần đủ chỗ cho CẢ hàng số tick (~14px) LẪN hàng tiêu đề trục bên dưới nó (~14px) khi
    // có axisLabel — nếu chỉ chừa 1 hàng, tiêu đề trục sẽ đè lên số tick ở giữa trục.
    const pad = { l: 16, r: 100, t: 8, b: axisLabel ? 40 : 24 };
    const H = height || (pad.t + items.length * rowH + pad.b);
    const plotW = W - pad.l - pad.r;
    // Nếu người gọi truyền `max` cố định (VD so với ngưỡng cảnh báo) thì DÙNG ĐÚNG giá trị đó —
    // không trộn thêm giá trị thật của từng thanh vào, nếu không 1 lô lỗi dữ liệu/test cũ có giá
    // trị hàng nghìn sẽ kéo dãn cả trục (thanh vượt quá `m` vẫn hiện đủ dài nhờ Math.min bên dưới).
    // Chỉ tự co giãn theo dữ liệu khi người gọi KHÔNG truyền max (VD báo cáo tồn tối thiểu).
    const m = max != null ? Math.max(max, 1e-9) : Math.max(...items.map(i => i.value || 0), 10);
    const x = (v) => pad.l + Math.max(0, Math.min(v, m)) / m * plotW;
    const nTicks = 10;
    const step = m / nTicks;
    const ticks = Array.from({ length: nTicks + 1 }, (_, i) => i * step);
    const tickY = H - pad.b + 14;
    const gridlines = ticks.map(t => `<line x1="${x(t).toFixed(1)}" y1="${pad.t}" x2="${x(t).toFixed(1)}" y2="${(H - pad.b).toFixed(1)}" stroke="var(--border)" stroke-width="1"/>
      <text x="${x(t).toFixed(1)}" y="${tickY.toFixed(1)}" fill="var(--muted)" font-size="10" text-anchor="middle">${Math.round(t)}</text>`).join("");
    const bars = items.map((it, i) => {
      const rowTop = pad.t + i * rowH;
      const labelY = rowTop + 11;
      const y = rowTop + labelH + (rowH - labelH - barH) / 2;
      const bw = Math.max(x(it.value) - pad.l, 0);
      const col = it.color || "#17a2b8";
      const disp = it.disp != null ? it.disp : it.value;
      return `<text x="${pad.l.toFixed(1)}" y="${labelY.toFixed(1)}" fill="var(--text)" font-size="12" text-anchor="start">${esc(String(it.label))}</text>
        <rect x="${pad.l.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${barH}" rx="${barH / 2}" fill="${col}"/>
        <text x="${(pad.l + bw + 8).toFixed(1)}" y="${(y + barH / 2 + 4).toFixed(1)}" fill="var(--text)" font-size="12">${esc(String(disp))}</text>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
      ${gridlines}
      ${bars}
      ${axisLabel ? `<text x="${(pad.l + plotW / 2).toFixed(1)}" y="${(H - 6).toFixed(1)}" fill="var(--muted)" font-size="11" text-anchor="middle">${esc(axisLabel)}</text>` : ""}
    </svg>`;
  },
  // Thanh ngang lệch 2 phía quanh mốc 0, có trục số + tick — dùng cho báo cáo dạng "còn hạn/quá
  // hạn" (số ngày đến hạn: âm = đã quá hạn, vẽ lệch trái; dương = còn hạn, vẽ lệch phải).
  // items=[{label,value,color,disp}]. maxAbs tự tính từ |value| lớn nhất nếu không truyền.
  hbarsDiverge(items, { maxAbs, height, axisLabel = "" } = {}) {
    if (!items || !items.length) return '<div class="muted">Không có dữ liệu.</div>';
    // Tên vật tư nằm trên 1 dòng riêng phía trên thanh (thay vì cùng hàng bên trái trục) — nếu
    // để chung 1 hàng, nhãn "Quá hạn N ngày" của thanh âm dài nhất sẽ chồng lên tên vật tư vì cả
    // 2 cùng dồn về phía bên trái mốc 0.
    const rowH = 42, barH = 14, labelH = 16;
    const W = 700;
    // pad.b cần đủ chỗ cho CẢ hàng số tick (~14px) LẪN hàng tiêu đề trục bên dưới nó (~14px) khi
    // có axisLabel — nếu chỉ chừa 1 hàng, tiêu đề trục sẽ đè lên số tick ở giữa trục.
    const pad = { l: 90, r: 100, t: 8, b: axisLabel ? 40 : 24 };
    const H = height || (pad.t + items.length * rowH + pad.b);
    const plotW = W - pad.l - pad.r;
    const cx = pad.l + plotW / 2;
    const half = plotW / 2;
    const m = Math.max(maxAbs || 0, ...items.map(i => Math.abs(i.value || 0)), 1);
    const x = (v) => cx + Math.max(-1, Math.min(1, v / m)) * half;
    const nTicks = 4;
    const step = m / nTicks;
    const ticks = Array.from({ length: nTicks * 2 + 1 }, (_, i) => (i - nTicks) * step);
    const tickY = H - pad.b + 14;
    const gridlines = ticks.map(t => {
      const isZero = Math.abs(t) < 1e-9;
      const xt = x(t);
      return `<line x1="${xt.toFixed(1)}" y1="${pad.t}" x2="${xt.toFixed(1)}" y2="${(H - pad.b).toFixed(1)}" stroke="${isZero ? "var(--muted)" : "var(--border)"}" stroke-width="${isZero ? 1.5 : 1}"/>
        <text x="${xt.toFixed(1)}" y="${tickY.toFixed(1)}" fill="var(--muted)" font-size="10" text-anchor="middle">${Math.round(t)}</text>`;
    }).join("");
    const bars = items.map((it, i) => {
      const rowTop = pad.t + i * rowH;
      const labelY = rowTop + 11;
      const y = rowTop + labelH + 2;
      const v = it.value || 0;
      const x0 = Math.min(x(0), x(v)), x1 = Math.max(x(0), x(v));
      const col = it.color || "#17a2b8";
      const disp = it.disp != null ? it.disp : it.value;
      const labelX = v < 0 ? x0 - 8 : x1 + 8;
      const anchor = v < 0 ? "end" : "start";
      return `<text x="4" y="${labelY.toFixed(1)}" fill="var(--text)" font-size="12" text-anchor="start">${esc(String(it.label))}</text>
        <rect x="${x0.toFixed(1)}" y="${y.toFixed(1)}" width="${(x1 - x0).toFixed(1)}" height="${barH}" rx="${barH / 2}" fill="${col}"/>
        <text x="${labelX.toFixed(1)}" y="${(y + barH / 2 + 4).toFixed(1)}" fill="var(--text)" font-size="12" text-anchor="${anchor}">${esc(String(disp))}</text>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
      ${gridlines}
      ${bars}
      ${axisLabel ? `<text x="${cx.toFixed(1)}" y="${(H - 6).toFixed(1)}" fill="var(--muted)" font-size="11" text-anchor="middle">${esc(axisLabel)}</text>` : ""}
    </svg>`;
  },
  // Cột đứng: items=[{label,value,color?}]
  vbars(items, { unit = "", height = 150, color = "#17a2b8" } = {}) {
    if (!items || !items.length) return '<div class="muted">Không có dữ liệu.</div>';
    const W = 560, H = height, pad = { l: 40, r: 8, t: 10, b: 40 };
    const max = Math.max(...items.map(i => i.value), 1e-9);
    const bw = (W - pad.l - pad.r) / items.length;
    const bars = items.map((it, i) => {
      const h = (it.value / max) * (H - pad.t - pad.b);
      const x = pad.l + i * bw + bw * 0.15, w = bw * 0.7, y = H - pad.b - h;
      return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(h,0).toFixed(1)}" rx="2" fill="${it.color || color}"/>
        <text x="${(x + w / 2).toFixed(1)}" y="${(y - 3).toFixed(1)}" fill="var(--text)" font-size="10" text-anchor="middle">${typeof it.value === "number" ? (it.value >= 1000 ? (it.value / 1000).toFixed(1) + "k" : it.value) : it.value}</text>
        <text x="${(x + w / 2).toFixed(1)}" y="${H - pad.b + 13}" fill="var(--muted)" font-size="10" text-anchor="middle">${esc(String(it.label).slice(0, 8))}</text>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
      <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="var(--border)"/>
      <text x="4" y="${pad.t + 8}" fill="var(--muted)" font-size="10">${max >= 1000 ? (max / 1000).toFixed(1) + "k" : Math.round(max)} ${esc(unit)}</text>${bars}</svg>`;
  },
  // Cột nhóm 2 series (vd định mức vs thực tế): items=[{label,a,b}]
  grouped(items, { labelA = "A", labelB = "B", colorA = "#3498db", colorB = "#f5a623", height = 160 } = {}) {
    if (!items || !items.length) return '<div class="muted">Không có dữ liệu.</div>';
    const W = 560, H = height, pad = { l: 44, r: 8, t: 14, b: 42 };
    const max = Math.max(...items.flatMap(i => [i.a, i.b]), 1e-9);
    const gw = (W - pad.l - pad.r) / items.length;
    const norm = (v) => (v / max) * (H - pad.t - pad.b);
    const g = items.map((it, i) => {
      const x0 = pad.l + i * gw;
      const bw = gw * 0.32;
      const ya = H - pad.b - norm(it.a), yb = H - pad.b - norm(it.b);
      return `<rect x="${(x0 + gw * 0.15).toFixed(1)}" y="${ya.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(norm(it.a),0).toFixed(1)}" fill="${colorA}"/>
        <rect x="${(x0 + gw * 0.15 + bw + 3).toFixed(1)}" y="${yb.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(norm(it.b),0).toFixed(1)}" fill="${colorB}"/>
        <text x="${(x0 + gw / 2).toFixed(1)}" y="${H - pad.b + 13}" fill="var(--muted)" font-size="10" text-anchor="middle">${esc(String(it.label).slice(0, 9))}</text>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
      <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="var(--border)"/>
      <rect x="${pad.l}" y="2" width="9" height="9" fill="${colorA}"/><text x="${pad.l + 13}" y="10" fill="var(--muted)" font-size="10">${esc(labelA)}</text>
      <rect x="${pad.l + 70}" y="2" width="9" height="9" fill="${colorB}"/><text x="${pad.l + 83}" y="10" fill="var(--muted)" font-size="10">${esc(labelB)}</text>${g}</svg>`;
  },
  // Cột nhóm N series (vd nhiều nhóm chỉ tiêu năng lượng theo kỳ):
  // categories=[label,...], series=[{label,color,values:[v theo từng category]}]
  groupedN(categories, series, { height = 180, unit = "" } = {}) {
    if (!categories || !categories.length || !series || !series.length) return '<div class="muted">Không có dữ liệu.</div>';
    const W = Math.max(560, categories.length * 60), H = height, pad = { l: 44, r: 8, t: 22, b: 40 };
    const PAL = ["#3498db", "#f5a623", "#2ecc71", "#e74c3c", "#9b59b6", "#1abc9c", "#e67e22", "var(--muted)"];
    const max = Math.max(...series.flatMap(s => s.values), 1e-9);
    const gw = (W - pad.l - pad.r) / categories.length;
    const n = series.length;
    const bw = (gw * 0.8) / n;
    const norm = (v) => (v / max) * (H - pad.t - pad.b);
    const fmtV = (v) => v >= 1000 ? (v / 1000).toFixed(1) + "k" : (v ? Math.round(v) : "0");
    const bars = categories.map((cat, ci) => {
      const x0 = pad.l + ci * gw + gw * 0.1;
      const rects = series.map((s, si) => {
        const v = s.values[ci] || 0;
        const x = x0 + si * bw, h = Math.max(norm(v), 0), y = H - pad.b - h;
        const col = s.color || PAL[si % PAL.length];
        return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw * 0.88).toFixed(1)}" height="${h.toFixed(1)}" fill="${col}"/>
          <text x="${(x + bw * 0.44).toFixed(1)}" y="${(y - 2).toFixed(1)}" fill="var(--text)" font-size="8" text-anchor="middle">${fmtV(v)}</text>`;
      }).join("");
      return `${rects}<text x="${(x0 + (gw * 0.8) / 2).toFixed(1)}" y="${H - pad.b + 13}" fill="var(--muted)" font-size="10" text-anchor="middle">${esc(String(cat).slice(0, 9))}</text>`;
    }).join("");
    const legend = series.map((s, si) => `<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;font-size:11px;color:var(--muted)">
      <span style="width:9px;height:9px;border-radius:2px;background:${s.color || PAL[si % PAL.length]};display:inline-block"></span>${esc(s.label)}</span>`).join("");
    return `<div>
      <div style="margin-bottom:4px">${legend}</div>
      <svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
        <text x="4" y="${pad.t - 6}" fill="var(--muted)" font-size="10">${max >= 1000 ? (max / 1000).toFixed(1) + "k" : Math.round(max)} ${esc(unit)}</text>
        <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="var(--border)"/>${bars}
      </svg></div>`;
  },
  // Nhiều đường trên cùng 1 trục (vd nhiều nhóm chỉ tiêu năng lượng theo thời gian):
  // series=[{label,color,points:[{x,value}]}] — x dùng chung trục ngang (chuỗi hoặc số thứ tự kỳ)
  lineMulti(series, { height = 180, unit = "" } = {}) {
    if (!series || !series.length || !series.some(s => s.points && s.points.length)) return '<div class="muted">Không có dữ liệu.</div>';
    const W = 620, H = height, pad = { l: 44, r: 12, t: 22, b: 24 };
    const PAL = ["#3498db", "#f5a623", "#2ecc71", "#e74c3c", "#9b59b6", "#1abc9c", "#e67e22", "var(--muted)"];
    const xcats = series.find(s => s.points && s.points.length).points.map(p => p.x);
    const allVals = series.flatMap(s => (s.points || []).map(p => p.value));
    let ymin = Math.min(...allVals, 0), ymax = Math.max(...allVals, 1e-9);
    if (ymin === ymax) { ymin -= 1; ymax += 1; }
    const pdy = (ymax - ymin) * 0.1; ymax += pdy;
    const px = (i) => pad.l + (xcats.length <= 1 ? 0 : (i / (xcats.length - 1)) * (W - pad.l - pad.r));
    const py = (v) => pad.t + (1 - (v - ymin) / (ymax - ymin)) * (H - pad.t - pad.b);
    const lines = series.map((s, si) => {
      const col = s.color || PAL[si % PAL.length];
      const pts = (s.points || []).map((p, i) => `${px(i).toFixed(1)},${py(p.value).toFixed(1)}`).join(" ");
      return `<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="2"/>`;
    }).join("");
    const legend = series.map((s, si) => `<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;font-size:11px;color:var(--muted)">
      <span style="width:9px;height:9px;border-radius:2px;background:${s.color || PAL[si % PAL.length]};display:inline-block"></span>${esc(s.label)}</span>`).join("");
    const fmtX = (i) => String(xcats[i] ?? "").slice(5);
    return `<div>
      <div style="margin-bottom:4px">${legend}</div>
      <svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
        <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${H - pad.b}" stroke="var(--border)"/>
        <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="var(--border)"/>
        <text x="4" y="${py(ymax) + 4}" fill="var(--muted)" font-size="10">${ymax.toFixed(1)} ${esc(unit)}</text>
        <text x="4" y="${py(ymin) + 4}" fill="var(--muted)" font-size="10">${ymin.toFixed(1)}</text>
        <text x="${pad.l}" y="${H - 6}" fill="var(--muted)" font-size="10">${fmtX(0)}</text>
        <text x="${W - pad.r}" y="${H - 6}" fill="var(--muted)" font-size="10" text-anchor="end">${fmtX(xcats.length - 1)}</text>
        ${lines}
      </svg></div>`;
  },
  // 2 trục Y độc lập (vd nhiệt độ+°S bên trái 0-20, mật độ tế bào 10^6/ml bên phải 0-56 —
  // biểu đồ theo dõi lên men BM 1.11 (06)): leftSeries/rightSeries=[{label,color,
  // points:[{x,value}]}] (value=null/undefined -> vẽ đứt đoạn, bỏ điểm đó). xLabels dùng
  // chung trục ngang (VD số ngày) cho cả 2 nhóm series.
  lineDualAxis(leftSeries, rightSeries, xLabels, { height = 220 } = {}) {
    const all = [...(leftSeries || []), ...(rightSeries || [])];
    if (!all.length || !all.some(s => s.points && s.points.length)) return '<div class="muted">Không có dữ liệu.</div>';
    const W = 640, H = height, pad = { l: 40, r: 40, t: 22, b: 24 };
    const PAL_L = ["#3498db", "#f5a623"], PAL_R = ["#2ecc71", "#9b59b6"];
    const n = Math.max(...all.map(s => (s.points || []).length), (xLabels || []).length);
    const vals = (list) => list.flatMap(s => (s.points || []).map(p => p.value).filter(v => v !== null && v !== undefined));
    const scale = (list) => {
      let vmin = Math.min(...vals(list), 0), vmax = Math.max(...vals(list), 1e-9);
      if (!vals(list).length) { vmin = 0; vmax = 1; }
      if (vmin === vmax) { vmin -= 1; vmax += 1; }
      vmax += (vmax - vmin) * 0.1;
      return { vmin, vmax };
    };
    const { vmin: lymin, vmax: lymax } = scale(leftSeries || []);
    const { vmin: rymin, vmax: rymax } = scale(rightSeries || []);
    const px = (i) => pad.l + (n <= 1 ? 0 : (i / (n - 1)) * (W - pad.l - pad.r));
    const pyL = (v) => pad.t + (1 - (v - lymin) / (lymax - lymin)) * (H - pad.t - pad.b);
    const pyR = (v) => pad.t + (1 - (v - rymin) / (rymax - rymin)) * (H - pad.t - pad.b);
    const segmentsOf = (points, py) => {
      const segs = []; let cur = [];
      (points || []).forEach((p, i) => {
        if (p.value === null || p.value === undefined) { if (cur.length) segs.push(cur); cur = []; }
        else cur.push(`${px(i).toFixed(1)},${py(p.value).toFixed(1)}`);
      });
      if (cur.length) segs.push(cur);
      return segs;
    };
    const drawLines = (list, PAL, py, dash) => (list || []).map((s, si) => {
      const col = s.color || PAL[si % PAL.length];
      return segmentsOf(s.points, py).map(seg =>
        `<polyline points="${seg.join(" ")}" fill="none" stroke="${col}" stroke-width="2"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`
      ).join("");
    }).join("");
    const linesLeft = drawLines(leftSeries, PAL_L, pyL, null);
    const linesRight = drawLines(rightSeries, PAL_R, pyR, "4,3");
    const legendOf = (list, PAL) => (list || []).map((s, si) => `<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;font-size:11px;color:var(--muted)">
      <span style="width:9px;height:9px;border-radius:2px;background:${s.color || PAL[si % PAL.length]};display:inline-block"></span>${esc(s.label)}</span>`).join("");
    const fmtX = (i) => (xLabels && xLabels[i] != null) ? String(xLabels[i]) : String(i + 1);
    return `<div>
      <div style="margin-bottom:4px">${legendOf(leftSeries, PAL_L)}${legendOf(rightSeries, PAL_R)}</div>
      <svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
        <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${H - pad.b}" stroke="var(--border)"/>
        <line x1="${W - pad.r}" y1="${pad.t}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="var(--border)"/>
        <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="var(--border)"/>
        <text x="4" y="${pyL(lymax) + 4}" fill="var(--muted)" font-size="10">${lymax.toFixed(1)}</text>
        <text x="4" y="${pyL(lymin) + 4}" fill="var(--muted)" font-size="10">${lymin.toFixed(1)}</text>
        <text x="${W - pad.r + 3}" y="${pyR(rymax) + 4}" fill="var(--muted)" font-size="10">${rymax.toFixed(1)}</text>
        <text x="${W - pad.r + 3}" y="${pyR(rymin) + 4}" fill="var(--muted)" font-size="10">${rymin.toFixed(1)}</text>
        <text x="${pad.l}" y="${H - 6}" fill="var(--muted)" font-size="10">${esc(fmtX(0))}</text>
        <text x="${W - pad.r}" y="${H - 6}" fill="var(--muted)" font-size="10" text-anchor="end">${esc(fmtX(n - 1))}</text>
        ${linesLeft}${linesRight}
      </svg></div>`;
  },
  // Tròn/donut phân loại: items=[{label,value,color?}]
  pie(items, { size = 170, donut = true, showPercent = true } = {}) {
    const total = items.reduce((s, i) => s + i.value, 0) || 1;
    const cx = size / 2, cy = size / 2, r = size / 2 - 6, ri = donut ? r * 0.58 : 0;
    const PAL = ["#f5a623", "#3498db", "#2ecc71", "#e74c3c", "#9b59b6", "#1abc9c", "#e67e22", "var(--muted)"];
    let ang = -Math.PI / 2, segs = "", labels = "";
    items.forEach((it, i) => {
      const frac = it.value / total, a2 = ang + frac * 2 * Math.PI;
      const large = frac > 0.5 ? 1 : 0;
      const x1 = cx + r * Math.cos(ang), y1 = cy + r * Math.sin(ang);
      const x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
      const col = it.color || PAL[i % PAL.length];
      if (frac > 0.999) { segs += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${col}"/>`; }
      else { segs += `<path d="M ${cx} ${cy} L ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)} Z" fill="${col}"/>`; }
      if (showPercent && frac >= 0.03) {
        const midAng = ang + frac * Math.PI;
        const labelR = donut ? (r + ri) / 2 : r * 0.65;
        const lx = cx + labelR * Math.cos(midAng), ly = cy + labelR * Math.sin(midAng);
        labels += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" fill="#fff" font-size="11" font-weight="700" text-anchor="middle" dominant-baseline="middle">${Math.round(frac * 100)}%</text>`;
      }
      ang = a2;
    });
    const totalLabel = total.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
    const hole = donut ? `<circle cx="${cx}" cy="${cy}" r="${ri}" fill="var(--panel)"/><text x="${cx}" y="${cy + 4}" fill="var(--text)" font-size="15" font-weight="700" text-anchor="middle">${totalLabel}</text>` : "";
    const legend = items.map((it, i) => `<div style="display:flex;align-items:center;gap:6px;font-size:12px;margin:2px 0">
      <span style="width:10px;height:10px;border-radius:2px;background:${it.color || PAL[i % PAL.length]}"></span>${esc(it.label)} <span class="muted">(${it.value}${showPercent ? ", " + Math.round((it.value / total) * 100) + "%" : ""})</span></div>`).join("");
    return `<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
      <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">${segs}${labels}${hole}</svg><div>${legend}</div></div>`;
  },
};
