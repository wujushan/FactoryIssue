-- 案例：OS-002
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 已选现象原文在应用层按海外主表的 JSON 规则展平。
-- 可能问题原因按现象主数据取每个标准现象下的候选，不读主表原因分析。
SELECT p.Numbers, p.hasCheckedPhenomenon, p.MemberListName, p.Status
FROM CoreINFO.dbo.OverseasProblemDetail AS p
WHERE p.Numbers = 'HW2512001'
  AND p.IsDelete = 0;
