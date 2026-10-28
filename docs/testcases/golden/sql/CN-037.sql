-- 案例：CN-037
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
INNER JOIN info.dbo.Department AS d ON d.ID = p.RDepartment
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND d.Name = N'生产工程部' AND p.ProblemType = 3;
-- 物料问题、工厂制程、资料问题不指定跟进部门。上面这句预期经常是 0 行，回答仍要说明未计入。
