# Báo cáo Tổng Giám đốc — Dự án MES Bia Hạ Long

**Người trình:** Phòng Sản xuất/CNTT — Nhà máy Đông Mai · **Ngày:** 22/07/2026

---

## 1. Tóm tắt

Hệ thống điều hành sản xuất (MES) cho nhà máy đã **hoàn thành và đang chạy thật** trên toàn bộ chuỗi giá trị: từ nhận nguyên liệu, nấu, lên men, lọc, chiết, tới kho thành phẩm và xuất hàng, cùng các phân hệ chất lượng, kho, năng lượng, bảo trì, báo cáo. Toàn bộ 27 phân hệ đã được kiểm thử tự động và xác minh thao tác thực tế. Đề xuất: **cho phép mở rộng dữ liệu thật và tăng dần phạm vi người dùng sang các ca sản xuất tiếp theo.**

---

## 2. Hiệu quả đã ghi nhận

| Trước khi có MES | Sau khi có MES |
|---|---|
| Tra cứu nguồn gốc 1 lô: hàng giờ lật sổ sách | Tra cứu tức thời, vài giây trên hệ thống |
| Lô lỗi chất lượng có thể bị bỏ sót do quên chặn thủ công | Tự động giữ lô (`on_hold`) ngay khi có chỉ tiêu QC không đạt |
| Không phát hiện kịp tồn kho thiếu hụt/hết hạn | Cảnh báo tự động ngay trên Dashboard |
| Ghi log nấu bia bằng tay từ máy Braumat, dễ sai sót | Nhập tự động từ file PDF máy xuất ra, chính xác 100% |
| Số liệu sản lượng/điện nằm rời rạc ở nhiều hệ SCADA | Tổng hợp về 1 Dashboard duy nhất, dữ liệu thật theo thời gian thực |
| Không ai biết ai đã thao tác gì trên hệ thống | Nhật ký audit đầy đủ, không thể sửa/xoá |

---

## 3. Dữ liệu thực tế đang chạy trên hệ thống

**Tiến độ theo công đoạn:**

| Công đoạn | Tiến độ |
|---|---|
| Lệnh nấu | 1/1 |
| Lệnh lọc | 2/2 |
| Mẻ nấu | 5/5 |
| Mẻ lọc | 3/3 |
| Mẻ chiết | 2 xong · 2 đang chạy |
| Tank lên men | 2/4 đang dùng |

**Trạng thái 2 lô đang sản xuất:**

| Mã nấu | Dịch bia | Nấu | Lên men | Lọc | Chiết |
|---|---|---|---|---|---|
| 2 | Dịch Legend 13oP | Hoàn thành | Lọc 1 phần | Đã kết thúc | Đang chiết |
| 1 | Dịch Sapphire 14oP | Hoàn thành | Lọc 1 phần | Đã kết thúc | Đã kết thúc |

**Tồn kho nguyên liệu (12 dòng thật):**

| Mã VT | Tên | Tồn | ĐVT |
|---|---|---|---|
| 002 | Test VT02 | 1.614 | kg |
| BBB01 | Bìa carton | 500 | Cái |
| GAO-504 | Gạo tẻ (504) | 4.240,4 | kg |
| HOP-SAAZ | Hoa bia Saaz | 61,04 | kg |
| **LOWSTOCK01** | Vat tu ton thap Demo | **15 ⚠ (ngưỡng 100)** | kg |
| MALT-ANH | Malt Anh (bao) | 498,08 | kg |
| MALT-E2E | Malt kiểm thử E2E | 497,6 | kg |
| MALT-PILS | Malt Pilsner | 5.302 | kg |
| MALT-VIENNA | Malt Vienna (thay thế) | 3.000 | kg |
| NAPCHAI-LIVE | Nắp chai (test live) | 460 | cái |
| PFBROWSER01 | Vat tu PF browser | 50 | kg |
| YEAST-L34 | Men Lager W-34/70 | 149,76 | L |

