# Tài liệu Kiến trúc Chuẩn — MES Bia Hạ Long (Nhà Máy Đông Mai)

> Phần mềm điều hành sản xuất (Manufacturing Execution System) cho nhà máy bia.
> Tài liệu này mô tả kiến trúc *thực tế đã hiện thực* trong mã nguồn, không phải bản đề xuất.
> Tham chiếu blueprint nội bộ `MES-ARCH-002` (*MES-Nha-may-Bia-Kien-truc-Chuan-V2.0*).

**Phiên bản phần mềm:** `0.1.0-mvp` · **Tên ứng dụng:** `MES Bia Hạ Long - Nhà Máy Đông Mai`
**Ngày phát hành:** 23/06/2026 · **Ngày cập nhật:** 31/07/2026

---

## 1. Tổng quan & nguyên tắc kiến trúc

MES này điều phối toàn bộ vòng đời sản xuất bia: **Lệnh sản xuất → Điều độ (Work Order) → Lệnh nấu/Lệnh lọc → Mẻ (Batch) → Công thức/Phiên bản → Kiểm soát chất lượng (hold/release) → Phả hệ (Genealogy) → Kiểm toán (Audit)**, đồng thời bao trùm các phân hệ chiều sâu: ISA-88, LIMS/QC nâng cao theo công đoạn (stage QC), OEE/downtime, kho NVL 2 địa điểm (Kho công ty ↔ Kho phân xưởng) & kho thành phẩm theo đơn vị (WMS unit-based), năng lượng, bảo trì/kiểm định, historian thời gian thực, tích hợp CSDL SCADA ngoài + panel Realtime thật, import dữ liệu ngoài (Excel/CSV + custom field động), lập lịch tối ưu, và lớp AI tư vấn.

### Nguyên tắc nền tảng

| Nguyên tắc | Hiện thực |
|---|---|
| **Modular monolith** | Một tiến trình FastAPI, chia theo *bounded context* (mỗi phân hệ có model → service → router riêng). Dễ tách microservice sau này. |
| **Bounded context** | Mỗi module sở hữu dữ liệu của mình; truy cập chéo đi qua **service layer**, không truy vấn trực tiếp bảng của module khác. |
| **REST/JSON, OpenAPI tự sinh** | Toàn bộ API theo REST; tài liệu Swagger tại `/docs`. |
| **RDBMS chuẩn** | SQLAlchemy 2.0 ORM; **SQLite** để chạy ngay (dev), **PostgreSQL 16** cho production (đổi qua biến môi trường). |
| **Source of Record bất biến** | Mẻ chụp snapshot công thức bất biến; audit append-only có hash-chain; EBR khóa được; lô có thể **khóa (lock)** thủ công để chặn sửa/xóa/tiêu thụ. |
| **Human-in-the-loop** | AI **chỉ tư vấn**, mọi hành động sản xuất cần con người + đúng quyền. |
| **Zero-build frontend** | UI web bằng vanilla JS + SVG, không framework, không bước build — chạy offline. |
| **Chỉ đọc với hệ thống ngoài** | Kết nối CSDL SCADA thật (WinCC/khác) chỉ dùng `SELECT` — không ghi/điều khiển thiết bị; panel Realtime hiển thị đúng nguyên giá trị cột nguồn, không tự suy diễn/tính toán thêm. |

---

## 2. Sơ đồ tầng (layered architecture)

```
┌─────────────────────────────────────────────────────────────────────┐
│  CLIENT                                                               │
│  • Web UI đầy đủ (/)            • Kiosk cảm ứng (/kiosk.html)          │
│  • Swagger /docs                • Phần mềm ngoài (ERP/WMS/BI) qua API  │
│  • Edge connector (OPC UA/MQTT) • AI agent / MCP (manifest tool)      │
│  • CSDL SCADA ngoài (WinCC…)    • File Excel/CSV import ngoài          │
└───────────────┬───────────────────────────────────────┬─────────────┘
                │ Authorization: Bearer <token>          │ X-API-Key (scope)
┌───────────────▼───────────────────────────────────────▼─────────────┐
│  MIDDLEWARE (main.py)                                                 │
│  request-id · rate-limit · đo độ trễ · log JSON · /metrics            │
│  ánh xạ lỗi nghiệp vụ → HTTP (404 / 409 / 403)                        │
└───────────────┬──────────────────────────────────────────────────────┘
┌───────────────▼──────────────────────────────────────────────────────┐
│  ROUTERS (REST endpoints) — 33 router, ~397 endpoint                  │
│  auth · orders · workorders · recipes · batches · dispense · quality  │
│  quality_adv · traceability · performance · downtime · warehouse      │
│  energy · maintenance · process · brewing · reports · historian       │
│  scan · schedule · ai · jobs · isa88 · wms · label · lines            │
│  packaging · gateway · audit · master · materials · import_explorer   │
│  cip                                                                  │
└───────────────┬──────────────────────────────────────────────────────┘
┌───────────────▼──────────────────────────────────────────────────────┐
│  SERVICES (quy tắc nghiệp vụ) — 48 module                              │
│  batches · recipes · workorders · isa88 · genealogy · bom · dispense  │
│  warehouse · quality · quality_adv · qc_catalog · ebr · yield_calc    │
│  downtime · performance · scheduler · historian · wms · packaging     │
│  brew_order · filter_order · lot_lock · lot_record · load_slip        │
│  ferment_log · braumat_import · dashboard · lo_status · ops_setting   │
│  master_data · integration_connection · energy_external · filling_… │
│  keg_external · wastewater_external · import_mapping/parser/runner/… │
│  custom_fields · ai · ai_tools · conversations · jobs · derived · cip │
└───────────────┬──────────────────────────────────────────────────────┘
┌───────────────▼──────────────────────────────────────────────────────┐
│  MODELS (SQLAlchemy ORM) — ~104 lớp / 32 file theo bounded context     │
└───────────────┬──────────────────────────────────────────────────────┘
┌───────────────▼──────────────────────────────────────────────────────┐
│  DATABASE   SQLite (dev)  │  PostgreSQL 16 (prod) — Alembic migration  │
└───────────────────────────────────────────────────────────────────────┘
   ┌─────────────────────────────────────────────────────────────────┐
   │  CSDL SCADA NGOÀI (WAN, chỉ đọc) — qua SqlConnection cấu hình    │
   │  purpose: energy_* · filling · filling_keg · wastewater · …      │
   └─────────────────────────────────────────────────────────────────┘

   Cross-cutting (xuyên suốt mọi tầng):
   security.py (RBAC/SoD/scope) · audit.py (hash-chain) · config.py (Settings)
   logging_config.py (request-id, log chi phí AI) · ratelimit.py · metrics_prom.py
```

**Quy tắc phụ thuộc:** Router → Service → Model. Service **không** phụ thuộc ngược Router (truy vấn dẫn xuất được gom vào `services/derived.py` để cắt vòng phụ thuộc).

---

## 3. Ngăn xếp công nghệ (tech stack)

