-- 案例：OS-009
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 不按 Series 筛选。若改按机型回答，大机型 ID 在 ProductType，名称在应用层对。
SELECT p.Numbers, p.ProductType, p.Series
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0;
