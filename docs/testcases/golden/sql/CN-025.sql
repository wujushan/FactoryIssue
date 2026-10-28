-- 案例：CN-025
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 1 硬件问题，2 软件问题，6 结构问题。两年都按完整自然年，不截到今天。
SELECT YEAR(p.AddDate) AS Y, p.ProblemType, COUNT(*) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.ProblemType IN (1, 2, 6)
  AND p.AddDate >= '2024-01-01'
  AND p.AddDate < '2026-01-01'
GROUP BY YEAR(p.AddDate), p.ProblemType;
-- 增减量＝2025 张数 − 2024 张数。变化率以 2024 张数为分母；2024 为 0 时变化率写明无法计算，不除零。
