-- 案例：XC-016
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 窗口 [2026-06-01, 2026-07-01)。「6 月份」没写年份，今年 6 月已过，即 2026 年 6 月。
SELECT p.Numbers, p.ProblemType, p.Rate, p.BadQty, p.AddDate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= '2026-06-01'
  AND p.AddDate < '2026-07-01';
-- 机型从 ZCTracking_ProductNames 收成一行再展示。问题类型、空值翻成人话在应用层做。
