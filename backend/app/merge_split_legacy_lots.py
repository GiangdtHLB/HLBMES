"""Gộp lại các lô NVL bị "tách sinh mã lô MỚI" theo cơ chế CŨ (trước khi sửa để tái dùng lại
lot_code khi tách — xem services/warehouse.py::_transfer_lot, và routers/materials.py::
_attach_split_from's docstring: "Từ khi tách lô KHÔNG còn sinh mã mới ... tag chỉ còn hiện cho
dữ liệu tách kiểu CŨ").

Phạm vi (yêu cầu người dùng 2026-09-15): rà toàn hệ thống thấy 154 lô (20 "lô cha" gốc, mỗi cha
có 1-18 "lô con" mang mã KHÁC hẳn cha) là tồn dư từ TRƯỚC khi code fix được deploy lên server
thật — không phải lỗi đang tiếp diễn (đã xác nhận: mọi lần tách MỚI sau khi fix đều tái dùng
đúng lot_code, không sinh mã mới nữa).

QUAN TRỌNG — sửa 2026-09-15 sau khi đối chiếu dữ liệu thật: điều kiện an toàn BAN ĐẦU ("đúng 1
StockMovement") vừa THIẾU vừa THỪA:
  - THIẾU: không kiểm tra `parent.location == child.location`. Kiểm tra thật thấy cặp DUY NHẤT
    khớp điều kiện cũ (TD-KCT-22 → 2026-00069) có lô cha ở "Kho công ty" nhưng lô con đang THẬT
    SỰ nằm ở "Kho phân xưởng" (transfer thật, CHƯA hoàn tác) — nếu gộp sẽ cộng nhầm số lượng vào
    sai kho, làm sai lệch tồn kho thật giữa 2 kho. Đã thêm điều kiện bắt buộc: chỉ gộp khi 2 lô
    CÙNG vị trí kho hiện tại.
  - THỪA: yêu cầu "đúng 1 giao dịch" loại bỏ nhầm các lô con đã "Xuất theo đề nghị" rồi bị
    "Hoàn tác" (undo_fulfill_line) — 2 giao dịch transfer (đi + hoàn tác) nhưng NET không đổi gì,
    lô con thực chất CHƯA từng được dùng thật, quay đúng về vị trí ban đầu. Đổi điều kiện thành:
    MỌI StockMovement của lô con đều phải là movement_type="transfer" (không giới hạn số lượng
    giao dịch) — nếu có bất kỳ issue/receipt/adjust nào khác xen vào, vẫn coi là có lịch sử độc
    lập, không tự ý gộp.

Với MỖI cặp cha/con hợp lệ để gộp:
  1. Cộng dồn quantity của lô con vào lô cha (parent.quantity += child.quantity).
  2. Di chuyển QualityResult/Deviation đang gắn scope_id=lô con (scope_type="lot") sang gắn lại
     scope_id=lô cha — GIỮ NGUYÊN lịch sử chỉ tiêu chất lượng đã khai/duyệt cho lô con, không mất
     dấu vết QC (nhiều lô con đang ở trạng thái "released" — đã qua QC thật).
  3. StockMovement còn tham chiếu lot_id=lô con được gỡ lot_id (đặt NULL, GIỮ NGUYÊN cột lot_code
     dạng text để vẫn tra được lịch sử) — tránh lỗi khóa ngoại khi xóa lô con, đồng thời tránh
     đếm trùng số lượng nếu gán lại movement đó cho lô cha (lô cha đã được cộng dồn ở bước 1 rồi).
  4. Xóa cạnh GenealogyEdge(relation=split) nối cha→con — đã gộp xong thì cạnh này không còn ý
     nghĩa (2 dòng đã hợp thành 1).
  5. Xóa hẳn dòng MaterialLot của lô con.

AN TOÀN — BỎ QUA (không gộp, in ra để kiểm tra tay) nếu lô con KHÔNG thỏa TẤT CẢ:
  - Không phải nguồn (from_id) của bất kỳ GenealogyEdge nào khác (nghĩa là chưa từng bị tách tiếp/
    tiêu thụ cho mẻ/dùng cho lô lọc/lô thành phẩm nào — nếu có, gộp sẽ làm sai lệch chuỗi truy xuất
    nguồn gốc thật, KHÔNG được tự ý gộp).
  - MỌI StockMovement của lô con đều là movement_type="transfer" (không có issue/receipt/adjust
    nào khác xen vào — nếu có, lô con đã có lịch sử độc lập, không tự ý gộp).
  - `location` hiện tại của lô con TRÙNG với `location` hiện tại của lô cha (nếu khác kho, lô con
    đang là tồn thật ở kho khác — gộp sẽ sai lệch tồn kho theo từng kho, KHÔNG được gộp).
  - status khác "on_hold" (đang chờ khai báo/duyệt QC — không tự ý gộp khi chưa rõ kết quả).

QUAN TRỌNG — ĐỌC TRƯỚC KHI CHẠY (giống hệt quy ước reset_nvl_dispense_and_requests.py):
  1. Đây là thao tác SỬA DỮ LIỆU THẬT (cộng dồn quantity, xóa lô con + cạnh genealogy liên quan)
     — KHÔNG hoàn tác được qua ứng dụng. Sao lưu CSDL trước khi chạy --execute.
  2. Script đọc kết nối CSDL giống hệt server đang chạy (MES_DATABASE_URL). Kiểm tra kỹ trước khi
     chạy --execute — chạy nhầm máy sẽ sửa nhầm CSDL đó.
  3. Mặc định DRY-RUN (chỉ đếm/tính toán, KHÔNG ghi gì). Phải thêm --execute mới sửa thật, vẫn
     phải gõ đúng cụm xác nhận (trừ khi thêm --yes).

Cách chạy (từ thư mục backend/, đã kích hoạt venv có đúng MES_DATABASE_URL):
    python -m app.merge_split_legacy_lots                # xem thử, không sửa
    python -m app.merge_split_legacy_lots --execute       # sửa thật (hỏi xác nhận)
    python -m app.merge_split_legacy_lots --execute --yes # sửa thật, không hỏi
"""

