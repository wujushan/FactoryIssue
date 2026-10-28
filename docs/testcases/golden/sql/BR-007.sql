-- 案例：BR-007
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = DATETIMEFROMPARTS(YEAR(@today), 1, 1, 0, 0, 0, 0);
DECLARE @end datetime = DATEADD(day, 1, CAST(@today AS datetime));

SELECT
    CASE
        WHEN p.ProblemType IS NULL OR LTRIM(RTRIM(p.ProblemType)) = N'' THEN N'未填'
        WHEN p.ProblemType = N'其他' OR p.ProblemType LIKE N'其他|%' THEN N'其他'
        ELSE p.ProblemType
    END AS TypeName,
    COUNT(*) AS Cnt
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1
  AND p.AddDate >= @start
  AND p.AddDate < @end
GROUP BY
    CASE
        WHEN p.ProblemType IS NULL OR LTRIM(RTRIM(p.ProblemType)) = N'' THEN N'未填'
        WHEN p.ProblemType = N'其他' OR p.ProblemType LIKE N'其他|%' THEN N'其他'
        ELSE p.ProblemType
    END;
