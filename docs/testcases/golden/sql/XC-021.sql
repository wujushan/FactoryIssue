-- 案例：XC-021
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = DATETIMEFROMPARTS(YEAR(@today), 1, 1, 0, 0, 0, 0);
DECLARE @end datetime = DATEADD(day, 1, CAST(@today AS datetime));
-- 第一段：今年建单且机型 A8900。第二段：这段结果里 IsStop＝1 且停线日期有值。
SELECT p.Numbers, p.IsStop, p.StopDate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @start AND p.AddDate < @end AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'A8900');
-- 巴西 IsStopLine、海外 IsStop 用各自的停过线口径，机型用大机型名称 A8900。日期文本在应用层解析。
