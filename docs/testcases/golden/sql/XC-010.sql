-- 案例：XC-010
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 只查工厂名称，不出问题单。海外加工厂就存在单上。
SELECT DISTINCT p.Factory
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0 AND p.Factory LIKE N'%伊朗%';
-- 国内、巴西没有名称含「伊朗」的工厂时，回答写明未命中。国内工厂名称在另一个实例，应用层对。
