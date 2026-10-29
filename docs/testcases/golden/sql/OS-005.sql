-- 案例：OS-005
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- Status＝32 已完成。IQCOpinion＝2 退回仓库。ProblemType＝3 物料问题。
SELECT p.Numbers, p.Status, p.IQCOpinion, p.ProblemType
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0 AND p.Status = 32 AND p.IQCOpinion = 2 AND p.ProblemType = 3;
-- 2026-10-29 实库这次没有符合条件的单。应用层照实说没有查到，不出表。
-- 没给时间，统计口径写不限建单时间。筛选条件：已完成、退回仓库、物料问题。只查海外。
