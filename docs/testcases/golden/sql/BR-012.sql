-- 案例：BR-012
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 两轮：① BR2405005 这张单处理得怎么样了？→ 打开这张单
-- ② 这单的 5Why 和库存处理数量是什么？→ 下面是最新一条处理过程。
-- 5Why 没有查询。回答说明「5Why分析过程」暂不提供，请到管理页面查看。
-- IsStockPrecess＝是 时给出 StockPrecessQty；为否或空时不给。不锁数量。
SELECT TOP (1) x.IsStockPrecess, x.StockPrecessQty
FROM CoreINFO.dbo.BrazilProblemProcess AS x
INNER JOIN CoreINFO.dbo.BrazilProblemList AS p ON p.ID = x.ProblemID
WHERE p.OrderNumber = 'BR2405005' AND p.Status <> -1
ORDER BY x.ID DESC;
