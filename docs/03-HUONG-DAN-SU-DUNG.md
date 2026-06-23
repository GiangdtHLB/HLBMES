# Sách Hướng dẫn Sử dụng — MES Bia Hạ Long (Nhà Máy Đông Mai)

> Hướng dẫn chi tiết cho **tất cả tài khoản/chức danh**. Đọc Phần A (chung) trước, rồi tìm
> phần dành cho chức danh của bạn ở Phần C. Phần D mô tả quy trình end-to-end xuyên vai trò.

**Truy cập:** mở trình duyệt → `http://localhost:8077/` (bản đầy đủ) hoặc `http://localhost:8077/kiosk.html` (kiosk xưởng).
**Tài liệu API kỹ thuật:** `http://localhost:8077/docs`.

---

# PHẦN A — KIẾN THỨC CHUNG

## A.1. Đăng nhập

1. Mở `http://localhost:8077/`. Màn hình hiện hộp **🍺 MES Bia Hạ Long**.
2. Nhập **Tên đăng nhập** và **Mật khẩu** → bấm **Đăng nhập** (hoặc nhấn Enter ở ô mật khẩu).
3. Nếu sai, dòng đỏ báo lỗi. Đăng nhập sai nhiều lần liên tiếp sẽ bị **giới hạn tần suất** (10 lần/phút/IP) — chờ 1 phút.
4. Đăng nhập thành công: hệ thống ghi nhớ phiên (token lưu trong trình duyệt), **tự đăng nhập lại** trong **12 giờ**. Mở lại tab không cần nhập lại.

> **Lần đầu với tài khoản `admin`:** nếu admin dùng mật khẩu mặc định, hệ thống **buộc đổi mật khẩu** ngay — bạn sẽ được đưa tới tab **Hồ sơ** để đặt mật khẩu mới trước khi làm việc.

## A.2. Tài khoản demo (sau khi seed dữ liệu mẫu)

| Tài khoản | Mật khẩu | Chức danh | Vai trò |
|---|---|---|---|
| `admin` | `admin123` | Quản trị hệ thống | admin |
| `giamdoc` | `123456` | Giám đốc nhà máy | supervisor |
| `quandoc` | `123456` | Quản đốc phân xưởng | supervisor |
| `truongca` | `123456` | Trưởng ca sản xuất | supervisor |
| `vanhanh` | `123456` | Nhân viên vận hành | operator |
| `kcs` | `123456` | Nhân viên KCS / QA | qa |
| `kysu` | `123456` | Kỹ sư công nghệ | engineer |
| `thukho` | `123456` | Thủ kho NVL | operator |
| `baotri` | `123456` | Nhân viên bảo trì | operator |
| `nangluong` | `123456` | NV quản lý năng lượng | operator |

> Đây là tài khoản **demo** — môi trường thật chỉ tạo `admin` và admin tự tạo các tài khoản khác (Phần G).

## A.3. Giao diện chung

- **Thanh menu trên cùng**: các tab chức năng. **Bạn chỉ thấy những tab được phân quyền** cho chức danh của mình (xem Phần C). Tab **Hồ sơ** luôn hiện.
- **Góc phải header**: tên bạn + chức danh, nút đăng xuất, link **📱 Kiosk**.
- **Subnav** (thanh phụ): nhiều tab có các mục con (vd Kho NVL có Tồn / Thẻ kho / Hạn dùng / BC / Nhập-Xuất).
- **Ô tìm kiếm** trên các bảng lớn: gõ để lọc nhanh dòng.
- **Modal**: cửa sổ bật lên cho thao tác tạo/sửa/xem chi tiết (vd Xem BOM, Hồ sơ EBR, tem mã vạch).
- **Toast**: thông báo nhỏ góc màn hình — màu xanh = thành công, đỏ = lỗi.
- **Màu trạng thái** (Nấu-Lọc-Chiết): đỏ=thiếu thông tin, xanh lá=chưa nhập NVL, xanh dương=đầy đủ, xanh nhạt=lọc vào BBT phối.

## A.4. Đổi mật khẩu & hồ sơ cá nhân (mọi tài khoản)

Vào tab **Hồ sơ**:
- **Bên trái**: thông tin cá nhân — bạn có thể sửa **Họ tên** rồi bấm **Lưu**. Xem được vai trò, quyền được cấp, phạm vi (line/khu vực/loại test).
- **Bên phải**: form **Đổi mật khẩu** — nhập mật khẩu hiện tại, mật khẩu mới (≥6 ký tự), nhập lại → **Đổi mật khẩu**.

