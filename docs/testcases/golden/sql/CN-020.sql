-- 案例：CN-020
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 词组：电池卡扣、电池盖卡扣。不拆开。
SELECT p.Numbers, p.CInvCode
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= '2025-10-01' AND p.AddDate < '2026-01-01';
