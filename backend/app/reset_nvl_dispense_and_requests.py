"""Hoàn tác toàn bộ "Cấp liệu" (Dispense), "Đề nghị nhận kho" đã fulfilled, "Xuất tự do" (kể cả
NVL dùng cho Lọc/Chiết) và "Điều chuyển sang nhà máy khác" — đưa NVL về đúng hiện trạng thật
(2026-09-14).

Phạm vi (yêu cầu người dùng): dữ liệu vận hành NVL trên server thật đã bị làm bẩn bởi 1 đợt
test/demo lớn — trong khi hiện trạng ĐÚNG chỉ nên có "Nhập tồn đầu" và "Xuất sang ngang" đã thật
sự xảy ra. Người dùng xác nhận (2026-09-14) cả "Xuất tự do"/"Điều chuyển sang nhà máy khác" cũng
thuộc diện chưa thật sự xảy ra, hoàn tác luôn.

Hoàn tác (4 bước, THỨ TỰ BẮT BUỘC — xem Bước 2):
  1. Mọi Dispense/DispenseLine (mode dispense/backflush/adjust) của MỌI BatchExecution — hoàn lại
     quantity cho MaterialLot đã bị trừ (mirror _restore_material_lots() ở
     reset_batch_pipeline_data.py), xóa cạnh GenealogyEdge(relation=consume).
  2. Mọi MaterialRequestLine.status=="fulfilled" — chuyển lô đã xuất VỀ LẠI Kho công ty (gọi
     services/warehouse.py::transfer(), mirror đúng undo_fulfill_line() nhưng chạy hàng loạt),
     đưa dòng về status="pending".
  3. Mọi StockMovement mode="tu_do" gắn với 1 dòng BatchFilterLotMaterialUsage/
     BatchPackLotMaterialUsage (NVL dùng cho Lọc/Chiết) — gọi đúng
     batch_pipeline.delete_filter_lot_material()/delete_pack_lot_material() (tự hoàn kho + xóa
     dòng NVL đã dùng), mirror thao tác "Xóa" người dùng tự bấm trên từng dòng.
  4. Mọi StockMovement mode="tu_do" CÒN LẠI (không gắn Lọc/Chiết — "Xuất tự do" thuần từ tab Kho
     phân xưởng → Xuất tự do) và mode="dieu_chuyen_nha_may" — gọi
     services/warehouse.py::undo_issue() (mirror nút "Hoàn lại"/"Hoàn tác" tương ứng).
  5. Mọi TransferPxRequest.status=="approved" (Điều chuyển Kho phân xưởng → Kho công ty) — gọi
     services/warehouse.py::undo_transfer_px_request() (mirror nút "Hoàn tác" tương ứng).

GIỮ NGUYÊN — script này KHÔNG động tới:
  - MaterialLot từ "Nhập tồn đầu" (không xóa lô, không đổi quantity ngoài việc hoàn ở các bước).
  - SangNgangRequest / StockMovement mode="sang_ngang".
  - BatchExecution và mọi dữ liệu quy trình/QC của mẻ (mẻ vẫn còn nguyên, chỉ "đã cấp gì" bị xóa).
  - StockMovement mode="dieu_chuyen_kcpx"/"tra_ncc" — CHƯA được người dùng xác nhận.
  - Danh mục, audit_log.

Bước 0 (BẮT BUỘC chạy trước, kể cả dry-run) — kiểm tra bất thường: đếm StockMovement mode
"dieu_chuyen_kcpx"/"tra_ncc" (Điều chuyển Kho công ty → Phân xưởng qua đề nghị, Trả NCC) — nếu
có, IN RA rồi DỪNG, không tự ý xử lý (phạm vi những loại này chưa được xác nhận).

QUAN TRỌNG — ĐỌC TRƯỚC KHI CHẠY (giống hệt quy ước reset_operational_data.py):
  1. Đây là thao tác SỬA DỮ LIỆU THẬT (không xóa mẻ, không xóa lô, nhưng trừ/cộng quantity + xóa
     lịch sử Cấp liệu/Đề nghị đã fulfilled/Xuất tự do/Điều chuyển nhà máy khác) — không hoàn tác
     được qua ứng dụng. Sao lưu CSDL trước.
  2. Script đọc kết nối CSDL giống hệt server đang chạy (MES_DATABASE_URL). Kiểm tra kỹ trước khi
     chạy --execute — chạy nhầm máy sẽ sửa nhầm CSDL đó.
  3. Mặc định DRY-RUN (chỉ đếm/tính toán, KHÔNG ghi gì). Phải thêm --execute mới sửa thật, vẫn
     phải gõ đúng cụm xác nhận (trừ khi thêm --yes).

Cách chạy (từ thư mục backend/, đã kích hoạt venv có đúng MES_DATABASE_URL):
    python -m app.reset_nvl_dispense_and_requests                # xem thử, không sửa
    python -m app.reset_nvl_dispense_and_requests --execute       # sửa thật (hỏi xác nhận)
    python -m app.reset_nvl_dispense_and_requests --execute --yes # sửa thật, không hỏi
"""

