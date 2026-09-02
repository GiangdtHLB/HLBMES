"""Xóa dữ liệu VẬN HÀNH của pipeline "Mẻ sản xuất" MỚI — để test lại từ đầu (2026-08-31).

Phạm vi xóa (đúng các module người dùng chỉ ra trong sidebar "Sản xuất"):
  Điều độ (WorkOrder), Mẻ sản xuất (BatchExecution), Tank lên men (Mẻ SX) (BatchTank),
  Lệnh lọc (Mẻ SX) (BatchFilterOrder), Lô lọc (Mẻ SX) (BatchFilterLot), Lô TP (Mẻ SX)
  (BatchPackLot), Cấp liệu (Dispense — tab "nav-unused" nhưng model FK thẳng vào
  BatchExecution nên phải dọn cùng để không vỡ ràng buộc).

Cùng dọn theo (bắt buộc về mặt kỹ thuật, không phải "module" riêng nhưng FK thẳng vào
BatchExecution/BatchTank/BatchFilterLot/BatchPackLot nên phải xóa cùng, nếu không sẽ vỡ
FK/để lại rác): BatchPhaseRun (ISA-88), ProcessReading (giám sát), ChemicalUsage/YeastIssue
(chỉ xóa dòng có batch_id — KHÔNG đụng dòng batch_id=NULL, vì đó là dữ liệu không thuộc
mẻ nào), BatchYieldActual, QualityResult/Deviation/Sample (lims_sample) có scope_type
thuộc 4 loại node mới (batch/batch_tank/batch_filter_lot/batch_pack_lot — "batch" ở đây
LUÔN là BatchExecution, KHÔNG trùng với "brew"/"ferment"/"filter"/"bottle" của module
Nấu-Lọc-Chiết cũ — xem services/quality.py, routers/brewing.py), GenealogyEdge có
from_type/to_type thuộc 4 loại trên (cạnh nối MaterialLot<->batch cũng nằm trong này).

KHÔNG xóa (giữ nguyên theo đúng phạm vi người dùng chỉ ra):
  - BrewOrder ("Lệnh nấu"/"Lệnh SX") — KHÔNG nằm trong sidebar được khoanh, giữ để dispatch
    lại WorkOrder mới ngay trên các Lệnh nấu đã có. Chỉ NULL work_order_id trên các BrewRecord
    (module cũ) đang trỏ vào WorkOrder sắp xóa (cờ hiển thị lịch sử dispatch kiểu cũ, không
    còn ý nghĩa khi WorkOrder gốc đã bị xóa) — KHÔNG xóa bản thân BrewRecord.
  - Toàn bộ module Nấu-Lọc-Chiết cũ (BrewBatch/FermentRecord/FilterRecord/BottleRecord) và
    Kho/WMS — không liên quan pipeline "Mẻ SX".
  - Danh mục (ProductionLine/Product/Recipe*/QCParameter*/ProcessParameter*/...), audit_log.
  - MaterialLot (Danh mục lô NVL thật) — CHỈ hoàn lại `quantity` đã bị trừ do mẻ tiêu thụ
    (consume_lot/dispense), không xóa lô. Lô OUTPUT do produce_lot tạo ra (nếu có) bị xóa
    cùng mẻ trừ khi đã bị tiêu thụ tiếp ở nơi khác — script DỪNG và báo lỗi nếu gặp trường
    hợp này (an toàn hơn xóa nhầm, xem Bước 1).

QUAN TRỌNG — ĐỌC TRƯỚC KHI CHẠY (giống hệt quy ước reset_operational_data.py):
  1. Đây là thao tác XÓA THẬT, không hoàn tác được qua ứng dụng. Phải sao lưu CSDL trước.
  2. Script đọc kết nối CSDL giống hệt server đang chạy (MES_DATABASE_URL). Kiểm tra kỹ
     trước khi chạy --execute.
  3. Mặc định DRY-RUN. Phải thêm --execute mới xóa thật, vẫn phải gõ đúng cụm xác nhận
     (trừ khi thêm --yes).

Cách chạy (từ thư mục backend/, đã kích hoạt venv có đúng MES_DATABASE_URL):
    python -m app.reset_batch_pipeline_data                # xem thử, không xóa
    python -m app.reset_batch_pipeline_data --execute       # xóa thật (hỏi xác nhận)
    python -m app.reset_batch_pipeline_data --execute --yes # xóa thật, không hỏi
"""

import argparse
import sys

from sqlalchemy import delete, func, or_, select, update

from .database import SessionLocal
from .common import LotStatus
from .models.batches import BatchExecution
from .models.batch_pipeline import (
    BatchFilterLot,
    BatchFilterLotBatch,
    BatchFilterLotBatchDraw,
    BatchFilterLotSource,
    BatchFilterOrder,
    BatchFilterOrderSource,
    BatchPackLot,
    BatchPackLotMaterialUsage,
    BatchTank,
    BatchTankDailyReading,
    BatchTankLink,
    BatchTankProcessLog,
)
from .models.brewing import BrewRecord
from .models.isa88 import BatchPhaseRun
from .models.materials import GenealogyEdge, MaterialLot
from .models.materials_ext import Dispense, DispenseLine
from .models.metrics import ProcessReading
from .models.process import ChemicalUsage, YeastIssue
from .models.quality import Deviation, QualityResult
from .models.quality_ext import Sample
from .models.recipe_ext import BatchYieldActual
from .models.workorder import WorkOrder

