-- 案例：XC-004
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = DATEADD(day, -13, CAST(@today AS datetime));
DECLARE @end datetime = DATEADD(day, 1, CAST(@today AS datetime));

SELECT N'国内' AS DomainName, p.Numbers, p.AddDate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @start AND p.AddDate < @end
UNION ALL
SELECT N'巴西', p.OrderNumber, p.AddDate
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1 AND p.AddDate >= @start AND p.AddDate < @end
UNION ALL
SELECT N'海外', p.Numbers, p.AddDate
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0 AND p.AddDate >= @start AND p.AddDate < @end;
-- 展示按域拆开，域内 AddDate 倒序。超过导出阈值时的截断在应用层。
