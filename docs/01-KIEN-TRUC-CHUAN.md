# Tài liệu Kiến trúc Chuẩn — MES Bia Hạ Long (Nhà Máy Đông Mai)

> Phần mềm điều hành sản xuất (Manufacturing Execution System) cho nhà máy bia.
> Tài liệu này mô tả kiến trúc *thực tế đã hiện thực* trong mã nguồn, không phải bản đề xuất.
> Tham chiếu blueprint nội bộ `MES-ARCH-002` (*MES-Nha-may-Bia-Kien-truc-Chuan-V2.0*).

**Phiên bản phần mềm:** `0.1.0-mvp` · **Tên ứng dụng:** `MES Bia Hạ Long - Nhà Máy Đông Mai`

---

## 1. Tổng quan & nguyên tắc kiến trúc

MES này điều phối toàn bộ vòng đời sản xuất bia: **Lệnh sản xuất → Điều độ (Work Order) → Mẻ (Batch) → Công thức/Phiên bản → Kiểm soát chất lượng (hold/release) → Phả hệ (Genealogy) → Kiểm toán (Audit)**, đồng thời bao trùm các phân hệ chiều sâu: ISA-88, LIMS/QC nâng cao, OEE/downtime, kho NVL & kho thành phẩm (WMS), năng lượng, bảo trì/kiểm định, historian thời gian thực, lập lịch tối ưu, và lớp AI tư vấn.

### Nguyên tắc nền tảng

| Nguyên tắc | Hiện thực |
|---|---|
| **Modular monolith** | Một tiến trình FastAPI, chia theo *bounded context* (mỗi phân hệ có model → service → router riêng). Dễ tách microservice sau này. |
| **Bounded context** | Mỗi module sở hữu dữ liệu của mình; truy cập chéo đi qua **service layer**, không truy vấn trực tiếp bảng của module khác. |
| **REST/JSON, OpenAPI tự sinh** | Toàn bộ API theo REST; tài liệu Swagger tại `/docs`. |
| **RDBMS chuẩn** | SQLAlchemy 2.0 ORM; **SQLite** để chạy ngay (dev), **PostgreSQL 16** cho production (đổi qua biến môi trường). |
| **Source of Record bất biến** | Mẻ chụp snapshot công thức bất biến; audit append-only có hash-chain; EBR khóa được. |
| **Human-in-the-loop** | AI **chỉ tư vấn**, mọi hành động sản xuất cần con người + đúng quyền. |
| **Zero-build frontend** | UI web bằng vanilla JS + SVG, không framework, không bước build — chạy offline. |

---

## 2. Sơ đồ tầng (layered architecture)

```
┌─────────────────────────────────────────────────────────────────────┐
│  CLIENT                                                               │
│  • Web UI đầy đủ (/)            • Kiosk cảm ứng (/kiosk.html)          │
│  • Swagger /docs                • Phần mềm ngoài (ERP/WMS/BI) qua API  │
│  • Edge connector (OPC UA/MQTT) • AI agent / MCP (manifest tool)      │
└───────────────┬───────────────────────────────────────┬─────────────┘
                │ Authorization: Bearer <token>          │ X-API-Key (scope)
┌───────────────▼───────────────────────────────────────▼─────────────┐
│  MIDDLEWARE (main.py)                                                 │
│  request-id · rate-limit · đo độ trễ · log JSON · /metrics            │
│  ánh xạ lỗi nghiệp vụ → HTTP (404 / 409 / 403)                        │
└───────────────┬──────────────────────────────────────────────────────┘
┌───────────────▼──────────────────────────────────────────────────────┐
│  ROUTERS (REST endpoints) — ~31 router, ~180 endpoint                 │
│  auth · orders · workorders · recipes · batches · dispense · quality  │
│  quality_adv · traceability · performance · downtime · warehouse      │
│  energy · maintenance · process · brewing · reports · historian       │
│  scan · schedule · ai · jobs · isa88 · wms · label · lines            │
│  packaging · gateway · audit · master · materials                     │
└───────────────┬──────────────────────────────────────────────────────┘
┌───────────────▼──────────────────────────────────────────────────────┐
│  SERVICES (quy tắc nghiệp vụ) — 23 module                             │
│  batches · recipes · workorders · isa88 · genealogy · bom · dispense  │
│  warehouse · quality · quality_adv · ebr · yield_calc · downtime      │
│  performance · scheduler · historian · wms · packaging · ai           │
│  ai_tools · conversations · jobs · derived                            │
└───────────────┬──────────────────────────────────────────────────────┘
┌───────────────▼──────────────────────────────────────────────────────┐
│  MODELS (SQLAlchemy ORM) — ~40 bảng theo bounded context              │
└───────────────┬──────────────────────────────────────────────────────┘
┌───────────────▼──────────────────────────────────────────────────────┐
│  DATABASE   SQLite (dev)  │  PostgreSQL 16 (prod) — Alembic migration  │
└───────────────────────────────────────────────────────────────────────┘

   Cross-cutting (xuyên suốt mọi tầng):
   security.py (RBAC/SoD/scope) · audit.py (hash-chain) · config.py (Settings)
   logging_config.py (request-id, log chi phí AI) · ratelimit.py · metrics_prom.py
```