| Lớp | Công nghệ | Ghi chú |
|---|---|---|
| Web framework | **FastAPI** | OpenAPI tự sinh, `lifespan`, middleware |
| ASGI server | **Uvicorn** | `[standard]` |
| ORM | **SQLAlchemy 2.0** | `DeclarativeBase`, session-per-request |
| Validation/cấu hình | **Pydantic 2 + pydantic-settings** | `config.Settings` gom mọi biến `MES_*` |
| Migration | **Alembic** | ~90 file migration (đợt tính năng gần nhất mỗi tính năng 1 migration) |
| CSDL nội bộ | **SQLite** (dev) / **PostgreSQL 16** (prod) | Đổi qua `MES_DATABASE_URL` |
| CSDL ngoài (tích hợp) | **SQL Server (pyodbc/pymssql qua SQLAlchemy)** | Kết nối cấu hình tại Tích hợp › Kết nối CSDL, chỉ `SELECT` |
| Xử lý file import | **openpyxl / pandas-lite thuần Python** | Đọc Excel/CSV (đề nghị đóng hàng, Braumat PDF nấu) |
| Sinh tài liệu Word/PowerPoint | **python-docx / python-pptx** | `docs/build/md2docx.py`, `docs/build/build_decks.py` |
| Edge OT | **asyncua** (OPC UA) | Tiến trình `app.opcua_edge`; core app không import |
| Mã vạch / QR | **segno** (QR) + Code39 thuần JS | Tem lô/pallet/unit thành phẩm |
| AI (tùy chọn) | **anthropic** SDK (Claude) | Không có key → engine luật offline |
| Frontend | **Vanilla JS + SVG** | Không framework, không build; `app.js` + `views_ext.js` + `import_explorer.js` + `charts.js` + `barcode.js` |
| Cache/rate-limit (tùy chọn) | **Redis** | `MES_REDIS_URL`; tự fallback in-process |
| Observability | **Prometheus** text exposition | `/metrics` không thêm dependency |
| Đóng gói | **Docker** + docker-compose | app FastAPI + PostgreSQL 16 |
| CI | **GitHub Actions** | ruff lint + pytest (57 file test) + docker build |

---

## 4. Cấu trúc thư mục

```
MES/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app: mount 33 router + UI, middleware, ánh xạ lỗi→HTTP
│   │   ├── config.py / database.py / common.py / security.py / audit.py
│   │   ├── errors.py / logging_config.py / ratelimit.py / metrics_prom.py
│   │   ├── seed.py            # dữ liệu mẫu + 10 tài khoản demo theo chức danh
│   │   ├── edge_sim.py / opcua_edge.py
│   │   ├── models/            # ORM theo bounded context (~104 lớp / 32 file)
│   │   ├── services/          # quy tắc nghiệp vụ (48 module)
│   │   └── routers/           # REST endpoints (33 router, ~397 endpoint)
│   ├── alembic/versions/       # ~90 migration
│   ├── tests/                  # pytest: 55 file
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                   # UI vanilla JS (zero-build)
│   ├── index.html  app.js  views_ext.js  import_explorer.js  charts.js  barcode.js  styles.css
│   └── kiosk.html  kiosk.js   # giao diện cảm ứng cho xưởng
├── docs/                        # tài liệu + script build docx/pptx (docs/build/)
├── scripts/                     # backup.sh · restore.sh · test_restore.sh
├── .github/workflows/ci.yml
├── docker-compose.yml
└── .env.example
```

---

## 5. Mô hình dữ liệu (bounded context → bảng)

~104 lớp ORM, nhóm theo bounded context. Mỗi bảng dưới đây thuộc một file trong `app/models/`.

### 5.1 Xác thực & phân quyền (`auth.py`)
| Bảng | Mục đích |
|---|---|
| `app_user` (**User**) | Tài khoản: username, mật khẩu băm PBKDF2, `role` (1 trong 5 vai trò enforcement), `job_title` (chức danh hiển thị), `allowed_views`, `permissions` (CSV), `scope_lines/areas/qc`, `must_change_password`, `active` |
| `user_session` (**UserSession**) | Phiên đăng nhập: token, user_id, role, created_at, expires_at (mặc định 12h) |

### 5.2 Master data (`master.py`, `lines.py`, `materials_ext.py`)
| Bảng | Mục đích |
|---|---|
| `product` (**Product**) | Dịch bia (chưa đóng gói): mã, tên, `ferment_days_std`, `spec_json` (thông số Braumat) |
| `beer_type` (**BeerType**) | Loại bia — khoá scoping cho Lọc/Chiết khi chưa gắn `finished_product_id` cụ thể |
| `finished_product` (**FinishedProduct**) | SKU thành phẩm: mã, tên, `unit_type`/`pack_size`/`units_per_case`, `category`, gắn `product_id`/`beer_type_id` |
| `material` (**Material**) | NVL: mã, tên, nhóm, `stock_min` (ngưỡng cảnh báo tồn tối thiểu) |
| `material_group` (**MaterialGroup**) | Nhóm vật tư, cờ `is_packaging` |
| `supplier` (**Supplier**) | Nhà cung cấp: mã, tên, liên hệ |
| `production_line` (**ProductionLine**) | Dây chuyền/tank/nhà nấu: mã, kind, area, `capacity_uom/volume/volume_uom`, active |
| `ops_setting` (**OpsSetting**) | Cấu hình vận hành toàn cục: ngưỡng cảnh báo tuổi lô (caution/warning/critical) |

### 5.3 Lệnh & điều độ (`orders.py`, `workorder.py`, `scheduling.py`, `brewing.py`)
| Bảng | Mục đích |
|---|---|
| `production_order` (**ProductionOrder**) | Lệnh gốc từ ERP: SL, deadline, ưu tiên, trạng thái |
| `work_order` (**WorkOrder**) | Phân rã PO → kế hoạch ngày/ca/line; planned vs actual; trạng thái |
| `schedule_slot` (**ScheduleSlot**) | Khối thời gian chiếm tài nguyên (tank/line): production/cip/maintenance, start/end |
| `brew_master_order` / `brew_order` (**BrewMasterOrder/BrewOrder**) | **Lệnh nấu** phân cấp: 1 lệnh cha (SP, tổng SL kế hoạch) → nhiều lệnh con (mã nấu riêng); hoàn thành theo `planned_volume_hl ± tolerance` |
| `brew_order_material_line` | Dòng NVL kế hoạch của lệnh nấu (preview/sửa số lượng trước khi nấu) |
| `filter_master_order` / `filter_order` / `filter_order_tank` (**FilterMasterOrder/FilterOrder/FilterOrderTank**) | **Lệnh lọc** phân cấp tương tự Lệnh nấu; mỗi lệnh con gồm N tank nguồn (CCT hoặc BBT tái lọc) với thể tích kế hoạch riêng từng tank. `batch_number`/`order_number` **được phép trùng** giữa các lệnh lọc khác nhau (trước bị chặn unique) — mỗi dòng "mẻ lọc số" nhận diện qua bộ 3 `(batch_number, order_number, batch_seq_no)`; cờ `is_final_batch` đánh dấu đợt rút CUỐI để loại khỏi phân loại Thấp/Cao sản lượng (`services/filter_yield_report.py`) |
| `filter_order_material_line` | Dòng NVL kế hoạch của lệnh lọc (hoá chất lọc…) |

### 5.4 Công thức (`recipes.py`, `recipe_ext.py`)
| Bảng | Mục đích |
|---|---|
| `recipe` / `recipe_version` (**Recipe/RecipeVersion**) | Định danh + phiên bản công thức: tham số, BOM (JSON), QC, `yield_steps`, thủ tục ISA-88. Chỉ `effective` mới chạy mẻ được |
| `recipe_change` (**RecipeChange**) | Phiếu kiểm soát thay đổi: lý do (bắt buộc), diff JSON, state |
| `batch_yield_actual` (**BatchYieldActual**) | Hiệu suất thực tế theo công đoạn |

