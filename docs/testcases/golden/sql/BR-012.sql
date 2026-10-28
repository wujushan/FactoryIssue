-- 案例：BR-012
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT TOP (1) x.IsStockPrecess, x.StockPrecessQty
FROM CoreINFO.dbo.BrazilProblemProcess AS x
INNER JOIN CoreINFO.dbo.BrazilProblemList AS p ON p.ID = x.ProblemID
WHERE p.OrderNumber = 'BR2608004' AND p.Status <> -1
ORDER BY x.ID DESC;
-- 5Why 没有查询。回答说明暂不提供。
