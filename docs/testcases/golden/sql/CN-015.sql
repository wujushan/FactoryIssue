-- 案例：CN-015
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, v.fname
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
INNER JOIN info.dbo.tbIQCvendor AS v ON v.ferpcode = p.VenCode
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.VenCode IS NOT NULL AND LTRIM(RTRIM(p.VenCode)) <> N''
  AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01'
  AND v.fname LIKE N'%普瑞特%';
