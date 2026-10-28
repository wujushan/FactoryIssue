-- 案例：XC-027
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @juneYear int = CASE WHEN MONTH(@today) >= 6 THEN YEAR(@today) ELSE YEAR(@today) - 1 END;
DECLARE @julyYear int = CASE WHEN MONTH(@today) >= 7 THEN YEAR(@today) ELSE YEAR(@today) - 1 END;
DECLARE @juneStart datetime = DATETIMEFROMPARTS(@juneYear, 6, 1, 0, 0, 0, 0);
DECLARE @julyStart datetime = DATETIMEFROMPARTS(@julyYear, 7, 1, 0, 0, 0, 0);
DECLARE @julyEnd datetime = DATEADD(month, 1, @julyStart);
-- 国内：已完成，建单在 6 月，环节 31 最新一条的操作时间在 7 月。
SELECT p.Numbers, close_step.AddDate AS CloseAt
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
CROSS APPLY (
    SELECT TOP (1) s.AddDate
    FROM CoreINFO.dbo.ZCTracking_ProblemSteplog AS s
    WHERE s.ProblemId = p.ID AND s.Step = 31
    ORDER BY s.ID DESC
) AS close_step
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.Status = 32
  AND p.AddDate >= @juneStart AND p.AddDate < DATEADD(month, 1, @juneStart)
  AND close_step.AddDate >= @julyStart AND close_step.AddDate < @julyEnd;
-- 海外同样用环节 31。巴西用已结案单最新一条处理过程的结案日期。没有结案时间的张数按域另计。
