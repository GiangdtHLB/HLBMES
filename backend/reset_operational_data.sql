-- Xóa dữ liệu VẬN HÀNH (tồn) trước khi chạy thử — GIỮ NGUYÊN Danh mục.
-- Mirror chính xác thứ tự xóa trong backend/app/reset_operational_data.py — xem file đó để
-- biết lý do/chi tiết từng bảng (phạm vi, cái gì KHÔNG đụng: audit_log, formula_activation_log,
-- recipe_change, ops_setting, packaging_type, và mọi Danh mục).
--
-- CÁCH DÙNG (SQL Server Management Studio hoặc sqlcmd):
--   1. Đã sao lưu CSDL trước (BACKUP DATABASE ...).
--   2. Mở file này, chạy từ đầu tới hết khối DELETE (không chạy COMMIT/ROLLBACK vội).
--   3. Đọc kết quả khối "kiểm tra sau khi xóa" ở cuối — nếu đúng ý, bôi đen dòng
--      COMMIT TRANSACTION rồi chạy riêng dòng đó. Nếu sai/nghi ngờ, chạy ROLLBACK TRANSACTION
--      thay vào đó — mọi thứ trở lại như cũ, không mất gì.

SET NOCOUNT ON;
BEGIN TRANSACTION;

DELETE FROM stage_indicator;
DELETE FROM genealogy_edge;
DELETE FROM brew_process_step;
DELETE FROM brew_process_log;
DELETE FROM ferment_brew_link;
DELETE FROM ferment_process_log;
DELETE FROM ferment_daily_reading;
DELETE FROM load_slip_line;
DELETE FROM packaging_move;
DELETE FROM brew_material_usage;
DELETE FROM filter_material_usage;
DELETE FROM bottle_material_usage;
DELETE FROM material_request_line;
DELETE FROM stock_count_line;
DELETE FROM filter_order_tank;
DELETE FROM filter_order_material_line;
DELETE FROM brew_order_material_line;
DELETE FROM near_expiry_entry;
DELETE FROM consigned_entry;
DELETE FROM finished_goods_unit;
DELETE FROM load_slip;
DELETE FROM material_request;
DELETE FROM stock_count;
DELETE FROM brew_batch;
DELETE FROM bottle_record;
DELETE FROM filter_record;
DELETE FROM brew_record;
DELETE FROM ferment_record;
DELETE FROM shipment;
DELETE FROM brew_order;
DELETE FROM filter_order;
DELETE FROM brew_master_order;
DELETE FROM filter_master_order;
DELETE FROM stock_movement;
DELETE FROM material_lot;
DELETE FROM material_receipt;

-- Kiểm tra sau khi xóa — mọi dòng phải = 0.
SELECT 'stage_indicator' AS tbl, COUNT(*) AS con_lai FROM stage_indicator
UNION ALL SELECT 'genealogy_edge', COUNT(*) FROM genealogy_edge
UNION ALL SELECT 'brew_material_usage', COUNT(*) FROM brew_material_usage
UNION ALL SELECT 'filter_material_usage', COUNT(*) FROM filter_material_usage
UNION ALL SELECT 'bottle_material_usage', COUNT(*) FROM bottle_material_usage
UNION ALL SELECT 'finished_goods_unit', COUNT(*) FROM finished_goods_unit
UNION ALL SELECT 'brew_batch', COUNT(*) FROM brew_batch
UNION ALL SELECT 'bottle_record', COUNT(*) FROM bottle_record
UNION ALL SELECT 'filter_record', COUNT(*) FROM filter_record
UNION ALL SELECT 'brew_record', COUNT(*) FROM brew_record
UNION ALL SELECT 'ferment_record', COUNT(*) FROM ferment_record
UNION ALL SELECT 'shipment', COUNT(*) FROM shipment
UNION ALL SELECT 'brew_order', COUNT(*) FROM brew_order
UNION ALL SELECT 'filter_order', COUNT(*) FROM filter_order
UNION ALL SELECT 'stock_movement', COUNT(*) FROM stock_movement
UNION ALL SELECT 'material_lot', COUNT(*) FROM material_lot;

-- Xem kỹ kết quả SELECT ở trên rồi mới chạy 1 trong 2 dòng dưới (chạy RIÊNG, không chạy cùng lúc):
-- COMMIT TRANSACTION;   -- xác nhận xóa thật
-- ROLLBACK TRANSACTION; -- hủy, khôi phục như cũ
