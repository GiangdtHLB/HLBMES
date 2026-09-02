"""EBR — Hồ sơ mẻ điện tử (tài liệu §7.6).

Lắp ráp dossier step-by-step từ dữ liệu sẵn có (audit, genealogy, QC, deviation,
readings, hóa chất, BOM). E-signature yêu cầu re-authentication; khóa hồ sơ tạo
snapshot bất biến có content_hash. Sau khóa, mẻ không cho sửa (chỉ amendment).
"""

import hashlib
import json

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, utcnow
from ..errors import DomainError, PermissionError_
from ..models.audit import AuditLog
from ..models.auth import User as UserModel
from ..models.batches import BatchExecution
from ..models.brewing import BrewOrder
from ..models.process import ChemicalUsage
from ..models.quality import Deviation, QualityResult
from ..models.quality_ext import QCParameter
from ..models.signature import EBRSnapshot, Signature
from ..security import User, require_perm, verify_password
from . import bom, dispense as dispense_svc, genealogy


def _stage_for_scope(node_type: str, node_id: str) -> str:
    """Công đoạn (StageQcGroup.stage) suy từ node genealogy — mirror quy ước scope_id đã dùng ở
    services/qc_catalog.py (VD ferment/batch_tank ghép "__len_men_chinh"/"__len_men_phu"), để hồ
    sơ EBR hiện đúng công đoạn thay vì chỉ có loại node (yêu cầu người dùng 2026-09-01)."""
    if node_type in ("batch", "brew_batch"):
        return "nau"
    if node_type == "brew":
        return "nuoc_nau"
    if node_type in ("ferment", "batch_tank"):
        return node_id.rsplit("__", 1)[-1] if "__" in node_id else "len_men_chinh"
    if node_type in ("filter", "batch_filter_lot"):
        return "loc"
    if node_type in ("bottle", "batch_pack_lot"):
        return "thanh_pham"
    return node_type


def _param_names(db: Session) -> dict:
    return {p.code: p.name for p in db.execute(select(QCParameter)).scalars().all()}


def _lot_material_labels(db: Session, lot_ids: list[str]) -> dict:
    """Tên NVL thật (mã — tên) + mã lô phần mềm (MaterialLot.lot_code) theo lot_id — mirror
    genealogy._material_label, dùng để hồ sơ EBR hiện đúng nguyên liệu (VD "Malt Pilsner") VÀ
    đúng lô cụ thể nào (VD "lô 3") thay vì chỉ "Lô NVL" chung chung — nhiều lô cùng 1 nguyên
    liệu (VD nhập nhiều đợt) sẽ không phân biệt được nếu thiếu mã lô (yêu cầu người dùng
    2026-09-01)."""
    if not lot_ids:
        return {}
    from ..models.materials import MaterialLot
    lots = db.execute(select(MaterialLot).where(MaterialLot.lot_id.in_(lot_ids))).scalars().all()
    return {lot.lot_id: {"material_label": genealogy._material_label(db, lot), "lot_code": lot.lot_code}
            for lot in lots}


def assemble(db: Session, batch: BatchExecution) -> dict:
    snap = batch.recipe_snapshot or {}
    order = db.get(BrewOrder, batch.order_id)

    # Các bước thực thi (chronological) từ audit của mẻ + kết quả QC.
    steps = []
    for a in db.execute(select(AuditLog).where(AuditLog.entity_id == batch.batch_id)
                        .order_by(AuditLog.seq)).scalars().all():
        if a.action.startswith("ebr_"):   # ký/khóa là meta hồ sơ, không tính vào lõi hash
            continue
        steps.append({"seq": a.seq, "time": (a.ts.replace(tzinfo=None) if a.ts.tzinfo else a.ts).isoformat(),
                      "action": a.action, "by": a.actor, "role": a.actor_role, "reason": a.reason,
                      "detail": a.after})
    qc = [{"parameter": r.parameter, "value": r.value, "unit": r.unit, "status": r.status,
           "lower": r.lower_limit, "upper": r.upper_limit, "by": r.recorded_by,
           "time": r.recorded_at.isoformat()}
          for r in db.execute(select(QualityResult).where(
              QualityResult.scope_type == "batch", QualityResult.scope_id == batch.batch_id)
              .order_by(QualityResult.recorded_at)).scalars().all()]
    deviations = [{"code": d.deviation_code, "severity": d.severity, "reason": d.reason,
                   "state": d.state, "by": d.opened_by, "disposition": d.disposition}
                  for d in db.execute(select(Deviation).where(
                      Deviation.scope_type == "batch", Deviation.scope_id == batch.batch_id)).scalars().all()]
    chemicals = [{"stage": c.stage, "chemical": c.chemical, "quantity": c.quantity,
                  "uom": c.uom, "time": c.ts.isoformat()}
                 for c in db.execute(select(ChemicalUsage).where(
                     ChemicalUsage.batch_id == batch.batch_id)).scalars().all()]
    materials = bom.compare_batch(db, batch)
    genealogy_tree = genealogy.trace_backward(db, "batch", batch.batch_id)

    # Phần lõi dùng để hash (bất biến) — không gồm chữ ký/thời điểm sinh.
    core = {
        "batch_code": batch.batch_code,
        "order_code": order.order_code if order else None,
        "work_order_id": batch.work_order_id,
        "product_id": batch.product_id,
        "recipe": {"recipe_id": snap.get("recipe_id"), "version_no": snap.get("version_no"),
                   "base_qty": snap.get("base_qty"), "base_uom": snap.get("base_uom")},
        "planned_qty": batch.planned_qty, "actual_qty": batch.actual_qty, "uom": batch.uom,
        "state": batch.state, "quality_status": batch.quality_status,
        "start_at": batch.start_at.isoformat() if batch.start_at else None,
        "end_at": batch.end_at.isoformat() if batch.end_at else None,
        "steps": steps, "quality": qc, "deviations": deviations, "chemicals": chemicals,
        "materials": materials,
    }
    signatures = [{"meaning": s.meaning, "by": s.signed_by, "role": s.role, "reason": s.reason,
                   "hash": s.content_hash, "time": s.signed_at.isoformat()}
                  for s in db.execute(select(Signature).where(
                      Signature.scope_type == "ebr", Signature.scope_id == batch.batch_id)
                      .order_by(Signature.signed_at)).scalars().all()]
    snapshot = db.execute(select(EBRSnapshot).where(
        EBRSnapshot.batch_id == batch.batch_id).order_by(EBRSnapshot.snapshot_version.desc())
    ).scalars().first()
    return {
        "core": core, "genealogy": genealogy_tree, "signatures": signatures,
        "locked": bool(batch.ebr_locked),
        # CHỈ để hiển thị (KHÔNG đưa vào core/hash — sẽ làm sai lệch content_hash của mọi hồ sơ
        # đã khóa trước đây) — tách "materials" (core, gộp theo mã Nhóm vật tư thay thế, giữ
        # NGUYÊN để không đổi hash) thành đúng mã vật tư thật + mã lô/FIFO, xem
        # services/dispense.py::batch_dispense_summary.
        "materials_display": dispense_svc.batch_dispense_summary(db, batch.batch_id, only_dispensed=False),
        "snapshot": ({"version": snapshot.snapshot_version, "hash": snapshot.content_hash,
                      "locked_by": snapshot.locked_by, "locked_at": snapshot.locked_at.isoformat()}
                     if snapshot else None),
        "current_hash": _hash(core),
        "generated_at": utcnow().isoformat(),
    }


