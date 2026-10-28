-- 案例：CN-008
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = '2026-01-01';
DECLARE @end datetime = CASE WHEN @today < '2027-01-01'
    THEN DATEADD(day, 1, CAST(@today AS datetime)) ELSE '2027-01-01' END;
-- 现象「料带变形开裂、没法贴片」在剥净后的比对范围里找，应用层做。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @start AND p.AddDate < @end AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'Q80');
