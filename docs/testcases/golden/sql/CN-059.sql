-- 案例：CN-059
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 未删除集合里没有这一号。已删除的行只用来确认「查不到」，不返回给用户。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE p.Numbers = N'ZC2608038' AND (p.IsDelete = 0 OR p.IsDelete IS NULL);