def _hash(core: dict) -> str:
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _reauth(db: Session, user: User, password: str) -> UserModel:
    u = db.execute(select(UserModel).where(UserModel.username == user.username)).scalar_one_or_none()
    if not u or not verify_password(password or "", u.password_hash):
        raise PermissionError_("Xác thực lại thất bại: mật khẩu không đúng (yêu cầu cho chữ ký điện tử).")
    return u


def sign(db: Session, batch: BatchExecution, user: User, password: str, meaning: str, reason: str) -> dict:
    require_perm(user, "ebr.sign")
    _reauth(db, user, password)
    if not meaning:
        raise DomainError("Phải nêu ý nghĩa chữ ký.")
    core_hash = _hash(assemble(db, batch)["core"])
    sig = Signature(sig_id=new_id(), scope_type="ebr", scope_id=batch.batch_id, meaning=meaning,
                    signed_by=user.username, role=user.role, reason=reason, content_hash=core_hash,
                    signed_at=utcnow())
    db.add(sig)
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="ebr_sign",
                 actor=user, after={"meaning": meaning, "hash": core_hash[:12]}, reason=reason)
    db.commit()
    return {"signed": True, "meaning": meaning, "hash": core_hash}


def lock(db: Session, batch: BatchExecution, user: User, password: str, reason: str) -> dict:
    require_perm(user, "ebr.approve")
    _reauth(db, user, password)
    # with_for_update(): khóa hàng ngay TRƯỚC khi check ebr_locked — tuần tự hoá đúng 2 giao dịch
    # gần như đồng thời (VD 1 người bấm khóa thủ công đúng lúc lô thành phẩm dùng mẻ này bị khóa
    # ở Chiết, kích hoạt cascade) trên DB có row-lock thật (SQL Server/Postgres — SQLite bỏ qua,
    # xem UniqueConstraint(batch_id, snapshot_version) ở models/signature.py làm backstop thứ 2,
    # 2026-09-02 audit module "Mẻ sản xuất": trước đây chỉ check-rồi-ghi kiểu Python thường, 2
    # giao dịch race đều đọc ebr_locked=False trước khi cái nào commit xong, có thể tạo 2 snapshot
    # cho cùng 1 mẻ dù docstring khẳng định không thể).
    batch = db.execute(select(BatchExecution).where(
        BatchExecution.batch_id == batch.batch_id).with_for_update()).scalar_one()
    if batch.ebr_locked:
        raise DomainError("Hồ sơ mẻ đã được khóa trước đó.")
    dossier = assemble(db, batch)
    core = dossier["core"]
    core_hash = _hash(core)
    last = db.execute(select(EBRSnapshot).where(EBRSnapshot.batch_id == batch.batch_id)
                      .order_by(EBRSnapshot.snapshot_version.desc())).scalars().first()
    ver = (last.snapshot_version + 1) if last else 1
    db.add(EBRSnapshot(snap_id=new_id(), batch_id=batch.batch_id, snapshot_version=ver,
                       content_hash=core_hash, content=core, locked_by=user.username, locked_at=utcnow()))
    batch.ebr_locked = True
    try:
        # record_audit tự flush() ngay (bắt trùng seq sớm) — chính flush đó cũng phát INSERT
        # EBRSnapshot còn đang chờ ở trên, nên IntegrityError (nếu race) nổi lên ngay TẠI ĐÂY,
        # không phải ở db.commit() bên dưới — phải bọc try/except từ chỗ này (2026-09-02, audit
        # module "Mẻ sản xuất": lần đầu chỉ bọc quanh commit() nên không bắt được).
        record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="ebr_lock",
                     actor=user, after={"version": ver, "hash": core_hash[:12]}, reason=reason)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError("Hồ sơ mẻ vừa bị khóa bởi 1 thao tác khác gần như đồng thời — tải lại để xem.")
    return {"locked": True, "snapshot_version": ver, "hash": core_hash}


# ==================== EBR neo ở lô thành phẩm (BatchPackLot, blueprint mới) ====================
# Khác assemble() ở trên (1 BatchExecution phẳng): ở đây "mẻ" thật sự là TOÀN BỘ cây genealogy
# ngược từ lô thành phẩm (lô TP -> lô lọc -> tank lên men -> mẻ nấu, có thể nhiều nhánh nếu đã
# phối/lọc lại) — gộp audit/QC/deviation của MỌI node trong cây vào 1 hồ sơ. Đường cũ
# (assemble/sign/lock ở trên, scope "batch" của BatchExecution gốc) giữ NGUYÊN, không đổi gì.
# EBRSnapshot.batch_id/Signature.scope_id được TÁI DÙNG để lưu pack_lot_id (cột không có FK
# constraint thật, mirror quy ước "cột liên kết mềm" của cả session này) — tránh phải thêm
# migration cho phần này.
def _flatten_tree(tree: dict) -> list[dict]:
    """Phẳng hoá cây genealogy (trace_backward) thành danh sách node duy nhất (dedup theo
    type+id, giữ thứ tự xuất hiện đầu tiên — gốc trước, tổ tiên xa dần sau)."""
    seen: set = set()
    out: list[dict] = []

    def walk(n: dict) -> None:
        key = (n.get("type"), n.get("id"))
        if n.get("type") and n.get("id") and key not in seen:
            seen.add(key)
            out.append(n)
        for c in n.get("children", []) or []:
            walk(c)

    walk(tree)
    return out


# Nhãn công đoạn theo loại node — CHỈ dùng cho hiển thị "Xem khác biệt" (không đưa vào core/hash
# — xem diff_pack_lot_snapshot) — "Nấu"/"Lên men"/"Lọc"/"Thành phẩm" thay vì chỉ có tên node "Mẻ
# nấu"/"Tank lên men"...
_STEP_STAGE_LABEL = {"batch": "Nấu", "batch_tank": "Lên men", "batch_filter_lot": "Lọc",
                     "batch_pack_lot": "Thành phẩm"}


def _node_audit_steps(db: Session, node_type: str, node_id: str) -> list[dict]:
    steps = []
    for a in db.execute(select(AuditLog).where(AuditLog.entity_id == node_id)
                        .order_by(AuditLog.seq)).scalars().all():
        if a.action.startswith("ebr_"):
            continue
        steps.append({"seq": a.seq, "node_type": node_type, "node_id": node_id,
                      "time": (a.ts.replace(tzinfo=None) if a.ts.tzinfo else a.ts).isoformat(),
                      "action": a.action, "by": a.actor, "role": a.actor_role, "reason": a.reason,
                      "detail": a.after})
    return steps


