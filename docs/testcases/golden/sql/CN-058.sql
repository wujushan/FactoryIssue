-- 案例：CN-058
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 只比对改善措施 Measures。剥净后按词，并按意思补充。
SELECT p.Numbers, p.Measures
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL);