## A.5. Hiểu về phân quyền (vì sao tôi không bấm được nút nào đó?)

Hệ thống kiểm soát 3 lớp:
1. **Menu** — chức danh quyết định tab nào hiện.
2. **Quyền thao tác** — nút "ghi/tạo/duyệt" chỉ hoạt động nếu bạn có quyền tương ứng; nếu không, hệ thống trả lỗi **403** (toast đỏ "không đủ quyền").
3. **Phạm vi dữ liệu (scope)** — bạn chỉ thao tác được trên dây chuyền/khu vực/loại test được phân. Vd trưởng ca chỉ thấy/sửa mẻ của **Nấu A**.
4. **Phân tách nhiệm vụ (SoD)** — bạn **không được tự duyệt việc mình làm**: người soạn công thức ≠ người duyệt; người ghi QC ≠ người release; người ký EBR ≠ người khóa.

---

# PHẦN B — BẢN ĐỒ NHANH 28 TAB

| Tab | Dùng để | Ai thường dùng |
|---|---|---|
| **Tổng quan** | Dashboard KPI: lệnh, mẻ chạy, HOLD, deviation, cảnh báo, OEE, biểu đồ | tất cả |
| **Lệnh SX** | Tạo & xem lệnh sản xuất từ ERP | trưởng ca, quản đốc |
| **Điều độ** | Lập Work Order, phát mẻ (dispatch) | trưởng ca, quản đốc |
| **Lập lịch** | Gantt + tự lập lịch tank/CIP/bảo trì | quản đốc, kỹ sư, giám đốc |
| **Công thức** | Tạo công thức, BOM, version, duyệt/ban hành | kỹ sư |
| **Công thức+** | Yield công đoạn, change-control, NVL thay thế | kỹ sư, quản đốc |
| **Mẻ sản xuất** | Tạo/chạy mẻ, consume, produce, actual, EBR | vận hành, trưởng ca, quản đốc |
| **ISA-88** | Chạy phase theo thủ tục (nấu/lên men/lọc/CIP) | vận hành, trưởng ca |
| **Cấp liệu** | Cấp NVL cho mẻ / backflush | vận hành, thủ kho, trưởng ca |
| **Chất lượng** | Ghi QC, hold/release, deviation | KCS, quản đốc |
| **QC Lab** | SPC, CAPA, COA, LIMS | KCS, kỹ sư |
| **Nấu-Lọc-Chiết** | Nhập liệu công đoạn chi tiết + cảnh báo + men + hóa chất | vận hành, KCS, quản đốc |
| **Truy xuất** | Truy ngược/xuôi + recall | KCS, quản đốc, kỹ sư, giám đốc |
| **Kho NVL** | Nhập/xuất/hoàn/sang ngang, tồn, thẻ kho, hạn dùng | thủ kho |
| **Kho TP (WMS)** | Đóng pallet, vị trí, cất/xuất, in tem | thủ kho, quản đốc |
| **Bao bì** | Bao bì tuần hoàn (vỏ chai/két/keg) | thủ kho |
| **Năng lượng** | Cập nhật & xem điện/nước/hơi | NV năng lượng |
| **Realtime** | Telemetry sensor + xu hướng 6h | vận hành, trưởng ca |
| **OEE/Dừng máy** | OEE, sự kiện dừng, Pareto, MTBF | quản đốc, bảo trì, giám đốc |
| **Bảo trì** | Sự cố, kế hoạch, thiết bị, phụ tùng | bảo trì |
| **Kiểm định** | Hiệu chuẩn/kiểm định + hạn | bảo trì |
| **Báo cáo** | BC định mức NVL | quản đốc, kỹ sư, giám đốc |
| **Trợ lý AI** | Chat AI + cảnh báo vận hành | tất cả được cấp |
| **Tích hợp** | API mở, AI tool, API key, webhook | admin, giám đốc |
| **Danh mục** | Sản phẩm/vật tư/dây chuyền | kỹ sư, quản đốc |
| **Tài khoản** | Quản lý người dùng | admin |
| **Audit** | Nhật ký bất biến | admin, quản đốc, giám đốc |
| **Hồ sơ** | Thông tin cá nhân + đổi mật khẩu | tất cả |

---

# PHẦN C — HƯỚNG DẪN THEO TỪNG CHỨC DANH

