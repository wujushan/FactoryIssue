-- 案例：CN-019
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 说法：磁卡、磁条、磁头、刷磁、刷卡。不含 IC卡、芯片卡、PSAM、SAM卡。
-- 剥净后按说法所在栏目分三组，应用层做。截止建单时间 < 2026-07-01，机型 A920PRO。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate < '2026-07-01' AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'A920PRO');
