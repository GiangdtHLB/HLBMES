"""Validate + lập kế hoạch import (preview). KHÔNG ghi DB ở đây.

Áp transform rule (import_rules) → ép kiểu → phân loại issue:
- kind="error": ép kiểu sai, rule lỗi, regex fail.
- kind="conflict": thiếu trường bắt buộc, thiếu/trùng khóa, vượt độ dài (chặn dòng).
- kind="warning": giá trị bị chuẩn hoá/trim, tùy chọn thiếu, update làm đổi tên/uom (không chặn).
Cột nguồn không map → raw_payload (không ALTER core).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import Base
from . import import_rules, import_targets


def _coerce(value, col):
    t = col["type"]
    if value is None:
        return None, None
    if not isinstance(value, str):
        return value, None       # rule đã trả bool/float/… → giữ nguyên
    s = value.strip()
    if s == "":
        return None, None
    try:
        if t == "int":
            return int(float(s)), None
        if t == "float":
            return float(s.replace(",", ".")), None
        if t == "bool":
            r = import_rules.apply(s, {"type": "boolean_map"})
            return (r["value"], None) if not r["error"] else (None, r["error"])
        return s, None
    except (ValueError, TypeError):
        return None, f"Không ép được kiểu {t}: '{s}'"


def build_plan(db: Session, table: str, mapping: dict, defaults: dict, key_field: str,
               rows: list, rules: dict = None) -> dict:
    schema = import_targets.target_schema(table)        # raise nếu ngoài whitelist
    cols = {c["name"]: c for c in schema["columns"]}
    if key_field not in cols:
        key_field = "code" if "code" in cols else schema["key_candidates"][0]
    mapping = {k: v for k, v in (mapping or {}).items() if k in cols and v}
    defaults = {k: v for k, v in (defaults or {}).items() if k in cols}
    rules = {k: v for k, v in (rules or {}).items() if k in cols and v}

    tbl = Base.metadata.tables[table]
    # bản ghi cũ để phát hiện update + warning đổi tên/uom
    cmp_cols = [c for c in ("name", "uom", "full_name") if c in cols]
    existing = {}
    sel_cols = [tbl.c[key_field]] + [tbl.c[c] for c in cmp_cols]
    for r in db.execute(select(*sel_cols)):
        existing[str(r[0])] = {cmp_cols[i]: r[i + 1] for i in range(len(cmp_cols))}

    items = []
    issues_all = []
    seen = {}
    ins = upd = skip = err = warn = conflict = 0

    for idx, row in enumerate(rows):
        issues = []
        data = {}
        # map + rule + coerce
        for tgt, src in mapping.items():
            raw = row.get(src, "")
            val = raw
            rule = rules.get(tgt)
            if rule:
                rr = import_rules.apply(raw, rule)
                if rr["error"]:
                    issues.append({"column": tgt, "value": str(raw), "message": rr["error"], "kind": "error"})
                if rr["warning"]:
                    issues.append({"column": tgt, "value": str(raw), "message": rr["warning"], "kind": "warning"})
                val = rr["value"]
            cv, e = _coerce(val, cols[tgt])
            if e:
                issues.append({"column": tgt, "value": str(raw), "message": e, "kind": "error"})
            else:
                data[tgt] = cv
        # defaults
        for tgt, dv in defaults.items():
            if data.get(tgt) in (None, ""):
                cv, e = _coerce(dv, cols[tgt])
                if not e:
                    data[tgt] = cv
        # raw_payload (cột nguồn dư)
        mapped_src = set(mapping.values())
        raw_extra = {s: v for s, v in row.items() if s not in mapped_src and v not in (None, "")}
        # required
        for c in schema["columns"]:
            if c["required"] and (data.get(c["name"]) in (None, "")):
                issues.append({"column": c["name"], "value": "", "message": f"Thiếu trường bắt buộc '{c['name']}'", "kind": "conflict"})
            elif (not c["required"]) and c["name"] in mapping and data.get(c["name"]) in (None, ""):
                issues.append({"column": c["name"], "value": "", "message": f"Tùy chọn '{c['name']}' trống", "kind": "warning"})
        # length
        for name, val in data.items():
            ml = cols[name].get("max_length")
            if ml and isinstance(val, str) and len(val) > ml:
                issues.append({"column": name, "value": val[:30] + "…", "message": f"Vượt độ dài tối đa {ml}", "kind": "conflict"})

        keyval = data.get(key_field)
        dup_skip = False
        if keyval in (None, ""):
            issues.append({"column": key_field, "value": "", "message": f"Thiếu khóa upsert '{key_field}'", "kind": "conflict"})
        elif str(keyval) in seen:
            issues.append({"column": key_field, "value": str(keyval), "message": f"Trùng khóa trong file (dòng {seen[str(keyval)] + 1})", "kind": "conflict"})
            dup_skip = True
        else:
            seen[str(keyval)] = idx
            # update vs insert + warning đổi giá trị
            if str(keyval) in existing:
                for cc in cmp_cols:
                    old = existing[str(keyval)].get(cc)
                    new = data.get(cc)
                    if new not in (None, "") and old is not None and str(old) != str(new):
                        issues.append({"column": cc, "value": str(new), "message": f"'{cc}' khác bản ghi hiện có ('{old}'→'{new}')", "kind": "warning"})

        blocking = [i for i in issues if i["kind"] in ("error", "conflict")]
        if dup_skip:
            action = "skip"
        elif blocking:
            action = "error"
        else:
            action = "update" if (keyval is not None and str(keyval) in existing) else "insert"

        if action == "insert":
            ins += 1
        elif action == "update":
            upd += 1
        elif action == "skip":
            skip += 1
        else:
            err += 1
        if any(i["kind"] == "warning" for i in issues) and action in ("insert", "update"):
            warn += 1
        if any(i["kind"] == "conflict" for i in issues):
            conflict += 1
        for i in issues:
            issues_all.append({"row_index": idx, **i})
        items.append({"row_index": idx, "action": action, "data": data,
                      "raw_payload": raw_extra or None, "issues": issues})

    return {
        "table": table, "key_field": key_field,
        "summary": {"total": len(rows), "insert": ins, "update": upd, "skip": skip,
                    "error": err, "warning": warn, "conflict": conflict},
        "items": items,
        "issues": issues_all,
        # tương thích ngược: 'errors' = các issue chặn (error+conflict)
        "errors": [i for i in issues_all if i["kind"] in ("error", "conflict")],
    }