import argparse
import sys

from sqlalchemy import delete, func, select

from .common import LotStatus, Role
from .database import SessionLocal
from .errors import DomainError, NotFoundError
from .models.batch_pipeline import (
    BatchFilterLot,
    BatchFilterLotMaterialUsage,
    BatchPackLot,
    BatchPackLotMaterialUsage,
)
from .models.materials import GenealogyEdge, MaterialLot
from .models.materials_ext import Dispense, DispenseLine
from .models.warehouse import MaterialRequestLine, StockMovement, TransferPxRequest
from .security import User
from .services import batch_pipeline as batch_pipeline_svc
from .services import warehouse as warehouse_svc

# StockMovement mode CHƯA được người dùng xác nhận thuộc phạm vi hoàn tác — nếu có phát sinh,
# phải hỏi lại trước khi xử lý, không tự đoán (2026-09-14: đã xác nhận thêm tu_do/
# dieu_chuyen_nha_may/dieu_chuyen vào phạm vi, CHỈ còn 2 loại dưới đây là chưa xác nhận).
UNCONFIRMED_MODES = ("dieu_chuyen_kcpx", "tra_ncc")

SYSTEM_USER = User(username="system_reset", role=Role.ADMIN.value, full_name="Script hoàn tác dữ liệu")


def _check_unconfirmed_modes(db) -> list[str]:
    warnings = []
    for mode in UNCONFIRMED_MODES:
        n = db.execute(select(func.count()).select_from(StockMovement)
                       .where(StockMovement.mode == mode)).scalar_one()
        if n:
            warnings.append(f'StockMovement mode="{mode}": {n} dòng — CHƯA được xác nhận trong '
                            "phạm vi hoàn tác lần này.")
    return warnings


def _restore_dispensed_lots(db) -> tuple[int, int, float]:
    """Bước 1: hoàn lại quantity cho lô đã bị Cấp liệu trừ + xóa cạnh consume + xóa Dispense/
    DispenseLine. Trả về (số cạnh consume đã hoàn, số phiếu Dispense đã xóa, tổng SL đã hoàn)."""
    consumed_edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.from_type == "lot", GenealogyEdge.to_type == "batch",
        GenealogyEdge.relation == "consume")).scalars().all()
    total_qty = 0.0
    for edge in consumed_edges:
        lot = db.get(MaterialLot, edge.from_id)
        if lot and edge.quantity:
            lot.quantity = round(lot.quantity + edge.quantity, 6)
            total_qty += edge.quantity
            if lot.status == LotStatus.CONSUMED.value:
                lot.status = LotStatus.AVAILABLE.value
        db.delete(edge)
    db.flush()

    dispense_ids = db.execute(select(Dispense.dispense_id)).scalars().all()
    if dispense_ids:
        db.execute(delete(DispenseLine).where(DispenseLine.dispense_id.in_(dispense_ids)))
        db.execute(delete(Dispense))
    db.flush()
    return len(consumed_edges), len(dispense_ids), round(total_qty, 3)


