# Kho thành phẩm: chuyển từ "1 dòng / vỉ" sang "theo LÔ + số lượng"

> Bàn giao cho bên phát triển. Bên deploy KHÔNG sửa (theo yêu cầu chủ dự án). Tài liệu này
> đã gói sẵn kết quả audit để không phải điều tra lại. Sau khi sửa, theo `docs/DEPLOY-CONTRACT.md`
> (chạy gate MSSQL + smoke đường GHI) trước khi merge.

## 1. Vấn đề
`approve_bottle` (duyệt chiết) hiện tạo **1 dòng `finished_goods_unit` cho MỖI vỉ/keg** + 1 cạnh
phả hệ / vỉ → **`2×ca_total + 2` dòng / lần duyệt** (`ca_total = ca1+ca2+ca3` tính theo vỉ/két).
- Bản ghi CH-47773 có ca_total = 190.000 → định tạo ~380.000 dòng trong 1 transaction.
- Insert **row-by-row** (không bật `fast_executemany`), qua mạng tới SQL Server → ~1 giờ →
  Cloudflare cắt 100s → **524, nút Duyệt "treo"**. Trên local (SQLite in-process) thì nhanh nên
  "chạy được" — KHÔNG phải hồi quy do code deploy; là bản chất quy mô + môi trường.
- Kèm bom scale: `GET /api/wms/units` (`list_units`, `services/wms.py:157-191`) select **cả bảng,
  không phân trang** → màn Kho TP treo khi bảng lớn.
- Mỗi duyệt còn giữ **khóa audit toàn cục** (`sp_getapplock 'mes_audit_chain'`, `app/audit.py:25,50`)
  suốt transaction → chặn mọi thao tác ghi có audit khác trong lúc đó.

**Yêu cầu:** duyệt chiết chỉ ghi **thông tin LÔ** (1 bản ghi + tổng số lượng), không ghi từng vỉ.

## 2. Điểm mấu chốt (từ audit)
- **Frontend Kho TP đã hoàn toàn theo lô + số lượng** (`frontend/views_ext.js`, `VIEWS.wms`): mọi
  màn dùng `GET /wms/units/by-lot` (`list_lot_summaries`) làm nguồn; **không màn nào** gọi
  `GET /wms/units` (per-vỉ) hay liệt kê từng `unit_code`. Mọi thao tác POST kèm `{product, lot,
  type, count/quantity}` — hệ tự chọn FIFO. → **Đổi backend sang lô hầu như không đụng frontend.**
- Cột `quantity` đã có sẵn và đã được `SUM(quantity)` ở tầng đọc (`list_lot_summaries`,
  `lot_aging_report`, `list_shipments`, `_bottle_forward_groups`).
- Giả định "1 dòng = 1 vỉ" tập trung ở **3 cột scalar per-row**: `status`, `location_id`,
  `shipment_id` (+ `unit_code` UNIQUE). **Không có bảng `ShipmentLine`** (đã bị bỏ) và không có
  bảng phân bổ vị trí → xuất/chuyển **một phần** lô buộc phải tách dòng hoặc thêm bảng con.
- Đã có 1 tiền lệ trừ theo số lượng: `adjust_bottle_finish_stock` (`wms.py:344-406`, nhánh delta<0
  `u.quantity -= remaining`) — dùng làm mẫu.

## 3. Phương án
**A (khuyến nghị) — Lô = 1 dòng, tách dòng khi thao tác một phần.**
Duyệt chiết tạo 1 dòng `quantity=total`. Khi xuất/chuyển/phân rã/xuất-tự-do một phần thì tách thành
(phần thao tác + phần còn lại) — tối đa vài dòng/lô, không bao giờ hàng trăm nghìn. Ít đụng schema.

**B — Mô hình lô thuần + bảng con** (`ShipmentLine` + bảng phân bổ vị trí). Sạch hơn về mô hình
nhưng thay đổi lớn, migration nặng, rủi ro cao hơn.

