-- 案例：CN-035
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = '2026-01-01';
DECLARE @end datetime = CASE WHEN @today < '2027-01-01'
    THEN DATEADD(day, 1, CAST(@today AS datetime)) ELSE '2027-01-01' END;
SELECT p.Numbers, p.StopDate, restart.Result AS RestartRaw
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
OUTER APPLY (
    SELECT TOP (1) s.Result
    FROM CoreINFO.dbo.ZCTracking_ProblemSteplog AS s
    WHERE s.ProblemId = p.ID AND s.Step = 29
    ORDER BY s.ID DESC
) AS restart
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL) AND p.IsStop = 1
  AND p.StopDate >= @start AND p.StopDate < @end;
-- RestartRaw 解析出日期后才参加平均。解析不出的算没重启，不计入时长。
