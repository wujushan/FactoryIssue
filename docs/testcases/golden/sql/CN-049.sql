-- 案例：CN-049
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 前置轮打开 ZC2609017。操作记录：Step 不是 29、32、34。
SELECT s.AddUser, s.AddDate, s.Step, s.StepStr, s.Measures, s.Opinon, s.FileUrl
FROM CoreINFO.dbo.ZCTracking_ProblemSteplog AS s
INNER JOIN CoreINFO.dbo.ZCTracking_ProblemList AS p ON p.ID = s.ProblemId
WHERE p.Numbers = N'ZC2609017' AND (p.IsDelete = 0 OR p.IsDelete IS NULL) AND s.Step NOT IN (29, 32, 34)
ORDER BY s.ID;
SELECT COUNT(*) AS RejectCnt
FROM CoreINFO.dbo.ZCTracking_ProblemSteplog AS s
INNER JOIN CoreINFO.dbo.ZCTracking_ProblemList AS p ON p.ID = s.ProblemId
WHERE p.Numbers = N'ZC2609017' AND (p.IsDelete = 0 OR p.IsDelete IS NULL) AND s.Step = 28;
-- 重启操作日志另查 Step IN (29, 32, 34)，同样全部列出。
