-- 案例：CN-048
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, N'生产订单' AS HitKind, o.OrderNumber
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
INNER JOIN CoreINFO.dbo.ZCTracking_ProblemOrders AS o ON o.ProblemId = p.ID
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND o.OrderNumber = N'230939'
UNION ALL
SELECT p.Numbers, N'小板订单', x.OrderNumber
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
INNER JOIN CoreINFO.dbo.ZCTracking_XBOrders AS x ON x.ProblemId = p.ID
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND x.OrderNumber = N'230939';
-- 同一问题编号两边都命中时仍是一单一行，订单明细合并展示。不查其他在线订单、退货单号。
