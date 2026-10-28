-- 案例：CN-018
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, p.AllReDepartment
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.ProblemType <> 3
  AND p.AddDate < '2026-07-01'
  AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'A800')
  AND EXISTS (
      SELECT 1 FROM info.dbo.Department AS d
      WHERE d.Name = N'研发一部'
        AND (',' + REPLACE(ISNULL(p.AllReDepartment, ''), ' ', '') + ',')
            LIKE '%,' + CAST(d.ID AS varchar(20)) + ',%'
  );
