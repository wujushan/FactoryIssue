-- 案例：XC-001
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @thisMonth date = DATEFROMPARTS(YEAR(@today), MONTH(@today), 1);
DECLARE @prevMonth date = DATEADD(month, -1, @thisMonth);

-- 国内：已完成＝32。海外：已完成＝32。巴西：已结案＝50；待提交＝0；已终止＝-2；已删除＝-1 排除。
SELECT N'国内' AS DomainName,
       SUM(CASE WHEN p.Status = 32 THEN 1 ELSE 0 END) AS ClosedCnt,
       SUM(CASE WHEN p.Status <> 32 THEN 1 ELSE 0 END) AS OpenCnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= @prevMonth AND p.AddDate < @thisMonth
UNION ALL
SELECT N'海外',
       SUM(CASE WHEN p.Status = 32 THEN 1 ELSE 0 END),
       SUM(CASE WHEN p.Status <> 32 THEN 1 ELSE 0 END)
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0
  AND p.AddDate >= @prevMonth AND p.AddDate < @thisMonth
UNION ALL
SELECT N'巴西',
       SUM(CASE WHEN p.Status = 50 THEN 1 ELSE 0 END),
       SUM(CASE WHEN p.Status IN (10, 20, 25, 26, 30, 40) THEN 1 ELSE 0 END)
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1
  AND p.AddDate >= @prevMonth AND p.AddDate < @thisMonth;

SELECT
    SUM(CASE WHEN p.Status = 0 THEN 1 ELSE 0 END) AS DraftCnt,
    SUM(CASE WHEN p.Status = -2 THEN 1 ELSE 0 END) AS StoppedCnt
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1
  AND p.AddDate >= @prevMonth AND p.AddDate < @thisMonth;