def _node_qc_results(db: Session, node_type: str, node_id: str) -> list[dict]:
    """QualityResult tra theo scope_id — với batch_tank (2 stage len_men_chinh/len_men_phu ghi
    trên CÙNG 1 tank), scope_id THẬT là "{tank_id}__{stage}" (qc_catalog.batch_tank_scope_id),
    KHÔNG bằng thẳng node_id (tank_id trần) — khớp đúng "==" bỏ sót toàn bộ kết quả lên men
    chính/phụ (bug xác nhận qua yêu cầu người dùng 2026-09-01: PKG-934995 có tank 01 đã ghi đủ
    2 stage nhưng EBR hiện "chưa có dữ liệu"). Khớp thêm dạng "{node_id}__%" để lấy đủ; giữ lại
    scope_id thật (không phải node_id) trong kết quả để _stage_for_scope tách đúng stage."""
    rows = db.execute(select(QualityResult).where(
        QualityResult.scope_type == node_type,
        or_(QualityResult.scope_id == node_id, QualityResult.scope_id.like(f"{node_id}\\_\\_%", escape="\\")))
        .order_by(QualityResult.recorded_at)).scalars().all()
    # sample_id + sampled_at: cần để nhóm lại thành "lần lấy mẫu" (MULTI_SAMPLE_STAGES —
    # len_men_chinh/len_men_phu) khi hiển thị trong Hồ sơ EBR (yêu cầu người dùng 2026-09-02:
    # "cũng phải chia theo group chỉ tiêu lên men chính, chỉ tiêu lên men phụ, lần lấy mẫu"),
    # mirror qc_catalog.list_qc_samples (eff_time = sampled_at hoặc recorded_at nếu NULL — stage
    # khác len_men_chinh/phu không có khái niệm "lần", sampled_at luôn NULL ở đó).
    return [{"node_type": node_type, "node_id": node_id, "scope_id": r.scope_id, "parameter": r.parameter,
             "value": r.value, "unit": r.unit, "status": r.status, "lower": r.lower_limit,
             "upper": r.upper_limit, "by": r.recorded_by, "time": r.recorded_at.isoformat(),
             "sample_id": r.sample_id, "sampled_at": (r.sampled_at or r.recorded_at).isoformat()}
            for r in rows]


def _node_deviations(db: Session, node_type: str, node_id: str) -> list[dict]:
    return [{"node_type": node_type, "node_id": node_id, "code": d.deviation_code, "severity": d.severity,
             "reason": d.reason, "state": d.state, "by": d.opened_by, "disposition": d.disposition}
            for d in db.execute(select(Deviation).where(
                Deviation.scope_type == node_type, Deviation.scope_id == node_id)).scalars().all()]


def _context_display(db: Session, filter_lot, pack_lot) -> dict:
    """Loại bia/Dịch bia/Sản phẩm chiết/Tank thành phẩm — CHỈ để hiển thị (mirror
    materials_display/quality_display, không đưa vào core/hash) vì đây là TÊN suy ra từ các id
    đã có sẵn trong core (finished_product_id) hoặc từ BatchFilterLot cha (beer_type_id/
    product_id không có trên chính BatchPackLot) — không phải dữ liệu mới cần niêm phong (yêu
    cầu người dùng 2026-09-01: hồ sơ EBR phải ghi rõ Loại bia/Dịch bia/Sản phẩm/Tank BBT)."""
    from ..models.master import BeerType, FinishedProduct, Product
    beer_type = db.get(BeerType, filter_lot.beer_type_id) if filter_lot and filter_lot.beer_type_id else None
    product = db.get(Product, filter_lot.product_id) if filter_lot and filter_lot.product_id else None
    fp = db.get(FinishedProduct, pack_lot.finished_product_id) if pack_lot.finished_product_id else None
    return {
        "beer_type_name": f"{beer_type.code} — {beer_type.name}" if beer_type else None,
        "product_name": f"{product.code} — {product.name}" if product else None,
        "finished_product_name": f"{fp.code} — {fp.name}" if fp else None,
        "tank_bbt": pack_lot.from_bbt,
    }


def _material_usage_display(rows) -> list[dict]:
    return [{"material_name": m.material_name, "lot_pm": m.lot_pm, "quantity": m.quantity,
             "uom": m.uom, "fifo_ok": m.fifo_ok, "reason": m.reason} for m in rows]


def _batch_materials_display(db: Session, nodes: list[dict]) -> list[dict]:
    """NVL dùng cho nấu — KHÁC filter_lot/pack_lot (không có bảng Usage riêng cho nấu): nguồn dữ
    liệu là DispenseLine (qua Dispense.batch_id, xem services/dispense.py) — chỉ có mã lô/FIFO
    khi tiêu thụ qua Cấp liệu (dispense/adjust); tiêu thụ qua /consume trực tiếp không suy đoán
    được FIFO (fifo_ok=None, mirror hạn chế đã ghi ở batch_dispense_summary). Gắn kèm batch_id để
    hồ sơ EBR tách theo đúng mẻ nấu (yêu cầu người dùng 2026-09-01: "Lô nguyên liệu dùng cho nấu
    thiếu mã lô PM, FIFO")."""
    from ..models.master import Material
    from ..models.materials_ext import Dispense, DispenseLine
    batch_ids = [n["id"] for n in nodes if n["type"] == "batch"]
    if not batch_ids:
        return []
    dispenses = db.execute(select(Dispense).where(Dispense.batch_id.in_(batch_ids))).scalars().all()
    dispense_batch = {d.dispense_id: d.batch_id for d in dispenses}
    if not dispense_batch:
        return []
    lines = db.execute(select(DispenseLine).where(
        DispenseLine.dispense_id.in_(dispense_batch.keys()))).scalars().all()
    mat_names = {m.code: m.name for m in db.execute(select(Material)).scalars().all()}
    return [{"batch_id": dispense_batch[l.dispense_id], "material_name": mat_names.get(l.material_code, l.material_code),
             "lot_pm": l.lot_code, "fifo_ok": l.fifo_ok, "reason": l.reason, "quantity": l.quantity, "uom": l.uom}
            for l in lines]


def _nuoc_nau_display(db: Session, nodes: list[dict]) -> list[dict]:
    """Chỉ tiêu Nước nấu bia — khai theo MÃ ĐIỀU ĐỘ (WorkOrder), không phải theo mẻ nấu/genealogy
    edge thật (WorkOrder nối Mẻ nấu qua BatchExecution.work_order_id, không qua GenealogyEdge —
    xem qc_catalog.list_pending_stage_declarations). Gom riêng theo TỪNG mã điều độ nếu lô thành
    phẩm bắt nguồn từ NHIỀU mã điều độ khác nhau — yêu cầu người dùng 2026-09-01."""
    from ..models.workorder import WorkOrder
    batch_ids = [n["id"] for n in nodes if n["type"] == "batch"]
    if not batch_ids:
        return []
    wo_ids = {b.work_order_id for b in db.execute(
        select(BatchExecution).where(BatchExecution.batch_id.in_(batch_ids))).scalars().all()
        if b.work_order_id}
    if not wo_ids:
        return []
    wos = db.execute(select(WorkOrder).where(WorkOrder.wo_id.in_(wo_ids))).scalars().all()
    param_names = _param_names(db)
    out = []
    for wo in wos:
        rows = db.execute(select(QualityResult).where(
            QualityResult.scope_type == "work_order", QualityResult.scope_id == wo.wo_id)).scalars().all()
        for r in rows:
            out.append({"work_order_id": wo.wo_id, "wo_code": wo.wo_code, "parameter": r.parameter,
                       "parameter_name": param_names.get(r.parameter, r.parameter),
                       "value": r.value, "unit": r.unit, "status": r.status})
    return out


