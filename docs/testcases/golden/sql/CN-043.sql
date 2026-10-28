-- 案例：CN-043
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, N'料号' AS HitAt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.CInvCode = N'200209010001203'
UNION ALL
SELECT p.Numbers, N'PN'
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
INNER JOIN CoreINFO.dbo.ZCTracking_ProblemOrders AS o ON o.ProblemId = p.ID
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND o.PartNumber = N'200209010001203';
