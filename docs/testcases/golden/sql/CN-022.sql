-- 案例：CN-022
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 只定位这一张。原因、措施的哪几列给用户，见国内「原因与措施怎么给」，应用层组装。
SELECT p.Numbers, p.Reason, p.Measures, p.Prevention
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE p.Numbers = N'ZC2604018'
  AND (p.IsDelete = 0 OR p.IsDelete IS NULL);

SELECT s.Step, s.Opinon, s.Measures, s.AddDate
FROM CoreINFO.dbo.ZCTracking_ProblemSteplog AS s
INNER JOIN CoreINFO.dbo.ZCTracking_ProblemList AS p ON p.ID = s.ProblemId
WHERE p.Numbers = N'ZC2604018'
  AND (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND s.Step IN (3, 4, 6, 10, 11, 13, 14, 35);
-- 同一 Step 只留 ID 最大的一条后再展示。