def _tank_lm_labels(db: Session, tank_ids: list[str]) -> dict:
    """tank_lm (tên tank vật lý, VD "FV-01") theo tank_id — CHỈ hiển thị, tank_code (VD "01")
    trong core["nodes"] là số thứ tự nội bộ, không đủ rõ tank vật lý nào (yêu cầu người dùng
    2026-09-01)."""
    if not tank_ids:
        return {}
    from ..models.batch_pipeline import BatchTank
    return {t.tank_id: t.tank_lm for t in db.execute(
        select(BatchTank).where(BatchTank.tank_id.in_(tank_ids))).scalars().all()}


def assemble_pack_lot(db: Session, pack_lot_id: str) -> dict:
    from ..models.batch_pipeline import BatchFilterLot, BatchFilterLotMaterialUsage, BatchPackLot, BatchPackLotMaterialUsage
    pack_lot = db.get(BatchPackLot, pack_lot_id)
    if not pack_lot:
        raise DomainError("Lô thành phẩm không tồn tại.")
    filter_lot = db.get(BatchFilterLot, pack_lot.filter_lot_id)
    tree = genealogy.trace_backward(db, "batch_pack_lot", pack_lot_id)
    nodes = _flatten_tree(tree)
    steps: list[dict] = []
    qc: list[dict] = []
    deviations: list[dict] = []
    for n in nodes:
        steps.extend(_node_audit_steps(db, n["type"], n["id"]))
        qc.extend(_node_qc_results(db, n["type"], n["id"]))
        deviations.extend(_node_deviations(db, n["type"], n["id"]))
    steps.sort(key=lambda s: (s["time"], s["seq"]))

    core = {
        "pack_lot_code": pack_lot.pack_lot_code,
        "filter_lot_id": pack_lot.filter_lot_id,
        "qty": pack_lot.qty, "finished_product_id": pack_lot.finished_product_id,
        "lot_no": pack_lot.lot_no, "line": pack_lot.line,
        "approved": pack_lot.approved, "approved_by": pack_lot.approved_by,
        "quality_status": pack_lot.quality_status,
        "created_at": pack_lot.created_at.isoformat() if pack_lot.created_at else None,
        "nodes": [{"type": n["type"], "id": n["id"], "code": n["code"]} for n in nodes],
        "steps": steps, "quality": qc, "deviations": deviations,
    }
    signatures = [{"meaning": s.meaning, "by": s.signed_by, "role": s.role, "reason": s.reason,
                   "hash": s.content_hash, "time": s.signed_at.isoformat()}
                  for s in db.execute(select(Signature).where(
                      Signature.scope_type == "ebr", Signature.scope_id == pack_lot_id)
                      .order_by(Signature.signed_at)).scalars().all()]
    snapshot = db.execute(select(EBRSnapshot).where(
        EBRSnapshot.batch_id == pack_lot_id).order_by(EBRSnapshot.snapshot_version.desc())
    ).scalars().first()
    param_names = _param_names(db)
    material_labels = _lot_material_labels(db, [n["id"] for n in nodes if n["type"] == "lot"])
    return {
        "core": core, "genealogy": tree, "signatures": signatures,
        "locked": snapshot is not None,
        # CHỈ để hiển thị (KHÔNG đưa vào core/hash — sẽ làm sai lệch content_hash của mọi hồ sơ
        # đã khóa trước đây, mirror assemble() ở trên) — tên chỉ tiêu/công đoạn thật thay vì chỉ
        # có mã QCParameter.code, yêu cầu người dùng 2026-09-01. material_label/lot_code: tên NVL
        # thật + mã lô phần mềm của từng "Lô NVL" (node_type="lot") — trước đó chỉ hiện chung
        # chung "Lô NVL", không biết nguyên liệu gì lẫn lô nào (yêu cầu người dùng 2026-09-01).
        "quality_display": [{**q, "stage": _stage_for_scope(q["node_type"], q.get("scope_id", q["node_id"])),
                            "parameter_name": param_names.get(q["parameter"], q["parameter"]),
                            "material_label": (material_labels.get(q["node_id"]) or {}).get("material_label")
                                              if q["node_type"] == "lot" else None,
                            "lot_code": (material_labels.get(q["node_id"]) or {}).get("lot_code")
                                       if q["node_type"] == "lot" else None}
                           for q in qc],
        "context_display": _context_display(db, filter_lot, pack_lot),
        # NVL dùng thật cho lọc/chiết (BatchFilterLotMaterialUsage/BatchPackLotMaterialUsage) —
        # CHỈ hiển thị (mirror materials_display ở assemble()), hồ sơ EBR trước đây chỉ có Kết
        # quả QC, không thấy NVL đã dùng cho 2 công đoạn này (yêu cầu người dùng 2026-09-01).
        "filter_lot_materials_display": _material_usage_display(db.execute(select(BatchFilterLotMaterialUsage).where(
            BatchFilterLotMaterialUsage.filter_lot_id == pack_lot.filter_lot_id)).scalars().all()),
        "pack_lot_materials_display": _material_usage_display(db.execute(select(BatchPackLotMaterialUsage).where(
            BatchPackLotMaterialUsage.pack_lot_id == pack_lot_id)).scalars().all()),
        "batch_materials_display": _batch_materials_display(db, nodes),
        "nuoc_nau_display": _nuoc_nau_display(db, nodes),
        "tank_lm_by_id": _tank_lm_labels(db, [n["id"] for n in nodes if n["type"] == "batch_tank"]),
        "snapshot": ({"version": snapshot.snapshot_version, "hash": snapshot.content_hash,
                      "locked_by": snapshot.locked_by, "locked_at": snapshot.locked_at.isoformat()}
                     if snapshot else None),
        "current_hash": _hash(core),
        "generated_at": utcnow().isoformat(),
    }


def sign_pack_lot(db: Session, pack_lot_id: str, user: User, password: str, meaning: str, reason: str) -> dict:
    require_perm(user, "ebr.sign")
    _reauth(db, user, password)
    if not meaning:
        raise DomainError("Phải nêu ý nghĩa chữ ký.")
    core_hash = _hash(assemble_pack_lot(db, pack_lot_id)["core"])
    sig = Signature(sig_id=new_id(), scope_type="ebr", scope_id=pack_lot_id, meaning=meaning,
                    signed_by=user.username, role=user.role, reason=reason, content_hash=core_hash,
                    signed_at=utcnow())
    db.add(sig)
    record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="ebr_sign",
                 actor=user, after={"meaning": meaning, "hash": core_hash[:12]}, reason=reason)
    db.commit()
    return {"signed": True, "meaning": meaning, "hash": core_hash}