Mỗi mục dưới đây liệt kê **menu thấy được**, **quyền có**, **phạm vi dữ liệu**, và **các thao tác chính từng bước**.

---

## C.1. `admin` — Quản trị hệ thống

**Menu:** tất cả + **Tài khoản**. **Quyền:** toàn quyền. **Phạm vi:** toàn nhà máy.

**Việc chính:**

### Tạo tài khoản mới
1. Vào tab **Tài khoản** → panel **Tạo tài khoản**.
2. Nhập: Đăng nhập, Mật khẩu, Họ tên, Chức danh, **Vai trò** (admin/supervisor/qa/engineer/operator).
3. **Menu được phép**: nhập danh sách view, ngăn cách bằng dấu phẩy (vd `dashboard,batches,dispense`) hoặc `*` (tất cả).
4. **Phạm vi dữ liệu**: Line (vd `Nấu A` hoặc `*`), Khu vực (`nau,len_men,...` hoặc `*`), Loại test QC (vd `Độ đường (°P),pH` hoặc `*`).
5. **Quyền thao tác**: tích các ô quyền cần cấp (14+ quyền).
6. Bấm **Tạo tài khoản**. Người mới đăng nhập được ngay.

### Sửa phạm vi / khóa tài khoản
- Trong bảng danh sách, bấm **Phạm vi** để mở modal gán lại line/khu vực/loại test.
- Bấm **Khóa**/**Mở** để vô hiệu/kích hoạt (không khóa được chính mình).

### Quản trị tích hợp (tab **Tích hợp**)
- **Tạo API key**: nhập tên hệ thống + chọn scope (`read` hoặc `read,write`) → **Tạo key**. Token hiện **một lần** — sao chép ngay. Khóa key bằng nút **Khóa**.
- **Webhook**: nhập URL nhận sự kiện → **Đăng ký**.

### Giám sát toàn vẹn
- Tab **Audit**: xem nhật ký; lọc theo entity_id.
- Mở `http://localhost:8077/api/audit/verify-chain` để kiểm tra chuỗi hash còn nguyên vẹn.

> Admin nên đổi mật khẩu mặc định ngay lần đầu (hệ thống sẽ buộc), và đặt `MES_ADMIN_PASSWORD` ở môi trường thật.

---

## C.2. `giamdoc` — Giám đốc nhà máy

**Menu:** Tổng quan, Điều độ, Lập lịch, OEE, QC Lab, Realtime, Trợ lý AI, Truy xuất, Năng lượng, Kho TP (WMS), Bao bì, Báo cáo, Tích hợp, Audit.
**Quyền:** *chỉ xem* (không có quyền ghi). **Phạm vi:** toàn nhà máy.

**Việc chính (giám sát, không thao tác sản xuất):**
1. **Tổng quan**: theo dõi KPI — số lệnh, WO chạy/chờ, mẻ chạy, số mẻ HOLD, deviation mở, cảnh báo cao; gauge OEE từng dây chuyền; biểu đồ năng lượng, sản lượng, định mức↔thực tế.
2. **OEE/Dừng máy**: xem hiệu suất thiết bị, Pareto dừng máy, MTBF/MTTR.
3. **Báo cáo**: BC định mức NVL theo kỳ (30/90/365 ngày) — đánh giá hao hụt.
4. **Truy xuất**: tra cứu nguồn gốc lô khi cần (recall).
5. **Trợ lý AI**: hỏi đáp tình hình nhà máy + xem **AI insights** (cảnh báo & đề xuất ưu tiên), tạo **Báo cáo nền**.
6. **Audit**: kiểm tra nhật ký hoạt động.

> Khi bấm các nút ghi/tạo (nếu có), hệ thống sẽ báo "không đủ quyền" — đúng thiết kế cho vai trò chỉ-xem.

---

## C.3. `quandoc` — Quản đốc phân xưởng

**Menu:** Tổng quan, Danh mục, Lệnh SX, Điều độ, Lập lịch, Mẻ, ISA-88, Cấp liệu, Công thức+, Nấu-Lọc-Chiết, Realtime, Chất lượng, QC Lab, OEE, Truy xuất, WMS, Bao bì, Báo cáo, Trợ lý AI, Audit.
**Quyền:** `master.manage`, `order.create`, `wo.manage`, `wo.dispatch`, `batch.create`, `batch.execute`, `quality.deviation`, `ebr.sign`, `ebr.approve`. **Phạm vi:** toàn nhà máy.

**Việc chính (điều hành xưởng, phê duyệt):**

### Lập kế hoạch & điều độ
1. **Lệnh SX** → tạo lệnh từ ERP (mã, sản phẩm, SL, ưu tiên) → **Tạo lệnh**.
2. **Điều độ** → chọn lệnh ERP, recipe version (auto theo sản phẩm), SL, dây chuyền, ca, ngày → **Tạo lệnh (WO)**. Sau đó dùng nút **Phát hành** → **Phát mẻ** → **Hoàn thành** → **Chốt** theo tiến độ.
3. **Lập lịch** → **Tự lập lịch tối ưu** để xếp tank/line/CIP và phát hiện xung đột.

### Giám sát & phê duyệt
4. **Mẻ sản xuất** → theo dõi tiến độ; mở **Hồ sơ mẻ (EBR)** → **Phê duyệt & khóa** mẻ đã hoàn tất (cần nhập lại mật khẩu; bạn **không khóa được** mẻ mình tự ký — SoD).
5. **Chất lượng** → mở/đóng **deviation** khi có lệch chuẩn.
6. **OEE / Truy xuất / Báo cáo** → giám sát hiệu suất, truy xuất, hao hụt NVL.

> Quản đốc có thể tạo và chạy mẻ như trưởng ca, nhưng vai trò chính là điều phối + phê duyệt EBR.

---

## C.4. `truongca` — Trưởng ca sản xuất

**Menu:** Tổng quan, Lệnh SX, Điều độ, Lập lịch, Mẻ, ISA-88, Cấp liệu, Nấu-Lọc-Chiết, Realtime, OEE, Báo cáo, Trợ lý AI.
**Quyền:** `order.create`, `wo.dispatch`, `batch.create`, `batch.execute`, `ebr.sign`. **Phạm vi:** Line **Nấu A**; khu vực **nau, len_men, chiet**.

**Việc chính (điều hành ca):**

### Tạo & chạy mẻ
1. **Mẻ sản xuất** → panel **Tạo mẻ**: chọn lệnh SX (auto-fill recipe version), nhập SL kế hoạch → bấm **Kiểm tra tồn** (xem NVL đủ/thiếu) → **Tạo mẻ**.
   - Nếu thiếu tồn, hệ thống cảnh báo; xác nhận để tạo (cho phép thiếu) nếu cần.
2. Chọn mẻ trong danh sách → panel chi tiết bên phải:
   - Chuyển trạng thái: **→ ready** → **→ running** (nút theo trạng thái hiện tại).
   - **Consume lô**: chọn lô khả dụng + SL → **Consume** (nếu vượt định mức → xác nhận `cho vượt`).
   - **Ghi actual**: nhập tham số quy trình thực tế.
   - **Produce lô**: tạo lô bán thành phẩm/thành phẩm.
3. Khi xong: **→ completed**. (Đóng `closed` thường do quản đốc sau khi QA release.)
4. **ISA-88**: chạy từng phase (Bắt đầu → Hoàn thành/Giữ → Tiếp).
5. **Ký EBR**: mở **Hồ sơ mẻ (EBR)** → **Ký điện tử** (nhập lại mật khẩu + ý nghĩa/lý do).

> Bạn chỉ thấy & thao tác mẻ thuộc **Nấu A**. Mẻ line khác sẽ không hiện.

---

## C.5. `vanhanh` — Nhân viên vận hành

**Menu:** Tổng quan, Mẻ, ISA-88, Cấp liệu, Nấu-Lọc-Chiết, Realtime.
**Quyền:** `batch.execute`, `ebr.sign`. **Phạm vi:** Line **Nấu A**; khu vực **nau, len_men**.

**Việc chính (thao tác sàn):**
1. **Mẻ sản xuất** → chọn mẻ đang chạy → thực hiện:
   - Chuyển trạng thái (running/held/completed) theo lệnh ca.
   - **Consume** lô NVL theo định mức.
   - **Ghi actual** tham số (nhiệt độ, thời gian...).
   - **Produce** lô output.
2. **ISA-88** → chạy phase: bấm **Bắt đầu** (idle), **Hoàn thành**/**Giữ** (running), **Tiếp** (held).
3. **Cấp liệu** → cấp NVL cho mẻ hoặc backflush (xem C.10).
4. **Nấu-Lọc-Chiết** → nhập số liệu công đoạn (nấu, lên men...).
5. **Realtime** → theo dõi nhiệt độ tank, áp suất sensor (auto cập nhật 4s).
6. **Ký EBR** nếu được yêu cầu.