### 5.5 Thực thi mẻ (`batches.py`, `isa88.py`, `metrics.py`)
| Bảng | Mục đích |
|---|---|
| `batch_execution` (**BatchExecution**) | SoR thực thi mẻ: trạng thái, snapshot recipe bất biến, actuals, `quality_status`, `ebr_locked` |
| `batch_phase_run` (**BatchPhaseRun**) | Log chạy phase ISA-88 |
| `process_reading` (**ProcessReading**) | Telemetry curated gắn mẻ |
| `oee_record` (**OEERecord**) | Dữ liệu ca đóng gói |

### 5.6 Công đoạn nấu bia chi tiết (`brewing.py` — 23 lớp)
| Bảng | Mục đích |
|---|---|
| `material_receipt` (**MaterialReceipt**) | Nhập nguyên liệu công đoạn: MSKT, lô PM/KCS, NCC |
| `brew_record` / `brew_batch` (**BrewRecord/BrewBatch**) | Nấu theo mã nấu (BrewRecord) → nhiều mẻ (BrewBatch); `locked/locked_by/locked_at` |
| `brew_material_usage` (**BrewMaterialUsage**) | NVL tiêu thụ theo mẻ nấu — trừ tồn thật qua `warehouse.issue()`, có `lot_id`/`movement_id` để hoàn tác |
| `brew_process_step` / `brew_process_log` (**BrewProcessStep/BrewProcessLog**) | Ghi chép quy trình nấu import từ PDF Braumat + `manual_json` (biểu mẫu QT-KCS-QT-BM-05) |
| `ferment_record` (**FermentRecord**) | Lên men: lm_code, tank, đời men, tồn CCT, `qc_approved*`, trạng thái |
| `ferment_process_log` / `ferment_daily_reading` (**FermentProcessLog/FermentDailyReading**) | Nhật ký lên men hàng ngày có audit "stamp-on-value" (ghi đè có vết) |
| `filter_record` (**FilterRecord**) | Lọc CCT/BBT→BBT: v_dich, v_beer, nguồn tank (`tank_type` cct/bbt tái lọc), `qc_approved*` |
| `filter_material_usage` (**FilterMaterialUsage**) | NVL/hoá chất tiêu thụ theo mẻ lọc |
| `bottle_record` (**BottleRecord**) | Chiết: theo ca 1/2/3, dây chuyền (multi-select), `finished_product_id`, đã duyệt/khóa |
| `stage_indicator` (**StageIndicator**) | Chỉ tiêu phân tích gắn công đoạn |
| `chemical_usage`, `yeast_lot`/`yeast_issue` | Hóa chất theo công đoạn; thu hồi & cấy men |

### 5.7 Chất lượng (`quality.py`, `quality_ext.py` — 6 lớp)
| Bảng | Mục đích |
|---|---|
| `quality_result` (**QualityResult**) | Kết quả QC: PASS/FAIL số học; FAIL → ON_HOLD tự động |
| `deviation` (**Deviation**) | Lệch chuẩn: severity, workflow open→…→closed |
| `qc_parameter` (**QCParameter**) | Chỉ tiêu SPC: target, USL/LSL, stage, `value_type` |
| `qc_group` / `qc_group_item` (**QcGroup/QcGroupItem**) | **Nhóm chỉ tiêu chất lượng** tái sử dụng — gắn vào NVL hoặc vào công đoạn (`stage_qc_group`, scoping theo `product_id`/`beer_type_id`/`finished_product_id`) |
| `capa` (**CAPA**) | Hành động khắc phục/phòng ngừa |
| `lims_sample` (**Sample**) | Phiếu mẫu LIMS-lite |

### 5.8 Vật tư, lô, phả hệ & kho NVL (`materials.py`, `materials_ext.py`, `warehouse.py`)
| Bảng | Mục đích |
|---|---|
| `material_lot` (**MaterialLot**) | Lô NVL: tồn, hạn dùng, `location` (chuỗi tự do — `"Kho công ty"`/`"Kho phân xưởng"`), `lot_year`/`kcs_lot_no`/`unit_price`/`supplier_id`, `locked` |
| `genealogy_edge` (**GenealogyEdge**) | Cạnh phả hệ có hướng (consume/produce/split/merge/transfer) |
| `dispense`/`dispense_line` | Phiếu cấp liệu cho mẻ |
| `stock_movement` (**StockMovement**) | Sổ cái kho bất biến: `location_from`/`location_to` (chuỗi tự do), `reversed`/`reversal_of` để hỗ trợ hoàn tác |
| `material_request` / `material_request_line` (**MaterialRequest/…Line**) | Phiếu đề nghị nhận NVL (Kho phân xưởng đề nghị ← Kho công ty duyệt/fulfill từng dòng, FIFO) |
| `stock_count` / `stock_count_line` (**StockCount/…Line**) | Kiểm kê định kỳ: nhập số đếm → post chênh lệch → `approved_by/approved_at`, có Hoàn tác |

### 5.9 Bảo trì, kiểm định, năng lượng, downtime
| Bảng (file) | Mục đích |
|---|---|
| `equipment`, `spare_part`, `incident`, `maintenance_plan`, `calibration` (`maintenance.py`) | CMMS |
| `downtime_event` (`oee_ext.py`) | Sự kiện dừng máy |
| `energy_group`, `energy_area`, `energy_reading` (`energy.py`) | Năng lượng nội bộ (nhập tay theo ngày) |