**Quy tắc phụ thuộc:** Router → Service → Model. Service **không** phụ thuộc ngược Router (truy vấn dẫn xuất được gom vào `services/derived.py` để cắt vòng phụ thuộc).

---

## 3. Ngăn xếp công nghệ (tech stack)

| Lớp | Công nghệ | Phiên bản | Ghi chú |
|---|---|---|---|
| Web framework | **FastAPI** | 0.111.0 | OpenAPI tự sinh, `lifespan`, middleware |
| ASGI server | **Uvicorn** | 0.30.1 | `[standard]` |
| ORM | **SQLAlchemy** | 2.0.30 | `DeclarativeBase`, session-per-request |
| Validation/cấu hình | **Pydantic** + **pydantic-settings** | 2.7.4 / 2.3.4 | `config.Settings` gom mọi biến `MES_*` |
| Migration | **Alembic** | — | 6+ migration; chuỗi `4b0bfd…→89f74f…→a1b2c3…` |
| CSDL | **SQLite** (dev) / **PostgreSQL 16** (prod) | — | Đổi qua `MES_DATABASE_URL` |
| Edge OT | **asyncua** (OPC UA) | 1.1.8 | Tiến trình `app.opcua_edge`; core app không import |
| Mã vạch / QR | **segno** (QR) + Code39 thuần JS | 1.6.6 | Tem pallet/case/lô |
| AI (tùy chọn) | **anthropic** SDK (Claude) | 0.69.0 | `claude-opus-4-8`; không có key → engine luật offline |
| Multipart | python-multipart | 0.0.9 | Form upload |
| Frontend | **Vanilla JS + SVG** | — | Không framework, không build |
| Cache/rate-limit (tùy chọn) | **Redis** | — | `MES_REDIS_URL`; tự fallback in-process |
| Observability | **Prometheus** text exposition | — | `/metrics` không thêm dependency |
| Đóng gói | **Docker** + docker-compose | — | app FastAPI + PostgreSQL 16 |
| CI | **GitHub Actions** | — | ruff lint + pytest + docker build |

---

## 4. Cấu trúc thư mục

```
MES/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app: mount router + UI, middleware, ánh xạ lỗi→HTTP
│   │   ├── config.py          # Settings (pydantic-settings) — mọi biến MES_*
│   │   ├── database.py        # engine/session SQLAlchemy, init_db()
│   │   ├── common.py          # Enum + bảng state-transition (batch/recipe/deviation/WO/phase)
│   │   ├── security.py        # User, token, require_role/require_perm/require_scope, enforce_sod
│   │   ├── audit.py           # ghi audit append-only + hash-chain + verify_chain
│   │   ├── errors.py          # lỗi nghiệp vụ (NotFound/Domain/Permission)
│   │   ├── logging_config.py  # log JSON, request-id, log chi phí AI
│   │   ├── ratelimit.py       # sliding-window in-proc hoặc Redis
│   │   ├── metrics_prom.py    # Prometheus counters/gauges
│   │   ├── seed.py            # dữ liệu mẫu + kịch bản 1 mẻ end-to-end
│   │   ├── edge_sim.py        # mô phỏng edge gateway (đẩy telemetry qua API key)
│   │   ├── opcua_edge.py      # client OPC UA THẬT (asyncua) → historian
│   │   ├── models/            # ORM theo bounded context (~40 bảng)
│   │   ├── services/          # quy tắc nghiệp vụ (23 module)
│   │   └── routers/           # REST endpoints (~31 router)
│   ├── alembic/               # migration (versions/)
│   ├── tests/                 # pytest: smoke + depth + opcua (30/30 pass)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                  # UI vanilla JS (zero-build)
│   ├── index.html  app.js  views_ext.js  charts.js  barcode.js  styles.css
│   └── kiosk.html  kiosk.js  # giao diện cảm ứng cho xưởng
├── scripts/                   # backup.sh · restore.sh · test_restore.sh
├── .github/workflows/ci.yml
├── docker-compose.yml         # app + PostgreSQL 16
└── .env.example
```