> Không tạo được mẻ mới (không có `batch.create`), không release QC, không duyệt.
> **Khuyến nghị:** dùng giao diện **Kiosk** (Phần E) cho thao tác nhanh tại xưởng.

---

## C.6. `kcs` — Nhân viên KCS / QA

**Menu:** Tổng quan, Chất lượng, QC Lab, Nấu-Lọc-Chiết, Truy xuất, Trợ lý AI.
**Quyền:** `quality.release`, `quality.deviation`, `recipe.approve`, `ebr.sign`, `ebr.approve`. **Phạm vi loại test:** chỉ **Độ đường (°P), pH** (không ghi parameter khác).

**Việc chính (kiểm soát chất lượng):**

### Ghi kết quả & release
1. **Chất lượng** → panel trái **Ghi KQ QC**: nhập Phạm vi (`batch:<id>` hoặc `lot:<id>`), Tham số, Giá trị, Lower, Upper → **Ghi KQ**.
   - Hệ thống tự tính **PASS/FAIL** theo giới hạn số học. **FAIL → tự động HOLD** scope đó.
   - *Lưu ý scope:* bạn chỉ ghi được parameter `Độ đường (°P)` và `pH`.
2. Panel phải **Hold/Release**: nhập phạm vi → **RELEASE** (chỉ KCS/QA mới release được).
   - Release **bị chặn** nếu còn FAIL chưa đóng deviation.
