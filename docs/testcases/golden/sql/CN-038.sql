-- 案例：CN-038
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 说法：换料、更换物料、替换物料。
-- 比对栏：改善建议、改善措施、预防对策，以及环节 3、4、6、10、11、13、14、35 每个环节最新一条。
-- 问题描述不进入前一组。第三组最多 10 张。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL);
