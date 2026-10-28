-- 案例：CN-047
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 参与：BadQty 非空，且 ProdQty 非空、非 0。
SELECT
    SUM(CASE WHEN p.BadQty IS NOT NULL AND p.ProdQty IS NOT NULL AND p.ProdQty <> 0
             THEN p.BadQty END) AS BadSum,
    SUM(CASE WHEN p.BadQty IS NOT NULL AND p.ProdQty IS NOT NULL AND p.ProdQty <> 0
             THEN p.ProdQty END) AS ProdSum,
    SUM(CASE WHEN p.BadQty IS NOT NULL AND p.ProdQty IS NOT NULL AND p.ProdQty <> 0
             THEN 1 ELSE 0 END) AS UsedCnt,
    SUM(CASE WHEN p.BadQty IS NULL OR p.ProdQty IS NULL OR p.ProdQty = 0
             THEN 1 ELSE 0 END) AS SkippedCnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= '2026-01-01'
  AND p.AddDate < '2026-07-01'
  AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'A8900'
);
-- 不良率＝ROUND(BadSum * 100.0 / ProdSum, 2)。ProdSum 为空或 0 时不除，写明无法计算。
