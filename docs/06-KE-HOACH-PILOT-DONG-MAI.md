# Kế hoạch Pilot — Nhà máy Đông Mai

**Trả lời chỉ đạo của TGĐ (25/07/2026)** · Người trình: Phòng Sản xuất/CNTT · Ngày: 27/07/2026 (bản soạn lại)

---

## 0. Xác nhận phạm vi theo chỉ đạo

- **Chạy thử trước tại Nhà máy Đông Mai.** Chưa triển khai sang Hạ Long cho đến khi hoàn tất một chu kỳ pilot **và** có biên bản đánh giá đạt đủ 6 tiêu chí nghiệm thu (mục 6).
- Tài liệu này cung cấp đủ 5 hạng mục TGĐ yêu cầu: link hệ thống, tài khoản theo vai trò, phạm vi dữ liệu dùng thử, phương án sao lưu/khôi phục, kế hoạch pilot — kèm bộ tiêu chí nghiệm thu và đề xuất thứ tự backlog cho CIP/hiệu suất.
- **2 điểm còn lại cần anh/quản đốc xác nhận trước khi gửi chính thức** được đánh dấu ⚠️ và tổng hợp lại ở mục 8 — bản trước có 3 điểm, phần hạ tầng CSDL nay đã có xác nhận chính thức nên chỉ còn lại 2 (địa chỉ mạng thực tế, cách hiểu "không để phần mềm tự động thay đổi dữ liệu vận hành quan trọng").

---

## 1. Link hệ thống

| Mục | Giá trị |
|---|---|
| Địa chỉ truy cập (máy chủ đang chạy) | `http://localhost:8077` |
| Tài liệu API (Swagger) | `http://localhost:8077/docs` |
| Kiểm tra tình trạng máy chủ | `http://localhost:8077/api/health` |

⚠️ **Cần xác nhận:** đây là địa chỉ máy chủ dev hiện tại. Repo **không có** tài liệu ghi địa chỉ IP/tên miền nội bộ thật của nhà máy Đông Mai — đề nghị IT xác nhận địa chỉ LAN sẽ dùng để các ca sản xuất truy cập trong giờ pilot, trước khi gửi link cho người dùng thật.

**Khuyến nghị an toàn trước khi mở cho nhiều người dùng thật:**
- Bật HTTPS qua khối nginx reverse-proxy đã có sẵn trong `docker-compose.yml` (hiện đang tắt/comment) — tránh gửi mật khẩu qua HTTP thuần trong mạng nội bộ.
- Hạn chế/tắt quyền truy cập `/docs` (Swagger) trong môi trường pilot thật — hiện để hở sẽ lộ toàn bộ danh sách API cho bất kỳ ai có link.

---

## 2. Tài khoản theo từng vai trò

Danh sách tài khoản đã được **rà soát lại theo đúng sơ đồ tổ chức thật** của công ty (văn bản 01/2026/SĐTC-BHL) — bỏ các chức danh không có trong sơ đồ, thêm đúng các vị trí thật (Phó Quản đốc kiêm trực ca, Trưởng phòng KCS, Giám đốc Sản xuất-Kỹ thuật, Trung tâm Điều hành). Hệ thống có **10 tài khoản demo** (kể cả `admin`), ánh xạ vào **5 vai trò kiểm tra quyền** (operator/supervisor/qa/engineer/admin), mỗi tài khoản còn có phạm vi dữ liệu riêng (dây chuyền/khu vực/chỉ tiêu QC/kho) — phân quyền được chặn ở tầng server, không chỉ ẩn/hiện trên giao diện.

| Tài khoản | Chức danh | Vai trò | Quyền chính | Phạm vi dữ liệu |
|---|---|---|---|---|
| `admin` | Quản trị viên | admin | Toàn quyền | Toàn bộ |
| `quandoc` | Quản đốc phân xưởng | supervisor | Quản lý danh mục, lệnh SX, mẻ, deviation, ký/duyệt EBR, CIP | Toàn bộ |
| `phoquandoc` | Phó Quản đốc phân xưởng (trực ca) | supervisor | Thực hiện mẻ, ký/duyệt EBR, deviation, CIP | Toàn bộ |
| `vanhanh` | Nhân viên vận hành | operator | Thực hiện mẻ, ký EBR, đề nghị nhận kho, CIP | Dây chuyền "Nấu A" |
| `kcs` | Nhân viên KCS/QA | qa | Duyệt QC, deviation, duyệt công thức, ký/duyệt EBR | Chỉ tiêu QC: "Độ đường (°P), pH" |
| `kcs_truongphong` | Trưởng phòng KCS | qa | Như `kcs` + tạo lệnh SX (khóa chỉ tiêu, tạo Lệnh lọc) | Toàn bộ |
| `kysu` | Kỹ sư công nghệ (Phòng Kỹ thuật, Công nghệ & Cải tiến SX) | engineer | Quản lý danh mục, soạn/duyệt công thức, mẻ, EBR, CIP | Toàn bộ |
| `thukho` | Thủ kho NVL | operator | Nhận/xuất kho | Kho công ty |
| `giamdoc_sx` | Giám đốc Sản xuất - Kỹ thuật | supervisor | **Duyệt lô chiết nhập kho thành phẩm** (tách riêng khỏi quyền duyệt QC của KCS) | Toàn bộ |
| `ttdh_thukhotp` | NV Trung tâm Điều hành - Thủ kho TP | operator | Nhận/xuất kho thành phẩm (WMS) | Kho thành phẩm |

