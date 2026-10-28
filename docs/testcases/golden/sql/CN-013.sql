-- 案例：CN-013
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= '2025-01-01' AND p.AddDate < '2026-01-01';
-- 现象在应用层比对。候选大于最终答案。ZC2507021 应在最终答案里。
