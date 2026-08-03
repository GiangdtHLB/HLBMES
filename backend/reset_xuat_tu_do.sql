-- Xóa lịch sử "Xuất tự do" (chỉ loại thật sự tự do — KHÔNG đụng các dòng đang gắn với
-- NVL đã dùng cho mẻ nấu/lọc/chiết, vì các dòng đó bị brew_material_usage/
-- filter_material_usage/bottle_material_usage.movement_id tham chiếu).
--
-- CÁCH DÙNG: giống các file reset khác — chạy khối DELETE/SELECT trước, xem kết quả,
-- rồi mới chạy riêng COMMIT hoặc ROLLBACK. Đã sao lưu CSDL trước khi chạy.

SET NOCOUNT ON;
BEGIN TRANSACTION;

DECLARE @ad_hoc_ids TABLE (movement_id NVARCHAR(64) PRIMARY KEY);
INSERT INTO @ad_hoc_ids (movement_id)
SELECT m.movement_id
FROM stock_movement m
WHERE m.movement_type = 'issue' AND m.mode = 'tu_do'
  AND NOT EXISTS (SELECT 1 FROM brew_material_usage u WHERE u.movement_id = m.movement_id)
  AND NOT EXISTS (SELECT 1 FROM filter_material_usage u WHERE u.movement_id = m.movement_id)
  AND NOT EXISTS (SELECT 1 FROM bottle_material_usage u WHERE u.movement_id = m.movement_id);

-- Xóa trước các giao dịch "Hoàn lại" (movement_type='return') trỏ ngược (reversal_of) tới
-- đúng các dòng ad-hoc này — tự tham chiếu nên phải xóa con trước cha.
DELETE FROM stock_movement WHERE reversal_of IN (SELECT movement_id FROM @ad_hoc_ids);

-- Xóa chính các dòng xuất tự do ad-hoc.
DELETE FROM stock_movement WHERE movement_id IN (SELECT movement_id FROM @ad_hoc_ids);

-- Kiểm tra: số dòng "tu_do" còn lại (phải là NVL đã dùng cho mẻ — không xóa được ở đây).
SELECT COUNT(*) AS con_lai_tu_do FROM stock_movement WHERE movement_type = 'issue' AND mode = 'tu_do';

-- Xem kết quả xong mới chạy 1 trong 2 dòng dưới (chạy RIÊNG):
-- COMMIT TRANSACTION;   -- xác nhận xóa thật
-- ROLLBACK TRANSACTION; -- hủy, khôi phục như cũ
