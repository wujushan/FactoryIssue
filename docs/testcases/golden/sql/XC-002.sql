-- 案例：XC-002
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = '2026-01-01';
DECLARE @end datetime = CASE
    WHEN @today < '2027-01-01' THEN DATEADD(day, 1, CAST(@today AS datetime))
    ELSE '2027-01-01' END;

SELECT N'国内' AS DomainName, p.ProblemType, COUNT(*) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @start AND p.AddDate < @end
GROUP BY p.ProblemType
UNION ALL
SELECT N'海外', p.ProblemType, COUNT(*)
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0 AND p.AddDate >= @start AND p.AddDate < @end
GROUP BY p.ProblemType
UNION ALL
SELECT N'巴西',
       CASE
           WHEN p.ProblemType IS NULL OR LTRIM(RTRIM(p.ProblemType)) = N'' THEN NULL
           WHEN p.ProblemType = N'其他' OR p.ProblemType LIKE N'其他|%' THEN N'其他'
           ELSE p.ProblemType
       END,
       COUNT(*)
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1 AND p.AddDate >= @start AND p.AddDate < @end
GROUP BY
       CASE
           WHEN p.ProblemType IS NULL OR LTRIM(RTRIM(p.ProblemType)) = N'' THEN NULL
           WHEN p.ProblemType = N'其他' OR p.ProblemType LIKE N'其他|%' THEN N'其他'
           ELSE p.ProblemType
       END;
-- 国内/海外整型要翻成人话后再同名相加。空类型→未填；海外 1–7 以外→其他（未识别）。
-- 某域没有的类型补「—」，有类型但本窗口为 0 补 0。这两格不由 GROUP BY 产生。
