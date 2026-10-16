select * from (select ROW_NUMBER() over(order by a.adddate desc ) rownum,CASE a.ProblemType WHEN '1' THEN '硬件问题' WHEN '2' THEN '软件问题' WHEN '3' THEN '物料问题' WHEN '4' THEN '其他' WHEN '6' THEN '结构问题' WHEN '7' THEN '制程优化' ELSE '工厂制程' END ProblemTypeStr,a.ID,a.Numbers ,a.Factory ,a.Factory2 ,a.AddUser,e.Name  as AddUserName ,a.FoundDate ,
stuff((select ',' + pn.ProductName from info.dbo.ProductName pn where ',' + a.ProductType + ',' like('%,' + cast(pn.ID as varchar) + ',%') for xml path('')),1,1,'') ProductName,
a.ProductType  ,a.ProblemLevel ,a.ImpactQty ,a.BadQty ,a.Rate ,ProblemType ,a.ProblemDesc ,a.InvInfo  ,a.StopState ,a.Status ,a.MemberList,a.MemberListName 
from OverseasProblemDetail a
left join info.dbo.Employee e on a.AddUser = e.ID
left join (SELECT ProblemId as iProblemId, STUFF(',', 1, 0, (SELECT ',' + b2.MemberList FROM OverseasProblem_StepLog b2 WHERE b2.ProblemId=b1.ProblemId FOR XML PATH(''))) AS iMemberList
FROM OverseasProblem_StepLog b1 GROUP BY ProblemId) l on a.id=l.iProblemId
where IsDelete=0  --and  Numbers like N'%HW2512001%'
) t2 where t2.rownum between 1 and 20