3. **Deviation**: mở khi có lệch chuẩn (mức minor/major/critical + lý do); chuyển trạng thái `open→triage→…→closed`.

### QC Lab (nâng cao)
4. **SPC**: chọn chỉ tiêu → xem control chart (UCL/LCL, Cp/Cpk, điểm vi phạm Western Electric đỏ).
5. **CAPA**: mở hành động khắc phục/phòng ngừa; điền nguyên nhân gốc, kế hoạch, verification.
6. **COA**: chọn mẻ → **Xuất COA** (phiếu phân tích + kết luận PASS/FAIL).
7. **LIMS**: đăng ký mẫu → **Bắt đầu test** → **Hoàn thành**.

### Khác
8. **Duyệt công thức**: bạn có `recipe.approve` (nhưng **không duyệt công thức do chính mình soạn** — SoD).
9. **Ký + khóa EBR**: hỗ trợ phê duyệt hồ sơ mẻ.

---

## C.7. `kysu` — Kỹ sư công nghệ

**Menu:** Tổng quan, Danh mục, Công thức, Công thức+, Mẻ, ISA-88, QC Lab, Nấu-Lọc-Chiết, Realtime, OEE, Truy xuất, Báo cáo, Lập lịch.
**Quyền:** `master.manage`, `recipe.author`, `recipe.approve`, `batch.create`, `batch.execute`, `ebr.sign`. **Phạm vi:** toàn nhà máy.

**Việc chính (thiết kế công thức & quy trình):**

### Tạo công thức + BOM
1. **Danh mục** → tạo Sản phẩm/Vật tư nếu chưa có.
2. **Công thức** → tạo công thức (mã, tên, sản phẩm) → **Tạo**.
3. Bấm **+ Tạo version (BOM)** → editor:
   - Đặt **quy mô mẻ chuẩn** (base_qty).
   - Thêm dòng BOM: chọn vật tư (ĐVT auto), nhập định mức, dung sai ±%.
   - Thêm **tham số quy trình** (tên, mục tiêu, giới hạn) và **chỉ tiêu QC** (bắt buộc/tùy chọn).
   - Khai báo **thủ tục ISA-88** (procedure) và **yield kỳ vọng** theo công đoạn nếu cần.
4. Chuyển trạng thái: **→ review** → **→ duyệt** (approved) → **→ hiệu lực** (effective).
   - **SoD:** bạn **không tự duyệt** version mình soạn — nhờ kỹ sư/QA khác duyệt.
   - Chỉ version **effective** mới dùng chạy mẻ được.

### Quản lý thay đổi (Công thức+)
5. **Yield**: chọn mẻ → so sánh kỳ vọng % vs thực tế % từng công đoạn; ghi yield.
6. **Change-control**: xem **diff** giữa các version; ký duyệt thay đổi (nhập mật khẩu + lý do).
7. **Kiểm tra tồn & NVL thay thế**: nhập công thức + SL → xem nhu cầu, tồn, gợi ý vật tư thay thế.

