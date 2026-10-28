-- 案例：XC-024
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.ProblemType, COUNT(*) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.ProblemType <> 3
  AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01'
GROUP BY p.ProblemType;
-- 2 软件、1 硬件、4 资料、5 工厂制程、6 结构、7 制程优化。缺的补 0。
-- 另计 ProblemType＝3 的张数，用来核对 6 类之和＝总数减物料问题。