### 5.10 Kho thành phẩm (WMS — 9 lớp) & bao bì tuần hoàn (`wms.py`, `packaging.py`, `master.py`)
| Bảng | Mục đích |
|---|---|
| `unit_type_catalog` (**UnitTypeCatalog**, `master.py`) | **Danh mục Loại đơn vị tồn kho** — thay hardcode chuỗi "vi"/"keg"/"lon" trước đây: `code` (khoá tra cứu logic, PHẢI chữ thường không dấu — regex `^[a-z0-9_-]+$`, tự hạ chữ thường khi gõ hoa), `name` (nhãn hiển thị có dấu), `divide_by_pack_size` (bool — loại này có chia `quantity` theo `pack_size` khi quy đổi ra số đơn vị đóng gói hay không, giống "vi"), `selectable` (ẩn khỏi lựa chọn khi khai báo SKU mới — vd "lon" do hệ thống tự sinh khi phân rã, không cho chọn tay), `active`. `services/wms.py` (`_pack_divisor`/`_pack_divisor_expr`), `services/genealogy.py`, `routers/wms.py` đọc theo danh mục này; CRUD tại `/api/unit-types` (`master.py`). **Fix lỗi gốc**: trước đây ô "Mã" khi tạo danh mục là input tự do không validate — gõ nhầm tên có dấu ("Vỉ") vào ô Mã (đáng lẽ gõ ở ô Tên) tạo ra `code` lạ khác "vi", khiến SKU gán loại đó không được `_pack_divisor` chia theo `pack_size` → đếm sai tồn (vd lô 100.000 vỉ bị đếm nguyên thay vì chia 24). Nay `UnitTypeCatalogIn.code` validate + tự hạ chữ thường ở tầng schema, đồng thời `FinishedProduct.unit_type` khi tạo/sửa SKU và `_create_units` (build_units + import tồn đầu Excel) đều đối chiếu lại danh mục trước khi ghi. |
| `wms_location` (**WmsLocation**) | Vị trí kho thành phẩm |
| `finished_goods_unit` (**FinishedGoodsUnit**) | **Đơn vị LÔ thành phẩm** (thay thế hoàn toàn Pallet/Case/ShipmentLine cũ) — thiết kế lại theo LÔ (2026-07): mỗi dòng đại diện **1 lô** (không còn 1 dòng/vỉ), `quantity` = tổng SL nhỏ (lon/keg) của cả lô, nên duyệt chiết luôn ra ĐÚNG 1 dòng bất kể quy mô (fix scale-bomb: lô 190.000 vỉ trước đây tạo ~190.000 dòng, treo nút Duyệt trên SQL Server). Xuất/phân rã (decompose)/điều chuyển (relocate)/xuất tự do MỘT PHẦN sẽ **tách dòng** theo FIFO (`_consume_lot_rows`) — dòng mới mang đúng phần đã xử lý, dòng gốc giữ phần dư — thay vì chọn/xóa từng vỉ; `pack_size` (khai báo ở Danh mục Sản phẩm) chỉ dùng ở tầng đọc để quy đổi `quantity` ra số vỉ/keg hiển thị. Còn `is_near_expiry` cho bia cận date. Xem `docs/WMS-LOT-LEVEL-REDESIGN.md`. |
| `near_expiry_entry` (**NearExpiryEntry**) | Bia cận date nhập thủ công (không qua Chiết bình thường) |
| `ship_to_location` (**ShipToLocation**) | Danh mục nơi xuất đến |
| `vehicle` (**Vehicle**) | Danh mục phương tiện vận chuyển |
| `shipment` (**Shipment**) | Phiếu xuất kho: header (người nhận/lái xe/xe/nơi đến), `shipment_type`, `fifo_ok` |
| `load_slip` / `load_slip_line` (**LoadSlip/…Line**) | Lệnh đóng hàng import từ Excel — danh mục 15 dòng cố định khớp mẫu giấy |
| `packaging_type` / `packaging_move` | Bao bì tuần hoàn (vỏ chai/két-gông/keg) |

### 5.11 Tích hợp CSDL ngoài & Import dữ liệu (`integration.py`, `integration_import.py`)
| Bảng | Mục đích |
|---|---|
| `sql_connection` (**SqlConnection**) | Kết nối SQL Server ngoài (WinCC/SCADA…): host/port/db/user/password (server-side only), `purpose` (CSV token, VD `filling,energy_dm`) để module MES tự tìm đúng kết nối |
| `api_key`, `webhook` | API key (scope read/write) + webhook (event_types, HMAC secret) |
| `import_profile`, custom-field/import-run models (**5 lớp**, `integration_import.py`) | Cấu hình ánh xạ cột Excel/CSV → bảng đích + **trường tùy biến (custom field)** động thêm vào NVL/lô mà không cần đổi schema cứng |

### 5.12 Lịch sử thời gian thực (`historian.py`)
| Bảng | Mục đích |
|---|---|
| `historian_point` (**HistorianPoint**) | Telemetry theo tag UNS (mô phỏng edge OT nội bộ — khác với panel Realtime SCADA thật đọc trực tiếp CSDL ngoài ở §9.2) |

### 5.13 Kiểm toán, chữ ký, AI, job
| Bảng (file) | Mục đích |
|---|---|
| `audit_log` (`audit.py`) | Append-only, hash-chain, `seq` UNIQUE |
| `esignature`, `ebr_snapshot` (`signature.py`) | Chữ ký điện tử (21 CFR Part 11) + snapshot EBR |
| `ai_conversation`, `ai_message` (`ai_memory.py`) | Bộ nhớ hội thoại AI theo user |
| `job` (`jobs.py`) | Tác vụ nền |

### 5.14 Vệ sinh thiết bị — CIP (`cip.py`, `services/cip.py`)
Theo dõi vệ sinh CIP (Cleaning-In-Place) — nguồn gốc **21 loại biểu mẫu giấy thật** của nhà máy (mã `QT-KCS-QT-BM-xx`), seed sẵn trong `seed.py`. Thiết kế linh hoạt vì các mẫu giấy có số cột/loại thông số khác nhau — không hard-code theo từng loại biểu mẫu.

| Bảng | Mục đích |
|---|---|
| `cip_form_type` (**CipFormType**) | Danh mục LOẠI biểu mẫu: `code` (unique, vd `"2.1.2/2025/QT-KCS-QT-BM-01"`), `name`, `area` (nau\|len_men\|loc\|chiet\|kho_tp), `kind` (full\|light — vd tank thành phẩm xen kẽ CIP đầy đủ và tráng nước nhẹ), `time_unit`/`temp_unit`/`conc_unit` (khai báo đơn vị 1 lần/biểu mẫu vì khác nhau giữa các mẫu giấy gốc — vd "giây" ở tank lên men, "phút" ở hầu hết mẫu khác), `default_steps` (JSON — bảng bước MẪU khoá "Tiêu chuẩn/Quy định", sao chép sang mỗi `CipRecord` mới), `active` |
| `cip_equipment` (**CipEquipment**) | Danh mục thiết bị vệ sinh: `code`/`name`/`area`, `production_line_id` FK optional tới `production_line` (gắn đúng 1 tank/dây chuyền nếu có, để lọc gợi ý theo mã thiết bị thực tế; để trống với thiết bị dùng chung như đường ống/máy nghiền) |
| `cip_record` (**CipRecord**) | 1 lần vệ sinh: `cip_code` (auto `"CIP-2026-00001"`), `form_type_id`/`equipment_id` FK, `batch_number`/`order_number` bắt buộc (đối chiếu ngược Batch/Order Number Braumat — cùng khái niệm dùng ở Ghi chép nấu/Lên men), `shift`, `started_at`/`ended_at`, `performed_by`, `duty_officer`, `steps` (JSON linh hoạt — mỗi dòng có 4 trường TIÊU CHUẨN khoá copy từ `default_steps` + 4 trường `*_actual` THỰC TẾ người vận hành tự nhập), `result` (dat\|khong_dat), `note`, `checked_by` (KCS nghiệm thu), `approved_at` |
| `cip_link` (**CipLink**, unique trên `cip_id+scope_type+scope_id`) | Gắn TAY (không tự suy đoán) 1 `CipRecord` với mẻ/lô — cùng vocabulary `scope_type` đã dùng ở Hold/Deviation trong `services/quality.py` (brew_batch\|ferment\|filter\|bottle), cộng thêm `bbt_tank` (không có ở Hold/Deviation — vì CIP tank thành phẩm thuộc về cả TANK vật lý, không phải 1 `FilterRecord` cụ thể, do nhiều mẻ lọc dùng chung tank) |

**Quyền:** `cip.manage` (permission mới trong `PERMISSION_CATALOG` — xem §8.3, tổng permission catalog hiện có **23 mục**).

