"""Rule Engine cho Import Mapping Explorer — transform/validate từng cột.

Rule lưu dạng JSON trong integration_column_mapping (không hardcode cho Brawmart):
    {"type": "normalize_uom", "params": {...}}

apply(value, rule) -> {"value": <đã transform>, "error": str|None, "warning": str|None}
- error: chặn dòng (conflict/error).
- warning: không chặn (giá trị bị chuẩn hoá / tùy chọn thiếu...).
"""

import re
from datetime import datetime

RULE_TYPES = [
    "trim", "uppercase", "lowercase", "normalize_uom", "boolean_map", "enum_map",
    "date_parse", "number_parse", "regex_validate", "default_if_empty", "required_if", "lookup",
]

_DEF_UOM = {
    "KG": ["kg", "kilogram", "kgs", "kí", "ki", "kilôgam"],
    "G": ["g", "gram", "gam"],
    "L": ["l", "lit", "liter", "litre", "lít"],
    "ML": ["ml", "mililit"],
    "CAI": ["cái", "cai", "pcs", "pc", "piece", "chiec", "chiếc"],
    "BO": ["bộ", "bo", "set"],
    "TAN": ["tấn", "tan", "ton", "tonne"],
    "M3": ["m3", "m³", "khối", "khoi"],
}


def _s(v):
    return "" if v is None else (v.strip() if isinstance(v, str) else str(v).strip())


def _date_fmt_to_strptime(fmt: str) -> str:
    return (fmt.replace("dd", "%d").replace("MM", "%m").replace("yyyy", "%Y")
            .replace("yy", "%y").replace("HH", "%H").replace("mm", "%M").replace("ss", "%S"))


def apply(value, rule: dict) -> dict:
    if not rule or not rule.get("type"):
        return {"value": value, "error": None, "warning": None}
    t = rule["type"]
    p = rule.get("params") or {}
    s = _s(value)

    if t == "trim":
        w = "đã trim khoảng trắng" if isinstance(value, str) and value != s else None
        return {"value": s, "error": None, "warning": w}
    if t == "uppercase":
        up = s.upper()
        return {"value": up, "error": None, "warning": ("đã viết HOA" if up != s else None)}
    if t == "lowercase":
        lo = s.lower()
        return {"value": lo, "error": None, "warning": ("đã viết thường" if lo != s else None)}

    if t == "normalize_uom":
        mp = p.get("map") or _DEF_UOM
        low = s.lower()
        for canon, syns in mp.items():
            if low == canon.lower() or low in [str(x).lower() for x in syns]:
                return {"value": canon, "error": None, "warning": (f"chuẩn hoá UOM '{s}'→'{canon}'" if canon != s else None)}
        return {"value": s.upper(), "error": None, "warning": f"UOM '{s}' không có trong bảng chuẩn, tạm dùng '{s.upper()}'"}

    if t == "boolean_map":
        tv = [str(x).lower() for x in (p.get("true") or ["1", "y", "yes", "true", "active", "đang dùng"])]
        fv = [str(x).lower() for x in (p.get("false") or ["0", "n", "no", "false", "inactive", "ngừng dùng"])]
        low = s.lower()
        if low in tv:
            return {"value": True, "error": None, "warning": None}
        if low in fv or low == "":
            return {"value": False, "error": None, "warning": None}
        return {"value": None, "error": f"boolean_map: '{s}' không khớp true/false", "warning": None}

    if t in ("enum_map", "lookup"):
        mp = {str(k).lower(): v for k, v in (p.get("map") or {}).items()}
        if s.lower() in mp:
            return {"value": mp[s.lower()], "error": None, "warning": None}
        if p.get("strict", True) and s != "":
            return {"value": None, "error": f"{t}: '{s}' không có trong bảng ánh xạ", "warning": None}
        return {"value": s, "error": None, "warning": (f"{t}: '{s}' không ánh xạ, giữ nguyên" if s else None)}

    if t == "date_parse":
        if s == "":
            return {"value": None, "error": None, "warning": None}
        fmt = _date_fmt_to_strptime(p.get("format", "dd/MM/yyyy"))
        try:
            return {"value": datetime.strptime(s, fmt).date().isoformat(), "error": None, "warning": None}
        except ValueError:
            return {"value": None, "error": f"date_parse: '{s}' không khớp định dạng {p.get('format', 'dd/MM/yyyy')}", "warning": None}

    if t == "number_parse":
        if s == "":
            return {"value": None, "error": None, "warning": None}
        norm = s.replace(" ", "").replace(",", ".")
        # bỏ dấu phân tách nghìn nếu có nhiều dấu chấm
        if norm.count(".") > 1:
            norm = norm.replace(".", "", norm.count(".") - 1)
        try:
            return {"value": float(norm), "error": None, "warning": None}
        except ValueError:
            return {"value": None, "error": f"number_parse: '{s}' không phải số", "warning": None}

    if t == "regex_validate":
        pat = p.get("pattern", ".*")
        if s != "" and not re.fullmatch(pat, s):
            return {"value": s, "error": f"regex_validate: '{s}' không khớp /{pat}/", "warning": None}
        return {"value": s, "error": None, "warning": None}

    if t == "default_if_empty":
        if s == "":
            dv = p.get("value", "")
            return {"value": dv, "error": None, "warning": f"dùng default '{dv}'"}
        return {"value": s, "error": None, "warning": None}

    if t == "required_if":
        if s == "":
            return {"value": s, "error": "required_if: trường bắt buộc nhưng trống", "warning": None}
        return {"value": s, "error": None, "warning": None}

    return {"value": value, "error": None, "warning": None}