Mật khẩu demo hiện tại: `123456` (riêng `admin` là `admin123`).

**Điểm mới đáng chú ý cho pilot:** việc nhập lô chiết vào kho thành phẩm nay tách thành 2 bước rõ ràng — KCS (`kcs`/`kcs_truongphong`) khóa/duyệt chỉ tiêu chất lượng, **Giám đốc Sản xuất-Kỹ thuật (`giamdoc_sx`) mới là người duyệt cuối để lô thực sự vào kho thành phẩm** — đúng theo phân cấp trách nhiệm thật, tránh 1 vai trò vừa duyệt chất lượng vừa duyệt nhập kho.

**Khuyến nghị trước pilot:** đổi toàn bộ mật khẩu demo trước khi giao cho người dùng thật (hệ thống đã hỗ trợ buộc đổi mật khẩu lần đầu cho `admin` qua biến môi trường `MES_ADMIN_PASSWORD`; các tài khoản còn lại cần đổi thủ công qua "Hồ sơ" hoặc admin reset). Màn hình "Tài khoản" (admin) nay đã có nút **"Sửa quyền"** cho từng tài khoản — chỉnh trực tiếp vai trò/menu/quyền thao tác mà không cần tạo lại hay copy từ tài khoản khác, thuận tiện khi cần điều chỉnh phân quyền phát sinh trong lúc pilot.

---

## 3. Phạm vi dữ liệu dùng thử

### Trong phạm vi pilot (chế độ ghi nhận song song với quy trình giấy hiện tại)

| Phân hệ | Nội dung ghi nhận trong pilot |
|---|---|
| Nấu–Lọc–Chiết | Lệnh nấu/lọc, mẻ nấu/lên men/lọc/chiết — nhập song song với sổ tay |
| Kho NVL (công ty + phân xưởng) | Nhận/xuất/đề nghị nhận kho |
| Kho thành phẩm (WMS) | Cất vị trí, xuất kho, điều chuyển |
| Chất lượng cơ bản | Ghi nhận kết quả QC, giữ lô tự động khi fail |
| Truy xuất nguồn gốc | Tra cứu — không phát sinh dữ liệu mới, chỉ dùng để đối chiếu |
| Audit | Ghi nhận tự động mọi thao tác (không cần thao tác thêm) |
| Báo cáo (Dashboard, tồn kho, hạn dùng...) | Chỉ xem — đối chiếu với sổ sách giấy |

### Ngoài phạm vi pilot lần này (theo đúng chỉ đạo)

- **CIP** — vẫn tạm dừng sử dụng trong đợt pilot theo đúng yêu cầu của TGĐ, dù về mặt kỹ thuật tính năng đã hoàn thiện thêm đáng kể so với lần báo cáo trước (bổ sung cột N/A cho thông số không cần ghi theo từng bước, đổi kết quả thực hiện thành lựa chọn Đạt/Không đạt thay vì gõ tự do, thêm chức năng sửa trực tiếp danh mục loại biểu mẫu/thiết bị). Việc này **không làm thay đổi quyết định tạm dừng của TGĐ** — chỉ ghi nhận để khi bật lại (mục 7) thì tính năng đã sẵn sàng hơn.
- **Hiệu suất/OEE & Dừng máy** — backend đã có sẵn (mô hình dữ liệu, API tính OEE/Pareto dừng máy/MTBF) nhưng **màn hình thao tác chưa được bật trên menu** (đang ở dạng "chưa xây dựng" trong giao diện) — không phải quyết định của pilot mà là hiện trạng xây dựng, cũng đưa vào backlog (mục 7).

### Các phân hệ khác chưa có giao diện (không nằm trong phạm vi quyết định của pilot, chỉ là hiện trạng)