---

## 5. Mô hình dữ liệu (bounded context → bảng)

~40 bảng ORM, nhóm theo bounded context. Mỗi bảng dưới đây thuộc một file trong `app/models/`.

### 5.1 Xác thực & phân quyền (`auth.py`)
| Bảng | Mục đích |
|---|---|
| `app_user` (**User**) | Tài khoản: username, mật khẩu băm PBKDF2, role, `allowed_views`, `permissions`, `scope_lines/areas/qc`, `must_change_password`, `active` |
| `user_session` (**UserSession**) | Phiên đăng nhập: token, user_id, role, created_at, expires_at (mặc định 12h) |

### 5.2 Master data (`master.py`, `lines.py`)
| Bảng | Mục đích |
|---|---|
| `product` (**Product**) | Sản phẩm (loại bia): mã, tên, ĐVT |
| `material` (**Material**) | Nguyên vật liệu (malt/hop/men/vỏ chai): mã, tên, nhóm |
| `production_line` (**ProductionLine**) | Dây chuyền/tank/nhà nấu: mã (khớp `OEERecord.line`), kind, area, `ideal_rate_per_min`, active |

### 5.3 Lệnh & điều độ (`orders.py`, `workorder.py`, `scheduling.py`)
| Bảng | Mục đích |
|---|---|
| `production_order` (**ProductionOrder**) | Lệnh gốc từ ERP: SL, deadline, ưu tiên, trạng thái |
| `work_order` (**WorkOrder**) | Phân rã PO → kế hoạch ngày/ca/line; planned vs actual; trạng thái |
| `schedule_slot` (**ScheduleSlot**) | Khối thời gian chiếm tài nguyên (tank/line): production/cip/maintenance, start/end |

### 5.4 Công thức (`recipes.py`, `recipe_ext.py`)
| Bảng | Mục đích |
|---|---|
| `recipe` (**Recipe**) | Định danh công thức ổn định, gắn product |
| `recipe_version` (**RecipeVersion**) | Phiên bản: tham số, BOM (JSON), QC, `yield_steps`, thủ tục ISA-88 (`procedure`). Chỉ trạng thái **effective** mới chạy mẻ được |
| `recipe_change` (**RecipeChange**) | Phiếu kiểm soát thay đổi: lý do (bắt buộc), diff JSON, state (open/approved) |
| `batch_yield_actual` (**BatchYieldActual**) | Hiệu suất thực tế theo công đoạn: input/output + expected_pct |

### 5.5 Thực thi mẻ (`batches.py`, `isa88.py`, `metrics.py`)
| Bảng | Mục đích |
|---|---|
| `batch_execution` (**BatchExecution**) | **SoR thực thi mẻ**: trạng thái, snapshot recipe bất biến, actuals (JSON), `quality_status`, `ebr_locked` |
| `batch_phase_run` (**BatchPhaseRun**) | Log chạy phase ISA-88: unit procedure → operation → phase, state, params snapshot + actual |
| `process_reading` (**ProcessReading**) | Telemetry curated gắn mẻ (°P/°C/pH…): value, ts, quality |
| `oee_record` (**OEERecord**) | Dữ liệu ca đóng gói: planned_time, downtime, ideal_rate, total/good count |

### 5.6 Vật tư, lô & phả hệ (`materials.py`, `materials_ext.py`, `warehouse.py`)
| Bảng | Mục đích |
|---|---|
| `material_lot` (**MaterialLot**) | Lô NVL/bán thành phẩm: tồn, hạn dùng, vị trí, trạng thái |
| `genealogy_edge` (**GenealogyEdge**) | Cạnh có hướng: from/to (type,id), relation (consume/produce/split/merge/transfer), qty, ts |
| `dispense` / `dispense_line` (**Dispense/DispenseLine**) | Phiếu cấp liệu cho mẻ (mode dispense/backflush) + dòng cấp |
| `stock_movement` (**StockMovement**) | **Sổ cái kho bất biến**: receipt/issue/return/transfer/adjust |