> Kỹ sư cũng tạo/chạy mẻ được để thử nghiệm.

---

## C.8. `thukho` — Thủ kho NVL

**Menu:** Tổng quan, Kho NVL, Kho TP (WMS), Bao bì, Cấp liệu.
**Quyền:** `warehouse.receive`, `warehouse.issue`. **Phạm vi:** khu vực **kho**.

**Việc chính (quản lý kho):**

### Nhập / xuất / hoàn / sang ngang (tab Kho NVL → mục Nhập/Xuất)
1. **Nhập kho**: nhập mã lô, vật tư, SL, ĐVT, hạn dùng → **Nhập**.
2. **Xuất kho**: chọn lô + SL → **Xuất**. **Nhập hoàn**: **Nhập hoàn**. **Sang ngang**: nhập vị trí đích → **Sang ngang**.
3. **Tồn kho**: xem tồn on-hand theo vật tư.
4. **Thẻ kho**: chọn vật tư → xem dòng nhập/xuất + **số dư lũy kế**.
5. **Hạn sử dụng**: theo dõi lô sắp/đã hết hạn (số ngày còn lại).
6. **BC nhập-xuất-tồn**: tổng hợp theo vật tư.

### Kho thành phẩm (WMS)
7. **Đóng pallet**: chọn sản phẩm, lô TP, số case, lon/case → **+ Đóng pallet** (tự sinh case + barcode Code39).
8. **Cất/Xuất pallet**: chọn vị trí → **Cất** (putaway) hoặc **Xuất** (ship). Bấm **🖨️ Tem** để in mã.

### Bao bì tuần hoàn
9. **Ghi biến động**: chọn loại bao bì + loại biến động (nhập/xuất/thu hồi/loại bỏ/kiểm kê) + SL → **Ghi**.

---

## C.9. `baotri` — Nhân viên bảo trì

**Menu:** Tổng quan, Bảo trì, Kiểm định, OEE.
**Quyền:** `maintenance.manage`, `calibration.manage`. **Phạm vi:** khu vực **loc, chiet**.

**Việc chính (CMMS):**

### Sự cố & kế hoạch (tab Bảo trì)
1. **Sự cố**: chọn thiết bị + tiêu đề + mức (minor/major/critical) → **Thêm sự cố**. Khi xong: **Xử lý xong** (nhập số phút dừng).
2. **Kế hoạch**: chọn thiết bị + loại (Bảo trì/Kiểm tra/Tu bổ) + ngày → **Thêm**. Hệ thống **tự đánh dấu quá hạn**. Khi làm xong: **Hoàn thành**.
3. **DM thiết bị**: thêm/sửa thiết bị.
4. **DM phụ tùng**: theo dõi tồn, cảnh báo **dưới tồn min**.

### Kiểm định (tab Kiểm định)
5. Thêm kiểm định: chọn loại (Hiệu chuẩn TBĐ / Van an toàn / Nguồn phóng xạ / TB YCNNVAT) + thiết bị + hạn → **Thêm**. Trạng thái tự cập nhật **valid/due/overdue** theo hạn.

### OEE
6. Xem **OEE/Dừng máy** để đối chiếu downtime do sự cố với MTBF/MTTR.

---

## C.10. `nangluong` — NV quản lý năng lượng

**Menu:** Tổng quan, Năng lượng. **Quyền:** `energy.update`. **Phạm vi:** khu vực **nau, len_men, chiet**.

**Việc chính:**
1. **Cập nhật số liệu**: chọn ngày + nhóm (điện/nước/hơi…) + khu vực (hoặc toàn nhà máy) + giá trị → **Lưu** (mỗi ngày/nhóm/khu chỉ 1 số đọc — ghi đè nếu nhập lại).
2. **Biểu đồ ngày**: xem xu hướng 30 ngày theo từng nhóm.
3. **Tổng hợp tháng**: bảng tổng theo tháng/nhóm.
4. **Danh mục**: thêm nhóm năng lượng (mã, tên, ĐVT) hoặc khu vực.

---

# PHẦN D — QUY TRÌNH NGHIỆP VỤ END-TO-END (xuyên vai trò)

## D.1. Từ lệnh ERP đến mẻ đóng kho

