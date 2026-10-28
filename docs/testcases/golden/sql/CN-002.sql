-- 案例：CN-002
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, p.Status, p.AllReDepartment
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.ProblemType = 2
  AND p.AddDate >= '2025-01-01' AND p.AddDate < '2026-01-01';
-- 逐段对 info.dbo.Department。空：Status＝32 为无需定责，否则未定责。对不上的 ID 显示未填。