def _undo_fulfilled_requests(db) -> tuple[int, list[str]]:
    """Bước 2: chuyển lô đã fulfilled về lại Kho công ty (mirror undo_fulfill_line, chạy hàng
    loạt). Trả về (số dòng đã hoàn tác, list lỗi nếu có dòng không hoàn tác được)."""
    lines = db.execute(select(MaterialRequestLine).where(
        MaterialRequestLine.status == "fulfilled")).scalars().all()
    errors = []
    done = 0
    for line in lines:
        try:
            warehouse_svc.transfer(
                db, line.fulfilled_lot_id, line.fulfilled_qty, "Kho công ty", SYSTEM_USER,
                mode="dieu_chuyen",
                reason=f"Hoàn tác hàng loạt (reset dữ liệu test 2026-09-14) — phiếu {line.request_id}")
        except DomainError as e:
            errors.append(f"Dòng {line.line_id} (request {line.request_id}): {e}")
            continue
        line.status = "pending"
        line.fulfilled_lot_id = None
        line.fulfilled_qty = None
        line.fulfilled_by = None
        line.fulfilled_at = None
        line.fifo_ok = None
        done += 1
    return done, errors


def _undo_filter_pack_material_usage(db) -> tuple[int, int, list[str]]:
    """Bước 3: xóa NVL đã dùng cho Lọc/Chiết (mỗi dòng tự hoàn kho qua undo_issue bên trong).
    Nếu hồ sơ (BatchFilterLot/BatchPackLot) chứa dòng đó đã khóa (EBR), MỞ KHÓA TẠM đúng hồ sơ
    đó trước khi xóa (yêu cầu người dùng 2026-09-14: "Mở khóa tạm 2 hồ sơ này để hoàn tác, rồi
    thôi" — không tự khóa lại sau, vì đây là dữ liệu test đang được dọn sạch, không phải hồ sơ
    thật cần giữ nguyên trạng thái khóa). Trả về (số dòng Lọc đã xóa, số dòng Chiết đã xóa, list
    lỗi — chỉ còn lỗi THẬT SỰ không lường trước, không còn lỗi "đã khóa")."""
    errors = []
    unlocked: list[str] = []

    filter_usages = db.execute(select(BatchFilterLotMaterialUsage)).scalars().all()
    n_filter = 0
    for u in filter_usages:
        fl = db.get(BatchFilterLot, u.filter_lot_id)
        if fl and fl.locked:
            fl.locked = False
            unlocked.append(f"Lô lọc {fl.filter_lot_code}")
        try:
            batch_pipeline_svc.delete_filter_lot_material(db, u.usage_id, SYSTEM_USER)
            n_filter += 1
        except DomainError as e:
            errors.append(f"NVL lô lọc {u.usage_id}: {e}")

    pack_usages = db.execute(select(BatchPackLotMaterialUsage)).scalars().all()
    n_pack = 0
    for u in pack_usages:
        p = db.get(BatchPackLot, u.pack_lot_id)
        if p and p.locked:
            p.locked = False
            unlocked.append(f"Lô thành phẩm {p.pack_lot_code}")
        try:
            batch_pipeline_svc.delete_pack_lot_material(db, u.usage_id, SYSTEM_USER)
            n_pack += 1
        except DomainError as e:
            errors.append(f"NVL lô thành phẩm {u.usage_id}: {e}")

    for label in unlocked:
        print(f"  (đã mở khóa tạm: {label})")
    return n_filter, n_pack, errors


