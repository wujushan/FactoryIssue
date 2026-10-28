-- 案例：XC-007
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT SUM(CASE WHEN p.BadQty IS NOT NULL AND p.ProdQty IS NOT NULL AND p.ProdQty <> 0 THEN p.BadQty END) AS BadSum,
       SUM(CASE WHEN p.BadQty IS NOT NULL AND p.ProdQty IS NOT NULL AND p.ProdQty <> 0 THEN p.ProdQty END) AS Denom
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01';
SELECT SUM(CASE WHEN p.BadQty IS NOT NULL AND p.ImpactQty IS NOT NULL AND p.ImpactQty <> 0 THEN p.BadQty END),
       SUM(CASE WHEN p.BadQty IS NOT NULL AND p.ImpactQty IS NOT NULL AND p.ImpactQty <> 0 THEN p.ImpactQty END)
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1 AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01';
SELECT p.Numbers, p.Rate
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0 AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01';
-- 国内、巴西：合计不良率＝不良合计 / 分母合计 × 100，保留 2 位。海外不参与这个算式。
