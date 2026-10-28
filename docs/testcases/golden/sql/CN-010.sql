-- 案例：CN-010
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 「去年」＝运行日所在年的上一个完整自然年。2026 年运行时即 2025。
DECLARE @year int = YEAR(SYSDATETIME()) - 1;
DECLARE @start datetime = DATETIMEFROMPARTS(@year, 1, 1, 0, 0, 0, 0);
DECLARE @end datetime = DATETIMEFROMPARTS(@year + 1, 1, 1, 0, 0, 0, 0);

SELECT p.ProblemType, COUNT(*) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= @start
  AND p.AddDate < @end
  AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'A6650'
)
GROUP BY p.ProblemType;
-- 占比＝Cnt / SUM(Cnt)。展示名：1 硬件问题，2 软件问题，3 物料问题，4 资料问题，5 工厂制程，6 结构问题，7 制程优化。
