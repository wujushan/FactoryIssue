-- 案例：CN-009
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 结构化范围：国内、未删除、机型完整名称 IM30。
-- 问的是一次具体现象（入库、IMEI 号重复）。剥净图片和格式后再在比对范围里找，
-- 这一步在应用层做，不在这里对富文本列做 LIKE。
-- 可能问题原因是候选清单，不参与「当时分析的原因」。
-- 候选集合大于最终答案。复核单 ZC2510027 应落在最终答案里。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL)
  AND EXISTS (
    SELECT 1
    FROM CoreINFO.dbo.ZCTracking_ProductNames AS n
    WHERE n.ProblemId = p.ID
      AND UPPER(REPLACE(REPLACE(REPLACE(n.ProductName, N' ', N''), N'-', N''), N'_', N'')) = N'IM30'
);
