-- 案例：XC-022
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @thisMonth date = DATEFROMPARTS(YEAR(@today), MONTH(@today), 1);
DECLARE @prevMonth date = DATEADD(month, -1, @thisMonth);
-- 第一步的国内机型计数。巴西、海外大机型按名称并进来之后再取第一。
SELECT UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) AS NormName, COUNT(DISTINCT p.ID) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
INNER JOIN CoreINFO.dbo.ZCTracking_ProductNames AS n ON n.ProblemId = p.ID
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @prevMonth AND p.AddDate < @thisMonth
GROUP BY UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N''));
-- 第二步、第三步用第一步点名的机型再查。海外 Rate 先换成同一单位再取最大。
