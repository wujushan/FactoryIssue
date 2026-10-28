-- 案例：OS-006
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @end datetime = DATEADD(day, 1, CAST(@today AS datetime));
-- 2024-01-01 至运行日（含当天）。
SELECT p.Factory,
       COUNT(*) AS Cnt,
       SUM(CASE WHEN p.Status <> 32 THEN 1 ELSE 0 END) AS OpenCnt
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0 AND p.AddDate >= '2024-01-01' AND p.AddDate < @end
GROUP BY p.Factory;