### 5.7 Chất lượng (`quality.py`, `quality_ext.py`)
| Bảng | Mục đích |
|---|---|
| `quality_result` (**QualityResult**) | Kết quả QC: value, lower/upper; PASS/FAIL tính số học; FAIL → ON_HOLD tự động |
| `deviation` (**Deviation**) | Lệch chuẩn: severity, workflow open→…→closed |
| `qc_parameter` (**QCParameter**) | Định nghĩa chỉ tiêu SPC: target, USL/LSL, stage |
| `capa` (**CAPA**) | Hành động khắc phục/phòng ngừa: workflow |
| `lims_sample` (**Sample**) | Phiếu mẫu LIMS-lite: status, test_set |

### 5.8 Công đoạn nấu bia chi tiết (`brewing.py`, `process.py`)
| Bảng | Mục đích |
|---|---|
| `material_receipt` (**MaterialReceipt**) | Nhập nguyên liệu: MSKT, lô PM/KCS, NCC |
| `brew_record` (**BrewRecord**) | Nấu: brew_code, dịch nha, volume, °P, độ hòa tan |
| `ferment_record` (**FermentRecord**) | Lên men: lm_code, tank, đời men, tồn CCT, trạng thái |
| `filter_record` (**FilterRecord**) | Lọc CCT→BBT: v_dich, v_beer, tank BBT, trạng thái chiết |
| `bottle_record` (**BottleRecord**) | Chiết: theo ca 1/2/3, dây chuyền, đã nhập kho, đã duyệt |
| `stage_indicator` (**StageIndicator**) | Chỉ tiêu phân tích gắn công đoạn: stage, scope_code, value/unit, cảnh báo |
| `chemical_usage` (**ChemicalUsage**) | Hóa chất theo công đoạn mẻ |
| `yeast_lot` / `yeast_issue` (**YeastLot/YeastIssue**) | Thu hồi & cấy men: đời, sống/sinh lực, lịch sử cấp |

### 5.9 Bảo trì, kiểm định, năng lượng, downtime
| Bảng (file) | Mục đích |
|---|---|
| `equipment`, `spare_part`, `incident`, `maintenance_plan`, `calibration` (`maintenance.py`) | CMMS: thiết bị, phụ tùng (tồn min), sự cố, kế hoạch bảo trì (tự đánh dấu quá hạn), kiểm định (valid/due/overdue) |
| `downtime_event` (`oee_ext.py`) | Sự kiện dừng máy: reason_group/code, loss_category, phút |
| `energy_group`, `energy_area`, `energy_reading` (`energy.py`) | Năng lượng: nhóm/khu, số đọc ngày (unique theo ngày/nhóm/khu) |

### 5.10 Kho thành phẩm & bao bì (`wms.py`, `packaging.py`)
| Bảng | Mục đích |
|---|---|
| `wms_location` (**WmsLocation**) | Vị trí kho: zone, kind (bin/staging/cold/dock), capacity |
| `pallet` / `wms_case` (**Pallet/Case**) | Pallet & case có barcode Code39; trạng thái building/stored/shipped |
| `packaging_type` / `packaging_move` (**PackagingType/PackagingMove**) | Bao bì tuần hoàn (vỏ chai/két-gông/keg): tồn, lưu hành, cược; biến động |

### 5.11 Lịch sử thời gian thực (`historian.py`)
| Bảng | Mục đích |
|---|---|
| `historian_point` (**HistorianPoint**) | Telemetry theo tag UNS `brewery/site/area/device/metric`: value, unit, quality, source, ts. Index (tag,ts). MVP SQLite, swap được TimescaleDB/Influx |

### 5.12 Tích hợp, kiểm toán, chữ ký, AI, job
| Bảng (file) | Mục đích |
|---|---|
| `api_key`, `webhook` (`integration.py`) | API key (scope read/write, call_count) + webhook (event_types, HMAC secret) |
| `audit_log` (`audit.py`) | **Append-only**: ai/khi/hành động/before-after, correlation_id, `seq` UNIQUE, `entry_hash` |
| `esignature`, `ebr_snapshot` (`signature.py`) | Chữ ký điện tử (21 CFR Part 11) + snapshot EBR bất biến (content_hash) |
| `ai_conversation`, `ai_message` (`ai_memory.py`) | Bộ nhớ hội thoại AI lưu phía server, cô lập theo user |
| `job` (`jobs.py`) | Tác vụ nền: kind, status, progress, result |

