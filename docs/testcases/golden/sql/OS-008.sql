-- 案例：OS-008
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, p.Rate
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0;
-- Rate 原样展示。不参与加减乘除。
