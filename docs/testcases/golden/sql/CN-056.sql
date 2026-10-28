-- 案例：CN-056
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 只认「漏电」这个说法，不认漏电流、电池电压低、待机耗电快。
-- 问题描述、现象、原因里的命中进待判断，不进前两组的硬命中。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL);