**Endpoints chính** (`routers/cip.py`, prefix `/api/cip`): `GET/POST /form-types`, `PUT/DELETE /form-types/{id}`, `POST /form-types/{id}/copy-steps` (copy bảng bước mẫu từ 1 form-type sang form-type khác, **chỉ khi đích đang có bảng bước rỗng** — tránh ghi đè nhầm, chặn 409 nếu đích không trống hoặc trùng nguồn), `GET/POST /equipment`, `PUT/DELETE /equipment/{id}`, `GET/POST /records`, `GET/PUT /records/{cip_id}`, `POST /records/{cip_id}/approve`, `GET /suggest` (gợi ý form-type/equipment theo scope), `GET/POST/DELETE /links`.

**Frontend** (`views_ext.js`): module CIP có 3 tab — "Danh mục" (form-types + equipment), "Khai báo biểu mẫu" (soạn bảng bước mẫu Tiêu chuẩn cho từng loại biểu mẫu, có ô N/A cho time/temp/conc khi bước đó không cần ghi; nút "Copy sang biểu mẫu khác"), "Khai báo CIP" (tạo 1 lần vệ sinh mới — chọn form-type tự điền bảng Tiêu chuẩn khoá, nhập cột Thực tế bên cạnh; trường "TH:Kết quả" là dropdown Đạt/Không đạt). Nút "Gắn CIP liên quan" (`app.js`) gắn vào 4 loại thực thể: mẻ nấu, mẻ lên men, mẻ lọc, mẻ chiết. Có báo cáo/in xem Tiêu chuẩn vs Thực tế. CIP link cũng được đưa vào Hồ sơ điện tử (`services/lot_record.py` aggregator) và vào Audit trail.

---

## 6. State machine (máy trạng thái) cốt lõi

Mọi chuyển trạng thái phải hợp lệ; sai → **HTTP 409**. Định nghĩa tại `common.py`.

**Mẻ (BatchState):** `planned → ready → running → held → completed → closed` (+ cancelled)

**Công thức (RecipeState):** `draft → review → approved → effective → suspended → (effective lại)`; `effective/suspended → obsolete`
> **Chỉ phiên bản `effective` mới được dùng để chạy mẻ.**

**Lệnh SX (WorkOrderState):** `planned → released → in_progress → completed → closed` (+ cancelled)

**Deviation:** `open → triage → investigation → disposition → approval → closed`

**Chất lượng (QualityStatus):** `pending → on_hold ⇄ released → rejected` (FAIL tự đưa về `on_hold`)

**Lô (LotStatus):** `available → consumed`; nhánh `on_hold / released / scrapped`; cờ **`locked`** độc lập (chặn sửa/xóa/tiêu thụ bất kể status) trên Lên men/Lọc/Chiết/Lô NVL

**Phase ISA-88 (PhaseState):** `idle → running → held → complete` (+ aborted)

**Lệnh nấu/Lệnh lọc:** hoàn thành theo **thể tích cộng dồn** (`Σ mẻ ≥ planned_volume_hl − tolerance`), không theo số lần chạy cố định

**Phiếu đề nghị nhận kho:** mỗi dòng NVL độc lập `pending → fulfilled/rejected` (+ Hoàn tác); phiếu cha huỷ được khi chưa có dòng nào fulfilled

**Kiểm kê định kỳ (StockCount):** `draft (nhập số đếm) → posted (đã ghi chênh lệch) → approved`; `undo` chỉ khi chưa approved

**Quan hệ phả hệ (GenealogyRelation):** `consume` (lô→mẻ), `produce` (mẻ→lô), `split`, `merge`, `transfer`

---

## 7. Luồng nghiệp vụ cốt lõi

### 7.1 Vòng đời sản xuất một mẻ (đường MES-hardcore, tổng quát)
```
ERP/người dùng tạo Production Order
   → Điều độ tạo Work Order (line/ca/ngày)
      → Dispatch sinh Batch từ recipe EFFECTIVE (snapshot bất biến BOM/param/QC)
         → [Kiểm tra tồn BOM ↔ tồn khả dụng; thiếu → chặn 409 trừ khi allow_shortage]
         → ready → running
         → Consume lô NVL (FEFO; chặn vượt định mức trừ khi allow_over) → genealogy edge
         → Ghi actual tham số quy trình
         → Ghi kết quả QC (PASS/FAIL số học; FAIL → on_hold)
         → Produce lô bán thành phẩm/thành phẩm → genealogy edge
         → QA release (chặn nếu còn FAIL chưa đóng deviation)
         → completed → closed
      → EBR: lắp dossier → ký điện tử (re-auth) → khóa (snapshot content_hash)
```

### 7.2 Luồng thực tế PX Đông Mai (Lệnh nấu → Lệnh lọc → Chiết → WMS)
```
Lệnh nấu (cha, SP + SL kế hoạch hl) → N lệnh nấu con (mã nấu riêng)
   → mỗi lệnh con chạy N mẻ nấu (BrewBatch) đến khi đủ thể tích kế hoạch ±dung sai
      → NVL từng mẻ trừ tồn thật (Kho phân xưởng, FIFO theo lô)
      → Kết thúc mẻ → Lên men (lô LM, tank CCT) → Duyệt LM (KCS, theo số ngày lên men chuẩn)
Lệnh lọc (cha) → N lệnh lọc con → mỗi lệnh con N tank nguồn (CCT hoặc BBT tái lọc)
   → Lọc vào BBT theo thể tích kế hoạch từng tank → mẻ lọc kết thúc chuyển trạng thái
     **"Chờ duyệt"** (trước gọi "Chờ chiết") → Duyệt Lọc (KCS)
Chiết (theo ca 1/2/3, nhiều dây chuyền, gắn SKU thành phẩm) → Kết thúc mẻ (nhập ca1/2/3 thật)
   → Duyệt Chiết (quality.release) → tự sinh N FinishedGoodsUnit vào WMS
WMS: Cất vào vị trí / Điều chuyển / Phân rã theo lô / Xuất kho (cart FIFO, theo Lệnh đóng hàng
   hoặc thủ công) / Xuất tự do (admin) → Shipment (có loại xuất, kiểm tra FIFO)
```
> **Lọc — mẻ lọc nhỏ độc lập**: cho phép trùng `batch_number`/`order_number` giữa các lệnh lọc khác nhau; báo cáo sản lượng gộp theo `(batch_number, order_number, batch_seq_no)`; `is_final_batch` loại "mẻ cuối" khỏi phân loại Thấp/Cao sản lượng. **Hồ sơ điện tử** (`services/lot_record.py`) liệt kê đầy đủ từng "mẻ lọc số" (tank nguồn, thể tích, thời điểm kết thúc) dưới mỗi mẻ lọc, không chỉ tổng hợp cấp bản ghi.

### 7.3 Luồng Kho NVL 2 địa điểm
```
Nhập kho (NCC → Kho công ty, mặc định) → thủ kho quản lý tồn tại Kho công ty
Kho phân xưởng đề nghị nhận NVL (Đề nghị nhận kho, theo Lệnh nấu/Lệnh lọc chưa hoàn thành)
   → Kho công ty duyệt/fulfill từng dòng (FIFO) → chuyển vật lý sang Kho phân xưởng
Kho phân xưởng tiêu thụ NVL trực tiếp cho mẻ nấu/lọc (trừ tồn ngay tại Kho phân xưởng)
Kiểm kê định kỳ độc lập ở mỗi địa điểm (location filter riêng)
```
> Xem **§8.7** — địa điểm là dữ liệu (chuỗi `location`), **không phải** một chiều phân quyền riêng.

