-- 案例：CN-034
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @start datetime = '2026-09-01';
DECLARE @end datetime = '2026-10-01';

WITH closed AS (
    SELECT p.ID, p.AddDate, close_step.AddDate AS CloseAt
    FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
    CROSS APPLY (
        SELECT TOP (1) s.AddDate
        FROM CoreINFO.dbo.ZCTracking_ProblemSteplog AS s
        WHERE s.ProblemId = p.ID AND s.Step = 31
        ORDER BY s.ID DESC
    ) AS close_step
    WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
      AND p.Status = 32
      AND close_step.AddDate >= @start
      AND close_step.AddDate < @end
),
days AS (
    SELECT DATEDIFF(day, CAST(AddDate AS date), CAST(CloseAt AS date)) AS CycleDays
    FROM closed
)
SELECT
    AVG(CAST(bucket.CycleDays AS decimal(18, 4))) AS AvgDays,
    MIN(bucket.MedianDays) AS MedianDays,
    SUM(CASE WHEN bucket.CycleDays <= 30 THEN 1 ELSE 0 END) AS Within30,
    SUM(CASE WHEN bucket.CycleDays BETWEEN 31 AND 90 THEN 1 ELSE 0 END) AS D31To90,
    SUM(CASE WHEN bucket.CycleDays >= 91 THEN 1 ELSE 0 END) AS Over90
FROM (
    SELECT
        days.CycleDays,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days.CycleDays) OVER () AS MedianDays
    FROM days
) AS bucket;

-- 没有环节 31 的已完成单：没有结案时间，进不了 9 月这个窗口，张数要写明。
SELECT COUNT(*) AS MissingCloseStep
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.Status = 32
  AND NOT EXISTS (
      SELECT 1 FROM CoreINFO.dbo.ZCTracking_ProblemSteplog AS s
      WHERE s.ProblemId = p.ID AND s.Step = 31
  );
