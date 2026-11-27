"""Chèn dữ liệu VÍ DỤ (không phải thật) vào filling_status_log trên DB dev local — CHỈ để xem
thử biểu đồ "Trạng thái máy chiết 30K theo thời gian" trông thế nào khi đã có cả 2 màu (xanh=
đang chiết, cam=đang CIP), vì dữ liệu thật hiện chưa có đoạn CIP nào (tác vụ mới bật). KHÔNG chạy
script này trên production — chỉ dùng DB dev local (mes.db) để xem demo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import timedelta

from app.common import utcnow
from app.database import SessionLocal, engine, init_db
from app.models.filling_log import FillingStatusLog

# CHỐT CHẶN — không chỉ dựa vào dòng cảnh báo ở docstring: script này XOÁ SẠCH filling_status_log
# (db.query(...).delete() bên dưới) rồi chèn dữ liệu giả. File nằm trong image nên CÓ MẶT trong
# container production, nơi MES_DATABASE_URL trỏ thẳng vào SQL Server thật — gõ nhầm 1 lệnh là
# mất toàn bộ log máy chiết thật, và log đó dùng cho báo cáo hiệu suất. Chỉ cho chạy trên SQLite
# (DB dev local); muốn chạy chỗ khác phải khai báo ý định thật rõ ràng.
_dialect = engine.url.get_backend_name()
if _dialect != "sqlite" and "--toi-biet-day-khong-phai-sqlite" not in sys.argv:
    sys.exit(
        f"TU CHOI CHAY: script demo nay XOA SACH bang filling_status_log roi chen du lieu GIA.\n"
        f"  CSDL dang tro toi : {_dialect} ({engine.url.host or engine.url.database})\n"
        f"  Chi cho chay tren : sqlite (DB dev local)\n"
        f"Neu that su co chu y, chay lai kem co --toi-biet-day-khong-phai-sqlite."
    )

init_db()
db = SessionLocal()
try:
    db.query(FillingStatusLog).delete()
    now = utcnow()
    t = now - timedelta(days=5)
    # Lien mach (status 3 = may dung, lap khoang trong truoc day) - dung chuoi 1/3/2/3 xen ke de
    # mo phong dung chu ky thuc te: chiet -> dung nghi giua ca -> CIP -> dung -> chiet lai...
    pattern = [
        (1, 180), (3, 40), (2, 25), (3, 15), (1, 210), (3, 60), (2, 20), (3, 20),
        (1, 95), (3, 30), (2, 30), (3, 10), (1, 240), (3, 50), (2, 15), (3, 25),
        (1, 160), (3, 35), (2, 45), (3, 15), (1, 300),
    ]
    for status, minutes in pattern:
        start = t
        end = t + timedelta(minutes=minutes)
        db.add(FillingStatusLog(status=status, machine_running=(status == 1),
                                clean_flushing=(status == 2), rins_return_gas_channel=False,
                                started_at=start, ended_at=end,
                                duration_minutes=minutes, data_gap=False))
        t = end  # LIEN MACH — doan sau bat dau dung luc doan truoc ket thuc, khong con khoang trong
    db.commit()
    print(f"Da chen {len(pattern)} doan vi du (lien mach), tu {now - timedelta(days=5)} den {t}")
finally:
    db.close()
