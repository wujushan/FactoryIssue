-- 案例：CN-041
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 剥净后的问题描述同时含「打印」和「USB」。不对富文本原列做匹配。
SELECT p.Numbers, p.ProblemDesc
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL);