def _undo_free_issue_and_factory_transfer(db) -> tuple[int, list[str]]:
    """Bước 4: hoàn lại các StockMovement mode="tu_do" CÒN LẠI (không gắn Lọc/Chiết — đã xử lý ở
    Bước 3) và mode="dieu_chuyen_nha_may", qua undo_issue() (mirror nút Hoàn lại/Hoàn tác)."""
    linked_movement_ids = set(db.execute(select(BatchFilterLotMaterialUsage.movement_id)
                                         .where(BatchFilterLotMaterialUsage.movement_id.isnot(None))).scalars().all())
    linked_movement_ids |= set(db.execute(select(BatchPackLotMaterialUsage.movement_id)
                                          .where(BatchPackLotMaterialUsage.movement_id.isnot(None))).scalars().all())

    movements = db.execute(select(StockMovement).where(
        StockMovement.mode.in_(("tu_do", "dieu_chuyen_nha_may")),
        StockMovement.reversed.is_(False))).scalars().all()
    errors = []
    done = 0
    for mv in movements:
        if mv.mode == "tu_do" and mv.movement_id in linked_movement_ids:
            continue  # đã xử lý ở Bước 3 (mirror delete_filter_lot_material/delete_pack_lot_material)
        try:
            warehouse_svc.undo_issue(db, mv.movement_id, SYSTEM_USER, strict=True, skip_perm_check=True)
            done += 1
        except DomainError as e:
            errors.append(f"StockMovement {mv.movement_id} (mode={mv.mode}): {e}")
    return done, errors


def _undo_px_transfers(db) -> tuple[int, int, list[str]]:
    """Bước 5: hoàn tác Điều chuyển Kho phân xưởng → Kho công ty đã duyệt (mirror nút "Hoàn tác"
    ở màn Kho phân xưởng → Điều chuyển). Một số phiếu "approved" trên dev là rác test cũ — lô VÀ
    giao dịch gốc mà phiếu tham chiếu đã không còn tồn tại (do các lần reset dữ liệu test trước
    đó trong phiên này đã xóa lô/giao dịch nhưng không đụng tới phiếu điều chuyển). Với đúng
    trường hợp đó (không còn gì để hoàn kho), chỉ reset trạng thái phiếu về "pending" thay vì gọi
    transfer(). Trả về (số phiếu hoàn tác thật qua transfer(), số phiếu rác chỉ reset trạng thái,
    list lỗi thật sự không lường trước)."""
    reqs = db.execute(select(TransferPxRequest).where(
        TransferPxRequest.status == "approved")).scalars().all()
    errors = []
    done = 0
    orphaned = 0
    for req in reqs:
        try:
            warehouse_svc.undo_transfer_px_request(db, req.request_id, SYSTEM_USER)
            done += 1
            continue
        except NotFoundError:
            pass
        except DomainError as e:
            errors.append(f"TransferPxRequest {req.request_id}: {e}")
            continue

        mv = db.get(StockMovement, req.movement_id) if req.movement_id else None
        lot_id_to_check = mv.lot_id if mv else req.lot_id
        if db.get(MaterialLot, req.lot_id) is not None or db.get(MaterialLot, lot_id_to_check) is not None:
            errors.append(f"TransferPxRequest {req.request_id}: lô không tồn tại (nguyên nhân "
                          "khác chưa rõ, cần kiểm tra tay).")
            continue

        print(f"  (phiếu {req.request_code} tham chiếu lô/giao dịch đã không còn — rác test dev cũ, "
              "chỉ reset trạng thái về 'pending', không có gì để hoàn kho)")
        req.status = "pending"
        req.approved_by = None
        req.approved_at = None
        req.movement_id = None
        req.reversed = True
        orphaned += 1
    return done, orphaned, errors


