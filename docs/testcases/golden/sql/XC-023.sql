-- 案例：XC-023
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @thisMonth date = DATEFROMPARTS(YEAR(@today), MONTH(@today), 1);
DECLARE @prevMonth date = DATEADD(month, -1, @thisMonth);
DECLARE @tomorrow datetime = DATEADD(day, 1, CAST(@today AS datetime));
SELECT N'国内' AS DomainName,
       SUM(CASE WHEN p.AddDate >= @prevMonth AND p.AddDate < @thisMonth THEN 1 ELSE 0 END) AS PrevCnt,
       SUM(CASE WHEN p.AddDate >= @thisMonth AND p.AddDate < @tomorrow THEN 1 ELSE 0 END) AS ThisCnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
UNION ALL
SELECT N'巴西',
       SUM(CASE WHEN p.AddDate >= @prevMonth AND p.AddDate < @thisMonth THEN 1 ELSE 0 END),
       SUM(CASE WHEN p.AddDate >= @thisMonth AND p.AddDate < @tomorrow THEN 1 ELSE 0 END)
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1
UNION ALL
SELECT N'海外',
       SUM(CASE WHEN p.AddDate >= @prevMonth AND p.AddDate < @thisMonth THEN 1 ELSE 0 END),
       SUM(CASE WHEN p.AddDate >= @thisMonth AND p.AddDate < @tomorrow THEN 1 ELSE 0 END)
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0;
-- 本月合计大于上月合计时，再按问题类型算增减。否则不列分类。
