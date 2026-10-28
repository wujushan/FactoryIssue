-- 案例：OS-003
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT d.PO, d.OrderNumber, d.Date, d.PN, np.Name AS PnName,
       d.DeliveryVersion, d.ProdVersion, d.Quantity, d.Remark
FROM CoreINFO.dbo.OverseasProblem_DeliveryOrder AS d
INNER JOIN CoreINFO.dbo.OverseasProblemDetail AS p ON p.Id = d.ProblemId
LEFT JOIN info.dbo.NewProduct AS np ON np.PartNumber = d.PN
WHERE p.Numbers = 'HW2511002'
  AND p.IsDelete = 0
ORDER BY d.OrderNumber;

SELECT SUM(d.Quantity) AS QtySum
FROM CoreINFO.dbo.OverseasProblem_DeliveryOrder AS d
INNER JOIN CoreINFO.dbo.OverseasProblemDetail AS p ON p.Id = d.ProblemId
WHERE p.Numbers = 'HW2511002'
  AND p.IsDelete = 0;
-- 序号不在这里取。找不到 PN 名称时只展示编码。
