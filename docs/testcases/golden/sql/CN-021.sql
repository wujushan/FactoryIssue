-- 案例：CN-021
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 建单时间 [2025-01-01, 2026-01-01)；机型完整名称等于 A920。
-- 责任人：硬件/软件/结构/制程优化→环节 3；物料→10；资料→4；工厂制程→6。
-- 同一环节最新一条：操作时间最晚，同一时间取后录入（ID 较大）。
-- 结案后改过问题分类时改按原问题类型取，该分支无真实样本，不在本 SQL 里分叉。
SELECT p.Numbers, p.ProblemType, p.AddDate, owner.AddUser
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
OUTER APPLY (
    SELECT TOP (1) s.AddUser
    FROM CoreINFO.dbo.ZCTracking_ProblemSteplog AS s
    WHERE s.ProblemId = p.ID
      AND s.Step = CASE p.ProblemType
            WHEN 1 THEN 3 WHEN 2 THEN 3 WHEN 6 THEN 3 WHEN 7 THEN 3
            WHEN 3 THEN 10 WHEN 4 THEN 4 WHEN 5 THEN 6
          END
    ORDER BY s.AddDate DESC, s.ID DESC
) AS owner
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.AddDate >= '2025-01-01'
  AND p.AddDate < '2026-01-01'
  AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'A920'
);
