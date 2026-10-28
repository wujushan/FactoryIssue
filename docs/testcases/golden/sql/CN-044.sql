-- 案例：CN-044
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 系列列归一后等于「底座」（末尾的「系列」二字不参与比较；本值本身不带）。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND EXISTS (
      SELECT 1 FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
      WHERE n.ProblemId = p.ID
        AND UPPER(REPLACE(REPLACE(REPLACE(n.Series, N' ', N''), N'-', N''), N'_', N'')) = N'底座'
  );
-- 「另有 N 张」按物料名称和文字另计，不并进上面这个集合。
