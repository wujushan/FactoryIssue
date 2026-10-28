-- 案例：BR-001
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 工厂名去空格后，用逗号包起来再匹配整段 TT，避免依赖拆分函数。
SELECT p.OrderNumber, p.ProblemLevel, p.Status, p.ProblemType
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1
  AND p.AddDate >= '2024-07-01'
  AND p.AddDate < '2024-10-01'
  AND p.ProblemLevel = 'A'
  AND p.ProblemType = N'硬件问题'
  AND (',' + REPLACE(ISNULL(p.BrazilFactory, ''), ' ', '') + ',') LIKE '%,TT,%';