## 4. Danh sách cần sửa (file:line) — cho phương án A
**Tạo (đổi thành 1 dòng/lô):**
- `services/wms.py:194-224 _create_units` → phát 1 dòng `quantity=total`, 1 `unit_code`/lô.
- `routers/brewing.py:1787-1794 approve_bottle` → 1 cạnh phả hệ (`quantity=total`) thay cho vòng lặp.
- `services/wms.py:254-288 create_near_expiry_entry` → 1 dòng; `unit_codes`/undo theo lô.
- Cân nhắc bật **`fast_executemany`** ở `app/database.py:_engine_kwargs` (giúp mọi bulk-insert; phòng khi vẫn còn chỗ tạo nhiều dòng).

**Đếm số vỉ → `SUM(quantity)`/pack (không đếm dòng):**
- `wms.py:139-154 summary`, `51-57 list_locations`, `409-413 _capacity_ok`, `684-748 list_lot_summaries`
  (`_count`), `808-819 list_lot_summaries_by_location`, `757-805 lot_aging_report` (`count`),
  `1107-1126 resolve`, `981-1007 list_shipments`, `genealogy.py:222-269 _bottle_forward_groups` (label).

**Tiêu thụ có TÁCH DÒNG (viết 1 helper "trừ N theo FIFO, tách dòng biên" dùng chung):**
- `wms.py:876-978 create_shipment`, `521-546 decompose_batch` + `476-497 _decompose_one_vi`,
  `594-625 free_issue_batch`, `1129-1165 relocate_batch`, `437-473 transfer_units`, `416-434 putaway`.
  (Hiện tất cả dùng `.order_by(created_at).limit(count)` chọn nguyên dòng + set `status`/`location_id`/
  `shipment_id` per-row → cần trừ `quantity` + tách dòng phần còn lại.)

**Undo theo unit_id (điều chỉnh theo mô hình mới):**
- `wms.py:1010-1038 undo_shipment`, `549-591 undo_decompose_batch`, `628-658 undo_free_issue_batch`,
  `305-341 undo_near_expiry_entry`.

**Sức chứa vị trí (`WmsLocation.capacity`):** hiện đếm dòng; đổi sang tổng vỉ = `SUM(quantity)/pack_size`
hoặc định nghĩa lại capacity theo đơn vị mới.

**Quyết định về vị trí:** 1 dòng-lô chỉ mang 1 `location_id`. Lô nằm ở nhiều bin → cần tách dòng theo
bin (chấp nhận vài dòng/lô) HOẶC thêm bảng phân bổ vị trí (phương án B).

## 5. Di trú dữ liệu
Prod đã có sẵn một ít `finished_goods_unit` (per-vỉ). Migration cần **gộp** các dòng cùng
(`finished_product_id`, `lot_code`, `unit_type`, `status`, `location_id`, `shipment_id`) thành 1 dòng
`quantity = SUM`. Giữ 1 `unit_code` đại diện. Cập nhật `genealogy_edge` tương ứng.

## 6. Kiểm thử bắt buộc (theo DEPLOY-CONTRACT)
- Gate MSSQL: `alembic upgrade <head-prod> → head` trên SQL Server thật.
- **Smoke đường GHI trên MSSQL** (bom scale chỉ lộ ở đây): seed 1 lô lớn (vd 190.000) → duyệt chiết
  (phải xong trong vài giây, 1 dòng) → xuất một phần → phân rã một phần → điều chuyển một phần →
  xuất tự do → undo từng cái; kiểm số lượng khớp và không đẻ dòng thừa.
- Phân trang `GET /api/wms/units` (P1) trước khi kho có nhiều lô.

## 7. Cũng cần xử (không thuộc kho TP nhưng liên quan hiệu năng — xem audit)
- N+1 ở `services/filter_order.py list_orders`, `brew_order.py list_orders`, `warehouse.py`,
  `genealogy` trace → preload theo batch.
- Realtime tab poll 2 call SQL ngoài mỗi 15s không clear (`frontend/app.js ~6390`) → clear khi rời tab.
- Cache engine SQL ngoài thay vì `create_engine` mỗi request (`*_external.py`).
</content>