def _lock_batch_snapshot(db: Session, batch: BatchExecution, user: User, reason: str) -> None:
    """Khóa EBR RIÊNG cho 1 BatchExecution khi cascade từ khóa lô thành phẩm xuống — mirror đúng
    lock() ở trên (KHÔNG re-auth lại, vì user đã xác thực 1 lần cho cả hành động khóa lô TP) —
    để mỗi mẻ nấu trong cây cũng có EBRSnapshot/version/hash/chữ ký RIÊNG của chính nó (trước đây
    chỉ set cờ ebr_locked=True suông, GET .../batches/{id}/ebr báo "đã khóa" nhưng không có
    snapshot nào đứng tên mẻ đó — mọi bằng chứng chỉ nằm gộp trong snapshot của lô TP) — yêu cầu
    người dùng 2026-09-02: "khóa ở chiết thì mặc định khóa EBR ở mẻ sản xuất được kích hoạt để
    lấy snapshot". Bỏ qua nếu mẻ ĐÃ tự khóa riêng từ trước (giữ nguyên snapshot/version gốc,
    không ghi đè). with_for_update(): khóa hàng trước khi check — race với lock_tank() thủ công
    trên CÙNG mẻ (xem lock())."""
    batch = db.execute(select(BatchExecution).where(
        BatchExecution.batch_id == batch.batch_id).with_for_update()).scalar_one()
    if batch.ebr_locked:
        return
    core = assemble(db, batch)["core"]
    core_hash = _hash(core)
    db.add(EBRSnapshot(snap_id=new_id(), batch_id=batch.batch_id, snapshot_version=1,
                       content_hash=core_hash, content=core, locked_by=user.username, locked_at=utcnow()))
    batch.ebr_locked = True
    record_audit(db, entity_type="batch", entity_id=batch.batch_id, action="ebr_lock",
                 actor=user, after={"version": 1, "hash": core_hash[:12], "via": "cascade_from_pack_lot"},
                 reason=reason)


def _tank_fermentation_log_display(db: Session, tank_id: str) -> dict:
    """Ghi chép lên men (bảng thông tin đầu BM 1.11(06) + bảng theo ngày + mốc hạ phụ) — dữ liệu
    QUAN TRỌNG NHẤT của công đoạn Lên men, trước đây KHÔNG hề vào core (đưa vào core/hash, không
    phải "_display" thuần hiển thị như materials_display — đây là dữ liệu thật cần niêm phong,
    không phải suy diễn từ dữ liệu khác) nên hồ sơ EBR "bất biến" của tank khóa xong vẫn trống
    trơn phần này (2026-09-02, audit module "Mẻ sản xuất"). Đọc thẳng model, KHÔNG gọi
    batch_tank_log.get_or_create_process_log (sẽ INSERT+commit 1 dòng rỗng mỗi lần chỉ ĐỌC hồ sơ,
    kể cả tank chưa từng ghi gì) — tank chưa có process log nào thì trả rỗng."""
    from ..models.batch_pipeline import BatchTankDailyReading, BatchTankProcessLog
    from . import batch_tank_log
    log = db.execute(select(BatchTankProcessLog).where(
        BatchTankProcessLog.tank_id == tank_id)).scalar_one_or_none()
    readings = db.execute(select(BatchTankDailyReading).where(BatchTankDailyReading.tank_id == tank_id)
                          .order_by(BatchTankDailyReading.day_no)).scalars().all()
    return {
        "note": log.note if log else None,
        "manual": batch_tank_log.get_manual_values(log) if log else {},
        "ha_phu_events": batch_tank_log.get_ha_phu_events(log) if log else [],
        "daily_readings": [{
            "day_no": r.day_no, "reading_date": r.reading_date,
            "nhiet_do_c": r.nhiet_do_c, "do_s": r.do_s, "mat_do_tb": r.mat_do_tb,
            "measured_by": r.measured_by, "measured_at": r.measured_at.isoformat() if r.measured_at else None,
            "kcs": r.kcs, "kcs_by": r.kcs_by, "kcs_at": r.kcs_at.isoformat() if r.kcs_at else None,
            "truc_ca": r.truc_ca, "truc_ca_by": r.truc_ca_by,
            "truc_ca_at": r.truc_ca_at.isoformat() if r.truc_ca_at else None,
        } for r in readings],
    }


def _tank_core(db: Session, tank) -> dict:
    """Core EBR của 1 BatchTank — CHỈ gồm phần dữ liệu đã THẬT SỰ xong (QC lên men/audit tạo-gộp
    mẻ/deviation/ghi chép lên men) — KHÔNG gồm on_hand/volume, vì 1 tank có thể còn tiếp tục được
    rút dịch cho các lô lọc KHÁC ở nhiều đợt sau này (yêu cầu người dùng 2026-09-02: "tank lên
    men... chưa rút hết dịch... có tạo được lô lọc khác, rút tiếp được không" — CÓ, không chặn, vì
    on_hand không nằm trong core nên rút thêm không làm snapshot cũ sai lệch). Dùng chung cho cả
    lúc khóa (_lock_tank_snapshot, cần bất biến) lẫn lúc đọc live (assemble_tank, cần so hash hiện
    tại)."""
    return {
        "tank_code": tank.tank_code, "tank_lm": tank.tank_lm, "product_id": tank.product_id,
        "created_at": tank.created_at.isoformat() if tank.created_at else None,
        "steps": _node_audit_steps(db, "batch_tank", tank.tank_id),
        "quality": _node_qc_results(db, "batch_tank", tank.tank_id),
        "deviations": _node_deviations(db, "batch_tank", tank.tank_id),
        "fermentation_log": _tank_fermentation_log_display(db, tank.tank_id),
    }


def assemble_tank(db: Session, tank_id: str) -> dict:
    """Đọc hồ sơ EBR của 1 BatchTank — mirror assemble()/assemble_pack_lot() nhưng cho Tank lên
    men (yêu cầu người dùng 2026-09-02: "có bổ sung cho tôi" — nút Hồ sơ EBR cho Lên men/Lọc).
    core LUÔN dựng lại LIVE (dữ liệu hiện tại, KHÔNG gồm on_hand — xem _tank_core) để so hash với
    snapshot đã khóa (nếu có — hoặc do người phụ trách Lên men tự ký/khóa riêng NGAY sau khi
    xong công đoạn qua lock_tank(), hoặc do cascade từ khóa lô thành phẩm ở Chiết sau này qua
    _lock_tank_snapshot — cả 2 đường đều tạo ĐÚNG 1 snapshot như nhau, không xung đột)."""
    from ..models.batch_pipeline import BatchTank
    tank = db.get(BatchTank, tank_id)
    if not tank:
        raise DomainError("Tank lên men không tồn tại.")
    core = _tank_core(db, tank)
    snapshot = db.execute(select(EBRSnapshot).where(
        EBRSnapshot.batch_id == tank_id).order_by(EBRSnapshot.snapshot_version.desc())).scalars().first()
    return {
        "core": core, "locked": bool(tank.locked),
        "snapshot": ({"version": snapshot.snapshot_version, "hash": snapshot.content_hash,
                     "locked_by": snapshot.locked_by, "locked_at": snapshot.locked_at.isoformat()}
                    if snapshot else None),
        "current_hash": _hash(core), "generated_at": utcnow().isoformat(),
    }


