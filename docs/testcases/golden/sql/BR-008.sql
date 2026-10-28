-- 案例：BR-008
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

SELECT p.OrderNumber, latest.ProcessUserID
FROM CoreINFO.dbo.BrazilProblemList AS p
OUTER APPLY (
    SELECT TOP (1) x.ProcessUserID
    FROM CoreINFO.dbo.BrazilProblemProcess AS x
    WHERE x.ProblemID = p.ID
    ORDER BY x.ID DESC
) AS latest
WHERE p.OrderNumber = 'BR2510012' AND p.Status <> -1;
