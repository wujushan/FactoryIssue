-- 案例：CN-045
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, p.ProblemLevel
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.ProblemLevel = N'A+';
-- 文字一组按安全话题里不带歧义标记的说法，在应用层分三组。本查询只覆盖等级这一路。
