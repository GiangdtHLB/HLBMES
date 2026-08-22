"""Xóa dữ liệu VẬN HÀNH (tồn) trước khi chạy thử — GIỮ NGUYÊN Danh mục.

Phạm vi xóa (đúng 6 module người dùng yêu cầu — 2026-08-01): Nấu, Lên men, Lọc,
Chiết, Kho TP (WMS), Kho công ty/phân xưởng (NVL) — gồm cả 2 bảng sổ cái dùng
chung giữa Kho công ty/phân xưởng (StockMovement, MaterialLot) và bảng truy xuất
nguồn gốc dùng chung toàn hệ thống (GenealogyEdge).

KHÔNG xóa (giữ nguyên theo yêu cầu + quyết định 2026-08-01):
  - Toàn bộ Danh mục: Material/Product/BeerType/FinishedProduct/MaterialGroup/
    MaterialAltGroup/Supplier (cũng là nơi xuất đến của Kho TP)/WmsLocation/Vehicle/UnitTypeCatalog/
    Formula/Recipe/RecipeVersion/QCParameter*/StageQcGroup/CipFormType/CipEquipment/
    ProductionLine/User/...
  - audit_log (nhật ký thao tác — có chuỗi hash, xóa sẽ vỡ chuỗi + mất lịch sử
    sửa Danh mục).
  - formula_activation_log, recipe_change (lịch sử thay đổi Danh mục, không phải
    dữ liệu sản xuất).
  - ops_setting (cấu hình vận hành, không phải dữ liệu vận hành).
  - packaging_type (Danh mục bao bì — GIỮ dòng, nhưng xem note bên dưới về
    on_hand/in_circulation).
  - Các module KHÔNG nằm trong 6 module đã nêu (WorkOrder/BatchExecution/
    ProductionOrder/ISA-88/Lập lịch/Cấp liệu/CAPA/LIMS/Bảo trì/Năng lượng...) —
    đều là tab "nav-unused", không thuộc phạm vi yêu cầu, KHÔNG đụng tới.

CHƯA xử lý (cần quyết định thêm nếu cần): PackagingType.on_hand/in_circulation
là 2 cột số tồn/lưu hành nằm ngay trên bảng Danh mục bao bì — script này KHÔNG
tự ý sửa 2 cột đó (không phải bảng riêng, sợ ảnh hưởng ngoài ý muốn). Nếu cần
đưa tồn bao bì về 0 trước khi chạy thử, làm riêng — không gộp vào đây.

QUAN TRỌNG — ĐỌC TRƯỚC KHI CHẠY:
  1. Đây là thao tác XÓA THẬT, không hoàn tác được qua ứng dụng. Phải sao lưu
     CSDL trước (đúng lệnh cho loại CSDL đang dùng — script này KHÔNG tự sao lưu).
  2. Script đọc kết nối CSDL giống hệt server đang chạy (biến môi trường
     MES_DATABASE_URL — xem backend/.env). Chạy nhầm máy sẽ xóa nhầm CSDL đó.
     Kiểm tra kỹ MES_DATABASE_URL đang trỏ đúng nơi trước khi chạy --execute.
  3. Mặc định là DRY-RUN (chỉ đếm số dòng từng bảng, KHÔNG xóa gì). Phải thêm
     --execute mới thực sự xóa, và vẫn phải gõ đúng cụm xác nhận khi được hỏi
     (trừ khi thêm --yes để bỏ qua bước hỏi — chỉ dùng khi chạy tự động có kiểm
     soát, VD script CI riêng).

Cách chạy (từ thư mục backend/, đã kích hoạt venv có đúng MES_DATABASE_URL):
    python -m app.reset_operational_data                # xem thử, không xóa
    python -m app.reset_operational_data --execute       # xóa thật (hỏi xác nhận)
    python -m app.reset_operational_data --execute --yes # xóa thật, không hỏi
"""

import argparse
import sys

from sqlalchemy import delete, func, select

from .database import SessionLocal
from .models.brewing import (
    BottleMaterialUsage,
    BottleRecord,
    BrewBatch,
    BrewMaterialUsage,
    BrewOrder,
    BrewOrderMaterialLine,
    BrewProcessLog,
    BrewProcessStep,
    BrewRecord,
    FermentBrewLink,
    FermentDailyReading,
    FermentProcessLog,
    FermentRecord,
    FilterMasterOrder,
    FilterMaterialUsage,
    FilterOrder,
    FilterOrderMaterialLine,
    FilterOrderTank,
    FilterRecord,
    MaterialReceipt,
    StageIndicator,
)
from .models.materials import GenealogyEdge, MaterialLot
from .models.packaging import PackagingMove
from .models.warehouse import (
    MaterialRequest,
    MaterialRequestLine,
    StockCount,
    StockCountLine,
    StockMovement,
)
from .models.wms import (
    ConsignedEntry,
    FinishedGoodsUnit,
    LoadSlip,
    LoadSlipLine,
    NearExpiryEntry,
    Shipment,
)

# Thứ tự XÓA — con trước cha, đã tính toán theo toàn bộ khóa ngoại thật giữa các
# bảng (kể cả tự tham chiếu như StockMovement.reversal_of, FilterRecord.source_filter_id
# — xóa gọn trong 1 câu lệnh DELETE cho cả bảng nên không cần xử lý thứ tự bên
# trong 1 bảng tự tham chiếu). KHÔNG tự ý đổi thứ tự nếu không kiểm tra lại FK.
DELETE_ORDER = [
    StageIndicator,
    GenealogyEdge,
    BrewProcessStep,
    BrewProcessLog,
    FermentBrewLink,
    FermentProcessLog,
    FermentDailyReading,
    LoadSlipLine,
    PackagingMove,
    BrewMaterialUsage,
    FilterMaterialUsage,
    BottleMaterialUsage,
    MaterialRequestLine,
    StockCountLine,
    FilterOrderTank,
    FilterOrderMaterialLine,
    BrewOrderMaterialLine,
    NearExpiryEntry,
    ConsignedEntry,
    FinishedGoodsUnit,
    LoadSlip,
    MaterialRequest,
    StockCount,
    BrewBatch,
    BottleRecord,
    FilterRecord,
    BrewRecord,
    FermentRecord,
    Shipment,
    BrewOrder,
    FilterOrder,
    FilterMasterOrder,
    StockMovement,
    MaterialLot,
    MaterialReceipt,
]


def _counts(db) -> list[tuple[str, int]]:
    out = []
    for model in DELETE_ORDER:
        n = db.execute(select(func.count()).select_from(model)).scalar_one()
        out.append((model.__tablename__, n))
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
        print("Đang đếm số dòng từng bảng (dữ liệu vận hành, TRƯỚC khi xóa)...")
        before = _counts(db)
        total = _print_counts(before)

        if total == 0:
            print("\nKhông có dữ liệu vận hành nào để xóa. Dừng.")
            return

        if not args.execute:
            print("\nDRY-RUN — chưa xóa gì. Chạy lại với --execute để xóa thật.")
            return

        if not args.yes:
            print("\n*** CẢNH BÁO: sắp XÓA THẬT toàn bộ dữ liệu vận hành liệt kê ở trên. ***")
            print("Thao tác này KHÔNG hoàn tác được qua ứng dụng. Đảm bảo đã sao lưu CSDL trước.")
            answer = input("Gõ đúng chữ  XOA DU LIEU  để xác nhận: ")
            if answer.strip() != "XOA DU LIEU":
                print("Xác nhận không khớp — hủy, không xóa gì.")
                sys.exit(1)

        print("\nĐang xóa...")
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