# "batch" ở đây LUÔN là BatchExecution (pipeline mới) — module Nấu-Lọc-Chiết cũ dùng
# scope_type/genealogy type riêng ("brew_batch"/"brew"/"ferment"/"filter"/"bottle" — xem
# services/genealogy.py::NODE_REGISTRY), không đụng nhau.
NEW_PIPELINE_TYPES = ("batch", "batch_tank", "batch_filter_lot", "batch_pack_lot")
# Người dùng đã xác nhận xóa CẢ module Nấu-Lọc-Chiết cũ (chạy cùng reset_operational_data.py
# — script đó xóa BrewBatch/FermentRecord/FilterRecord/BottleRecord/BrewRecord/BrewOrder/
# FilterOrder nhưng KHÔNG dọn QualityResult/Deviation/lims_sample/genealogy_edge theo scope
# cũ — dọn nốt phần đó ở đây luôn cho sạch, không để rác mồ côi).
OLD_PIPELINE_TYPES = ("brew_batch", "brew", "ferment", "filter", "bottle")
NEW_PIPELINE_TYPES = NEW_PIPELINE_TYPES + OLD_PIPELINE_TYPES

# Thứ tự XÓA — con trước cha theo đúng FK thật giữa các bảng (xem models/batch_pipeline.py,
# models/isa88.py, models/metrics.py, models/materials_ext.py, models/process.py,
# models/recipe_ext.py). ChemicalUsage/YeastIssue KHÔNG nằm trong list này — xóa CÓ ĐIỀU
# KIỆN (chỉ dòng batch_id NOT NULL) ở hàm _delete_scoped_batch_children riêng bên dưới.
DELETE_ORDER = [
    BatchTankDailyReading,
    BatchTankProcessLog,
    BatchPackLotMaterialUsage,
    BatchPackLot,
    BatchFilterLotBatchDraw,
    BatchFilterLotBatch,
    BatchFilterLotSource,
    BatchFilterLot,
    BatchFilterOrderSource,
    BatchFilterOrder,
    BatchTankLink,
    BatchTank,
    BatchPhaseRun,
    ProcessReading,
    DispenseLine,
    Dispense,
    BatchYieldActual,
    BatchExecution,
    WorkOrder,
]


def _restore_material_lots(db) -> list[str]:
    """Bước 1 (BẮT BUỘC chạy TRƯỚC mọi lệnh xóa): hoàn lại quantity cho các MaterialLot đã bị
    trừ do mẻ tiêu thụ (consume_lot/dispense đều tạo genealogy edge from_type=lot,to_type=batch
    — xem services/batches.py::delete_batch, đây là mirror ĐÚNG logic đó nhưng áp dụng cho
    TOÀN BỘ mẻ sắp xóa cùng lúc, không phải từng mẻ một).

    Trả về list cảnh báo (nếu có lô OUTPUT do produce_lot tạo ra mà đã bị tiêu thụ tiếp ở nơi
    khác — KHÔNG tự xóa lô đó, để người dùng tự kiểm tra bằng tay)."""
    warnings: list[str] = []

    consumed_edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.from_type == "lot", GenealogyEdge.to_type == "batch")).scalars().all()
    for edge in consumed_edges:
        lot = db.get(MaterialLot, edge.from_id)
        if lot and edge.quantity:
            lot.quantity = round(lot.quantity + edge.quantity, 6)
            if lot.status == LotStatus.CONSUMED.value:
                lot.status = LotStatus.AVAILABLE.value

    produced_edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.from_type == "batch", GenealogyEdge.to_type == "lot")).scalars().all()
    for edge in produced_edges:
        consumed_further = db.execute(select(GenealogyEdge.edge_id).where(
            GenealogyEdge.from_type == "lot", GenealogyEdge.from_id == edge.to_id)).first()
        if consumed_further:
            warnings.append(
                f"Lô '{edge.to_id}' do mẻ '{edge.from_id}' sản xuất đã được dùng tiếp ở nơi khác "
                "— KHÔNG tự xóa, kiểm tra tay trước khi chạy lại.")
            continue
        lot = db.get(MaterialLot, edge.to_id)
        if lot:
            db.delete(lot)

    return warnings


