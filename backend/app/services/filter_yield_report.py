"""Nhãn phân loại + hàm phân loại sản lượng lọc theo ngưỡng cấu hình (OpsSetting) — dùng bởi
pipeline "Mẻ sản xuất" mới (xem services/dashboard.py::_batch_filter_lot_yield_items/
low_yield_filter_alerts, dựa trên BatchFilterLotBatch).

Trước đây file này còn có báo cáo sản lượng lọc đầy đủ (theo mẻ/theo "mẻ lọc số", gộp
ngày/tuần/tháng) dựa trên FilterRecord/FilterOrderTank/FermentRecord (module Nấu-Lọc-Chiết
cũ) — đã xóa cùng module đó (chưa có báo cáo tương đương cho pipeline mới)."""


LABEL = {"thap": "Thấp", "binh_thuong": "Bình thường", "cao": "Cao", "cuoi": "Mẻ cuối (không tính)"}


def classify_yield_l(v_l: float, low_l: float, high_l: float) -> str:
    if v_l <= low_l:
        return "thap"
    if v_l <= high_l:
        return "binh_thuong"
    return "cao"
