-- 案例：CN-057
-- 数据源：info
-- 只读。不写结果行数。另一个实例上的名称对照在应用层做，本文件不连过去。
-- 对应断言：docs/testcases/golden/cases.json 里同编号的 expect

-- 算的说法：打印、打印机、打印头、热敏头、走纸、卡纸、胶辊、缺纸。带歧义的纸仓另判。
-- 不算：打印标签、标签打印、打印模板、打印机盖、打印机支架、打印机组件、打印机开关、纸仓盖。
-- 负样本单号：ZC2608022、ZC2603053、ZC2509019、ZC2508019、ZC2507009。
SELECT p.Numbers
FROM CoreINFO.dbo.ZCTracking_ProblemList AS p
WHERE (p.IsDelete = 0 OR p.IsDelete IS NULL);
