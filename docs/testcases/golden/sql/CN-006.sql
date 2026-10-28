-- 案例：CN-006
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = '2026-01-01';
DECLARE @end datetime = CASE WHEN @today < '2027-01-01'
    THEN DATEADD(day, 1, CAST(@today AS datetime)) ELSE '2027-01-01' END;
SELECT p.Numbers, p.StopStatus, p.StopDate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.IsStop = 1
  AND p.StopDate >= @start AND p.StopDate < @end
  AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'L1400');
-- 停线日期为空、是否停线为是的张数另计，写明不计入。
-- 重启日期：Step＝29 中 ID 最大的一条，结论里的日期。解析在应用层。