Điều độ, Lập lịch, Công thức nâng cao, Mẻ sản xuất (khung ISA-88 riêng), Cấp liệu, QC Lab (SPC/CAPA/LIMS nâng cao), Bảo trì/CMMS, Kiểm định — các mục này **chưa có màn hình sử dụng thật** trong bản hiện tại nên đương nhiên không thể đưa vào pilot, không liên quan tới quyết định "chưa tự động hoá" của TGĐ.

⚠️ **Cần xác nhận cách hiểu "ưu tiên chế độ ghi nhận, chưa để phần mềm tự động thay đổi dữ liệu vận hành quan trọng":** hệ thống hiện có một số hành vi tự động **theo thiết kế** đã kiểm thử kỹ (vd: tự động giữ lô khi QC fail, tự trừ tồn kho khi xuất, tự tạo đơn vị kho khi duyệt mẻ chiết). Đề xuất hiểu chỉ đạo là: **không bật thêm tự động hoá mới nào ngoài các hành vi đã kiểm thử này trong thời gian pilot**, chứ không tắt các cơ chế tự động đã là bản chất cốt lõi của hệ thống (nếu tắt sẽ mất chính giá trị MES mang lại, vd mục 2 báo cáo trước — "Tự động giữ lô ngay khi có chỉ tiêu QC không đạt"). Nếu quản đốc muốn hiểu theo nghĩa khác (vd: tắt hẳn tự động giữ lô, chỉ cảnh báo cho người xem xét thủ công), cần nêu rõ để điều chỉnh trước khi pilot bắt đầu.

---

## 4. Phương án sao lưu / khôi phục

✅ **Đã chốt (25/07/2026): hạ tầng CSDL dùng SQL Server** — không còn là đề xuất, đã xác nhận chính thức và production thực tế đã chuyển hẳn sang chạy trên SQL Server (không phải PostgreSQL/SQLite như 2 tài liệu cũ từng ghi). Toàn bộ migration đã kiểm thử và chạy gate thành công trên SQL Server thật.

⚠️ **Việc còn lại cần xử lý trước khi công bố phương án sao lưu chính thức:** **3 script sao lưu hiện có (`scripts/backup.sh`, `restore.sh`, `test_restore.sh`) vẫn đang gọi lệnh của PostgreSQL (`pg_dump`/`psql`), sẽ KHÔNG chạy được trên SQL Server** — quyết định hạ tầng đã chốt nhưng script sao lưu chưa được viết lại tương ứng (`sqlcmd`/`BACKUP DATABASE`). Đây là việc kỹ thuật thuần túy, không phải điểm cần TGĐ/quản đốc quyết định — CNTT cần hoàn tất trước khi pilot bắt đầu chạy dữ liệu thật.

**Hiện trạng khác cần biết:** sao lưu hiện tại là **thủ công**, chưa có lịch tự động (cron/Task Scheduler) nào đang thật sự chạy — chỉ có dòng gợi ý lịch chạy hàng tuần ghi trong comment của script, chưa được kích hoạt.

**Đề xuất phương án cho giai đoạn pilot:**
1. Sao lưu toàn bộ (full backup) **hàng ngày** cuối mỗi ca cuối cùng trong ngày, lưu ít nhất **7 bản gần nhất**.
2. Kiểm thử khôi phục (restore) **1 lần/tuần** vào môi trường tách biệt, đối chiếu số dòng dữ liệu + kiểm tra chuỗi audit không đứt gãy (`GET /api/audit/verify-chain`) — nguyên lý giống `test_restore.sh` đã có, cần viết lại cho đúng SQL Server.
3. Giữ tối thiểu 1 bản sao lưu offline (ngoài máy chủ chính) theo nguyên tắc 3-2-1 đã ghi trong script gốc.
4. Có người phụ trách rõ ràng (đề xuất: bộ phận CNTT) chịu trách nhiệm xác nhận sao lưu chạy thành công mỗi ngày trong suốt đợt pilot.

---

## 5. Kế hoạch pilot theo mốc thời gian

| Giai đoạn | Nội dung |
|---|---|
| **Ngày 1–5** | Chạy song song với quy trình giấy hiện tại tại Đông Mai. Chế độ ghi nhận theo mục 3. Không mở rộng sang Hạ Long. CNTT theo dõi sao lưu hàng ngày + phản hồi sự cố trong ca. |
| **Ngày 6** | Họp đánh giá nhanh giữa kỳ — đối chiếu số liệu ghi nhận trên hệ thống với sổ sách giấy, xử lý vướng mắc phát sinh. |
| **Ngày 7–14** (nếu giai đoạn đầu ổn) | Tiếp tục song song, mở rộng dần số ca/người dùng thật theo vai trò đã cấp ở mục 2. |
| **Kết thúc chu kỳ pilot** | Lập **biên bản đánh giá** đối chiếu với 6 tiêu chí nghiệm thu tối thiểu (mục 6). Đây là điều kiện bắt buộc trước khi xem xét mở rộng sang Hạ Long, theo đúng chỉ đạo. |

