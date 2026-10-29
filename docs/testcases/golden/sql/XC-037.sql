-- 案例：XC-037
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 「最近」＝近 30 天，含运行日往前共 30 个日期。起止日期随运行日变，不写死。
-- 国内、机型对库后显示 A920Pro、软件问题。不把窗口改成近 90 天再出数。
-- 2026-10-29 实测这次没有符合条件的单，应用层不出表。有单时清单仍给默认列。
DECLARE @today date = CAST(SYSDATETIME() AS date);
DECLARE @start datetime = DATEADD(day, -29, CAST(@today AS datetime));
DECLARE @end datetime = DATEADD(day, 1, CAST(@today AS datetime));

SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND p.ProblemType = 2
  AND p.AddDate >= @start
  AND p.AddDate < @end
  AND EXISTS (
      SELECT 1
      FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
      WHERE n.ProblemId = p.ID
        AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'A920PRO'
  );
