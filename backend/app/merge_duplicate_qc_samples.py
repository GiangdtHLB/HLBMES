"""Gộp các "lần lấy mẫu" CT chính/CT phụ lên men bị TÁCH VỤN thành nhiều bản ghi rời rạc do bug
frontend cũ (submit từng chỉ tiêu một thay vì bắt buộc đủ cả bộ 1 lần — đã sửa, yêu cầu người
dùng 2026-09-02: "lần 1 cũng phải gom lại"). Xem services/qc_catalog.py::merge_duplicate_qc_samples
cho chi tiết điều kiện gộp (an toàn, idempotent, không xóa dữ liệu).

Đọc kết nối CSDL giống hệt server đang chạy (biến môi trường MES_DATABASE_URL, mirror
reset_operational_data.py) — kiểm tra đúng CSDL trước khi chạy nếu không phải môi trường dev.

Chạy: python -m app.merge_duplicate_qc_samples
"""

import sys

from .database import SessionLocal
from .services.qc_catalog import merge_duplicate_qc_samples


def main() -> None:
    db = SessionLocal()
    try:
        result = merge_duplicate_qc_samples(db)
        # stdout của Windows console mặc định là cp1252 (không encode được tiếng Việt có dấu) —
        # dùng errors="replace" để KHÔNG crash sau khi đã commit xong (script vẫn thành công dù
        # dòng thông báo hiện lỗi thay vì chữ Việt trên console cp1252).
        msg = (f"Đã gộp {result['merged_groups']} nhóm lần lấy mẫu bị tách vụn "
              f"({result['merged_rows']} dòng đổi sample_id).")
        sys.stdout.buffer.write(msg.encode("utf-8", errors="replace") + b"\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