| Bước | Người làm | Tab | Thao tác |
|---|---|---|---|
| 1 | Quản đốc/Trưởng ca | Lệnh SX | Tạo lệnh sản xuất (PO) |
| 2 | Quản đốc/Trưởng ca | Điều độ | Tạo Work Order (line/ca/ngày) → **Phát hành** → **Phát mẻ** |
| 3 | Thủ kho | Kho NVL | Đảm bảo NVL đã nhập kho, còn hạn |
| 4 | Trưởng ca | Mẻ | **Kiểm tra tồn** → **Tạo mẻ** → **→ ready → running** |
| 5 | Vận hành/Thủ kho | Cấp liệu | Cấp NVL theo định mức (FEFO) |
| 6 | Vận hành | Mẻ / ISA-88 | Chạy phase, **ghi actual**, **consume** |
| 7 | KCS | Chất lượng / QC Lab | Ghi kết quả QC (PASS/FAIL); xử lý deviation nếu FAIL |
| 8 | Vận hành | Mẻ | **Produce** lô bright/package |
| 9 | KCS | Chất lượng | **RELEASE** (sau khi hết FAIL) |
| 10 | Vận hành | Mẻ | **→ completed** |
| 11 | Trưởng ca/Vận hành | Mẻ → EBR | **Ký điện tử** hồ sơ |
| 12 | Quản đốc | Mẻ → EBR | **Phê duyệt & khóa** (mẻ thành bất biến) → **→ closed** |
| 13 | Thủ kho | WMS | Đóng pallet thành phẩm, putaway, in tem |

## D.2. Cấp liệu (dispense / backflush)
- **Cấp liệu thủ công** (Cấp liệu): chọn mẻ → xem BOM → chọn vật tư + SL → **Cấp liệu**. Hệ thống xuất theo **FEFO** (lô hết hạn trước), **chặn lô hết hạn** và **chặn vượt định mức** (tích "cho vượt" + xác nhận nếu cần).
- **Backflush**: nhập sản lượng đã sản xuất → **Chạy backflush** → tự khấu trừ NVL = định mức × (SL / base_qty), không trừ trùng.

## D.3. Truy xuất & Recall (KCS/Quản đốc)
1. Tab **Truy xuất** → nhập mã lô/mẻ.
2. **Truy ngược ↑**: từ thành phẩm về nguyên liệu. **Truy xuôi ↓**: từ NVL ra các lô bị ảnh hưởng.
3. **Recall simulation**: liệt kê toàn bộ lô/mẻ bị ảnh hưởng + thời gian truy vấn.

## D.4. Xử lý mẻ bị HOLD do QC FAIL
1. KCS ghi QC → FAIL → mẻ tự **on_hold**.
2. KCS mở **deviation** (mô tả + mức) trong tab **Chất lượng**.
3. Điều tra → có thể mở **CAPA** (QC Lab).
4. Đóng deviation → KCS **RELEASE** → mẻ tiếp tục.

---

# PHẦN E — KIOSK XƯỞNG (`/kiosk.html`)

Giao diện cảm ứng cho tablet/máy quét tại sàn sản xuất.

1. **Đăng nhập** bằng tài khoản của bạn (vd `vanhanh`).
2. Màn hình chính có 4 ô lớn:
   - **📷 Quét mã**: focus ô quét → dùng máy quét bắn mã (hoặc gõ + Enter). Kết quả tự phân giải:
     - **Lô NVL** → hiện tồn/vị trí + nếu có mẻ đang chạy: chọn mẻ, bấm nút SL lớn (10/50/100/500) hoặc nhập tay → **cấp liệu nhanh** (chặn vượt định mức).
     - **Mẻ** → hiện trạng thái + tình trạng khóa EBR.
     - **Work Order / Đơn hàng** → hiện trạng thái, line/ca, SL.
   - **🏷️ In tem**: nhập mã → **Tạo tem** → **🖨️ IN TEM** (Code39).
   - **⚗️ Mẻ đang chạy**: xem nhanh danh sách mẻ đang chạy.
   - **💻 Bản đầy đủ**: quay lại UI chính.

---

# PHẦN F — TRỢ LÝ AI (tab Trợ lý AI)

**Bên trái — Chat:**
1. Chọn/ tạo hội thoại (lưu trên server, còn nguyên khi tải lại/đổi máy).
2. Gõ câu hỏi (vd "Mẻ nào đang HOLD?", "OEE line chiết hôm nay?") → **Gửi**. Câu trả lời hiện dần (streaming). Nếu AI dùng tool, sẽ hiện nhãn tool đã gọi.
3. Nút **Mới** (xóa khung chat), **Xoá** (xóa hội thoại).

