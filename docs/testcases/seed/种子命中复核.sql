-- 种子命中复核（只读）
-- 用途：复核 v0.4「应命中集v0」里从国内种子案例回填的 9 条事实。
-- 规则：只 SELECT，不改数据；在测试镜像执行；结果填回工作簿「种子复核」页。
-- 判定：单号存在、未删除（IsDelete 为 0 或空）、且「命中」列为 1，才算复核通过。
-- 未通过时不要改单号，先记录：是单被删了、还是文字改了、还是归组变了。

-- 1) CN-019 磁卡与 IC 卡：ZC2208016、ZC2204045、ZC2112027
SELECT p.Numbers, p.IsDelete, p.ProblemType, p.AddDate,
       CASE WHEN (
            p.ProblemDesc LIKE N'%磁卡%' OR p.ProblemDesc LIKE N'%磁条%' OR p.ProblemDesc LIKE N'%磁头%'
         OR p.ProblemDesc LIKE N'%刷磁%' OR p.ProblemDesc LIKE N'%刷卡%' OR p.ProblemDesc LIKE N'%IC卡%'
         OR p.Reason LIKE N'%磁卡%' OR p.Reason LIKE N'%磁条%' OR p.Reason LIKE N'%磁头%'
         OR p.Reason LIKE N'%刷卡%' OR p.Reason LIKE N'%IC卡%'
         OR EXISTS (SELECT 1 FROM CoreINFO.dbo.ZCTracking_ProblemSteplog s
                    WHERE s.ProblemId = p.ID
                      AND (s.Opinon LIKE N'%磁卡%' OR s.Opinon LIKE N'%磁条%' OR s.Opinon LIKE N'%磁头%'
                        OR s.Opinon LIKE N'%刷卡%' OR s.Opinon LIKE N'%IC卡%'
                        OR s.Measures LIKE N'%磁卡%' OR s.Measures LIKE N'%磁条%' OR s.Measures LIKE N'%磁头%'
                        OR s.Measures LIKE N'%刷卡%' OR s.Measures LIKE N'%IC卡%'))
       ) THEN 1 ELSE 0 END AS 命中
FROM CoreINFO.dbo.ZCTracking_ProblemList p
WHERE p.Numbers IN (N'ZC2208016', N'ZC2204045', N'ZC2112027')
ORDER BY p.Numbers;

-- 2) CN-020 电池与充电：ZC2512023、ZC2511025
SELECT p.Numbers, p.IsDelete,
       CASE WHEN (
            p.ProblemDesc LIKE N'%电池%' OR p.ProblemDesc LIKE N'%电芯%' OR p.ProblemDesc LIKE N'%充电%'
         OR p.ProblemDesc LIKE N'%续航%' OR p.ProblemDesc LIKE N'%电量%' OR p.ProblemDesc LIKE N'%鼓包%'
         OR p.ProblemDesc LIKE N'%卡扣%'
         OR p.Reason LIKE N'%电池%' OR p.Reason LIKE N'%充电%' OR p.Reason LIKE N'%鼓包%'
         OR p.Reason LIKE N'%卡扣%'
         OR EXISTS (SELECT 1 FROM CoreINFO.dbo.ZCTracking_ProblemSteplog s
                    WHERE s.ProblemId = p.ID
                      AND (s.Opinon LIKE N'%电池%' OR s.Opinon LIKE N'%充电%' OR s.Opinon LIKE N'%鼓包%'
                        OR s.Opinon LIKE N'%卡扣%'
                        OR s.Measures LIKE N'%电池%' OR s.Measures LIKE N'%充电%' OR s.Measures LIKE N'%鼓包%'
                        OR s.Measures LIKE N'%卡扣%'))
       ) THEN 1 ELSE 0 END AS 命中
FROM CoreINFO.dbo.ZCTracking_ProblemList p
WHERE p.Numbers IN (N'ZC2512023', N'ZC2511025')
ORDER BY p.Numbers;

-- 3) CN-013 电池与充电（电量虚高）：ZC2507021
SELECT p.Numbers, p.IsDelete,
       CASE WHEN (p.ProblemDesc LIKE N'%电量%' OR p.ProblemDesc LIKE N'%虚高%' OR p.ProblemDesc LIKE N'%煲机%'
               OR p.Reason LIKE N'%电量%' OR p.Reason LIKE N'%虚高%')
            THEN 1 ELSE 0 END AS 命中
FROM CoreINFO.dbo.ZCTracking_ProblemList p
WHERE p.Numbers = N'ZC2507021';

-- 4) CN-012 屏幕显示（A960 煲机屏幕异常）：ZC2604021
SELECT p.Numbers, p.IsDelete,
       CASE WHEN (p.ProblemDesc LIKE N'%屏幕%' OR p.ProblemDesc LIKE N'%显示屏%' OR p.ProblemDesc LIKE N'%LCD%'
               OR p.ProblemDesc LIKE N'%花屏%' OR p.ProblemDesc LIKE N'%白屏%' OR p.ProblemDesc LIKE N'%黑屏%'
               OR p.ProblemDesc LIKE N'%闪屏%' OR p.ProblemDesc LIKE N'%背光%'
               OR p.Reason LIKE N'%屏幕%' OR p.Reason LIKE N'%显示%')
            THEN 1 ELSE 0 END AS 命中
