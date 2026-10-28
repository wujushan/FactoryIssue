-- 案例：OS-007
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT DISTINCT p.Factory2
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0 AND p.Factory2 IS NOT NULL AND LTRIM(RTRIM(p.Factory2)) <> '';
-- Factory2 是国内工厂码，名称在应用层对。空的不列出。
