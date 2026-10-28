-- 案例：CN-012
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 结构化范围：国内、未删除、机型完整名称 A960。
-- 说法（屏幕显示话题，不含带歧义标记的「显示」）：
-- 屏幕、显示屏、LCD、液晶、花屏、白屏、黑屏、闪屏、背光、坏点、亮线、暗线。
-- 剥净后再匹配，在应用层做。复核单 ZC2604021 应在最终清单里。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'A960'
);
