-- Xóa CHỈ tồn kho NVL ở "Kho công ty" (không đụng Kho phân xưởng, Nấu/Lọc/Chiết, Kho TP).
-- material_lot không tách bảng riêng theo kho — lọc bằng cột location = N'Kho công ty'.
--
-- CÁCH DÙNG: giống reset_operational_data.sql — chạy từ đầu tới hết khối DELETE (không chạy
-- COMMIT/ROLLBACK vội), đọc kết quả SELECT ở cuối, rồi mới bôi đen chạy riêng COMMIT hoặc
-- ROLLBACK. Đã sao lưu CSDL trước khi chạy.

SET NOCOUNT ON;
BEGIN TRANSACTION;

DECLARE @company_lots TABLE (lot_id NVARCHAR(64) PRIMARY KEY);
INSERT INTO @company_lots (lot_id)
SELECT lot_id FROM material_lot WHERE location = N'Kho công ty';

-- Kiểm tra an toàn: lô nào ở Kho công ty mà đã bị Nấu/Lọc/Chiết dùng (hiếm, nhưng nếu có thì
-- KHÔNG được xóa lô đó ở đây — xóa sẽ vỡ khóa ngoại/mất dấu vết NVL đã dùng thật).
IF EXISTS (SELECT 1 FROM brew_material_usage WHERE lot_id IN (SELECT lot_id FROM @company_lots))
   OR EXISTS (SELECT 1 FROM filter_material_usage WHERE lot_id IN (SELECT lot_id FROM @company_lots))
   OR EXISTS (SELECT 1 FROM bottle_material_usage WHERE lot_id IN (SELECT lot_id FROM @company_lots))
BEGIN
    PRINT N'DỪNG LẠI — có lô ở Kho công ty đang được Nấu/Lọc/Chiết tham chiếu (đã dùng thật), không an toàn để xóa theo cách này. Xem 3 bảng dưới đây, xử lý riêng trước.';
    SELECT 'brew_material_usage' AS bang, u.usage_id, u.lot_id, u.material_name, u.quantity
      FROM brew_material_usage u WHERE u.lot_id IN (SELECT lot_id FROM @company_lots)
    UNION ALL
    SELECT 'filter_material_usage', u.usage_id, u.lot_id, u.material_name, u.quantity
      FROM filter_material_usage u WHERE u.lot_id IN (SELECT lot_id FROM @company_lots)
    UNION ALL
    SELECT 'bottle_material_usage', u.usage_id, u.lot_id, u.material_name, u.quantity
      FROM bottle_material_usage u WHERE u.lot_id IN (SELECT lot_id FROM @company_lots);
    ROLLBACK TRANSACTION;
    RETURN;
END

DELETE FROM stock_movement WHERE lot_id IN (SELECT lot_id FROM @company_lots);
DELETE FROM material_request_line
  WHERE preferred_lot_id IN (SELECT lot_id FROM @company_lots)
     OR fulfilled_lot_id IN (SELECT lot_id FROM @company_lots);
DELETE FROM stock_count_line WHERE lot_id IN (SELECT lot_id FROM @company_lots);
DELETE FROM genealogy_edge
  WHERE (from_type = 'lot' AND from_id IN (SELECT lot_id FROM @company_lots))
     OR (to_type = 'lot' AND to_id IN (SELECT lot_id FROM @company_lots));
DELETE FROM material_lot WHERE lot_id IN (SELECT lot_id FROM @company_lots);

-- Kiểm tra sau khi xóa — phải = 0.
SELECT COUNT(*) AS con_lai_kho_cong_ty FROM material_lot WHERE location = N'Kho công ty';

-- Xem kết quả xong mới chạy 1 trong 2 dòng dưới (chạy RIÊNG):
-- COMMIT TRANSACTION;   -- xác nhận xóa thật
-- ROLLBACK TRANSACTION; -- hủy, khôi phục như cũ