def sign_tank(db: Session, tank_id: str, user: User, password: str, meaning: str, reason: str) -> dict:
    """Ký điện tử RIÊNG cho 1 Tank lên men — mirror sign(), cho phép người phụ trách Lên men xác
    nhận NGAY sau khi xong công đoạn, không phải đợi tới khi Chiết khóa cả chuỗi (yêu cầu người
    dùng 2026-09-02: "có cần ký" — có). Chỉ lưu hash + chữ ký, KHÔNG tạo snapshot, KHÔNG khóa gì
    — giống hệt ý nghĩa sign() ở Mẻ nấu."""
    from ..models.batch_pipeline import BatchTank
    require_perm(user, "ebr.sign")
    _reauth(db, user, password)
    if not meaning:
        raise DomainError("Phải nêu ý nghĩa chữ ký.")
    tank = db.get(BatchTank, tank_id)
    if not tank:
        raise DomainError("Tank lên men không tồn tại.")
    core_hash = _hash(_tank_core(db, tank))
    sig = Signature(sig_id=new_id(), scope_type="ebr", scope_id=tank_id, meaning=meaning,
                    signed_by=user.username, role=user.role, reason=reason, content_hash=core_hash,
                    signed_at=utcnow())
    db.add(sig)
    record_audit(db, entity_type="batch_tank", entity_id=tank_id, action="ebr_sign",
                 actor=user, after={"meaning": meaning, "hash": core_hash[:12]}, reason=reason)
    db.commit()
    return {"signed": True, "meaning": meaning, "hash": core_hash}


def lock_tank(db: Session, tank_id: str, user: User, password: str, reason: str) -> dict:
    """Phê duyệt & khóa hồ sơ RIÊNG cho 1 Tank lên men — entry point THỦ CÔNG (mirror lock()),
    dùng lại đúng _lock_tank_snapshot làm lõi (yêu cầu người dùng 2026-09-02: "có cần ký" — có).
    An toàn dùng chung với cascade từ Chiết: bên nào khóa TRƯỚC thì bên sau (dù thủ công hay
    cascade) đều tự bỏ qua, không tạo snapshot thứ 2 — chỉ khác readonly cascade ở chỗ NÀY có
    guard raise rõ ràng nếu bấm lại khi đã khóa (giống lock()/lock_pack_lot()), còn cascade chỉ
    lặng lẽ bỏ qua vì nó khóa CẢ CHUỖI, không riêng người bấm chủ động chọn tank này."""
    from ..models.batch_pipeline import BatchTank
    require_perm(user, "ebr.approve")
    _reauth(db, user, password)
    tank = db.get(BatchTank, tank_id)
    if not tank:
        raise DomainError("Tank lên men không tồn tại.")
    if tank.locked:
        raise DomainError("Hồ sơ tank đã được khóa trước đó.")
    try:
        # _lock_tank_snapshot gọi record_audit (tự flush() ngay) — IntegrityError của race (nếu
        # có) nổi lên TRONG lệnh gọi này, không phải ở db.commit() bên dưới, nên phải bọc từ đây
        # (2026-09-02, audit module "Mẻ sản xuất").
        _lock_tank_snapshot(db, tank, user, reason)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError("Hồ sơ tank vừa bị khóa bởi 1 thao tác khác gần như đồng thời — tải lại để xem.")
    snap = db.execute(select(EBRSnapshot).where(EBRSnapshot.batch_id == tank_id)
                      .order_by(EBRSnapshot.snapshot_version.desc())).scalars().first()
    return {"locked": True, "snapshot_version": snap.snapshot_version, "hash": snap.content_hash}


def _lock_tank_snapshot(db: Session, tank, user: User, reason: str) -> None:
    """Lõi tạo snapshot cho 1 BatchTank — dùng chung cho CẢ 2 đường: lock_tank() (thủ công, người
    phụ trách Lên men tự bấm) VÀ cascade từ khóa lô thành phẩm ở Chiết (mirror
    _lock_batch_snapshot). Chỉ tạo ĐÚNG 1 LẦN (bỏ qua nếu tank ĐÃ khóa từ trước theo 1 trong 2
    đường) — tránh nhân bản snapshot (yêu cầu người dùng 2026-09-02: "nhiều snapshot quá sẽ gây
    nhiễu"). with_for_update(): khóa hàng trước khi check — tuần tự hoá race giữa 2 đường (thủ
    công vs cascade) trên CÙNG tank trên DB có row-lock thật (SQL Server/Postgres — SQLite bỏ
    qua, có UniqueConstraint(batch_id, snapshot_version) làm backstop, xem models/signature.py)."""
    from ..models.batch_pipeline import BatchTank
    tank = db.execute(select(BatchTank).where(
        BatchTank.tank_id == tank.tank_id).with_for_update()).scalar_one()
    if tank.locked:
        return
    core = _tank_core(db, tank)
    core_hash = _hash(core)
    db.add(EBRSnapshot(snap_id=new_id(), batch_id=tank.tank_id, snapshot_version=1,
                       content_hash=core_hash, content=core, locked_by=user.username, locked_at=utcnow()))
    tank.locked = True
    tank.locked_by = user.username
    tank.locked_at = utcnow()
    record_audit(db, entity_type="batch_tank", entity_id=tank.tank_id, action="ebr_lock",
                 actor=user, after={"version": 1, "hash": core_hash[:12]}, reason=reason)


def _filter_lot_core(db: Session, fl) -> dict:
    """Mirror _tank_core cho BatchFilterLot — cùng lý do KHÔNG gồm on_hand/volume (1 lô lọc có
    thể còn được dùng làm nguồn "lọc lại" cho lô lọc khác, hoặc tách thêm lô thành phẩm khác sau
    này). Có thêm NVL đã dùng (BatchFilterLotMaterialUsage), khác tank (không có bảng usage
    riêng cho lên men)."""
    from ..models.batch_pipeline import BatchFilterLotMaterialUsage
    materials = db.execute(select(BatchFilterLotMaterialUsage).where(
        BatchFilterLotMaterialUsage.filter_lot_id == fl.filter_lot_id)).scalars().all()
    return {
        "filter_lot_code": fl.filter_lot_code, "to_bbt": fl.to_bbt, "product_id": fl.product_id,
        "beer_type_id": fl.beer_type_id, "created_at": fl.created_at.isoformat() if fl.created_at else None,
        "steps": _node_audit_steps(db, "batch_filter_lot", fl.filter_lot_id),
        "quality": _node_qc_results(db, "batch_filter_lot", fl.filter_lot_id),
        "deviations": _node_deviations(db, "batch_filter_lot", fl.filter_lot_id),
        "materials": _material_usage_display(materials),
    }


