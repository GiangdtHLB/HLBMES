# MES Nhà máy Bia — MVP P0

Phần mềm MES (Manufacturing Execution System) cho nhà máy bia, hiện thực hóa **lõi P0**
trong blueprint kiến trúc `MES-ARCH-002` (tài liệu *MES-Nha-may-Bia-Kien-truc-Chuan-V2.0*).

> Đây là **MVP P0** — nền tảng để mở rộng theo lộ trình, **không phải** bản production hoàn chỉnh.
> Xem [Giới hạn & lộ trình](#giới-hạn--lộ-trình-mở-rộng) ở cuối.

## Lớp AI & Cổng tích hợp

| Thành phần | Mô tả | Tham chiếu |
|---|---|---|
| **AI vận hành** (advisory) | `GET /api/ai/insights` — quét dữ liệu thật, sinh cảnh báo/đề xuất có mức ưu tiên (tồn/hạn dùng, kiểm định quá hạn, sự cố, QC FAIL, OEE thấp). **Không tự hành động** — human-in-the-loop. | §1.1, §5.1 (P3) |
| **Trợ lý AI chat** | `POST /api/ai/chat` — hỏi-đáp trên dữ liệu MES. Dùng **Claude `claude-opus-4-8`** (adaptive thinking, tool-use) khi có `ANTHROPIC_API_KEY`; nếu không, dùng **engine luật nội bộ** (chạy offline). | §5.1 (P3) |
| **Lớp tool MES** | 8 tool read-only dùng chung cho trợ lý và AI agent (`services/ai_tools.py`). `GET /api/ai/tools` xuất **manifest** cho AI agent / MCP tương lai. | nền tảng agent |
| **Cổng API mở** `/api/v1` | Cho phần mềm ngoài (ERP/WMS/BI): xác thực **`X-API-Key`** theo scope read/write; batches, inventory, OEE, energy, quality, traceability; **feed sự kiện** `GET /api/v1/events` + nhận sự kiện `POST /api/v1/events`. | §9.1, §9.3 |
| **Quản trị tích hợp** | `/api/integration/keys`, `/api/integration/webhooks` (vai trò admin): tạo/khoá API key, đăng ký webhook. | §9 |

> **Nguyên tắc an toàn (tài liệu §1.1):** AI **chỉ tư vấn** — không có tool nào đổi setpoint, điều khiển thiết bị
> hay ghi dữ liệu sản xuất. Mọi tool MES dùng cho AI đều read-only; mọi hành động cần con người phê duyệt.
>
> **Bật Claude thật:** `pip install anthropic` (bỏ comment trong `requirements.txt`) + `export ANTHROPIC_API_KEY=...`
> Mặc định không có key → trợ lý vẫn chạy bằng engine luật. UI: tab **🤖 Trợ lý AI** và **Tích hợp**.
> API key demo (read-only) sau khi seed: `mes_demo_readonly_key_0001`.

## Phạm vi đã hiện thực (đúng §5.1 — ưu tiên P0)

| Năng lực | Trạng thái | Tham chiếu tài liệu |
|---|---|---|
| Lệnh sản xuất (Order) | ✅ | §7.1 |
| **Lệnh sản xuất & Điều độ** (PO→Work Order→dispatch→batch, kế hoạch ngày/ca/line, trạng thái, planned vs actual) | ✅ | §7.1 |
| Công thức + version + workflow duyệt + SoD | ✅ | §7.2 |
| **BOM / định mức NVL** — nhập theo dòng, hiển thị, scale theo mẻ, đối chiếu định mức↔thực tế | ✅ | §7.2, §7.4 |
| Thực thi mẻ + state machine + recipe snapshot bất biến | ✅ | §7.1, §4.2 |
| Tiêu thụ/sinh lô + đồ thị phả hệ (genealogy) | ✅ | §7.6, §8.2 |
| Chất lượng: ghi kết quả, pass/fail tự động, hold/release | ✅ | §7.5 |
| Deviation workflow | ✅ | §7.5 |
| Truy xuất ngược/xuôi + Recall simulation | ✅ | §7.6, §12 |
| Audit trail append-only | ✅ | §10.3 |
| RBAC + Segregation of Duties | ✅ (tối giản) | §7.8, §10.2 |
| **Đường cong lên men** (telemetry curated: °P/°C/pH) | ✅ | §7.4, §8.1 |
| **OEE đóng gói** (Availability × Performance × Quality) | ✅ | §7.7 |

> Biểu đồ vẽ bằng **SVG thuần** trong [frontend/app.js](frontend/app.js) (`CH.line` / `CH.donut` / `CH.hbars`) —
> không thư viện ngoài, không build, chạy offline. Dashboard hiển thị gauge OEE + phân rã A/P/Q; chi tiết mẻ hiển thị đường cong lên men.

### Các module nhà máy (theo hệ thống PX Đông Mai)

| Module (tab) | Chức năng | Tham chiếu |
|---|---|---|
| **Kho NVL** | Nhập/Xuất (đề nghị, tự do)/Nhập hoàn/Sang ngang; Xem tồn; Thẻ kho (có số dư luỹ kế); Hạn sử dụng; BC nhập-xuất-tồn | §7.4 |
| **Năng lượng** | Cập nhật số liệu ngày (upsert); biểu đồ ngày theo nhóm; tổng hợp tháng; DM nhóm/khu | §7.7 |
| **Bảo trì** | Thêm sự cố + xử lý; DM thiết bị/phụ tùng (cảnh báo tồn min); kế hoạch bảo trì/kiểm tra/tu bổ (tự đánh dấu quá hạn) | §7.7 (CMMS) |
| **Kiểm định** | Kiểm định/hiệu chuẩn (phóng xạ, van an toàn, hiệu chuẩn TBĐ, YCNNVAT) với trạng thái valid/due/overdue theo hạn | §3, §7.7 |
| **Nấu-Lọc-Chiết** (chi tiết) | Mô phỏng luồng sản xuất thực (PX Đông Mai): **Nguyên liệu** (số lô PM/KCS, NCC, màu trạng thái) → **Nấu** (dịch nha, °P, độ hòa tan) → **Lên men** (lô LM theo tank, đời men, tồn CCT, tổng cộng) → **Lọc** (CCT→BBT, Chờ chiết/Chiết 1 phần/Đã chiết hết) → **Chiết** (theo ca 1/2/3, dây chuyền, đã nhập kho, chiết duyệt) → **Cảnh báo chỉ tiêu** (theo tháng/năm) + Hóa chất + Thu hồi men | §4, §7.4, §7.5 |

Mỗi module có model → service → router → tab UI riêng (bounded context). API prefix: `/api/warehouse`,
`/api/energy`, `/api/maint`, `/api/process`, `/api/brewing`. Xem đầy đủ tại `/docs`.

**Màu trạng thái dữ liệu** (như hệ PX Đông Mai): đỏ = thiếu thông tin (số lô / chỉ tiêu / sản lượng),
xanh lá = chưa nhập NVL, xanh dương = đầy đủ, xanh nhạt = lọc vào BBT phối. Engine **Cảnh báo chỉ tiêu**
quét theo tháng/năm và liệt kê bản ghi nấu thiếu Plato/độ hòa tan, chiết sai sản lượng, lọc chưa nhập chỉ tiêu.

## Kiến trúc

Theo khuyến nghị tài liệu §6.2: **modular monolith**, REST/JSON (OpenAPI tự sinh),
RDBMS (PostgreSQL-compatible; mặc định SQLite để chạy ngay).

```
backend/
  app/
    main.py            # FastAPI app, mount router + UI, ánh xạ lỗi → HTTP
    config.py          # DATABASE_URL (đổi sang Postgres qua biến môi trường)
    database.py        # SQLAlchemy engine/session
    common.py          # enum + state-transition tables (batch/recipe/deviation)
    security.py        # User (X-User/X-Role), require_role, enforce_sod
    audit.py           # ghi audit append-only
    errors.py          # lỗi nghiệp vụ
    models/            # ORM theo bounded context: master/orders/recipes/batches/materials/quality/audit
    services/          # quy tắc nghiệp vụ: recipes, batches, quality, genealogy
    routers/           # REST endpoints
    seed.py            # dữ liệu mẫu + kịch bản 1 mẻ end-to-end
frontend/              # UI web vanilla JS (zero-build): index.html, app.js, styles.css
```

Mỗi module sở hữu dữ liệu của mình; truy cập chéo đi qua service layer (bounded context).

## Chạy

```bash
cd backend
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m app.seed          # tạo dữ liệu mẫu (1 lần)
./.venv/bin/python -m uvicorn app.main:app --port 8077
```

Mở:
- **UI**: http://localhost:8077/
- **API docs (Swagger)**: http://localhost:8077/docs
- **Health**: http://localhost:8077/api/health

> Dùng PostgreSQL: đặt `MES_DATABASE_URL=postgresql+psycopg://user:pass@host/db` rồi cài thêm driver `psycopg[binary]`.

## BOM / Định mức nguyên vật liệu

BOM gắn theo **recipe version** (có `base_qty` = quy mô mẻ chuẩn + các dòng `{material_code, qty, uom, tol_pct}`).
- **Nhập/sửa**: tab Công thức → "+ Tạo version (BOM)" mở editor dòng BOM (chọn vật tư từ danh mục, ĐVT tự điền, dung sai ±%); chỉ `recipe.author` sửa được, chỉ ở trạng thái `draft`.
- **Hiển thị**: nút "Xem BOM" cho từng version (BOM + tham số + QC).
- **Scale theo mẻ**: nhu cầu = định mức × (SL kế hoạch / `base_qty`); snapshot bất biến vào mẻ khi tạo.
- **Đối chiếu định mức ↔ thực tế** (`GET /api/batches/{id}/bom`): so định mức (đã scale) với thực tế tiêu thụ lấy từ genealogy consume, tính chênh lệch/% và trạng thái **đạt / vượt / thiếu / chưa dùng** theo dung sai — hiển thị bảng có màu trong chi tiết mẻ.

> Đã kiểm chứng: mẻ 25.000 L (hệ số 0.5×) → MALT 700/600 = **vượt 16.7%**, HOP 7/7.5 = **thiếu 6.7%**, YEAST 0/25 = **chưa dùng**.

### Kiểm soát theo BOM (đầy đủ)

1. **Kiểm tra tồn trước khi tạo mẻ** (tài liệu §7.1): `GET /api/batches/availability?recipe_version_id=&planned_qty=` trả nhu cầu BOM (đã scale) ↔ tồn khả dụng (`status=available`). Khi tạo mẻ, nếu thiếu tồn → **chặn (409)** trừ khi `allow_shortage`. UI có nút "Kiểm tra tồn" + xác nhận khi thiếu.
2. **Chặn consume vượt định mức**: ngưỡng = định mức(scale) × (1 + dung sai%); nếu (đã tiêu thụ + lần này) > ngưỡng → **chặn (409)** trừ khi `allow_over` (có phê duyệt). UI bắt lỗi → hỏi xác nhận → gửi lại `allow_over`.
3. **BC định mức NVL** (tab Báo cáo): `GET /api/reports/material-norm?days=` gộp định mức(scale) ↔ thực tế theo vật tư qua nhiều mẻ, có chênh lệch/% và trạng thái; kèm bảng theo mẻ. Quyền xem: giám đốc, quản đốc, trưởng ca, kỹ sư, admin.

> Logic BOM dùng chung ở `services/bom.py` (factor/availability/ceiling/compare/report). Đã kiểm chứng: tạo mẻ thiếu tồn→409 / `allow_shortage`→201; consume 1300>ngưỡng 1236→409 / `allow_over`→200.

**Đã review đối kháng (multi-agent) + vá:** đóng 2 lỗ hổng bảo mật (bypass quyền qua header; 2 endpoint BOM thiếu auth), chặn `planned_qty ≤ 0` (factor 0 vô hiệu hóa kiểm tra), gộp BOM trùng `material_code`, báo cáo dùng đúng dung sai từng vật tư + chỉ tính mẻ đã chạy + đếm mẻ theo `batch_id`. **Giới hạn còn lại (chủ ý cho MVP):** `availability` là kiểm tra tư vấn, chưa **giữ chỗ tồn** (có thể chênh nếu nhiều mẻ tạo đồng thời — TOCTOU); lô bán thành phẩm (`material_id` null) không bị ràng buộc định mức (đúng bản chất — không phải NVL gốc).

## Đăng nhập & tài khoản theo chức danh

Hệ thống có **màn hình đăng nhập thật** (token, mật khẩu băm pbkdf2 — stdlib, không thư viện ngoài).
Mỗi tài khoản gắn một **vai trò nghiệp vụ** (quyết định quyền/SoD ở backend) và **chức danh + menu riêng**.

| Tài khoản | Mật khẩu | Chức danh | Vai trò | Menu thấy được |
|---|---|---|---|---|
| `admin` | `admin123` | Quản trị hệ thống | admin | tất cả + **Tài khoản** |
| `giamdoc` | `123456` | Giám đốc nhà máy | supervisor | Tổng quan, AI, Truy xuất, Năng lượng, Tích hợp, Audit |
| `quandoc` | `123456` | Quản đốc phân xưởng | supervisor | Tổng quan, Lệnh SX, Mẻ, Nấu-Lọc-Chiết, Chất lượng, Truy xuất, AI, Audit |
| `truongca` | `123456` | Trưởng ca sản xuất | supervisor | Tổng quan, Lệnh SX, Mẻ, Nấu-Lọc-Chiết, AI |
| `vanhanh` | `123456` | Nhân viên vận hành | operator | Tổng quan, Mẻ, Nấu-Lọc-Chiết |
| `kcs` | `123456` | Nhân viên KCS / QA | qa | Tổng quan, Chất lượng, Nấu-Lọc-Chiết, Truy xuất, AI |
| `kysu` | `123456` | Kỹ sư công nghệ | engineer | Tổng quan, Công thức, Mẻ, Nấu-Lọc-Chiết, Truy xuất |
| `thukho` | `123456` | Thủ kho NVL | operator | Tổng quan, Kho NVL |
| `baotri` | `123456` | Nhân viên bảo trì | operator | Tổng quan, Bảo trì, Kiểm định |
| `nangluong` | `123456` | NV quản lý năng lượng | operator | Tổng quan, Năng lượng |

- Token lưu ở `localStorage`, gửi qua header **`Authorization: Bearer …`**; phiên 12 giờ.
- Backend `get_current_user` **yêu cầu token**; không có token → 403. Fallback `X-User`/`X-Role` (toàn quyền) **mặc định TẮT**, chỉ bật khi đặt `MES_DEV_HEADER_AUTH=1` (chỉ dùng cho dev/`/docs`) — tránh bypass quyền. *(Phát hiện & vá qua review đối kháng.)*
- Quyền nghiệp vụ vẫn theo 5 vai trò (vd: chỉ `qa` release, chỉ `engineer` tạo recipe version,
  SoD soạn≠duyệt) — đã kiểm chứng đăng nhập từng chức danh trả về đúng 403/200.
- Admin có trang **Tài khoản** (`/api/auth/users`): tạo tài khoản, gán chức danh/vai trò/menu/quyền, khoá/mở.
- **Hồ sơ cá nhân** (mọi tài khoản): đổi họ tên, **đổi mật khẩu** (`/api/auth/change-password`, `PUT /api/auth/me`).
- **Audit đăng nhập**: ghi `login` / `logout` / `login_failed` / `change_password` vào audit log (lọc `entity_type=auth`).

### Ma trận quyền chi tiết theo chức danh

Ngoài 5 vai trò, mỗi tài khoản có tập **quyền thao tác** (permission) áp ở tầng API (`require_perm`).
Catalog 14 quyền: `order.create`, `batch.create`, `batch.execute`, `recipe.author`, `recipe.approve`,
`quality.release`, `quality.deviation`, `warehouse.receive`, `warehouse.issue`, `maintenance.manage`,
`calibration.manage`, `energy.update`, `user.manage`, `integration.manage`.

| Chức danh | Quyền thao tác |
|---|---|
| Thủ kho | `warehouse.receive`, `warehouse.issue` |
| Trưởng ca | `order.create`, `batch.create`, `batch.execute` |
| Quản đốc | + `quality.deviation` |
| Vận hành | `batch.execute` |
| KCS/QA | `quality.release`, `quality.deviation`, `recipe.approve` |
| Kỹ sư CN | `recipe.author`, `recipe.approve`, `batch.create`, `batch.execute` |
| Bảo trì | `maintenance.manage`, `calibration.manage` |
| NV năng lượng | `energy.update` |
| Giám đốc | (chỉ xem) |
| Admin | toàn quyền |

> Đã kiểm chứng: thủ kho xuất kho ✓ / tạo lệnh ✗; trưởng ca tạo lệnh ✓ / xuất kho ✗; KCS release ✓ / tạo lệnh ✗;
> vận hành release ✗. Admin có UI chọn quyền (14 checkbox) khi tạo tài khoản và xem cột quyền của từng người.

## Xác thực & vai trò (MVP)

Danh tính truyền qua header **`X-User`** và **`X-Role`** (UI có ô chọn ở góc phải).
Vai trò: `operator`, `supervisor`, `qa`, `engineer`, `admin`.

Quy tắc **Segregation of Duties** được thực thi, ví dụ:
- Duyệt recipe (`approved`) phải **khác người soạn** version đó.
- Chỉ `qa` được **release** chất lượng; release bị chặn nếu còn kết quả **FAIL** chưa đóng deviation.
- Không **close** mẻ khi chưa release hoặc còn QC bắt buộc chưa pass.

> Production phải thay bằng IdP/SSO + MFA (tài liệu §10.2). Header chỉ để minh hoạ RBAC/SoD.

## Thử nhanh bằng API

```bash
# Truy ngược thành phẩm về nguyên liệu
curl "localhost:8077/api/trace/backward?code=PKG-2406-0001"
# Recall: lô malt ảnh hưởng những lô nào
curl "localhost:8077/api/trace/recall?code=MALT-2406-01"
# Đường cong lên men của mẻ (telemetry curated)
curl "localhost:8077/api/batches/<batch_id>/readings?parameter=gravity"
# OEE đóng gói (đã tính A/P/Q)
curl "localhost:8077/api/oee"
# Tạo recipe version với vai trò engineer
curl -X POST localhost:8077/api/recipes/<id>/versions -H "X-Role: engineer" \
     -H "Content-Type: application/json" -d '{"parameters":[],"quality_checks":[]}'
```

## Quy tắc nghiệp vụ cốt lõi đã thực thi

- **Recipe snapshot bất biến**: khi tạo mẻ, toàn bộ parameters/materials/QC của recipe
  version được copy vào mẻ → sửa recipe sau này không làm biến đổi hồ sơ mẻ đã chạy (§4.2).
- **State machine**: mẻ và recipe chỉ chuyển theo các transition hợp lệ (sai → HTTP 409).
- **Genealogy**: mọi consume/produce tạo cạnh có hướng, quantity, timestamp → truy xuất đồ thị.
- **QC tự động**: pass/fail tính theo limit số học; FAIL tự đưa scope về ON HOLD.
- **Audit append-only**: mọi thay đổi ghi ai/khi/hành động/trước-sau; không có API sửa/xóa.

## Lộ trình "MES hardcore" (13 phân hệ)

Danh sách lớn được chia giai đoạn, mỗi giai đoạn chạy được + verify. **✅ Hoàn thành 13/13.**

| # | Phân hệ | Trạng thái | Ghi chú |
|---|---|---|---|
| 1 | **Lệnh sản xuất & Điều độ** (work order, kế hoạch ngày/ca, dispatch, planned vs actual) | ✅ **Xong** | PO→WO→batch; tab Điều độ; quyền wo.manage/dispatch |
| 2 | **EBR — hồ sơ mẻ điện tử** step-by-step (ai/bước/lúc/thông số/thiết bị/NVL/deviation/duyệt) | ✅ **Xong** | Dossier từ audit+genealogy+QC+hóa chất+BOM; modal EBR; e-sign + hash + khóa hồ sơ |
| 3 | **Recipe/BOM nâng cao** (effective date chặt, change control, yield/hao hụt chuẩn, alt material) | ✅ **Xong** | + **Yield theo công đoạn** (`yield_calc.py`, cumulative/loss + cảnh báo), **nguyên liệu thay thế** (`/batches/availability-alt`), **change-control e-sign** (`/recipes/versions/{id}/change-approve` re-auth + diff + `RecipeChange`); tab **Công thức+** |
| 4 | **Tích hợp thiết bị** (OPC UA/MQTT/edge gateway, cân, lưu lượng kế, tank sensor) | ✅ **Xong** | **edge_sim** (tiến trình độc lập) đẩy telemetry qua API key; ranh giới cắm PLC thật rõ ràng |
| 5 | **Historian/time-series** (timestamped sensor, downsample) | ✅ **Xong** | `services/historian.py` (ingest/query/series/downsample), swap được TimescaleDB/Influx; tab Realtime auto-refresh |
| 6 | **Material consumption thật** (cấp phát theo lệnh, cân/dispense, backflush, hold/release NVL) | ✅ **Xong** | + **Dispense theo lô FEFO** (`dispense.py`, chặn lô hết hạn + vượt định mức), **backflush** theo định mức × sản lượng (không trừ trùng); tab **Cấp liệu** |
| 7 | **Quality hardcore** (sampling plan, spec theo SP/công đoạn, SPC chart, OOS/OOT, CAPA, COA, LIMS) | ✅ **Xong** | + **SPC control chart** (I-MR, UCL/LCL, **luật Western Electric**, Cp/Cpk — `quality_adv.py`), **CAPA** workflow, **COA** xuất phiếu, **LIMS-lite** sample; tab **QC Lab** |
| 8 | **OEE/downtime** (reason tree, changeover, micro-stop, MTBF/MTTR) | ✅ **Xong** | + **Cây lý do dừng máy** (`downtime.py` REASON_TREE), **Pareto** + % tích lũy, **6 big losses**, **MTBF/MTTR** theo thiết bị; tab **OEE/Dừng máy** |
| 9 | **Barcode/RFID/mobile/kiosk** (in tem, quét lô/vật tư/pallet, xác nhận nhanh) | ✅ **Xong** | `/kiosk.html` UI cảm ứng (đăng nhập, quét→tra cứu→cấp liệu nhanh, in tem **Code39**); `GET /api/scan` |
| 10 | **Phân quyền sâu** (theo phân xưởng/line/ca/loại kiểm nghiệm) | ✅ **Xong** | + **Data-scoping** theo line/khu vực/loại test (`require_scope`/`filter_by_scope` trong `security.py`): lọc work order & batch, chặn ghi QC ngoài phạm vi; UI gán phạm vi (Tài khoản) + hiển thị (Hồ sơ) |
| 11 | **E-signature & audit bất biến** (e-sign 2 lớp, reason-for-change, record locking, 21 CFR Part 11) | ✅ **Xong** | E-sign re-auth + ý nghĩa/lý do; **audit hash-chain tamper-evident** (`/api/audit/verify-chain` phát hiện giả mạo); khóa hồ sơ → mẻ bất biến |
| 12 | **Kiến trúc production** (PostgreSQL, Alembic migration, Docker, HTTPS, monitoring, CI, backup, job queue) | ✅ **Xong** | Dockerfile + docker-compose (app+Postgres); **Alembic migration** (40 bảng); pytest 8/8; /api/health (DB check); backup/restore; CI |

**✅ Đã xong toàn bộ 13/13 phân hệ.** Phase 1–5 + 5 phân hệ chiều sâu #3/#6/#7/#8/#10. Riêng #4 (tích hợp thiết bị) chạy ở dạng **mô phỏng edge** (`edge_sim`) với ranh giới cắm PLC/SCADA thật rõ ràng — phần còn lại cần phần cứng/giao thức tại hiện trường.

**Màn hình quản lý danh mục:** tab **Danh mục** cho phép **tạo/sửa Sản phẩm & Vật tư** (`POST/PUT /api/products`, `/api/materials` — yêu cầu quyền `master.manage` + audit + chặn trùng mã). Sản phẩm mới dùng được ngay khi tạo Công thức/Lệnh SX.

### Mobile/Kiosk + barcode (Phase 4)
- **`/kiosk.html`** — giao diện cảm ứng cho xưởng (tablet/scanner): đăng nhập, **Quét mã** (scanner gõ + Enter → `GET /api/scan` phân giải lô/mẻ/lệnh), **cấp liệu nhanh** vào mẻ đang chạy (nút SL lớn, chặn vượt định mức), **In tem** mã vạch **Code 39** (`barcode.js`, in trực tiếp), xem mẻ đang chạy. Link "📱 Kiosk" ở header bản đầy đủ.

### Hạ tầng production (Phase 5)
- **Docker**: `backend/Dockerfile` + `docker-compose.yml` (app FastAPI + **PostgreSQL 16**), healthcheck, volume bền. `docker compose up -d` → tự `alembic upgrade head` + seed + chạy.
- **Migration thật**: Alembic (`backend/alembic/`) — `alembic revision --autogenerate` + `upgrade head` (đã sinh migration đầu tạo **40 bảng**). App cũng `create_all` cho dev.
- **Test tự động**: `backend/tests/` pytest + FastAPI TestClient (**22/22 pass**: smoke + 5 phân hệ chiều sâu + hardening). **CI** GitHub Actions (`.github/workflows/ci.yml`: ruff lint + pytest + docker build).
- **Vận hành**: `/api/health` kiểm tra kết nối DB + dialect + version; `scripts/backup.sh` / `restore.sh` (pg_dump 3-2-1); `.env.example`; HTTPS qua reverse proxy (mẫu nginx trong compose, comment sẵn); cấu hình qua biến môi trường; `MES_DEV_HEADER_AUTH=0` ở production.

> **Cách chạy production:** `cp .env.example .env` → chỉnh `POSTGRES_PASSWORD` → `docker compose up -d` → https qua proxy. **Dev:** như mục "Chạy" (SQLite). **Test:** `cd backend && pip install -r requirements-dev.txt && pytest -q`.

### Vận hành & Bảo mật — hardening P0/P1
- **Rate-limit + quota AI** (`ratelimit.py`, middleware in-proc sliding-window): `/api/auth/login` chống brute-force (mặc định 10/phút/IP); `/api/ai/*` giới hạn 20/phút/phiên + **hạn mức chat AI/ngày** (mặc định 300) — chặn lạm dụng vì AI gọi **Claude thật = chi phí**. `/api/ai/chat|insights|tools` nay **bắt buộc đăng nhập**.
- **Seed an toàn production**: `MES_SEED_DEMO=0` → **chỉ tạo admin**, không seed tài khoản/API key/dữ liệu demo. Admin lấy mật khẩu từ `MES_ADMIN_PASSWORD`; nếu dùng mặc định `admin123` thì **buộc đổi mật khẩu lần đầu** (`must_change_password`). docker-compose đặt `MES_SEED_DEMO=0` sẵn.
- **Audit chống race + bất biến**: `record_audit` tuần tự hoá bằng `pg_advisory_xact_lock` (Postgres) + khoá tiến trình; cột `seq` **UNIQUE** (fail-loud). `POST /api/v1/events` ghi **qua `record_audit`** nên không còn làm gãy chuỗi hash (đã kiểm chứng: chèn external event → verify-chain vẫn intact).
- **Cấu hình tập trung** `pydantic-settings` (`config.Settings`) — validate kiểu, gom mọi biến `MES_*` + `ANTHROPIC_API_KEY`.
- **Structured logging + request-id** (`logging_config.py`): mỗi request có `X-Request-ID`, log JSON tuỳ chọn (`MES_LOG_JSON=1`); **log chi phí AI** (model/token/USD ước tính/latency) mỗi lượt gọi LLM; bỏ pattern nuốt exception (health, fallback LLM đều log có ngữ cảnh).
- **Test + CI**: **22/22 pass** (smoke 8 + depth/hardening 14: SPC, downtime/MTBF, dispense, scope, audit-chain-qua-event, rate-limit, auth-gap…); CI chạy **ruff lint + pytest + docker build**.
- **Kiến trúc**: gỡ phụ thuộc ngược service→router (`services/derived.py`); dùng FastAPI `lifespan`; validate payload gateway bằng Pydantic.

> **Còn lại (P2 — khi quy mô/đồng thời tăng, đặc biệt nếu làm AI agent):** chat AI **async + streaming SSE** + worker/queue; lưu **ConversationMemory** (bảng `ai_conversation/ai_message` qua Alembic) thay vì chỉ giữ ở client; **monitoring** `/metrics` + cảnh báo lỗi LLM/timeout + kiểm thử restore backup định kỳ; **module hoá `frontend/app.js`** khi UI phình thêm. Rate-limit hiện in-process — nhiều worker/replica nên chuyển sang Redis (token bucket), interface `check_rate_limit()` giữ nguyên.

### Edge + Historian real-time (Phase 3)
- **Historian** (`services/historian.py`): time-series theo tag UNS (`brewery/site01/<area>/<device>/<metric>`); `POST /api/historian/ingest` (xác thực **X-API-Key** scope write), `GET /api/historian/{tags,latest,series}` (downsample min/avg/max cho biểu đồ). SQLite cho demo — interface swap được TimescaleDB/Influx.
- **Edge connector** `python -m app.edge_sim`: tiến trình **độc lập** mô phỏng gateway OPC UA/MQTT, đẩy 8 tag (nhiệt độ/áp suất/°P/DO/flow/hơi/điện) mỗi vài giây qua API key `mes_edge_writer_key_0001`. Thay phần sinh giá trị bằng client OPC UA/MQTT thật là chạy production.
- **UI tab 📡 Realtime**: thẻ giá trị tức thời + biểu đồ xu hướng 6h, **tự cập nhật mỗi 4s**; nút "Mô phỏng 1 nhịp" để demo không cần edge_sim.

> Đã kiểm chứng: backfill 8 tag; ingest no-key/read-key→403, edge write→200; edge_sim đẩy liên tục; tab Realtime cập nhật trực tiếp (65.559→65.86 sau tick); timer auto-refresh dọn khi rời tab.

### EBR + e-signature + audit bất biến (Phase 2)
- **EBR** (`GET /api/batches/{id}/ebr`): lắp ráp dossier step-by-step — header (lệnh/WO/recipe/SL), **timeline thao tác** (từ audit: ai/bước/lúc/lý do/chi tiết), BOM định mức↔thực tế, kết quả QC, deviation, hóa chất, genealogy, chữ ký, hash toàn vẹn. UI: nút "📄 Hồ sơ mẻ (EBR)" trong chi tiết mẻ → modal.
- **E-signature** (`POST .../ebr/sign`): yêu cầu **nhập lại mật khẩu** (re-auth, 21 CFR Part 11), lưu ý nghĩa + lý do + hash nội dung tại thời điểm ký; quyền `ebr.sign`.
- **Khóa hồ sơ** (`POST .../ebr/lock`, quyền `ebr.approve`): tạo **snapshot bất biến** có content_hash; sau khóa **mẻ không cho sửa** (transition/consume/produce/actual → 409, chỉ amendment).
- **Audit bất biến**: mỗi bản ghi có `entry_hash = sha256(prev_hash + nội dung)` → **chuỗi tamper-evident**. `GET /api/audit/verify-chain` phát hiện nếu có bản ghi bị sửa (đã kiểm chứng: sửa trực tiếp DB → báo gãy đúng vị trí).

> Nhiều mục cần hạ tầng thật (PLC/SCADA, TimescaleDB, K8s) — trong môi trường này tôi dựng **bản mô phỏng + điểm tích hợp chuẩn** để cắm thiết bị/DB thật sau, đúng tinh thần tài liệu (§9 edge, §11 hạ tầng).

## Giới hạn & lộ trình mở rộng

MVP này tương ứng **GĐ 1 (MVP pilot)** trong §14. Chưa bao gồm (các giai đoạn sau):

- **GĐ 2** — Kết nối OT thật: OPC UA / MQTT-Sparkplug, edge connector, store-and-forward, CIP tự động.
- **GĐ 3** — Tích hợp doanh nghiệp: ERP/WMS/LIMS/CMMS (hiện đang nhận order thủ công), packaging, OEE, EBR/DR.
- **Hạ tầng**: hiện chạy đơn-instance + SQLite. Production cần PostgreSQL HA, backup bất biến,
  OT DMZ, observability (§10–§12).
- **IdP/SSO + MFA**, chữ ký điện tử có re-authentication, mã hóa, secret vault (§10.2–§10.3).
- Migration (Alembic) thay cho `create_all`.

Các điểm này là **chủ ý** — tài liệu nhấn mạnh triển khai tăng dần và không đưa OT/AI
lên critical path quá sớm.
