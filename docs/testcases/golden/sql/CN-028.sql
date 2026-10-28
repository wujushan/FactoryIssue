-- 案例：CN-028
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Factory, COUNT(*) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.IsStop = 1
  AND p.StopDate >= '2025-01-01' AND p.StopDate < '2026-01-01'
GROUP BY p.Factory;
-- 工厂码翻成名称在应用层。柯洱斯的同名码合并成一行。
SELECT COUNT(*) AS MissingStopDate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.IsStop = 1 AND p.StopDate IS NULL;
