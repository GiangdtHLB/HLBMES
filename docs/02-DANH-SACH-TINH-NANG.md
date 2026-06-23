# Danh sách Tính năng — MES Bia Hạ Long (Nhà Máy Đông Mai)

> Liệt kê đầy đủ các tính năng *đã hiện thực trong mã nguồn*, nhóm theo phân hệ.
> Mỗi tính năng kèm endpoint API và quyền yêu cầu (nếu có). Phiên bản: `0.1.0-mvp`.

**Quy ước cột "Quyền":** ✅ = đăng nhập là đủ · *(permission)* = cần quyền thao tác cụ thể · *(role)* = cần vai trò · *(X-API-Key)* = cho phần mềm ngoài.

---

## Mục lục phân hệ
1. [Xác thực, tài khoản & phân quyền](#1-xác-thực-tài-khoản--phân-quyền)
2. [Danh mục (master data)](#2-danh-mục-master-data)
3. [Lệnh sản xuất & Điều độ](#3-lệnh-sản-xuất--điều-độ)
4. [Công thức & BOM](#4-công-thức--bom)
5. [Mẻ sản xuất & thực thi](#5-mẻ-sản-xuất--thực-thi)
6. [ISA-88 — recipe/batch theo thủ tục](#6-isa-88--recipebatch-theo-thủ-tục)
7. [Cấp liệu (dispense/backflush)](#7-cấp-liệu-dispensebackflush)
8. [Chất lượng cơ bản](#8-chất-lượng-cơ-bản)
9. [QC nâng cao — SPC / CAPA / COA / LIMS](#9-qc-nâng-cao--spc--capa--coa--lims)
10. [Nấu–Lọc–Chiết (công đoạn chi tiết)](#10-nấulọcchiết-công-đoạn-chi-tiết)
11. [Truy xuất & Recall](#11-truy-xuất--recall)
12. [Hồ sơ mẻ điện tử (EBR) & chữ ký điện tử](#12-hồ-sơ-mẻ-điện-tử-ebr--chữ-ký-điện-tử)
13. [Kho NVL (warehouse)](#13-kho-nvl-warehouse)
14. [Kho thành phẩm (WMS) & bao bì tuần hoàn](#14-kho-thành-phẩm-wms--bao-bì-tuần-hoàn)
15. [OEE & Downtime](#15-oee--downtime)
16. [Bảo trì & Kiểm định (CMMS)](#16-bảo-trì--kiểm-định-cmms)
17. [Năng lượng](#17-năng-lượng)
18. [Historian & Realtime (edge OT)](#18-historian--realtime-edge-ot)
19. [Lập lịch sản xuất tối ưu](#19-lập-lịch-sản-xuất-tối-ưu)
20. [Báo cáo](#20-báo-cáo)
21. [Trợ lý AI & tác vụ nền](#21-trợ-lý-ai--tác-vụ-nền)
22. [Cổng tích hợp & API mở](#22-cổng-tích-hợp--api-mở)
23. [Barcode / QR / Kiosk xưởng](#23-barcode--qr--kiosk-xưởng)
24. [Audit & toàn vẹn dữ liệu](#24-audit--toàn-vẹn-dữ-liệu)
25. [Hệ thống & vận hành](#25-hệ-thống--vận-hành)

---

## 1. Xác thực, tài khoản & phân quyền
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Đăng nhập (token, mật khẩu băm PBKDF2) | `POST /api/auth/login` | công khai |
| Đăng xuất (xóa phiên) | `POST /api/auth/logout` | ✅ |
| Xem hồ sơ cá nhân | `GET /api/auth/me` | ✅ |
| Cập nhật họ tên | `PUT /api/auth/me` | ✅ |
| Đổi mật khẩu (verify cũ, ≥6 ký tự) | `POST /api/auth/change-password` | ✅ |
| Xem catalog quyền | `GET /api/auth/permissions` | ✅ |
| Liệt kê tài khoản | `GET /api/auth/users` | *(admin)* |
| Tạo tài khoản (role/menu/quyền/scope) | `POST /api/auth/users` | *(admin)* |
| Gán phạm vi dữ liệu (line/khu vực/loại test) | `PUT /api/auth/users/{username}/scope` | *(admin)* |
| Danh mục scope (line/khu vực/QC) | `GET /api/auth/scope-catalog` | ✅ |
| Khóa / mở tài khoản | `POST /api/auth/users/{username}/toggle` | *(admin)* |

**Đặc tính:** 5 vai trò (operator/supervisor/qa/engineer/admin) · 19 quyền thao tác · Segregation of Duties (soạn≠duyệt, ghi QC≠release, ký≠khóa EBR) · data-scoping 3 chiều · buộc đổi mật khẩu mặc định lần đầu · phiên 12h · audit `login/logout/login_failed/change_password`.

---

## 2. Danh mục (master data)
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê / tạo / sửa sản phẩm | `GET/POST/PUT /api/products` | *(master.manage)* để ghi |
| Liệt kê / tạo / sửa vật tư | `GET/POST/PUT /api/materials` | *(master.manage)* để ghi |
| Liệt kê / tạo dây chuyền & tank | `GET/POST /api/lines` | *(master.manage)* |
| Bật/tắt dây chuyền | `POST /api/lines/{id}/toggle` | *(master.manage)* |
| Quản lý lô vật tư | `GET/POST /api/lots` | ✅ để tạo |

**Đặc tính:** chặn trùng mã + audit; sản phẩm mới dùng được ngay khi tạo công thức/lệnh SX.

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

**Đặc tính:** phân tầng PO → WO → Batch; kế hoạch ngày/ca/line; % hoàn thành = Σ thực tế các mẻ / kế hoạch; planned vs actual.

---

## 4. Công thức & BOM
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

**BOM / định mức NVL:**
- BOM gắn theo phiên bản (`base_qty` + dòng `{material_code, qty, uom, tol_pct}`).
- **Scale theo mẻ**: nhu cầu = định mức × (SL kế hoạch / base_qty); snapshot bất biến vào mẻ.
- **Kiểm tra tồn trước khi tạo mẻ**: `GET /api/batches/availability` — nhu cầu BOM ↔ tồn khả dụng; thiếu → chặn 409 trừ `allow_shortage`.
- **Nguyên liệu thay thế**: `GET /api/batches/availability-alt` — gợi ý vật tư thay thế + hệ số.
- **Chặn consume vượt định mức**: ngưỡng = định mức(scale) × (1 + dung sai%); vượt → 409 trừ `allow_over`.
- **Yield theo công đoạn** (`yield_steps`): kỳ vọng & cảnh báo dưới ngưỡng.

---

## 5. Mẻ sản xuất & thực thi
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê mẻ (lọc theo scope line) | `GET /api/batches` | ✅ |
| Chi tiết mẻ | `GET /api/batches/{id}` | ✅ |
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

## 6. ISA-88 — recipe/batch theo thủ tục
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Xem thủ tục recipe (procedure → UP → operation → phase) | `GET /api/isa88/recipe/{version_id}` | ✅ |
| Xem trạng thái phase của mẻ | `GET /api/isa88/batch/{batch_id}` | ✅ |
| Bắt đầu phase (unit/op/phase) | `POST /api/isa88/batch/{batch_id}/start` | *(batch.execute)* |
| Chuyển trạng thái phase (hold/resume/complete/abort) | `POST /api/isa88/phase/{run_id}/transition` | *(batch.execute)* |

**Đặc tính:** state machine phase `idle→running→held→complete/aborted`; setpoint snapshot + actual; gồm CIP/SIP; tiến độ donut phase hoàn thành.

---

## 7. Cấp liệu (dispense/backflush)
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê phiếu cấp liệu | `GET /api/dispense` | ✅ |
| Cấp liệu cho mẻ (FEFO + chặn lô hết hạn/vượt ĐM) | `POST /api/dispense/{batch_id}` | *(batch.execute)* |
| Backflush theo BOM × tỉ lệ sản lượng | `POST /api/dispense/{batch_id}/backflush` | *(batch.execute)* |

**Đặc tính:** cấp theo lô cụ thể hoặc FEFO (hết hạn trước xuất trước); backflush không trừ trùng; tái dùng logic consume → genealogy.

---

## 8. Chất lượng cơ bản
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê / ghi kết quả QC | `GET/POST /api/quality/results` | ✅ (scope theo loại test) |
| Hold / Release lô-mẻ | `POST /api/quality/hold` | *(quality.release)* khi release |
| Liệt kê / mở deviation | `GET/POST /api/quality/deviations` | *(quality.deviation)* để mở |
| Chuyển trạng thái deviation | `POST /api/quality/deviations/{id}/transition` | ✅ |

**Đặc tính:** PASS/FAIL tính theo giới hạn số học; FAIL tự đưa scope về ON HOLD; release bị chặn nếu còn FAIL chưa đóng deviation; deviation workflow `open→…→closed`.

---

## 9. QC nâng cao — SPC / CAPA / COA / LIMS
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Danh sách QC parameter (SPC) | `GET /api/qc/parameters` | ✅ |
| SPC control chart (I-MR, UCL/LCL, Western Electric, Cp/Cpk) | `GET /api/qc/spc` | ✅ |
| Liệt kê / mở / chuyển CAPA | `GET/POST /api/qc/capa`, `/capa/{id}/transition` | ✅ |
| COA — phiếu phân tích cho mẻ | `GET /api/qc/coa/{batch_id}` | ✅ |
| LIMS-lite: đăng ký / chuyển trạng thái mẫu | `GET/POST /api/qc/samples`, `/samples/{id}/transition` | ✅ (scope) |

**Đặc tính:** control chart phát hiện điểm ngoài giới hạn + luật Western Electric; Cp/Cpk; CAPA `open→investigation→action→verification→closed`; COA tổng hợp chỉ tiêu + kết luận; mẫu `registered→in_test→completed`.

---

## 10. Nấu–Lọc–Chiết (công đoạn chi tiết)
*(mô phỏng luồng sản xuất thực hệ PX Đông Mai — prefix `/api/brewing` + `/api/process`)*

| Tính năng | Endpoint | Quyền |
|---|---|---|
| Nguyên liệu (lô PM/KCS, NCC, MSKT) | `GET/POST /api/brewing/materials` | đọc công khai |
| Nấu (dịch nha, °P, độ hòa tan) | `GET/POST /api/brewing/brews` | đọc công khai |
| Lên men (lô LM, tank, đời men, tồn CCT) | `GET/POST /api/brewing/ferments` | đọc công khai |
| Lọc (CCT→BBT, trạng thái chiết) | `GET/POST /api/brewing/filters` | đọc công khai |
| Chiết (theo ca 1/2/3, dây chuyền) | `GET/POST /api/brewing/bottles` | đọc công khai |
| Duyệt chiết | `POST /api/brewing/bottles/{id}/approve` | ✅ |
| Chỉ tiêu phân tích theo công đoạn | `GET/POST /api/brewing/indicators` | ✅ để ghi |
| Cảnh báo chỉ tiêu theo tháng/năm | `GET /api/brewing/alerts`, `/api/process/alerts` | đọc |
| Tổng hợp công đoạn (readings/QC/hóa chất) | `GET /api/process/stage-info/{batch_id}` | đọc |
| Hóa chất theo công đoạn | `GET/POST /api/process/chemicals` | đọc |
| Thu hồi men + xuất men cho mẻ | `GET/POST /api/process/yeast`, `/yeast/{id}/issue`, `/yeast/issues` | ✅ để ghi |

**Đặc tính:** màu trạng thái dữ liệu (đỏ=thiếu thông tin, xanh lá=chưa nhập NVL, xanh dương=đầy đủ, xanh nhạt=lọc vào BBT phối); engine cảnh báo quét mẻ thiếu Plato/độ hòa tan, chiết sai sản lượng, lọc chưa nhập chỉ tiêu.

---

## 11. Truy xuất & Recall
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Truy ngược (thành phẩm → nguyên liệu) | `GET /api/trace/backward?code=` | đọc công khai |
| Truy xuôi (nguyên liệu → sản phẩm) | `GET /api/trace/forward?code=` | đọc công khai |
| Recall simulation (lô bị ảnh hưởng + thời gian) | `GET /api/trace/recall?code=` | đọc công khai |

**Đặc tính:** dựng trên đồ thị genealogy có hướng; hiển thị cây node (icon type + relation + quantity); recall đo số lô ảnh hưởng + thời gian (ms).

---

## 12. Hồ sơ mẻ điện tử (EBR) & chữ ký điện tử
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Lắp ráp dossier EBR step-by-step | `GET /api/batches/{id}/ebr` | ✅ |
| Ký điện tử (re-auth mật khẩu) | `POST /api/batches/{id}/ebr/sign` | *(ebr.sign)* |
| Phê duyệt & khóa hồ sơ (snapshot bất biến) | `POST /api/batches/{id}/ebr/lock` | *(ebr.approve)* |

**Đặc tính:** dossier gồm header (lệnh/WO/recipe/SL), timeline thao tác (từ audit), BOM định mức↔thực tế, QC, deviation, hóa chất, genealogy, chữ ký, hash toàn vẹn; ký yêu cầu nhập lại mật khẩu + ý nghĩa/lý do (21 CFR Part 11); sau khóa → mẻ bất biến (chỉ amendment).

---

## 13. Kho NVL (warehouse)
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Nhập kho | `POST /api/warehouse/receive` | *(warehouse.receive)* |
| Nhập hoàn | `POST /api/warehouse/return` | *(warehouse.issue)* |
| Xuất/tiêu thụ (batch/manual/cogs) | `POST /api/warehouse/issue` | *(warehouse.issue)* |
| Sang ngang (chuyển vị trí) | `POST /api/warehouse/transfer` | *(warehouse.issue)* |
| Xem tồn on-hand | `GET /api/warehouse/stock` | đọc |
| Thẻ kho (số dư lũy kế) | `GET /api/warehouse/card` | đọc |
| Báo cáo hạn sử dụng | `GET /api/warehouse/expiry` | đọc |
| BC nhập-xuất-tồn | `GET /api/warehouse/report` | đọc |

**Đặc tính:** sổ cái `stock_movement` bất biến (qty luôn dương, dấu suy từ loại); thẻ kho có số dư lũy kế; cảnh báo hạn dùng.

---

## 14. Kho thành phẩm (WMS) & bao bì tuần hoàn
**WMS** (`/api/wms`):
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Tóm tắt WMS (pallet/case/vị trí, % lấp đầy) | `GET /api/wms/summary` | ✅ |
| Quản lý vị trí kho | `GET/POST /api/wms/locations` | *(warehouse.receive)* tạo |
| Liệt kê / dựng pallet (+ case + barcode) | `GET/POST /api/wms/pallets` | ✅ |
| Putaway pallet vào vị trí | `POST /api/wms/pallets/{id}/putaway` | ✅ |
| Ship pallet | `POST /api/wms/pallets/{id}/ship` | ✅ |
| Phân giải barcode pallet/case | `GET /api/wms/resolve` | ✅ |

**Bao bì tuần hoàn** (`/api/packaging`):
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Danh sách loại + summary (tồn/lưu hành) | `GET /api/packaging` | ✅ |
| Khai báo loại bao bì (vỏ chai/két-gông/keg) | `POST /api/packaging` | ✅ |
| Ghi biến động (nhập/xuất/thu hồi/loại bỏ/kiểm kê) | `POST /api/packaging/move` | ✅ |
| Lịch sử biến động | `GET /api/packaging/moves` | ✅ |

**Đặc tính:** pallet/case barcode Code39; tiền cược (deposit); chặn kiểm kê số lượng âm.

---

## 15. OEE & Downtime
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê / ghi OEE theo ca | `GET/POST /api/oee` | *(supervisor/operator)* ghi |
| Cây nguyên nhân dừng máy | `GET /api/downtime/reason-tree` | ✅ |
| Liệt kê / ghi sự kiện dừng | `GET/POST /api/downtime` | ✅ |
| Pareto thời gian dừng (+% tích lũy) | `GET /api/downtime/pareto` | ✅ |
| 6 big losses | `GET /api/downtime/big-losses` | ✅ |
| MTBF / MTTR theo thiết bị | `GET /api/downtime/mtbf` | ✅ |

**Đặc tính:** OEE = Availability × Performance × Quality (gauge donut + phân rã A/P/Q); reason-tree nhóm→lý do; loss_category (availability/performance/quality) → 6 big losses.

---

## 16. Bảo trì & Kiểm định (CMMS)
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Danh mục thiết bị | `GET/POST /api/maint/equipment` | *(maintenance.manage)* tạo |
| Danh mục phụ tùng (cảnh báo tồn min) | `GET/POST /api/maint/parts` | đọc/ghi |
| Báo cáo sự cố + xử lý | `GET/POST /api/maint/incidents`, `/incidents/{id}/resolve` | *(maintenance.manage)* |
| Kế hoạch bảo trì/kiểm tra/tu bổ (tự đánh dấu quá hạn) | `GET/POST /api/maint/plans`, `/plans/{id}/done` | *(maintenance.manage)* |
| Kiểm định/hiệu chuẩn (phóng xạ/van an toàn/hiệu chuẩn TBĐ/YCNNVAT) | `GET/POST /api/maint/calibrations` | *(calibration.manage)* tạo |

**Đặc tính:** kế hoạch tự đánh dấu `overdue`; kiểm định trạng thái valid/due/overdue theo hạn; cảnh báo phụ tùng dưới tồn min.

---

## 17. Năng lượng
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Nhóm năng lượng (điện/nước/hơi/khí) | `GET/POST /api/energy/groups` | *(energy.update)* tạo |
| Khu vực năng lượng | `GET/POST /api/energy/areas` | *(energy.update)* tạo |
| Upsert số đọc ngày | `POST /api/energy/readings` | *(energy.update)* |
| Biểu đồ ngày theo nhóm | `GET /api/energy/daily` | đọc |
| Tổng hợp tháng | `GET /api/energy/monthly` | đọc |

**Đặc tính:** chỉ 1 số đọc/ngày/nhóm/khu (upsert); biểu đồ line theo nhóm.

---

## 18. Historian & Realtime (edge OT)
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Ingest telemetry từ edge | `POST /api/historian/ingest` | *(X-API-Key write)* |
| Liệt kê tag có sẵn | `GET /api/historian/tags` | ✅ |
| Giá trị mới nhất mọi tag | `GET /api/historian/latest` | ✅ |
| Time-series 1 tag (downsample min/avg/max) | `GET /api/historian/series` | ✅ |
| Mô phỏng 1 nhịp (demo) | `POST /api/historian/simulate` | ✅ |

**Đặc tính:** tag UNS `brewery/site/area/device/metric`; tab Realtime auto-refresh 4s; edge_sim đẩy 8 tag; client OPC UA thật (asyncua) ánh xạ Weihenstephan.

---

## 19. Lập lịch sản xuất tối ưu
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Bảng lịch Gantt | `GET /api/schedule` | ✅ |
| Liệt kê xung đột | `GET /api/schedule/conflicts` | ✅ |
| Tự lập lịch (greedy earliest-fit + CIP + né bảo trì + check NVL) | `POST /api/schedule/auto` | *(wo.dispatch)* |

**Đặc tính:** xếp WO lên tank/line không chồng lấn; CIP bắt buộc giữa mẻ; bảo trì khóa tài nguyên; phát hiện xung đột & thiếu NVL; Gantt SVG.

---

## 20. Báo cáo
| Tính năng | Endpoint | Quyền |
|---|---|---|
| BC định mức NVL (gộp nhiều mẻ, 30/90/365 ngày) | `GET /api/reports/material-norm` | ✅ |

**Đặc tính:** gộp định mức(scale) ↔ thực tế theo vật tư qua nhiều mẻ + chênh lệch/% + trạng thái; kèm bảng theo mẻ; dùng đúng dung sai từng vật tư, chỉ tính mẻ đã chạy.

---

## 21. Trợ lý AI & tác vụ nền
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Trạng thái LLM + danh sách tool | `GET /api/ai/status` | công khai |
| Chat có bộ nhớ | `POST /api/ai/chat` | ✅ |
| Chat streaming (SSE, hiện token dần) | `POST /api/ai/chat/stream` | ✅ |
| Liệt kê / xem / xóa hội thoại | `GET/DELETE /api/ai/conversations[/{id}]` | ✅ |
| AI insights (cảnh báo & đề xuất ưu tiên) | `GET /api/ai/insights` | ✅ |
| Manifest tool cho AI agent/MCP | `GET /api/ai/tools` | ✅ |
| Liệt kê / submit / poll tác vụ nền | `GET/POST /api/jobs`, `/jobs/{id}` | ✅ |

**Đặc tính:** Claude `claude-opus-4-8` (tool-use) hoặc engine luật offline; 8 tool read-only; advisory-only (không hành động); rate-limit + hạn mức 300 chat/ngày; job nền `ai_report`/`recall`.

---

## 22. Cổng tích hợp & API mở
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Ping / batches / inventory / oee / energy / quality alerts / traceability | `GET /api/v1/*` | *(X-API-Key read)* |
| Feed sự kiện | `GET /api/v1/events?since_seq=` | *(X-API-Key read)* |
| Nhận sự kiện ngoài (qua record_audit) | `POST /api/v1/events` | *(X-API-Key write)* |
| Quản lý API key (tạo/khóa) | `GET/POST /api/integration/keys`, `/keys/{id}/revoke` | *(admin)* |
| Quản lý webhook (đăng ký/tắt) | `GET/POST /api/integration/webhooks`, `/webhooks/{id}/disable` | *(admin)* |

**Đặc tính:** API key scope read/write + đếm lượt gọi; webhook event_types + HMAC secret; sự kiện ngoài không làm gãy hash-chain audit.

---

## 23. Barcode / QR / Kiosk xưởng
| Tính năng | Endpoint / nơi dùng | Quyền |
|---|---|---|
| Sinh QR (SVG) cho tem | `GET /api/label/qr` | ✅ |
| Quét mã → phân giải lô/mẻ/WO/đơn | `GET /api/scan` | ✅ |
| Mẻ đang chạy (cho kiosk cấp liệu) | `GET /api/scan/running-batches` | ✅ |
| Kiosk: đăng nhập, quét, cấp liệu nhanh, in tem Code39 | `/kiosk.html` | ✅ |

**Đặc tính:** giao diện cảm ứng cho tablet/scanner; nút SL lớn; chặn vượt định mức; in tem Code39 trực tiếp.

---

## 24. Audit & toàn vẹn dữ liệu
| Tính năng | Endpoint | Quyền |
|---|---|---|
| Liệt kê audit log (lọc entity) | `GET /api/audit` | đọc |
| Kiểm tra toàn vẹn hash-chain | `GET /api/audit/verify-chain` | đọc |

**Đặc tính:** append-only (không có API sửa/xóa); `entry_hash = sha256(prev_hash + nội dung)`; `seq` UNIQUE chống race; phát hiện đúng vị trí bị giả mạo.

---

## 25. Hệ thống & vận hành
| Tính năng | Endpoint / cơ chế |
|---|---|
| Health/readiness (kiểm tra DB) | `GET /api/health` |
| Metrics Prometheus | `GET /metrics` |
| Swagger / OpenAPI | `GET /docs` |
| Rate-limit (login/AI) + hạn mức AI/ngày | middleware `ratelimit.py` (in-proc / Redis) |
| Structured logging + request-id + log chi phí AI | `logging_config.py` |
| Tác vụ nền | `ThreadPoolExecutor` (`services/jobs.py`) |
| Migration | Alembic |
| Đóng gói | Docker + docker-compose (app + PostgreSQL 16) |
| Backup/Restore + test khôi phục | `scripts/backup.sh` · `restore.sh` · `test_restore.sh` |
| CI | GitHub Actions (ruff + pytest + docker build), 30/30 test |

---

## Tổng kết phạm vi
- **~31 router · ~180 endpoint · ~40 bảng dữ liệu · 23 service nghiệp vụ · 28 tab UI.**
- **13/13 phân hệ "MES hardcore"** hoàn thành (xem README mục lộ trình); riêng tích hợp thiết bị OT ở dạng mô phỏng edge + client OPC UA thật demo, với ranh giới cắm PLC/SCADA thật rõ ràng.
