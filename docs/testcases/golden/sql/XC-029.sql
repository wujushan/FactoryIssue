-- 案例：XC-029
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = DATEADD(day, -29, CAST(@today AS datetime));
DECLARE @end datetime = DATEADD(day, 1, CAST(@today AS datetime));
-- 近 30 天含今天，所以往前 29 天。国内机型 A920。停线中见国内四种停线状态。
SELECT p.Numbers, p.ProblemType, p.Status, p.StopStatus
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @start AND p.AddDate < @end AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'A920');
