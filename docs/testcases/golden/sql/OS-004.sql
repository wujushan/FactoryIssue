-- 案例：OS-004
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, d.OrderNumber, d.Date, d.PN, d.Quantity
FROM CoreINFO.dbo.OverseasProblemDetail AS p
INNER JOIN CoreINFO.dbo.OverseasProblem_DeliveryOrder AS d ON d.ProblemId = p.Id
WHERE p.IsDelete = 0 AND d.OrderNumber = '2406648';
SELECT p.Numbers FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.Numbers = N'ZC2406648';
SELECT p.OrderNumber FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1 AND p.OrderNumber = 'BR2406648';
SELECT p.Numbers FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0 AND p.Numbers = 'HW2406648';
