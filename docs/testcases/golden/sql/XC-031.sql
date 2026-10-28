-- 案例：XC-031
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = '2026-01-01';
DECLARE @end datetime = CASE WHEN @today < '2027-01-01'
    THEN DATEADD(day, 1, CAST(@today AS datetime)) ELSE '2027-01-01' END;
-- 说法同 CN-055。三域各自在剥净后的文字里分三组，再按域给出张数。
SELECT N'国内' AS DomainName, p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @start AND p.AddDate < @end
UNION ALL
SELECT N'巴西', p.OrderNumber
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1 AND p.AddDate >= @start AND p.AddDate < @end
UNION ALL
SELECT N'海外', p.Numbers
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0 AND p.AddDate >= @start AND p.AddDate < @end;