**Bên phải — AI insights & cảnh báo:**
- 3 thẻ Cao/Trung bình/Thấp + bảng cảnh báo (miền, phát hiện, đề xuất).
- **📋 Báo cáo nền**: tạo tác vụ nền sinh báo cáo vận hành (poll tiến độ %).

> AI **chỉ tư vấn**, không tự thay đổi dữ liệu sản xuất. Nếu chưa cấu hình `ANTHROPIC_API_KEY`, trợ lý vẫn chạy bằng engine luật nội bộ (offline). Có giới hạn số lượt chat/ngày để kiểm soát chi phí.

---

# PHẦN G — DÀNH RIÊNG CHO QUẢN TRỊ (admin)

## G.1. Khởi tạo & seed dữ liệu
- **Dev (SQLite):** `python -m app.seed` rồi `uvicorn app.main:app --port 8077`. Seed tạo 10 tài khoản + dữ liệu mẫu (1 mẻ chạy end-to-end, kho, OEE, QC...).
- **Production (Docker + PostgreSQL):** `docker compose up -d`. Mặc định `MES_SEED_DEMO=0` → **chỉ tạo admin**; admin tạo các tài khoản thật.
- Đặt `MES_ADMIN_PASSWORD` để admin không dùng mật khẩu mặc định.

## G.2. Quản lý vòng đời tài khoản
- Tạo theo chức danh thực tế của nhà máy; gán **menu + quyền + phạm vi** tối thiểu cần thiết (least privilege).
- Khóa tài khoản nghỉ việc; định kỳ rà soát quyền trong bảng **Tài khoản**.

## G.3. Tích hợp hệ thống ngoài
- Cấp **API key read** cho BI/ERP chỉ đọc; **read,write** cho edge gateway.
- Kiểm tra số lượt gọi (call_count) và khóa key khi nghi ngờ.

## G.4. Giám sát & bảo trì hệ thống
- `GET /api/health` (DB ok?), `GET /metrics` (Prometheus), `GET /api/audit/verify-chain` (toàn vẹn).
- Sao lưu định kỳ: `scripts/backup.sh`; kiểm thử khôi phục: `scripts/test_restore.sh` (cron hàng tuần).

---

# PHẦN H — XỬ LÝ SỰ CỐ THƯỜNG GẶP (FAQ)

| Tình huống | Nguyên nhân | Cách xử lý |
|---|---|---|
| Không thấy tab nào đó | Chức danh không được cấp menu này | Đúng thiết kế; nhờ admin cấp thêm nếu cần |
| Bấm nút → "không đủ quyền" (403) | Thiếu quyền thao tác (permission) | Nhờ admin gán quyền tương ứng |
| Không thấy mẻ/đơn của line khác | Phạm vi dữ liệu (scope) giới hạn | Đúng thiết kế; admin mở rộng scope nếu cần |
| Không duyệt được công thức/khóa được EBR mình làm | Phân tách nhiệm vụ (SoD) | Nhờ người khác duyệt/khóa |
| Tạo mẻ báo "thiếu tồn" (409) | NVL không đủ theo BOM | Nhập kho thêm, hoặc xác nhận "cho phép thiếu" |
| Consume báo "vượt định mức" (409) | Vượt ngưỡng dung sai | Kiểm tra lại; nếu hợp lý, tích "cho vượt" + xác nhận |
| Release bị chặn | Còn kết quả QC FAIL chưa đóng deviation | Xử lý/đóng deviation rồi release |
| Đăng nhập bị chặn tạm thời | Vượt giới hạn tần suất (brute-force) | Chờ ~1 phút rồi thử lại |
| Mẻ không sửa được nữa | EBR đã khóa → mẻ bất biến | Chỉ tạo amendment; không sửa hồ sơ đã khóa |
| Trợ lý AI báo hết lượt | Vượt hạn mức chat/ngày | Chờ sang ngày hoặc tăng `MES_AI_DAILY_QUOTA` |

---

> **Tài liệu liên quan:** [Kiến trúc chuẩn](01-KIEN-TRUC-CHUAN.md) · [Danh sách tính năng](02-DANH-SACH-TINH-NANG.md) · API kỹ thuật tại `/docs`.
