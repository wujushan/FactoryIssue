-- 案例：XC-041
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 三轮：① 今年上半年国内惠州的三个工厂一共出了多少问题？→ 追问，「惠州」按国内加工厂的地区说法对到柯洱斯、亮亮、惠州百富
-- ② 惠州百富（点追问按钮）→ 只查惠州百富 ③ 那另外两个工厂呢？→ 惠州三家减去惠州百富，即柯洱斯、亮亮。
-- 下面是第 3 轮。工厂码照国内工厂表：柯洱斯 04、06（同名两个码），亮亮 05，惠州百富 09。
SELECT
    CASE p.Factory WHEN '04' THEN N'柯洱斯' WHEN '06' THEN N'柯洱斯' WHEN '05' THEN N'亮亮' END AS FactoryName,
    COUNT(*) AS Cnt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= DATEFROMPARTS(YEAR(SYSDATETIME()), 1, 1)
  AND p.AddDate < DATEFROMPARTS(YEAR(SYSDATETIME()), 7, 1)
  AND p.Factory IN ('04', '06', '05')
GROUP BY CASE p.Factory WHEN '04' THEN N'柯洱斯' WHEN '06' THEN N'柯洱斯' WHEN '05' THEN N'亮亮' END;
-- 合计就是本轮的张数。惠州百富（09）不计入；回答开头写明按柯洱斯、亮亮统计。
