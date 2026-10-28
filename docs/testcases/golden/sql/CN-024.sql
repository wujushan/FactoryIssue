-- 案例：CN-024
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 窗口 [2026-01-01, 2026-07-01)。部门 ID 逐段拆开在应用层做（同实例拆分函数先不用）。
-- 物料问题 ProblemType＝3 整段排除，并单独计数写进统计口径。
SELECT p.Numbers, p.Status, p.AllReDepartment
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.ProblemType <> 3
  AND p.AddDate >= '2026-01-01'
  AND p.AddDate < '2026-07-01';
-- AllReDepartment 空：Status＝32 → 无需定责，否则 → 未定责。
-- 非空：逐段对 info.dbo.Department.ID，部门名称用 Department.Name。
