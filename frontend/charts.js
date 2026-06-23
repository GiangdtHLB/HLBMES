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
      <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${H - pad.b}" stroke="#2b3a47"/>
      <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="#2b3a47"/>
      <text x="4" y="${py(ymax) + 4}" fill="#8aa0b2" font-size="11">${ymax.toFixed(1)}</text>
      <text x="4" y="${py(ymin) + 4}" fill="#8aa0b2" font-size="11">${ymin.toFixed(1)}</text>
      <text x="${pad.l}" y="${H - 6}" fill="#8aa0b2" font-size="11">${fmtT(xmin)}</text>
      <text x="${W - pad.r}" y="${H - 6}" fill="#8aa0b2" font-size="11" text-anchor="end">${fmtT(xmax)}</text>
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
      <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="#2b3a47" stroke-width="10"/>
      <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="${color}" stroke-width="10"
        stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"
        stroke-linecap="round" transform="rotate(-90 ${cx} ${cx})"/>
      <text x="${cx}" y="${cx - 2}" fill="#e6edf3" font-size="22" font-weight="700" text-anchor="middle">${(p * 100).toFixed(1)}%</text>
      <text x="${cx}" y="${cx + 18}" fill="#8aa0b2" font-size="11" text-anchor="middle">${label}</text>
    </svg>`;
  },
  // Thanh ngang cho các thành phần (A/P/Q hoặc phân bố trạng thái).
  hbars(items) {
    const max = Math.max(...items.map(i => i.value), 1e-9);
    return `<div style="display:flex;flex-direction:column;gap:8px">${items.map(i => {
      const w = (i.value / max) * 100;
      const col = i.color || "#17a2b8";
      const disp = i.pct ? (i.value * 100).toFixed(1) + "%" : i.value;
      return `<div><div style="display:flex;justify-content:space-between;font-size:12px;color:#8aa0b2"><span>${esc(i.label)}</span><span>${disp}</span></div>
        <div style="background:#1e2a36;border-radius:4px;height:10px;overflow:hidden"><div style="width:${w}%;height:100%;background:${col}"></div></div></div>`;
    }).join("")}</div>`;
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
        <text x="${(x + w / 2).toFixed(1)}" y="${(y - 3).toFixed(1)}" fill="#cdd9e3" font-size="10" text-anchor="middle">${typeof it.value === "number" ? (it.value >= 1000 ? (it.value / 1000).toFixed(1) + "k" : it.value) : it.value}</text>
        <text x="${(x + w / 2).toFixed(1)}" y="${H - pad.b + 13}" fill="#8aa0b2" font-size="10" text-anchor="middle">${esc(String(it.label).slice(0, 8))}</text>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
      <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="#2b3a47"/>
      <text x="4" y="${pad.t + 8}" fill="#8aa0b2" font-size="10">${max >= 1000 ? (max / 1000).toFixed(1) + "k" : Math.round(max)} ${esc(unit)}</text>${bars}</svg>`;
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
        <text x="${(x0 + gw / 2).toFixed(1)}" y="${H - pad.b + 13}" fill="#8aa0b2" font-size="10" text-anchor="middle">${esc(String(it.label).slice(0, 9))}</text>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
      <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="#2b3a47"/>
      <rect x="${pad.l}" y="2" width="9" height="9" fill="${colorA}"/><text x="${pad.l + 13}" y="10" fill="#8aa0b2" font-size="10">${esc(labelA)}</text>
      <rect x="${pad.l + 70}" y="2" width="9" height="9" fill="${colorB}"/><text x="${pad.l + 83}" y="10" fill="#8aa0b2" font-size="10">${esc(labelB)}</text>${g}</svg>`;
  },
  // Tròn/donut phân loại: items=[{label,value,color?}]
  pie(items, { size = 170, donut = true } = {}) {
    const total = items.reduce((s, i) => s + i.value, 0) || 1;
    const cx = size / 2, cy = size / 2, r = size / 2 - 6, ri = donut ? r * 0.58 : 0;
    const PAL = ["#f5a623", "#3498db", "#2ecc71", "#e74c3c", "#9b59b6", "#1abc9c", "#e67e22", "#8aa0b2"];
    let ang = -Math.PI / 2, segs = "";
    items.forEach((it, i) => {
      const frac = it.value / total, a2 = ang + frac * 2 * Math.PI;
      const large = frac > 0.5 ? 1 : 0;
      const x1 = cx + r * Math.cos(ang), y1 = cy + r * Math.sin(ang);
      const x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
      const col = it.color || PAL[i % PAL.length];
      if (frac > 0.999) { segs += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${col}"/>`; }
      else { segs += `<path d="M ${cx} ${cy} L ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)} Z" fill="${col}"/>`; }
      ang = a2;
    });
    const hole = donut ? `<circle cx="${cx}" cy="${cy}" r="${ri}" fill="#17212b"/><text x="${cx}" y="${cy + 4}" fill="#e6edf3" font-size="15" font-weight="700" text-anchor="middle">${total}</text>` : "";
    const legend = items.map((it, i) => `<div style="display:flex;align-items:center;gap:6px;font-size:12px;margin:2px 0">
      <span style="width:10px;height:10px;border-radius:2px;background:${it.color || PAL[i % PAL.length]}"></span>${esc(it.label)} <span class="muted">(${it.value})</span></div>`).join("");
    return `<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
      <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">${segs}${hole}</svg><div>${legend}</div></div>`;
  },
};
