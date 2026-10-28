-- 案例：CN-053
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, p.MHead, p.ImpactQty, p.OutPutStatus
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE p.Numbers = N'ZC2604012' AND (p.IsDelete = 0 OR p.IsDelete IS NULL);
-- MHead＝物料 时，展示机型写「物料」，影响数量和产品在制属性不展示。
