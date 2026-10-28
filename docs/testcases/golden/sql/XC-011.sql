-- 案例：XC-011
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT e.ID, e.Name
FROM info.dbo.Employee AS e
WHERE e.Name = N'李飞';
-- 多于一个 ID 则本轮追问部门，不查问题单。