def _summary(db) -> None:
    remaining_fulfilled = db.execute(select(func.count()).select_from(MaterialRequestLine)
                                     .where(MaterialRequestLine.status == "fulfilled")).scalar_one()
    remaining_dispense = db.execute(select(func.count()).select_from(Dispense)).scalar_one()
    remaining_consume_edges = db.execute(select(func.count()).select_from(GenealogyEdge)
                                         .where(GenealogyEdge.relation == "consume",
                                                GenealogyEdge.to_type == "batch")).scalar_one()
    remaining_filter_usage = db.execute(select(func.count()).select_from(BatchFilterLotMaterialUsage)).scalar_one()
    remaining_pack_usage = db.execute(select(func.count()).select_from(BatchPackLotMaterialUsage)).scalar_one()
    remaining_tu_do = db.execute(select(func.count()).select_from(StockMovement).where(
        StockMovement.mode.in_(("tu_do", "dieu_chuyen_nha_may")), StockMovement.reversed.is_(False))).scalar_one()
    remaining_px_transfer = db.execute(select(func.count()).select_from(TransferPxRequest)
                                       .where(TransferPxRequest.status == "approved")).scalar_one()
    print(f"  material_request_line còn 'fulfilled':      {remaining_fulfilled}")
    print(f"  dispense còn lại:                           {remaining_dispense}")
    print(f"  genealogy_edge (consume->batch) còn:        {remaining_consume_edges}")
    print(f"  NVL dùng cho lô lọc còn lại:                 {remaining_filter_usage}")
    print(f"  NVL dùng cho lô thành phẩm còn lại:           {remaining_pack_usage}")
    print(f"  tu_do/dieu_chuyen_nha_may chưa hoàn:          {remaining_tu_do}")
    print(f"  TransferPxRequest còn 'approved':            {remaining_px_transfer}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="Thực sự sửa (mặc định chỉ xem thử).")
    ap.add_argument("--yes", action="store_true", help="Bỏ qua bước gõ xác nhận.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        print("Bước 0 — kiểm tra các loại giao dịch chưa được xác nhận trong phạm vi...")
        mode_warnings = _check_unconfirmed_modes(db)
        if mode_warnings:
            for w in mode_warnings:
                print(f"  !! {w}")
            print("\nCó giao dịch KHÔNG thuộc phạm vi đã xác nhận (Điều chuyển PX↔CT/CT→PX qua đề "
                  "nghị/Trả NCC) — DỪNG, chưa sửa gì. Hỏi lại người dùng trước khi chạy lại.")
            db.rollback()
            sys.exit(1)
        print("  Không có.")

        n_fulfilled_before = db.execute(select(func.count()).select_from(MaterialRequestLine)
                                        .where(MaterialRequestLine.status == "fulfilled")).scalar_one()
        n_dispense_before = db.execute(select(func.count()).select_from(Dispense)).scalar_one()
        n_filter_usage_before = db.execute(select(func.count()).select_from(BatchFilterLotMaterialUsage)).scalar_one()
        n_pack_usage_before = db.execute(select(func.count()).select_from(BatchPackLotMaterialUsage)).scalar_one()
        n_tu_do_before = db.execute(select(func.count()).select_from(StockMovement).where(
            StockMovement.mode.in_(("tu_do", "dieu_chuyen_nha_may")), StockMovement.reversed.is_(False))).scalar_one()
        n_px_transfer_before = db.execute(select(func.count()).select_from(TransferPxRequest)
                                          .where(TransferPxRequest.status == "approved")).scalar_one()
        print(f"\nHiện trạng trước khi sửa: {n_fulfilled_before} dòng đề nghị đã fulfilled, "
              f"{n_dispense_before} phiếu cấp liệu, {n_filter_usage_before} NVL dùng cho lô lọc, "
              f"{n_pack_usage_before} NVL dùng cho lô thành phẩm, {n_tu_do_before} giao dịch xuất "
              f"tự do/điều chuyển nhà máy khác, {n_px_transfer_before} điều chuyển PX↔CT đã duyệt.")

        if not any((n_fulfilled_before, n_dispense_before, n_filter_usage_before,
                    n_pack_usage_before, n_tu_do_before, n_px_transfer_before)):
            print("Không có gì để hoàn tác. Dừng.")
            return

        if not args.execute:
            print("\nDRY-RUN — chưa sửa gì. Chạy lại với --execute để sửa thật.")
            return

        if not args.yes:
            print("\n*** CẢNH BÁO: sắp SỬA THẬT — hoàn tác toàn bộ Cấp liệu + Đề nghị nhận kho đã "
                  "fulfilled + Xuất tự do (kể cả NVL Lọc/Chiết) + Điều chuyển sang nhà máy khác "
                  "liệt kê ở trên. ***")
            print("Nhập tồn đầu, Xuất sang ngang, và bản thân các Mẻ nấu KHÔNG bị đụng tới.")
            print("Thao tác này KHÔNG hoàn tác được qua ứng dụng. Đảm bảo đã sao lưu CSDL trước.")
            answer = input("Gõ đúng chữ  HOAN TAC DU LIEU  để xác nhận: ")
            if answer.strip() != "HOAN TAC DU LIEU":
                print("Xác nhận không khớp — hủy, không sửa gì.")
                sys.exit(1)

        print("\nBước 1 — hoàn tác Cấp liệu (Dispense)...")
        n_edges, n_disp, total_qty = _restore_dispensed_lots(db)
        print(f"  Đã hoàn {n_edges} cạnh tiêu thụ (tổng {total_qty} đơn vị đã cộng lại vào lô), "
              f"xóa {n_disp} phiếu cấp liệu.")

        print("\nBước 2 — hoàn tác Đề nghị nhận kho đã fulfilled...")
        n_done, errors = _undo_fulfilled_requests(db)
        if errors:
            for e in errors:
                print(f"  !! LỖI: {e}")
            print(f"\nCó {len(errors)} dòng không hoàn tác được (Bước 2) — DỪNG, rollback toàn bộ, "
                  "không sửa gì. Kiểm tra tay rồi chạy lại.")
            db.rollback()
            sys.exit(1)
        print(f"  Đã hoàn tác {n_done} dòng — chuyển lô về lại Kho công ty, đưa về 'pending'.")

        print("\nBước 3 — xóa NVL đã dùng cho Lọc/Chiết (tự hoàn kho)...")
        n_filter, n_pack, errors3 = _undo_filter_pack_material_usage(db)
        if errors3:
            for e in errors3:
                print(f"  !! LỖI: {e}")
            print(f"\nCó {len(errors3)} dòng không xóa được (Bước 3, có thể do hồ sơ Lọc/Chiết đã "
                  "khóa) — DỪNG, rollback toàn bộ, không sửa gì. Kiểm tra tay rồi chạy lại.")
            db.rollback()
            sys.exit(1)
        print(f"  Đã xóa {n_filter} dòng NVL lô lọc, {n_pack} dòng NVL lô thành phẩm.")

        print("\nBước 4 — hoàn tác Xuất tự do (còn lại)/Điều chuyển sang nhà máy khác...")
        n_free, errors4 = _undo_free_issue_and_factory_transfer(db)
        if errors4:
            for e in errors4:
                print(f"  !! LỖI: {e}")
            print(f"\nCó {len(errors4)} giao dịch không hoàn tác được (Bước 4) — DỪNG, rollback "
                  "toàn bộ, không sửa gì. Kiểm tra tay rồi chạy lại.")
            db.rollback()
            sys.exit(1)
        print(f"  Đã hoàn tác {n_free} giao dịch.")

        print("\nBước 5 — hoàn tác Điều chuyển Kho phân xưởng → Kho công ty đã duyệt...")
        n_px, n_px_orphaned, errors5 = _undo_px_transfers(db)
        if errors5:
            for e in errors5:
                print(f"  !! LỖI: {e}")
            print(f"\nCó {len(errors5)} điều chuyển không hoàn tác được (Bước 5) — DỪNG, rollback "
                  "toàn bộ, không sửa gì. Kiểm tra tay rồi chạy lại.")
            db.rollback()
            sys.exit(1)
        print(f"  Đã hoàn tác {n_px} điều chuyển PX↔CT, reset {n_px_orphaned} phiếu rác test cũ "
              "(lô/giao dịch gốc đã không còn).")

        db.commit()
        print("\nĐã commit. Đối chiếu lại:")
        _summary(db)
    except Exception:
        db.rollback()
        print("\nCÓ LỖI — đã rollback, KHÔNG có gì bị sửa. Chi tiết lỗi:", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