---

## 6. State machine (máy trạng thái) cốt lõi

Mọi chuyển trạng thái phải hợp lệ; sai → **HTTP 409**. Định nghĩa tại `common.py`.

**Mẻ (BatchState):**
```
planned → ready → running → held → completed → closed
                    ↑___________↓
        (+ cancelled từ các trạng thái chưa hoàn tất)
```

**Công thức (RecipeState):**
```
draft → review → approved → effective → suspended → (effective lại)
                                effective/suspended → obsolete
```
> **Chỉ phiên bản `effective` mới được dùng để chạy mẻ.**

**Lệnh SX (WorkOrderState):** `planned → released → in_progress → completed → closed` (+ cancelled)

**Deviation:** `open → triage → investigation → disposition → approval → closed`

**Chất lượng (QualityStatus):** `pending → on_hold ⇄ released → rejected` (FAIL tự đưa về `on_hold`)

**Lô (LotStatus):** `available → consumed`; nhánh `on_hold / released / scrapped`

**Phase ISA-88 (PhaseState):** `idle → running → held → complete` (+ aborted)

**Quan hệ phả hệ (GenealogyRelation):** `consume` (lô→mẻ), `produce` (mẻ→lô), `split`, `merge`, `transfer`

---

## 7. Luồng nghiệp vụ cốt lõi

### 7.1 Vòng đời sản xuất một mẻ
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

### 7.2 Quy tắc bất biến đã thực thi
- **Recipe snapshot bất biến**: khi tạo mẻ, copy toàn bộ params/materials/QC của version → sửa recipe sau này không đổi hồ sơ mẻ đã chạy.
- **State machine**: mẻ/recipe/WO/deviation/phase chỉ chuyển theo transition hợp lệ.
- **Genealogy**: mọi consume/produce tạo cạnh có hướng (qty, ts) → truy xuất đồ thị xuôi/ngược + recall.
- **QC tự động**: PASS/FAIL theo giới hạn số học; FAIL tự đưa scope về ON HOLD.
- **Audit append-only + hash-chain**: mỗi bản ghi `entry_hash = sha256(prev_hash + nội dung)`; `verify-chain` phát hiện giả mạo.
- **EBR khóa → mẻ bất biến**: sau khóa, transition/consume/produce/actual đều 409, chỉ amendment.

---

## 8. Bảo mật & phân quyền

### 8.1 Xác thực
- **Đăng nhập thật**: mật khẩu băm **PBKDF2-HMAC-SHA256, 100.000 vòng**, salt ngẫu nhiên; so sánh chống timing (`compare_digest`).
- **Token phiên** (urlsafe, 32 byte) lưu DB + `localStorage`, gửi qua header `Authorization: Bearer …`; phiên **12 giờ** (`MES_SESSION_HOURS`).
- `get_current_user` **yêu cầu token**; không có → 403.
- **Fallback dev** `X-User`/`X-Role` (toàn quyền) **mặc định TẮT**, chỉ bật khi `MES_DEV_HEADER_AUTH=1` (chỉ cho `/docs`/test).
- **`must_change_password`**: admin tạo bằng mật khẩu mặc định → buộc đổi lần đầu.

### 8.2 RBAC — 5 vai trò
`operator` · `supervisor` · `qa` · `engineer` · `admin`. Admin bỏ qua `require_perm`/`require_scope`/`require_role` (nhưng **vẫn bị ràng buộc SoD**).

### 8.3 Catalog quyền thao tác (permission) áp ở tầng API (`require_perm`)
`master.manage`, `order.create`, `wo.manage`, `wo.dispatch`, `batch.create`, `batch.execute`, `recipe.author`, `recipe.approve`, `quality.release`, `quality.deviation`, `ebr.sign`, `ebr.approve`, `warehouse.receive`, `warehouse.issue`, `maintenance.manage`, `calibration.manage`, `energy.update`, `user.manage`, `integration.manage`.

