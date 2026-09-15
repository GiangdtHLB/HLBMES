/* ============================================================================
   Gộp lại các lô NVL bị "tách sinh mã lô MỚI" theo cơ chế CŨ (trước khi code
   được sửa để tái dùng lại lot_code khi tách — xem app/services/warehouse.py::
   _transfer_lot). Bản T-SQL tương đương app/merge_split_legacy_lots.py — cùng
   1 logic an toàn, chỉ khác cách chạy (SQL Server Management Studio / sqlcmd
   thay vì Python).

   AN TOÀN: chỉ gộp lô con KHI VÀ CHỈ KHI thỏa CẢ 4 điều kiện:
     1. Không phải nguồn (from_id) của bất kỳ genealogy_edge nào khác (chưa
        từng bị tách tiếp / tiêu thụ cho mẻ / dùng cho lô lọc / lô thành phẩm).
     2. MỌI stock_movement của lô con đều là movement_type='transfer' — nếu
        có thêm issue/receipt/adjust nào khác thì đã có lịch sử độc lập.
     3. location HIỆN TẠI của lô con TRÙNG với location hiện tại của lô cha
        (nếu khác kho, lô con là tồn THẬT đang ở kho khác — gộp sẽ làm sai
        lệch tồn kho theo từng kho, tuyệt đối không được gộp).
     4. status khác 'on_hold'.
   Lô con KHÔNG thỏa cả 4 điều kiện trên sẽ được liệt kê riêng (cột `action`
   = lý do bỏ qua) — KHÔNG bị đụng tới.

   SỬA 2026-09-15 (so với bản đầu): bản đầu chỉ chấp nhận "đúng 1 giao dịch" (bỏ sót các lô
   "Xuất theo đề nghị" rồi bị "Hoàn tác" — 2 giao dịch transfer nhưng NET không đổi gì, lô con
   thực chất CHƯA dùng thật) VÀ THIẾU kiểm tra vị trí kho (kiểm tra dữ liệu thật thấy cặp
   TD-KCT-22 → 2026-00069: lô cha ở "Kho công ty", lô con ĐANG THẬT SỰ ở "Kho phân xưởng" — nếu
   gộp theo bản đầu sẽ cộng nhầm quantity sang sai kho). Bản này thêm điều kiện 3 (khớp kho) và
   nới điều kiện 2 (không giới hạn SỐ LƯỢNG giao dịch, chỉ cấm LOẠI giao dịch khác transfer).

   QUAN TRỌNG — ĐỌC TRƯỚC KHI CHẠY:
     1. Đây là thao tác sửa dữ liệu thật — sao lưu CSDL trước khi chạy.
     2. Chạy NGUYÊN CẢ FILE này 1 lượt, từ đầu đến cuối, trong CÙNG 1 cửa sổ
        query (không tách rời PHẦN 1/PHẦN 2 ra 2 lượt chạy khác nhau — bảng
        tạm #eligible chỉ tồn tại trong đúng phiên kết nối đang chạy).
     3. AN TOÀN MẶC ĐỊNH: script kết thúc bằng ROLLBACK TRAN — chạy nguyên
        file lần đầu SẼ KHÔNG sửa gì thật, chỉ in ra (PRINT) số dòng LẼ RA sẽ
        bị đổi. Xem kỹ phần PRINT đó VÀ bảng xem trước (PHẦN 1), đúng ý rồi
        mới đổi đúng 1 chữ ở dòng cuối file: `ROLLBACK TRAN;` → `COMMIT TRAN;`,
        rồi chạy lại nguyên file — lúc đó mới thật sự áp dụng.
   ============================================================================ */


/* ================= PHẦN 1 — XEM TRƯỚC (chỉ SELECT, không sửa gì) ================= */

;WITH split_edges AS (
    SELECT
        ge.edge_id, ge.from_id AS parent_lot_id, ge.to_id AS child_lot_id,
        p.lot_code AS parent_code, c.lot_code AS child_code,
        c.quantity AS child_qty, c.status AS child_status,
        p.location AS parent_location, c.location AS child_location
    FROM genealogy_edge ge
    JOIN material_lot p ON p.lot_id = ge.from_id
    JOIN material_lot c ON c.lot_id = ge.to_id
    WHERE ge.from_type = 'lot' AND ge.to_type = 'lot' AND ge.relation = 'split'
      AND p.lot_code <> c.lot_code
),
further_edges AS (
    -- lô con đã có giao dịch genealogy TIẾP THEO (tách tiếp/tiêu thụ cho mẻ/lọc/chiết)
    SELECT DISTINCT from_id AS child_lot_id FROM genealogy_edge WHERE from_type = 'lot'
),
movement_check AS (
    -- KHÔNG giới hạn SỐ LƯỢNG giao dịch — chỉ cấm LOẠI khác 'transfer' (issue/receipt/adjust).
    -- 2 lần transfer (đi + hoàn tác, NET = 0) vẫn coi là an toàn nếu vị trí đã quay về đúng chỗ.
    SELECT lot_id, SUM(CASE WHEN movement_type <> 'transfer' THEN 1 ELSE 0 END) AS n_other
    FROM stock_movement GROUP BY lot_id
),
preview AS (
    SELECT
        se.*,
        CASE
            WHEN fe.child_lot_id IS NOT NULL THEN N'BỎ QUA — đã có giao dịch tiếp theo'
            WHEN mc.n_other IS NULL OR mc.n_other > 0 THEN N'BỎ QUA — có giao dịch khác transfer (issue/receipt/adjust)'
            WHEN se.child_location <> se.parent_location THEN N'BỎ QUA — đang ở kho khác lô cha (tồn thật, không gộp)'
            WHEN se.child_status = 'on_hold' THEN N'BỎ QUA — đang ON HOLD'
            ELSE N'OK — sẽ gộp'
        END AS action
    FROM split_edges se
    LEFT JOIN further_edges fe ON fe.child_lot_id = se.child_lot_id
    LEFT JOIN movement_check mc ON mc.lot_id = se.child_lot_id
)
SELECT parent_code, child_code, child_qty, parent_location, child_location, action
INTO #eligible_preview
FROM preview;

