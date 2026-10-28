-- 案例：CN-039
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = DATEADD(year, -1, CAST(@today AS datetime));
DECLARE @end datetime = DATEADD(day, 1, CAST(@today AS datetime));
-- 「最近一年」含今天往前倒推。说法见案例备注。剥净后再分三组。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @start AND p.AddDate < @end;
