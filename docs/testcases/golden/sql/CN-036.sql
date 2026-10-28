-- 案例：CN-036
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 只负责把姓名对到员工。当前责任人按国内「当前状态」各行人员现算（含并行阶段、IQC、退货 / 退库），
-- 不在这一条 SQL 里复刻。对上零个：请用户核对姓名。对上多个：追问部门。
SELECT e.ID, e.Name
FROM info.dbo.Employee AS e
WHERE e.Name = N'马万军';
