-- 案例：CN-031
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = '2026-01-01';
DECLARE @end datetime = CASE WHEN @today < '2027-01-01'
    THEN DATEADD(day, 1, CAST(@today AS datetime)) ELSE '2027-01-01' END;
-- 工厂码：柯洱斯 04 与 06，亮亮 05，惠州百富 09（2026-10-24 落盘）。
-- 只返回有单的工厂。没有单的不补 0。这次范围内只有柯洱斯有单。
SELECT
    CASE p.Factory WHEN '04' THEN N'柯洱斯' WHEN '06' THEN N'柯洱斯'
                   WHEN '05' THEN N'亮亮' WHEN '09' THEN N'惠州百富' END AS FactoryName,
    COUNT(*) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
INNER JOIN info.dbo.tbIQCvendor AS v ON v.ferpcode = p.VenCode
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= @start AND p.AddDate < @end
  AND v.fname LIKE N'%高展光电%'
  AND p.Factory IN ('04', '06', '05', '09')
GROUP BY CASE p.Factory WHEN '04' THEN N'柯洱斯' WHEN '06' THEN N'柯洱斯'
                        WHEN '05' THEN N'亮亮' WHEN '09' THEN N'惠州百富' END;
