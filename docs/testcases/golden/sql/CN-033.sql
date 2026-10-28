-- 案例：CN-033
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 1900-01-01 是星期一，用来算周一，避免依赖 DATEFIRST。
DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @thisMonday date = DATEADD(day, -(DATEDIFF(day, 0, @today) % 7), @today);
DECLARE @lastMonday date = DATEADD(day, -7, @thisMonday);

SELECT p.Numbers, p.ProblemLevel, p.Status
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.Status <> 32
  AND p.ProblemLevel IN (N'A+', N'A')
  AND p.AddDate >= @lastMonday
  AND p.AddDate < @thisMonday;
-- Status＝13 是生产角色驳回，仍算未结案。有则单独计数。
