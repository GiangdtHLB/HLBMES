"""Việc cần làm — tổng hợp các mục "đang chờ xử lý" theo ĐÚNG quyền/phạm vi của tài khoản đang
đăng nhập (yêu cầu người dùng 2026-09-10: "cảnh báo có bao nhiêu công việc phải làm đối với
từng tài khoản... bấm vào đó sẽ dẫn đến chỗ cần xem").

CHỈ mang tính thông báo/điều hướng — không cấp thêm quyền gì; bấm vào 1 mục ở frontend vẫn phải
qua đúng require_perm/scope thật của API xử lý việc đó, y hệt như khi tự vào màn hình đó gõ tay.
Vì vậy các hàm dưới đây dùng bản KHÔNG raise (`_has_perm`/`has_scope`) — sai (đếm thiếu/thừa 1
mục) chỉ là lỗi hiển thị, không phải lỗ hổng bảo mật.

CỐ TÌNH KHÔNG đếm các bước duyệt của module "Nấu-Lọc-Chiết" cũ (BrewBatch/FermentRecord/
FilterRecord/BottleRecord — routers/brewing.py::approve_ferment/approve_filter/approve_bottle)
— chỉ đếm theo pipeline mới "Mẻ sản xuất" (BatchTank/BatchFilterLot/BatchPackLot) để tránh đếm
trùng 1 mẻ vật lý thành 2 việc nếu cả 2 module cùng có bước duyệt riêng trên nó (xác nhận với
người dùng: module cũ không còn là nguồn chính, xem lịch sử trao đổi 2026-09-10)."""

from sqlalchemy import false, func, or_, select, true
from sqlalchemy.orm import Session

from ..common import DeviationState, RecipeState, Role
from ..security import User, has_scope
from ..models.batch_pipeline import BatchFilterLot, BatchPackLot
from ..models.materials import MaterialLot
from ..models.quality import Deviation
from ..models.quality_ext import CAPA
from ..models.recipes import RecipeVersion
from ..models.warehouse import (MaterialRequestLine, SangNgangRequest, StockCount,
                                TransferKcPxRequest, TransferPxRequest)
from ..models.wms import FinishedGoodsUnit, Shipment, WmsLocation, WmsTransfer, WmsTransferLine, WmsWarehouse
from ..models.maintenance import Incident, MaintenancePlan
from . import qc_catalog
from . import wms as wms_svc


def _has_perm(user: User, perm: str) -> bool:
    """Mirror security.require_perm nhưng KHÔNG raise — chỉ để quyết định có đếm/hiện mục này
    cho tài khoản đang đăng nhập hay không."""
    if user.role == Role.ADMIN.value:
        return True
    perms = user.permissions
    return perms == "*" or bool(perms and perm in perms)


