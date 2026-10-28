-- 案例：BR-004
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = '2026-01-01';
DECLARE @end datetime = CASE
    WHEN @today < '2027-01-01' THEN DATEADD(day, 1, CAST(@today AS datetime))
    ELSE '2027-01-01' END;

WITH fee AS (
    SELECT c.ProblemID,
           SUM(ISNULL(c.CostMoney, 0)) AS Usd,
           SUM(ISNULL(c.CostBrlMoney, 0)) AS Brl
    FROM CoreINFO.dbo.BrazilProblemCost AS c
    GROUP BY c.ProblemID
),
picked AS (
    SELECT p.ID, fee.Usd, fee.Brl
    FROM CoreINFO.dbo.BrazilProblemList AS p
    INNER JOIN fee ON fee.ProblemID = p.ID
    WHERE p.Status <> -1
      AND p.AddDate >= @start
      AND p.AddDate < @end
      AND (fee.Usd > 0 OR fee.Brl > 0)
)
SELECT
    COUNT(*) AS IssueCnt,
    SUM(picked.Usd) AS UsdSum,
    SUM(picked.Brl) AS BrlSum,
    SUM(ISNULL(latest.DebitMoney, 0)) AS DebitSum
FROM picked
OUTER APPLY (
    SELECT TOP (1) x.DebitMoney
    FROM CoreINFO.dbo.BrazilProblemProcess AS x
    WHERE x.ProblemID = picked.ID
    ORDER BY x.ID DESC
) AS latest;