---

## 6. Bộ tiêu chí nghiệm thu tối thiểu

| Tiêu chí | Cách đo trong đợt pilot | Hiện trạng / rủi ro cần lưu ý |
|---|---|---|
| **Độ đầy đủ dữ liệu** | So khớp % sự kiện sản xuất ghi trên MES so với sổ giấy cùng kỳ | Cần chốt ngưỡng đạt (đề xuất ≥95%) |
| **Độ ổn định** | Số lần lỗi/gián đoạn ngoài kế hoạch trong 5–14 ngày pilot | Chưa có giám sát uptime tự động — cần phân công người trực theo dõi thủ công trong pilot |
| **Thời gian phản hồi** | Thời gian tải các màn hình thao tác chính (Dashboard, nhập mẻ, xuất kho) | Chưa đo baseline thật — nên đo ngày đầu pilot để lấy mốc so sánh |
| **Quyền truy cập** | Từng tài khoản chỉ thấy/thao tác đúng phạm vi đã cấp (mục 2) | Cơ chế đã kiểm thử tự động (64 file test), nên test lại thủ công 1 lượt với tài khoản thật trước khi giao |
| **Nhật ký thao tác (audit)** | Chuỗi audit không đứt gãy trong suốt pilot (`verify-chain`) | Đã có sẵn, ghi tự động, không cần thao tác thêm |
| **Khả năng xuất báo cáo** | Xuất được báo cáo tồn kho/sản xuất/truy xuất ra file (Excel/PDF) khi cần đối chiếu | ⚠️ **Khoảng trống thật, chưa thay đổi so với báo cáo trước:** hệ thống mới có **1 chức năng xuất CSV** (log nấu Braumat) và bản in trực tiếp từ trình duyệt cho lệnh nấu/lọc/hồ sơ lô — **chưa có xuất Excel/PDF chung cho các báo cáo tồn kho/sản xuất khác**. Cần quyết định: (a) bổ sung xuất báo cáo trước khi tính là đạt tiêu chí này, hoặc (b) chấp nhận bản in/xem trên màn hình là đủ cho pilot và bổ sung xuất file sau. |

---

## 7. CIP và Hiệu suất (OEE) — backlog sau pilot

| Hạng mục | Hiện trạng | Đề xuất thứ tự ưu tiên sau pilot |
|---|---|---|
| **Hiệu suất/OEE & Dừng máy** | Phần xử lý dữ liệu (mô hình, API tính OEE, Pareto dừng máy, MTBF) **đã xây xong và có dữ liệu mẫu** — chỉ còn thiếu màn hình thao tác trên menu | **Ưu tiên 1** — chi phí hoàn thiện thấp (chủ yếu là nối giao diện vào phần đã có), giá trị cao cho quản đốc theo dõi hiệu suất dây chuyền |
| **CIP** | Đã hoàn thiện đầy đủ và đang hiển thị trên menu, có 21 mẫu biểu mẫu CIP thật theo đúng quy trình vệ sinh, vừa bổ sung thêm cột N/A cho thông số không áp dụng theo từng bước và sửa trực tiếp danh mục — chỉ tạm dừng sử dụng trong đợt pilot theo yêu cầu | **Ưu tiên 2** — bật lại ngay khi pilot phần lõi ổn định, vì bản thân tính năng không có gì thiếu, chỉ đang chờ đúng lúc để đưa vào sử dụng |

*(Thứ tự trên là đề xuất dựa trên hiện trạng kỹ thuật — quyết định cuối cùng nên theo nhu cầu vận hành thực tế của quản đốc/TGĐ.)*

---

## 8. Việc cần xác nhận trước khi gửi chính thức

1. **Địa chỉ truy cập thật (LAN) cho Đông Mai** — repo không có địa chỉ IP/tên miền nội bộ; cần IT xác nhận trước khi gửi link cho người dùng thật (mục 1).
2. **Cách hiểu "không để phần mềm tự động thay đổi dữ liệu vận hành quan trọng"** — xác nhận chỉ dừng ở việc không bật tự động hoá mới, hay cần tắt bớt các hành vi tự động đã có sẵn (giữ lô QC, trừ tồn kho tự động...) (mục 3).

*(Điểm hạ tầng CSDL trong bản trước — nay đã chốt SQL Server, không còn là việc cần xác nhận; chỉ còn việc kỹ thuật thuần túy là viết lại script sao lưu, xem mục 4.)*