### 7.4 Quy tắc bất biến đã thực thi
- **Recipe/BOM snapshot bất biến** khi tạo mẻ.
- **State machine** kiểm soát mọi chuyển trạng thái.
- **Genealogy**: mọi consume/produce tạo cạnh có hướng → truy xuất đồ thị xuôi/ngược + recall.
- **QC tự động**: PASS/FAIL theo giới hạn số học; FAIL tự đưa scope về ON HOLD.
- **Audit append-only + hash-chain**: `entry_hash = sha256(prev_hash + nội dung)`.
- **EBR khóa → mẻ bất biến**; **`locked` thủ công** chặn thao tác bất kể trạng thái nghiệp vụ.
- **Panel Realtime SCADA**: chỉ đọc cột nguồn nguyên trạng (không tính tốc độ/suy diễn từ 2 lần đọc).

---

## 8. Bảo mật & phân quyền

### 8.1 Xác thực
- **Đăng nhập thật**: mật khẩu băm **PBKDF2-HMAC-SHA256, 100.000 vòng**, salt ngẫu nhiên; so sánh chống timing.
- **Token phiên** (urlsafe, 32 byte) lưu DB + `localStorage`, gửi qua header `Authorization: Bearer …`; phiên **12 giờ**.
- `get_current_user` **yêu cầu token**; không có → 403. Fallback dev header **mặc định TẮT**.
- **`must_change_password`**: admin tạo bằng mật khẩu mặc định → buộc đổi lần đầu.

### 8.2 RBAC — 5 vai trò *thực thi* (enforcement) + chức danh hiển thị
Tầng kiểm tra quyền (`require_role`, `common.py:180`) chỉ biết **đúng 5 giá trị**: `operator` · `supervisor` · `qa` · `engineer` · `admin`. Admin bỏ qua mọi `require_perm`/`require_role`/`require_scope` (vẫn bị ràng buộc SoD).

Các "chức danh" tài khoản demo (Quản đốc, Phó Quản đốc, Vận hành, KCS, Kỹ sư, Thủ kho, Trưởng phòng KCS, Giám đốc SX-KT, Thủ kho TP…) **không phải vai trò thứ 6+** — mỗi tài khoản chỉ ánh xạ vào 1 trong 5 vai trò trên, rồi được cấp **`permissions` (CSV quyền cụ thể)** + **`allowed_views` (CSV menu)** + **scope** riêng theo từng người (xem `seed.py::_seed_users`).

**Roster hiện tại căn cứ đúng sơ đồ tổ chức thật 01/2026/SĐTC-BHL** (thay cho bảng đề xuất cũ) — đã bỏ các chức danh không có riêng trong sơ đồ hoặc trùng vai trò với tài khoản khác: `giamdoc` (chỉ xem chung), `truongca`, `thukho_px`, `baotri`, `nangluong`:

| Tài khoản (chức danh) | `role` enforcement | Quyền chính (`permissions`) | `scope_warehouse` |
|---|---|---|---|
| `admin` | admin | * (toàn quyền, tạo riêng bởi `ensure_admin`, không trong bảng accounts) | * |
| `quandoc` (Quản đốc phân xưởng) | supervisor | master.manage, order.create, wo.manage, wo.dispatch, batch.create, batch.execute, quality.deviation, ebr.sign, ebr.approve, cip.manage | * |
| `phoquandoc` (Phó Quản đốc phân xưởng — trực ca) | supervisor | batch.execute, ebr.sign, ebr.approve, quality.deviation, cip.manage. Tài khoản MỚI, thay `truongca` cũ (không có chức danh riêng trong sơ đồ thật) | * |
| `vanhanh` (Nhân viên vận hành) | operator | batch.execute, ebr.sign, warehouse.request, cip.manage | phan_xuong |
| `kcs` (Nhân viên KCS/QA) | qa | quality.release, quality.deviation, recipe.approve, ebr.sign, ebr.approve | * |
| `kysu` (Kỹ sư — P. Kỹ thuật, Công nghệ và Cải tiến Sản xuất) | engineer | master.manage, recipe.author, recipe.approve, batch.create, batch.execute, ebr.sign, cip.manage — tài khoản demo **DUY NHẤT** giữ `recipe.author` | * |
| `thukho` (Thủ kho NVL) | operator | warehouse.receive, warehouse.issue | cong_ty |
| `kcs_truongphong` (Trưởng phòng KCS) | qa | quality.release, quality.deviation, recipe.approve, ebr.sign, ebr.approve, **order.create** — khác NV KCS: Trưởng phòng KCS khóa chỉ tiêu VÀ tạo Lệnh lọc, NV KCS chỉ nhập/duyệt theo chỉ tiêu được gán | * |
| `giamdoc_sx` (Giám đốc Sản xuất - Kỹ thuật) | supervisor | **production.release_to_wms** (quyền MỚI, tách khỏi `quality.release` — KCS nhập/khóa chỉ tiêu, Giám đốc SX-KT quyết định duyệt lô chiết cho nhập kho thành phẩm; enforced trong `approve_bottle`, `routers/brewing.py`) | * |
| `ttdh_thukhotp` (NV Trung tâm Điều hành - Thủ kho TP) | operator | warehouse.receive, warehouse.issue (quản lý kho thành phẩm: xuất kho, điều chuyển, nhập bia cận date) | * |

> `vanhanh` chỉ có `warehouse.request` (tạo đề nghị nhận kho) — **không** có `warehouse.receive`/`issue`, nên không tự nhập/xuất trực tiếp NVL tại Kho phân xưởng được. Roster hiện không còn tài khoản "Thủ kho phân xưởng" riêng (đã bỏ `thukho_px`, không có trong sơ đồ thật) — chỉ `thukho` (Kho công ty NVL) và `ttdh_thukhotp` (Kho thành phẩm) có `warehouse.receive`/`issue`, phân biệt bằng **`scope_warehouse`** (§8.5/§8.7), không phải bằng permission riêng.

### 8.2b Copy quyền giữa tài khoản (admin)
`POST /api/auth/users/{username}/copy-permissions {source_username}` — ghi đè toàn bộ `role` + `allowed_views` + `permissions` + cả 4 chiều scope (`scope_lines`/`scope_areas`/`scope_qc`/`scope_warehouse`) của tài khoản đích bằng đúng cấu hình tài khoản nguồn; không đụng danh tính (username/mật khẩu/họ tên/chức danh) hay `active`/`must_change_password`. Dùng khi 2 người cùng chức danh cần cấu hình quyền giống hệt nhau, khỏi gán tay từng mục. *(admin)*; audit `action=copy_permissions` (before/after đầy đủ).

### 8.3 Catalog quyền thao tác (permission) — 23 quyền, áp ở tầng router/service (`require_perm`)
`master.manage` · `order.create` · `wo.manage` · `wo.dispatch` · `batch.create` · `batch.execute` · `recipe.author` · `recipe.approve` · `quality.release` · `quality.deviation` · `production.release_to_wms` · `ebr.sign` · `ebr.approve` · `warehouse.receive` · `warehouse.issue` · `warehouse.request` · `maintenance.manage` · `calibration.manage` · `energy.update` · `user.manage` · `integration.manage` · `integration.import` · `cip.manage`.

