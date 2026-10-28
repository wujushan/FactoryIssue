-- 案例：XC-005
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, p.Status
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.Numbers = N'ZC2609012';
SELECT p.OrderNumber, p.Status
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1 AND p.OrderNumber = 'BR2608005';