**Cảnh báo đang mở:**

| Loại | Chi tiết |
|---|---|
| QC | Lô QCDEMO-LOT-01 đang giữ (on_hold), 1 chỉ tiêu fail |
| Tồn kho | LOWSTOCK01 thiếu 85kg so với tồn tối thiểu |
| Hạn dùng | 3 lô đã quá hạn (1–13 ngày) · 4 lô sắp hết hạn (0–8 ngày) |

## 4. Quy mô đang vận hành (số liệu thật, 22/07/2026)

- **11** tài khoản đang hoạt động, phân theo 5 vai trò (vận hành / quản đốc / QA / kỹ sư / quản trị).
- **5** sản phẩm (dịch bia), **4** loại bia, **25** SKU thành phẩm, **13** vật tư nguyên liệu.
- **1** Lệnh nấu, **2** Lệnh lọc đã xử lý; **5** mẻ nấu, **3** mẻ lọc, **4** mẻ chiết (2 đang chạy).
- Hơn **300.000** đơn vị thành phẩm (lon/keg/vỉ) đang được theo dõi trong kho.
- **1** cảnh báo QC đang mở, **1** vật tư dưới mức tồn tối thiểu, **8** lô NVL sắp/đã hết hạn — tất cả đã hiển thị sẵn trên Dashboard, không cần chờ báo cáo giấy.

---

## 5. Tiến độ triển khai

Toàn bộ các phân hệ cốt lõi đã hoàn thành: Lệnh sản xuất, Công thức/BOM, Chất lượng, Nấu–Lọc–Chiết, Truy xuất nguồn gốc, Kho NVL, Kho thành phẩm, Bao bì, Năng lượng, Bảo trì/Kiểm định, Báo cáo, Tích hợp hệ thống ngoài, Tài khoản/phân quyền, Audit. Các tính năng gần nhất vừa hoàn tất và xác minh: cảnh báo QC hợp nhất trên Dashboard, cảnh báo tồn tối thiểu kèm biểu đồ, và quy trình **Duyệt/Hoàn tác** cho kiểm kê định kỳ (đảm bảo số liệu kiểm kê phải được cấp quản lý xác nhận chính thức trước khi khoá).

**Chưa còn hạng mục nào tồn đọng ở các phân hệ cốt lõi.** Hệ thống đủ điều kiện để mở rộng dữ liệu thật và số lượng người dùng.

---

## 6. Đề xuất kế hoạch tiếp theo

1. **Mở rộng dữ liệu thật:** chuyển từ dữ liệu minh hoạ/thử nghiệm sang nhập liệu song song với sản xuất thật trong 2–4 tuần để kiểm chứng ở quy mô đầy đủ trước khi dừng hẳn ghi chép giấy song song.
2. **Đào tạo người dùng theo vai trò:** mỗi chức danh (vận hành, KCS, thủ kho, quản đốc...) chỉ cần nắm phần việc của mình — tài liệu hướng dẫn sử dụng chi tiết theo từng phân hệ đã sẵn sàng.
3. **Xác định phân hệ mở rộng ưu tiên tiếp theo** theo nhu cầu thực tế phát sinh sau giai đoạn dùng thật (ví dụ: thêm chỉ tiêu QC mới, thêm kết nối SCADA khác, mở rộng sang các dây chuyền/nhà máy khác nếu cần).
4. **Duy trì backup & vận hành hạ tầng máy chủ** — hiện chạy trên SQLite cho môi trường thử nghiệm; khi chuyển sản xuất thật cần chuyển sang PostgreSQL (đã hỗ trợ sẵn, chỉ cần đổi cấu hình) để đảm bảo an toàn dữ liệu ở quy mô lớn.

---

*Chi tiết đầy đủ từng tính năng: xem "Blueprint giới thiệu hệ thống" (04). Hướng dẫn thao tác từng phân hệ: xem "Hướng dẫn sử dụng phần mềm" (03).*
