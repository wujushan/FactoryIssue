-- 案例：CN-007
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 类似问题。候选是国内未删除的单。排序、最多 10 张、不保证完整，都在检索侧，不在这条 SQL 里截断。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL);
