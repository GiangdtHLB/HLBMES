// Code39 barcode → SVG (không phụ thuộc thư viện ngoài). Hỗ trợ 0-9 A-Z - . space $ / + %
// Dùng cho in tem lô/mẻ/lệnh ở kiosk.
(function (global) {
  const C39 = {
    "0": "nnnwwnwnn", "1": "wnnwnnnnw", "2": "nnwwnnnnw", "3": "wnwwnnnnn", "4": "nnnwwnnnw",
    "5": "wnnwwnnnn", "6": "nnwwwnnnn", "7": "nnnwnnwnw", "8": "wnnwnnwnn", "9": "nnwwnnwnn",
    "A": "wnnnnwnnw", "B": "nnwnnwnnw", "C": "wnwnnwnnn", "D": "nnnnwwnnw", "E": "wnnnwwnnn",
    "F": "nnwnwwnnn", "G": "nnnnnwwnw", "H": "wnnnnwwnn", "I": "nnwnnwwnn", "J": "nnnnwwwnn",
    "K": "wnnnnnnww", "L": "nnwnnnnww", "M": "wnwnnnnwn", "N": "nnnnwnnww", "O": "wnnnwnnwn",
    "P": "nnwnwnnwn", "Q": "nnnnnnwww", "R": "wnnnnnwwn", "S": "nnwnnnwwn", "T": "nnnnwnwwn",
    "U": "wwnnnnnnw", "V": "nwwnnnnnw", "W": "wwwnnnnnn", "X": "nwnnwnnnw", "Y": "wwnnwnnnn",
    "Z": "nwwnwnnnn", "-": "nwnnnnwnw", ".": "wwnnnnwnn", " ": "nwwnnnwnn", "*": "nwnnwnwnn",
    "$": "nwnwnwnnn", "/": "nwnwnnnwn", "+": "nwnnnwnwn", "%": "nnnwnwnwn",
  };
  function code39SVG(text, opts) {
    opts = opts || {};
    const narrow = opts.narrow || 2, wide = narrow * 2.6, h = opts.height || 64, pad = 10;
    const data = "*" + String(text).toUpperCase().replace(/[^0-9A-Z\-. $/+%]/g, "") + "*";
    let x = pad, rects = "";
    for (let ci = 0; ci < data.length; ci++) {
      const pat = C39[data[ci]]; if (!pat) continue;
      for (let i = 0; i < pat.length; i++) {
        const w = pat[i] === "w" ? wide : narrow;
        if (i % 2 === 0) rects += `<rect x="${x.toFixed(1)}" y="0" width="${w.toFixed(1)}" height="${h}" fill="#000"/>`;
        x += w;
      }
      x += narrow; // khoảng cách giữa ký tự
    }
    const W = x + pad;
    return `<svg viewBox="0 0 ${W.toFixed(0)} ${h + 22}" width="100%" style="background:#fff;max-width:${Math.min(W, 420)}px">
      <rect width="100%" height="100%" fill="#fff"/>${rects}
      <text x="${(W / 2).toFixed(0)}" y="${h + 16}" text-anchor="middle" font-family="monospace" font-size="13" fill="#000">${String(text)}</text></svg>`;
  }
  global.code39SVG = code39SVG;
})(window);