def assemble_filter_lot(db: Session, filter_lot_id: str) -> dict:
    """Mirror assemble_tank cho BatchFilterLot — snapshot có thể do tự ký/khóa riêng (lock_filter_lot())
    hoặc do cascade từ Chiết (yêu cầu người dùng 2026-09-02: "có cần ký" — có)."""
    from ..models.batch_pipeline import BatchFilterLot
    fl = db.get(BatchFilterLot, filter_lot_id)
    if not fl:
        raise DomainError("Lô lọc không tồn tại.")
    core = _filter_lot_core(db, fl)
    snapshot = db.execute(select(EBRSnapshot).where(
        EBRSnapshot.batch_id == filter_lot_id).order_by(EBRSnapshot.snapshot_version.desc())).scalars().first()
    return {
        "core": core, "locked": bool(fl.locked),
        "snapshot": ({"version": snapshot.snapshot_version, "hash": snapshot.content_hash,
                     "locked_by": snapshot.locked_by, "locked_at": snapshot.locked_at.isoformat()}
                    if snapshot else None),
        "current_hash": _hash(core), "generated_at": utcnow().isoformat(),
    }


def sign_filter_lot(db: Session, filter_lot_id: str, user: User, password: str, meaning: str, reason: str) -> dict:
    """Mirror sign_tank cho BatchFilterLot."""
    from ..models.batch_pipeline import BatchFilterLot
    require_perm(user, "ebr.sign")
    _reauth(db, user, password)
    if not meaning:
        raise DomainError("Phải nêu ý nghĩa chữ ký.")
    fl = db.get(BatchFilterLot, filter_lot_id)
    if not fl:
        raise DomainError("Lô lọc không tồn tại.")
    core_hash = _hash(_filter_lot_core(db, fl))
    sig = Signature(sig_id=new_id(), scope_type="ebr", scope_id=filter_lot_id, meaning=meaning,
                    signed_by=user.username, role=user.role, reason=reason, content_hash=core_hash,
                    signed_at=utcnow())
    db.add(sig)
    record_audit(db, entity_type="batch_filter_lot", entity_id=filter_lot_id, action="ebr_sign",
                 actor=user, after={"meaning": meaning, "hash": core_hash[:12]}, reason=reason)
    db.commit()
    return {"signed": True, "meaning": meaning, "hash": core_hash}


def lock_filter_lot(db: Session, filter_lot_id: str, user: User, password: str, reason: str) -> dict:
    """Mirror lock_tank cho BatchFilterLot."""
    from ..models.batch_pipeline import BatchFilterLot
    require_perm(user, "ebr.approve")
    _reauth(db, user, password)
    fl = db.get(BatchFilterLot, filter_lot_id)
    if not fl:
        raise DomainError("Lô lọc không tồn tại.")
    if fl.locked:
        raise DomainError("Hồ sơ lô lọc đã được khóa trước đó.")
    try:
        _lock_filter_lot_snapshot(db, fl, user, reason)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError("Hồ sơ lô lọc vừa bị khóa bởi 1 thao tác khác gần như đồng thời — tải lại để xem.")
    snap = db.execute(select(EBRSnapshot).where(EBRSnapshot.batch_id == filter_lot_id)
                      .order_by(EBRSnapshot.snapshot_version.desc())).scalars().first()
    return {"locked": True, "snapshot_version": snap.snapshot_version, "hash": snap.content_hash}


def _lock_filter_lot_snapshot(db: Session, fl, user: User, reason: str) -> None:
    """Lõi tạo snapshot cho 1 BatchFilterLot — dùng chung cho lock_filter_lot() (thủ công) VÀ
    cascade từ Chiết (mirror _lock_tank_snapshot). Chỉ tạo ĐÚNG 1 LẦN. with_for_update(): khóa
    hàng trước khi check — race giữa 2 đường trên CÙNG lô lọc (2026-09-02, audit module "Mẻ sản
    xuất")."""
    from ..models.batch_pipeline import BatchFilterLot
    fl = db.execute(select(BatchFilterLot).where(
        BatchFilterLot.filter_lot_id == fl.filter_lot_id).with_for_update()).scalar_one()
    if fl.locked:
        return
    core = _filter_lot_core(db, fl)
    core_hash = _hash(core)
    db.add(EBRSnapshot(snap_id=new_id(), batch_id=fl.filter_lot_id, snapshot_version=1,
                       content_hash=core_hash, content=core, locked_by=user.username, locked_at=utcnow()))
    fl.locked = True
    fl.locked_by = user.username
    fl.locked_at = utcnow()
    record_audit(db, entity_type="batch_filter_lot", entity_id=fl.filter_lot_id, action="ebr_lock",
                 actor=user, after={"version": 1, "hash": core_hash[:12]}, reason=reason)


def _cascade_lock(db: Session, nodes: list[dict], user: User, reason: str) -> list[str]:
    """Khóa BẤT BIẾN toàn bộ cây genealogy ngược của lô thành phẩm (mẻ nấu → tank lên men → lô
    lọc → lô thành phẩm) khi khóa hồ sơ EBR — trước đây lock_pack_lot CHỈ tạo EBRSnapshot, không
    đụng tới cột `.locked`/`.ebr_locked` của từng bản ghi, nên các cổng chặn sửa đã có sẵn khắp
    services/batch_pipeline.py (_assert_unlocked ở xóa/sửa SL/NVL/hoàn thành lọc...) không bao
    giờ được kích hoạt cho EBR neo ở lô thành phẩm — sửa được cả sau khi hồ sơ đã "khóa" (yêu cầu
    người dùng 2026-09-01: khóa lô TP phải khóa CẢ chuỗi từ mẻ nấu tới chiết, gồm chỉ tiêu/NVL/
    lượng dịch). Cả 4 lớp (batch/batch_tank/batch_filter_lot/batch_pack_lot) đều được cấp snapshot
    RIÊNG của chính nó khi lần đầu bị cascade chạm tới (yêu cầu người dùng 2026-09-02: "khóa ở
    chiết thì mặc định mẻ sản xuất, lên men, lọc, chiết sẽ snapshot") — batch_pack_lot (chính lô
    đang được khóa) đã có snapshot từ lock_pack_lot() ngay trước khi gọi hàm này nên ở đây chỉ cần
    set cờ; batch/batch_tank/batch_filter_lot tạo snapshot qua 3 hàm _lock_*_snapshot riêng (xem
    đó) — mỗi hàm tự bỏ qua nếu bản ghi ĐÃ khóa từ trước (dùng chung tank/lô lọc/mẻ nấu giữa
    nhiều lô thành phẩm không tạo snapshot trùng lặp). Trả về danh sách "type:id" đã khóa để ghi
    audit."""
    from ..models.batch_pipeline import BatchFilterLot, BatchPackLot, BatchTank
    model_by_type = {"batch": BatchExecution, "batch_tank": BatchTank,
                     "batch_filter_lot": BatchFilterLot, "batch_pack_lot": BatchPackLot}
    locked_refs = []
    for n in nodes:
        model = model_by_type.get(n["type"])
        if not model:
            continue
        obj = db.get(model, n["id"])
        if not obj:
            continue
        if n["type"] == "batch":
            _lock_batch_snapshot(db, obj, user, reason)
        elif n["type"] == "batch_tank":
            _lock_tank_snapshot(db, obj, user, reason)
        elif n["type"] == "batch_filter_lot":
            _lock_filter_lot_snapshot(db, obj, user, reason)
        else:
            obj.locked = True
            obj.locked_by = user.username
            obj.locked_at = utcnow()
        locked_refs.append(f"{n['type']}:{n['id']}")
    return locked_refs