def get_pending_tasks(db: Session, user: User) -> list[dict]:
    items: list[dict] = []

    def add(key: str, label: str, count: int, view: str, sub: str | None = None) -> None:
        if count:
            items.append({"key": key, "label": label, "count": count, "view": view, "sub": sub})

    # ---- Kho công ty / Kho phân xưởng ----
    if _has_perm(user, "warehouse.request") and has_scope(user, "warehouse", "phan_xuong"):
        n = db.execute(select(func.count()).select_from(SangNgangRequest)
                      .where(SangNgangRequest.status == "pending")).scalar_one()
        add("sng_approve", "Xuất sang ngang chờ duyệt", n, "warehouse_px", "sangngang")

        n = db.execute(select(func.count()).select_from(TransferKcPxRequest)
                      .where(TransferKcPxRequest.status == "pending")).scalar_one()
        add("kcpx_approve", "Nhận điều chuyển từ Kho công ty chờ duyệt", n, "warehouse_px", "dieuchuyen")

    if _has_perm(user, "warehouse.issue"):
        request_ids_pending = set(db.execute(select(MaterialRequestLine.request_id)
                                             .where(MaterialRequestLine.status == "pending")).scalars().all())
        add("material_request", "Đề nghị nhận kho chờ xử lý", len(request_ids_pending), "warehouse_kc", "xtdn")

    if _has_perm(user, "warehouse.receive") and has_scope(user, "warehouse", "cong_ty"):
        n = db.execute(select(func.count()).select_from(TransferPxRequest)
                      .where(TransferPxRequest.status == "pending")).scalar_one()
        add("px_transfer_approve", "Điều chuyển Phân xưởng → Công ty chờ duyệt", n, "warehouse_kc", "dc")

    if _has_perm(user, "warehouse.count_approve"):
        rows = db.execute(select(StockCount.location).where(StockCount.status == "posted",
                                                            StockCount.approved_by.is_(None))).all()
        n = sum(1 for (loc,) in rows if not loc or has_scope(user, "warehouse",
                "phan_xuong" if "phân xưởng" in loc.lower() else "cong_ty"))
        add("stock_count_approve", "Kiểm kê định kỳ chờ duyệt", n, "warehouse_kc", "kk")

    # ---- Chất lượng ----
    if _has_perm(user, "quality.release") or user.role in (Role.QA.value, Role.OPERATOR.value):
        n = db.execute(select(func.count()).select_from(MaterialLot)
                      .where(MaterialLot.lot_type == "material", MaterialLot.status == "on_hold")).scalar_one()
        add("lot_qc", "Lô NVL chờ khai báo/duyệt chỉ tiêu", n, "quality")

    if _has_perm(user, "batch.execute") or _has_perm(user, "quality.release"):
        pending_stages = [p for p in qc_catalog.list_pending_stage_declarations(db) if p["pending"]]
        add("stage_qc", "Công đoạn chờ khai báo chỉ tiêu chất lượng", len(pending_stages), "quality")

    if _has_perm(user, "quality.deviation"):
        n = db.execute(select(func.count()).select_from(Deviation)
                      .where(Deviation.state != DeviationState.CLOSED.value)).scalar_one()
        add("deviation_open", "Deviation đang mở", n, "quality")

    capa_states = []
    if _has_perm(user, "quality.capa_approve_kcs"):
        capa_states.append("kcs_approval")
    if _has_perm(user, "quality.capa_approve_director"):
        capa_states.append("director_approval")
    if capa_states:
        n = db.execute(select(func.count()).select_from(CAPA)
                      .where(CAPA.state.in_(capa_states))).scalar_one()
        add("capa_approve", "CAPA chờ duyệt", n, "qclab")

    # ---- Mẻ sản xuất (pipeline mới) ----
    if _has_perm(user, "quality.release"):
        n = db.execute(select(func.count()).select_from(BatchPackLot)
                      .where(BatchPackLot.approved == false())).scalar_one()
        add("pack_lot_approve", "Mẻ chiết chờ duyệt KCS", n, "batchpacklots")

        n = db.execute(select(func.count()).select_from(BatchFilterLot)
                      .where(BatchFilterLot.qc_approved == false())).scalar_one()
        add("filter_lot_approve", "Lô lọc chưa duyệt KCS", n, "batchfilterlots")

    if _has_perm(user, "production.release_to_wms"):
        n = db.execute(select(func.count()).select_from(BatchPackLot)
                      .where(BatchPackLot.approved == true(), BatchPackLot.stocked == false())).scalar_one()
        add("pack_lot_release_wms", "Đã duyệt KCS, chưa nhập kho thành phẩm", n, "batchpacklots")

    if _has_perm(user, "recipe.approve"):
        n = db.execute(select(func.count()).select_from(RecipeVersion)
                      .where(RecipeVersion.state == RecipeState.REVIEW.value)).scalar_one()
        add("recipe_review", "Recipe version chờ duyệt", n, "recipeadv")

    # ---- Kho TP (WMS) ----
    if _has_perm(user, "wms.confirm_receipt"):
        n = sum(1 for e in wms_svc.list_near_expiry_entries(db, user=user) if e["can_approve"])
        add("near_expiry_approve", "Bia cận date chờ duyệt nhập kho", n, "wms", "canexpiry")

        n = sum(1 for e in wms_svc.list_consigned_entries(db, user=user) if e["can_approve"])
        add("consigned_approve", "Bia gửi chờ duyệt nhập kho", n, "wms", "consigned")

        n = sum(1 for e in wms_svc.list_factory_import_entries(db, user=user) if e["can_approve"])
        add("factory_import_approve", "Nhập từ nhà máy khác chờ duyệt", n, "wms", "factoryimport")

        disallowed = wms_svc._disallowed_location_ids(db, user)
        stmt = wms_svc._filter_loc_scope(
            select(func.count()).select_from(FinishedGoodsUnit)
            .where(FinishedGoodsUnit.source.in_(("chiet", "manual")),
                  FinishedGoodsUnit.received_confirmed_by.is_(None)),
            FinishedGoodsUnit.location_id, disallowed)
        n = db.execute(stmt).scalar_one()
        add("unit_receipt_confirm", "Đơn vị chiết/nhập tay chờ duyệt nhập kho", n, "wms", "kho")

    if _has_perm(user, "wms.confirm_shipment"):
        allowed_codes = None if (user.role == Role.ADMIN.value or user.scope_wms_warehouse == "*") \
            else user.scope_wms_warehouse
        stmt = select(func.count()).select_from(Shipment).where(Shipment.confirmed_by.is_(None))
        if allowed_codes is not None:
            disallowed_wh = set(db.execute(select(WmsWarehouse.warehouse_id)
                                          .where(WmsWarehouse.code.notin_(allowed_codes))).scalars().all())
            if disallowed_wh:
                stmt = stmt.where(or_(Shipment.warehouse_id.is_(None), Shipment.warehouse_id.notin_(disallowed_wh)))
        n = db.execute(stmt).scalar_one()
        add("shipment_confirm", "Phiếu xuất kho chưa xác nhận", n, "wms", "xuatkho")

        stmt_tr = select(func.count()).select_from(WmsTransfer).where(WmsTransfer.confirmed_by.is_(None))
        if allowed_codes is not None and disallowed_wh:
            # Mirror list_transfers: hiện phiếu nếu ĐÍCH thuộc kho mình, HOẶC ít nhất 1 dòng
            # NGUỒN thuộc kho mình, HOẶC đích chưa xác định (chưa cất) — xem docstring ở đó.
            stmt_tr = stmt_tr.where(or_(
                WmsTransfer.to_location_id.is_(None),
                WmsTransfer.to_location_id.in_(
                    select(WmsLocation.loc_id).where(WmsLocation.warehouse_id.notin_(disallowed_wh))),
                WmsTransfer.transfer_id.in_(
                    select(WmsTransferLine.transfer_id).join(
                        WmsLocation, WmsLocation.loc_id == WmsTransferLine.from_location_id)
                    .where(WmsLocation.warehouse_id.notin_(disallowed_wh)))))
        n = db.execute(stmt_tr).scalar_one()
        add("wms_transfer_confirm", "Phiếu điều chuyển kho TP chưa xác nhận", n, "wms", "dieuchuyen")

    # ---- Bảo trì ----
    if _has_perm(user, "maintenance.manage"):
        n = db.execute(select(func.count()).select_from(Incident)
                      .where(Incident.status != "resolved")).scalar_one()
        add("incident_open", "Sự cố bảo trì chưa xử lý", n, "maint", "incidents")

        n = db.execute(select(func.count()).select_from(MaintenancePlan)
                      .where(MaintenancePlan.status != "done")).scalar_one()
        add("plan_open", "Kế hoạch bảo trì chưa hoàn thành", n, "maint", "plans")

    items.sort(key=lambda x: -x["count"])
    return items
