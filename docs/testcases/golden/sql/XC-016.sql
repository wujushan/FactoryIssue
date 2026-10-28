-- 案例：XC-016
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @thisMonth date = DATEFROMPARTS(YEAR(@today), MONTH(@today), 1);
DECLARE @prevMonth date = DATEADD(month, -1, @thisMonth);

SELECT p.Numbers, p.ProblemType, p.Rate, p.BadQty, p.AddDate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= @prevMonth
  AND p.AddDate < @thisMonth;
-- 机型从 ZCTracking_ProductNames 收成一行再展示。问题类型、空值翻成人话在应用层做。
