-- 案例：XC-019
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = DATETIMEFROMPARTS(YEAR(@today), 1, 1, 0, 0, 0, 0);
DECLARE @end datetime = DATEADD(day, 1, CAST(@today AS datetime));
-- 国内机型走机型子表。巴西、海外的大机型 ID 逐段对产品主数据，名称归一后等于 A8900。
SELECT p.ProblemType, COUNT(*) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @start AND p.AddDate < @end AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'A8900')
GROUP BY p.ProblemType;
