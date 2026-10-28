-- 案例：CN-050
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, p.IsStop, p.StopStatus, p.StopDate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE p.Numbers = N'ZC2608015' AND (p.IsDelete = 0 OR p.IsDelete IS NULL);
-- 环节 29 最新一条的结论日期＝重启日期。环节 34 的意见＝重启方案。环节 32 的结论＝审核意见。
SELECT s.Step, s.Result, s.Opinon, s.AddDate
FROM CoreINFO.dbo.ZCTracking_ProblemSteplog AS s
INNER JOIN CoreINFO.dbo.ZCTracking_ProblemList AS p ON p.ID = s.ProblemId
WHERE p.Numbers = N'ZC2608015' AND (p.IsDelete = 0 OR p.IsDelete IS NULL) AND s.Step IN (29, 32, 34);