Hai quyền mới thêm so với bản trước (21 quyền): `production.release_to_wms` (Giám đốc/Phó GĐ Sản xuất - Kỹ thuật duyệt lô chiết nhập kho thành phẩm, tách khỏi `quality.release`) và `cip.manage` (khai báo/thao tác vệ sinh CIP — xem §5.14).

### 8.4 Segregation of Duties (SoD) — `enforce_sod`
Soạn recipe ≠ Duyệt recipe · Ghi kết quả QC ≠ Release QC · Ký EBR ≠ Phê duyệt/khóa EBR.

### 8.5 Data-scoping (phân quyền theo dữ liệu) — `require_scope` / `filter_by_scope`
- **`scope_lines`** — dây chuyền: lọc Work Order & Batch.
- **`scope_areas`** — khu vực `nau/len_men/loc/chiet/kho` (giá trị `kho` là **một khu vực duy nhất**, không tách công ty/phân xưởng).
- **`scope_qc`** — loại test QC: chặn KCS ghi parameter ngoài phạm vi. Danh sách "Loại chỉ tiêu QC" trong scope-picker (khi phân quyền tài khoản) nay lấy từ **Danh mục chỉ tiêu** (`QCParameter`, `active=True`) thay vì chỉ liệt kê chỉ tiêu ĐÃ có kết quả ghi nhận trong `QualityResult` — tránh thiếu chỉ tiêu mới chưa ai ghi kết quả (gộp thêm mã cũ trong `QualityResult` không còn trong Danh mục để không mất scope đã gán cho tài khoản từ trước).
- **`scope_warehouse`** — địa điểm kho NVL: `"cong_ty"` | `"phan_xuong"` | `"*"` — chặn thao tác kho ngoài địa điểm được phân (chi tiết §8.7).
> Bản ghi cũ chưa gắn scope (null) **không bị khóa**.

### 8.6 Audit bất biến & chữ ký điện tử (21 CFR Part 11)
`record_audit` tuần tự hóa (khóa tiến trình/DB); `seq` UNIQUE; `GET /api/audit/verify-chain` kiểm tra hash-chain; e-signature yêu cầu nhập lại mật khẩu + lý do + hash nội dung.

Tab Audit trail (frontend) nay thêm **cột "Module" đầu bảng** — ánh xạ `entity_type` → tên module trên thanh menu chính (VD `finished_goods_unit` → "Kho TP (WMS)", `cip_record` → "CIP", `finished_product` → "Danh mục") để biết 1 dòng audit thuộc phân hệ nào mà không cần đoán qua mã kỹ thuật. Nút **"Xem chi tiết"** mở modal so sánh **diff trước/sau theo từng trường**, dịch `entity_type`/`action`/tên trường sang tiếng Việt (kèm mã gốc để đối chiếu, tự "làm đẹp" field lạ chưa có trong từ điển) — thay vì chỉ hiện JSON thô như trước.

### 8.7 Kho công ty vs Kho phân xưởng — địa điểm kho enforce ở tầng server (`scope_warehouse`)
Ranh giới địa điểm kho **được enforce ở server**, không chỉ ở menu UI, qua chiều data-scoping thứ 4 `User.scope_warehouse` (§8.5):

- **Phân loại địa điểm**: `location` trên `MaterialLot`/`StockMovement.location_from/to`/`StockCount.location` vẫn là **chuỗi tự do** (`"Kho công ty"` / `"Kho phân xưởng"` …) — `_warehouse_token(location)` (services/warehouse.py) tái dùng `_is_workshop_location()` để quy về `"cong_ty"` hoặc `"phan_xuong"`, đối chiếu với `scope_warehouse` của user (`"cong_ty"` | `"phan_xuong"` | `"*"` = không giới hạn).
- **Thao tác 1 địa điểm** — `receive()`, `return_stock()`, `issue()`, `create_count()`, `update_count_lines()`, `post_count()`, `approve_count()`, `undo_count()`: mỗi hàm gọi `_assert_location_scope(user, location)` → 403 nếu `location` ngoài `scope_warehouse` của user. `location` rỗng/None (vd kiểm kê không lọc theo kho cụ thể) **không bị khoá**, theo đúng quy ước "bản ghi chưa gắn phạm vi cụ thể thì không khoá cứng" như 3 chiều scope kia.
- **`transfer()` (chuyển kho, đụng 2 địa điểm)** — `_assert_transfer_scope(user, loc_from, loc_to)`: cho phép nếu user có `scope_warehouse` khớp **ít nhất 1 trong 2 đầu** (nguồn hoặc đích), chỉ chặn khi không khớp đầu nào. Đây là quy tắc cố ý: Thủ kho công ty (`cong_ty`) vẫn cần duyệt/hoàn tác "Đề nghị nhận kho" — luồng này luôn có 1 đầu là Kho công ty — nhưng không được dùng tài khoản đó để bắc cầu chuyển thẳng giữa 2 vị trí đều thuộc Kho phân xưởng.
- **Các endpoint gọi gián tiếp qua `transfer()`/`issue()`/`return_stock()`** (`fulfill_request_line`, `fulfill_all_lines`, `undo_fulfill_line`, `transfer_to_company`, `return_to_supplier`, `undo_issue`…) thừa hưởng nguyên vẹn kiểm tra trên, không cần thêm guard riêng.
- **Admin bỏ qua mọi kiểm tra `scope_warehouse`** (như mọi chiều scope khác) — dùng cho fixture/test hoặc thao tác vượt phạm vi khi thật sự cần.
- **Tài khoản demo**: `thukho` → `scope_warehouse="cong_ty"`; `vanhanh` → `"phan_xuong"`; các tài khoản còn lại (`quandoc`, `phoquandoc`, `kcs`, `kysu`, `kcs_truongphong`, `giamdoc_sx`, `ttdh_thukhotp`) → `"*"` (không giới hạn — `ttdh_thukhotp` thao tác kho thành phẩm/WMS, không phải kho NVL công ty/phân xưởng nên không dùng chiều scope này).
- **"Xuất tự do"** (miễn phí, không qua phiếu) vẫn khoá **admin-only** riêng (`require_role(ADMIN)`) ở cả 2 màn hình — độc lập với `scope_warehouse`.

---

## 9. Tích hợp (integration)

### 9.1 Cổng API mở `/api/v1` — cho phần mềm ngoài (ERP/WMS/BI)
Xác thực **`X-API-Key`** theo scope `read`/`write`: `ping · production/batches · inventory · oee · energy · quality/alerts · traceability` (read) · `events?since_seq=` (read) · `POST events` (write). Quản trị: `/api/integration/keys`, `/api/integration/webhooks` (admin).

