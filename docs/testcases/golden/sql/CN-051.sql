-- 案例：CN-051
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT MONTH(p.AddDate) AS Mon, COUNT(*) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01'
GROUP BY MONTH(p.AddDate);
-- 1 到 6 月里没有的月份补 0。
