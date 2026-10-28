-- 案例：CN-046
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @thisMonth date = DATEFROMPARTS(YEAR(@today), MONTH(@today), 1);
DECLARE @prevMonth date = DATEADD(month, -1, @thisMonth);
SELECT p.Numbers, p.AddDate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.AddDate >= @prevMonth AND p.AddDate < @thisMonth
ORDER BY p.AddDate DESC;
-- 展示取最近 20 张。文件里的问题描述是剥净后的全文。