SELECT * FROM #eligible_preview ORDER BY parent_code, child_code;
SELECT action, COUNT(*) AS so_luong, SUM(child_qty) AS tong_qty FROM #eligible_preview GROUP BY action;


/* ================= PHẦN 2 — GỘP THẬT (dùng lại đúng #eligible_preview ở trên) ================= */

;WITH split_edges AS (
    SELECT ge.edge_id, ge.from_id AS parent_lot_id, ge.to_id AS child_lot_id,
           p.lot_code AS parent_code, c.lot_code AS child_code, c.quantity AS child_qty
    FROM genealogy_edge ge
    JOIN material_lot p ON p.lot_id = ge.from_id
    JOIN material_lot c ON c.lot_id = ge.to_id
    WHERE ge.from_type = 'lot' AND ge.to_type = 'lot' AND ge.relation = 'split'
      AND p.lot_code <> c.lot_code
)
SELECT se.edge_id, se.parent_lot_id, se.child_lot_id, se.child_qty
INTO #eligible
FROM split_edges se
JOIN #eligible_preview ep ON ep.parent_code = se.parent_code AND ep.child_code = se.child_code
WHERE ep.action = N'OK — sẽ gộp';

BEGIN TRAN;

DECLARE @rows_updated_parent INT, @rows_moved_qc INT, @rows_moved_dev INT,
        @rows_cleared_mv INT, @rows_deleted_edges INT, @rows_deleted_lots INT;

-- 1) Cộng dồn quantity của MỌI lô con hợp lệ về đúng lô cha (gộp theo cha, 1 UPDATE duy nhất)
UPDATE p
SET p.quantity = p.quantity + agg.total_qty
FROM material_lot p
JOIN (SELECT parent_lot_id, SUM(child_qty) AS total_qty FROM #eligible GROUP BY parent_lot_id) agg
  ON agg.parent_lot_id = p.lot_id;
SET @rows_updated_parent = @@ROWCOUNT;

-- 2) Di chuyển QualityResult của lô con sang lô cha (giữ nguyên lịch sử QC)
UPDATE qr SET qr.scope_id = e.parent_lot_id
FROM quality_result qr JOIN #eligible e ON e.child_lot_id = qr.scope_id AND qr.scope_type = 'lot';
SET @rows_moved_qc = @@ROWCOUNT;

-- 3) Di chuyển Deviation của lô con sang lô cha
UPDATE dv SET dv.scope_id = e.parent_lot_id
FROM deviation dv JOIN #eligible e ON e.child_lot_id = dv.scope_id AND dv.scope_type = 'lot';
SET @rows_moved_dev = @@ROWCOUNT;

-- 4) Gỡ lot_id khỏi StockMovement của lô con (giữ NGUYÊN cột lot_code dạng text để vẫn tra được
--    lịch sử) — tránh lỗi khóa ngoại khi xóa lô con ở bước 6.
UPDATE sm SET sm.lot_id = NULL
FROM stock_movement sm JOIN #eligible e ON e.child_lot_id = sm.lot_id;
SET @rows_cleared_mv = @@ROWCOUNT;

-- 5) Xóa cạnh genealogy_edge (relation=split) nối cha→con — đã gộp xong thì cạnh này hết ý nghĩa
DELETE ge FROM genealogy_edge ge JOIN #eligible e ON e.edge_id = ge.edge_id;
SET @rows_deleted_edges = @@ROWCOUNT;

-- 6) Xóa hẳn dòng MaterialLot của lô con
DELETE ml FROM material_lot ml JOIN #eligible e ON e.child_lot_id = ml.lot_id;
SET @rows_deleted_lots = @@ROWCOUNT;

PRINT N'--- Kết quả (đang ROLLBACK theo mặc định — xem kỹ rồi mới đổi COMMIT nếu đúng ý) ---';
PRINT N'Lô cha được cộng dồn quantity: ' + CAST(@rows_updated_parent AS NVARCHAR(20));
PRINT N'QualityResult đã chuyển sang lô cha: ' + CAST(@rows_moved_qc AS NVARCHAR(20));
PRINT N'Deviation đã chuyển sang lô cha: ' + CAST(@rows_moved_dev AS NVARCHAR(20));
PRINT N'StockMovement đã gỡ lot_id: ' + CAST(@rows_cleared_mv AS NVARCHAR(20));
PRINT N'Cạnh genealogy (split) đã xóa: ' + CAST(@rows_deleted_edges AS NVARCHAR(20));
PRINT N'Lô con đã xóa: ' + CAST(@rows_deleted_lots AS NVARCHAR(20));

-- AN TOÀN MẶC ĐỊNH: ROLLBACK — đổi thành COMMIT TRAN khi ĐÃ xem kỹ 2 bảng PHẦN 1 + PRINT ở
-- trên và chắc chắn muốn áp dụng thật (không hoàn tác được qua ứng dụng nữa).
ROLLBACK TRAN;

DROP TABLE #eligible_preview;
DROP TABLE #eligible;