def lock_pack_lot(db: Session, pack_lot_id: str, user: User, password: str, reason: str) -> dict:
    from ..models.batch_pipeline import BatchPackLot
    require_perm(user, "ebr.approve")
    _reauth(db, user, password)
    # with_for_update(): khóa hàng BatchPackLot trước khi check còn snapshot hay không — race
    # giữa 2 người cùng bấm khóa 1 lô thành phẩm gần như đồng thời (2026-09-02, audit module
    # "Mẻ sản xuất"). Race giữa cascade (từ đây) và lock_tank/lock_filter_lot thủ công trên CÙNG
    # tank/lô lọc đã tuần tự hoá riêng ở _lock_tank_snapshot/_lock_filter_lot_snapshot.
    db.execute(select(BatchPackLot).where(
        BatchPackLot.pack_lot_id == pack_lot_id).with_for_update()).scalar_one()
    last = db.execute(select(EBRSnapshot).where(EBRSnapshot.batch_id == pack_lot_id)
                      .order_by(EBRSnapshot.snapshot_version.desc())).scalars().first()
    if last:
        raise DomainError("Hồ sơ lô thành phẩm đã được khóa trước đó.")
    dossier = assemble_pack_lot(db, pack_lot_id)
    core = dossier["core"]
    core_hash = _hash(core)
    ver = 1
    db.add(EBRSnapshot(snap_id=new_id(), batch_id=pack_lot_id, snapshot_version=ver,
                       content_hash=core_hash, content=core, locked_by=user.username, locked_at=utcnow()))
    try:
        # _cascade_lock/record_audit tự flush() ngay — IntegrityError của race (nếu có, VD 1 tank
        # dùng chung đã bị khóa thủ công đúng lúc) nổi lên TRONG khối này, không phải ở
        # db.commit() (2026-09-02, audit module "Mẻ sản xuất").
        locked_refs = _cascade_lock(db, core["nodes"], user, reason)
        record_audit(db, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="ebr_lock",
                     actor=user, after={"version": ver, "hash": core_hash[:12], "locked_nodes": locked_refs}, reason=reason)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError("Hồ sơ lô thành phẩm vừa bị khóa bởi 1 thao tác khác gần như đồng thời — tải lại để xem.")
    return {"locked": True, "snapshot_version": ver, "hash": core_hash}


def _step_key(s: dict) -> tuple:
    return (s.get("seq"), s.get("time"), s.get("node_type"), s.get("node_id"), s.get("action"))


def _diff_core(old, new, path: str = "") -> list[dict]:
    """So sánh core đã khóa (snapshot.content) với core hiện tại — trả về danh sách khác biệt để
    trả lời "đã chỉnh cái gì sau khóa" thay vì chỉ báo hash lệch (yêu cầu người dùng 2026-09-01).
    "steps" (nhật ký audit gộp toàn cây) là phần hay đổi NHẤT sau khóa (mọi thao tác sửa đều ghi
    audit) — so theo (seq,time,node,action) thay vì so vị trí từng phần tử, để chỉ ra ĐÚNG bước
    nào là MỚI phát sinh sau khóa (dễ đọc hơn nhiều so với báo "danh sách đã đổi") thay vì so
    sánh sai lệch khi độ dài 2 danh sách khác nhau."""
    out: list[dict] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            out.extend(_diff_core(old.get(k), new.get(k), f"{path}.{k}" if path else k))
    elif isinstance(old, list) and isinstance(new, list):
        if old == new:
            return out
        if path == "steps":
            old_keys = {_step_key(s) for s in old}
            for s in new:
                if _step_key(s) not in old_keys:
                    out.append({"field": "steps", "kind": "step_added", "step": s})
        else:
            out.append({"field": path, "kind": "list_changed", "old": old, "new": new})
    else:
        if old != new:
            out.append({"field": path, "kind": "value_changed", "old": old, "new": new})
    return out


def diff_pack_lot_snapshot(db: Session, pack_lot_id: str) -> dict:
    """Khác biệt giữa hồ sơ đã khóa (snapshot mới nhất) và dữ liệu hiện tại — dùng khi "Toàn vẹn"
    báo "✗ KHÁC (đã chỉnh sau khóa?)" để biết CHÍNH XÁC đã chỉnh gì, ai, lúc nào, thay vì chỉ có
    2 hash không khớp không tra được lý do (yêu cầu người dùng 2026-09-01)."""
    snap = db.execute(select(EBRSnapshot).where(EBRSnapshot.batch_id == pack_lot_id)
                      .order_by(EBRSnapshot.snapshot_version.desc())).scalars().first()
    if not snap:
        raise DomainError("Hồ sơ lô thành phẩm chưa được khóa — không có gì để so sánh.")
    current_core = assemble_pack_lot(db, pack_lot_id)["core"]
    changes = _diff_core(snap.content, current_core)
    # Bổ sung "before" (giá trị TRƯỚC khi sửa, VD SL thực tế cũ) + "stage_label" (Nấu/Lên men/
    # Lọc/Thành phẩm) cho từng bước mới phát sinh — tra lại đúng dòng AuditLog gốc (entity_id +
    # seq định danh duy nhất 1 dòng) thay vì đưa thẳng vào core["steps"]/hash (core["steps"] giữ
    # NGUYÊN shape cũ để không làm sai lệch hash của mọi hồ sơ đã khóa trước đây — yêu cầu người
    # dùng 2026-09-01: "chưa rõ delete gì/sửa gì/trước-sau bao nhiêu/công đoạn nào").
    for c in changes:
        if c.get("kind") != "step_added":
            continue
        s = c["step"]
        s["stage_label"] = _STEP_STAGE_LABEL.get(s["node_type"])
        a = db.execute(select(AuditLog).where(
            AuditLog.entity_id == s["node_id"], AuditLog.seq == s["seq"])).scalar_one_or_none()
        s["before"] = a.before if a else None
    return {"snapshot_version": snap.snapshot_version, "locked_at": snap.locked_at.isoformat(),
            "matches": not changes, "changes": changes}