import argparse
import sys

from sqlalchemy import select, update

from .common import GenealogyRelation, LotStatus
from .database import SessionLocal
from .models.materials import GenealogyEdge, MaterialLot
from .models.quality import Deviation, QualityResult
from .models.warehouse import StockMovement


def _find_merge_candidates(db) -> tuple[list[tuple], list[str]]:
    """Trả về (list[(parent_lot, child_lot, split_edge)] hợp lệ để gộp, list[str] lô con bị BỎ
    QUA kèm lý do)."""
    edges = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.from_type == "lot", GenealogyEdge.to_type == "lot",
        GenealogyEdge.relation == GenealogyRelation.SPLIT.value)).scalars().all()
    candidates = []
    skipped = []
    for edge in edges:
        parent = db.get(MaterialLot, edge.from_id)
        child = db.get(MaterialLot, edge.to_id)
        if not parent or not child:
            continue
        if parent.lot_code == child.lot_code:
            continue  # tách kiểu MỚI (đã tái dùng lot_code) — không cần gộp, không phải mục tiêu
        # Lô con đã bị tách/tiêu thụ tiếp (chính nó là nguồn của 1 cạnh genealogy khác)?
        further = db.execute(select(GenealogyEdge.edge_id).where(
            GenealogyEdge.from_type == "lot", GenealogyEdge.from_id == child.lot_id).limit(1)
            ).scalar_one_or_none()
        if further:
            skipped.append(f"Lô {child.lot_code} (tách từ {parent.lot_code}): đã có giao dịch "
                           "tiếp theo (tách/tiêu thụ) — bỏ qua, cần kiểm tra tay.")
            continue
        movements = db.execute(select(StockMovement).where(
            StockMovement.lot_id == child.lot_id)).scalars().all()
        non_transfer = [m for m in movements if m.movement_type != "transfer"]
        if non_transfer:
            skipped.append(f"Lô {child.lot_code} (tách từ {parent.lot_code}): có "
                           f"{len(non_transfer)} giao dịch khác transfer (issue/receipt/adjust) — "
                           "bỏ qua, cần kiểm tra tay.")
            continue
        if child.location != parent.location:
            skipped.append(f"Lô {child.lot_code} (tách từ {parent.lot_code}): đang ở kho "
                           f"'{child.location}' khác kho lô cha '{parent.location}' — bỏ qua, "
                           "đây là tồn thật ở kho khác, không tự ý gộp.")
            continue
        if child.status == LotStatus.ON_HOLD.value:
            skipped.append(f"Lô {child.lot_code} (tách từ {parent.lot_code}): đang ON HOLD — "
                           "bỏ qua, cần kiểm tra tay.")
            continue
        candidates.append((parent, child, edge))
    return candidates, skipped


