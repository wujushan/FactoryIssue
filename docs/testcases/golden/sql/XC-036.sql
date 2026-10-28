-- 案例：XC-036
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 按上一轮同样的条件重查：2026-06、国内、机型 A920PRO、软件问题。不因质疑改条件。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.ProblemType = 2
  AND p.AddDate >= '2026-06-01'
  AND p.AddDate < '2026-07-01'
  AND EXISTS (
      SELECT 1
      FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
      WHERE n.ProblemId = p.ID
        AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'A920PRO'
  );
