-- 案例：CN-026
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 窗口 [2026-01-01, 2026-04-01)。简称「工程部」→ 部门名称「生产工程部」。
-- 名称对上的部门 ID 都算。AllReDepartment 按逗号逐段精确等于这些 ID，物料问题排除。
SELECT p.Numbers, p.AllReDepartment
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.ProblemType <> 3
  AND p.AddDate >= '2026-01-01'
  AND p.AddDate < '2026-04-01'
  AND EXISTS (
      SELECT 1
      FROM info.dbo.Department AS d
      WHERE d.Name = N'生产工程部'
        AND (',' + REPLACE(ISNULL(p.AllReDepartment, ''), ' ', '') + ',')
            LIKE '%,' + CAST(d.ID AS varchar(20)) + ',%'
  );
