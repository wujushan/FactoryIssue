-- 案例：CN-016
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- ProblemType＝6 结构问题。Rate 存的是百分数的数值部分，100 表示 100%。
SELECT p.Numbers, p.Rate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.ProblemType = 6
  AND p.Rate = 100
  AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01';