### 8.4 Segregation of Duties (SoD) — `enforce_sod`
Người thực hiện bước sau **không được trùng** người thực hiện bước trước:
- Soạn recipe ≠ Duyệt recipe.
- Ghi kết quả QC ≠ Release QC.
- Ký EBR ≠ Phê duyệt/khóa EBR.

### 8.5 Data-scoping (phân quyền theo dữ liệu) — `require_scope` / `filter_by_scope`
Ba chiều giới hạn phạm vi mỗi tài khoản (giá trị CSV hoặc `*`):
- **`scope_lines`** — dây chuyền (vd `Nấu A`): lọc Work Order & Batch.
- **`scope_areas`** — khu vực `nau/len_men/loc/chiet/kho`: lọc công đoạn/thiết bị/năng lượng.
- **`scope_qc`** — loại test QC (vd `Độ đường (°P),pH`): chặn KCS ghi parameter ngoài phạm vi.
> Bản ghi cũ chưa gắn scope (null) **không bị khóa** (tránh chặn dữ liệu lịch sử).

### 8.6 Audit bất biến & chữ ký điện tử (21 CFR Part 11)
- Audit `record_audit` tuần tự hóa bằng `pg_advisory_xact_lock` (Postgres) + khóa tiến trình; cột `seq` UNIQUE (fail-loud chống race).
- `GET /api/audit/verify-chain` kiểm tra toàn vẹn hash-chain.
- E-signature yêu cầu **nhập lại mật khẩu** + lưu ý nghĩa/lý do + hash nội dung tại thời điểm ký.

---

## 9. Tích hợp (integration)

### 9.1 Cổng API mở `/api/v1` — cho phần mềm ngoài (ERP/WMS/BI)
Xác thực **`X-API-Key`** theo scope `read`/`write`:
- `GET /api/v1/ping` · `/production/batches` · `/inventory` · `/oee` · `/energy` · `/quality/alerts` · `/traceability` (read)
- `GET /api/v1/events?since_seq=` — feed sự kiện (read); `POST /api/v1/events` — nhận sự kiện ngoài (write, ghi qua `record_audit` nên không gãy hash-chain).
- Quản trị: `/api/integration/keys`, `/api/integration/webhooks` (vai trò admin) — tạo/khóa API key, đăng ký webhook (HMAC secret).

### 9.2 Edge OT & Historian
- **Historian** `services/historian.py`: ingest theo tag UNS; `POST /api/historian/ingest` (X-API-Key write), `GET /api/historian/{tags,latest,series}` (downsample min/avg/max).
- **`app/edge_sim.py`**: tiến trình độc lập mô phỏng gateway OPC UA/MQTT, đẩy 8 tag qua API key.
- **`app/opcua_edge.py`**: client OPC UA **thật** (asyncua) đọc bộ tag chuẩn **Weihenstephan** → map UNS → historian. Chạy demo: `python -m app.opcua_edge --demo`. *Ranh giới production:* trỏ tới PLC/SCADA thật tại hiện trường.

### 9.3 Barcode / Kiosk
- Tem **Code 39** (thuần JS) + **QR** (`segno`, `GET /api/label/qr`).
- `GET /api/scan` phân giải mã → lô/mẻ/WO/đơn hàng; `GET /api/wms/resolve` cho pallet/case.

---

## 10. Lớp AI (advisory)

| Thành phần | Mô tả |
|---|---|
| **AI vận hành** | `GET /api/ai/insights` — quét dữ liệu thật, sinh cảnh báo/đề xuất có mức ưu tiên (tồn/hạn dùng, kiểm định quá hạn, sự cố, QC FAIL, OEE thấp). **Không tự hành động.** |
| **Trợ lý AI chat** | `POST /api/ai/chat` & `/chat/stream` (SSE) — hỏi-đáp trên dữ liệu MES. Dùng **Claude `claude-opus-4-8`** (adaptive thinking, tool-use) khi có `ANTHROPIC_API_KEY`; nếu không → **engine luật offline**. |
| **Bộ nhớ hội thoại** | `ai_conversation/ai_message` — lưu lịch sử phía server, cô lập theo user; `GET/DELETE /api/ai/conversations`. |
| **Lớp tool MES** | 8 tool **read-only** dùng chung (`services/ai_tools.py`): inventory, OEE, quality alerts, batch status, calibrations due, open incidents, energy, trace_lot. `GET /api/ai/tools` xuất manifest cho AI agent/MCP. |
| **Tác vụ nền** | `POST /api/jobs {kind}` → chạy nền (ai_report, recall); `GET /api/jobs/{id}` poll. |

