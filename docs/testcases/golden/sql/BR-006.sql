-- 案例：BR-006
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.OrderNumber, p.ProductIDAll
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1
  AND (',' + REPLACE(ISNULL(p.BrazilFactory, ''), ' ', '') + ',') LIKE '%,CA,%';
-- ProductIDAll 逐段对 info.dbo.ProductName，名称去重后展示。拆段在应用层。
