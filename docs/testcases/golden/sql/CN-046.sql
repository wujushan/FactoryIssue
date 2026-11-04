-- 案例：CN-046
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect
-- 「上半年」没写年份：今年 1 月 1 日至 6 月 30 日；今年这段还没结束时止于今天。

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start date = DATEFROMPARTS(YEAR(@today), 1, 1);
DECLARE @halfEnd date = DATEFROMPARTS(YEAR(@today), 7, 1);
DECLARE @end date = CASE WHEN @today < @halfEnd THEN DATEADD(day, 1, @today) ELSE @halfEnd END;
SELECT p.Numbers, p.AddDate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @start AND p.AddDate < @end
ORDER BY p.AddDate DESC;
-- 展示取最近 20 张。文件里的问题描述是剥净后的全文。
