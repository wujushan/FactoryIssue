-- 案例：CN-052
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT
    CASE WHEN p.ProblemLevel IS NULL OR LTRIM(RTRIM(p.ProblemLevel)) = N'' THEN N'未填'
         ELSE p.ProblemLevel END AS LevelName,
    COUNT(*) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= '2026-01-01' AND p.AddDate < '2026-07-01'
GROUP BY CASE WHEN p.ProblemLevel IS NULL OR LTRIM(RTRIM(p.ProblemLevel)) = N'' THEN N'未填'
              ELSE p.ProblemLevel END;
-- 只返回有单的等级。这次是 A、B、C。A+、未填没有单，不补 0，不要求出现在表里。
