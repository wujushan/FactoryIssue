-- 案例：CN-053
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 两轮：① ZC2604012 这张单是什么情况？→ 打开这张单
-- ② 这张物料单为什么机型显示「物料」？它的影响数量怎么没有？→ 下面是这张单。
-- MHead＝物料 时，机型一栏显示「物料」，不展示产品在制属性与影响数量。
SELECT p.Numbers, p.MHead, p.ImpactQty, p.OutPutStatus
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE p.Numbers = N'ZC2604012' AND (p.IsDelete = 0 OR p.IsDelete IS NULL);