FROM CoreINFO.dbo.ZCTracking_ProblemList p
WHERE p.Numbers = N'ZC2604021';

-- 5) CN-023 通信（A800 eSIM）：ZC2511032、ZC2509039
SELECT p.Numbers, p.IsDelete,
       CASE WHEN (p.ProblemDesc LIKE N'%eSIM%' OR p.ProblemDesc LIKE N'%ESIM%' OR p.ProblemDesc LIKE N'%SIM卡%'
               OR p.Reason LIKE N'%eSIM%' OR p.Reason LIKE N'%ESIM%' OR p.Reason LIKE N'%SIM卡%'
               OR EXISTS (SELECT 1 FROM CoreINFO.dbo.ZCTracking_ProblemSteplog s
                          WHERE s.ProblemId = p.ID
                            AND (s.Opinon LIKE N'%eSIM%' OR s.Opinon LIKE N'%ESIM%' OR s.Opinon LIKE N'%SIM卡%'
                              OR s.Measures LIKE N'%eSIM%' OR s.Measures LIKE N'%ESIM%' OR s.Measures LIKE N'%SIM卡%')))
            THEN 1 ELSE 0 END AS 命中
FROM CoreINFO.dbo.ZCTracking_ProblemList p
WHERE p.Numbers IN (N'ZC2511032', N'ZC2509039')
ORDER BY p.Numbers;

-- 6) CN-020 外壳与结构（电池卡扣）：ZC2512023、ZC2511025
SELECT p.Numbers, p.IsDelete,
       CASE WHEN (p.ProblemDesc LIKE N'%卡扣%' OR p.ProblemDesc LIKE N'%外壳%' OR p.ProblemDesc LIKE N'%壳体%'
               OR p.ProblemDesc LIKE N'%面壳%' OR p.ProblemDesc LIKE N'%底壳%' OR p.ProblemDesc LIKE N'%开裂%'
               OR p.Reason LIKE N'%卡扣%' OR p.Reason LIKE N'%外壳%' OR p.Reason LIKE N'%开裂%')
            THEN 1 ELSE 0 END AS 命中
FROM CoreINFO.dbo.ZCTracking_ProblemList p
WHERE p.Numbers IN (N'ZC2512023', N'ZC2511025')
ORDER BY p.Numbers;

-- 7) CN-007 类似问题（PCB 油墨凸起）：ZC2507029、ZC2412024
SELECT p.Numbers, p.IsDelete,
       CASE WHEN (p.ProblemDesc LIKE N'%油墨%' OR p.ProblemDesc LIKE N'%凸起%' OR p.ProblemDesc LIKE N'%PCB%'
               OR p.Reason LIKE N'%油墨%' OR p.Reason LIKE N'%凸起%'
               OR EXISTS (SELECT 1 FROM CoreINFO.dbo.ZCTracking_ProblemSteplog s
                          WHERE s.ProblemId = p.ID
                            AND (s.Opinon LIKE N'%油墨%' OR s.Opinon LIKE N'%凸起%'
                              OR s.Measures LIKE N'%油墨%' OR s.Measures LIKE N'%凸起%')))
            THEN 1 ELSE 0 END AS 命中
FROM CoreINFO.dbo.ZCTracking_ProblemList p
WHERE p.Numbers IN (N'ZC2507029', N'ZC2412024')
ORDER BY p.Numbers;

-- 8) CN-008 类似问题（Q80 料带变形）：ZC2606037
SELECT p.Numbers, p.IsDelete,
       CASE WHEN (p.ProblemDesc LIKE N'%料带%' OR p.ProblemDesc LIKE N'%变形%' OR p.ProblemDesc LIKE N'%开裂%'
               OR p.ProblemDesc LIKE N'%贴片%'
               OR p.Reason LIKE N'%料带%' OR p.Reason LIKE N'%变形%')
            THEN 1 ELSE 0 END AS 命中
FROM CoreINFO.dbo.ZCTracking_ProblemList p
WHERE p.Numbers = N'ZC2606037';

-- 9) CN-009 原因检索（IM30 IMEI 重复）：ZC2510027
SELECT p.Numbers, p.IsDelete,
       CASE WHEN (p.ProblemDesc LIKE N'%IMEI%' OR p.ProblemDesc LIKE N'%重复%'
               OR p.Reason LIKE N'%IMEI%' OR p.Reason LIKE N'%重复%'
               OR EXISTS (SELECT 1 FROM CoreINFO.dbo.ZCTracking_ProblemSteplog s
                          WHERE s.ProblemId = p.ID
                            AND (s.Opinon LIKE N'%IMEI%' OR s.Opinon LIKE N'%重复%'
                              OR s.Measures LIKE N'%IMEI%' OR s.Measures LIKE N'%重复%')))
            THEN 1 ELSE 0 END AS 命中
FROM CoreINFO.dbo.ZCTracking_ProblemList p
WHERE p.Numbers = N'ZC2510027';
