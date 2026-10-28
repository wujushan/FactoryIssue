-- 案例：OS-001
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.Numbers, p.ProblemLevel
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0
  AND p.ProblemLevel = 'A+';
-- 0 行：正文写「目前没有登记为 A+ 的单」。有行：展示的等级只能是 A+。
