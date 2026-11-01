-- 案例：XC-040
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 今年＝本年 1 月 1 日至今天，按建单时间，三域都查。按星期几分（周一至周日），
-- 1900-01-01 是星期一，用来算星期几，避免依赖 DATEFIRST（0＝周一 … 6＝周日）。
-- 固定统计没有这个维度，应用层走临时统计：数字由临时编写的脚本在取好的单上算，这里只给对照的口径。
-- 国内、海外已删除按 IsDelete 排除；巴西已删除＝-1 排除，待提交、已终止照计。
DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @yearStart date = DATEFROMPARTS(YEAR(@today), 1, 1);
DECLARE @tomorrow date = DATEADD(day, 1, @today);

SELECT x.Weekday0, COUNT(*) AS Cnt
FROM (
    SELECT DATEDIFF(day, 0, p.AddDate) % 7 AS Weekday0
    FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
    WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
      AND p.AddDate >= @yearStart AND p.AddDate < @tomorrow
    UNION ALL
    SELECT DATEDIFF(day, 0, p.AddDate) % 7
    FROM CoreINFO.dbo.BrazilProblemList AS p
    WHERE p.Status <> -1
      AND p.AddDate >= @yearStart AND p.AddDate < @tomorrow
    UNION ALL
    SELECT DATEDIFF(day, 0, p.AddDate) % 7
    FROM CoreINFO.dbo.OverseasProblemDetail AS p
    WHERE p.IsDelete = 0
      AND p.AddDate >= @yearStart AND p.AddDate < @tomorrow
) AS x
GROUP BY x.Weekday0
ORDER BY x.Weekday0;