def _merge_one(db, parent: MaterialLot, child: MaterialLot, edge: GenealogyEdge) -> float:
    """Gộp 1 lô con vào lô cha — trả về quantity đã gộp."""
    qty = child.quantity
    parent.quantity = round(parent.quantity + qty, 4)
    db.execute(update(QualityResult).where(
        QualityResult.scope_type == "lot", QualityResult.scope_id == child.lot_id
        ).values(scope_id=parent.lot_id))
    db.execute(update(Deviation).where(
        Deviation.scope_type == "lot", Deviation.scope_id == child.lot_id
        ).values(scope_id=parent.lot_id))
    db.execute(update(StockMovement).where(
        StockMovement.lot_id == child.lot_id).values(lot_id=None))
    db.delete(edge)
    db.delete(child)
    return qty


def _summary(db) -> None:
    remaining = db.execute(select(GenealogyEdge).where(
        GenealogyEdge.from_type == "lot", GenealogyEdge.to_type == "lot",
        GenealogyEdge.relation == GenealogyRelation.SPLIT.value)).scalars().all()
    n_legacy = 0
    for edge in remaining:
        parent = db.get(MaterialLot, edge.from_id)
        child = db.get(MaterialLot, edge.to_id)
        if parent and child and parent.lot_code != child.lot_code:
            n_legacy += 1
    print(f"  Cạnh split mã-khác-cha (chưa gộp/bị bỏ qua) còn lại: {n_legacy}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="Thực sự sửa (mặc định chỉ xem thử).")
    ap.add_argument("--yes", action="store_true", help="Bỏ qua bước gõ xác nhận.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        candidates, skipped = _find_merge_candidates(db)
        total_qty_by_parent: dict[str, float] = {}
        for parent, child, _edge in candidates:
            total_qty_by_parent[parent.lot_code] = total_qty_by_parent.get(parent.lot_code, 0.0) + child.quantity

        print(f"Tìm thấy {len(candidates)} lô con hợp lệ để gộp, thuộc "
              f"{len(total_qty_by_parent)} lô cha khác nhau.")
        for code, qty in sorted(total_qty_by_parent.items()):
            print(f"  {code}: +{round(qty, 4)}")
        if skipped:
            print(f"\n{len(skipped)} lô con BỊ BỎ QUA (cần kiểm tra tay, KHÔNG tự động gộp):")
            for s in skipped:
                print(f"  !! {s}")

        if not candidates:
            print("\nKhông có gì để gộp.")
            return

        if not args.execute:
            print("\n(DRY-RUN — chưa sửa gì. Chạy lại với --execute để gộp thật.)")
            return

        if not args.yes:
            print(f"\nSắp gộp {len(candidates)} lô con vào {len(total_qty_by_parent)} lô cha — "
                  "XÓA HẲN dòng lô con, cộng dồn quantity về lô cha, chuyển QC/Deviation sang lô "
                  "cha, gỡ lot_id khỏi StockMovement liên quan.")
            print("Thao tác này KHÔNG hoàn tác được qua ứng dụng. Đảm bảo đã sao lưu CSDL trước.")
            answer = input("Gõ đúng chữ  GOP LO TACH CU  để xác nhận: ")
            if answer.strip() != "GOP LO TACH CU":
                print("Xác nhận không khớp — hủy, không sửa gì.")
                sys.exit(1)

        print("\nĐang gộp...")
        merged = 0
        for parent, child, edge in candidates:
            _merge_one(db, parent, child, edge)
            merged += 1
        db.flush()
        db.commit()
        print(f"Đã gộp {merged} lô con. Đối chiếu lại:")
        _summary(db)
    except Exception:
        db.rollback()
        print("\nCÓ LỖI — đã rollback, KHÔNG có gì bị sửa. Chi tiết lỗi:", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
