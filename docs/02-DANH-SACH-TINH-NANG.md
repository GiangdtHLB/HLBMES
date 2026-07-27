# Danh sách Tính năng — MES Bia Hạ Long (Nhà Máy Đông Mai)

> Liệt kê đầy đủ các tính năng *đã hiện thực trong mã nguồn*, nhóm theo phân hệ.
> Mỗi tính năng kèm endpoint API và quyền yêu cầu (nếu có). Phiên bản: `0.1.0-mvp`.

**Ngày phát hành:** 23/06/2026 · **Ngày cập nhật:** 23/07/2026

**Quy ước cột "Quyền":** ✅ = đăng nhập là đủ · *(permission)* = cần quyền thao tác cụ thể · *(role)* = cần vai trò · *(X-API-Key)* = cho phần mềm ngoài.

---

## Mục lục phân hệ
1. [Xác thực, tài khoản & phân quyền](#1-xác-thực-tài-khoản--phân-quyền)
2. [Danh mục (master data)](#2-danh-mục-master-data)
3. [Lệnh sản xuất & Điều độ](#3-lệnh-sản-xuất--điều-độ)
4. [Lệnh nấu & Lệnh lọc (phân cấp)](#4-lệnh-nấu--lệnh-lọc-phân-cấp)
5. [Công thức & BOM](#5-công-thức--bom)
6. [Mẻ sản xuất & thực thi](#6-mẻ-sản-xuất--thực-thi)
7. [ISA-88 — recipe/batch theo thủ tục](#7-isa-88--recipebatch-theo-thủ-tục)
8. [Cấp liệu (dispense/backflush)](#8-cấp-liệu-dispensebackflush)
9. [Chất lượng cơ bản](#9-chất-lượng-cơ-bản)
10. [QC nâng cao — SPC / CAPA / COA / LIMS / Nhóm chỉ tiêu](#10-qc-nâng-cao--spc--capa--coa--lims--nhóm-chỉ-tiêu)
11. [Nấu–Lọc–Chiết (công đoạn chi tiết)](#11-nấulọcchiết-công-đoạn-chi-tiết)
12. [Truy xuất, Recall & Hồ sơ lô điện tử](#12-truy-xuất-recall--hồ-sơ-lô-điện-tử)
13. [Hồ sơ mẻ điện tử (EBR) & chữ ký điện tử](#13-hồ-sơ-mẻ-điện-tử-ebr--chữ-ký-điện-tử)
14. [Kho NVL (Kho công ty ↔ Kho phân xưởng)](#14-kho-nvl-kho-công-ty--kho-phân-xưởng)
15. [Kho thành phẩm (WMS theo unit) & bao bì tuần hoàn](#15-kho-thành-phẩm-wms-theo-unit--bao-bì-tuần-hoàn)
16. [OEE & Downtime](#16-oee--downtime)
17. [Bảo trì & Kiểm định (CMMS)](#17-bảo-trì--kiểm-định-cmms)
18. [Năng lượng](#18-năng-lượng)
19. [Tích hợp CSDL SCADA ngoài & Realtime thật](#19-tích-hợp-csdl-scada-ngoài--realtime-thật)
20. [Import dữ liệu ngoài & trường tùy biến](#20-import-dữ-liệu-ngoài--trường-tùy-biến)
21. [Lập lịch sản xuất tối ưu](#21-lập-lịch-sản-xuất-tối-ưu)
22. [Báo cáo](#22-báo-cáo)
23. [Trợ lý AI & tác vụ nền](#23-trợ-lý-ai--tác-vụ-nền)
24. [Cổng tích hợp & API mở](#24-cổng-tích-hợp--api-mở)
25. [Barcode / QR / Kiosk xưởng](#25-barcode--qr--kiosk-xưởng)
26. [Audit & toàn vẹn dữ liệu](#26-audit--toàn-vẹn-dữ-liệu)
27. [Hệ thống & vận hành](#27-hệ-thống--vận-hành)

---

## 1. Xác thực, tài khoản & phân quyền
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Đăng nhập (token, mật khẩu băm PBKDF2) | `POST /api/auth/login` | công khai |
| Đăng xuất (xóa phiên) | `POST /api/auth/logout` | ✅ |
| Xem / cập nhật hồ sơ cá nhân | `GET/PUT /api/auth/me` | ✅ |
| Đổi mật khẩu (verify cũ, ≥6 ký tự) | `POST /api/auth/change-password` | ✅ |
| Xem catalog quyền (21 quyền) | `GET /api/auth/permissions` | ✅ |
| Liệt kê / tạo tài khoản (role/menu/quyền/scope) | `GET/POST /api/auth/users` | *(admin)* |
| Gán phạm vi dữ liệu (line/khu vực/loại test/địa điểm kho) | `PUT /api/auth/users/{username}/scope` | *(admin)* |
| Danh mục scope (line/khu vực/QC/địa điểm kho) | `GET /api/auth/scope-catalog` | ✅ |
| Khóa / mở tài khoản | `POST /api/auth/users/{username}/toggle` | *(admin)* |
| Copy toàn bộ quyền/scope từ 1 tài khoản sang tài khoản khác | `POST /api/auth/users/{username}/copy-permissions` | *(admin)* |

**Đặc tính:** 5 vai trò thực thi (operator/supervisor/qa/engineer/admin) · 10 tài khoản demo theo **chức danh nhà máy** (Giám đốc/Quản đốc/Trưởng ca/Vận hành/KCS/Kỹ sư/Thủ kho NVL/Thủ kho phân xưởng/Bảo trì/Năng lượng), mỗi tài khoản gán `permissions`+`allowed_views`+scope riêng · 21 quyền thao tác · SoD (soạn≠duyệt, ghi QC≠release, ký≠khóa EBR) · **data-scoping 4 chiều** (line/khu vực/loại QC/**địa điểm kho** — chiều thứ 4 chặn thao tác kho ngoài Kho công ty hoặc Kho phân xưởng ở tầng server, xem mục 14) · **copy quyền** giữa 2 tài khoản (admin, ghi đè toàn bộ role/menu/quyền/4 chiều scope) · buộc đổi mật khẩu mặc định lần đầu · phiên 12h.

---

## 2. Danh mục (master data)
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Dịch bia (Product): liệt kê/tạo/sửa + thông số Braumat (`spec_json`), số ngày lên men chuẩn | `GET/POST/PUT /api/products`, `GET/PUT /api/products/{id}/brew-spec` | *(master.manage)* để ghi |
| Loại bia (BeerType): CRUD | `GET/POST/PUT/DELETE /api/master/beer-types` | *(master.manage)* |
| Sản phẩm thành phẩm (FinishedProduct — SKU): CRUD, lon/thùng, `units_per_case` | `GET/POST/PUT/DELETE /api/master/finished-products` | *(master.manage)* |
| Vật tư (Material): CRUD, tồn tối thiểu (`stock_min`), gán nhóm chỉ tiêu QC | `GET/POST/PUT/DELETE /api/master/materials`, `/materials/{id}/qc-groups` | *(master.manage)* |
| Nhóm vật tư (MaterialGroup): CRUD, cờ bao bì | `GET/POST/PUT/DELETE /api/master/material-groups` | *(master.manage)* |
| Nhà cung cấp (Supplier): CRUD | `GET/POST/PUT/DELETE /api/master/suppliers` | *(master.manage)* |
| Dây chuyền & tank (kể cả BBT/CCT): CRUD, bật/tắt | `GET/POST/PUT/DELETE /api/lines`, `/lines/{id}/toggle` | *(master.manage)* |
| Cấu hình vận hành (ngưỡng cảnh báo tuổi lô) | `GET/PUT /api/master/ops-settings` | *(master.manage)* để ghi |
| Quản lý lô vật tư | `GET/POST/PUT /api/lots` | ✅ để tạo |

**Đặc tính:** xóa có kiểm tra ràng buộc (guarded delete — chặn nếu đang được tham chiếu); chặn trùng mã + audit; Dịch bia/Loại bia/SKU dùng để scoping Nhóm chỉ tiêu chất lượng theo từng công đoạn (xem mục 10).

---

## 3. Lệnh sản xuất & Điều độ
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê / chi tiết lệnh ERP | `GET /api/orders`, `/api/orders/{id}` | công khai đọc |
| Tạo lệnh sản xuất (PO) | `POST /api/orders` | *(order.create)* |
| Bảng điều độ (lọc ngày/line) | `GET /api/workorders` | ✅ |
| Chi tiết WO + rollup planned/actual | `GET /api/workorders/{id}` | ✅ |
| Tạo Work Order (kế hoạch ngày/ca/line) | `POST /api/workorders` | ✅ |
| Chuyển trạng thái WO | `POST /api/workorders/{id}/transition` | ✅ |
| Dispatch — phát mẻ từ WO (recipe) | `POST /api/workorders/{id}/dispatch` | ✅ |

**Đặc tính:** phân tầng PO → WO → Batch; kế hoạch ngày/ca/line; % hoàn thành = Σ thực tế các mẻ / kế hoạch.

---

## 4. Lệnh nấu & Lệnh lọc (phân cấp)
*(mô hình 2 cấp: 1 lệnh cha ↔ nhiều lệnh con, mỗi lệnh con hoàn thành theo thể tích cộng dồn — thay cho việc tạo lệnh rời rạc từng mã nấu/mã lọc)*

| Tính năng | Endpoint | Quyền |
|---|---|---|
| Lệnh nấu cha: CRUD | `GET/POST/PUT/DELETE /api/brewing/brew-master-orders[/{id}]` | ✅ đọc, *(order.create)* ghi |
| Lệnh nấu con: CRUD, xem/sửa NVL kế hoạch trước khi nấu | `GET/POST/PUT/DELETE /api/brewing/orders[/{id}]`, `GET /orders/bom-preview` | ✅ đọc, *(order.create)* ghi |
| Lệnh lọc cha: CRUD | `GET/POST/PUT/DELETE /api/brewing/filter-master-orders[/{id}]` | ✅ đọc, *(order.create)* ghi |
| Lệnh lọc con: CRUD (mỗi lệnh gồm N tank nguồn CCT/BBT tái lọc, thể tích kế hoạch riêng từng tank) | `GET/POST/PUT/DELETE /api/brewing/filter-orders[/{id}]` | ✅ đọc, *(order.create)* ghi |
| In lệnh nấu / lệnh lọc (mẫu giấy) | UI (`printBrewOrder`/`printFilterOrder`/`printFilterMasterOrder`) | ✅ |

**Đặc tính:** hoàn thành theo `Σ thể tích mẻ ≥ planned_volume_hl − tolerance` (không giới hạn số lần nấu/lọc cố định); lệnh lọc hỗ trợ **tái lọc từ BBT** (không chỉ từ CCT) kèm lý do; chặn tank đã bị lệnh khác "khoá" (tank-per-order inheritance) khi đã có mẻ đầu tiên; cảnh báo/chặn khi tổng thể tích các lệnh con vượt tồn tank khả dụng.

---

## 5. Công thức & BOM
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê / tạo công thức | `GET/POST /api/recipes` | công khai đọc |
| Liệt kê / chi tiết phiên bản | `GET /api/recipes/{id}/versions`, `/versions/{vid}` | đọc |
| Tạo phiên bản mới (BOM editor) | `POST /api/recipes/{id}/versions` | *(recipe.author)* |
| Sửa phiên bản draft | `PUT /api/recipes/versions/{vid}` | *(recipe.author)* |
| Chuyển trạng thái (review/approved/effective/suspend/obsolete) | `POST /api/recipes/versions/{vid}/transition` | *(recipe.approve)* |
| Duyệt thay đổi có e-signature + lý do | `POST /api/recipes/versions/{vid}/change-approve` | *(recipe.approve)* |
| So sánh 2 phiên bản (diff) | `GET /api/recipes/diff` | ✅ |
| Lịch sử thay đổi (change-control) | `GET /api/recipes/changes` | ✅ |

**BOM / định mức NVL:** scale theo mẻ (`base_qty` → nhu cầu theo SL kế hoạch); kiểm tra tồn trước khi tạo mẻ (`GET /api/batches/availability[-alt]`); chặn consume vượt định mức trừ `allow_over`; yield theo công đoạn (`yield_steps`).

---

## 6. Mẻ sản xuất & thực thi
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê / chi tiết mẻ | `GET /api/batches`, `/api/batches/{id}` | ✅ |
| Tạo mẻ (snapshot recipe bất biến) | `POST /api/batches` | *(batch.create)* |
| Chuyển trạng thái mẻ | `POST /api/batches/{id}/transition` | *(batch.execute)* |
| Ghi thực tế (actual) tham số | `POST /api/batches/{id}/actuals` | *(batch.execute)* |
| Consume lô NVL (FEFO + genealogy) | `POST /api/batches/{id}/consume` | *(batch.execute)* |
| Produce lô output (genealogy) | `POST /api/batches/{id}/produce` | *(batch.execute)* |
| Đối chiếu BOM định mức ↔ thực tế | `GET /api/batches/{id}/bom` | ✅ |
| Hiệu suất theo công đoạn + tích lũy | `GET/POST /api/batches/{id}/yield` | *(batch.execute)* để ghi |
| Đường cong lên men (telemetry curated) | `GET/POST /api/batches/{id}/readings` | *(batch.execute)* để ghi |

**Đặc tính:** state machine kiểm soát; đối chiếu BOM hiển thị màu (đạt/vượt/thiếu/chưa dùng); đường cong °P/°C/pH vẽ SVG trong chi tiết mẻ.

---

## 7. ISA-88 — recipe/batch theo thủ tục
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Xem thủ tục recipe (procedure → UP → operation → phase) | `GET /api/isa88/recipe/{version_id}` | ✅ |
| Xem trạng thái phase của mẻ | `GET /api/isa88/batch/{batch_id}` | ✅ |
| Bắt đầu phase (unit/op/phase) | `POST /api/isa88/batch/{batch_id}/start` | *(batch.execute)* |
| Chuyển trạng thái phase (hold/resume/complete/abort) | `POST /api/isa88/phase/{run_id}/transition` | *(batch.execute)* |

**Đặc tính:** state machine phase `idle→running→held→complete/aborted`; setpoint snapshot + actual; tiến độ donut phase hoàn thành.

---

## 8. Cấp liệu (dispense/backflush)
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê phiếu cấp liệu | `GET /api/dispense` | ✅ |
| Cấp liệu cho mẻ (FEFO + chặn lô hết hạn/vượt ĐM) | `POST /api/dispense/{batch_id}` | *(batch.execute)* |
| Backflush theo BOM × tỉ lệ sản lượng | `POST /api/dispense/{batch_id}/backflush` | *(batch.execute)* |

**Đặc tính:** cấp theo lô cụ thể hoặc FEFO; backflush không trừ trùng; tái dùng logic consume → genealogy.

---

## 9. Chất lượng cơ bản
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê / ghi kết quả QC | `GET/POST /api/quality/results` | ✅ (scope theo loại test) |
| Danh sách công đoạn đang chờ khai báo QC | `GET /api/quality/pending-stage-qc` | ✅ |
| Hold / Release lô-mẻ | `POST /api/quality/hold` | *(quality.release)* khi release |
| Liệt kê / mở deviation | `GET/POST /api/quality/deviations` | *(quality.deviation)* để mở |
| Chuyển trạng thái deviation | `POST /api/quality/deviations/{id}/transition` | ✅ |

**Đặc tính:** PASS/FAIL tính theo giới hạn số học; FAIL tự đưa scope về ON HOLD; release bị chặn nếu còn FAIL chưa đóng deviation.

---

## 10. QC nâng cao — SPC / CAPA / COA / LIMS / Nhóm chỉ tiêu
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Danh sách QC parameter (SPC) | `GET/POST/PUT /api/qc/parameters[/{id}]` | ✅ đọc, ghi cần quyền |
| **Nhóm chỉ tiêu chất lượng** (tái sử dụng, gán vào NVL hoặc công đoạn) — CRUD nhóm + item | `GET/POST/PUT/DELETE /api/qc/groups[/{id}]`, `/groups/{id}/items[/{item_id}]` | ✅ đọc, ghi cần quyền |
| Gán nhóm chỉ tiêu theo công đoạn (Lên men/Lọc/Chiết), scoping theo Sản phẩm/Loại bia/SKU | `GET/POST/PUT/DELETE /api/qc/stage-groups[/{link_id}]` | ✅ đọc, ghi cần quyền |
| Gán/gỡ nhóm chỉ tiêu NVL cho từng vật tư | `GET/POST/DELETE /api/master/materials/{id}/qc-groups[/{group_id}]` | *(master.manage)* ghi |
| SPC control chart (I-MR, UCL/LCL, Western Electric, Cp/Cpk) | `GET /api/qc/spc` | ✅ |
| Liệt kê / mở / chuyển CAPA | `GET/POST /api/qc/capa`, `/capa/{id}/transition` | ✅ |
| COA — phiếu phân tích cho mẻ | `GET /api/qc/coa/{batch_id}` | ✅ |
| LIMS-lite: đăng ký / chuyển trạng thái mẫu | `GET/POST /api/qc/samples`, `/samples/{id}/transition` | ✅ (scope) |

**Đặc tính:** control chart phát hiện điểm ngoài giới hạn + luật Western Electric; Cp/Cpk; CAPA `open→investigation→action→verification→closed`; nhóm chỉ tiêu chất lượng là hạ tầng dùng chung cho cả NVL và từng công đoạn sản xuất — tránh khai báo chỉ tiêu trùng lặp theo từng vật tư/mẻ riêng lẻ.

---

## 11. Nấu–Lọc–Chiết (công đoạn chi tiết)
*(luồng sản xuất thực hệ PX Đông Mai — prefix `/api/brewing` + `/api/process`)*

| Tính năng | Endpoint | Quyền |
|---|---|---|
| Nguyên liệu công đoạn (lô PM/KCS, NCC, MSKT) | `GET/POST/DELETE /api/brewing/materials[/{id}]` | đọc công khai, ghi ✅ |
| Nấu theo mã nấu → nhiều mẻ (BrewBatch) | `GET/POST/DELETE /api/brewing/brews[/{id}]`, `/brew-batches`, `/brews/{id}/batches[/{batch_id}]` | đọc công khai, ghi ✅ |
| Kết thúc mẻ nấu | `POST /api/brewing/brews/{id}/batches/{batch_id}/finish` | ✅ |
| NVL tiêu thụ theo mẻ nấu (trừ tồn thật, sao chép giữa các mẻ) | `GET/POST/PUT/DELETE /api/brewing/brews/{id}/batches/{batch_id}/materials[/{usage_id}]` | ✅ |
| Ghi chép quy trình nấu — import PDF Braumat + biểu mẫu thủ công (QT-KCS-QT-BM-05) | `POST .../process-log/import`, `GET/PUT .../process-log` | ✅ |
| Khóa / mở khóa lô nấu | `POST /api/brewing/brews/{id}/lock-lot`, `/unlock-lot` | ✅ |
| Lên men (lô LM, tank, đời men, tồn CCT) | `GET/POST/DELETE /api/brewing/ferments[/{id}]` | đọc công khai, ghi ✅ |
| Duyệt Lên men (KCS, theo số ngày lên men chuẩn của sản phẩm) | `POST /api/brewing/ferments/{id}/approve` | *(quality.release)* |
| Nhật ký lên men hàng ngày (audit stamp-on-value) | `GET/PUT /api/brewing/ferments/{id}/process-log`, `PUT .../process-log/readings` | ✅ |
| Xả hết tank CCT | `POST /api/brewing/ferments/{id}/empty-cct` | ✅ |
| Lọc (CCT/BBT tái lọc → BBT, nhiều tank/lệnh) | `GET/POST/DELETE /api/brewing/filters[/{id}]`, `/filters/{id}/tanks`, `/bbt-tanks`, `/ferment-tanks` | đọc công khai, ghi ✅ |
| Kết thúc từng tank lọc | `POST /api/brewing/filters/{id}/tanks/{line_id}/finish` | ✅ |
| Duyệt Lọc (KCS) | `POST /api/brewing/filters/{id}/approve` | *(quality.release)* |
| NVL/hoá chất tiêu thụ theo mẻ lọc | `GET/POST/PUT/DELETE /api/brewing/filters/{id}/materials[/{usage_id}]` | ✅ |
| Xả hết BBT | `POST /api/brewing/filters/{id}/empty-bbt` | ✅ |
| Chiết (ca 1/2/3, nhiều dây chuyền, gắn SKU) | `GET/POST/DELETE /api/brewing/bottles[/{id}]` | đọc công khai, ghi ✅ |
| Kết thúc mẻ chiết (nhập ca1/2/3 + v_cap_chiet thật) | `POST /api/brewing/bottles/{id}/finish` | ✅ |
| Duyệt Chiết (tự sinh N unit thành phẩm vào WMS) | `POST /api/brewing/bottles/{id}/approve` | *(quality.release)* |
| NVL bao bì tiêu thụ theo mẻ chiết | `GET/POST/PUT/DELETE /api/brewing/bottles/{id}/materials[/{usage_id}]` | ✅ |
| Khóa/mở khóa Lên men, Lọc, Chiết | `POST .../lock-lot`, `/unlock-lot` | ✅ |
| Trạng thái QC tổng hợp theo lô/mẻ | `GET /api/brewing/qc-status` | ✅ |
| Hồ sơ lô điện tử tổng hợp (nấu→lên men→lọc→chiết) | `GET /api/brewing/lot-record` | ✅ |
| Truy xuôi tổng hợp từ mã nấu | `GET /api/brewing/brew-forward-record` | ✅ |
| Ghi kết quả QC nhanh + chỉ tiêu phân tích theo công đoạn | `POST /api/brewing/qc-results`, `GET/POST /api/brewing/indicators` | ✅ |
| Cảnh báo chỉ tiêu theo tháng/năm | `GET /api/brewing/alerts`, `/api/process/alerts` | đọc |
| Tổng hợp công đoạn (readings/QC/hóa chất) | `GET /api/process/stage-info/{batch_id}` | đọc |
| Hóa chất theo công đoạn | `GET/POST /api/process/chemicals` | đọc |
| Thu hồi men + xuất men cho mẻ | `GET/POST /api/process/yeast`, `/yeast/{id}/issue`, `/yeast/issues` | ✅ để ghi |

**Đặc tính:** màu trạng thái theo dữ liệu thật (không hardcode); **khóa lô (`locked`)** độc lập với trạng thái nghiệp vụ, chặn sửa/xóa/tiêu thụ trên cả 4 công đoạn; NVL từng mẻ nấu/lọc/chiết trừ tồn thật (Kho phân xưởng) qua `warehouse.issue()`, hoàn tác được khi xóa dòng.

---

## 12. Truy xuất, Recall & Hồ sơ lô điện tử
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Truy ngược (thành phẩm → nguyên liệu) | `GET /api/trace/backward?code=` | đọc công khai |
| Truy xuôi (nguyên liệu → sản phẩm) | `GET /api/trace/forward?code=` | đọc công khai |
| Recall simulation (lô bị ảnh hưởng + thời gian) | `GET /api/trace/recall?code=` | đọc công khai |
| Hồ sơ lô điện tử (in được) — tổng hợp toàn bộ công đoạn 1 lô | `GET /api/brewing/lot-record` (UI: nút "Hồ sơ điện tử" tại Truy xuất) | ✅ |

**Đặc tính:** dựng trên đồ thị genealogy có hướng; cây node (icon type + relation + quantity); recall đo số lô ảnh hưởng + thời gian; hồ sơ lô gộp cả bản ghi Braumat import + biểu mẫu thủ công + chữ ký KCS từng công đoạn để in trực tiếp.

---

## 13. Hồ sơ mẻ điện tử (EBR) & chữ ký điện tử
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Lắp ráp dossier EBR step-by-step | `GET /api/batches/{id}/ebr` | ✅ |
| Ký điện tử (re-auth mật khẩu) | `POST /api/batches/{id}/ebr/sign` | *(ebr.sign)* |
| Phê duyệt & khóa hồ sơ (snapshot bất biến) | `POST /api/batches/{id}/ebr/lock` | *(ebr.approve)* |

**Đặc tính:** dossier gồm header, timeline (audit), BOM định mức↔thực tế, QC, deviation, genealogy, chữ ký, hash toàn vẹn; sau khóa → mẻ bất biến (chỉ amendment).

---

## 14. Kho NVL (Kho công ty ↔ Kho phân xưởng)
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Nhập kho (mặc định vào Kho công ty) | `POST /api/warehouse/receive` | *(warehouse.receive)* |
| Nhập hoàn | `POST /api/warehouse/return` | *(warehouse.issue)* |
| Xuất/tiêu thụ (batch/manual/**tu_do** miễn phí) | `POST /api/warehouse/issue` | *(warehouse.issue)*; `tu_do`/`tu_do_px` riêng *(admin)* |
| Sang ngang (chuyển vị trí trong cùng kho) | `POST /api/warehouse/transfer` | *(warehouse.issue)* |
| Chuyển Kho phân xưởng → Kho công ty | `POST /api/warehouse/transfer-to-company` | *(warehouse.issue)* |
| Trả lại nhà cung cấp | `POST /api/warehouse/return-to-supplier` | *(warehouse.issue)* |
| Hoàn tác 1 lượt xuất/nhập | `POST /api/warehouse/movements/{id}/undo-issue` | *(warehouse.issue)* |
| Đề nghị nhận kho (Kho phân xưởng đề nghị, theo Lệnh nấu/Lệnh lọc chưa hoàn thành) — tạo/xem trước nguồn FIFO | `POST /api/warehouse/requests`, `GET /requests/source-preview` | *(warehouse.request)* tạo |
| Liệt kê / duyệt từng dòng / duyệt tất cả / từ chối / hoàn tác / huỷ phiếu | `GET /requests`, `POST /requests/{id}/lines/{lid}/fulfill[/undo-fulfill]`, `/fulfill-all`, `/reject`, `DELETE /requests/{id}` | *(warehouse.issue)* duyệt, *(warehouse.request)* huỷ phiếu của mình |
| Kiểm kê định kỳ: tạo phiếu, nhập số đếm, ghi sổ (post), duyệt, hoàn tác | `POST/GET /counts[/{id}]`, `PUT /counts/{id}/lines`, `POST /counts/{id}/post[/approve][/undo]` | *(warehouse.receive)* nhập/post, *(role supervisor/qa/engineer/admin)* duyệt |
| Lịch sử sử dụng NVL tại Kho phân xưởng (ledger theo công đoạn/mẻ/lô) | `GET /api/warehouse/workshop-usage-history` | ✅ |
| Xem tồn on-hand (mỗi kho lọc riêng) + cảnh báo tồn dưới mức tối thiểu | `GET /api/warehouse/stock`, `/low-stock` | đọc |
| FIFO chi tiết theo vật tư | `GET /api/warehouse/materials/{id}/fifo` | đọc |
| Thẻ kho (số dư lũy kế) | `GET /api/warehouse/card` | đọc |
| Báo cáo hạn sử dụng | `GET /api/warehouse/expiry` | đọc |
| BC nhập-xuất-tồn + lịch sử biến động | `GET /api/warehouse/report`, `/movements` | đọc |

**Đặc tính:** sổ cái `stock_movement` bất biến (`location_from`/`location_to` là **chuỗi tự do**, không phải enum) + hỗ trợ hoàn tác (`reversed`/`reversal_of`); thẻ kho có số dư lũy kế; cảnh báo hạn dùng + tồn tối thiểu.

> ✅ **Phân quyền theo địa điểm — enforce ở tầng server** (`scope_warehouse`, chiều data-scoping thứ 4 — §8.5/§8.7 tài liệu Kiến trúc): mỗi tài khoản có `scope_warehouse` = `"cong_ty"` | `"phan_xuong"` | `"*"`; mọi thao tác 1 địa điểm (`receive`/`return`/`issue`/kiểm kê) bị chặn 403 nếu `location` ngoài phạm vi; `transfer` (đụng 2 địa điểm) cho qua nếu khớp **ít nhất 1 đầu**. Tài khoản demo: `thukho` → Kho công ty; `thukho_px` (Thủ kho phân xưởng, mới), `truongca`, `vanhanh` → Kho phân xưởng — `truongca`/`vanhanh` chỉ có `warehouse.request` (tạo đề nghị), **`thukho_px`** mới là tài khoản thao tác trực tiếp (nhập/xuất) phía phân xưởng. Ranh giới menu (`allowed_views`) vẫn giữ nguyên, nay chỉ là lớp UI phụ trợ cho lớp chặn server này.

---

## 15. Kho thành phẩm (WMS theo LÔ) & bao bì tuần hoàn
**WMS** (`/api/wms`) — quản lý theo **LÔ** (`FinishedGoodsUnit`, thay Pallet/Case cũ; thiết kế lại 2026-07 từ "1 dòng/vỉ" sang "1 dòng/lô" để duyệt chiết không treo với lô sản lượng lớn — xem `docs/WMS-LOT-LEVEL-REDESIGN.md`): 1 dòng đại diện cả lô (`quantity` = tổng SL nhỏ), xuất/phân rã/điều chuyển/xuất tự do một phần chỉ tách dòng theo FIFO, không phải chọn/xóa từng vỉ:
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Tóm tắt WMS (theo vị trí, % lấp đầy) | `GET /api/wms/summary` | ✅ |
| Danh mục vị trí kho / nơi xuất đến / phương tiện vận chuyển | `GET/POST/PUT/DELETE /api/wms/locations[/{id}]`, `/ship-to[/{id}]`, `/vehicles[/{id}]` | *(warehouse.receive)* ghi |
| Liệt kê unit (theo vị trí, theo lô) + nhập tồn đầu thủ công | `GET /api/wms/units`, `/units/by-location`, `/units/by-lot`, `POST /api/wms/units` | ✅ |
| Cất vào vị trí (putaway) | `POST /api/wms/units/{id}/putaway` | ✅ |
| Điều chuyển vị trí | `POST /api/wms/units/transfer` | ✅ |
| Phân rã theo lô (count-based) + hoàn tác | `POST /api/wms/units/decompose-batch[/{audit_id}/undo]` | ✅ |
| Gộp/di dời cả lô (relocate) | `POST /api/wms/units/relocate-batch` | ✅ |
| Xuất tự do (miễn phí, có lý do bắt buộc) + hoàn tác + lịch sử | `POST /api/wms/units/free-issue[/{audit_id}/undo]`, `GET /free-issue-history` | *(admin)* |
| Xóa unit / xóa theo lô | `DELETE /api/wms/units/{id}`, `POST /units/delete-batch`, `/delete-by-lot` | ✅ |
| Xuất kho (Shipment) — cart FIFO theo sản phẩm/lô/loại xuất | `GET/POST /api/wms/shipments`, `POST /shipments/{id}/undo` | ✅ |
| Bia cận date: tra cứu lô-chiết, nhập thủ công, xem lịch sử, hoàn tác | `POST /api/wms/near-expiry/lookup`, `POST/GET /near-expiry`, `POST /near-expiry/{id}/undo` | ✅ |
| Lệnh đóng hàng: import Excel, xem/sửa, in | `POST /api/wms/load-slips/import`, `GET/PUT/DELETE /load-slips[/{id}]` | ✅ |
| Phân giải barcode unit | `GET /api/wms/resolve` | ✅ |

**Bao bì tuần hoàn** (`/api/packaging`):
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Danh sách loại + summary (tồn/lưu hành) | `GET /api/packaging` | ✅ |
| Khai báo loại bao bì (vỏ chai/két-gông/keg) | `POST /api/packaging` | ✅ |
| Ghi biến động (nhập/xuất/thu hồi/loại bỏ/kiểm kê) + lịch sử | `POST /api/packaging/move`, `GET /moves` | ✅ |
| Báo cáo theo lô | `GET /api/packaging/lot-report` | ✅ |

**Đặc tính:** đơn vị thành phẩm gắn trực tiếp lô sản xuất (truy xuất tới tận mẻ chiết); FIFO kiểm tra khi xuất (`fifo_ok`); phân rã/gộp theo lô (không thao tác từng unit lẻ); Xuất tự do admin-only ở cả Kho TP lẫn 2 kho NVL dùng chung 1 luật server.

---

## 16. OEE & Downtime
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê / ghi OEE theo ca | `GET/POST /api/oee` | *(supervisor/operator)* ghi |
| Cây nguyên nhân dừng máy | `GET /api/downtime/reason-tree` | ✅ |
| Liệt kê / ghi sự kiện dừng | `GET/POST /api/downtime` | ✅ |
| Pareto thời gian dừng (+% tích lũy) | `GET /api/downtime/pareto` | ✅ |
| 6 big losses | `GET /api/downtime/big-losses` | ✅ |
| MTBF / MTTR theo thiết bị | `GET /api/downtime/mtbf` | ✅ |

**Đặc tính:** OEE = Availability × Performance × Quality; reason-tree nhóm→lý do; loss_category → 6 big losses.

---

## 17. Bảo trì & Kiểm định (CMMS)
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Danh mục thiết bị | `GET/POST /api/maint/equipment` | *(maintenance.manage)* tạo |
| Danh mục phụ tùng (cảnh báo tồn min) | `GET/POST /api/maint/parts` | đọc/ghi |
| Báo cáo sự cố + xử lý | `GET/POST /api/maint/incidents`, `/incidents/{id}/resolve` | *(maintenance.manage)* |
| Kế hoạch bảo trì/kiểm tra/tu bổ (tự đánh dấu quá hạn) | `GET/POST /api/maint/plans`, `/plans/{id}/done` | *(maintenance.manage)* |
| Kiểm định/hiệu chuẩn | `GET/POST /api/maint/calibrations` | *(calibration.manage)* tạo |

**Đặc tính:** kế hoạch tự đánh dấu `overdue`; kiểm định valid/due/overdue theo hạn; cảnh báo phụ tùng dưới tồn min.

---

## 18. Năng lượng
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Nhóm/khu vực năng lượng (nội bộ, nhập tay) | `GET/POST /api/energy/groups`, `/areas` | *(energy.update)* tạo |
| Upsert số đọc ngày (1 số đọc/ngày/nhóm/khu) | `POST /api/energy/readings` | *(energy.update)* |
| Biểu đồ ngày/tổng hợp tháng (nội bộ) | `GET /api/energy/daily`, `/monthly` | đọc |
| Báo cáo năng lượng có nhóm theo khu vực (chart) | `GET /api/energy/report` | đọc |
| Danh sách site năng lượng ngoài (Hạ Long/Đông Mai…) | `GET /api/energy/external-sites` | đọc |
| Điện thật từ SCADA ngoài — khoảng ngày/theo ca | `GET /api/energy/external-bounds`, `/external-report`, `/external-ca-report` | đọc |

**Đặc tính:** năng lượng nội bộ = nhập tay upsert theo ngày; điện thật đọc trực tiếp CSDL SCADA ngoài theo site (mỗi nhà máy 1 `purpose` token riêng, không lẫn giữa Hạ Long/Đông Mai) — xem mục 19.

---

## 19. Tích hợp CSDL SCADA ngoài & Realtime thật
*(tính năng mới — kết nối trực tiếp CSDL SQL Server của hệ SCADA/WinCC thật ngoài nhà máy, chỉ đọc)*

| Tính năng | Endpoint | Quyền |
|---|---|---|
| Khai báo / sửa / xóa kết nối CSDL ngoài | `GET/POST/PUT/DELETE /api/integration/connections[/{id}]` | *(admin)* |
| Test kết nối (thủ công + tự động thử lại mỗi 15s cho kết nối đang lỗi) | `POST /api/integration/connections/{id}/test` | *(admin)* |
| Xem trước bảng (cột + mẫu dữ liệu, chỉ đọc) | `GET /api/integration/connections/{id}/preview-table` | *(admin)* |
| Liệt kê bảng/view sẵn có | `GET /api/integration/connections/{id}/tables` | *(admin)* |
| Báo cáo sản lượng chiết lon thật (30K_Report, theo ca/tháng) | `GET /api/reports/filling-bounds`, `/filling-report` | ✅ |
| **Realtime máy chiết lon "30K"** (snapshot 1 dòng: trạng thái máy, lưu lượng, tốc độ, sản lượng/số lon lũy kế) | `GET /api/reports/filling-realtime` | ✅ |
| Báo cáo sản lượng chiết keg thật | `GET /api/reports/keg-bounds`, `/keg-report` | ✅ |
| **Realtime trạm quan trắc nước thải Hạ Long** (pH/nhiệt độ/TSS/COD/NH4/lưu lượng vào-ra, badge vượt chuẩn QCVN 40:2011/BTNMT) | `GET /api/reports/wastewater-realtime` | ✅ |
| Điện thật theo site/theo ca (xem mục 18) | `GET /api/energy/external-*` | đọc |

**Đặc tính:**
- 1 kết nối vật lý gán **nhiều `purpose`** (VD `energy_dm,filling`) — module tự tìm đúng kết nối qua `get_connection_by_purpose()`.
- Panel Realtime **chỉ hiển thị nguyên văn cột nguồn** — không tính tốc độ/suy diễn thêm từ nhiều lần đọc; tự làm mới mỗi 15 giây; báo lỗi rõ ràng khi WAN timeout (không kẹt màn hình "Đang tải…").
- Không còn cột "Dùng cho" dạng checkbox thủ công trong UI — gán `purpose` cho kết nối do người vận hành hệ thống thực hiện trực tiếp khi cần thêm nguồn dữ liệu mới.

---

## 20. Import dữ liệu ngoài & trường tùy biến
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Danh mục bảng đích + cấu trúc cột | `GET /api/import/targets[/{table}]` | ✅ |
| Trường tùy biến (custom field): xem/tạo/xóa theo bảng | `GET/POST/DELETE /api/import/custom-fields[/{table}/{key}]` | *(integration.import)* ghi |
| Xem giá trị custom field của 1 bản ghi | `GET /api/import/records/{table}/{id}/custom` | ✅ |
| Tra cứu nhanh theo mã | `GET /api/import/lookup/{table}/{code}` | ✅ |
| Upload file + xem trước | `POST /api/import/upload`, `GET /preview/{file_id}` | *(integration.import)* |
| Xác thực dữ liệu trước khi chạy | `POST /api/import/validate` | *(integration.import)* |
| Chạy import (ghi vào bảng đích) | `POST /api/import/run` | *(integration.import)* |
| Xuất kết quả / lịch sử / lỗi từng dòng | `GET /api/import/export/{run_id}`, `/history`, `/errors/{run_id}` | ✅ |
| Lưu / tái sử dụng profile ánh xạ cột | `GET/POST /api/import/profiles[/{id}]` | *(integration.import)* ghi |

**Đặc tính:** custom field cho phép thêm cột tùy biến vào NVL/lô mà không cần đổi schema cứng (xóa mềm/ẩn hoặc xóa cứng); profile ánh xạ tái sử dụng cho các đợt import sau, tránh phải map lại cột từ đầu mỗi lần.

---

## 21. Lập lịch sản xuất tối ưu
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Bảng lịch Gantt | `GET /api/schedule` | ✅ |
| Liệt kê xung đột | `GET /api/schedule/conflicts` | ✅ |
| Tự lập lịch (greedy earliest-fit + CIP + né bảo trì + check NVL) | `POST /api/schedule/auto` | *(wo.dispatch)* |

**Đặc tính:** xếp WO lên tank/line không chồng lấn; CIP bắt buộc giữa mẻ; phát hiện xung đột & thiếu NVL; Gantt SVG.

---

## 22. Báo cáo
| Tính năng | Endpoint | Quyền |
|---|---|---|
| BC định mức NVL (gộp nhiều mẻ, 30/90/365 ngày) | `GET /api/reports/material-norm` | ✅ |
| BC sản lượng chiết lon/keg (SCADA thật) | `GET /api/reports/filling-report`, `/keg-report` | ✅ |
| Trạng thái lô tổng hợp (Nấu/Lên men/Lọc/Chiết) | `GET /api/reports/lo-status` | ✅ |
| Tổng hợp Dashboard (lệnh/mẻ + sản lượng chiết) | `GET /api/reports/dashboard-summary` | ✅ |
| Cảnh báo QC cần xử lý (lô hold / deviation mở / chỉ tiêu fail) | `GET /api/reports/qc-attention-alerts` | ✅ |
| Tồn kho thành phẩm theo tuổi lô | `GET /api/reports/inventory-aging` | ✅ |
| Tồn dưới mức tối thiểu (NVL) | `GET /api/warehouse/low-stock` | ✅ |

**Đặc tính:** gộp định mức(scale) ↔ thực tế theo vật tư qua nhiều mẻ; dashboard tổng hợp trực quan có biểu đồ; cảnh báo QC gộp 3 nguồn (hold/deviation/fail) tránh trùng lặp 1 lô nhiều dòng.

---

## 23. Trợ lý AI & tác vụ nền
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Trạng thái LLM + danh sách tool | `GET /api/ai/status` | công khai |
| Chat có bộ nhớ / streaming (SSE) | `POST /api/ai/chat`, `/chat/stream` | ✅ |
| Liệt kê / xem / xóa hội thoại | `GET/DELETE /api/ai/conversations[/{id}]` | ✅ |
| AI insights (cảnh báo & đề xuất ưu tiên) | `GET /api/ai/insights` | ✅ |
| Manifest tool cho AI agent/MCP | `GET /api/ai/tools` | ✅ |
| Liệt kê / submit / poll tác vụ nền | `GET/POST /api/jobs`, `/jobs/{id}` | ✅ |

**Đặc tính:** Claude (tool-use) hoặc engine luật offline; tool read-only; advisory-only; rate-limit + hạn mức chat/ngày.

---

## 24. Cổng tích hợp & API mở
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Ping / batches / inventory / oee / energy / quality alerts / traceability | `GET /api/v1/*` | *(X-API-Key read)* |
| Feed sự kiện | `GET /api/v1/events?since_seq=` | *(X-API-Key read)* |
| Nhận sự kiện ngoài (qua record_audit) | `POST /api/v1/events` | *(X-API-Key write)* |
| Quản lý API key (tạo/khóa) | `GET/POST /api/integration/keys`, `/keys/{id}/revoke` | *(admin)* |
| Quản lý webhook (đăng ký/tắt) | `GET/POST /api/integration/webhooks`, `/webhooks/{id}/disable` | *(admin)* |

**Đặc tính:** API key scope read/write + đếm lượt gọi; webhook event_types + HMAC secret; sự kiện ngoài không làm gãy hash-chain audit.

---

## 25. Barcode / QR / Kiosk xưởng
| Tính năng | Endpoint / nơi dùng | Quyền |
|---|---|---|
| Sinh QR (SVG) cho tem | `GET /api/label/qr` | ✅ |
| Quét mã → phân giải lô/mẻ/WO/đơn/unit thành phẩm | `GET /api/scan`, `/api/wms/resolve` | ✅ |
| Mẻ đang chạy (cho kiosk cấp liệu) | `GET /api/scan/running-batches` | ✅ |
| Kiosk: đăng nhập, quét, cấp liệu nhanh, in tem Code39 | `/kiosk.html` | ✅ |

**Đặc tính:** giao diện cảm ứng cho tablet/scanner; chặn vượt định mức; in tem Code39 trực tiếp.

---

## 26. Audit & toàn vẹn dữ liệu
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê audit log (lọc entity) | `GET /api/audit` | đọc |
| Kiểm tra toàn vẹn hash-chain | `GET /api/audit/verify-chain` | đọc |

**Đặc tính:** append-only (không có API sửa/xóa); `entry_hash = sha256(prev_hash + nội dung)`; `seq` UNIQUE chống race.

---

## 27. Hệ thống & vận hành
| Tính năng | Endpoint / cơ chế |
|---|---|
| Health/readiness (kiểm tra DB) | `GET /api/health` |
| Metrics Prometheus | `GET /metrics` |
| Swagger / OpenAPI | `GET /docs` |
| Rate-limit (login/AI) + hạn mức AI/ngày | middleware `ratelimit.py` |
| Structured logging + request-id | `logging_config.py` |
| Tác vụ nền | `ThreadPoolExecutor` (`services/jobs.py`) |
| Migration | Alembic (~90 file) |
| Đóng gói | Docker + docker-compose (app + PostgreSQL 16) |
| Backup/Restore + test khôi phục | `scripts/backup.sh` · `restore.sh` · `test_restore.sh` |
| CI | GitHub Actions (ruff + pytest + docker build) |

---

## Tổng kết phạm vi
- **32 router · ~379 endpoint · ~100 lớp dữ liệu (31 file model) · 47 service nghiệp vụ · 57 file test · ~90 migration.**
- **13/13 phân hệ "MES hardcore"** hoàn thành, cộng thêm các phân hệ mở rộng theo yêu cầu vận hành thực tế PX Đông Mai: Lệnh nấu/Lệnh lọc phân cấp, Kho NVL 2 địa điểm (đề nghị nhận kho + kiểm kê định kỳ), WMS theo unit thành phẩm, Nhóm chỉ tiêu chất lượng dùng chung theo công đoạn, Tích hợp CSDL SCADA ngoài + Realtime thật (chiết lon/keg/điện/nước thải), Import dữ liệu ngoài + trường tùy biến.
- Tích hợp thiết bị OT lớp historian nội bộ vẫn ở dạng mô phỏng edge; panel Realtime SCADA (mục 19) đã là **dữ liệu thật qua WAN**, không còn mô phỏng.
