-- 案例：CN-029
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 工厂码以国内工厂主数据当时的同名码为准。2026-10-24 落盘：柯洱斯 04 与 06，亮亮 05，惠州百富 09。
-- 码有增减时改这一段，不要把两个实例连在一条 SQL 里。
-- GROUP BY 不会变出 0。应用层把缺的那家补成 0。
SELECT
    CASE p.Factory WHEN '04' THEN N'柯洱斯' WHEN '06' THEN N'柯洱斯'
                   WHEN '05' THEN N'亮亮' WHEN '09' THEN N'惠州百富' END AS FactoryName,
    COUNT(*) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= '2026-01-01'
  AND p.AddDate < '2026-07-01'
  AND p.Factory IN ('04', '06', '05', '09')
GROUP BY CASE p.Factory WHEN '04' THEN N'柯洱斯' WHEN '06' THEN N'柯洱斯'
                        WHEN '05' THEN N'亮亮' WHEN '09' THEN N'惠州百富' END;