> **Nguyên tắc an toàn:** mọi tool AI đều read-only; **không** tool nào đổi setpoint/điều khiển thiết bị/ghi dữ liệu sản xuất.
> **Kiểm soát chi phí:** rate-limit `/api/ai/*` 20/phút/phiên + hạn mức chat **300/ngày** (`MES_AI_DAILY_QUOTA`); mỗi lượt gọi LLM được log model/token/USD ước tính/latency.

---

## 11. Quan sát & vận hành (observability)

- **Health**: `GET /api/health` — kiểm tra kết nối DB + dialect + version (cho monitoring/readiness).
- **Metrics**: `GET /metrics` (Prometheus, không thêm dep): `mes_http_requests_total{route,status}` + thời gian, `mes_ai_calls/errors/tokens_total`, `mes_ratelimit_blocks_total`, gauge `mes_audit_chain_intact`/`mes_audit_entries`.
- **Logging**: structured + **request-id** (`X-Request-ID` mỗi request); log JSON tùy chọn (`MES_LOG_JSON=1`); log chi phí AI mỗi lượt.
- **Rate-limit**: middleware in-proc sliding-window (login chống brute-force 10/phút/IP; AI 20/phút/phiên); pluggable **Redis** (`MES_REDIS_URL`, tự fallback).
- **Job worker**: `ThreadPoolExecutor` + registry handler; quy mô lớn thay bằng Celery/RQ (interface `submit()/get()` giữ nguyên).

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
cp .env.example .env            # chỉnh POSTGRES_PASSWORD, MES_ADMIN_PASSWORD
docker compose up -d            # app FastAPI + PostgreSQL 16; tự alembic upgrade head
# HTTPS qua reverse proxy (mẫu nginx có sẵn trong compose, comment)
```
docker-compose đặt sẵn an toàn production: `MES_SEED_DEMO=0` (chỉ tạo admin), `MES_DEV_HEADER_AUTH=0`, `MES_LOG_JSON=1`.

### 12.3 Migration, test, sao lưu
- **Alembic**: `alembic upgrade head` (prod); dev dùng `create_all` qua `init_db()`.
- **Test**: `cd backend && pip install -r requirements-dev.txt && pytest -q` (**30/30 pass**). **CI**: ruff lint + pytest + docker build.
- **Backup/Restore**: `scripts/backup.sh` / `restore.sh` (pg_dump 3-2-1); `scripts/test_restore.sh` kiểm thử khôi phục vào DB scratch + verify hash-chain (lập lịch cron hàng tuần).

### 12.4 Biến cấu hình chính (`MES_*`)
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `MES_DATABASE_URL` | SQLite local | Đổi sang `postgresql+psycopg://…` cho prod |
| `ANTHROPIC_API_KEY` | "" | Bật Claude thật; rỗng → engine luật offline |
| `MES_LLM_MODEL` | `claude-opus-4-8` | Model LLM |
| `MES_LLM_ENABLED` | `auto` | auto/on/off |
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

- **Tích hợp thiết bị (#4)** chạy ở dạng **mô phỏng edge** (`edge_sim`) + client OPC UA thật demo; production cần trỏ tới PLC/SCADA thật + đầu đọc cầm tay vật lý.
- **Historian** dùng SQLite cho demo; production swap **TimescaleDB/InfluxDB** (interface đã sẵn điểm cắm).
- **SSO/OIDC + MFA** chưa tích hợp (cần IdP); hiện dùng token nội bộ. **HTTPS** qua reverse proxy (mẫu nginx có sẵn).
- **`availability`** (kiểm tra tồn trước khi tạo mẻ) là tư vấn, **chưa giữ chỗ tồn** → có thể chênh nếu nhiều mẻ tạo đồng thời (TOCTOU).
- **Worker nền** in-process; quy mô rất lớn → Celery/RQ + Redis broker.
- Hồ sơ **CSV/IQ-OQ-PQ** & **UAT theo ca thật** thuộc quy trình tại site.

> Các điểm này là **chủ ý**: tài liệu blueprint nhấn mạnh triển khai tăng dần, không đưa OT/AI lên critical path quá sớm. Mọi phần mô phỏng đều có **điểm tích hợp chuẩn** để cắm thiết bị/DB thật về sau.
