-- 案例：CN-054
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT w.Question, w.Reason, w.Status, w.AddUser, w.AddDate, w.UpdateUser, w.UpdateDate
FROM CoreINFO.dbo.ZCTracking_ProblemFiveWhy AS w
INNER JOIN CoreINFO.dbo.ZCTracking_ProblemList AS p ON p.ID = w.ProblemId
WHERE p.Numbers = N'ZC2606010' AND (p.IsDelete = 0 OR p.IsDelete IS NULL)
ORDER BY w.ID;
-- Status＝0 显示待答复。人员 ID 翻成姓名。
