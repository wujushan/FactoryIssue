-- 案例：CN-014
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 名称先按完整名称规则归一后再分组。前 10 与并列在应用层截。
SELECT UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) AS NormName, COUNT(DISTINCT p.ID) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
INNER JOIN CoreINFO.dbo.ZCTracking_ProductNames AS n ON n.ProblemId = p.ID
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01'
GROUP BY UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N''));
