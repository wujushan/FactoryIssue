-- 案例：XC-006
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 国内：机型子表，名称归一后按机型计单。巴西 ProductIDAll、海外 ProductType 是大机型 ID，
-- 逐段对产品主数据后按同一套名称规则合并。拆段在应用层。前 10 也在应用层。
SELECT UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) AS NormName, COUNT(DISTINCT p.ID) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
INNER JOIN CoreINFO.dbo.ZCTracking_ProductNames AS n ON n.ProblemId = p.ID
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01'
GROUP BY UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N''));
SELECT p.ID, p.ProductIDAll
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1 AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01';
SELECT p.Id, p.ProductType
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0 AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01';
