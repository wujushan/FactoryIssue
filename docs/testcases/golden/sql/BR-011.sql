-- 案例：BR-011
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.OrderNumber, r.PartNumber
FROM CoreINFO.dbo.BrazilProblemList AS p
LEFT JOIN CoreINFO.dbo.BrazilProblemPO AS po ON po.ProblemID = p.ID
LEFT JOIN info.dbo.Brazil_RequestList AS r ON r.ID = po.RequestID
WHERE p.OrderNumber = 'BR2605006' AND p.Status <> -1;
-- PartNumber 为 0 或 '0' 的不展示。全部如此则 PN 显示未填。
