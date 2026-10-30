-- 案例：XC-039
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 上上周＝上周一再往前的那一周（周一至周日）。1900-01-01 是星期一，用来算周一。
-- 起止日期随运行日变，golden 不写死。清单类给了能换算的时间，本轮不追问。
-- 2026-10-29 实测这次没有符合条件的单，应用层不出表。不是滚动到今天，口径不写「截至今天」。
DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @thisMonday date = DATEADD(day, -(DATEDIFF(day, 0, @today) % 7), @today);
DECLARE @lastMonday date = DATEADD(day, -7, @thisMonday);
DECLARE @start date = DATEADD(day, -7, @lastMonday);

SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= @start
  AND p.AddDate < @lastMonday;
