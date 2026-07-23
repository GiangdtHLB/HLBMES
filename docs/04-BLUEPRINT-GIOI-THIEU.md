# MES Bia Hạ Long — Blueprint giới thiệu hệ thống

**Nhà máy Đông Mai · Hệ thống điều hành sản xuất (Manufacturing Execution System)**

> Tài liệu chuẩn giới thiệu: phần mềm này là gì, làm được những gì, và mang lại hiệu quả cụ thể ra sao khi đưa vào sử dụng. Cập nhật 22/07/2026.

---

## 1. Phần mềm này giải quyết vấn đề gì?

Trước khi có MES, việc điều hành sản xuất bia tại nhà máy phụ thuộc vào giấy tờ rời rạc, sổ sách viết tay và trao đổi miệng giữa các bộ phận: xưởng nấu, KCS, kho NVL, kho thành phẩm, bảo trì, năng lượng — mỗi nơi một hệ thống ghi chép riêng, không liên thông. Hệ quả thường gặp:

- Không biết chính xác **1 lô bia cụ thể** đã dùng nguyên liệu nào, ai kiểm tra chất lượng, xuất đi đâu — mất nhiều giờ tra cứu thủ công khi cần truy xuất hoặc thu hồi.
- Tồn kho nguyên liệu/thành phẩm chỉ biết được khi kiểm kê tay, dễ hết hạn mà không ai phát hiện kịp.
- Không có cảnh báo tự động khi lô hàng có vấn đề chất lượng — rủi ro xuất nhầm hàng chưa đạt.
- Số liệu sản xuất/năng lượng nằm rải rác ở nhiều hệ thống SCADA khác nhau, không tổng hợp được thành 1 bức tranh chung cho người quản lý.

**MES Bia Hạ Long được xây dựng để giải quyết trực tiếp 4 vấn đề trên**, bằng cách số hoá toàn bộ chuỗi sản xuất — từ nhận nguyên liệu tới xuất hàng — thành 1 hệ thống duy nhất, mọi bộ phận cùng nhìn vào 1 nguồn dữ liệu.

---

## 2. Phần mềm bao trùm những gì? (theo chuỗi giá trị thực tế)

```
NVL nhập kho → Nấu → Lên men → Lọc → Chiết → Kho thành phẩm → Xuất kho/Vận chuyển
     ↕              ↕         ↕      ↕      ↕
   Kiểm tra chất lượng (QC) xuyên suốt mọi công đoạn — tự động giữ lô khi có vấn đề
     ↕
   Truy xuất nguồn gốc hai chiều cho mọi lô, mọi thời điểm
```

Cùng với đó là các phân hệ hỗ trợ vận hành: điều độ sản xuất, công thức/BOM, bảo trì thiết bị, kiểm định đo lường, năng lượng, báo cáo, tích hợp với hệ thống SCADA/ERP sẵn có của nhà máy, và một trợ lý AI tra cứu nhanh.

Toàn bộ chạy trên **1 phần mềm nền web**, dùng được trên máy tính văn phòng lẫn tablet cảm ứng ngoài xưởng (giao diện Kiosk riêng), không cần cài đặt phức tạp.

---

## 3. Các nhóm tính năng chính & hiệu quả mang lại

### 3.1 Kiểm soát chất lượng tự động, không phụ thuộc trí nhớ con người

Mỗi vật tư, mỗi công đoạn sản xuất (Nấu/Lên men/Lọc/Chiết), mỗi sản phẩm có thể gán **nhóm chỉ tiêu QC riêng**. Khi một chỉ tiêu bị đánh giá **không đạt**, hệ thống **tự động giữ lô** (`on_hold`) — chặn ngay lập tức việc xuất kho hoặc chuyển sang công đoạn tiếp theo, không cần ai đó nhớ để chặn tay.

**Hiệu quả:** loại bỏ hoàn toàn rủi ro "quên chặn" lô lỗi — điều vốn phụ thuộc vào sự cẩn thận của từng cá nhân trong quy trình giấy tờ truyền thống. Người ghi kết quả QC và người ra quyết định release lô luôn là 2 người khác nhau (Segregation of Duties), đúng chuẩn thực hành sản xuất tốt (GMP).

### 3.2 Truy xuất nguồn gốc tức thời (traceability)

Từ 1 lô thành phẩm bất kỳ, tra ngược lại toàn bộ chuỗi: mẻ chiết nào → tank lọc nào → lô lên men nào → mẻ nấu nào → nguyên liệu (lô, nhà cung cấp) nào đã dùng. Chiều ngược lại: từ 1 lô nguyên liệu, biết đã đi vào những mẻ nào, thành phẩm nào, xuất cho khách hàng nào.

**Hiệu quả:** nếu phát sinh sự cố chất lượng cần thu hồi (recall), thời gian xác định phạm vi ảnh hưởng giảm từ hàng giờ tra cứu sổ sách xuống **còn vài giây tra cứu trên hệ thống**.

### 3.3 Kiểm soát tồn kho chủ động — không chờ đến lúc thiếu hụt hoặc hết hạn mới biết

- Cảnh báo tự động khi tồn kho một vật tư xuống dưới **mức tồn tối thiểu** đã cấu hình, kèm biểu đồ trực quan mức thiếu hụt.
- Cảnh báo lô nguyên liệu/thành phẩm **sắp hoặc đã hết hạn** ngay trên Dashboard, không cần chủ động vào từng kho kiểm tra.
- **Kiểm kê định kỳ số hoá**: tạo phiếu, đối chiếu, chốt lệch tồn, và có quy trình **Duyệt** bởi cấp quản lý (giám đốc/quản đốc/KCS/kỹ sư) để đảm bảo số liệu kiểm kê được xác nhận chính thức trước khi trở thành số liệu chính thức không thể sửa lại.

