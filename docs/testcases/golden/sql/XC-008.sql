-- 案例：XC-008
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 全集定义。展示多少张、是否导出，按总述「回答怎么组织」，不在这里截断。
SELECT N'国内' AS DomainName, p.Numbers, p.AddDate
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
UNION ALL
SELECT N'巴西', p.OrderNumber, p.AddDate
FROM CoreINFO.dbo.BrazilProblemList AS p
WHERE p.Status <> -1
UNION ALL
SELECT N'海外', p.Numbers, p.AddDate
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.IsDelete = 0;
