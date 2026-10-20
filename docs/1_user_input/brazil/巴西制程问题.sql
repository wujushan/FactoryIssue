select distinct a.fID,a.frecID,a.fUserID,b.Name as fUserName,a.ftable,a.fstat,
                    case when a.fwhenDone is null then -1 else datediff(day,a.fwhenCreate,a.fwhenDone) end as EfficiencyValue
                    into #tempTask 
                    from info.dbo.tbTask a with(nolock)
                    inner join info.dbo.Employee b with(nolock) on a.fUserID=b.ID
                    where a.ftable in (
                        'BrazilProblemEditType','BrazilProblemProcess','BrazilProblemDesignChange','BrazilProblemSQE',
                        'BrazilProblemConfirm','BrazilProblemFinish','BrazilProblemSupplement','BrazilProblemStockPrecess'
                    ) 
                    and a.fstat in ('已接受','已完成')

                    select ProblemID,sum(isnull(CostMoney,0)) as CostMoneyTotal,sum(isnull(CostBrlMoney,0)) as CostBrlMoneyTotal
                    into #tempCost
                    from CoreINFO.dbo.BrazilProblemCost a
                    group by ProblemID

                    select a.ID,a.OrderNumber,a.ClaimNumber,a.BrazilFactory,a.ProductIDAll,
                    a.ProblemType,a.IsStopLine,a.StopDate,a.StopStatus,a.ProblemClass,a.ProblemPhenomenon,a.ProblemLevel,
                    a.ProblemDiscoveryDate,a.ProblemDiscoveryStation,a.StatisticsDate,a.cInvCode,a.cVenCode,a.ImpactQty,a.BadQty,
                    case a.ImpactQty when 0 then 0 else cast(a.BadQty as decimal)/a.ImpactQty end as BadOrder,
                    format(case a.ImpactQty when 0 then 0 else cast(a.BadQty as decimal)/a.ImpactQty end, 'P') as BadRate,
                    a.ProblemDesc,a.IsRequire8D,a.IsSupplement,a.IsCost,a.ActorUserID,
                    a.SupplementQty,a.SupplementResult,a.SupplementMemo,a.SupplementUserID,a.SupplementDate,
                    a.Memo,a.AddUserID,a.AddDate,a.UpdateUserID,a.UpdateDate,isnull(a.MailCount,0) as MailCount,a.Status,
                    case a.Status 
                    when '0' then '待提交' 
                    when '10' then '待修改类别' 
                    when '20' then '待跟进' 
                    when '25' then '待设计更改' 
                    when '26' then '待SQE确认' 
                    when '30' then '待效果确认' 
                    when '40' then '待结案' 
                    when '50' then '已结案' 
                    when '-2' then '已终止'
                    when '-1' then '已删除'
                    else '' end as StatusName,
                    Year(a.AddDate) as YearValue,
                    b.Name as AddUserName,d.ID as UnitID,d.Name as UnitName,
                    c.Name as UpdateUserName,
                    e.Name as SupplementUserName,
                    f.Name as ActorUserName,
                    h.cInvName,h.cInvStd,i.cInvCName,j.fname as cVenName,
                    isnull(k.CostMoneyTotal,0) as CostMoneyTotal,isnull(k.CostBrlMoneyTotal,0) as CostBrlMoneyTotal,
                    isnull(stuff((
						select distinct ','+b.ProductName
						from info.dbo.f_split(a.ProductIDAll,',') a
						inner join info.dbo.ProductName b on a.col=b.ID
						for xml path('')
					),1,1,''),'') as ProductNameAll,
                    isnull(stuff((
						select distinct ','+b.Series
						from info.dbo.f_split(a.ProductIDAll,',') a
						inner join info.dbo.ProductName b on a.col=b.ID
						for xml path('')
					),1,1,''),'') as SeriesAll                    
                    into #tempList
                    from coreinfo.dbo.BrazilProblemList a
                    left join info.dbo.Employee b on a.AddUserID=b.ID
                    left join info.dbo.Department d on b.Unit=d.ID
                    left join info.dbo.employee c on a.UpdateUserID=c.ID
                    left join info.dbo.employee e on a.SupplementUserID=e.ID
                    left join info.dbo.employee f on a.ActorUserID=f.ID
                    left join info.dbo.Inventory h on a.cInvCode=h.cInvCode
                    left join temperp.UFDATA_999_2021.dbo.InventoryClass i on h.cInvCCode=i.cInvCCode
                    left join info.dbo.tbIQCvendor j on isnull(a.cVenCode,'')=j.ferpcode and isnull(j.ferpcode,'')<>''
                    left join #tempCost k on a.ID=k.ProblemID
                    where a.Status<>-1 --and a.ClaimNumber like '%CLAIM-138/25%'  
					
					SELECT row_number() over(order by AddDate Desc,ID desc) RowNum,*
                        into #tempTable
                        from #tempList
                        order by AddDate Desc,ID
						
						select * 
                        into #tempTable2
                        from #tempTable
                        where RowNum between 1 and 20
                    
                        select a.*,                        
					    case when a.Status=-2 then '' else isnull(stuff((
                            select distinct ','+c2.Name
					        from #tempTask a2
					        cross apply info.dbo.f_split(a2.fUserID,',') b2
					        inner join info.dbo.Employee c2 on b2.col=cast(c2.ID as varchar)
					        where a2.frecID=cast(a.ID as varchar) and a2.fstat in ('已接受')
                            and a2.ftable not in ('BrazilProblemSupplement','BrazilProblemStockPrecess') 
					        for xml path('')
                        ),1,1,''),'') end as CurrentOperator,
                        case when a.Status in (0,10,20,30,40) and (a.AddUserID='4001' or 1004=4001) THEN '1' ELSE '0' END IsShowEdit,
                        case when a.Status in (0) and (a.AddUserID='4001' or 1004=4001) THEN '1' ELSE '0' END IsShowDel,
                        case when a.Status in (10,20,30,40) and (a.AddUserID='4001' or 1004=4001) THEN '1' ELSE '0' END IsShowStop,
                        case when a.Status in (10)
                        and ((
                            select count(0) from #tempTask 
                            where (fUserID='4001' or 1004=4001) and frecID=cast(a.ID as varchar) 
                            and ftable in ('BrazilProblemEditType') and fstat in ('已接受')
                        )>0) THEN '1' ELSE '0' END IsShowEditType,
                        case when a.Status in (20)
                        and ((
                            select count(0) from #tempTask 
                            where (fUserID='4001' or 1004=4001) and frecID=cast(a.ID as varchar) 
                            and ftable in ('BrazilProblemProcess') and fstat in ('已接受')
                        )>0) THEN '1' ELSE '0' END IsShowProcess,
                        case when a.Status in (25)
                        and ((
                            select count(0) from #tempTask 
                            where (fUserID='4001' or 1004=4001) and frecID=cast(a.ID as varchar) 
                            and ftable in ('BrazilProblemDesignChange') and fstat in ('已接受')
                        )>0) THEN '1' ELSE '0' END IsShowDesignChange,

                        case when a.Status in (26)
                        and ((
                            select count(0) from #tempTask 
                            where (fUserID='4001' or 1004=4001) and frecID=cast(a.ID as varchar) 
                            and ftable in ('BrazilProblemSQE') and fstat in ('已接受')
                        )>0) THEN '1' ELSE '0' END IsShowSQE,
                        case when a.Status in (30)
                        and ((
                            select count(0) from #tempTask 
                            where (fUserID='4001' or 1004=4001) and frecID=cast(a.ID as varchar) 
                            and ftable in ('BrazilProblemConfirm') and fstat in ('已接受')
                        )>0) THEN '1' ELSE '0' END IsShowConfirm,
                        case when a.Status in (40)
                        and ((
                            select count(0) from #tempTask 
                            where (fUserID='4001' or 1004=4001) and frecID=cast(a.ID as varchar) 
                            and ftable in ('BrazilProblemFinish') and fstat in ('已接受')
                        )>0) THEN '1' ELSE '0' END IsShowFinish,
                        case when ((
                            select count(0) from #tempTask 
                            where (fUserID='4001' or 1004=4001) and frecID=cast(a.ID as varchar) 
                            and ftable in ('BrazilProblemSupplement') and fstat in ('已接受')
                        )>0) THEN '1' ELSE '0' END IsShowSupplement,
                        case when ((
                            select count(0) from #tempTask 
                            where (fUserID='4001' or 1004=4001) and frecID=cast(a.ID as varchar) 
                            and ftable in ('BrazilProblemStockPrecess') and fstat in ('已接受')
                        )>0) THEN '1' ELSE '0' END IsShowStockPrecess,
                        case when a.Status in (10,20,30,40) and isnull(a.StopStatus,'')='停线中' and (a.AddUserID='4001' or 1004=4001) THEN '1' ELSE '0' END IsShowRestart,
                        case when a.Status in (30,40)
                        and ((
                            select count(0)
                            from coreinfo.dbo.BrazilProblemProcess a2
                            inner join (
                                select ProblemID,Max(ID) as MaxProblemProcessID from coreinfo.dbo.BrazilProblemProcess group by ProblemID
                            ) b2 on a2.ID=b2.MaxProblemProcessID
                            where a2.ProblemID=a.ID and a2.IsCostShift='是' and isnull(a2.DebitMoney,0)=0
                        )>0) THEN '1' ELSE '0' END IsShowDebit,
                        case when a.Status in (10,20,25,26,30,40) THEN '1' ELSE '0' END IsShowUrge,
                        isnull((select Max(ID) from coreinfo.dbo.BrazilProblemProcess where ProblemID=a.ID),0) as ProblemProcessID,
                        isnull((
                            select top 1 EfficiencyValue 
                            from #tempTask where frecID=cast(a.ID as varchar) and ftable='BrazilProblemProcess' and fstat in ('已完成') 
                            order by fID desc
                        ),-1) as EfficiencyValue
                        from #tempTable2 a                        
						order by RowNum  select count(1) as total from #tempTable
                        drop table #tempList
                        drop table #tempTable
                        drop table #tempTable2
                        drop table #tempTask
                        drop table #tempCost