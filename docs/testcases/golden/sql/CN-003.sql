-- 案例：CN-003
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 停线状态 1 停线中、4 重启审核中、5 重启审核通过、6 责任人填写重启方案。不按结案、不按建单时间收。
SELECT p.Numbers, p.StopStatus, p.StopDate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.StopStatus IN (1, 4, 5, 6);
