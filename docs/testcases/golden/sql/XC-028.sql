-- 案例：XC-028
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = '2026-01-01';
DECLARE @end datetime = CASE WHEN @today < '2027-01-01'
    THEN DATEADD(day, 1, CAST(@today AS datetime)) ELSE '2027-01-01' END;
SELECT UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) AS NormName, COUNT(DISTINCT p.ID) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
INNER JOIN CoreINFO.dbo.ZCTracking_ProductNames AS n ON n.ProblemId = p.ID
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @start AND p.AddDate < @end
  AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) IN (N'A920', N'A920PRO')
GROUP BY UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N''));
-- 巴西、海外大机型同样只收这两个归一名称，再按名称相加。