**Hiệu quả:** giảm thất thoát do hết hạn không phát hiện kịp; giảm gián đoạn sản xuất do thiếu nguyên liệu đột xuất; số liệu tồn kho luôn có người chịu trách nhiệm xác nhận rõ ràng.

### 3.4 Số hoá hồ sơ mẻ sản xuất, thay thế hoàn toàn ghi chép giấy

Log nhiệt độ/thời gian nấu bia trước đây ghi tay hoặc lấy từ máy Braumat rồi chép lại thủ công vào biểu mẫu giấy QT-KCS-QT-BM-05. Hệ thống hiện **tự động nhập (import) trực tiếp file PDF xuất ra từ máy Braumat**, phân tích và điền đúng vào đúng vị trí biểu mẫu điện tử — loại bỏ hoàn toàn bước chép tay dễ sai sót.

**Hiệu quả:** hồ sơ mẻ đầy đủ, chính xác 100% so với dữ liệu máy, có thể in ra đúng layout biểu mẫu giấy quen thuộc khi cần lưu hồ sơ hoặc trình thanh tra.

### 3.5 Một màn hình nhìn thấy toàn bộ nhà máy

Dashboard tổng hợp thời gian thực: tình trạng các lệnh nấu/lọc, số mẻ đang chạy ở từng công đoạn, cảnh báo QC, cảnh báo tồn kho, và **số liệu sản lượng/điện tiêu thụ lấy trực tiếp từ hệ thống SCADA thật của nhà máy** (không phải số liệu nhập tay hay giả lập) — tất cả trong 1 màn hình, không cần đăng nhập nhiều hệ thống khác nhau.

**Hiệu quả:** người quản lý nắm được tình hình sản xuất toàn nhà máy trong vài giây thay vì phải hỏi từng bộ phận hoặc mở nhiều phần mềm khác nhau.

### 3.6 Kết nối được với hệ thống sẵn có, không phải xây lại từ đầu

Phần mềm kết nối trực tiếp vào các hệ thống SCADA/CSDL đang vận hành thật tại nhà máy (Energy/NameSys, 30K_Report, Donggoi...) để lấy số liệu điện, sản lượng dây chuyền lon/keg — không yêu cầu nhập tay lại, không thay thế các hệ thống đó mà **tổng hợp và trình bày lại** cho người quản lý dễ theo dõi hơn.

**Hiệu quả:** tận dụng được hạ tầng đã đầu tư, triển khai nhanh, không gây gián đoạn hệ thống đang chạy.

### 3.7 Phân quyền chặt chẽ, mọi thao tác đều có dấu vết

11 tài khoản đang hoạt động, chia theo 5 vai trò (vận hành/quản đốc/QA/kỹ sư/quản trị), mỗi tài khoản còn có danh sách quyền thao tác riêng biệt. Mọi thay đổi dữ liệu quan trọng đều được ghi vào **nhật ký audit không thể sửa/xoá** — biết chính xác ai đã làm gì, lúc nào.

**Hiệu quả:** đáp ứng yêu cầu tuân thủ (compliance) khi có thanh tra hoặc điều tra sự cố; ngăn chặn thao tác sai quyền hạn ngay từ đầu thay vì phát hiện sau.

---

## 4. Ảnh chụp dữ liệu thực tế đang chạy

**Tiến độ theo công đoạn:**

| Công đoạn | Tiến độ |
|---|---|
| Lệnh nấu | 1/1 hoàn thành |
| Lệnh lọc | 2/2 hoàn thành |
| Mẻ nấu | 5/5 hoàn thành |
| Mẻ lọc | 3/3 hoàn thành |
| Mẻ chiết | 2 hoàn thành · 2 đang chạy |

**Tồn kho nguyên liệu (trích 5/12 dòng thật):**

| Vật tư | Tồn | ĐVT |
|---|---|---|
| MALT-PILS — Malt Pilsner | 5.302 | kg |
| GAO-504 — Gạo tẻ (504) | 4.240,4 | kg |
| 002 — Test VT02 | 1.614 | kg |
| MALT-VIENNA — Malt Vienna | 3.000 | kg |
| **LOWSTOCK01 ⚠ dưới ngưỡng** | **15 / 100** | kg |

## 5. Quy mô hệ thống hiện tại (số liệu thật trên máy chủ, 22/07/2026)

| Chỉ số | Giá trị |
|---|---|
| Tài khoản đang hoạt động | 11 |
| Sản phẩm (dịch bia) / Loại bia / SKU thành phẩm | 5 / 4 / 25 |
| Vật tư nguyên liệu quản lý | 13 |
| Lệnh nấu / Lệnh lọc đã xử lý | 1 / 2 |
| Mẻ nấu / mẻ lọc / mẻ chiết đã xử lý | 5 / 3 / 4 |
| Đơn vị thành phẩm (lon/keg/vỉ) đang theo dõi | > 300.000 |
| Phân hệ nghiệp vụ độc lập | 27 (từ Dashboard tới Audit) |

---

## 6. Vì sao đây là một khoản đầu tư hiệu quả

Phần mềm không phải là một dự án lý thuyết — mọi tính năng nêu trên đều **đang chạy thật, có dữ liệu thật, được kiểm thử tự động** (bộ kiểm thử hồi quy hàng trăm kịch bản chạy lại mỗi khi có thay đổi để đảm bảo không phát sinh lỗi ngược) và đã qua xác minh thao tác thực tế trên giao diện trước khi đưa vào sử dụng. Nhà máy có thể tiếp tục mở rộng thêm tính năng theo nhu cầu phát sinh mà không cần thay thế toàn bộ hệ thống, do kiến trúc được thiết kế theo từng phân hệ độc lập, dễ bổ sung.