def _counts(db) -> list[tuple[str, int]]:
    out = []
    for model in DELETE_ORDER:
        n = db.execute(select(func.count()).select_from(model)).scalar_one()
        out.append((model.__tablename__, n))
    out.append(("chemical_usage (có mẻ)", db.execute(
        select(func.count()).select_from(ChemicalUsage).where(ChemicalUsage.batch_id.isnot(None))).scalar_one()))
    out.append(("yeast_issue (có mẻ)", db.execute(
        select(func.count()).select_from(YeastIssue).where(YeastIssue.batch_id.isnot(None))).scalar_one()))
    out.append(("quality_result (pipeline mới)", db.execute(
        select(func.count()).select_from(QualityResult).where(
            QualityResult.scope_type.in_(NEW_PIPELINE_TYPES))).scalar_one()))
    out.append(("deviation (pipeline mới)", db.execute(
        select(func.count()).select_from(Deviation).where(
            Deviation.scope_type.in_(NEW_PIPELINE_TYPES))).scalar_one()))
    out.append(("lims_sample (pipeline mới)", db.execute(
        select(func.count()).select_from(Sample).where(
            Sample.scope_type.in_(NEW_PIPELINE_TYPES))).scalar_one()))
    out.append(("genealogy_edge (pipeline mới)", db.execute(
        select(func.count()).select_from(GenealogyEdge).where(or_(
            GenealogyEdge.from_type.in_(NEW_PIPELINE_TYPES),
            GenealogyEdge.to_type.in_(NEW_PIPELINE_TYPES)))).scalar_one()))
    return out


def _print_counts(rows: list[tuple[str, int]]) -> int:
    total = 0
    for name, n in rows:
        print(f"  {name:<32} {n:>8}")
        total += n
    print(f"  {'TỔNG':<32} {total:>8}")
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="Thực sự xóa (mặc định chỉ xem thử/đếm số dòng).")
    ap.add_argument("--yes", action="store_true", help="Bỏ qua bước gõ xác nhận (chỉ dùng khi chạy tự động có kiểm soát).")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        print("Đang đếm số dòng từng bảng (pipeline Mẻ sản xuất, TRƯỚC khi xóa)...")
        before = _counts(db)
        total = _print_counts(before)

        if total == 0:
            print("\nKhông có dữ liệu nào để xóa. Dừng.")
            return

        if not args.execute:
            print("\nDRY-RUN — chưa xóa gì. Chạy lại với --execute để xóa thật.")
            return

        if not args.yes:
            print("\n*** CẢNH BÁO: sắp XÓA THẬT toàn bộ dữ liệu pipeline Mẻ sản xuất liệt kê ở trên. ***")
            print("Lệnh nấu (BrewOrder) và mọi Danh mục KHÔNG bị đụng tới.")
            print("Thao tác này KHÔNG hoàn tác được qua ứng dụng. Đảm bảo đã sao lưu CSDL trước.")
            answer = input("Gõ đúng chữ  XOA DU LIEU  để xác nhận: ")
            if answer.strip() != "XOA DU LIEU":
                print("Xác nhận không khớp — hủy, không xóa gì.")
                sys.exit(1)

        print("\nĐang hoàn lại tồn NVL đã bị trừ do mẻ tiêu thụ (Bước 1)...")
        warnings = _restore_material_lots(db)
        for w in warnings:
            print(f"  !! CẢNH BÁO: {w}")
        if warnings:
            print("\nCó cảnh báo ở trên — DỪNG, chưa xóa gì. Kiểm tra tay rồi chạy lại.")
            db.rollback()
            sys.exit(1)

        print("\nĐang gỡ liên kết BrewRecord.work_order_id (giữ nguyên BrewRecord, chỉ NULL cột này)...")
        r = db.execute(update(BrewRecord).where(BrewRecord.work_order_id.isnot(None))
                      .values(work_order_id=None))
        print(f"  brew_record.work_order_id đã NULL: {r.rowcount}")

        print("\nĐang xóa các bảng scope-tự-do (quality_result/deviation/lims_sample/genealogy_edge)...")
        for label, model, col in (
            ("quality_result", QualityResult, QualityResult.scope_type),
            ("deviation", Deviation, Deviation.scope_type),
            ("lims_sample", Sample, Sample.scope_type),
        ):
            res = db.execute(delete(model).where(col.in_(NEW_PIPELINE_TYPES)))
            print(f"  {label:<32} đã xóa {res.rowcount}")
        res = db.execute(delete(GenealogyEdge).where(or_(
            GenealogyEdge.from_type.in_(NEW_PIPELINE_TYPES), GenealogyEdge.to_type.in_(NEW_PIPELINE_TYPES))))
        print(f"  {'genealogy_edge':<32} đã xóa {res.rowcount}")

        print("\nĐang xóa chemical_usage/yeast_issue (chỉ dòng có gắn mẻ)...")
        res = db.execute(delete(ChemicalUsage).where(ChemicalUsage.batch_id.isnot(None)))
        print(f"  {'chemical_usage (có mẻ)':<32} đã xóa {res.rowcount}")
        res = db.execute(delete(YeastIssue).where(YeastIssue.batch_id.isnot(None)))
        print(f"  {'yeast_issue (có mẻ)':<32} đã xóa {res.rowcount}")

        print("\nĐang xóa theo thứ tự con->cha...")
        for model in DELETE_ORDER:
            result = db.execute(delete(model))
            print(f"  {model.__tablename__:<32} đã xóa {result.rowcount}")
        db.commit()
        print("\nĐã commit. Đếm lại để xác nhận:")
        _print_counts(_counts(db))
    except Exception:
        db.rollback()
        print("\nCÓ LỖI — đã rollback, KHÔNG có gì bị xóa. Chi tiết lỗi:", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