### 9.2 Kết nối CSDL SCADA ngoài + panel Realtime thật (tính năng mới)
- **`SqlConnection`** (Tích hợp › Kết nối CSDL): khai báo host/port/database/user/password (lưu server, không hiển thị lại) + **`purpose`** (CSV token) để mỗi service tự tìm đúng kết nối qua `get_connection_by_purpose()` — 1 kết nối vật lý có thể phục vụ nhiều mục đích (VD `energy_dm,filling`).
- **Chỉ đọc (`SELECT`)** — `test-connection`, `preview-table` (xem cột + mẫu dữ liệu) dùng SQLAlchemy reflection, không nối chuỗi SQL thô với tên bảng người dùng nhập.
- **Báo cáo từ CSDL ngoài**: `services/energy_external.py` (điện theo site/ca), `filling_external.py` (chiết lon 30K), `keg_external.py` (chiết keg) — đọc bảng lịch sử theo khoảng ngày.
- **Panel Realtime thật** (`GET /reports/filling-realtime`, `/reports/wastewater-realtime`): đọc **snapshot 1 dòng** (PLC ghi đè liên tục) từ bảng `30K_Realtime` / `QT_Realtime` — hiển thị **nguyên văn** các cột nguồn (không tính tốc độ/suy diễn); UI tự thử lại mỗi 15 giây; badge cảnh báo vượt ngưỡng QCVN cho trạm quan trắc nước thải.
- **Tự động thử lại kết nối lỗi**: tab Kết nối CSDL tự `test-connection` lại mỗi 15 giây cho các kết nối đang ở trạng thái Lỗi (không đụng tới kết nối đang OK), phục hồi badge khi WAN thông trở lại — không cần thao tác thủ công.

### 9.3 Import dữ liệu ngoài (Import Mapping Explorer)
Sub-tab trong Tích hợp: upload Excel/CSV → xem trước → xác thực (validate) → chạy import (run) theo **profile ánh xạ cột** đã lưu → lịch sử + log lỗi từng dòng. Hỗ trợ **custom field** — thêm trường tùy biến vào NVL/lô mà không cần đổi schema cứng (bảng riêng `integration_import.py`), xoá mềm (ẩn) hoặc xoá cứng.

### 9.4 Edge OT & Historian (mô phỏng nội bộ)
- **Historian** (`services/historian.py`): ingest theo tag UNS; downsample min/avg/max — dùng cho demo edge OT nội bộ, **khác** với panel Realtime SCADA thật ở §9.2 (đọc trực tiếp CSDL ngoài, không qua historian).
- **`opcua_edge.py`**: client OPC UA thật (asyncua) đọc tag Weihenstephan demo → historian.

### 9.5 Sinh tài liệu (docx/pptx)
`docs/build/md2docx.py` (Markdown → Word có bìa/mục lục/bảng định dạng) và `docs/build/build_decks.py` (dựng 3 bộ slide PowerPoint: Kiến trúc, Danh sách tính năng, Hướng dẫn sử dụng) — chạy thủ công khi cần đồng bộ tài liệu với mã nguồn.

### 9.6 Barcode / Kiosk
Tem **Code 39** (thuần JS) + **QR** (`segno`); `GET /api/scan` phân giải mã → lô/mẻ/WO/đơn; `GET /api/wms/resolve` cho unit thành phẩm.

---

## 10. Lớp AI (advisory)

| Thành phần | Mô tả |
|---|---|
| **AI vận hành** | `GET /api/ai/insights` — cảnh báo/đề xuất ưu tiên. **Không tự hành động.** |
| **Trợ lý AI chat** | `POST /api/ai/chat` & `/chat/stream` (SSE) — dùng Claude khi có `ANTHROPIC_API_KEY`; nếu không → engine luật offline. |
| **Bộ nhớ hội thoại** | `ai_conversation/ai_message` — lưu phía server, cô lập theo user. |
| **Lớp tool MES** | Tool read-only (`services/ai_tools.py`): inventory, OEE, quality alerts, batch status, calibrations due, open incidents, energy, trace_lot. `GET /api/ai/tools` xuất manifest. |
| **Tác vụ nền** | `POST /api/jobs {kind}` → chạy nền; `GET /api/jobs/{id}` poll. |

> **Nguyên tắc an toàn:** mọi tool AI đều read-only; rate-limit `/api/ai/*` + hạn mức chat/ngày; mỗi lượt gọi LLM được log model/token/USD ước tính/latency.

---

## 11. Quan sát & vận hành (observability)

- **Health**: `GET /api/health`. **Metrics**: `GET /metrics` (Prometheus). **Logging**: structured + request-id.
- **Rate-limit**: sliding-window in-proc (login chống brute-force; AI); pluggable Redis.
- **Job worker**: `ThreadPoolExecutor` + registry handler.

---

## 12. Triển khai & cấu hình

### 12.1 Chạy dev (SQLite)
```bash
cd backend
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m app.seed                       # tạo dữ liệu mẫu (1 lần)
./.venv/bin/python -m uvicorn app.main:app --port 8077
# UI: http://localhost:8077/   ·   Swagger: /docs   ·   Health: /api/health
```

### 12.2 Chạy production (Docker + PostgreSQL)
```bash
cp .env.example .env
docker compose up -d
```

### 12.3 Migration, test, sao lưu
- **Alembic**: `alembic upgrade head` (prod); dev dùng `create_all` qua `init_db()` — ~90 migration tích lũy qua các đợt tính năng.
- **Test**: `cd backend && pytest -q` — **57 file test**. **CI**: ruff lint + pytest + docker build.
- **Backup/Restore**: `scripts/backup.sh` / `restore.sh` / `test_restore.sh`.

### 12.4 Biến cấu hình chính (`MES_*`)
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `MES_DATABASE_URL` | SQLite local | Đổi sang `postgresql+psycopg://…` cho prod |
| `ANTHROPIC_API_KEY` | "" | Bật Claude thật; rỗng → engine luật offline |
| `MES_SESSION_HOURS` | 12 | Hết hạn phiên |
| `MES_ADMIN_PASSWORD` | "" | Rỗng → `admin123` + buộc đổi |
| `MES_SEED_DEMO` | True (dev) / 0 (compose) | Tạo tài khoản/API key/dữ liệu demo hay chỉ admin |
| `MES_DEV_HEADER_AUTH` | False | Bypass token bằng header (chỉ dev) |
| `MES_RL_ENABLED` / `MES_RL_LOGIN_PER_MIN` / `MES_RL_AI_PER_MIN` | True/10/20 | Rate-limit |
| `MES_AI_DAILY_QUOTA` | 300 | Hạn mức chat AI/ngày |
| `MES_REDIS_URL` | "" | Backend rate-limit đa worker |
| `MES_LOG_LEVEL` / `MES_LOG_JSON` | INFO / False | Logging |

---

## 13. Giới hạn & ranh giới tích hợp thật (chủ ý cho MVP)

- **Panel Realtime SCADA** (§9.2) đã đọc **CSDL SCADA thật** qua WAN — không còn là mô phỏng; nhưng chỉ 2 nguồn (30K_Realtime, QT_Realtime) đã nối, các nguồn khác cần cấu hình `SqlConnection` + viết service tương tự.
- **Historian nội bộ** (§9.4) vẫn ở dạng mô phỏng edge (demo OPC UA) — khác panel Realtime SCADA thật.
- **SSO/OIDC + MFA** chưa tích hợp; hiện dùng token nội bộ.
- **`availability`** (kiểm tra tồn trước khi tạo mẻ) là tư vấn, chưa giữ chỗ tồn (TOCTOU).
- **Worker nền** in-process; quy mô rất lớn → Celery/RQ + Redis broker.
- Hồ sơ **CSV/IQ-OQ-PQ** & **UAT theo ca thật** thuộc quy trình tại site.

> Các điểm này là **chủ ý**: triển khai tăng dần, không đưa OT/AI lên critical path quá sớm. Mọi phần mô phỏng đều có **điểm tích hợp chuẩn** để cắm thiết bị/DB thật về sau.
