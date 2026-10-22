/*
 *所有关于ZCTracking_ProblemList类的业务代码应在此处编写
*可使用repository.调用常用方法，获取EF/Dapper等信息
*如果需要事务请使用repository.DbContextBeginTransaction
*也可使用DBServerProvider.手动获取数据库相关信息
*用户信息、权限、角色等使用UserContext.Current操作
*ZCTracking_ProblemListService对增、删、改查、导入、导出、审核业务代码扩展参照ServiceFunFilter
*/
using AutoMapper;
using iTextSharp.text.pdf;
using Microsoft.EntityFrameworkCore;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.NetworkInformation;
using System.Text;
using System.Threading.Tasks;
using VOL.Core.Configuration;
using VOL.Core.Const;
using VOL.Core.Dapper;
using VOL.Core.Enums;
using VOL.Core.Exceptions;
using VOL.Core.Extensions;
using VOL.Core.ManageUser;
using VOL.Core.Model.ZCTracking;
using VOL.Core.Models;
using VOL.Core.Models.AfterService.AfterProblemHanding;
using VOL.Core.Models.QualityManage.SampleManage;
using VOL.Core.Utilities;
using VOL.Entity.DomainModels;
using VOL.Entity.Dto;
using VOL.Entity.Dto.ZCTracking;
using VOL.Service.IServices;
using VOL.Service.IServices.ZCTracking.Partial;
using VOL.Service.Services.QualityManage.FiveWhy;
using VOL.Service.Services.ZCTracking.Partial;

namespace VOL.Service.Services
{
    public partial class ZCTracking_ProblemListService
    {
        private readonly IPilotProductStreamItemService _pilotProductStreamItemService = PilotProductStreamItemService.Instance;
        private readonly IHr_EmployeeService _hrEmployeeService = Hr_EmployeeService.Instance;
        private readonly IPub_TaskService _pubTaskService = Pub_TaskService.Instance;
        private readonly IZCTrackingService zCTrackingService = ZCTrackingService.Instance;
        private readonly IMailAddressService mailAddressService = MailAddressService.Instance;
        private readonly ISys_EmployeeAuthService sys_EmployeeAuthService = Sys_EmployeeAuthService.Instance;
        private readonly IZCTracking_ProductNamesService zCTracking_ProductNamesService = ZCTracking_ProductNamesService.Instance;
        private readonly IZCTracking_ProblemOrdersService zCTracking_ProblemOrdersService = ZCTracking_ProblemOrdersService.Instance;
        private readonly IZCTracking_ProblemSteplogService zCTracking_ProblemSteplogService = ZCTracking_ProblemSteplogService.Instance;
        private readonly IZCTracking_CKDProductService zCTracking_CKDProductService = ZCTracking_CKDProductService.Instance;
        private readonly IZCTracking_OnlineOrderService zCTracking_OnlineOrderService = ZCTracking_OnlineOrderService.Instance;
        private readonly IZCTracking_OtherOrderService zCTracking_OtherOrderService = ZCTracking_OtherOrderService.Instance;
        private readonly IZCTracking_StockService zCTracking_StockService = ZCTracking_StockService.Instance;
        private readonly IAfterSaleIssueClassService afterSaleIssueClassService = AfterSaleIssueClassService.Instance;
        private readonly IDocumentListService _documentListService = DocumentListService.Instance;
        private readonly IZCTracking_XBOrdersService zCTracking_XBOrdersService = ZCTracking_XBOrdersService.Instance;
        private readonly IZCTracking_PossibleInvCodeService zCTracking_PossibleInvCodeService = ZCTracking_PossibleInvCodeService.Instance;
        private readonly DapperHelper dapperHelperCoreInfo = DapperHelper.GetDapperWrite();
        private readonly DapperHelper dapperHelperInfo = DapperHelper.GetDapperInfo();
        private const string scbEmail = "Produce_Dept@paxsz.com";
        private const string streamNameRJ = "制程问题-软件、硬件问题";
        private const string streamNameZL = "制程问题-资料问题";
        private const string streamNameZC = "制程问题-工厂制程";
        public const string streamNameWL = "制程问题-物料问题";

        //停线责任人填写
        private const string stopRsUser = "ZCTracking_StopRsUser";
        //停线重启审核
        private const string stopRsUserExamine = "ZCTracking_StopRsUserExamine";
        /// <summary>
        /// 效果确认
        /// </summary>
        private const string xgfTable = "ZCTracking_ProblemSoftware3";
        /// <summary>
        /// 结案确认
        /// </summary>
        private const string jafTable = "ZCTracking_ProblemSoftware4";
        /// <summary>
        /// 结构问题预防对策确认（与效果确认并行）
        /// </summary>
        private const string preventionTable = "ZCTracking_PreventionConfirm";

        private const string cuijuan = "cuij@paxsz.com";
        #region 私有方法
        /// <summary>
        /// 停线抄送人
        /// 如果是在行的项目：项目经理；如果是结项项目：产品维护负责人。
        /// </summary>
        /// <param name="number"></param>
        /// <returns></returns>
        public async Task<string> GetStopCCMail(string number)
        {
            var sql = @$"SELECT CASE WHEN pp.ProjectStatus=1 THEN CONVERT(NVARCHAR(5),ppm.EmployeeID)  ELSE pmp.ResponsibleEmpID END Users
FROM CoreINFO.dbo.ZCTracking_ProblemList a
LEFT JOIN CoreINFO.dbo.ZCTracking_ProblemOrders b ON a.ID=b.ProblemId
LEFT JOIN dbo.NewProduct np ON b.PartNumber=np.PartNumber
LEFT JOIN dbo.Pro_ProjectInfo pp ON np.ProjectId=pp.ID
LEFT JOIN dbo.ProductName pn ON np.ProductID=pn.ID
LEFT JOIN dbo.ProductMaintainPerson pmp ON pn.ID=pmp.BigProID
LEFT JOIN Pro_ProjectMember ppm ON pp.ID=ppm.ProjectID AND ppm.RoleID=1 AND ppm.IsEnable=1
LEFT JOIN dbo.Employee ppme ON ppm.EmployeeID=ppme.ID AND ppme.status=1
WHERE a.Numbers='{number}' AND ppm.IsEnable=1 AND ppme.status=1";
            var list = await dapperHelperInfo.QueryAsync<string>(sql);
            if (list.Any())
            {
                var userIds = list.SelectMany(x => x.Split(",")).Distinct().ToList();
                return await _hrEmployeeService.GetEmailFromIDAsync(string.Join(",", userIds));
            }
            return "";
        }
        private async Task SendEmail(string sendMail, string toEmail, string ccMailList, string taskName, string context, string productIds = "")
        {
            //if (!string.IsNullOrWhiteSpace(productIds))
            //{
            //    if (await IsZLProd(productIds))
            //    {
            //        var zlEmail = await mailAddressService.GetMailAddress("国内制程涉及兆珑机型停线或重启通知");
            //        ccMailList += $";{zlEmail.MailTo}";
            //    }
            //}
            toEmail = string.Join(";", toEmail.Split(";").Distinct());
            ccMailList = string.Join(";", ccMailList.Split(";").Distinct());
            Mail.SendMailSMTPBeltGog(sendMail, UserContext.Current.UserName, toEmail, ccMailList, "", taskName, context, "2423", "制程问题追踪", "0", null);
        }
        private async Task SendEmail(string sendMail, string toEmail, string ccMailList, string taskName, string context, List<int> productIdList)
        {
            //if (productIdList.Any())
            //{
            //    var productIds = string.Join(",", productIdList);
            //    if (await IsZLProd(productIds))
            //    {
            //        var zlEmail = await mailAddressService.GetMailAddress("国内制程涉及兆珑机型停线或重启通知");
            //        ccMailList += $";{zlEmail.MailTo}";
            //    }
            //}
            toEmail = string.Join(";", toEmail.Split(";").Distinct());
            ccMailList = string.Join(";", ccMailList.Split(";").Distinct());
            Mail.SendMailSMTPBeltGog(sendMail, UserContext.Current.UserName, toEmail, ccMailList, "", taskName, context, "2423", "制程问题追踪", "0", null);
        }
        /// <summary>
        /// 是否兆珑机型
        /// </summary>
        /// <param name="productIds"></param>
        /// <returns></returns>
        public async Task<bool> IsZLProd(string productIds)
        {
            var i = await dapperHelperInfo.ExecuteScalarAsync<int>(
                   @$"SELECT count(*) FROM info.dbo.ProductNameZoLon WITH(NOLOCK) WHERE Ispax in (0,2,3) AND ProdID IN ({productIds})");
            return i > 0;
        }
        /// <summary>
        /// 获取对应问题类型的流程类型
        /// 1, "硬件问题" 2, "软件问题" 3, "物料问题" 4, "资料问题" 5, "工厂制程" 6, "结构问题" 7, "制程优化"
        /// </summary>
        /// <param name="probleType"></param>
        /// <returns></returns>
        public string GetfTable(int probleType)
        {
            switch (probleType)
            {
                case 1:
                case 2:
                case 6:
                case 7:
                    return "ZCTracking_ProblemSoftware"; //软、硬件问题
                case 3: return "ZCTracking_ProblemWL";//物料问题
                case 4: return "ZCTracking_ProblemZL";//资料问题
                case 5: return "ZCTracking_ProblemZC";//制程问题
                default:
                    return "";
            }
        }

        private static int GetInitStatus(int probleType)
        {
            switch (probleType)
            {
                case 1:
                case 2:
                case 6:
                    return (int)ZCTracking_ProblemStatusEnum.ResponsibleUser; //软、硬件问题
                case 3: return (int)ZCTracking_ProblemStatusEnum.IQCOpinion;//物料问题
                case 4: return (int)ZCTracking_ProblemStatusEnum.ConfirmVersion;//资料问题
                case 5: return (int)ZCTracking_ProblemStatusEnum.FactoryAnalysis;//制程问题
                case 7:
                    return (int)ZCTracking_ProblemStatusEnum.ProduceConfirm; //软、硬件问题
                default:
                    return 0;
            }
        }

        /// <summary>
        /// 获取编码
        /// </summary>
        /// <returns></returns>
        private async Task<string> GetNumbersByMonth()
        {
            var now = DateTime.Now;
            var begTime = new DateTime(now.Year, now.Month, 1);
            var endTime = begTime.AddMonths(1).AddSeconds(-1);
            var list = await repository.FindAsync(x => x.AddDate >= begTime && x.AddDate <= endTime);
            var last = list.OrderByDescending(x => x.AddDate).FirstOrDefault();
            var num = "";
            if (last == null || string.IsNullOrWhiteSpace(last.Numbers))
            {
                num = "0";
            }
            else
            {
                num = last.Numbers.Substring(last.Numbers.Length - 3, 3);
            }
            var result = int.Parse(num);
            if (result > 999)
            {
                throw new Exception("当月数据已超出999条");
            }
            return $"ZC{now:yyMM}" + (result + 1).ToString().PadLeft(3, '0');
        }

        /// <summary>
        /// 检测用户是否存在制程问题菜单浏览权限
        /// 不存在则自动添加权限
        /// </summary>
        /// <param name="userId"></param>
        /// <returns></returns>
        private async Task IsExistMenuAuth(int userId)
        {
            await sys_EmployeeAuthService.IsExistMenuAuthByMenuId(userId, 2517);
        }
        /// <summary>
        /// 
        /// </summary>
        /// <param name="problemType">1硬件问题，2软件问题，3物料问题，4资料问题，5工厂制程，6结构问题，7制程优化</param>
        /// <param name="venCode">供应商编码</param>
        /// <param name="orderNumberList">订单号</param>
        /// <param name="productIds">机型id</param>
        /// <returns></returns>
        private async Task<string> GetNewEmail(int problemType, string venCode, List<string> orderNumberList, List<int> productIds)
        {
            /*
            1、软件问题增加“杨维”
            2、物料问题：要有对应的SQE+IQC 
            3、所有问题：对应的销售、需求单填单人、产品维护人、产品维护人的部门经理、产品经理、导入工程师 
            4、固定人员：安旭东、谭明富、王瑞、刘银行、许进浩,
            5、新加固定人员王君
            6、针对一部的产品，且是硬件问题，统一抄送邓丽恒，毛慰，娄兵将，蔡辉
            7、工厂制程问题，填写人提交后请增加邮件抄送给程玉兰
            8、结构问题，邮件抄送林志华、朱琨

            2026年2月28日14:04:00    去除安旭东
             */
            var userIds = "1209,285,1235,517,3250,";
            if (problemType == 2)
            {
                userIds += "247,";
            }
            if (problemType == 3)
            {
                //iqc
                userIds += "624,3301,526,3218,";
                if (!string.IsNullOrWhiteSpace(venCode))
                {
                    var sqe = await zCTrackingService.GetSQEByVenCode(venCode);
                    if (!string.IsNullOrWhiteSpace(sqe))
                    {
                        userIds += sqe + ",";
                    }
                }
            }
            if (problemType == 7)
            {
                userIds += "5257,";//程玉兰
            }
            if (problemType == 6)
            {
                userIds += "1194,1867,";//林志华、朱琨
            }
            //需求单填单人和销售
            var sql = "";
            if (orderNumberList.Any())
            {
                var orderNumbers = string.Join(",", orderNumberList.Select(x => $"'{x}'"));
                sql = @$"SELECT r.AddUser [Key],c.OpID [Value] FROM coreinfo.dbo.Sale_RequestOrder r WITH(NOLOCK) 
    LEFT JOIN info.dbo.Client c ON c.ID=r.ClientID
    WHERE OrderNumber IN (
	SELECT o.RequestOrderNumber FROM coreinfo.dbo.MoOrder m WITH(NOLOCK)
	LEFT JOIN coreinfo.dbo.MoOrderSaleRequestOrder o WITH(NOLOCK) ON m.ID=o.MoOrderID
	WHERE m.OrderNumber IN ({orderNumbers}))";
                var requertOrderAddUserList = await dapperHelperCoreInfo.QueryAsync<SelectItem>(sql);
                if (requertOrderAddUserList.Any())
                {
                    userIds += string.Join(",", requertOrderAddUserList.Select(x => x.Key)) + ",";
                    userIds += string.Join(",", requertOrderAddUserList.Select(x => x.Value)) + ",";
                }
            }
            if (productIds.Any())
            {
                var productIdStr = string.Join(",", productIds);
                if (problemType == 1)
                {
                    //研发一部
                    var isRD1 = await dapperHelperInfo.ExecuteScalarAsync<int>(@$"SELECT COUNT(BigProID) FROM info.dbo.ProductMaintainPerson WHERE MaintainUnit='162' AND BigProID IN ({productIdStr})");
                    if (isRD1 > 0)
                    {
                        userIds += "898,2638,542,282,";
                    }
                }
                //产品维护人
                sql = @$"SELECT ResponsibleEmpID FROM info.dbo.ProductMaintainPerson a WITH(NOLOCK) WHERE a.ResponsibleEmpID IS NOT NULL and a.BigProID IN ({productIdStr})";
                var responsibleEmpList = await dapperHelperCoreInfo.QueryAsync<string>(sql);
                responsibleEmpList = responsibleEmpList.Where(x => !string.IsNullOrWhiteSpace(x)).ToList();
                if (responsibleEmpList.Any())
                {
                    userIds += string.Join(",", responsibleEmpList) + ",";
                }
                //产品维护人的部门经理
                sql = @$"SELECT e1.ID FROM info.dbo.ProductMaintainPerson a WITH(NOLOCK)
CROSS APPLY dbo.SplitStr(a.ResponsibleEmpID,',')b
LEFT JOIN info.dbo.Employee e WITH(NOLOCK) ON e.ID=b.F1
LEFT JOIN info.dbo.Department d WITH(NOLOCK) ON e.Unit=d.ID
LEFT JOIN info.dbo.Employee e1 WITH(NOLOCK) ON e1.ID=d.Lead
WHERE a.ResponsibleEmpID IS NOT NULL AND a.BigProID IN ({productIdStr})";
                var responsibleEmpLeadList = await dapperHelperCoreInfo.QueryAsync<string>(sql);
                responsibleEmpLeadList = responsibleEmpLeadList.Where(x => !string.IsNullOrWhiteSpace(x)).ToList();
                if (responsibleEmpLeadList.Any())
                {
                    userIds += string.Join(",", responsibleEmpLeadList) + ",";
                }
                //产品经理、导入工程师 
                sql = @$"SELECT Manage [Key],ImportEngineer [Value] FROM info.dbo.ProductName WITH(NOLOCK) WHERE ID IN ({productIdStr})";
                var productList = await dapperHelperCoreInfo.QueryAsync<SelectItem>(sql);
                userIds += string.Join(",", productList.Select(x => x.Key)) + ",";
                userIds += string.Join(",", productList.Select(x => x.Value)) + ",";
            }
            return await _hrEmployeeService.GetEmailFromIDAsync(userIds);
        }

        /// <summary>
        /// 硬件/软件/物料/资料/结构需要预防对策确认；制程优化、工厂制程不需要。
        /// </summary>
        private static bool NeedPreventionConfirm(int problemType)
        {
            return problemType == 1 || problemType == 2 || problemType == 3 || problemType == 4 || problemType == 6;
        }

        /// <summary>预防对策确认固定处理人：林志华（与结构问题抄送工号一致）。</summary>
        private const int PreventionUserLinZhiHua = 1194;
        /// <summary>预防对策确认固定处理人：娄兵将（与一部硬件问题抄送工号一致）。</summary>
        private const int PreventionUserLouBingJiang = 542;
        /// <summary>预防对策确认固定处理人：周登威。</summary>
        private const int PreventionUserZhouDengWei = 2165;
        /// <summary>预防对策确认固定处理人：刘银行（工号 1235）。</summary>
        private const int PreventionUserLiuYinHang = 1235;
        /// <summary>软件问题预防对策确认：基础软件部刘传（与客诉纠正预防措施确认工号一致）。</summary>
        private const int PreventionUserLiuChuan = 890;
        /// <summary>软件问题预防对策确认：研发二部刘志杰（与客诉纠正预防措施确认工号一致）。</summary>
        private const int PreventionUserLiuZhiJie = 1742;
        /// <summary>部门：研发一部。</summary>
        private const int PreventionMaintainUnitRd1 = 162;
        /// <summary>部门：研发二部。</summary>
        private const int PreventionMaintainUnitRd2 = 180;
        /// <summary>部门：生产工程部。</summary>
        private const int PreventionMaintainUnitProdEngineer = 167;

        /// <summary>
        /// 未匹配到指定处理人时，从流程配置读取预防对策确认默认处理人。
        /// 软件/硬件/结构：制程问题-软件、硬件问题 第6步；资料：制程问题-资料问题 第5步；物料：制程问题-物料问题 第9步。
        /// </summary>
        private async Task<int> GetDefaultPreventionUserIdAsync(int problemType)
        {
            string streamName;
            int stepId;
            switch (problemType)
            {
                case 4:
                    streamName = streamNameZL;
                    stepId = 5;
                    break;
                case 3:
                    streamName = streamNameWL;
                    stepId = 9;
                    break;
                default:
                    streamName = streamNameRJ;
                    stepId = 6;
                    break;
            }
            var userIds = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamName, stepId);
            var userId = userIds == null ? 0 : userIds.FirstOrDefault(x => x > 0);
            if (userId <= 0)
            {
                throw new BusinessException($"未在流程配置【{streamName}】第{stepId}步找到预防对策确认默认处理人");
            }
            return userId;
        }

        /// <summary>
        /// 解析逗号/分号分隔的工号，取第一个有效值。
        /// </summary>
        private static int ParseFirstUserId(string ids)
        {
            if (string.IsNullOrWhiteSpace(ids))
            {
                return 0;
            }
            foreach (var part in ids.Split(new[] { ',', ';' }, StringSplitOptions.RemoveEmptyEntries))
            {
                if (int.TryParse(part.Trim(), out var id) && id > 0)
                {
                    return id;
                }
            }
            return 0;
        }

        /// <summary>
        /// 软件问题：按「处理人」所属部门分派预防对策确认（基础软件部刘传、研发二部刘志杰）。
        /// </summary>
        private async Task<int> GetSoftwarePreventionUserIdAsync(ZCTracking_ProblemList problemInfo)
        {
            var handlerId = await GetStepLogAddUserAsync(problemInfo.ID, ZCTracking_ProblemOpeEnum.Confirm);
            if (handlerId <= 0)
            {
                handlerId = ParseFirstUserId(problemInfo.RUser);
            }
            if (handlerId <= 0)
            {
                handlerId = UserContext.Current.UserId;
            }
            var emp = await _hrEmployeeService.GetEmployeeByIdAsync(handlerId);
            if (emp == null)
            {
                return 0;
            }
            var deptName = await _hrEmployeeService.GetUnitNameByUnitIdZLAsync(emp.Unit);
            if (string.IsNullOrWhiteSpace(deptName))
            {
                return 0;
            }
            if (deptName.Contains("基础软件"))
            {
                return PreventionUserLiuChuan;
            }
            if (deptName.Contains("研发二部"))
            {
                return PreventionUserLiuZhiJie;
            }
            return 0;
        }

        /// <summary>
        /// 按维护部门 ID 映射固定处理人：研发一部娄兵将、研发二部周登威（硬件问题用，不含生产工程部）。
        /// </summary>
        private static int MapMaintainUnitToFixedUser(int maintainUnit)
        {
            if (maintainUnit == PreventionMaintainUnitRd1)
            {
                return PreventionUserLouBingJiang;
            }
            if (maintainUnit == PreventionMaintainUnitRd2)
            {
                return PreventionUserZhouDengWei;
            }
            return 0;
        }

        /// <summary>
        /// 资料问题：按工程确认处理人所属部门 ID 映射预防对策确认人。
        /// 研发一部娄兵将、研发二部周登威、生产工程部刘银行。
        /// </summary>
        private static int MapDataPreventionUnitToFixedUser(int unitId)
        {
            if (unitId == PreventionMaintainUnitRd1)
            {
                return PreventionUserLouBingJiang;
            }
            if (unitId == PreventionMaintainUnitRd2)
            {
                return PreventionUserZhouDengWei;
            }
            if (unitId == PreventionMaintainUnitProdEngineer)
            {
                return PreventionUserLiuYinHang;
            }
            return 0;
        }

        /// <summary>
        /// 按部门名称映射固定处理人：研发一部娄兵将、研发二部周登威；资料问题生产工程部给刘银行。
        /// </summary>
        private static int MapDeptNameToFixedUser(string deptName, bool includeEngineerDept)
        {
            if (string.IsNullOrWhiteSpace(deptName))
            {
                return 0;
            }
            if (deptName.Contains("研发一部"))
            {
                return PreventionUserLouBingJiang;
            }
            if (deptName.Contains("研发二部"))
            {
                return PreventionUserZhouDengWei;
            }
            // 资料问题：工程确认处理人在生产工程部时，预防对策确认给刘银行
            if (includeEngineerDept && deptName.Contains("生产工程"))
            {
                return PreventionUserLiuYinHang;
            }
            return 0;
        }

        /// <summary>
        /// 取步骤日志最近一次处理人。
        /// </summary>
        private async Task<int> GetStepLogAddUserAsync(int problemId, ZCTracking_ProblemOpeEnum step)
        {
            var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AsNoTracking()
                .Where(x => x.ProblemId == problemId && x.Step == step.GetEnumIntValue())
                .OrderByDescending(x => x.AddDate)
                .FirstOrDefaultAsync();
            return log?.AddUser ?? 0;
        }

        /// <summary>
        /// 取指定操作步骤最近一次处理人（实际操作人 AddUser；没有再取 MemberList）。
        /// 不能按 ProblemStatus 查：工程确认提交后日志状态已是效果确认，按状态 3 会命中填写问题、误给填单人。
        /// </summary>
        private async Task<int> GetStepOpeHandlerIdAsync(int problemId, ZCTracking_ProblemOpeEnum step)
        {
            var log = await zCTracking_ProblemSteplogService.GetStepLogByOpe(problemId, step);
            if (log == null)
            {
                return 0;
            }
            if (log.AddUser > 0)
            {
                return log.AddUser;
            }
            return ParseFirstUserId(log.MemberList);
        }

        /// <summary>
        /// 把驳回待办处理人写入 memberListName，供后续建任务与更新当前责任人。
        /// </summary>
        private async Task SetRejectHandlerAsync(SelectItem memberListName, int handlerId, string emptyMessage)
        {
            if (handlerId <= 0)
            {
                throw new BusinessException(emptyMessage);
            }
            memberListName.Key = handlerId.ToString();
            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
        }

        /// <summary>
        /// 硬件问题：按机型产品维护部门分派（研发一部娄兵将、研发二部周登威）。
        /// </summary>
        private async Task<int> GetHardwarePreventionUserIdAsync(string productIds)
        {
            if (string.IsNullOrWhiteSpace(productIds))
            {
                return 0;
            }
            var productIdList = productIds.Split(',').Select(x => x.Trim()).Where(x => int.TryParse(x, out _)).ToList();
            if (productIdList.Count == 0)
            {
                return 0;
            }
            var productIdStr = string.Join(",", productIdList);
            var units = await dapperHelperInfo.QuerySqlAsync<int>(
                $@"SELECT TOP 1 TRY_CAST(a.MaintainUnit AS int)
                    FROM dbo.ProductMaintainPerson a WITH(NOLOCK)
                    WHERE a.BigProID IN ({productIdStr}) AND TRY_CAST(a.MaintainUnit AS int) IS NOT NULL
                    ORDER BY a.BigProID",null);
            var maintainUnit = units != null && units.Count > 0 ? units[0] : 0;
            return MapMaintainUnitToFixedUser(maintainUnit);
        }

        /// <summary>
        /// 资料问题：预防对策确认给工程确认节点处理人所属部门的固定人员
        /// （研发一部娄兵将、研发二部周登威、生产工程部刘银行）。
        /// </summary>
        private async Task<int> GetDataPreventionUserIdAsync(int problemId)
        {
            var handlerId = await GetStepLogAddUserAsync(problemId, ZCTracking_ProblemOpeEnum.ConfirmVersion);
            if (handlerId <= 0)
            {
                handlerId = UserContext.Current.UserId;
            }
            var emp = await _hrEmployeeService.GetEmployeeByIdAsync(handlerId);
            if (emp == null)
            {
                return 0;
            }
            var byUnit = MapDataPreventionUnitToFixedUser(emp.Unit);
            if (byUnit > 0)
            {
                return byUnit;
            }
            var deptName = await _hrEmployeeService.GetUnitNameByUnitIdZLAsync(emp.Unit);
            return MapDeptNameToFixedUser(deptName, true);
        }

        /// <summary>
        /// 物料问题：SQE跟进节点对应的 SQE。
        /// </summary>
        private async Task<int> GetMaterialPreventionUserIdAsync(ZCTracking_ProblemList problemInfo)
        {
            var followLog = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AsNoTracking()
                .Where(x => x.ProblemId == problemInfo.ID && x.Step == ZCTracking_ProblemOpeEnum.FollowSQE.GetEnumIntValue())
                .OrderByDescending(x => x.AddDate)
                .FirstOrDefaultAsync();
            var userId = ParseFirstUserId(followLog?.MemberList);
            if (userId <= 0 && followLog != null)
            {
                userId = followLog.AddUser;
            }
            if (userId <= 0 && !string.IsNullOrWhiteSpace(problemInfo.VenCode))
            {
                userId = ParseFirstUserId(await zCTrackingService.GetSQEByVenCode(problemInfo.VenCode));
            }
            return userId;
        }

        /// <summary>
        /// 按问题类型解析预防对策确认处理人；匹配不到则按流程配置取默认处理人。
        /// </summary>
        private async Task<int> ResolvePreventionConfirmUserIdAsync(ZCTracking_ProblemList problemInfo, string productIds)
        {
            var userId = 0;
            switch (problemInfo.ProblemType)
            {
                case 6:
                    userId = PreventionUserLinZhiHua;
                    break;
                case 2:
                    userId = await GetSoftwarePreventionUserIdAsync(problemInfo);
                    break;
                case 1:
                    userId = await GetHardwarePreventionUserIdAsync(productIds);
                    break;
                case 4:
                    userId = await GetDataPreventionUserIdAsync(problemInfo.ID);
                    break;
                case 3:
                    userId = await GetMaterialPreventionUserIdAsync(problemInfo);
                    break;
            }
            if (userId <= 0)
            {
                userId = await GetDefaultPreventionUserIdAsync(problemInfo.ProblemType);
            }
            return userId;
        }

        /// <summary>
        /// 进入效果确认时并行发起预防对策确认待办；邮件/菜单权限失败不影响待办已创建。
        /// </summary>
        private async Task StartPreventionConfirmAsync(ZCTracking_ProblemList problemInfo, string productIds, string sendMail, string ccMailList)
        {
            if (problemInfo == null || !NeedPreventionConfirm(problemInfo.ProblemType))
            {
                return;
            }
            var pendingCount = await _pubTaskService.GetTaskCount(preventionTable, problemInfo.ID);
            if (pendingCount > 0)
            {
                return;
            }
            // 预防对策已办结则保留结果，效果确认驳回后再次进入并行节点不再重开
            if (await HasKeptPreventionConfirmResultAsync(problemInfo.ID))
            {
                return;
            }
            if (string.IsNullOrWhiteSpace(productIds))
            {
                var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(problemInfo.ID);
                productIds = string.Join(",", products.Select(x => x.ProductId));
            }
            var userId = await ResolvePreventionConfirmUserIdAsync(problemInfo, productIds);
            var now = DateTime.Now;
            var taskName = "国内制程问题单【" + problemInfo.Numbers + "】待预防对策确认";
            // 先建待办，避免发信或权限补录异常导致并行节点缺失
            await _pubTaskService.AddTaskAsync(preventionTable, problemInfo.ID, taskName, userId, now, now.AddDays(3));
            try
            {
                await IsExistMenuAuth(userId);
            }
            catch (Exception)
            {
                // 待办已创建
            }
            try
            {
                var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/PreventionConfirm?id={problemInfo.ID}'>点击进入该链接页面</a>";
                var context = await GetEmailHtml(problemInfo.ID, urlHtml);
                var email = await _hrEmployeeService.GetEmailFromIDAsync(userId.ToString());
                var managerCc = await GetDeptManagerEmailsByUserIdAsync(userId);
                await SendEmail(sendMail, email, managerCc, taskName, context, productIds);
            }
            catch (Exception)
            {
                // 待办已创建，通知失败不影响预防对策确认
            }
        }

        /// <summary>
        /// 是否仍有未完成的预防对策确认待办（不限当前登录人）。
        /// </summary>
        private async Task<bool> HasPendingPreventionConfirmTaskAsync(int problemId)
        {
            return await _pubTaskService.GetTaskCount(preventionTable, problemId) > 0;
        }

        /// <summary>
        /// 效果确认与预防对策确认（如需）均完成后进入结案确认；任一未完成或已在结案则不推进。
        /// </summary>
        private async Task<bool> TryEnterClosingConfirmAsync(ZCTracking_ProblemList problemInfo, DateTime now)
        {
            if (problemInfo == null)
            {
                return false;
            }
            if (problemInfo.Status == (int)ZCTracking_ProblemStatusEnum.End
                || problemInfo.Status == (int)ZCTracking_ProblemStatusEnum.ClosingConfirm)
            {
                return false;
            }
            if (await _pubTaskService.GetTaskCount(jafTable, problemInfo.ID) > 0)
            {
                return false;
            }
            if (await _pubTaskService.GetTaskCount(xgfTable, problemInfo.ID) > 0)
            {
                return false;
            }
            if (NeedPreventionConfirm(problemInfo.ProblemType) && await HasPendingPreventionConfirmTaskAsync(problemInfo.ID))
            {
                return false;
            }
            await EnterClosingConfirmAsync(problemInfo, now);
            return true;
        }

        /// <summary>
        /// 是否处于效果确认/预防对策确认并行阶段。
        /// </summary>
        private static bool IsParallelConfirmStatus(int status)
        {
            return status == (int)ZCTracking_ProblemStatusEnum.EffectConfirm
                || status == (int)ZCTracking_ProblemStatusEnum.EffectConfirmOnly
                || status == (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly;
        }

        /// <summary>
        /// 按效果确认、预防对策确认待办计算并行主状态：30 两者未完成，36 仅效果未完成，37 仅预防对策未完成。
        /// 不需要预防对策确认的类型保持 30。
        /// </summary>
        private async Task<int> ResolveParallelConfirmStatusAsync(int problemId, int problemType)
        {
            if (!NeedPreventionConfirm(problemType))
            {
                return (int)ZCTracking_ProblemStatusEnum.EffectConfirm;
            }
            var effectPending = await _pubTaskService.GetTaskCount(xgfTable, problemId) > 0;
            var preventionPending = await HasPendingPreventionConfirmTaskAsync(problemId);
            return ApplyParallelConfirmStatusOnView(
                problemType, (int)ZCTracking_ProblemStatusEnum.EffectConfirm, effectPending, preventionPending);
        }

        /// <summary>
        /// 写入并行阶段主状态；仅剩预防对策确认时清空效果确认处理人。
        /// </summary>
        private async Task PersistParallelConfirmStatusAsync(ZCTracking_ProblemList problemInfo)
        {
            var status = await ResolveParallelConfirmStatusAsync(problemInfo.ID, problemInfo.ProblemType);
            problemInfo.Status = status;
            if (status == (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly)
            {
                problemInfo.MemberList = "";
                problemInfo.MemberListName = "";
            }
            repository.Update(problemInfo, x => new { x.Status, x.MemberList, x.MemberListName, x.Confirmation, x.ConfirmUser, x.ConfirmDate });
            await repository.SaveChangesAsync();
        }

        /// <summary>
        /// 发起结案确认待办、更新主单状态并邮件通知结案处理人。
        /// </summary>
        private async Task EnterClosingConfirmAsync(ZCTracking_ProblemList problemInfo, DateTime now)
        {
            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(problemInfo.ID);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(problemInfo.ID);
            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;
            if (problemInfo.ProblemType == 3)
            {
                ccMailList += $";{cuijuan}";
            }
            var memberListName = new SelectItem();
            var status = (int)ZCTracking_ProblemStatusEnum.ClosingConfirm;
            var taskName = "国内制程问题单【" + problemInfo.Numbers + "】待结案确认";
            switch (problemInfo.ProblemType)
            {
                case 1:
                case 2:
                case 6:
                case 7:
                    memberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameRJ, 4);
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(jafTable, problemInfo.ID.ToString(), taskName, memberListName.Key.Split(",").Select(x => int.Parse(x)).ToList(), now, now.AddDays(3)));
                    break;
                case 3:
                    memberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameWL, 7);
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(jafTable, problemInfo.ID.ToString(), taskName, memberListName.Key.Split(",").Select(x => int.Parse(x)).ToList(), now, now.AddDays(3)));
                    break;
                case 4:
                    memberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameZL, 4);
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(jafTable, problemInfo.ID.ToString(), taskName, memberListName.Key.Split(",").Select(x => int.Parse(x)).ToList(), now, now.AddDays(3)));
                    break;
                case 5:
                    memberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameZC, 5);
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(jafTable, problemInfo.ID.ToString(), taskName, memberListName.Key.Split(",").Select(x => int.Parse(x)).ToList(), now, now.AddDays(3)));
                    break;
                default:
                    return;
            }
            repository.Update(new ZCTracking_ProblemList
            {
                ID = problemInfo.ID,
                MemberListName = memberListName.Value,
                MemberList = memberListName.Key,
                Confirmation = problemInfo.Confirmation,
                ConfirmUser = problemInfo.ConfirmUser,
                ConfirmDate = problemInfo.ConfirmDate,
                Status = status
            }, x => new { x.MemberListName, x.MemberList, x.Status, x.Confirmation, x.ConfirmUser, x.ConfirmDate });
            problemInfo.MemberListName = memberListName.Value;
            problemInfo.MemberList = memberListName.Key;
            problemInfo.Status = status;
            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var productIds = string.Join(',', productIdList);
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/EndConfirm?id={problemInfo.ID}'>点击进入该链接页面</a>";
            var context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ClosingConfirm);
            var email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
            if (!string.IsNullOrWhiteSpace(ccMailList))
            {
                ccMailList += ";" + newEmail;
            }
            else
            {
                ccMailList = newEmail;
            }
            await SendEmail(sendMail, email, ccMailList, taskName, context, productIds);
            await repository.SaveChangesAsync();
        }

        /// <summary>
        /// 组织架构上的主管/经理工号：小组主管、副主管（tbHRgroup.fmanager/fvmanager），以及部门经理、副经理（Department.Lead/vLead）。
        /// </summary>
        private const string PreventionOrgLeaderIdsSql = @"
SELECT TRY_CAST(LTRIM(RTRIM(s.Value)) AS int)
FROM dbo.tbHRgroup g WITH(NOLOCK)
CROSS APPLY dbo.Split(ISNULL(g.fmanager, N'') + N',' + ISNULL(g.fvmanager, N''), ',') s
WHERE ISNULL(g.fdeleted, 0) = 0 AND g.ftype = N'组'
AND TRY_CAST(LTRIM(RTRIM(s.Value)) AS int) > 0
UNION
SELECT TRY_CAST(d.Lead AS int)
FROM dbo.Department d WITH(NOLOCK)
WHERE TRY_CAST(d.Lead AS int) > 0
UNION
SELECT TRY_CAST(LTRIM(RTRIM(x.Value)) AS int)
FROM dbo.Department d WITH(NOLOCK)
CROSS APPLY dbo.Split(ISNULL(d.vLead, N''), ',') x
WHERE TRY_CAST(LTRIM(RTRIM(x.Value)) AS int) > 0
";

        /// <summary>
        /// 判断是否小组主管/副主管或部门经理/副经理（组织架构，不看职务名称）。
        /// </summary>
        private async Task<bool> IsSupervisorOrManagerAsync(int userId)
        {
            if (userId <= 0)
            {
                return false;
            }
            var count = await dapperHelperInfo.ExecuteScalarAsync<int>(
                $@"SELECT COUNT(1) FROM dbo.Employee e WITH(NOLOCK)
WHERE e.ID = @UserId AND ISNULL(e.status, 0) = 1
AND e.ID IN ({PreventionOrgLeaderIdsSql})",
                new { UserId = userId });
            return count > 0;
        }

        /// <summary>
        /// 处理人所在部门的全部经理邮箱（岗位含「经理」以及部门 Lead/vLead/Lead2），不含处理人本人。
        /// </summary>
        private async Task<string> GetDeptManagerEmailsByUserIdAsync(int userId)
        {
            if (userId <= 0)
            {
                return "";
            }
            var emp = await _hrEmployeeService.GetEmployeeByIdAsync(userId);
            if (emp == null || emp.Unit <= 0)
            {
                return "";
            }
            var ids = await dapperHelperInfo.QuerySqlAsync<int>(
                @"SELECT DISTINCT e.ID
                FROM dbo.Employee e WITH(NOLOCK)
                WHERE ISNULL(e.status, 0) = 1
                AND e.ID <> @UserId
                AND (
                    (e.Unit = @Unit AND e.zhiwu LIKE N'%经理%')
                    OR e.ID IN (
                        SELECT TRY_CAST(d.Lead AS int) FROM dbo.Department d WITH(NOLOCK) WHERE d.ID = @Unit
                        UNION
                        SELECT TRY_CAST(x.Value AS int)
                        FROM dbo.Department d WITH(NOLOCK)
                        CROSS APPLY dbo.Split(ISNULL(d.vLead, N''), ',') x
                        WHERE d.ID = @Unit
                        UNION
                        SELECT TRY_CAST(CAST(d.Lead2 AS varchar(20)) AS int) FROM dbo.Department d WITH(NOLOCK) WHERE d.ID = @Unit
                    )
                )",new { Unit = emp.Unit, UserId = userId });
            if (ids == null || ids.Count == 0)
            {
                return "";
            }
            return await _hrEmployeeService.GetEmailFromIDAsync(string.Join(",", ids.Where(x => x > 0).Distinct()));
        }

        /// <summary>
        /// 效果确认/预防对策确认驳回：退回责任人确认；取消未完成的并行待办，不清除已办结的效果确认结果与日志。
        /// </summary>
        private async Task RejectParallelConfirmToDutyManAsync(
            ProblemRejectDto dto,
            ZCTracking_ProblemList problemInfo,
            List<ZCTracking_ProductNames> products,
            List<ZCTracking_ProblemOrders> problemOrders,
            string sendMail,
            string ccMailList,
            string productIds,
            DateTime now)
        {
            await ApplyParallelRejectKeepRulesAsync(problemInfo, dto.ThisStatus);
            var problemLog = await zCTracking_ProblemSteplogService.GetStepLog(dto.ProblemId, ZCTracking_ProblemStatusEnum.Confirm)
                ?? await zCTracking_ProblemSteplogService.GetStepLogByOpe(dto.ProblemId, ZCTracking_ProblemOpeEnum.Confirm);
            if (problemLog == null)
            {
                throw new Exception("未找到责任人确认记录，无法驳回");
            }
            var memberKey = ParseFirstUserId(problemLog.MemberList);
            if (memberKey <= 0)
            {
                memberKey = ParseFirstUserId(problemInfo.RUser);
            }
            if (memberKey <= 0)
            {
                memberKey = problemLog.AddUser;
            }
            await IsExistMenuAuth(memberKey);
            var userName = await _hrEmployeeService.GetNameByIDAsync(memberKey.ToString());
            var taskName = "国内制程问题单【" + problemInfo.Numbers + "】待责任人确认";
            await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + "2", dto.ProblemId, taskName, memberKey, now, now.AddDays(3));
            problemInfo.Status = (int)ZCTracking_ProblemStatusEnum.Confirm;
            problemInfo.MemberList = memberKey.ToString();
            problemInfo.MemberListName = userName;
            repository.Update(problemInfo, x => new { x.Status, x.MemberList, x.MemberListName, x.Confirmation, x.ConfirmUser, x.ConfirmDate });
            await repository.SaveChangesAsync();
            var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/QualityDutyManConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
            var context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.Confirm, dto.Remark);
            var email = await _hrEmployeeService.GetEmailFromIDAsync(memberKey.ToString());
            await SendEmail(sendMail, email, ccMailList, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
        }

        /// <summary>
        /// 效果确认/预防对策确认驳回时，操作记录类型显示节点名称；Step 仍用驳回，避免详情页把驳回当成已通过的效果确认。
        /// </summary>
        private static (int Step, string StepStr) ResolveParallelRejectStepLog(int thisStatus)
        {
            if (thisStatus == (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly)
            {
                return ((int)ZCTracking_ProblemOpeEnum.Reject, "预防对策确认");
            }
            if (thisStatus == (int)ZCTracking_ProblemStatusEnum.EffectConfirm
                || thisStatus == (int)ZCTracking_ProblemStatusEnum.EffectConfirmOnly)
            {
                return ((int)ZCTracking_ProblemOpeEnum.Reject, "效果确认");
            }
            return ((int)ZCTracking_ProblemOpeEnum.Reject, "驳回");
        }

        /// <summary>
        /// 预防对策确认驳回只抄送当前操作人；其它节点驳回沿用原抄送名单。
        /// </summary>
        private static string BuildRejectCcMail(int thisStatus, string sendMail, string fullCcMail)
        {
            if (thisStatus == (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly)
            {
                return sendMail;
            }
            return fullCcMail;
        }

        /// <summary>
        /// 软硬件/结构（及制程优化的效果确认）从并行节点驳回时退到责任人确认。
        /// </summary>
        private static bool IsRejectParallelToDutyMan(int problemType, int thisStatus)
        {
            if (thisStatus != (int)ZCTracking_ProblemStatusEnum.EffectConfirm
                && thisStatus != (int)ZCTracking_ProblemStatusEnum.EffectConfirmOnly
                && thisStatus != (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly)
            {
                return false;
            }
            if (problemType == 1 || problemType == 2 || problemType == 6)
            {
                return true;
            }
            return problemType == 7 && thisStatus != (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly;
        }

        /// <summary>
        /// 作废已完成的预防对策确认待办，再次进入并行阶段时需重做。
        /// </summary>
        private async Task InvalidateCompletedPreventionTasksAsync(int problemId)
        {
            await dapperHelperInfo.ExecuteAsync(
                @"UPDATE info.dbo.tbTask SET fstat=N'已取消', fmemo=N'预防对策确认驳回', fwhendone=GETDATE()
WHERE ftable=@Table AND frecID=@RecId AND fstat=N'已完成'",
                new { Table = preventionTable, RecId = problemId.ToString() });
        }

        /// <summary>
        /// 作废未真正通过的效果确认待办（含误标已完成），避免再次进入时被当成已通过。
        /// </summary>
        private async Task InvalidateCompletedEffectTasksAsync(int problemId)
        {
            await dapperHelperInfo.ExecuteAsync(
                @"UPDATE info.dbo.tbTask SET fstat=N'已取消', fmemo=N'效果确认驳回', fwhendone=GETDATE()
WHERE ftable=@Table AND frecID=@RecId AND fstat=N'已完成'",
                new { Table = xgfTable, RecId = problemId.ToString() });
        }

        /// <summary>
        /// 并行节点驳回：一方已通过另一方驳回则保留通过方；否则两侧都要重做。
        /// </summary>
        private async Task ApplyParallelRejectKeepRulesAsync(ZCTracking_ProblemList problemInfo, int thisStatus)
        {
            var problemId = problemInfo.ID;
            var rejectPreventionOnly = thisStatus == (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly;
            var rejectEffectOnly = thisStatus == (int)ZCTracking_ProblemStatusEnum.EffectConfirmOnly;
            var rejectBothPending = thisStatus == (int)ZCTracking_ProblemStatusEnum.EffectConfirm;

            await _pubTaskService.CancelTaskAddMemo(preventionTable, problemId.ToString(), null, "驳回");
            await _pubTaskService.CancelTaskAddMemo(xgfTable, problemId.ToString(), null, "驳回");

            if (rejectPreventionOnly)
            {
                await InvalidateCompletedPreventionTasksAsync(problemId);
                return;
            }
            if (rejectEffectOnly)
            {
                await InvalidateCompletedEffectTasksAsync(problemId);
                ClearEffectConfirmResult(problemInfo);
                return;
            }
            if (rejectBothPending)
            {
                await InvalidateCompletedPreventionTasksAsync(problemId);
                await InvalidateCompletedEffectTasksAsync(problemId);
                ClearEffectConfirmResult(problemInfo);
            }
        }

        /// <summary>
        /// 清空效果确认结果，驳回后需重做效果确认。
        /// </summary>
        private static void ClearEffectConfirmResult(ZCTracking_ProblemList problemInfo)
        {
            problemInfo.Confirmation = "";
            problemInfo.ConfirmUser = null;
            problemInfo.ConfirmDate = null;
        }

        /// <summary>
        /// 从并行节点退回上一流程前，按通过/驳回组合保留或作废并行结果。
        /// </summary>
        private async Task CancelParallelTasksBeforeBackAsync(ZCTracking_ProblemList problemInfo, int thisStatus)
        {
            await ApplyParallelRejectKeepRulesAsync(problemInfo, thisStatus);
        }

        /// <summary>
        /// 效果确认已通过：主单有确认结果且当前无效果确认待办。
        /// </summary>
        private async Task<bool> HasKeptEffectConfirmResultAsync(ZCTracking_ProblemList problemInfo)
        {
            if (problemInfo == null || string.IsNullOrWhiteSpace(problemInfo.Confirmation))
            {
                return false;
            }
            return await _pubTaskService.GetTaskCount(xgfTable, problemInfo.ID) == 0;
        }

        /// <summary>
        /// 再次进入并行阶段时若效果确认已通过，则只保留结果、主状态改为仅预防对策确认。
        /// </summary>
        private async Task<bool> ApplyKeptEffectConfirmOnReenterAsync(ZCTracking_ProblemList problemInfo)
        {
            if (!await HasKeptEffectConfirmResultAsync(problemInfo))
            {
                return false;
            }
            problemInfo.MemberList = "";
            problemInfo.MemberListName = "";
            problemInfo.Status = NeedPreventionConfirm(problemInfo.ProblemType)
                ? (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly
                : (int)ZCTracking_ProblemStatusEnum.EffectConfirm;
            return true;
        }

        /// <summary>
        /// 效果确认已保留时只重开预防对策确认，并刷新并行主状态。
        /// </summary>
        private async Task ResumePreventionOnlyAfterKeptEffectAsync(
            ZCTracking_ProblemList problemInfo, string productIds, string sendMail, string ccMailList)
        {
            await ReenterParallelConfirmAsync(problemInfo, productIds, sendMail, ccMailList);
        }

        /// <summary>
        /// 再次进入并行节点：按保留规则决定是否重开预防对策确认，并刷新主状态。
        /// </summary>
        private async Task ReenterParallelConfirmAsync(
            ZCTracking_ProblemList problemInfo, string productIds, string sendMail, string ccMailList)
        {
            await StartPreventionConfirmAsync(problemInfo, productIds, sendMail, ccMailList);
            if (!await TryEnterClosingConfirmAsync(problemInfo, DateTime.Now))
            {
                await PersistParallelConfirmStatusAsync(problemInfo);
            }
        }

        /// <summary>
        /// 预防对策确认已办结：存在已完成待办且当前无未完成待办（效果确认驳回后再次进入并行节点时不重开）。
        /// </summary>
        private async Task<bool> HasKeptPreventionConfirmResultAsync(int problemId)
        {
            if (await HasPendingPreventionConfirmTaskAsync(problemId))
            {
                return false;
            }
            return await _pubTaskService.EndCountTask(preventionTable, problemId) > 0;
        }

        private async Task<string> GetWLEmail(string invCode)
        {
            var emails = await dapperHelperInfo.QueryAsync<string>(@$"SELECT e.Mail
FROM info.dbo.Inventory i WITH(NOLOCK)
JOIN TEMPERP.UFDATA_999_2021.dbo.Vendor v WITH(NOLOCK) ON i.cVenCode=v.cVenCode
JOIN info.dbo.tbIQCvendor tv WITH(NOLOCK) ON v.cVenCode=tv.ferpcode
LEFT JOIN info.dbo.Employee e WITH(NOLOCK) ON e.ID=tv.SQE
WHERE i.cInvCode='{invCode}'");
            return string.Join(";", emails);
        }
        #endregion
        #region 编辑
        public async Task<bool> EditVenCode(UpdateVenCodeDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo.ProblemType == 3) //物料问题
            {
                repository.Update(new ZCTracking_ProblemList { ID = dto.ProblemId, VenCode = dto.VenCode }, x => new { x.VenCode });
            }
            return await repository.SaveChangesAsync() > 0;
        }
        public async Task<bool> UpdateCAR(int problemId, string carNo, int carId)
        {
            repository.Update(new ZCTracking_ProblemList { ID = problemId, CAR = carNo, CARID = carId }, x => new { x.CAR, x.CARID });
            return await repository.SaveChangesAsync() > 0;
        }
        public async Task<int> UpdateProblem(EditProblemDto dto)
        {
            repository.Update(new ZCTracking_ProblemList { ID = dto.ProblemId, ProblemDesc = dto.ProblemDesc, Improve = dto.Improve, Remark = dto.Remark, UpdateDate = DateTime.Now, UpdateUser = UserContext.Current.UserId }, x => new { x.ProblemDesc, x.Improve, x.Remark, x.UpdateDate, x.UpdateUser });
            await repository.SaveChangesAsync();
            var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().Where(x => x.ProblemId == dto.ProblemId && x.Step == 1).FirstOrDefaultAsync();
            return log.ID;
        }
        public async Task<bool> EditQtyByProblemId(EditQtyDto dto)
        {
            var afterSaleIssueCheckReasonDb = repository.DbContext.Set<ZCTracking_CheckReason>();
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var level = problemInfo.ProblemLevel;
            var checkReasonList = afterSaleIssueCheckReasonDb.Where(x => x.ProblemId == dto.ProblemId).Select(x => x.ClassID).Distinct().ToList();
            if (checkReasonList.Any())
            {
                if (problemInfo.ProblemType == 7)
                {
                    level = "C";
                }
                else if (problemInfo.ProblemType == 4)
                {
                    if (problemInfo.IsStop == 1)
                    {
                        level = "A";
                    }
                    else
                    {
                        level = "B";
                    }
                }
                else
                {
                    var scale = -1m;
                    if (dto.Rate.HasValue)
                    {
                        scale = dto.Rate.Value / 100;
                    }
                    level = await afterSaleIssueClassService.GetProblemLevel(string.Join(",", checkReasonList), scale);
                }


            }
            repository.Update(new ZCTracking_ProblemList
            {
                ID = dto.ProblemId,
                ProdQty = dto.ImpactQty,
                BadQty = dto.BadQty,
                Rate = dto.Rate,
                ProblemLevel = level,
            }, x => new { x.ProdQty, x.BadQty, x.Rate, x.ProblemLevel });
            return await repository.SaveChangesAsync() > 0;
        }

        public async Task<bool> EditProblemLevel(EditProblemLevelDto dto)
        {
            repository.Update(new ZCTracking_ProblemList
            {
                ID = dto.ProblemId,
                ProblemLevel = dto.Level
            }, x => new { x.ProblemLevel });
            return await repository.SaveChangesAsync() > 0;
        }

        public async Task<bool> EditReason(EditReasonDto dto)
        {
            repository.Update(new ZCTracking_ProblemList
            {
                ID = dto.ProblemId,
                Reason = dto.Reason,
            }, x => new { x.Reason });
            return await repository.SaveChangesAsync() > 0;
        }
        public async Task<bool> EditProblemDesc(EditReasonDto dto)
        {
            repository.Update(new ZCTracking_ProblemList
            {
                ID = dto.ProblemId,
                ProblemDesc = dto.Reason,
            }, x => new { x.ProblemDesc });
            return await repository.SaveChangesAsync() > 0;
        }
        public async Task<bool> EditMeasures(EditReasonDto dto)
        {
            repository.Update(new ZCTracking_ProblemList
            {
                ID = dto.ProblemId,
                Measures = dto.Reason,
            }, x => new { x.Measures });
            return await repository.SaveChangesAsync() > 0;
        }
        public async Task<bool> EditPrevention(EditReasonDto dto)
        {
            repository.Update(new ZCTracking_ProblemList
            {
                ID = dto.ProblemId,
                Prevention = dto.Reason,
            }, x => new { x.Prevention });
            return await repository.SaveChangesAsync() > 0;
        }

        public async Task<bool> EditEndConfirmDesc(EditReasonDto dto)
        {
            var logDb = repository.DbContext.Set<ZCTracking_ProblemSteplog>();
            var closeLog = await logDb.Where(x => x.ProblemId == dto.ProblemId && x.Step == ZCTracking_ProblemOpeEnum.ClosingConfirm.GetEnumIntValue()).FirstOrDefaultAsync();
            closeLog.Opinon = dto.Reason;
            logDb.Update(closeLog);
            return await repository.SaveChangesAsync() > 0;
        }
        public async Task<bool> EditDepartmentAndReasonClass(EditDepartmentAndReasonClassDto dto)
        {
            var main = await repository.FindAsyncFirst(x => x.ID == dto.ID);
            main.AllReDepartment = dto.AllReDepartment;
            main.ReasonClass = dto.ReasonClass;
            main.ReasonClassRemark = dto.ReasonClassRemark;
            repository.Update(main, x => new { x.AllReDepartment, x.ReasonClass, x.ReasonClassRemark });
            return await repository.SaveChangesAsync() > 0;
        }

        /// <summary>
        /// 结案后修改问题分类，并写入操作记录。
        /// </summary>
        public async Task<bool> EditProblemType(EditProblemTypeDto dto)
        {
            var main = await repository.FindAsyncFirst(x => x.ID == dto.ID);
            if (main == null)
            {
                throw new BusinessException("问题单不存在");
            }
            if (main.Status != ZCTracking_ProblemStatusEnum.End.GetEnumIntValue())
            {
                throw new BusinessException("仅已完成的问题单可以修改问题分类");
            }
            if (main.ProblemType == dto.ProblemType)
            {
                return true;
            }
            var oldTypeName = DicConst.ProblemTypeDic.TryGetValue(main.ProblemType, out var oldName) ? oldName : main.ProblemType.ToString();
            var newTypeName = DicConst.ProblemTypeDic.TryGetValue(dto.ProblemType, out var newName) ? newName : dto.ProblemType.ToString();
            var now = DateTime.Now;
            // 结案后改分类原先只改主表，操作记录看不到
            await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = main.ID,
                Step = (int)ZCTracking_ProblemOpeEnum.EditProblemType,
                StepStr = "修改问题分类",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Measures = $"原问题分类：{oldTypeName}，修改为：{newTypeName}",
                ProblemStatus = main.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            main.OldProblemType = main.ProblemType;
            main.ProblemType = dto.ProblemType;
            main.EditProblemTypeTime = now;
            repository.Update(main, x => new { x.ProblemType, x.OldProblemType, x.EditProblemTypeTime });
            return await repository.SaveChangesAsync() > 0;
        }
        #endregion
        public async Task<int> CreateProblem(ProblemAddDto dto)
        {
            var classIds = new List<int>();
            if (dto.CheckReasonList != null)
            {
                classIds.AddRange(dto.CheckReasonList.Select(x => x.ClassID));
            }
            if (dto.AddOtherReasonList != null)
            {
                classIds.AddRange(dto.AddOtherReasonList.Select(x => x.ClassID));
            }
            var level = "";
            if (dto.ProblemType == 7)
            {
                level = "C";
            }
            else if (dto.ProblemType == 4)
            {
                if (dto.IsStop == 1)
                {
                    level = "A";
                }
                else
                {
                    level = "B";
                }
            }
            else
            {
                var scale = -1m;
                if (dto.Rate.HasValue)
                {
                    scale = dto.Rate.Value / 100;
                }
                level = await afterSaleIssueClassService.GetProblemLevel(string.Join(",", classIds), scale);
            }
            var stepId = 1;

            #region 问题
            var now = DateTime.Now;
            var numbers = await GetNumbersByMonth();
            var status = GetInitStatus(dto.ProblemType);
            int? outPutStatus = null;
            if (dto.SchemeOnlineList.Any())
            {
                if (dto.SchemeOnlineList.Any(x => x.OutPutStatus == 197)) outPutStatus = 197;
                else if (dto.SchemeOnlineList.Any(x => x.OutPutStatus == 196)) outPutStatus = 196;
                else if (dto.SchemeOnlineList.Any(x => x.OutPutStatus == 195)) outPutStatus = 195;
                else if (dto.SchemeOnlineList.Any(x => x.OutPutStatus == 9)) outPutStatus = 9;
                else if (dto.SchemeOnlineList.Any(x => x.OutPutStatus == 6)) outPutStatus = 6;
                else if (dto.SchemeOnlineList.Any(x => x.OutPutStatus == 8)) outPutStatus = 8;
                else if (dto.SchemeOnlineList.Any(x => x.OutPutStatus == 5)) outPutStatus = 5;
                else if (dto.SchemeOnlineList.Any(x => x.OutPutStatus == 7)) outPutStatus = 7;
            }
            var problemInfo = new ZCTracking_ProblemList
            {
                Numbers = numbers,
                ProblemType = dto.ProblemType,
                Factory = dto.Factory,
                Status = status,
                ImpactQty = dto.ImpactQty,
                BadQty = dto.BadQty,
                Rate = dto.Rate,
                ProblemDesc = dto.ProblemDesc,
                Improve = dto.Improve,
                FoundDate = dto.FoundDate,
                Station = dto.Station,
                Version = dto.Version,
                IsStop = dto.IsStop,
                StopStatus = dto.IsStop == 1 ? 1 : 3,
                StopDate = dto.StopDate,
                CInvCode = dto.CInvCode,
                VenCode = dto.VenCode,
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Remark = dto.Remark,
                IsDelete = 0,
                OutPutStatus = outPutStatus,
                ProblemLevel = level,
                MHead = dto.MHead,
                ProdQty = dto.ProdQty,
            };
            var zlmemberListName = new SelectItem();
            if (dto.ProblemType == 4)
            {
                zlmemberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameZL, stepId);
                if (problemInfo.IsStop.Value == 1)
                {
                    problemInfo.ReStartSchemeUser = zlmemberListName.Key;
                    problemInfo.StopStatus = 6;
                }
            }
            var problemEntity = await repository.DbContext.Set<ZCTracking_ProblemList>().AddAsync(problemInfo);
            await repository.SaveChangesAsync();
            var problemId = problemEntity.Entity.ID;
            #endregion

            //日志记录
            var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = problemId,
                Step = (int)ZCTracking_ProblemOpeEnum.Create,
                StepStr = "填写问题",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                ProblemStatus = status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            await repository.SaveChangesAsync();

            #region 机型
            var products = new List<ZCTracking_ProductNames>();
            var productIds = "";
            if (dto.ProductNames.Any())
            {
                foreach (var item in dto.ProductNames)
                {
                    products.Add(new ZCTracking_ProductNames
                    {
                        ProblemId = problemId,
                        ProductId = item.ProductId,
                        ProductName = item.ProductName,
                        Series = item.Series,
                    });
                    productIds += $"{item.ProductId},";
                }
                ;
                productIds = productIds.TrimEnd(',');
                await repository.DbContext.Set<ZCTracking_ProductNames>().AddRangeAsync(products);
            }
            #endregion

            #region 订单
            var problemOrders = new List<ZCTracking_ProblemOrders>();
            if (dto.SchemeOnlineList.Any())
            {
                foreach (var item in dto.SchemeOnlineList)
                {
                    problemOrders.Add(new ZCTracking_ProblemOrders
                    {
                        ProblemId = problemId,
                        OrderNumber = item.OrderNumber,
                        PartNumber = item.PartNumber,
                        PartName = item.PN,
                        IssueDate = item.FaliaoDate,
                        OrderQty = item.Quantity,
                        ReceiptQty = item.Totalinqty,
                        OnlineQty = item.OnlineQty,
                        Version = item.Version,
                    });
                }
                await repository.DbContext.Set<ZCTracking_ProblemOrders>().AddRangeAsync(problemOrders);
            }
            #endregion

            #region 小板订单
            var xbOrderDb = repository.DbContext.Set<ZCTracking_XBOrders>();
            var addXbOrders = new List<ZCTracking_XBOrders>();
            if (dto.XBOrderList.Any())
            {
                foreach (var item in dto.XBOrderList)
                {
                    addXbOrders.Add(new ZCTracking_XBOrders
                    {
                        ProblemId = problemId,
                        OrderNumber = item.OrderNumber,
                        InvCode = item.InvCode,
                        InvStd = item.InvStd,
                        Qty = item.Qty,
                        InQty = item.InQty,
                        NoQty = item.NoQty,
                        Factory = item.Factory,
                        Description = item.Description,
                    });
                }
                await xbOrderDb.AddRangeAsync(addXbOrders);
            }
            #endregion
            string context = string.Empty, urlHtml = string.Empty;
            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;//抄送人
            string email;

            #region 流程

            var orderNumberList = dto.SchemeOnlineList.Select(x => x.OrderNumber).ToList();
            var productIdList = dto.ProductNames.Select(x => x.ProductId).ToList();
            var newEmail = await GetNewEmail(dto.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            switch (dto.ProblemType)
            {
                case 1:
                case 2:
                case 6:
                    //发起任务
                    var taskName = "国内制程问题单【" + numbers + "】待指定责任人";
                    var memberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameRJ, stepId);
                    var userId = memberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType) + stepId, problemId.ToString(), taskName, userId, now, now.AddDays(3)));
                    //修改问题当前责任人                   
                    problemEntity.Entity.MemberListName = memberListName.Value;
                    problemEntity.Entity.MemberList = memberListName.Key;
                    /* 发邮件 */
                    problemInfo.MemberListName = memberListName.Value;
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/QualityAssignDutyMan?id={problemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ResponsibleUser, "", addXbOrders);
                    email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                    email = string.Join(";", email.Split(";").Distinct());
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    await SendEmail(sendMail, email, ccMailList, taskName, context, productIds);
                    break;
                case 3:
                    //发起任务
                    var wltaskName = "国内制程问题单【" + numbers + "】待IQC填写意见";
                    var userIds_IQC = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, stepId);
                    var userId_IQC = 0;
                    if (dto.Factory == "04")//柯洱斯
                    {
                        userId_IQC = userIds_IQC[1];
                    }
                    if (dto.Factory == "05")//亮亮
                    {
                        userId_IQC = userIds_IQC[1];
                    }
                    if (dto.Factory == "09")//09惠州百富
                    {
                        userId_IQC = userIds_IQC[0];
                    }
                    await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType) + 7, problemId, wltaskName, userId_IQC, now, now.AddDays(3));
                    //修改问题当前责任人
                    problemEntity.Entity.MemberList = userId_IQC.ToString();
                    problemEntity.Entity.MemberListName = await _hrEmployeeService.GetNameByIDAsync(problemEntity.Entity.MemberList);
                    /* 发邮件 */
                    problemInfo.MemberListName = problemEntity.Entity.MemberListName;
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/IQCOpinion?id={problemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.IQCOpinion, "", addXbOrders);
                    email = await _hrEmployeeService.GetEmailFromIDAsync(problemEntity.Entity.MemberList);
                    ccMailList = await _hrEmployeeService.GetEmailFromIDAsync(string.Join(",", userIds_IQC));
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    email = string.Join(";", email.Split(";").Distinct());

                    //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                    email += $";{await GetWLEmail(problemInfo.CInvCode)}";
                    ccMailList += $";{cuijuan}";
                    await SendEmail(sendMail, email, ccMailList, wltaskName, context, productIds);
                    break;
                case 4:
                    //发起任务
                    var zlTaskName = "国内制程问题单【" + numbers + "】待确认";
                    var zlUserId = zlmemberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType) + stepId, problemId.ToString(), zlTaskName, zlUserId, now, now.AddDays(3)));
                    //修改问题当前责任人
                    problemEntity.Entity.MemberListName = zlmemberListName.Value;
                    problemEntity.Entity.MemberList = zlmemberListName.Key;
                    /* 发邮件 */
                    problemInfo.MemberListName = zlmemberListName.Value;
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProjectConfirm?id={problemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ConfirmVersion, "", addXbOrders);
                    email = await _hrEmployeeService.GetEmailFromIDAsync(zlmemberListName.Key);
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    await SendEmail(sendMail, email, ccMailList, zlTaskName, context, productIds);

                    if (problemInfo.IsStop.Value == 1)
                    {
                        var stopTaskName = $"国内制程问题单【" + problemInfo.Numbers + "】待填写停线重启方案";
                        await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(stopRsUser, problemId.ToString(), stopTaskName, zlUserId, now, now.AddDays(3)));
                        await SendEmail(sendMail, email, ccMailList, stopTaskName, context, productIds);
                    }
                    break;
                case 5:
                    //发起任务
                    var zcTaskName = "国内制程问题单【" + numbers + "】待分析";
                    //修改问题当前责任人
                    var zcmemberList = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameZC, stepId);
                    var zcUserId = 0;
                    if (dto.Factory == "04")//柯洱斯
                    {
                        zcUserId = zcmemberList[1];
                        problemEntity.Entity.MemberList = zcUserId.ToString();
                    }
                    if (dto.Factory == "05")//亮亮
                    {
                        zcUserId = zcmemberList[2];
                        problemEntity.Entity.MemberList = zcUserId.ToString();
                    }
                    if (dto.Factory == "09")//09惠州百富
                    {
                        zcUserId = zcmemberList[0];
                        problemEntity.Entity.MemberList = zcUserId.ToString();
                    }
                    problemEntity.Entity.MemberListName = await _hrEmployeeService.GetNameByIDAsync(problemEntity.Entity.MemberList);
                    /* 发邮件 */
                    problemInfo.MemberListName = problemEntity.Entity.MemberListName;
                    await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType) + stepId, problemId, zcTaskName, zcUserId, now, now.AddDays(3));
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/FactoryConfirm?id={problemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.FactoryAnalysis, "", addXbOrders);
                    email = await _hrEmployeeService.GetEmailFromIDAsync(problemEntity.Entity.MemberList);
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    await SendEmail(sendMail, email, ccMailList, zcTaskName, context, productIds);
                    break;
                case 7:
                    var yhTaskName = "国内制程问题单【" + numbers + "】生产角色确认";
                    var yhMemberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameRJ, 5);
                    var yhUserId = yhMemberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType) + 5, problemId.ToString(), yhTaskName, yhUserId, now, now.AddDays(3)));
                    //修改问题当前责任人                   
                    problemEntity.Entity.MemberListName = yhMemberListName.Value;
                    problemEntity.Entity.MemberList = yhMemberListName.Key;
                    /* 发邮件 */
                    problemInfo.MemberListName = yhMemberListName.Value;
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProduceConfirm?id={problemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ProduceConfirm, "", addXbOrders);
                    email = await _hrEmployeeService.GetEmailFromIDAsync(yhMemberListName.Key);
                    email = string.Join(";", email.Split(";").Distinct());
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    await SendEmail(sendMail, email, ccMailList, yhTaskName, context, productIds);
                    break;
                    break;
                default:
                    break;
            }
            #endregion



            #region 问题原因
            var afterSaleIssueCheckReasonDb = repository.DbContext.Set<ZCTracking_CheckReason>();
            var afterSaleIssueClassPhenomenonDb = repository.DbContext.Set<AfterSaleIssueClassPhenomenon>();
            if (dto.AddOtherReasonList != null)
            {
                foreach (var reasonItem in dto.AddOtherReasonList)
                {
                    var addPhenomenon = new AfterSaleIssueClassPhenomenon
                    {
                        ClassID = reasonItem.ClassID,
                        PhenomenonDesc = reasonItem.PhenomenonDesc,
                        AddUser = UserContext.Current.UserId,
                        AddDate = DateTime.Now,
                    };
                    await afterSaleIssueClassPhenomenonDb.AddAsync(addPhenomenon);
                    await repository.SaveChangesAsync();
                    await afterSaleIssueCheckReasonDb.AddAsync(new ZCTracking_CheckReason
                    {
                        ProblemId = problemId,
                        ClassID = reasonItem.ClassID,
                        PhenomenonID = addPhenomenon.ID,
                        ReasonID = 0,
                        AddUser = UserContext.Current.UserId,
                        AddDate = DateTime.Now,
                    });
                }
            }
            await afterSaleIssueCheckReasonDb.AddRangeAsync(dto.CheckReasonList.Select(x => new ZCTracking_CheckReason
            {
                ProblemId = problemId,
                ClassID = x.ClassID,
                PhenomenonID = x.PhenomenonID,
                ReasonID = x.ReasonID,
                AddUser = UserContext.Current.UserId,
                AddDate = DateTime.Now,
            }));
            #endregion

            #region 可能物料
            if (dto.PossibleInvCodeList != null)
            {
                var afterSaleIssuePossibleInvCodeDb = repository.DbContext.Set<ZCTracking_PossibleInvCode>();
                foreach (var invCodeItem in dto.PossibleInvCodeList)
                {
                    await afterSaleIssuePossibleInvCodeDb.AddAsync(new ZCTracking_PossibleInvCode
                    {
                        ProblemId = problemId,
                        InvCode = invCodeItem.InvCode,
                        InvName = invCodeItem.InvName,
                        InvStd = invCodeItem.InvStd,
                    });
                }
            }
            #endregion
            await repository.SaveChangesAsync();

            #region 停线通知
            if (dto.IsStop == 1)
            {
                var zoCount = false;
                var emailUserIds = new List<int>();
                if (!string.IsNullOrWhiteSpace(productIds))
                {
                    emailUserIds = await dapperHelperCoreInfo.QueryAsync<int>(@$"SELECT DISTINCT d.Lead FROM info.dbo.ProductMaintainPerson p
LEFT JOIN info.dbo.V_Department_Include_Zolon d ON p.maintainunit=d.ID
WHERE p.BigProID in ({productIds})");
                    zoCount = await IsZLProd(productIds); ;
                }
                var toEmail = await _hrEmployeeService.GetEmailFromIDAsync(string.Join(",", emailUserIds));
                var emailgd = await mailAddressService.GetMailAddress("国内制程停线通知");
                var stopToEmail = emailgd.MailTo;
                var stopCCEmail = emailgd.MailCC;
                var productArrStr = string.Join(",", products.Select(x => x.ProductName));
                var orderArrStr = string.Join(",", problemOrders.Select(x => x.OrderNumber));
                switch (dto.Factory)
                {
                    case "04"://04柯洱斯
                        var pksEmail = await mailAddressService.GetMailAddress("国内制程停线通知(PKS)");
                        stopToEmail += $";{pksEmail.MailTo}";
                        stopCCEmail += $";{pksEmail.MailCC}";
                        break;
                    case "05"://05亮亮
                        var llEmail = await mailAddressService.GetMailAddress("国内制程停线通知(亮亮)");
                        stopToEmail += $";{llEmail.MailTo}";
                        stopCCEmail += $";{llEmail.MailCC}";
                        break;
                    case "09"://09惠州百富
                        var hlEmail = await mailAddressService.GetMailAddress("国内制程停线通知(惠州百富)");
                        stopToEmail += $";{hlEmail.MailTo}";
                        stopCCEmail += $";{hlEmail.MailCC}";
                        break;
                }
                stopToEmail += $";{toEmail}";
                stopToEmail = string.Join(";", stopToEmail.Split(";").Distinct());
                //if (zoCount)
                //{
                //    var zlEmail = await mailAddressService.GetMailAddress("国内制程涉及兆珑机型停线或重启通知");
                //    stopToEmail += $";{zlEmail.MailTo}";
                //}
                if (problemInfo.ProblemType == 3)
                {
                    //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                    stopToEmail += $";{await GetWLEmail(problemInfo.CInvCode)}";
                    stopCCEmail += $";{cuijuan}";
                }
                stopCCEmail += ";" + await GetStopCCMail(problemInfo.Numbers);
                Mail.SendMailSMTPBeltGog(sendMail, UserContext.Current.UserName, stopToEmail, stopCCEmail.Trim(';'), "", $"{productArrStr}停线通知", context, "2423", "制程问题追踪", "0", null);

            }
            #endregion

            return log.Entity.ID;
        }
        public async Task<bool> DeleteProblemById(int problemId)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == problemId);
            repository.Update(new ZCTracking_ProblemList { ID = problemId, IsDelete = 1 }, x => new { x.IsDelete });
            //日志记录
            var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = problemId,
                Step = (int)ZCTracking_ProblemOpeEnum.Delete,
                StepStr = "删除问题",
                AddUser = UserContext.Current.UserId,
                AddDate = DateTime.Now,
                ProblemStatus = problemInfo.Status,
                Measures = $"{UserContext.Current.UserName}删除问题",
                MemberList = UserContext.Current.UserId.ToString(),
            });
            var save = await repository.SaveChangesAsync() > 0;
            if (save)
            {
                //if (problemInfo.Status == (int)ZCTracking_ProblemStatusEnum.ResponsibleUser)
                //{
                //    await _pubTaskService.CancelTaskAddMemo(GetfTable(problemInfo.ProblemType) + 1, problemId.ToString(), UserContext.Current.UserId, "删除制程问题");
                //}
                //if (problemInfo.Status == (int)ZCTracking_ProblemStatusEnum.IQCOpinion)
                //{
                //    await _pubTaskService.CancelTaskAddMemo(GetfTable(problemInfo.ProblemType) + 7, problemId.ToString(), UserContext.Current.UserId, "删除制程问题");
                //}
                var sql = $@" update info.dbo.tbtask set fwhendone=getdate(),fstat='已取消',fmemo='删除制程问题' where ftable like 'ZCTracking_%' and fstat<>'已完成' and frecID='{problemId}' ";
                await dapperHelperCoreInfo.ExecuteAsync(sql);
            }
            return save;
        }
        public async Task<int> CreateOrders(CreateOrderDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var problemOrders = new List<ZCTracking_ProblemOrders>();
            foreach (var item in dto.SchemeOnlineList)
            {
                problemOrders.Add(new ZCTracking_ProblemOrders
                {
                    ProblemId = dto.ProblemId,
                    OrderNumber = item.OrderNumber,
                    PartNumber = item.PartNumber,
                    PartName = item.PN,
                    IssueDate = item.FaliaoDate,
                    OrderQty = item.Quantity,
                    ReceiptQty = item.Totalinqty,
                    OnlineQty = item.OnlineQty,
                    Version = item.Version,
                });
            }
            int? outPutStatus = null;

            var allOrders = new List<ZCTrackingSchemeOnlineDto>();
            if (problemInfo.OutPutStatus.HasValue)
            {
                allOrders.Add(new ZCTrackingSchemeOnlineDto { OutPutStatus = problemInfo.OutPutStatus.Value });
            }
            allOrders.AddRange(dto.SchemeOnlineList);
            if (allOrders.Any())
            {
                if (allOrders.Any(x => x.OutPutStatus == 197)) outPutStatus = 197;
                else if (allOrders.Any(x => x.OutPutStatus == 196)) outPutStatus = 196;
                else if (allOrders.Any(x => x.OutPutStatus == 195)) outPutStatus = 195;
                else if (allOrders.Any(x => x.OutPutStatus == 9)) outPutStatus = 9;
                else if (allOrders.Any(x => x.OutPutStatus == 6)) outPutStatus = 6;
                else if (allOrders.Any(x => x.OutPutStatus == 8)) outPutStatus = 8;
                else if (allOrders.Any(x => x.OutPutStatus == 5)) outPutStatus = 5;
                else if (allOrders.Any(x => x.OutPutStatus == 7)) outPutStatus = 7;
            }
            await repository.DbContext.Set<ZCTracking_ProblemOrders>().AddRangeAsync(problemOrders);

            #region 机型
            var productDb = repository.DbContext.Set<ZCTracking_ProductNames>();
            var productIdList = await productDb.Where(x => x.ProblemId == dto.ProblemId).Select(x => x.ProductId).ToListAsync();
            var productNames = dto.ProductNames.Where(x => !productIdList.Contains(x.ProductId)).ToList();
            if (productNames.Any())
            {
                var products = new List<ZCTracking_ProductNames>();
                foreach (var item in productNames)
                {
                    products.Add(new ZCTracking_ProductNames
                    {
                        ProblemId = dto.ProblemId,
                        ProductId = item.ProductId,
                        ProductName = item.ProductName,
                        Series = item.Series,
                    });
                }
                ;
                await productDb.AddRangeAsync(products);
            }
            #endregion

            problemInfo.ImpactQty += dto.SchemeOnlineList.Sum(x => x.OnlineQty);
            problemInfo.OutPutStatus = outPutStatus;
            repository.Update(problemInfo, x => new { x.ImpactQty, x.OutPutStatus });

            return await repository.SaveChangesAsync();
        }

        public async Task<int> CreateXBOrders(CreateXBOrdersDto model)
        {
            var xbOrderDb = repository.DbContext.Set<ZCTracking_XBOrders>();
            foreach (var item in model.XBOrderList)
            {
                await xbOrderDb.AddAsync(new ZCTracking_XBOrders
                {
                    ProblemId = model.ProblemId,
                    OrderNumber = item.OrderNumber,
                    InvCode = item.InvCode,
                    InvStd = item.InvStd,
                    Qty = item.Qty,
                    InQty = item.InQty,
                    NoQty = item.NoQty,
                    Factory = item.Factory,
                    Description = item.Description,
                });
            }
            return await repository.SaveChangesAsync();
        }
        /// <summary>
        /// 制程问题列表/导出排序字段白名单（前端列 prop → 安全列名）。
        /// </summary>
        private static readonly Dictionary<string, string> ProblemListSortColumnMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { "adddate", "AddDate" }, { "AddDate", "AddDate" }, { "Numbers", "Numbers" }, { "FactoryName", "FactoryName" },
            { "Factory", "Factory" }, { "AddUserName", "AddUserName" }, { "FoundDate", "FoundDate" },
            { "ProblemTypeStr", "ProblemTypeStr" }, { "ProblemType", "ProblemType" }, { "ProblemLevel", "ProblemLevel" },
            { "ProdQty", "ProdQty" }, { "ImpactQty", "ImpactQty" }, { "BadQty", "BadQty" }, { "Rate", "Rate" },
            { "ProductName", "ProductName" }, { "CInvCode", "CInvCode" }, { "CVenName", "CVenName" }, { "Status", "Status" },
            { "ID", "ID" }, { "IsStop", "IsStop" }, { "StopStatus", "StopStatus" }, { "StopDate", "StopDate" }
        };

        /// <summary>
        /// 解析列表排序字段，未命中白名单时按 AddDate。
        /// </summary>
        private static string ResolveProblemListSortColumn(string sort)
        {
            if (string.IsNullOrWhiteSpace(sort))
            {
                return "AddDate";
            }
            return ProblemListSortColumnMap.TryGetValue(sort.Trim(), out var col) ? col : "AddDate";
        }

        /// <summary>
        /// 解析排序方向，仅允许 ASC/DESC。
        /// </summary>
        private static string ResolveSortDirection(string orderBy)
        {
            return string.Equals(orderBy, "asc", StringComparison.OrdinalIgnoreCase) ? "ASC" : "DESC";
        }

        /// <summary>
        /// 将逗号分隔字符串解析为正整数列表，非法片段丢弃。
        /// </summary>
        private static List<int> ParsePositiveIntList(string raw)
        {
            var list = new List<int>();
            if (string.IsNullOrWhiteSpace(raw))
            {
                return list;
            }
            foreach (var part in raw.Split(new[] { ',', '，' }, StringSplitOptions.RemoveEmptyEntries))
            {
                if (int.TryParse(part.Trim(), out var id) && id > 0)
                {
                    list.Add(id);
                }
            }
            return list;
        }

        /// <summary>
        /// 将逗号分隔字符串解析为非空片段列表。
        /// </summary>
        private static List<string> ParseCsvList(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw))
            {
                return new List<string>();
            }
            return raw.Split(new[] { ',', '，' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(x => x.Trim()).Where(x => x.Length > 0).ToList();
        }

        public async Task<PageModel<ProblemListDto>> ProblemPageList(int pageIndex, int pageSize, string series, string productId, DateTime? addDate, DateTime? endTime, string venCode, string invCode, int? status, string problemType, string factory, string number, int? stopState, int? userType, string userId, string sort, string orderBy, int? isStop = null, string reasonClass = null, string materialTypeName = null)
        {
            var param = new Dapper.DynamicParameters();
            var whereSql = " where p.IsDelete=0 ";
            if (addDate.HasValue)
            {
                whereSql += " and p.AddDate>=@AddDate";
                param.Add("AddDate", addDate.Value);
            }
            if (endTime.HasValue)
            {
                // 与看板统计一致：结束日为含当日，上界为次日 0 点（不含）
                whereSql += " and p.AddDate<@EndTime";
                param.Add("EndTime", endTime.Value.Date.AddDays(1));
            }
            if (!string.IsNullOrWhiteSpace(venCode))
            {
                whereSql += " and p.VenCode=@VenCode";
                param.Add("VenCode", venCode);
            }
            if (!string.IsNullOrWhiteSpace(invCode))
            {
                whereSql += " and p.CInvCode=@InvCode";
                param.Add("InvCode", invCode);
            }
            if (!string.IsNullOrWhiteSpace(factory))
            {
                whereSql += " and p.Factory=@Factory";
                param.Add("Factory", factory);
            }
            var problemTypes = ParseCsvList(problemType);
            if (problemTypes.Count > 0)
            {
                whereSql += " and p.ProblemType in @ProblemTypes";
                param.Add("ProblemTypes", problemTypes);
            }
            if (status.HasValue)
            {
                if (status.Value == -1) //未完成
                {
                    whereSql += " and p.Status <>@EndStatus";
                    param.Add("EndStatus", (int)ZCTracking_ProblemStatusEnum.End);
                }
                else if (status.Value == (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly)
                {
                    whereSql += " and (p.Status=@EffectConfirm or p.Status=@PreventionConfirmOnly or exists (select 1 from info.dbo.tbTask t with(nolock) where t.ftable=@PreventionTable and t.frecID=cast(p.ID as nvarchar(50)) and t.fstat=N'已接受'))";
                    param.Add("EffectConfirm", (int)ZCTracking_ProblemStatusEnum.EffectConfirm);
                    param.Add("PreventionConfirmOnly", (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly);
                    param.Add("PreventionTable", preventionTable);
                }
                else if (status.Value == (int)ZCTracking_ProblemStatusEnum.EffectConfirm)
                {
                    whereSql += " and (p.Status=@EffectConfirm or p.Status=@EffectConfirmOnly or p.IQCStatus=@Status)";
                    param.Add("EffectConfirm", (int)ZCTracking_ProblemStatusEnum.EffectConfirm);
                    param.Add("EffectConfirmOnly", (int)ZCTracking_ProblemStatusEnum.EffectConfirmOnly);
                    param.Add("Status", status.Value);
                }
                else
                {
                    whereSql += " and (p.Status=@Status or p.IQCStatus=@Status)";
                    param.Add("Status", status.Value);
                }
            }
            if (!string.IsNullOrWhiteSpace(number))
            {
                whereSql += " and p.Numbers like @Number";
                param.Add("Number", $"%{number}%");
            }
            if (stopState.HasValue)
            {
                if (stopState == 1)
                {
                    whereSql += " and p.StopStatus in (1,4,5,6)";
                }
                else
                {
                    whereSql += " and p.StopStatus =@StopState";
                    param.Add("StopState", stopState.Value);
                }
            }
            if (isStop.HasValue && isStop.Value == 1)
            {
                whereSql += " and p.IsStop=1";
            }
            if (!string.IsNullOrWhiteSpace(reasonClass))
            {
                // 与看板「月度物料问题原因分类」统计口径一致：空值归为「未填写」
                whereSql += " AND ISNULL(NULLIF(LTRIM(RTRIM(p.ReasonClass)), N''), N'未填写') = @ReasonClass";
                param.Add("ReasonClass", reasonClass.Trim());
            }
            if (!string.IsNullOrWhiteSpace(materialTypeName))
            {
                // 与看板「物料问题 TOP10 类型」一致：同名分类会拼上一级名称
                whereSql += @" AND (
                    SELECT TOP 1
                      CASE
                        WHEN ic2.cInvCCode IS NULL THEN N'未分类'
                        WHEN cnt2.SameNameCnt > 1 AND ISNULL(NULLIF(LTRIM(RTRIM(pic2.cInvCName)), N''), N'') <> N''
                          THEN ISNULL(NULLIF(LTRIM(RTRIM(ic2.cInvCName)), N''), N'未分类') + N'(' + LTRIM(RTRIM(pic2.cInvCName)) + N')'
                        WHEN cnt2.SameNameCnt > 1
                          THEN ISNULL(NULLIF(LTRIM(RTRIM(ic2.cInvCName)), N''), N'未分类') + N'(' + ISNULL(ic2.cInvCCode, N'') + N')'
                        ELSE ISNULL(NULLIF(LTRIM(RTRIM(ic2.cInvCName)), N''), N'未分类')
                      END
                    FROM info.dbo.Inventory i2 WITH(NOLOCK)
                    LEFT JOIN TEMPERP.UFDATA_900_2021.dbo.InventoryClass ic2 WITH(NOLOCK) ON ic2.cInvCCode = i2.cInvCCode
                    OUTER APPLY (
                      SELECT TOP 1 p.cInvCName
                      FROM TEMPERP.UFDATA_900_2021.dbo.InventoryClass p WITH(NOLOCK)
                      WHERE p.iInvCGrade = ic2.iInvCGrade - 1
                        AND LEFT(ic2.cInvCCode, LEN(p.cInvCCode)) = p.cInvCCode
                      ORDER BY LEN(p.cInvCCode) DESC
                    ) pic2
                    OUTER APPLY (
                      SELECT COUNT(1) AS SameNameCnt
                      FROM TEMPERP.UFDATA_900_2021.dbo.InventoryClass x WITH(NOLOCK)
                      WHERE ISNULL(NULLIF(LTRIM(RTRIM(x.cInvCName)), N''), N'未分类')
                          = ISNULL(NULLIF(LTRIM(RTRIM(ic2.cInvCName)), N''), N'未分类')
                    ) cnt2
                    WHERE i2.cInvCode = p.CInvCode
                ) = @MaterialTypeName";
                param.Add("MaterialTypeName", materialTypeName.Trim());
            }
            if (userType.HasValue && !string.IsNullOrWhiteSpace(userId))
            {
                param.Add("UserId", userId);
                switch (userType)
                {
                    case 1:
                        whereSql += " AND p.AddUser =@UserId";
                        break;
                    case 2:
                        whereSql += " AND p.MemberList LIKE @UserIdLike";
                        param.Add("UserIdLike", $"%{userId}%");
                        break;
                    case 3:
                        whereSql += " AND l.MemberList LIKE @UserIdLike";
                        param.Add("UserIdLike", $"%{userId}%");
                        break;
                    case 4:
                        whereSql += " and np.Name like @UserIdPrefix";
                        param.Add("UserIdPrefix", $"{userId}%");
                        break;
                    case 5:
                        whereSql += " and p.ProblemDesc like @UserIdLike";
                        param.Add("UserIdLike", $"%{userId}%");
                        break;
                    case 6:
                        whereSql += " and p.Reason like @UserIdLike";
                        param.Add("UserIdLike", $"%{userId}%");
                        break;
                    default:
                        break;
                }
            }
            var tWhere = " where 1=1 ";
            if (!string.IsNullOrWhiteSpace(series))
            {
                if (series != "物料")
                {
                    tWhere += " and b.series=@Series";
                    whereSql += " and isnull(pn.series,'')!=''";
                    param.Add("Series", series);
                }
                else
                {
                    whereSql += " and p.MHead=@Series";
                    param.Add("Series", series);
                }
            }
            var productIds = ParsePositiveIntList(productId);
            if (productIds.Count > 0)
            {
                tWhere += " and b.productId in @ProductIds";
                param.Add("ProductIds", productIds);
            }
            var sortColumn = ResolveProblemListSortColumn(sort);
            var sortDir = ResolveSortDirection(orderBy);
            var sql = $@"
SELECT ROW_NUMBER() OVER(ORDER BY {sortColumn} {sortDir}) rowId,* FROM (SELECT p.ID,p.Numbers,p.FoundDate,p.Factory,
CASE p.Factory WHEN '04' THEN '柯洱斯'  WHEN '05' THEN '亮亮' WHEN '09' THEN '惠州百富' ELSE '' END FactoryName
,pn.ProductName,p.ProblemType,CASE p.ProblemType WHEN '1' THEN '硬件问题' WHEN '2' THEN '软件问题' WHEN '3' THEN '物料问题' WHEN '4' THEN '资料问题' WHEN '5' THEN '工厂制程' WHEN '6' THEN '结构问题' 
WHEN '7' THEN '制程优化' ELSE '' END ProblemTypeStr
,p.ProblemDesc,p.Status,p.MemberListName,pn.series,p.IsStop,p.StopStatus,p.StopDate,p.ImpactQty,p.BadQty,p.Station,p.Improve,p.AddUser,e.Name AddUserName,pn.ProductIds,p.MemberList,p.CInvCode,i.cInvName,p.VenCode,v.cVenName,po.OrderNumers,i.cInvStd,p.CAR,p.CARID,p.Rate,p.OutPutStatus,p.ProblemLevel,p.AddDate,p.Reason,p.MHead,p.ProdQty
,p.AllReDepartment,p.ReasonClass,p.ReStartExamineUser,p.ReasonClassRemark,p.ReStartSchemeUser,re.Name RUserName,b.RComplateTime,p.IQCStatus,p.IQCMemberList,p.IQCMemberListName,rk.ID RiskID
,p.IQCOpinion,rs.Step RsStep,rs.RsUsers,rs.RsUserNames,rk.AddUser RiskddUser
,prev.PreventionMemberList,prev.PreventionMemberListName
FROM dbo.ZCTracking_ProblemList p WITH(NOLOCK)
left JOIN 
(SELECT b.problemId,
STUFF((SELECT ','+a.productname FROM dbo.ZCTracking_ProductNames a WITH(NOLOCK) WHERE a.problemId=b.problemId FOR XML PATH('')),1,1,'') AS ProductName,
STUFF((SELECT ','+CAST(a.ProductId AS NVARCHAR(50)) FROM dbo.ZCTracking_ProductNames a WITH(NOLOCK) WHERE a.problemId=b.problemId FOR XML PATH('')),1,1,'') AS ProductIds
,STUFF((SELECT ','+a.series FROM (SELECT problemId,series FROM ZCTracking_ProductNames WITH(NOLOCK) GROUP BY problemid,series) a WHERE a.problemId=b.problemId FOR XML PATH('')),1,1,'') AS series
FROM dbo.ZCTracking_ProductNames b WITH(NOLOCK)
{tWhere} 
GROUP BY b.problemId
) pn ON pn.ProblemId=p.ID 
left JOIN (
	SELECT o.problemId,STUFF((SELECT ','+a.ordernumber FROM ZCTracking_ProblemOrders a WITH(NOLOCK) WHERE a.problemId=o.problemId FOR XML PATH ('')),1,1,'') AS OrderNumers FROM ZCTracking_ProblemOrders o WITH(NOLOCK) GROUP BY o.problemId
) po ON po.ProblemId=p.ID
left JOIN INFO.dbo.Employee e WITH(NOLOCK) ON p.AddUser=e.ID
LEFT JOIN info.dbo.Inventory i WITH(NOLOCK) ON i.cInvCode=p.CInvCode
LEFT JOIN TEMPERP.UFDATA_999_2021.dbo.Vendor v WITH(NOLOCK) ON v.cVenCode=p.VenCode
LEFT JOIN dbo.ZCTracking_ProblemSteplog l WITH(NOLOCK) ON l.ProblemId=p.ID and Step<>1
LEFT JOIN dbo.ZCTracking_ProblemOrders pos WITH(NOLOCK) ON pos.ProblemId=p.ID
LEFT JOIN info.dbo.NewProduct np WITH(NOLOCK) ON np.PartNumber=pos.PartNumber
LEFT JOIN  (
	SELECT ROW_NUMBER() OVER(PARTITION BY t.ftable,t.frecID ORDER BY fid desc) RowId,DATEDIFF(DAY, fwhenCreate,fwhenDone) RComplateTime,* FROM info.dbo.tbTask t WITH(NOLOCK)
	WHERE ftable='ZCTracking_ProblemSoftware2' AND fstat='已完成'
) b  on p.ID=b.frecID AND p.RUser=b.fuserID AND b.RowId=1
LEFT JOIN info.dbo.Employee re WITH(NOLOCK) ON p.RUser=re.ID
LEFT JOIN (
    SELECT ID, ProblemId, AddUser
    FROM (
        SELECT ID, ProblemId, AddUser,
               ROW_NUMBER() OVER(PARTITION BY ProblemId ORDER BY ID DESC) AS RowNum
        FROM dbo.ZCTracking_RiskOrderInfo WITH(NOLOCK)
    ) rkRank
    WHERE RowNum = 1
) rk ON rk.ProblemId = p.id
left join (
    SELECT
        rs.ProblemId,
        rs.Step,
        STRING_AGG(CAST(rs.UserID AS NVARCHAR(MAX)), ',') WITHIN GROUP (ORDER BY rs.UserID) AS RsUsers,
        STRING_AGG(e.Name, ',') WITHIN GROUP (ORDER BY rs.UserID) AS RsUserNames
    FROM dbo.ZCTracking_RiskStream rs WITH(NOLOCK)
    INNER JOIN (
        SELECT ProblemId, MAX(Step) AS Step
        FROM dbo.ZCTracking_RiskStream WITH(NOLOCK)
        WHERE Status = 1
        GROUP BY ProblemId
    ) latest ON latest.ProblemId = rs.ProblemId AND latest.Step = rs.Step
    LEFT JOIN info.dbo.Employee e WITH(NOLOCK) ON e.id = rs.UserID
    WHERE rs.Status = 1
    GROUP BY rs.ProblemId, rs.Step
) rs on rs.ProblemId=p.id
LEFT JOIN (
    SELECT
        t.frecID,
        STRING_AGG(CAST(t.fuserID AS NVARCHAR(MAX)), ',') WITHIN GROUP (ORDER BY t.fuserID) AS PreventionMemberList,
        STRING_AGG(e.Name, ',') WITHIN GROUP (ORDER BY t.fuserID) AS PreventionMemberListName
    FROM info.dbo.tbTask t WITH(NOLOCK)
    LEFT JOIN info.dbo.Employee e WITH(NOLOCK) ON e.ID = t.fuserID
    WHERE t.ftable = N'{preventionTable}' AND t.fstat = N'已接受'
    GROUP BY t.frecID
) prev ON p.ID = prev.frecID
{whereSql}
GROUP BY p.ID,p.Numbers,p.FoundDate,p.Factory,pn.ProductName,p.ProblemType,p.ProblemType,p.ProblemDesc,p.Status,p.MemberListName,pn.series,p.IsStop,p.StopStatus,p.StopDate,p.ImpactQty,p.BadQty
,p.Station,p.Improve,p.AddUser,e.Name,pn.ProductIds,p.MemberList,p.CInvCode,i.cInvName,p.VenCode,v.cVenName,po.OrderNumers,i.cInvStd,p.CAR,p.CARID,p.Rate,p.OutPutStatus,p.ProblemLevel,p.AddDate,p.Reason
,p.MHead,p.ProdQty,p.AllReDepartment,p.ReasonClass,p.ReStartExamineUser,p.ReasonClassRemark,p.ReStartSchemeUser,re.Name,b.RComplateTime,p.IQCStatus,p.IQCMemberList,p.IQCMemberListName,rk.ID,rs.Step,rs.RsUsers,rs.RsUserNames,p.IQCOpinion,rk.AddUser
,prev.PreventionMemberList,prev.PreventionMemberListName) a";

            param.Add("RowStart", (pageIndex - 1) * pageSize);
            param.Add("RowEnd", pageIndex * pageSize);
            var quarySql = $"SELECT * FROM ({sql}) t1 WHERE t1.rowId >@RowStart and t1.rowId<=@RowEnd ;";
            quarySql += $"SELECT COUNT(DISTINCT t1.ID) total FROM ({sql}) t1";
            var data = await dapperHelperCoreInfo.QueryMultipleAsync<ProblemListDto>(quarySql, param);
            if (data.Rows == null)
            {
                data.Rows = new List<ProblemListDto>();
            }
            else
            {
                data.Rows = data.Rows.ToList();
            }
            await FillPendingPreventionConfirmAsync(data.Rows);
            var unitAllNames = await _hrEmployeeService.GetALLUnitAsync();
            foreach (var item in data.Rows)
            {
                if (!string.IsNullOrWhiteSpace(item.AllReDepartment))
                {
                    var departmentIds = item.AllReDepartment.Split(",").Select(x => int.Parse(x));
                    item.AllReDepartmentName = string.Join(",", unitAllNames.Where(x => departmentIds.Contains(x.Id)).Select(x => x.Name).ToList());
                }
                if (!string.IsNullOrWhiteSpace(item.ReStartExamineUser))
                {
                    item.ReStartExamineUserName = await _hrEmployeeService.GetNameByIDAsync(item.ReStartExamineUser);
                }
                if (!string.IsNullOrWhiteSpace(item.ReStartSchemeUser))
                {
                    item.ReStartSchemeUserName = await _hrEmployeeService.GetNameByIDAsync(item.ReStartSchemeUser);
                }
            }
            return data;
        }

        /// <summary>
        /// 导出「责任人」：按问题类型取对应节点处理人；若改分类时间晚于结案时间，则按 OldProblemType 取值。
        /// </summary>
        public async Task FillExportRUserNameAsync(IEnumerable<ProblemListDto> rows)
        {
            if (rows == null)
            {
                return;
            }
            var list = rows as IList<ProblemListDto> ?? rows.ToList();
            if (list.Count == 0)
            {
                return;
            }
            var idStr = string.Join(",", list.Select(x => x.ID).Distinct());
            var typeSql = $@"SELECT ID, ProblemType, OldProblemType, EditProblemTypeTime
FROM dbo.ZCTracking_ProblemList WITH(NOLOCK)
WHERE ID IN ({idStr})";
            var typeList = await dapperHelperCoreInfo.QueryAsync<ExportRUserTypeDto>(typeSql);
            var typeDic = typeList.ToDictionary(x => x.ID);

            var stepConfirm = (int)ZCTracking_ProblemOpeEnum.Confirm;
            var stepConfirmVersion = (int)ZCTracking_ProblemOpeEnum.ConfirmVersion;
            var stepFactoryAnalysis = (int)ZCTracking_ProblemOpeEnum.FactoryAnalysis;
            var stepFollowSQE = (int)ZCTracking_ProblemOpeEnum.FollowSQE;
            var stepClosingConfirm = (int)ZCTracking_ProblemOpeEnum.ClosingConfirm;
            var logSql = $@"SELECT ProblemId, Step, AddUser, AddDate, ID
FROM dbo.ZCTracking_ProblemSteplog WITH(NOLOCK)
WHERE ProblemId IN ({idStr})
AND Step IN ({stepConfirm},{stepConfirmVersion},{stepFactoryAnalysis},{stepFollowSQE},{stepClosingConfirm})";
            var logs = await dapperHelperCoreInfo.QueryAsync<ExportRUserStepLogDto>(logSql);

            var closeTimeDic = logs
                .Where(x => x.Step == stepClosingConfirm)
                .GroupBy(x => x.ProblemId)
                .ToDictionary(g => g.Key, g => g.Max(x => x.AddDate));

            var latestHandlerDic = logs
                .Where(x => x.Step != stepClosingConfirm)
                .GroupBy(x => (x.ProblemId, x.Step))
                .ToDictionary(
                    g => g.Key,
                    g => g.OrderByDescending(x => x.AddDate).ThenByDescending(x => x.ID).First().AddUser);

            var userIds = latestHandlerDic.Values.Distinct().ToList();
            var nameDic = new Dictionary<int, string>();
            if (userIds.Count > 0)
            {
                var nameSql = $@"SELECT ID, Name FROM info.dbo.Employee WITH(NOLOCK) WHERE ID IN ({string.Join(",", userIds)})";
                var empList = await dapperHelperCoreInfo.QueryAsync<ExportRUserEmpDto>(nameSql);
                foreach (var emp in empList)
                {
                    nameDic[emp.ID] = emp.Name;
                }
            }

            foreach (var row in list)
            {
                row.RUserName = "";
                if (!typeDic.TryGetValue(row.ID, out var typeInfo))
                {
                    continue;
                }
                var problemType = typeInfo.ProblemType;
                if (typeInfo.EditProblemTypeTime.HasValue
                    && typeInfo.OldProblemType.HasValue
                    && closeTimeDic.TryGetValue(row.ID, out var closeTime)
                    && typeInfo.EditProblemTypeTime.Value > closeTime)
                {
                    problemType = typeInfo.OldProblemType.Value;
                }
                var step = GetExportResponsibleStep(problemType);
                if (!step.HasValue)
                {
                    continue;
                }
                if (!latestHandlerDic.TryGetValue((row.ID, step.Value), out var userId))
                {
                    continue;
                }
                if (nameDic.TryGetValue(userId, out var name))
                {
                    row.RUserName = name;
                }
            }
        }

        /// <summary>
        /// 导出责任人对应的流程节点：硬件/软件/结构/制程优化→责任人确认；物料→SQE跟进；工厂制程→工厂制程分析；资料→工程确认。
        /// </summary>
        private static int? GetExportResponsibleStep(int problemType)
        {
            switch (problemType)
            {
                case 1:
                case 2:
                case 6:
                case 7:
                    return (int)ZCTracking_ProblemOpeEnum.Confirm;
                case 3:
                    return (int)ZCTracking_ProblemOpeEnum.FollowSQE;
                case 4:
                    return (int)ZCTracking_ProblemOpeEnum.ConfirmVersion;
                case 5:
                    return (int)ZCTracking_ProblemOpeEnum.FactoryAnalysis;
                default:
                    return null;
            }
        }

        private class ExportRUserTypeDto
        {
            public int ID { get; set; }
            public int ProblemType { get; set; }
            public int? OldProblemType { get; set; }
            public DateTime? EditProblemTypeTime { get; set; }
        }

        private class ExportRUserStepLogDto
        {
            public int ProblemId { get; set; }
            public int Step { get; set; }
            public int AddUser { get; set; }
            public DateTime AddDate { get; set; }
            public int ID { get; set; }
        }

        private class ExportRUserEmpDto
        {
            public int ID { get; set; }
            public string Name { get; set; }
        }

        public async Task<PageModel<ProblemListDto>> ProblemReportListByMonth(int pageIndex, int pageSize, int reportType, int problemType, int year, int month, string sort, string orderBy, string factory, decimal minRate = 100, decimal maxRate = 100)
        {
            var param = new Dapper.DynamicParameters();
            var whereSql = " where p.IsDelete=0 and year(p.adddate)=@Year ";
            param.Add("Year", year);
            if (month > 0)
            {
                whereSql += " and MONTH(p.AddDate)=@Month";
                param.Add("Month", month);
            }
            if (problemType > 0)
            {
                whereSql += " and p.ProblemType =@ProblemType";
                param.Add("ProblemType", problemType);
            }
            switch (reportType)
            {
                case 1: break; //所有问题
                case 2://停线次数
                    whereSql += "  and p.IsStop=1";
                    break;
                case 3://不良问题
                    whereSql += " and p.Rate is not null and p.Rate>=@MinRate AND Rate<=@MaxRate  ";
                    param.Add("MinRate", minRate);
                    param.Add("MaxRate", maxRate);
                    break;
                default:
                    whereSql += " and 1!=1 ";
                    break;
            }
            if (!string.IsNullOrWhiteSpace(factory))
            {
                whereSql += " and p.factory=@Factory";
                param.Add("Factory", factory);
            }
            var sortColumn = ResolveProblemListSortColumn(sort);
            var sortDir = ResolveSortDirection(orderBy);
            param.Add("RowStart", (pageIndex - 1) * pageSize);
            param.Add("RowEnd", pageIndex * pageSize);
            var sql = $@"SELECT ROW_NUMBER() OVER(ORDER BY {sortColumn} {sortDir}) rowId,* into #temp1 
FROM (SELECT p.ID,p.Numbers,p.FoundDate,p.Factory,
CASE p.Factory WHEN '04' THEN '柯洱斯'  WHEN '05' THEN '亮亮' WHEN '09' THEN '惠州百富' ELSE '' END FactoryName
,pn.ProductName,p.ProblemType,CASE p.ProblemType WHEN '1' THEN '硬件问题' WHEN '2' THEN '软件问题' WHEN '3' THEN '物料问题' WHEN '4' THEN '资料问题' WHEN '5' THEN '工厂制程' WHEN '6' THEN '结构问题' 
WHEN '7' THEN '制程优化' ELSE '' END ProblemTypeStr
,p.ProblemDesc,p.Status,p.MemberListName,pn.series,p.IsStop,p.StopStatus,p.StopDate,p.ImpactQty,p.BadQty,p.Station,p.Improve,p.AddUser,e.Name AddUserName,pn.ProductIds,p.MemberList,p.CInvCode,i.cInvName,p.VenCode,v.cVenName,po.OrderNumers,i.cInvStd,p.CAR,p.CARID,p.Rate,p.OutPutStatus,p.ProblemLevel,p.AddDate,p.Reason,p.MHead,p.ProdQty
FROM dbo.ZCTracking_ProblemList p WITH(NOLOCK)
left JOIN 
(SELECT b.problemId,
STUFF((SELECT ','+a.productname FROM dbo.ZCTracking_ProductNames a WITH(NOLOCK) WHERE a.problemId=b.problemId FOR XML PATH('')),1,1,'') AS ProductName,
STUFF((SELECT ','+CAST(a.ProductId AS NVARCHAR(50)) FROM dbo.ZCTracking_ProductNames a WITH(NOLOCK) WHERE a.problemId=b.problemId FOR XML PATH('')),1,1,'') AS ProductIds
,STUFF((SELECT ','+a.series FROM (SELECT problemId,series FROM ZCTracking_ProductNames WITH(NOLOCK) GROUP BY problemid,series) a WHERE a.problemId=b.problemId FOR XML PATH('')),1,1,'') AS series
FROM dbo.ZCTracking_ProductNames b WITH(NOLOCK)
GROUP BY b.problemId
) pn ON pn.ProblemId=p.ID 
left JOIN (
	SELECT o.problemId,STUFF((SELECT ','+a.ordernumber FROM ZCTracking_ProblemOrders a WITH(NOLOCK) WHERE a.problemId=o.problemId FOR XML PATH ('')),1,1,'') AS OrderNumers FROM ZCTracking_ProblemOrders o WITH(NOLOCK) GROUP BY o.problemId
) po ON po.ProblemId=p.ID
left JOIN INFO.dbo.Employee e WITH(NOLOCK) ON p.AddUser=e.ID
LEFT JOIN info.dbo.Inventory i WITH(NOLOCK) ON i.cInvCode=p.CInvCode
LEFT JOIN TEMPERP.UFDATA_999_2021.dbo.Vendor v WITH(NOLOCK) ON v.cVenCode=p.VenCode
LEFT JOIN dbo.ZCTracking_ProblemSteplog l WITH(NOLOCK) ON l.ProblemId=p.ID and Step<>1
LEFT JOIN dbo.ZCTracking_ProblemOrders pos WITH(NOLOCK) ON pos.ProblemId=p.ID
LEFT JOIN info.dbo.NewProduct np WITH(NOLOCK) ON np.PartNumber=pos.PartNumber
{whereSql}
GROUP BY p.ID,p.Numbers,p.FoundDate,p.Factory,pn.ProductName,p.ProblemType,p.ProblemType,p.ProblemDesc,p.Status,p.MemberListName,pn.series,p.IsStop,p.StopStatus,p.StopDate,p.ImpactQty,p.BadQty
,p.Station,p.Improve,p.AddUser,e.Name,pn.ProductIds,p.MemberList,p.CInvCode,i.cInvName,p.VenCode,v.cVenName,po.OrderNumers,i.cInvStd,p.CAR,p.CARID,p.Rate,p.OutPutStatus,p.ProblemLevel,p.AddDate,p.Reason,
p.MHead,p.ProdQty) a

SELECT * FROM #temp1 t1 WHERE t1.rowId >@RowStart and t1.rowId<=@RowEnd ORDER BY rowId
SELECT COUNT(*) total FROM #temp1 t1

drop table #temp1 
";
            var data = await dapperHelperCoreInfo.QueryMultipleAsync<ProblemListDto>(sql, param);
            return data;
        }
        public async Task<List<MoOrderProblemModel>> GetProblemListByOrderNumber(string orderNumber)
        {
            var sql = @$"SELECT p.ID ProblemID,p.Numbers OrderNumber,p.Factory,p.ProblemType,p.AddDate,p.ProblemDesc FROM dbo.ZCTracking_ProblemList p
JOIN dbo.ZCTracking_ProblemOrders o ON p.ID=o.ProblemId 
WHERE o.OrderNumber='{orderNumber}'";
            return await dapperHelperCoreInfo.QueryAsync<MoOrderProblemModel>(sql);
        }
        public async Task<List<int>> GetProblemStateGroup()
        {
            var data = repository.Find(x => x.IsDelete == 0).Select(x => x.Status).Distinct().ToList();
            var iqcStatus = repository.Find(x => x.IsDelete == 0 && x.IQCStatus.HasValue).Select(x => x.IQCStatus.Value).Distinct().ToList();
            data.AddRange(iqcStatus);
            var pendingPrevention = await dapperHelperInfo.ExecuteScalarAsync<int>(
                "SELECT COUNT(1) FROM dbo.tbTask WITH(NOLOCK) WHERE ftable = @Table AND fstat = N'已接受'",
                new { Table = preventionTable });
            if (pendingPrevention > 0)
            {
                data.Add((int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly);
            }
            // 36 归并到筛选「效果确认」(30)；37 为「预防对策确认」页签
            data = data.Select(x => x == (int)ZCTracking_ProblemStatusEnum.EffectConfirmOnly
                    ? (int)ZCTracking_ProblemStatusEnum.EffectConfirm
                    : x)
                .ToList();
            return data.Distinct().ToList();
        }

        /// <summary>
        /// tbTask 待办行（预防对策确认并行节点）。
        /// </summary>
        private class PreventionTaskRow
        {
            public string frecID { get; set; }
            /// <summary>待办接收人（INFO.tbTask.fuserID）</summary>
            public string fuserID { get; set; }
        }

        /// <summary>
        /// 按 INFO.tbTask 批量查询并行「预防对策确认」待办处理人。
        /// </summary>
        private async Task<Dictionary<int, (string UserIds, string Names)>> GetPendingPreventionConfirmMembersMapAsync(IEnumerable<int> problemIds)
        {
            var result = new Dictionary<int, (string UserIds, string Names)>();
            var ids = problemIds?.Distinct().Select(x => x.ToString()).ToList();
            if (ids == null || ids.Count == 0)
            {
                return result;
            }
            var sql = @"SELECT CAST(frecID AS NVARCHAR(50)) AS frecID, fuserID
FROM dbo.tbTask WITH(NOLOCK)
WHERE ftable = @Table AND fstat = N'已接受' AND frecID IN @Ids";
            var taskRows = await dapperHelperInfo.QuerySqlAsync<PreventionTaskRow>(sql, new { Table = preventionTable, Ids = ids });
            if (taskRows == null || taskRows.Count == 0)
            {
                return result;
            }
            foreach (var group in taskRows.GroupBy(x => x.frecID))
            {
                if (!int.TryParse(group.Key, out var problemId))
                {
                    continue;
                }
                var userIds = group.Select(x => x.fuserID).Where(x => !string.IsNullOrWhiteSpace(x)).Distinct().ToList();
                if (userIds.Count == 0)
                {
                    continue;
                }
                var idStr = string.Join(",", userIds);
                var names = await _hrEmployeeService.GetNameByIDAsync(idStr);
                result[problemId] = (idStr, names);
            }
            return result;
        }

        /// <summary>
        /// 按 INFO.tbTask 批量查询指定 ftable、已接受待办对应的问题 Id。
        /// </summary>
        private async Task<HashSet<int>> GetPendingTaskProblemIdsAsync(string table, IEnumerable<int> problemIds)
        {
            var result = new HashSet<int>();
            var ids = problemIds?.Distinct().Select(x => x.ToString()).ToList();
            if (string.IsNullOrWhiteSpace(table) || ids == null || ids.Count == 0)
            {
                return result;
            }
            var sql = @"SELECT CAST(frecID AS NVARCHAR(50)) AS frecID
FROM dbo.tbTask WITH(NOLOCK)
WHERE ftable = @Table AND fstat = N'已接受' AND frecID IN @Ids";
            var taskRows = await dapperHelperInfo.QuerySqlAsync<PreventionTaskRow>(sql, new { Table = table, Ids = ids });
            if (taskRows == null)
            {
                return result;
            }
            foreach (var row in taskRows)
            {
                if (int.TryParse(row.frecID, out var problemId))
                {
                    result.Add(problemId);
                }
            }
            return result;
        }

        /// <summary>
        /// 查询展示用：按待办将并行阶段主状态规范为 30/36/37（不写库，兼容旧单仍为 30 的数据）。
        /// </summary>
        private static int ApplyParallelConfirmStatusOnView(int problemType, int status, bool effectPending, bool preventionPending)
        {
            if (!NeedPreventionConfirm(problemType))
            {
                return status;
            }
            if (status != (int)ZCTracking_ProblemStatusEnum.EffectConfirm
                && status != (int)ZCTracking_ProblemStatusEnum.EffectConfirmOnly
                && status != (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly)
            {
                return status;
            }
            if (effectPending && preventionPending)
            {
                return (int)ZCTracking_ProblemStatusEnum.EffectConfirm;
            }
            if (effectPending)
            {
                return (int)ZCTracking_ProblemStatusEnum.EffectConfirmOnly;
            }
            if (preventionPending)
            {
                return (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly;
            }
            return status;
        }

        /// <summary>
        /// 并行阶段库内主状态与待办不一致时写回 30/36/37，避免查询改展示、库仍为 30。
        /// </summary>
        private void QueueParallelStatusWriteBack(int problemId, int currentStatus, int expectedStatus)
        {
            if (currentStatus == expectedStatus || !IsParallelConfirmStatus(currentStatus))
            {
                return;
            }
            var entity = new ZCTracking_ProblemList
            {
                ID = problemId,
                Status = expectedStatus
            };
            if (expectedStatus == (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly)
            {
                entity.MemberList = "";
                entity.MemberListName = "";
                repository.Update(entity, x => new { x.Status, x.MemberList, x.MemberListName });
            }
            else
            {
                repository.Update(entity, x => new { x.Status });
            }
        }

        /// <summary>
        /// 详情：填充预防对策确认处理人；主状态与待办不一致时写回库。
        /// </summary>
        private async Task FillPendingPreventionConfirmAsync(ProblemInfoModel problemInfo)
        {
            if (problemInfo == null)
            {
                return;
            }
            var map = await GetPendingPreventionConfirmMembersMapAsync(new[] { problemInfo.ID });
            var effectPending = await _pubTaskService.GetTaskCount(xgfTable, problemInfo.ID) > 0;
            if (map.TryGetValue(problemInfo.ID, out var members))
            {
                problemInfo.PreventionMemberList = members.UserIds;
                problemInfo.PreventionMemberListName = members.Names;
            }
            var expected = ApplyParallelConfirmStatusOnView(
                problemInfo.ProblemType, problemInfo.Status, effectPending, map.ContainsKey(problemInfo.ID));
            QueueParallelStatusWriteBack(problemInfo.ID, problemInfo.Status, expected);
            if (expected != problemInfo.Status)
            {
                problemInfo.Status = expected;
                if (expected == (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly)
                {
                    problemInfo.MemberList = "";
                    problemInfo.MemberListName = "";
                }
                await repository.SaveChangesAsync();
            }
        }

        /// <summary>
        /// 列表：填充预防对策确认处理人；主状态与待办不一致时写回库。
        /// </summary>
        private async Task FillPendingPreventionConfirmAsync(IEnumerable<ProblemListDto> rows)
        {
            if (rows == null)
            {
                return;
            }
            var rowList = rows as IList<ProblemListDto> ?? rows.ToList();
            if (rowList.Count == 0)
            {
                return;
            }
            var map = await GetPendingPreventionConfirmMembersMapAsync(rowList.Select(x => x.ID));
            var effectPendingIds = await GetPendingTaskProblemIdsAsync(xgfTable, rowList.Select(x => x.ID));
            var needSave = false;
            foreach (var row in rowList)
            {
                if (map.TryGetValue(row.ID, out var members))
                {
                    row.PreventionMemberList = members.UserIds;
                    row.PreventionMemberListName = members.Names;
                }
                var expected = ApplyParallelConfirmStatusOnView(
                    row.ProblemType, row.Status, effectPendingIds.Contains(row.ID), map.ContainsKey(row.ID));
                QueueParallelStatusWriteBack(row.ID, row.Status, expected);
                if (expected != row.Status)
                {
                    needSave = true;
                    row.Status = expected;
                    if (expected == (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly)
                    {
                        row.MemberList = "";
                        row.MemberListName = "";
                    }
                }
            }
            if (needSave)
            {
                await repository.SaveChangesAsync();
            }
        }

        /// <summary>
        /// 并行阶段当前状态：30 两者未完成，36 仅效果未完成，37 仅预防对策未完成。非并行返回 null。
        /// </summary>
        private static string BuildParallelConfirmCurrentStatusHtml(int status, int problemType, string effectHandlerNames, string preventionHandlerNames)
        {
            if (!IsParallelConfirmStatus(status))
            {
                return null;
            }
            string Line(string text, string names) =>
                $"<div><span>{text}</span><span style=\"color:red;\">{names}</span></div>";
            if (status == (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly)
            {
                return Line("预防对策确认", preventionHandlerNames);
            }
            if (status == (int)ZCTracking_ProblemStatusEnum.EffectConfirmOnly
                || !NeedPreventionConfirm(problemType))
            {
                return Line("效果确认", effectHandlerNames);
            }
            return Line("预防对策确认", preventionHandlerNames) + Line("效果确认", effectHandlerNames);
        }

        public async Task<ZCTracking_ProblemList> GetProblemInfo(int problemId)
        {
            return await repository.FindAsyncFirst(x => x.ID == problemId);
        }
        public async Task<bool> IsIQC()
        {
            var IQC_UserIds = await _pilotProductStreamItemService.GetUserIdsByStreamName("制程问题-物料问题", 1);
            return IQC_UserIds.Contains(UserContext.Current.UserId);
        }
        public async Task<ProblemInfoModel> GetProblemView(int problemId)
        {
            var riskStreamDb = repository.DbContext.Set<ZCTracking_RiskStream>();
            var data = await GetProblemInfo(problemId);
            var riskStreamList = await riskStreamDb.AsNoTracking().Where(x => x.ProblemId == problemId && x.Status == 1).ToListAsync();
            var problemInfo = new ProblemInfoModel();
            data.MapValueToEntity(problemInfo);
            if (riskStreamList.Any())
            {
                problemInfo.RiskStatus = riskStreamList[0].Step;
                problemInfo.RiskMemberList = string.Join(",", riskStreamList.Select(x => x.UserID).ToList());
                problemInfo.RiskMemberListName = await _hrEmployeeService.GetNameByIDAsync(problemInfo.RiskMemberList);
            }
            await FillPendingPreventionConfirmAsync(problemInfo);
            problemInfo.StepLogs = new List<ProblemStepLogModel>();
            var problemStepLogData = await zCTracking_ProblemSteplogService.GetProblemStepLogsByProblemId(problemId);
            var logUserList = await _hrEmployeeService.GetUserIdNameList(problemStepLogData.Select(x => x.AddUser).ToList());
            foreach (var item in problemStepLogData)
            {
                var logModel = new ProblemStepLogModel();
                item.MapValueToEntity(logModel);
                logModel.AddUserStr = logUserList.Find(x => x.Id == item.AddUser)?.Name;
                if (!string.IsNullOrWhiteSpace(item.FileUrl))
                {
                    logModel.File = new List<ProblemFile>();
                    var fileIds = item.FileUrl.Split(",");
                    foreach (var id in fileIds)
                    {
                        var intId = int.Parse(id);
                        var doc = await _documentListService.GetDocumentByID(intId);
                        logModel.File.Add(new ProblemFile
                        {
                            FileId = intId,
                            Key = doc?.DocumentRealName,
                            Value = _documentListService?.GetDocumentUrl(intId, true)
                        });
                    }
                }
                problemInfo.StepLogs.Add(logModel);
            }
            if (!string.IsNullOrWhiteSpace(data.CInvCode))
            {
                problemInfo.CInvDesc = await zCTrackingService.GetInvStdByInvCode(data.CInvCode);
            }
            if (!string.IsNullOrWhiteSpace(data.VenCode))
            {
                problemInfo.VenName = await zCTrackingService.GetVenNameByVenCode(data.VenCode);
            }
            if (data.RDepartment.HasValue)
            {
                problemInfo.RDepartmentStr = await _hrEmployeeService.GetUnitNameByUnitIdZLAsync(data.RDepartment.Value);
            }
            if (!string.IsNullOrWhiteSpace(data.AllReDepartment))
            {
                var departmentIds = problemInfo.AllReDepartment.Split(",");
                var unitAllNames = await _hrEmployeeService.GetALLUnitAsync();
                foreach (var id in departmentIds)
                {
                    problemInfo.AllReDepartmentName += "," + unitAllNames.FirstOrDefault(x => x.Id == int.Parse(id))?.Name;
                }
                problemInfo.AllReDepartmentName = problemInfo.AllReDepartmentName.TrimStart(',');
            }
            if (!string.IsNullOrWhiteSpace(data.RUser))
            {
                problemInfo.RUserStr = await _hrEmployeeService.GetNameByIDAsync(data.RUser);
            }
            if (problemInfo.DesignUser.HasValue)
            {
                problemInfo.DesignUserName = await _hrEmployeeService.GetNameByIDAsync(problemInfo.DesignUser.Value.ToString());
            }
            if (problemInfo.ProduceConfirmUser.HasValue)
            {
                problemInfo.DesignUserName = await _hrEmployeeService.GetNameByIDAsync(problemInfo.ProduceConfirmUser.Value.ToString());
            }
            if (!string.IsNullOrWhiteSpace(problemInfo.ReStartExamineUser))
            {
                problemInfo.ReStartExamineUserName = await _hrEmployeeService.GetNameByIDAsync(problemInfo.ReStartExamineUser);
            }
            if (!string.IsNullOrWhiteSpace(problemInfo.ReStartSchemeUser))
            {
                problemInfo.ReStartSchemeUserName = await _hrEmployeeService.GetNameByIDAsync(problemInfo.ReStartSchemeUser);
            }
            problemInfo.AddUserName = logUserList.Find(x => x.Id == problemInfo.AddUser)?.Name;
            problemInfo.StatusStr = DicConst.ProblemStatusDic.ContainsKey(problemInfo.Status) ? DicConst.ProblemStatusDic[problemInfo.Status] : "";
            problemInfo.ProductNames = await zCTracking_ProductNamesService.GetProductNamesByProblemId(problemInfo.ID);
            var orders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(problemInfo.ID);
            if (orders.Any())
            {
                foreach (var item in orders)
                {
                    var verInfoList = new List<dynamic>();
                    if (!string.IsNullOrWhiteSpace(item.Version))
                    {
                        var version = item.Version.Replace(",", "','");
                        verInfoList = await dapperHelperCoreInfo.QueryAsync<dynamic>(@$"SELECT v.FID,'V'+v.fname FName FROM info.dbo.tbprver v WITH(NOLOCK)
LEFT join info.dbo.newproduct m WITH(NOLOCK) on v.fmodelid=m.fid 
WHERE m.PartNumber='{item.PartNumber}' AND 'V'+v.fname IN ('{version}')");
                    }

                    problemInfo.Orders.Add(new
                    {
                        ID = item.ID,
                        ProblemId = item.ProblemId,
                        OrderNumber = item.OrderNumber,
                        PartNumber = item.PartNumber,
                        PartName = item.PartName,
                        IssueDate = item.IssueDate,
                        OrderQty = item.OrderQty,
                        ReceiptQty = item.ReceiptQty,
                        OnlineQty = item.OnlineQty,
                        Version = item.Version,
                        VerInfoList = verInfoList,
                    });
                }
            }
            problemInfo.XBOrders = await zCTracking_XBOrdersService.GetXBOrders(problemInfo.ID);
            problemInfo.IsIQC = await IsIQC();
            problemInfo.AfterSaleIssueCheckReasonList = await GetCheckReason(problemId);
            problemInfo.PossibleInvCodeList = await zCTracking_PossibleInvCodeService.GetPossibleInvCodeList(problemId);
            problemInfo.FiveWhyList = await GetFiveWhyListByProblemId(problemId);
            if (problemInfo.OutPutStatus.HasValue)
            {
                problemInfo.MoOrderAttrName = DicConst.MoOrderAttrDic[problemInfo.OutPutStatus.Value];
            }
            return problemInfo;
        }

        public async Task<List<AfterSaleIssueCheckReasonModel>> GetCheckReason(int problemId)
        {
            var sql = @$"SELECT a.*,r.ReasonDesc,p.PhenomenonDesc,c.ClassName,c.TypeName 
FROM dbo.ZCTracking_CheckReason a WITH(NOLOCK)
LEFT JOIN dbo.AfterSaleIssueClassPhenomenonReason r WITH(NOLOCK) ON a.ReasonID = r.ID
LEFT JOIN dbo.AfterSaleIssueClassPhenomenon p WITH(NOLOCK) ON a.PhenomenonID = p.ID
LEFT JOIN dbo.AfterSaleIssueClass c WITH(NOLOCK) ON a.ClassID = c.ID
WHERE a.ProblemId = '{problemId}'
ORDER BY r.ReasonDesc";
            return await dapperHelperCoreInfo.QueryAsync<AfterSaleIssueCheckReasonModel>(sql);
        }

        public async Task<WebResponseContent> ReStartExamine(ReStartExamineDto dto)
        {
            var logDb = repository.DbContext.Set<ZCTracking_ProblemSteplog>();

            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemID);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemID);
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemID);

            var stopToEmail = "";
            var stopCCEmail = "";
            var sendEmail = UserContext.Current.UserInfo.Email;
            var sendUserName = UserContext.Current.UserName;
            var taskName = "";
            var sendReStopLog = await logDb.Where(x => x.ProblemId == dto.ProblemID && x.Step == ZCTracking_ProblemOpeEnum.ReStartScheme.GetEnumIntValue()).OrderByDescending(x => x.AddDate).FirstOrDefaultAsync();
            stopToEmail = await _hrEmployeeService.GetEmailFromIDAsync(sendReStopLog.AddUser.ToString());
            if (dto.Result == 0)
            {
                problemInfo.StopStatus = 6;
                repository.Update(problemInfo, x => new { x.StopStatus });

                await logDb.AddAsync(new ZCTracking_ProblemSteplog
                {
                    ProblemId = dto.ProblemID,
                    Step = (int)ZCTracking_ProblemOpeEnum.ReStartExamine,
                    StepStr = "停线重启审核",
                    AddUser = UserContext.Current.UserId,
                    AddDate = DateTime.Now,
                    Result = dto.Result.ToString(),
                    Measures = $"停线重启不同意{(!string.IsNullOrWhiteSpace(dto.Remark) ? $",备注:{dto.Remark}" : "")}",
                    Opinon = dto.Remark,
                });
                await repository.SaveChangesAsync();

                taskName = $"国内制程问题单【" + problemInfo.Numbers + "】待填写停线重启方案";
                await _pubTaskService.AddTaskAsync(stopRsUser, dto.ProblemID, taskName, sendReStopLog.AddUser, DateTime.Now, DateTime.Now.AddDays(3));
            }
            else
            {
                problemInfo.StopStatus = 5;
                repository.Update(problemInfo, x => new { x.StopStatus });
                await logDb.AddAsync(new ZCTracking_ProblemSteplog
                {
                    ProblemId = dto.ProblemID,
                    Step = (int)ZCTracking_ProblemOpeEnum.ReStartExamine,
                    StepStr = "停线重启审核",
                    AddUser = UserContext.Current.UserId,
                    AddDate = DateTime.Now,
                    Result = dto.Result.ToString(),
                    Measures = $"停线重启同意{(!string.IsNullOrWhiteSpace(dto.Remark) ? $",备注:{dto.Remark}" : "")}",
                    Opinon = dto.Remark,
                });
                await repository.SaveChangesAsync();

                taskName = $"国内制程问题单【" + problemInfo.Numbers + "】停线重启审核同意";
            }
            await _pubTaskService.FinishTaskMultiAsync(stopRsUserExamine, dto.ProblemID.ToString());
            var context = await PersonLiableHtml("", problemInfo, products, problemOrders, (ZCTracking_ProblemStatusEnum)problemInfo.Status);
            if (dto.Result == 0)
            {
                Mail.SendMailSMTPBeltGog(sendEmail, sendUserName, stopToEmail, stopCCEmail, "", taskName, context, "2423", "制程问题追踪", "0", null);
            }
            else
            {
                var toEmail = "";
                var addUserInfo = await _hrEmployeeService.GetEmployeeByIdAsync(problemInfo.AddUser);
                if (addUserInfo != null && addUserInfo.Status == 1)
                {
                    toEmail = await _hrEmployeeService.GetEmailFromIDAsync(problemInfo.AddUser.ToString());
                }
                else
                {
                    var lead = await _hrEmployeeService.GetEmpLead(problemInfo.AddUser);
                    toEmail = await _hrEmployeeService.GetEmailFromIDAsync(lead.ToString());
                }
                Mail.SendMailSMTPBeltGog(sendEmail, sendUserName, toEmail, stopToEmail, "", taskName, context, "2423", "制程问题追踪", "0", null);
            }
            return WebResponseContent.OK_obj();
        }
        public async Task<WebResponseContent> ReStartScheme(ResultConfirmDto dto)
        {
            var logDb = repository.DbContext.Set<ZCTracking_ProblemSteplog>();

            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);

            var stopToEmail = "";
            var sendEmail = UserContext.Current.Email;
            var sendUserName = UserContext.Current.UserName;
            //其中物料问题，审核人指定为崔娟，其它类型为处理人的上级主管（组的主管或部门经理）
            if (problemInfo.ProblemType == 3)
            {
                problemInfo.ReStartExamineUser = "1287";
                stopToEmail = await _hrEmployeeService.GetEmailFromIDAsync("1287");
            }
            else
            {
                var lead = await _hrEmployeeService.GetEmpLead(UserContext.Current.UserId);
                problemInfo.ReStartExamineUser = lead.ToString();
                stopToEmail = await _hrEmployeeService.GetEmailFromIDAsync(lead.ToString());
            }
            problemInfo.StopStatus = 4;
            problemInfo.ReStartScheme = dto.Confirmation;
            repository.Update(problemInfo, x => new { x.StopStatus, x.ReStartScheme, x.ReStartExamineUser });

            await logDb.AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = ZCTracking_ProblemOpeEnum.ReStartScheme.GetEnumIntValue(),
                StepStr = "责任人填写重启方案",
                AddUser = UserContext.Current.UserId,
                AddDate = DateTime.Now,
                Result = "",
                Measures = "",
                Opinon = dto.Confirmation,
            });

            var save = await repository.SaveChangesAsync();

            var taskName = $"国内制程问题单【" + problemInfo.Numbers + "】停线重启审核";
            if (save > 0)
            {
                await _pubTaskService.FinishTaskMultiAsync(stopRsUser, dto.ProblemId.ToString());
                var taskSql = _pubTaskService.GetAddTaskSql(stopRsUserExamine, dto.ProblemId.ToString(), taskName, problemInfo.ReStartExamineUser.Split(",").Select(x => int.Parse(x)).ToList(), DateTime.Now, DateTime.Now.AddDays(3));
                if (!string.IsNullOrWhiteSpace(taskSql))
                {
                    dapperHelperInfo.ExecuteAsync(taskSql);
                }
            }
            var context = await PersonLiableHtml("", problemInfo, products, problemOrders, (ZCTracking_ProblemStatusEnum)problemInfo.Status);
            Mail.SendMailSMTPBeltGog(sendEmail, sendUserName, stopToEmail, "", "", taskName, context, "2423", "制程问题追踪", "0", null);
            return WebResponseContent.OK_obj();
        }
        public async Task<bool> ReStart(int problemId, string remark, DateTime date)
        {
            repository.Update(new ZCTracking_ProblemList
            {
                ID = problemId,
                StopStatus = 2,
            }, x => new { x.StopStatus });
            var startDate = date.ToString("yyyy-MM-dd");
            await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = problemId,
                Step = (int)ZCTracking_ProblemOpeEnum.ReStart,
                StepStr = "停线重启",
                AddUser = UserContext.Current.UserId,
                AddDate = DateTime.Now,
                Result = startDate,
                Measures = $"{UserContext.Current.UserName}停线重启,重启时间：{startDate}{(!string.IsNullOrWhiteSpace(remark) ? $",备注:{remark}" : "")}",
                Opinon = remark,
            });
            var save = await repository.SaveChangesAsync() > 0;
            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(problemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(problemId);
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == problemId);

            var productIds = products.Select(x => x.ProductId).ToList();
            var emailUserIds = new List<int>();
            var zoCount = false;
            if (productIds.Any())
            {
                var productIdStr = string.Join(",", productIds);
                emailUserIds = await dapperHelperCoreInfo.QueryAsync<int>(@$"SELECT DISTINCT d.Lead FROM info.dbo.ProductMaintainPerson p
LEFT JOIN info.dbo.Department d ON p.maintainunit=d.ID
WHERE p.BigProID in ({productIdStr})");
                zoCount = await IsZLProd(productIdStr);
            }
            var toEmail = await _hrEmployeeService.GetEmailFromIDAsync(string.Join(",", emailUserIds));

            var emailgd = await mailAddressService.GetMailAddress("国内制程停线通知");
            var stopToEmail = emailgd.MailTo;
            var stopCCEmail = emailgd.MailCC;
            //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
            if (problemInfo.ProblemType == 3)
            {
                stopToEmail += $";{await GetWLEmail(problemInfo.CInvCode)}";
                stopCCEmail += $";{cuijuan}";
            }
            var productArrStr = string.Join(",", products.Select(x => x.ProductName));
            var orderArrStr = string.Join(",", problemOrders.Select(x => x.OrderNumber));
            switch (problemInfo.Factory)
            {
                case "04"://04柯洱斯
                    var pksEmail = await mailAddressService.GetMailAddress("国内制程停线通知(PKS)");
                    stopToEmail += $";{pksEmail.MailTo}";
                    stopCCEmail += $";{pksEmail.MailCC}";
                    break;
                case "05"://05亮亮
                    var llEmail = await mailAddressService.GetMailAddress("国内制程停线通知(亮亮)");
                    stopToEmail += $";{llEmail.MailTo}";
                    stopCCEmail += $";{llEmail.MailCC}";
                    break;
                case "09"://09惠州百富
                    var hlEmail = await mailAddressService.GetMailAddress("国内制程停线通知(惠州百富)");
                    stopToEmail += $";{hlEmail.MailTo}";
                    stopCCEmail += $";{hlEmail.MailCC}";
                    break;
            }
            stopToEmail += $";{toEmail}";
            //if (zoCount)
            //{
            //    var zlEmail = await mailAddressService.GetMailAddress("国内制程涉及兆珑机型停线或重启通知");
            //    stopToEmail += $";{zlEmail.MailTo}";
            //}
            stopCCEmail += ";" + await GetStopCCMail(problemInfo.Numbers);
            var context = await PersonLiableHtml("", problemInfo, products, problemOrders, (ZCTracking_ProblemStatusEnum)problemInfo.Status);
            Mail.SendMailSMTPBeltGog(UserContext.Current.UserInfo.Email, UserContext.Current.UserName, stopToEmail, stopCCEmail.Trim(';'), "", $"{productArrStr}停线重启通知", context, "2423", "制程问题追踪", "0", null);

            return save;
        }

        public async Task<bool> TransferUser(TransferUserDto dto)
        {
            var now = DateTime.Now;
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var isPreventionConfirmTransfer = dto.ThisStatus == (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly;
            if (dto.User <= 0)
            {
                throw new BusinessException("请选择有效的转移对象");
            }
            if (isPreventionConfirmTransfer && !await IsSupervisorOrManagerAsync(dto.User))
            {
                throw new BusinessException("预防对策确认任务仅支持转移给小组主管或部门经理");
            }
            var save = 0;

            var currentUserId = UserContext.Current.UserId;
            #region 检测是否有菜单的游览权限，没有就添加游览权限
            await IsExistMenuAuth(dto.User);
            #endregion
            var memberListName = new SelectItem
            {
                Key = dto.User.ToString()
            };
            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);

            //日志记录
            await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.Transfer,
                StepStr = "任务转移",
                AddUser = currentUserId,
                AddDate = now,
                Result = dto.User.ToString(),
                Measures = $"{now:yyyy/MM/dd},{UserContext.Current.UserName}将任务转移给{memberListName.Value}",
                Opinon = dto.Remark,
                ProblemStatus = problemInfo.Status,
                MemberList = currentUserId.ToString(),
            });
            save = await repository.SaveChangesAsync();
            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var sendMail = UserContext.Current.UserInfo.Email;

            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var newEmail = await GetNewEmail(dto.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            var ccMailList = newEmail;//抄送人
            ccMailList = string.Join(";", ccMailList.Split(";").Distinct());

            var taskName = string.Empty;
            var statusEnum = isPreventionConfirmTransfer
                ? (ZCTracking_ProblemStatusEnum)problemInfo.Status
                : (ZCTracking_ProblemStatusEnum)dto.ThisStatus;
            var urlHtml = "";
            var email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
            var fmemo = $"任务已转移给工号{dto.User}";
            switch (problemInfo.ProblemType)
            {
                case 1:
                case 2:
                case 6:
                case 7:
                    //软、硬件问题
                    switch (dto.ThisStatus)
                    {
                        case 1:
                            await _pubTaskService.CancelTaskAddMemo(GetfTable(problemInfo.ProblemType) + 1, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //指定责任人
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待指定责任人";
                            await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType) + 1, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/QualityAssignDutyMan?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 2:
                            await _pubTaskService.CancelTaskAddMemo(GetfTable(problemInfo.ProblemType) + 2, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待责任人确认";
                            await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 2, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            memberListName.Key = problemInfo.MemberList.Replace(currentUserId.ToString(), memberListName.Key);
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            if (problemInfo.IsStop.Value == 1 && problemInfo.StopStatus.Value == 6)
                            {
                                var stopTaskName = $"国内制程问题单【" + problemInfo.Numbers + "】待填写停线重启方案";
                                await _pubTaskService.CancelTaskAddMemo(stopRsUser, dto.ProblemId.ToString(), currentUserId, fmemo);
                                await _pubTaskService.AddTaskAsync(stopRsUser, dto.ProblemId, stopTaskName, dto.User, now, now.AddDays(3));
                                problemInfo.ReStartSchemeUser = dto.User.ToString();
                            }
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/QualityDutyManConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 36:
                        case 30:
                            await _pubTaskService.CancelTaskAddMemo(xgfTable, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                            await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 37:
                            await _pubTaskService.CancelTaskAddMemo(preventionTable, dto.ProblemId.ToString(), currentUserId, fmemo);
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待预防对策确认";
                            await _pubTaskService.AddTaskAsync(preventionTable, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/PreventionConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 31:
                            await _pubTaskService.CancelTaskAddMemo(jafTable, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待结案确认";
                            await _pubTaskService.AddTaskAsync(jafTable, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/EndConfirm?idid={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                    }
                    break;
                case 3://物料问题
                    switch (dto.ThisStatus)
                    {
                        case 6:
                            if (dto.IsIQC)
                            {
                                taskName = "国内制程问题单【" + problemInfo.Numbers + "】待IQC确认";
                                await _pubTaskService.CancelTaskAddMemo(GetfTable(problemInfo.ProblemType) + 1, dto.ProblemId.ToString(), currentUserId, fmemo);
                                await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType) + 1, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            }
                            else
                            {
                                taskName = "国内制程问题单【" + problemInfo.Numbers + "】待工厂填写退货数量";
                                await _pubTaskService.CancelTaskAddMemo(GetfTable(problemInfo.ProblemType) + 2, dto.ProblemId.ToString(), currentUserId, fmemo);
                                await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType) + 2, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            }
                            memberListName.Key = problemInfo.MemberList.Replace(currentUserId.ToString(), memberListName.Key);
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/IQCConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 7:
                            await _pubTaskService.CancelTaskAddMemo(GetfTable(problemInfo.ProblemType) + 3, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待填写退货单号";
                            await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 3, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/WriteQuitNo?id={dto.ProblemId}'>点击进入该链接页面</a>";

                            await _pubTaskService.CancelTaskAddMemo(stopRsUser, dto.ProblemId.ToString(), currentUserId, fmemo);
                            await _pubTaskService.AddTaskAsync(stopRsUser, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //日志记录
                            break;
                        case 8:
                            await _pubTaskService.CancelTaskAddMemo(GetfTable(problemInfo.ProblemType) + 4, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待SQE确认";
                            await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 4, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/SQEFollowCheck?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 9:
                            await _pubTaskService.CancelTaskAddMemo(GetfTable(problemInfo.ProblemType) + 5, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待设计变更";
                            await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 5, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/ChangeDesign?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 10:
                            await _pubTaskService.CancelTaskAddMemo(GetfTable(problemInfo.ProblemType) + 6, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待设计变更后SQE确认";
                            await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 6, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/SQEConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            //发邮件
                            break;
                        case 11:
                            await _pubTaskService.CancelTaskAddMemo(GetfTable(problemInfo.ProblemType) + 7, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待IQC填写意见";
                            await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 7, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/IQCConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";

                            await _pubTaskService.CancelTaskAddMemo(stopRsUser, dto.ProblemId.ToString(), currentUserId, fmemo);
                            await _pubTaskService.AddTaskAsync(stopRsUser, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            break;
                        case 36:
                        case 30:
                            await _pubTaskService.CancelTaskAddMemo(xgfTable, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                            await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 37:
                            await _pubTaskService.CancelTaskAddMemo(preventionTable, dto.ProblemId.ToString(), currentUserId, fmemo);
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待预防对策确认";
                            await _pubTaskService.AddTaskAsync(preventionTable, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/PreventionConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 31:
                            await _pubTaskService.CancelTaskAddMemo(jafTable, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待结案确认";
                            await _pubTaskService.AddTaskAsync(jafTable, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/EndConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        default:
                            break;
                    }
                    break;
                case 4: //资料问题
                    switch (dto.ThisStatus)
                    {
                        case 3:
                            await _pubTaskService.CancelTaskAddMemo(GetfTable(dto.ProblemType) + 1, dto.ProblemId.ToString(), currentUserId, fmemo);
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待确认";
                            await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType) + 1, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProjectConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";

                            #region 停线任务
                            if (problemInfo.IsStop.Value == 1 && problemInfo.StopStatus.Value == 6)
                            {
                                var stopTaskName = $"国内制程问题单【" + problemInfo.Numbers + "】待填写停线重启方案";
                                await _pubTaskService.CancelTaskAddMemo(stopRsUser, dto.ProblemId.ToString(), currentUserId, fmemo);
                                await _pubTaskService.AddTaskAsync(stopRsUser, dto.ProblemId, stopTaskName, dto.User, now, now.AddDays(3));
                                problemInfo.ReStartSchemeUser = dto.User.ToString();
                            }
                            #endregion
                            break;
                        case 4:
                            await _pubTaskService.CancelTaskAddMemo(GetfTable(dto.ProblemType) + 2, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待PMC确认";
                            await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 2, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            memberListName.Key = problemInfo.MemberList.Replace(currentUserId.ToString(), memberListName.Key);
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            //发邮件                         
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/PMCConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 36:
                        case 30:
                            await _pubTaskService.CancelTaskAddMemo(xgfTable, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                            await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 37:
                            await _pubTaskService.CancelTaskAddMemo(preventionTable, dto.ProblemId.ToString(), currentUserId, fmemo);
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待预防对策确认";
                            await _pubTaskService.AddTaskAsync(preventionTable, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/PreventionConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 31:
                            await _pubTaskService.CancelTaskAddMemo(jafTable, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待结案确认";
                            await _pubTaskService.AddTaskAsync(jafTable, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/EndConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                    }
                    break;
                case 5: //制程问题
                    switch (dto.ThisStatus)
                    {
                        case 5:
                            await _pubTaskService.CancelTaskAddMemo(GetfTable(dto.ProblemType) + 1, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待分析";
                            await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType) + 1, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/FactoryConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                        case 36:
                        case 30:
                            await _pubTaskService.CancelTaskAddMemo(xgfTable, dto.ProblemId.ToString(), currentUserId, fmemo);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                            await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskName, dto.User, now, now.AddDays(3));
                            //发邮件
                            urlHtml += $"<a  href='{FreqUsedConst.webSite}/QualityManage/EndConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            break;
                    }
                    break;
            }
            if (problemInfo.ProblemType == 3 && !isPreventionConfirmTransfer)
            {
                //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                email += $";{await GetWLEmail(problemInfo.CInvCode)}";
                ccMailList += $";{cuijuan}";
            }
            if (isPreventionConfirmTransfer)
            {
                email = await _hrEmployeeService.GetEmailFromIDAsync(dto.User.ToString());
                ccMailList = await GetDeptManagerEmailsByUserIdAsync(dto.User);
            }
            // 预防对策确认与效果确认并行：只转 preventionTable 待办，不改主单 MemberList（效果确认处理人）
            if (!isPreventionConfirmTransfer)
            {
                problemInfo.MemberList = memberListName.Key;
                problemInfo.MemberListName = memberListName.Value;
                if (statusEnum == ZCTracking_ProblemStatusEnum.DesignChange) //设计变更转移
                {
                    problemInfo.DesignUser = dto.User;
                }
                else if (statusEnum == ZCTracking_ProblemStatusEnum.Confirm) //责任人确认转移
                {
                    problemInfo.RUser = problemInfo.RUser.Replace(currentUserId.ToString(), memberListName.Key);
                    var user = await _hrEmployeeService.GetEmployeeByIdAsync(dto.User);
                    problemInfo.RDepartment = user.Unit;
                }
                repository.Update(problemInfo, x => new { x.MemberList, x.MemberListName, x.DesignUser, x.RUser, x.RDepartment, x.ReStartSchemeUser });
            }
            var productIds = string.Join(",", productIdList);
            var context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, statusEnum);
            await SendEmail(sendMail, email, ccMailList, taskName, context, productIds);
            save += await repository.SaveChangesAsync();
            return save > 0;
        }

        public async Task<bool> ProblemReject(ProblemRejectDto dto)
        {
            var save = 0;
            var now = DateTime.Now;
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var memberListName = new SelectItem();

            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;
            string context, email, taskName = string.Empty;
            if (problemInfo.ProblemType == 3)
            {
                email = await GetWLEmail(problemInfo.CInvCode);
                ccMailList += $";{cuijuan}";
            }
            var problemLog = new ZCTracking_ProblemSteplog();

            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var productIds = string.Join(",", productIdList);
            var newEmail = await GetNewEmail(dto.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            if (!string.IsNullOrWhiteSpace(ccMailList))
            {
                ccMailList += ";" + newEmail;
            }
            else
            {
                ccMailList = newEmail;
            }
            var rejectCc = BuildRejectCcMail(dto.ThisStatus, sendMail, ccMailList);
            var rejectLog = ResolveParallelRejectStepLog(dto.ThisStatus);
            //日志记录：并行节点驳回在操作记录中显示所在节点名称
            await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = rejectLog.Step,
                StepStr = rejectLog.StepStr,
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Measures = $"{now:yyyy/MM/dd},{UserContext.Current.UserName},驳回任务,驳回说明:{dto.Remark}",
                Opinon = dto.Remark,
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            save += await repository.SaveChangesAsync();
            if (IsRejectParallelToDutyMan(problemInfo.ProblemType, dto.ThisStatus))
            {
                await RejectParallelConfirmToDutyManAsync(dto, problemInfo, products, problemOrders, sendMail, rejectCc, productIds, now);
                return save > 0;
            }
            var urlHtml = "";
            var sql = $" update info.dbo.tbTask SET fstat='已取消',fmemo='驳回' WHERE (ftable='{stopRsUserExamine}' OR ftable='{stopRsUser}') AND frecID='{dto.ProblemId}' AND fstat='已接受';";
            switch (problemInfo.ProblemType)
            {
                case 1:
                case 2:
                case 6:
                case 7:
                    //软、硬件问题
                    switch (dto.ThisStatus)
                    {
                        case 2:
                            await _pubTaskService.FinishTaskMultiAsync("ZCTracking_ProblemSoftware2", problemInfo.ID.ToString());
                            var stepId = 1;
                            //指定责任人
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待指定责任人";
                            //获取上一次任务的责任人                          
                            problemLog = await zCTracking_ProblemSteplogService.GetStepLog(dto.ProblemId, ZCTracking_ProblemStatusEnum.ResponsibleUser);
                            memberListName.Key = problemLog.MemberList;
                            //var userId = (await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameRJ, stepId))[0];
                            var userIds = problemLog.MemberList.Split(",").Select(x => int.Parse(x)).ToList();
                            await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType) + stepId, dto.ProblemId.ToString(), taskName, userIds, now, now.AddDays(3)));
                            //修改问题当前责任人
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            //发邮件
                            problemInfo.MemberListName = memberListName.Value;
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/QualityAssignDutyMan?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ResponsibleUser, dto.Remark);
                            email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                            await SendEmail(sendMail, email, rejectCc, taskName, context, productIds);
                            repository.Update(new ZCTracking_ProblemList
                            {
                                ID = dto.ProblemId,
                                RDepartment = null,
                                RUser = null,
                                Status = dto.Status,
                                MemberList = memberListName.Key,
                                MemberListName = memberListName.Value,
                            }, x => new { x.RDepartment, x.RUser, x.Status, x.MemberList, x.MemberListName });
                            break;
                        case 36:
                        case 30:
                            await _pubTaskService.FinishTaskAsync(xgfTable, problemInfo.ID);
                            //获取上一次任务的责任人                          
                            problemLog = await zCTracking_ProblemSteplogService.GetStepLog(dto.ProblemId, ZCTracking_ProblemStatusEnum.Confirm);
                            memberListName.Key = problemLog.MemberList;
                            var userName = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            memberListName.Value = userName;
                            problemInfo.MemberListName = userName;
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/QualityDutyManConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.Confirm, dto.Remark);
                            //责任人确认
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待责任人确认";
                            await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + "2", dto.ProblemId, taskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                            /* 发邮件 */
                            email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                            await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            break;
                        case 31:
                            await _pubTaskService.FinishTaskAsync(jafTable, problemInfo.ID);
                            //获取上一次任务的责任人                          
                            problemLog = await zCTracking_ProblemSteplogService.GetStepLog(dto.ProblemId, ZCTracking_ProblemStatusEnum.EffectConfirm);
                            //修改问题当前责任人
                            memberListName.Key = problemLog.MemberList;
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            //效果确认
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                            await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                            //发邮件              
                            problemInfo.MemberListName = memberListName.Value;
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.EffectConfirm, dto.Remark);
                            email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                            await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            break;
                    }
                    break;
                case 3://物料问题
                    switch (dto.ThisStatus)
                    {
                        case 7: //TODO 退货不需要驳回
                            break;
                        case 8:
                            problemInfo.IQCStatus = null;
                            problemInfo.IQCMemberList = "";
                            problemInfo.IQCMemberListName = "";
                            var riskStreamDb = repository.DbContext.Set<ZCTracking_RiskStream>();
                            var riskStreamList = await riskStreamDb.Where(x => x.ProblemId == dto.ProblemId).ToListAsync();
                            if (riskStreamList.Any())
                            {
                                riskStreamDb.RemoveRange(riskStreamList);
                            }
                            var ftable = GetfTable(problemInfo.ProblemType);
                            //清除其他在执行的任务    
                            sql += @$" update info.dbo.tbTask SET fstat='已取消',fmemo='驳回' WHERE ftable LIKE '{ftable}%' AND ftable <>'{ftable}7' AND frecID='{dto.ProblemId}'  AND fstat='已接受' ";
                            await _pubTaskService.FinishTaskAsync(ftable + 4, dto.ProblemId);
                            //获取上一次任务的责任人                          
                            problemLog = await zCTracking_ProblemSteplogService.GetStepLog(dto.ProblemId, ZCTracking_ProblemStatusEnum.IQCOpinion);
                            //发起任务
                            memberListName.Key = problemLog.MemberList;
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待IQC填写意见";
                            await _pubTaskService.AddTaskAsync(ftable + 7, dto.ProblemId, taskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            //发邮件
                            problemInfo.MemberListName = memberListName.Value;
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/IQCOpinion?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.FillOrderNo, dto.Remark);
                            email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                            await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            break;
                        case 9:
                            await _pubTaskService.FinishTaskAsync(GetfTable(problemInfo.ProblemType) + 5, dto.ProblemId);
                            //获取上一次任务的责任人                          
                            problemLog = await zCTracking_ProblemSteplogService.GetStepLog(dto.ProblemId, ZCTracking_ProblemStatusEnum.FollowSQE);
                            memberListName.Key = problemLog.MemberList;
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待SQE跟进";
                            await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 4, dto.ProblemId, taskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                            //发邮件
                            problemInfo.MemberListName = memberListName.Value;
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/SQEFollowCheck?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.FollowSQE, dto.Remark);
                            email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                            await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            break;
                        case 10:
                            await _pubTaskService.FinishTaskAsync(GetfTable(problemInfo.ProblemType) + 6, dto.ProblemId);
                            //获取上一次任务的责任人                          
                            problemLog = await zCTracking_ProblemSteplogService.GetStepLog(dto.ProblemId, ZCTracking_ProblemStatusEnum.DesignChange);
                            memberListName.Key = problemLog.MemberList;
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            //发起任务
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待设计变更";
                            await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 5, dto.ProblemId, taskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                            //发邮件
                            problemInfo.MemberListName = memberListName.Value;
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ChangeDesign?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.DesignChange, dto.Remark);
                            email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                            await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            break;
                        case 37:
                        case 36:
                        case 30:
                            await CancelParallelTasksBeforeBackAsync(problemInfo, dto.ThisStatus);
                            if (problemInfo.IsDesignChange == 0)
                            {
                                await SetRejectHandlerAsync(memberListName,
                                    await GetStepOpeHandlerIdAsync(dto.ProblemId, ZCTracking_ProblemOpeEnum.FollowSQE),
                                    "未找到SQE跟进处理人，无法驳回");
                                taskName = "国内制程问题单【" + problemInfo.Numbers + "】待SQE跟进";
                                await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 4, dto.ProblemId, taskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                                //发邮件
                                problemInfo.MemberListName = memberListName.Value;
                                urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/SQEFollowCheck?id={dto.ProblemId}'>点击进入该链接页面</a>";
                                context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.FollowSQE, dto.Remark);
                                email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                                await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            }
                            else
                            {
                                if (problemInfo.DesignConfirmResult == 1) //如果是设计变更改善
                                {
                                    await SetRejectHandlerAsync(memberListName,
                                        await GetStepOpeHandlerIdAsync(dto.ProblemId, ZCTracking_ProblemOpeEnum.DesignChange),
                                        "未找到设计变更处理人，无法驳回");
                                    taskName = "国内制程问题单【" + problemInfo.Numbers + "】待设计变更";
                                    await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 5, dto.ProblemId, taskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                                    //发邮件
                                    problemInfo.MemberListName = memberListName.Value;
                                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ChangeDesign?id={dto.ProblemId}'>点击进入该链接页面</a>";
                                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.DesignChange, dto.Remark);
                                    email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                                    await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                                }
                                else  //如果是保持现状或者挂起
                                {
                                    await SetRejectHandlerAsync(memberListName,
                                        await GetStepOpeHandlerIdAsync(dto.ProblemId, ZCTracking_ProblemOpeEnum.ChangeConfirmSQE),
                                        "未找到设计变更后SQE确认处理人，无法驳回");
                                    taskName = "国内制程问题单【" + problemInfo.Numbers + "】待设计变更后SQE确认";
                                    await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 6, dto.ProblemId, taskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                                    //发邮件
                                    problemInfo.MemberListName = memberListName.Value;
                                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/SQEConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ChangeConfirmSQE, dto.Remark);
                                    email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                                    await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                                }

                            }
                            break;
                        case 31:
                            await _pubTaskService.FinishTaskAsync(jafTable, problemInfo.ID);
                            //获取上一次任务的责任人                          
                            problemLog = await zCTracking_ProblemSteplogService.GetStepLog(dto.ProblemId, ZCTracking_ProblemStatusEnum.EffectConfirm);
                            //效果确认
                            var taskNameThis = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                            await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskNameThis, problemInfo.AddUser, now, now.AddDays(3));
                            //修改问题当前责任人
                            memberListName.Key = problemLog.MemberList;
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            //发邮件
                            problemInfo.MemberListName = memberListName.Value;
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.EffectConfirm, dto.Remark);
                            email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                            await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            break;
                    }
                    break;
                case 4: //资料问题
                    switch (dto.ThisStatus)
                    {
                        case 4:
                            await _pubTaskService.FinishTaskMultiAsync(GetfTable(problemInfo.ProblemType) + 2, dto.ProblemId.ToString());
                            await SetRejectHandlerAsync(memberListName,
                                await GetStepOpeHandlerIdAsync(dto.ProblemId, ZCTracking_ProblemOpeEnum.ConfirmVersion),
                                "未找到工程确认处理人，无法驳回");
                            var zlTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待确认是否涉及版本";
                            await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType) + 1, dto.ProblemId, zlTaskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                            //修改问题当前责任人
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            //发邮件
                            problemInfo.MemberListName = memberListName.Value;
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProjectConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ConfirmVersion, dto.Remark);
                            email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                            await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            break;
                        case 37:
                        case 36:
                        case 30:
                            await CancelParallelTasksBeforeBackAsync(problemInfo, dto.ThisStatus);
                            if (Convert.ToBoolean(problemInfo.IsChangeOrderV))
                            {
                                await SetRejectHandlerAsync(memberListName,
                                    await GetStepOpeHandlerIdAsync(dto.ProblemId, ZCTracking_ProblemOpeEnum.ChangeVersion),
                                    "未找到PMC确认处理人，无法驳回");
                                taskName = "国内制程问题单【" + problemInfo.Numbers + "】待PMC确认";
                                await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 2, dto.ProblemId, taskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                                //修改问题当前责任人
                                memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                                problemInfo.MemberListName = memberListName.Value;
                                urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/PMCConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                                context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ChangeVersion, dto.Remark);
                                email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                                await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            }
                            else
                            {
                                await SetRejectHandlerAsync(memberListName,
                                    await GetStepOpeHandlerIdAsync(dto.ProblemId, ZCTracking_ProblemOpeEnum.ConfirmVersion),
                                    "未找到工程确认处理人，无法驳回");
                                taskName = "国内制程问题单【" + problemInfo.Numbers + "】待确认是否涉及版本";
                                await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType) + 1, dto.ProblemId, taskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                                //修改问题当前责任人
                                memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                                //发邮件
                                problemInfo.MemberListName = memberListName.Value;
                                urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProjectConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                                context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ConfirmVersion, dto.Remark);
                                email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                                await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            }
                            break;
                        case 31:
                            await _pubTaskService.FinishTaskAsync(jafTable, problemInfo.ID);
                            //获取上一次任务的责任人                          
                            problemLog = await zCTracking_ProblemSteplogService.GetStepLog(dto.ProblemId, ZCTracking_ProblemStatusEnum.EffectConfirm);
                            //修改问题当前责任人
                            memberListName.Key = problemLog.MemberList;
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            //效果确认
                            var taskNameThis = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                            await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskNameThis, int.Parse(memberListName.Key), now, now.AddDays(3));
                            //发邮件
                            problemInfo.MemberListName = memberListName.Value;
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.EffectConfirm, dto.Remark);
                            email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                            await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            break;
                    }
                    break;
                case 5: //工厂制程
                    switch (dto.ThisStatus)
                    {
                        case 36:
                        case 30:
                            await _pubTaskService.FinishTaskAsync(xgfTable, problemInfo.ID);
                            await SetRejectHandlerAsync(memberListName,
                                await GetStepOpeHandlerIdAsync(dto.ProblemId, ZCTracking_ProblemOpeEnum.FactoryAnalysis),
                                "未找到工厂制程分析处理人，无法驳回");
                            taskName = "国内制程问题单【" + problemInfo.Numbers + "】待分析";
                            await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType) + 1, dto.ProblemId, taskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                            /* 发邮件 */
                            problemInfo.MemberListName = memberListName.Value;
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/FactoryConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.FactoryAnalysis, dto.Remark);
                            email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                            await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            break;
                        case 31:
                            await _pubTaskService.FinishTaskAsync(jafTable, problemInfo.ID);
                            //获取上一次任务的责任人                          
                            problemLog = await zCTracking_ProblemSteplogService.GetStepLog(dto.ProblemId, ZCTracking_ProblemStatusEnum.EffectConfirm);
                            //修改问题当前责任人
                            memberListName.Key = problemLog.MemberList;
                            memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                            //效果确认
                            var taskNameThis = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                            await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskNameThis, int.Parse(memberListName.Key), now, now.AddDays(3));
                            //发邮件
                            problemInfo.MemberListName = memberListName.Value;
                            urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                            context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.EffectConfirm, dto.Remark);
                            email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                            await SendEmail(sendMail, email, rejectCc, "国内制程问题单【" + problemInfo.Numbers + "】被驳回", context, productIds);
                            break;
                    }
                    break;
            }
            if (dto.ThisStatus != 2)
            {
                var nextStatus = dto.Status;
                if (dto.ThisStatus == (int)ZCTracking_ProblemStatusEnum.ClosingConfirm)
                {
                    nextStatus = await ResolveParallelConfirmStatusAsync(dto.ProblemId, problemInfo.ProblemType);
                }
                repository.Update(new ZCTracking_ProblemList
                {
                    ID = dto.ProblemId,
                    Status = nextStatus,
                    MemberList = memberListName.Key,
                    MemberListName = memberListName.Value,
                    IQCStatus = problemInfo.IQCStatus,
                    IQCMemberList = problemInfo.IQCMemberList,
                    IQCMemberListName = problemInfo.IQCMemberListName,
                    Confirmation = problemInfo.Confirmation,
                    ConfirmUser = problemInfo.ConfirmUser,
                    ConfirmDate = problemInfo.ConfirmDate,
                }, x => new { x.Status, x.MemberList, x.MemberListName, x.IQCStatus, x.IQCMemberList, x.IQCMemberListName, x.Confirmation, x.ConfirmUser, x.ConfirmDate });
            }
            //取消任务
            await dapperHelperInfo.ExecuteAsync(sql);
            save += await repository.SaveChangesAsync();
            return save > 0;
        }
        #region 软硬件问题
        public async Task<bool> ResponsibleUser(int problemId, int department, string userId, string ccMail)
        {
            var save = 0;
            var now = DateTime.Now;
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == problemId);
            problemInfo.RDepartment = department;
            problemInfo.RUser = userId;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var existTask = await _pubTaskService.IsExistTask(GetfTable(problemInfo.ProblemType) + "1", problemId);
            if (!existTask)
            {
                throw new Exception("当前用户不存在此任务");
            }
            //完成当前任务
            await _pubTaskService.FinishTaskMultiAsync(GetfTable(problemInfo.ProblemType) + "1", problemId.ToString());
            var userName = await _hrEmployeeService.GetNameByIDAsync(userId);
            if (problemInfo.IsStop.Value == 1)
            {
                problemInfo.StopStatus = 6;
            }
            repository.Update(new ZCTracking_ProblemList
            {
                ID = problemId,
                RDepartment = department,
                RUser = userId,
                Status = (int)ZCTracking_ProblemStatusEnum.Confirm,
                MemberListName = userName,
                MemberList = userId,
                ReStartSchemeUser = userId,
                StopStatus = problemInfo.StopStatus,
            }, x => new { x.RDepartment, x.RUser, x.Status, x.MemberListName, x.MemberList, x.ReStartSchemeUser, x.StopStatus });
            //发起任务
            var taskName = "国内制程问题单【" + problemInfo.Numbers + "】待责任人确认";
            var userIdArr = userId.Split(',');

            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(problemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(problemId);
            problemInfo.MemberListName = userName;

            var sendMail = UserContext.Current.UserInfo.Email;
            string email;
            //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
            if (problemInfo.ProblemType == 3)
            {
                email = await GetWLEmail(problemInfo.CInvCode);
                ccMail += $";{cuijuan}";
            }
            var stopTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待填写停线重启方案";
            foreach (var id in userIdArr)
            {
                #region 检测是否有菜单的游览权限，没有就添加游览权限
                var idInt = int.Parse(id);
                await IsExistMenuAuth(idInt);
                #endregion
                await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + "2", problemId, taskName, idInt, now, now.AddDays(3));

                #region 停线任务
                if (problemInfo.IsStop.Value == 1)
                {
                    await _pubTaskService.AddTaskAsync(stopRsUser, problemId, stopTaskName, idInt, now, now.AddDays(3));
                }
                #endregion
            }

            var departmentName = await _hrEmployeeService.GetUnitNameByUnitIdZLAsync(department);
            //日志记录
            await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = problemId,
                Step = (int)ZCTracking_ProblemOpeEnum.ResponsibleUser,
                StepStr = "指定责任人",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Measures = $"{UserContext.Current.UserName}指定责任人：{userName},责任部门：{departmentName}",
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            save += await repository.SaveChangesAsync();

            /* 发邮件 */
            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            email = await _hrEmployeeService.GetEmailFromIDAsync(userId);
            if (!string.IsNullOrWhiteSpace(ccMail))
            {
                ccMail += ";" + newEmail;
            }
            else
            {
                ccMail = newEmail;
            }
            if (problemInfo.Factory == "09")//惠州百富
            {
                var hzEmail = await mailAddressService.GetMailAddress("惠州软硬件问题指定责任人抄送人");
                ccMail += ";" + hzEmail.MailTo;
            }
            var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/QualityDutyManConfirm?id={problemId}'>点击进入该链接页面</a>"; ;
            string context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.Confirm);
            var productIds = string.Join(',', productIdList);
            await SendEmail(sendMail, email, ccMail.Trim(';'), taskName, context, productIds);
            if (problemInfo.IsStop.Value == 1)
                await SendEmail(sendMail, email, "", stopTaskName, context, productIds);
            return save > 0;
        }

        public async Task<bool> UserConfirm(UserConfirmDto dto)
        {
            var logDb = repository.DbContext.Set<ZCTracking_ProblemSteplog>();

            var save = 0;
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var oldType = problemInfo.ProblemType;
            var taskTable = GetfTable(problemInfo.ProblemType);
            //判断是否存在任务
            var existTask = await _pubTaskService.IsExistTask(taskTable + 2, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }

            var measures = string.Empty;

            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;//抄送人
            string email, context;
            Func<Task> afterSaveAction = null;
            //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
            if (problemInfo.ProblemType == 3)
            {
                email = await GetWLEmail(problemInfo.CInvCode);
                ccMailList += $";{cuijuan}";
            }
            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var productIds = string.Join(',', productIdList);
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            var urlHtml = "";
            if (problemInfo.Factory == "09")//惠州百富
            {
                var hzEmail = await mailAddressService.GetMailAddress("惠州软硬件问题指定责任人抄送人");
                ccMailList += ";" + hzEmail.MailTo;
            }
            if (dto.Confirm)
            {
                problemInfo.Prevention = dto.Prevention;
                problemInfo.Measures = dto.Measures;
                problemInfo.RConfirm = Convert.ToInt32(dto.Confirm);
                problemInfo.RCompleteTime = dto.RCompleteTime;
                problemInfo.DesignConfirmResult = dto.DesignConfirmResult;
                problemInfo.Reason = dto.Reason;

                //修改问题当前责任人
                var memberListName = new SelectItem
                {
                    Key = problemInfo.AddUser.ToString()
                };

                //发起任务
                var taskNameThis = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                if (dto.IsSubmit)
                {
                    var keepEffect = await HasKeptEffectConfirmResultAsync(problemInfo);
                    if (keepEffect)
                    {
                        // 已办结的效果确认结果保留，不再发起效果确认待办
                        problemInfo.MemberList = "";
                        problemInfo.MemberListName = "";
                        problemInfo.Status = NeedPreventionConfirm(problemInfo.ProblemType)
                            ? (int)ZCTracking_ProblemStatusEnum.PreventionConfirmOnly
                            : (int)ZCTracking_ProblemStatusEnum.EffectConfirm;
                        afterSaveAction = async () =>
                        {
                            await ReenterParallelConfirmAsync(problemInfo, productIds, sendMail, ccMailList);
                        };
                    }
                    else
                    {
                    memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                    problemInfo.MemberListName = memberListName.Value;
                    problemInfo.MemberList = memberListName.Key;
                    problemInfo.Status = (int)ZCTracking_ProblemStatusEnum.EffectConfirm;
                    afterSaveAction = async () =>
                    {
                        await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskNameThis, problemInfo.AddUser, now, now.AddDays(3));
                        await ReenterParallelConfirmAsync(problemInfo, productIds, sendMail, ccMailList);
                        //发邮件              
                        urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                        context = await GetEmailHtml(dto.ProblemId, urlHtml);
                        email = await _hrEmployeeService.GetEmailFromIDAsync(problemInfo.AddUser.ToString());
                        if (!string.IsNullOrWhiteSpace(ccMailList))
                        {
                            ccMailList += ";" + newEmail;
                        }
                        else
                        {
                            ccMailList = newEmail;
                        }
                        await SendEmail(sendMail, email, ccMailList, taskNameThis, context, productIds);
                    };
                    }
                }
                if (dto.IsSubmit)
                {
                    repository.Update(problemInfo,
                        x => new { x.Prevention, x.Measures, x.MemberList, x.MemberListName, x.Status, x.RConfirm, x.RCompleteTime, x.DesignConfirmResult, x.Reason });
                }
                else
                {
                    repository.Update(problemInfo,
                        x => new { x.Prevention, x.Measures, x.RConfirm, x.RCompleteTime, x.DesignConfirmResult, x.Reason });
                }
                var designConfirmResultText = dto.DesignConfirmResult.HasValue ? DicConst.DesignConfirmResultDic[dto.DesignConfirmResult.Value] : "未选择";
                measures = $"{UserContext.Current.UserName}确认结果：是,处理结果：{designConfirmResultText},改善措施：{dto.Measures},预防对策：{dto.Prevention},原因分析：{dto.Reason}";
            }
            else
            {
                var stepId = 1;
                switch (dto.ProblemType)
                {
                    case 1:
                    case 2:
                    case 6:
                        //发起任务
                        var taskName = "国内制程问题单【" + problemInfo.Numbers + "】待指定责任人";
                        var memberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameRJ, stepId);
                        var userId = memberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();

                        problemInfo.Prevention = dto.Prevention;
                        problemInfo.Measures = dto.Measures;
                        problemInfo.ProblemType = dto.ProblemType.Value;
                        problemInfo.RConfirm = Convert.ToInt32(dto.Confirm);
                        problemInfo.CInvCode = dto.CInvCode;
                        problemInfo.OldProblemType = oldType;
                        problemInfo.Reason = dto.Reason;
                        problemInfo.ReStartSchemeUser = problemInfo.ReStartSchemeUser;
                        if (dto.IsSubmit)
                        {
                            problemInfo.Status = GetInitStatus(dto.ProblemType.Value);
                            problemInfo.MemberListName = memberListName.Value;
                            problemInfo.MemberList = memberListName.Key;
                            afterSaveAction = async () =>
                            {
                                await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType.Value) + stepId, dto.ProblemId.ToString(), taskName, userId, now, now.AddDays(3)));
                                /* 发邮件 */
                                urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/QualityAssignDutyMan?id={dto.ProblemId}'>点击进入该链接页面</a>";
                                context = await GetEmailHtml(dto.ProblemId, urlHtml);
                                email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                                if (!string.IsNullOrWhiteSpace(ccMailList))
                                {
                                    ccMailList += ";" + newEmail;
                                }
                                else
                                {
                                    ccMailList = newEmail;
                                }
                                await SendEmail(sendMail, email, ccMailList, taskName, context, productIds);
                            };
                        }
                        //修改问题当前责任人
                        if (dto.IsSubmit)
                        {
                            repository.Update(problemInfo, x => new { x.Status, x.Prevention, x.Measures, x.MemberList, x.MemberListName, x.RConfirm, x.ProblemType, x.CInvCode, x.OldProblemType, x.Reason, x.ReStartSchemeUser });
                        }
                        else
                        {
                            repository.Update(problemInfo, x => new { x.Prevention, x.Measures, x.RConfirm, x.ProblemType, x.CInvCode, x.OldProblemType, x.Reason, x.ReStartSchemeUser });
                        }
                        break;
                    case 3:
                        var wltaskName = "国内制程问题单【" + problemInfo.Numbers + "】待IQC填写意见";
                        var userIds_IQC = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, stepId);
                        var userId_IQC = 0;
                        if (problemInfo.Factory == "04")//柯洱斯
                        {
                            userId_IQC = userIds_IQC[1];
                        }
                        if (problemInfo.Factory == "05")//亮亮
                        {
                            userId_IQC = userIds_IQC[1];
                        }
                        if (problemInfo.Factory == "09")//惠州百富
                        {
                            userId_IQC = userIds_IQC[0];
                        }
                        //修改问题当前责任人
                        var memberList = userId_IQC.ToString();

                        problemInfo.CInvCode = dto.CInvCode;
                        problemInfo.VenCode = dto.VenCode;
                        problemInfo.ProblemType = dto.ProblemType.Value;
                        problemInfo.OldProblemType = oldType;
                        problemInfo.Reason = dto.Reason;

                        if (dto.IsSubmit)
                        {
                            problemInfo.MemberList = memberList;
                            problemInfo.MemberListName = await _hrEmployeeService.GetNameByIDAsync(memberList);
                            problemInfo.Status = GetInitStatus(dto.ProblemType.Value);
                            afterSaveAction = async () =>
                            {
                                await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType.Value) + 7, dto.ProblemId, wltaskName, userId_IQC, now, now.AddDays(3));
                                /* 发邮件 */
                                email = await _hrEmployeeService.GetEmailFromIDAsync(memberList);
                                urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/IQCOpinion?id={dto.ProblemId}'>点击进入该链接页面</a>";
                                context = await GetEmailHtml(dto.ProblemId, urlHtml);
                                if (!string.IsNullOrWhiteSpace(ccMailList))
                                {
                                    ccMailList += ";" + newEmail;
                                }
                                else
                                {
                                    ccMailList = newEmail;
                                }
                                await SendEmail(sendMail, email, ccMailList, wltaskName, context, productIds);
                            };
                        }
                        if (dto.IsSubmit)
                        {
                            repository.Update(problemInfo, x => new { x.MemberList, x.MemberListName, x.Status, x.CInvCode, x.VenCode, x.ProblemType, x.OldProblemType, x.Reason });
                        }
                        else
                        {
                            repository.Update(problemInfo, x => new { x.CInvCode, x.VenCode, x.ProblemType, x.OldProblemType, x.Reason });
                        }
                        break;
                    case 4:
                        //发起任务
                        var zlTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待确认";
                        var zlmemberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameZL, stepId);
                        var zlUserId = zlmemberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();

                        //修改问题当前责任人
                        if (dto.IsSubmit)
                        {
                            repository.Update(new ZCTracking_ProblemList
                            {
                                ID = dto.ProblemId,
                                Status = GetInitStatus(dto.ProblemType.Value),
                                Prevention = dto.Prevention,
                                Measures = dto.Measures,
                                MemberListName = zlmemberListName.Value,
                                MemberList = zlmemberListName.Key,
                                ProblemType = dto.ProblemType.Value,
                                RConfirm = Convert.ToInt32(dto.Confirm),
                                OldProblemType = oldType,
                                Reason = dto.Reason,
                                ReStartSchemeUser = problemInfo.ReStartSchemeUser,
                            }, x => new { x.Status, x.Prevention, x.Measures, x.MemberList, x.MemberListName, x.RConfirm, x.ProblemType, x.OldProblemType, x.Reason, x.ReStartSchemeUser });
                        }
                        else
                        {
                            repository.Update(new ZCTracking_ProblemList
                            {
                                ID = dto.ProblemId,
                                Prevention = dto.Prevention,
                                Measures = dto.Measures,
                                ProblemType = dto.ProblemType.Value,
                                RConfirm = Convert.ToInt32(dto.Confirm),
                                OldProblemType = oldType,
                                Reason = dto.Reason,
                                ReStartSchemeUser = problemInfo.ReStartSchemeUser,
                            }, x => new { x.Prevention, x.Measures, x.RConfirm, x.ProblemType, x.OldProblemType, x.Reason, x.ReStartSchemeUser });
                        }
                        if (dto.IsSubmit)
                        {
                            afterSaveAction = async () =>
                            {
                                /* 发邮件 */
                                await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType.Value) + stepId, dto.ProblemId.ToString(), zlTaskName, zlUserId, now, now.AddDays(3)));
                                if (problemInfo.IsStop.Value == 1 && problemInfo.StopStatus.Value == 6)
                                {
                                    var stopTaskName = $"国内制程问题单【" + problemInfo.Numbers + "】待填写停线重启方案";
                                    await _pubTaskService.CancelTaskAddMemo(stopRsUser, dto.ProblemId.ToString(), UserContext.Current.UserId);
                                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(stopRsUser, dto.ProblemId.ToString(), stopTaskName, zlUserId, now, now.AddDays(3)));
                                    problemInfo.ReStartSchemeUser = zlmemberListName.Key;
                                }
                                problemInfo.Prevention = dto.Prevention;
                                problemInfo.Measures = dto.Measures;
                                problemInfo.MemberList = zlmemberListName.Key;
                                problemInfo.ProblemType = dto.ProblemType.Value;
                                problemInfo.RConfirm = Convert.ToInt32(dto.Confirm);
                                problemInfo.OldProblemType = oldType;
                                problemInfo.Reason = dto.Reason;
                                problemInfo.MemberListName = zlmemberListName.Value;
                                problemInfo.ProblemType = dto.ProblemType.Value;
                                urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProjectConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                                context = await GetEmailHtml(dto.ProblemId, urlHtml);
                                email = await _hrEmployeeService.GetEmailFromIDAsync(zlmemberListName.Key);
                                if (!string.IsNullOrWhiteSpace(ccMailList))
                                {
                                    ccMailList += ";" + newEmail;
                                }
                                else
                                {
                                    ccMailList = newEmail;
                                }
                                await SendEmail(sendMail, email, ccMailList, zlTaskName, context, productIds);
                            };
                        }
                        break;
                    case 5:
                        //发起任务
                        var zcTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待原因分析";
                        //修改问题当前责任人
                        var zcmemberListName = new SelectItem();
                        var zcmemberList = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameZC, stepId);
                        var zcUserId = 0;
                        if (problemInfo.Factory == "04")//柯洱斯
                        {
                            zcUserId = zcmemberList[1];
                            zcmemberListName.Key = zcUserId.ToString();
                        }
                        if (problemInfo.Factory == "05")//亮亮
                        {
                            zcUserId = zcmemberList[2];
                            zcmemberListName.Key = zcUserId.ToString();
                        }
                        if (problemInfo.Factory == "09")//惠州百富
                        {
                            zcUserId = zcmemberList[0];
                            zcmemberListName.Key = zcUserId.ToString();
                        }
                        zcmemberListName.Value = await _hrEmployeeService.GetNameByIDAsync(zcmemberListName.Key);
                        if (dto.IsSubmit)
                        {
                            repository.Update(new ZCTracking_ProblemList
                            {
                                ID = dto.ProblemId,
                                Status = GetInitStatus(dto.ProblemType.Value),
                                Prevention = dto.Prevention,
                                Measures = dto.Measures,
                                MemberListName = zcmemberListName.Value,
                                MemberList = zcmemberListName.Key,
                                ProblemType = dto.ProblemType.Value,
                                RConfirm = Convert.ToInt32(dto.Confirm),
                                OldProblemType = oldType,
                                Reason = dto.Reason,
                            }, x => new { x.Status, x.Prevention, x.Measures, x.MemberList, x.MemberListName, x.RConfirm, x.ProblemType, x.OldProblemType, x.Reason });
                        }
                        else
                        {
                            repository.Update(new ZCTracking_ProblemList
                            {
                                ID = dto.ProblemId,
                                Prevention = dto.Prevention,
                                Measures = dto.Measures,
                                ProblemType = dto.ProblemType.Value,
                                RConfirm = Convert.ToInt32(dto.Confirm),
                                OldProblemType = oldType,
                                Reason = dto.Reason,
                            }, x => new { x.Prevention, x.Measures, x.RConfirm, x.ProblemType, x.OldProblemType, x.Reason });
                        }

                        if (dto.IsSubmit)
                        {
                            afterSaveAction = async () =>
                            {
                                await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType.Value) + stepId, dto.ProblemId, zcTaskName, zcUserId, now, now.AddDays(3));
                                problemInfo.Prevention = dto.Prevention;
                                problemInfo.Measures = dto.Measures;
                                problemInfo.ProblemType = dto.ProblemType.Value;
                                problemInfo.RConfirm = Convert.ToInt32(dto.Confirm);
                                problemInfo.OldProblemType = oldType;
                                problemInfo.Reason = dto.Reason;
                                /* 发邮件 */
                                problemInfo.MemberListName = zcmemberListName.Value;
                                problemInfo.ProblemType = dto.ProblemType.Value;
                                urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/FactoryConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                                context = await GetEmailHtml(dto.ProblemId, urlHtml);
                                email = await _hrEmployeeService.GetEmailFromIDAsync(zcmemberListName.Key);
                                if (!string.IsNullOrWhiteSpace(ccMailList))
                                {
                                    ccMailList += ";" + newEmail;
                                }
                                else
                                {
                                    ccMailList = newEmail;
                                }
                                await SendEmail(sendMail, email, ccMailList, zcTaskName, context, productIds);
                            };
                        }
                        break;
                    case 7:
                        var yhTaskName = "国内制程问题单【" + problemInfo.Numbers + "】生产角色确认";
                        var yhMemberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameRJ, 5);
                        var yhUserId = yhMemberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();


                        //修改问题当前责任人
                        problemInfo.ProblemType = dto.ProblemType.Value;
                        if (dto.IsSubmit)
                        {
                            problemInfo.MemberListName = yhMemberListName.Value;
                            problemInfo.MemberList = yhMemberListName.Key;
                            problemInfo.Status = GetInitStatus(dto.ProblemType.Value);
                            repository.Update(problemInfo, x => new { x.MemberList, x.MemberListName, x.Status, x.ProblemType });
                        }
                        else
                        {
                            repository.Update(problemInfo, x => new { x.ProblemType });
                        }
                        if (dto.IsSubmit)
                        {
                            afterSaveAction = async () =>
                            {
                                await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType.Value) + 5, dto.ProblemId.ToString(), yhTaskName, yhUserId, now, now.AddDays(3)));
                                /* 发邮件 */
                                urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProduceConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                                context = await GetEmailHtml(dto.ProblemId, urlHtml);
                                email = await _hrEmployeeService.GetEmailFromIDAsync(yhMemberListName.Key);
                                email = string.Join(";", email.Split(";").Distinct());
                                if (!string.IsNullOrWhiteSpace(ccMailList))
                                {
                                    ccMailList += ";" + newEmail;
                                }
                                else
                                {
                                    ccMailList = newEmail;
                                }
                                await SendEmail(sendMail, email, ccMailList, yhTaskName, context, productIds);
                            };
                        }
                        break;
                    default:
                        break;
                }
                measures = $"{UserContext.Current.UserName}确认结果：否，原问题分类：{DicConst.ProblemTypeDic[oldType]}，修改问题分类为：{DicConst.ProblemTypeDic[dto.ProblemType.Value]},原因分析：{dto.Reason}";
            }

            var log = new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.Confirm,
                StepStr = "责任人确认",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Opinon = dto.Remark,
                Measures = measures,
                ProblemStatus = (int)ZCTracking_ProblemStatusEnum.Confirm,
                MemberList = UserContext.Current.UserId.ToString(),
            };
            if (!string.IsNullOrWhiteSpace(measures))
            {
                log.Measures = measures;
            }
            //日志记录
            await logDb.AddAsync(log);
            save += await repository.SaveChangesAsync();
            if (dto.IsSubmit)
            {
                await _pubTaskService.FinishTaskMultiAsync(taskTable + 2, dto.ProblemId.ToString());
                if (afterSaveAction != null)
                {
                    try
                    {
                        await afterSaveAction();
                    }
                    catch (Exception)
                    {
                        // 系统统一捕获异常日志；通知失败不影响主流程保存结果
                    }
                }
            }
            return save > 0;
        }
        #endregion

        public async Task<int> ResultConfirm(ResultConfirmDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }

            var existTask = await _pubTaskService.IsExistTask(xgfTable, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }

            //日志记录
            var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.EffectConfirm,
                StepStr = "效果确认",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Opinon = dto.Confirmation,
                Measures = $"{UserContext.Current.UserName}效果确认结果：{dto.Confirmation}",
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            await repository.SaveChangesAsync();
            problemInfo.Confirmation = dto.Confirmation;
            problemInfo.ConfirmUser = UserContext.Current.UserId;
            problemInfo.ConfirmDate = now;
            await _pubTaskService.FinishTaskAsync(xgfTable, dto.ProblemId);
            // 需预防对策确认且该待办未完成时，主状态改为 37（仅预防对策确认）
            if (!await TryEnterClosingConfirmAsync(problemInfo, now))
            {
                await PersistParallelConfirmStatusAsync(problemInfo);
            }
            return log.Entity.ID;
        }

        /// <summary>
        /// 当前登录人是否存在结构问题预防对策确认待办。
        /// </summary>
        public async Task<bool> HasPreventionConfirmTask(int problemId)
        {
            return await _pubTaskService.IsExistTask(preventionTable, problemId);
        }

        /// <summary>
        /// 预防对策确认：完成后刷新并行主状态；效果确认已完成则进入结案。
        /// </summary>
        public async Task<int> PreventionConfirm(PreventionConfirmDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            if (!NeedPreventionConfirm(problemInfo.ProblemType))
            {
                throw new Exception("当前问题类型不需要预防对策确认");
            }
            var existTask = await _pubTaskService.IsExistTask(preventionTable, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }
            if (string.IsNullOrWhiteSpace(dto.Opinon))
            {
                throw new Exception("请填写预防对策确认结果");
            }

            var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.PreventionConfirm,
                StepStr = "预防对策确认",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Opinon = dto.Opinon,
                Measures = $"{UserContext.Current.UserName}预防对策确认：{dto.Opinon}",
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            await repository.SaveChangesAsync();
            await _pubTaskService.FinishTaskAsync(preventionTable, dto.ProblemId);
            // 效果确认已完成时进入结案；否则主状态改为 36（仅效果确认）
            if (await TryEnterClosingConfirmAsync(problemInfo, now))
            {
                return log.Entity.ID;
            }
            await PersistParallelConfirmStatusAsync(problemInfo);
            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var sendMail = UserContext.Current.UserInfo.Email;
            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var productIds = string.Join(',', productIdList);
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            var taskName = "国内制程问题单【" + problemInfo.Numbers + "】预防对策确认完成";
            var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProblemDetail?id={dto.ProblemId}'>点击进入该链接页面</a>";
            var context = await GetEmailHtml(dto.ProblemId, urlHtml);
            var toMail = newEmail;
            if (string.IsNullOrWhiteSpace(toMail.Replace(";", "")))
            {
                toMail = await _hrEmployeeService.GetEmailFromIDAsync(problemInfo.AddUser.ToString());
            }
            await SendEmail(sendMail, toMail, sendMail, taskName, context, productIds);
            return log.Entity.ID;
        }

        /// <summary>
        /// 预防对策确认任务转移可选人员：在职的小组主管/副主管、部门经理/副经理。
        /// </summary>
        public async Task<List<IdNameModel>> GetPreventionTransferEmployees()
        {
            return await dapperHelperInfo.QuerySqlAsync<IdNameModel>(
                $@"SELECT e.ID AS Id, e.Name
FROM dbo.Employee e WITH(NOLOCK)
WHERE ISNULL(e.status, 0) = 1
AND e.ID IN ({PreventionOrgLeaderIdsSql})
ORDER BY e.Name",
                null);
        }

        /// <summary>
        /// 修改已完成的预防对策确认，不改变主流程与效果确认。
        /// </summary>
        public async Task<int> EditPreventionConfirm(PreventionConfirmDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题！");
            }
            if (problemInfo.Status == ZCTracking_ProblemStatusEnum.End.GetEnumIntValue())
            {
                throw new Exception("流程已结束！");
            }
            if (string.IsNullOrWhiteSpace(dto.Opinon))
            {
                throw new Exception("请填写预防对策确认结果");
            }
            var logDb = repository.DbContext.Set<ZCTracking_ProblemSteplog>();
            var stepLog = await logDb
                .Where(x => x.ProblemId == dto.ProblemId && x.Step == ZCTracking_ProblemOpeEnum.PreventionConfirm.GetEnumIntValue())
                .OrderByDescending(x => x.AddDate)
                .FirstOrDefaultAsync();
            if (stepLog == null)
            {
                throw new Exception("未找到预防对策确认记录");
            }
            stepLog.Measures = $"{DateTime.Today:yyyy-MM-dd},{UserContext.Current.UserName}修改预防对策确认：{dto.Opinon}";
            stepLog.Opinon = dto.Opinon;
            logDb.Update(stepLog);
            await repository.SaveChangesAsync();
            return stepLog.ID;
        }

        public async Task<int> EditResultConfirm(ResultConfirmDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题！");
            }
            if (problemInfo.Status == ZCTracking_ProblemStatusEnum.End.GetEnumIntValue())
            {
                throw new Exception("流程已结束！");
            }
            var logDb = repository.DbContext.Set<ZCTracking_ProblemSteplog>();
            var stepLog = await logDb.FirstOrDefaultAsync(x => x.ProblemId == dto.ProblemId && x.Step == ZCTracking_ProblemOpeEnum.EffectConfirm.GetEnumIntValue());
            stepLog.Measures = $"{DateTime.Today:yyyy-MM-dd},{UserContext.Current.UserName}修改结果：{dto.Confirmation}";
            stepLog.Opinon = dto.Confirmation;
            logDb.Update(stepLog);
            //日志记录            

            problemInfo.Confirmation = dto.Confirmation;
            problemInfo.ConfirmUser = UserContext.Current.UserId;
            problemInfo.ConfirmDate = now;
            repository.Update(problemInfo, x => new { x.Confirmation, x.ConfirmUser, x.ConfirmDate });
            await repository.SaveChangesAsync();
            return stepLog.ID;
        }
        public async Task<int> EndConfirm(EndConfirmDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var existTask = await _pubTaskService.IsExistTask(jafTable, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }
            if (NeedPreventionConfirm(problemInfo.ProblemType) && await HasPendingPreventionConfirmTaskAsync(dto.ProblemId))
            {
                throw new Exception("预防对策确认尚未完成，不能结案确认");
            }
            if (problemInfo.ProblemType == 3)
            {
                if (problemInfo.IQCStatus.HasValue)
                {
                    throw new Exception($"IQC与工厂未确认退货信息！请联系{problemInfo.IQCMemberListName}");
                }
            }
            //完成效果确认任务
            await _pubTaskService.FinishTaskMultiAsync(jafTable, dto.ProblemId.ToString());

            //日志记录
            var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.ClosingConfirm,
                StepStr = "结案确认",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Opinon = dto.ConfirmDesc,
                Measures = $"{UserContext.Current.UserName}结案结论：{dto.ConfirmDesc}",
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            var save = await repository.SaveChangesAsync();
            //标记流程结束
            repository.Update(new ZCTracking_ProblemList
            {
                ID = dto.ProblemId,
                Status = (int)ZCTracking_ProblemStatusEnum.End,
                MemberListName = "",
                MemberList = "",
            },
                x => new { x.Status, x.MemberListName, x.MemberList });
            problemInfo.MemberListName = "";

            /* 发邮件 */
            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var sendMail = UserContext.Current.UserInfo.Email;
            var toMail = await _hrEmployeeService.GetEmailFromIDAsync(problemInfo.AddUser.ToString());
            var ccMailList = sendMail;//抄送人
            //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
            if (problemInfo.ProblemType == 3)
            {
                toMail += $";{await GetWLEmail(problemInfo.CInvCode)}";
                ccMailList += $";{cuijuan}";
            }
            var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProblemDetail?id={dto.ProblemId}'>点击进入该链接页面</a>";
            var context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.End);
            string problemTypeStr = DicConst.ProblemTypeDic.ContainsKey(problemInfo.ProblemType) ? DicConst.ProblemTypeDic[problemInfo.ProblemType] : "";

            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var productIds = string.Join(',', productIdList);
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            if (!string.IsNullOrWhiteSpace(ccMailList))
            {
                ccMailList += ";" + newEmail;
            }
            else
            {
                ccMailList = newEmail;
            }
            save += await repository.SaveChangesAsync();
            await SendEmail(sendMail, toMail, ccMailList, "国内制程问题单【" + problemInfo.Numbers + "】已结束", context, productIds);
            return log.Entity.ID;
        }

        #region 资料问题

        public async Task<int> ConfirmVersion(ConfirmVersionDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var oldType = problemInfo.ProblemType;
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            #region 完成任务
            var taskTable = GetfTable(problemInfo.ProblemType);
            //判断是否存在任务
            var existTask = await _pubTaskService.IsExistTask(taskTable + 1, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }
            await _pubTaskService.FinishTaskMultiAsync(taskTable + 1, dto.ProblemId.ToString());
            #endregion

            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;//抄送人
            string email, context, desc, taskName = string.Empty;
            var memberListName = new SelectItem();
            var urlHtml = "";

            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var productIds = string.Join(',', productIdList);
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            problemInfo.ZLConfirmResult = Convert.ToInt32(dto.Confirm);
            var logID = 0;
            if (dto.Confirm)
            {
                problemInfo.Prevention = dto.Prevention;
                problemInfo.Measures = dto.Measures;
                problemInfo.Reason = dto.Reason;
                problemInfo.IsChangeOrderV = Convert.ToInt32(dto.IsChangeVersion);
                problemInfo.RCompleteTime = dto.RCompleteTime;
                problemInfo.DesignConfirmResult = dto.DesignConfirmResult;
                problemInfo.OrderVersion = dto.Version;
                var keepEffectOnReenter = false;
                if (dto.IsChangeVersion)
                {
                    var stepId = 2;
                    //发起任务
                    taskName = "国内制程问题单【" + problemInfo.Numbers + "】待PMC确认";
                    var userId = (await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameZL, stepId));
                    foreach (var id in userId)
                    {
                        await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 2, dto.ProblemId, taskName, id, now, now.AddDays(3));
                    }
                    //修改问题当前责任人
                    memberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameZL, stepId);

                    repository.Update(new ZCTracking_ProblemList
                    {
                        ID = dto.ProblemId,
                        MemberListName = memberListName.Value,
                        MemberList = memberListName.Key,
                        Status = (int)ZCTracking_ProblemStatusEnum.ChangeVersion,
                        IsChangeOrderV = problemInfo.IsChangeOrderV,
                        ZLConfirmResult = problemInfo.ZLConfirmResult,
                        OrderVersion = dto.Version,
                        Prevention = dto.Prevention,
                        Measures = dto.Measures,
                        Reason = dto.Reason,
                        RCompleteTime = dto.RCompleteTime,
                        DesignConfirmResult = dto.DesignConfirmResult,
                    },
                        x => new { x.MemberListName, x.MemberList, x.Status, x.IsChangeOrderV, x.OrderVersion, x.Prevention, x.Measures, x.ZLConfirmResult, x.RCompleteTime, x.DesignConfirmResult, x.Reason });
                    /* 发邮件 */
                    problemInfo.MemberListName = memberListName.Value;
                    problemInfo.MemberListName = memberListName.Value;

                    email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    email = string.Join(";", email.Split(";").Distinct());
                    ccMailList = string.Join(";", ccMailList.Split(";").Distinct());
                    desc = $"{UserContext.Current.UserName}，更改版本号：是，版本号{dto.Version}";
                }
                else
                {
                    keepEffectOnReenter = await ApplyKeptEffectConfirmOnReenterAsync(problemInfo);
                    if (!keepEffectOnReenter)
                    {
                        taskName = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                        await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskName, problemInfo.AddUser, now, now.AddDays(3));
                        memberListName.Key = problemInfo.AddUser.ToString();
                        memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                        problemInfo.MemberList = memberListName.Key;
                        problemInfo.MemberListName = memberListName.Value;
                        problemInfo.Status = (int)ZCTracking_ProblemStatusEnum.EffectConfirm;
                    }
                    repository.Update(problemInfo,
                        x => new { x.MemberListName, x.MemberList, x.Status, x.IsChangeOrderV, x.OrderVersion, x.Prevention, x.Measures, x.ZLConfirmResult, x.RCompleteTime, x.DesignConfirmResult, x.Reason });
                    /* 发邮件 */

                    email = keepEffectOnReenter ? "" : await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    email = string.Join(";", email.Split(";").Distinct());
                    ccMailList = string.Join(";", ccMailList.Split(";").Distinct());
                    desc = $"{UserContext.Current.UserName}，更改版本号：否";
                }
                //日志记录
                var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
                {
                    ProblemId = dto.ProblemId,
                    Step = (int)ZCTracking_ProblemOpeEnum.ConfirmVersion,
                    StepStr = "确认版本信息",
                    AddUser = UserContext.Current.UserId,
                    AddDate = now,
                    Opinon = dto.Remark,
                    Measures = $"{desc},确认结果：是,处理结果：{(dto.DesignConfirmResult.HasValue ? DicConst.DesignConfirmResultDic[dto.DesignConfirmResult.Value] : "未选择")},改善措施：{dto.Measures},预防对策：{dto.Prevention},原因分析：{dto.Reason}",
                    ProblemStatus = problemInfo.Status,
                    MemberList = UserContext.Current.UserId.ToString(),
                });
                await repository.SaveChangesAsync();
                logID = log.Entity.ID;
                if (dto.IsChangeVersion)
                {
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/PMCConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ChangeVersion);
                    await SendEmail(sendMail, email, ccMailList, taskName, context, productIds);
                }
                else if (keepEffectOnReenter)
                {
                    await ResumePreventionOnlyAfterKeptEffectAsync(problemInfo, productIds, sendMail, ccMailList);
                }
                else
                {
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.EffectConfirm);
                    await ReenterParallelConfirmAsync(problemInfo, productIds, sendMail, ccMailList);
                    await SendEmail(sendMail, email, ccMailList, taskName, context, productIds);
                }
            }
            else
            {
                var stepId = 1;
                switch (dto.ProblemType)
                {
                    case 1:
                    case 2:
                    case 6:
                        //发起任务
                        taskName = "国内制程问题单【" + problemInfo.Numbers + "】待指定责任人";
                        memberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameRJ, stepId);
                        var userId = memberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();
                        await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType.Value) + stepId, dto.ProblemId.ToString(), taskName, userId, now, now.AddDays(3)));
                        if (problemInfo.IsStop.Value == 1 && problemInfo.StopStatus.Value == 6)
                        {
                            var stopTaskName = $"国内制程问题单【" + problemInfo.Numbers + "】待填写停线重启方案";
                            await _pubTaskService.CancelTaskAddMemo(stopRsUser, dto.ProblemId.ToString(), UserContext.Current.UserId);
                            await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(stopRsUser, dto.ProblemId.ToString(), stopTaskName, userId, now, now.AddDays(3)));
                            problemInfo.ReStartSchemeUser = memberListName.Key;
                        }
                        //修改问题当前责任人
                        repository.Update(new ZCTracking_ProblemList
                        {
                            ID = dto.ProblemId,
                            Status = GetInitStatus(dto.ProblemType.Value),
                            Prevention = dto.Prevention,
                            Measures = dto.Measures,
                            MemberListName = memberListName.Value,
                            MemberList = memberListName.Key,
                            ProblemType = dto.ProblemType.Value,
                            ZLConfirmResult = Convert.ToInt32(dto.Confirm),
                            CInvCode = dto.CInvCode,
                            OldProblemType = oldType,
                            Reason = dto.Reason,
                            ReStartSchemeUser = problemInfo.ReStartSchemeUser,
                        }, x => new { x.Status, x.Prevention, x.Measures, x.MemberList, x.MemberListName, x.ZLConfirmResult, x.ProblemType, x.CInvCode, x.OldProblemType, x.Reason, x.ReStartSchemeUser });
                        //发邮件
                        /* 发邮件 */
                        problemInfo.Prevention = dto.Prevention;
                        problemInfo.Measures = dto.Measures;
                        problemInfo.ProblemType = dto.ProblemType.Value;
                        problemInfo.ZLConfirmResult = Convert.ToInt32(dto.Confirm);
                        problemInfo.CInvCode = dto.CInvCode;
                        problemInfo.OldProblemType = oldType;
                        problemInfo.Reason = dto.Reason;

                        problemInfo.MemberListName = memberListName.Value;
                        problemInfo.ProblemType = dto.ProblemType.Value;
                        urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/QualityAssignDutyMan?id={dto.ProblemId}'>点击进入该链接页面</a>";
                        context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.Confirm);
                        email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                        if (!string.IsNullOrWhiteSpace(ccMailList))
                        {
                            ccMailList += ";" + newEmail;
                        }
                        else
                        {
                            ccMailList = newEmail;
                        }
                        await SendEmail(sendMail, email, ccMailList, taskName, context, productIds);

                        break;
                    case 3:
                        var wltaskName = "国内制程问题单【" + problemInfo.Numbers + "】待IQC填写意见";
                        var userIds_IQC = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, stepId);
                        var userId_IQC = 0;
                        if (problemInfo.Factory == "04")//柯洱斯
                        {
                            userId_IQC = userIds_IQC[1];
                        }
                        if (problemInfo.Factory == "05")//亮亮
                        {
                            userId_IQC = userIds_IQC[1];
                        }
                        if (problemInfo.Factory == "09")//惠州百富
                        {
                            userId_IQC = userIds_IQC[0];
                        }
                        await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType.Value) + 7, dto.ProblemId, wltaskName, userId_IQC, now, now.AddDays(3));
                        //修改问题当前责任人
                        var memberList = userId_IQC.ToString();
                        problemInfo.MemberList = memberList;
                        problemInfo.MemberListName = await _hrEmployeeService.GetNameByIDAsync(memberList);
                        problemInfo.Status = GetInitStatus(dto.ProblemType.Value);
                        problemInfo.CInvCode = dto.CInvCode;
                        problemInfo.VenCode = dto.VenCode;
                        problemInfo.ProblemType = dto.ProblemType.Value;
                        problemInfo.OldProblemType = oldType;
                        problemInfo.Reason = dto.Reason;
                        repository.Update(problemInfo, x => new { x.MemberList, x.MemberListName, x.Status, x.CInvCode, x.VenCode, x.ProblemType, x.OldProblemType, x.Reason });
                        /* 发邮件 */
                        email = await _hrEmployeeService.GetEmailFromIDAsync(memberList);
                        urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/IQCOpinion?id={dto.ProblemId}'>点击进入该链接页面</a>";
                        context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.IQCOpinion);
                        if (!string.IsNullOrWhiteSpace(ccMailList))
                        {
                            ccMailList += ";" + newEmail;
                        }
                        else
                        {
                            ccMailList = newEmail;
                        }
                        await SendEmail(sendMail, email, ccMailList, wltaskName, context, productIds);
                        break;
                    case 4:
                        //发起任务
                        var zlTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待确认";
                        var zlmemberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameZL, stepId);
                        var zlUserId = zlmemberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();
                        await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType.Value) + stepId, dto.ProblemId.ToString(), zlTaskName, zlUserId, now, now.AddDays(3)));

                        if (problemInfo.IsStop.Value == 1 && problemInfo.StopStatus.Value == 6)
                        {
                            var stopTaskName = $"国内制程问题单【" + problemInfo.Numbers + "】待填写停线重启方案";
                            await _pubTaskService.CancelTaskAddMemo(stopRsUser, dto.ProblemId.ToString(), UserContext.Current.UserId);
                            await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(stopRsUser, dto.ProblemId.ToString(), stopTaskName, zlUserId, now, now.AddDays(3)));
                            problemInfo.ReStartSchemeUser = zlmemberListName.Key;
                        }

                        //修改问题当前责任人
                        repository.Update(new ZCTracking_ProblemList
                        {
                            ID = dto.ProblemId,
                            Status = GetInitStatus(dto.ProblemType.Value),
                            Prevention = dto.Prevention,
                            Measures = dto.Measures,
                            MemberListName = zlmemberListName.Value,
                            MemberList = zlmemberListName.Key,
                            ProblemType = dto.ProblemType.Value,
                            ZLConfirmResult = Convert.ToInt32(dto.Confirm),
                            OldProblemType = oldType,
                            Reason = dto.Reason,
                            ReStartSchemeUser = problemInfo.ReStartSchemeUser,
                        }, x => new { x.Status, x.Prevention, x.Measures, x.MemberList, x.MemberListName, x.ZLConfirmResult, x.ProblemType, x.OldProblemType, x.Reason, x.ReStartSchemeUser });
                        /* 发邮件 */
                        problemInfo.Prevention = dto.Prevention;
                        problemInfo.Measures = dto.Measures;
                        problemInfo.MemberList = zlmemberListName.Key;
                        problemInfo.ProblemType = dto.ProblemType.Value;
                        problemInfo.ZLConfirmResult = Convert.ToInt32(dto.Confirm);
                        problemInfo.OldProblemType = oldType;
                        problemInfo.Reason = dto.Reason;

                        problemInfo.MemberListName = zlmemberListName.Value;
                        problemInfo.ProblemType = dto.ProblemType.Value;
                        urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProjectConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                        context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ConfirmVersion);
                        email = await _hrEmployeeService.GetEmailFromIDAsync(zlmemberListName.Key);
                        if (!string.IsNullOrWhiteSpace(ccMailList))
                        {
                            ccMailList += ";" + newEmail;
                        }
                        else
                        {
                            ccMailList = newEmail;
                        }
                        await SendEmail(sendMail, email, ccMailList, zlTaskName, context, productIds);
                        break;
                    case 5:
                        //发起任务
                        var zcTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待原因分析";
                        //修改问题当前责任人
                        var zcmemberListName = new SelectItem();
                        var zcmemberList = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameZC, stepId);
                        var zcUserId = 0;
                        if (problemInfo.Factory == "04")//柯洱斯
                        {
                            zcUserId = zcmemberList[1];
                            zcmemberListName.Key = zcUserId.ToString();
                        }
                        if (problemInfo.Factory == "05")//亮亮
                        {
                            zcUserId = zcmemberList[2];
                            zcmemberListName.Key = zcUserId.ToString();
                        }
                        if (problemInfo.Factory == "09")//惠州百富
                        {
                            zcUserId = zcmemberList[0];
                            zcmemberListName.Key = zcUserId.ToString();
                        }
                        await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType.Value) + stepId, dto.ProblemId, zcTaskName, zcUserId, now, now.AddDays(3));
                        //工厂制程没有停线,关闭停线任务
                        var gcMemberList = problemInfo.MemberList.Split(",").Select(x => int.Parse(x)).ToList();
                        foreach (var member in gcMemberList)
                        {
                            _pubTaskService.CancelTaskAddMemo(stopRsUser, dto.ProblemId.ToString(), member, "修改问题类型，关闭停线任务。");
                        }

                        zcmemberListName.Value = await _hrEmployeeService.GetNameByIDAsync(zcmemberListName.Key);
                        repository.Update(new ZCTracking_ProblemList
                        {
                            ID = dto.ProblemId,
                            Status = GetInitStatus(dto.ProblemType.Value),
                            Prevention = dto.Prevention,
                            Measures = dto.Measures,
                            MemberListName = zcmemberListName.Value,
                            MemberList = zcmemberListName.Key,
                            ProblemType = dto.ProblemType.Value,
                            ZLConfirmResult = Convert.ToInt32(dto.Confirm),
                            OldProblemType = oldType,
                            Reason = dto.Reason,
                        }, x => new { x.Status, x.Prevention, x.Measures, x.MemberList, x.MemberListName, x.ZLConfirmResult, x.ProblemType, x.OldProblemType, x.Reason });

                        problemInfo.Prevention = dto.Prevention;
                        problemInfo.Measures = dto.Measures;
                        problemInfo.ProblemType = dto.ProblemType.Value;
                        problemInfo.ZLConfirmResult = Convert.ToInt32(dto.Confirm);
                        problemInfo.OldProblemType = oldType;
                        problemInfo.Reason = dto.Reason;
                        /* 发邮件 */
                        problemInfo.MemberListName = zcmemberListName.Value;
                        problemInfo.ProblemType = dto.ProblemType.Value;
                        urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/FactoryConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                        context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.FactoryAnalysis);
                        email = await _hrEmployeeService.GetEmailFromIDAsync(zcmemberListName.Key);
                        if (!string.IsNullOrWhiteSpace(ccMailList))
                        {
                            ccMailList += ";" + newEmail;
                        }
                        else
                        {
                            ccMailList = newEmail;
                        }
                        await SendEmail(sendMail, email, ccMailList, zcTaskName, context, productIds);
                        break;
                    case 7:
                        var yhTaskName = "国内制程问题单【" + problemInfo.Numbers + "】生产角色确认";
                        var yhMemberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameRJ, 5);
                        var yhUserId = yhMemberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();
                        await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType.Value) + 5, dto.ProblemId.ToString(), yhTaskName, yhUserId, now, now.AddDays(3)));

                        //制程问题没有停线,关闭停线任务
                        var zcMemberList = problemInfo.MemberList.Split(",").Select(x => int.Parse(x)).ToList();
                        foreach (var member in zcMemberList)
                        {
                            _pubTaskService.CancelTaskAddMemo(stopRsUser, dto.ProblemId.ToString(), member, "修改问题类型，关闭停线任务。");
                        }

                        //修改问题当前责任人                   
                        problemInfo.MemberListName = yhMemberListName.Value;
                        problemInfo.MemberList = yhMemberListName.Key;
                        problemInfo.ProblemType = dto.ProblemType.Value;
                        problemInfo.Status = GetInitStatus(dto.ProblemType.Value);
                        // problemInfo.StopStatus = 1;
                        repository.Update(problemInfo, x => new { x.MemberList, x.MemberListName, x.Status, x.ProblemType });
                        /* 发邮件 */
                        urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProduceConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                        context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ProduceConfirm, "", new List<ZCTracking_XBOrders>());
                        email = await _hrEmployeeService.GetEmailFromIDAsync(yhMemberListName.Key);
                        email = string.Join(";", email.Split(";").Distinct());
                        if (!string.IsNullOrWhiteSpace(ccMailList))
                        {
                            ccMailList += ";" + newEmail;
                        }
                        else
                        {
                            ccMailList = newEmail;
                        }
                        await SendEmail(sendMail, email, ccMailList, yhTaskName, context, productIds);
                        break;
                    default:
                        break;
                }
                var measures = $"{UserContext.Current.UserName}确认结果：否，原问题分类：{DicConst.ProblemTypeDic[oldType]}，修改问题分类为：{DicConst.ProblemTypeDic[dto.ProblemType.Value]}";
                var log = new ZCTracking_ProblemSteplog
                {
                    ProblemId = dto.ProblemId,
                    Step = (int)ZCTracking_ProblemOpeEnum.ConfirmVersion,
                    StepStr = "工程确认",
                    AddUser = UserContext.Current.UserId,
                    AddDate = now,
                    Opinon = dto.Remark,
                    Measures = measures,
                    ProblemStatus = (int)ZCTracking_ProblemStatusEnum.Confirm,
                    MemberList = UserContext.Current.UserId.ToString(),
                };
                //日志记录
                await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(log);
                await repository.SaveChangesAsync();
                logID = log.ID;
            }
            return logID;
        }

        public async Task<bool> ChangeVersion(ChangeVersionDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var now = DateTime.Now;
            var taskTable = GetfTable(problemInfo.ProblemType);
            //判断是否存在任务
            var existTask = await _pubTaskService.IsExistTask(taskTable + 2, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }
            //完成任务
            await _pubTaskService.FinishTaskMultiAsync(taskTable + 2, dto.ProblemId.ToString());
            var taskNameThis = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
            var keepEffect = await ApplyKeptEffectConfirmOnReenterAsync(problemInfo);
            var memberListName = new SelectItem();
            if (!keepEffect)
            {
                await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskNameThis, problemInfo.AddUser, now, now.AddDays(3));
                memberListName.Key = problemInfo.AddUser.ToString();
                memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                problemInfo.MemberList = memberListName.Key;
                problemInfo.MemberListName = memberListName.Value;
                problemInfo.Status = (int)ZCTracking_ProblemStatusEnum.EffectConfirm;
            }
            repository.Update(problemInfo, x => new { x.MemberListName, x.MemberList, x.Status });
            /* 发邮件 */
            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;//抄送人
            var email = keepEffect ? "" : await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);

            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var productIds = string.Join(',', productIdList);
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            if (!string.IsNullOrWhiteSpace(ccMailList))
            {
                ccMailList += ";" + newEmail;
            }
            else
            {
                ccMailList = newEmail;
            }
            email = string.Join(";", email.Split(";").Distinct());
            ccMailList = string.Join(";", ccMailList.Split(";").Distinct());
            //日志记录
            await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.ChangeVersion,
                StepStr = "PMC确认",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Opinon = dto.Remark,
                Measures = $"{UserContext.Current.UserName}确认版本号",
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            var save = await repository.SaveChangesAsync();
            if (keepEffect)
            {
                await ResumePreventionOnlyAfterKeptEffectAsync(problemInfo, productIds, sendMail, ccMailList);
            }
            else
            {
                var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                var context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.EffectConfirm);
                await ReenterParallelConfirmAsync(problemInfo, productIds, sendMail, ccMailList);
                await SendEmail(sendMail, email, ccMailList, taskNameThis, context, productIds);
            }
            return save > 0;
        }
        #endregion
        #region 工厂制程

        public async Task<int> CauseAnalysis(CauseAnalysisDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var now = DateTime.Now;
            var taskTable = GetfTable(problemInfo.ProblemType);
            //判断是否存在任务
            var existTask = await _pubTaskService.IsExistTask(taskTable + 1, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }
            var stepId = 0;
            switch (problemInfo.Factory)
            {
                case "04": //柯洱斯
                    stepId = 4;
                    break;
                case "05": //亮亮
                    stepId = 3;
                    break;
                case "09"://惠州百富
                    stepId = 2;
                    break;
                default:
                    break;
            }
            if (stepId == 0) throw new Exception($"工厂代码：{problemInfo.Factory}，错误！");
            //完成任务
            await _pubTaskService.FinishTaskMultiAsync(taskTable + 1, dto.ProblemId.ToString());
            //发起任务
            var taskNameThis = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
            //修改问题当前责任人                       
            var memberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameZC, stepId);
            await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetMulitTaskSQL(xgfTable, dto.ProblemId, taskNameThis, memberListName.Key, now, now.AddDays(3)));
            repository.Update(new ZCTracking_ProblemList
            {
                ID = dto.ProblemId,
                MemberListName = memberListName.Value,
                MemberList = memberListName.Key,
                Status = (int)ZCTracking_ProblemStatusEnum.EffectConfirm
            },
                x => new { x.MemberListName, x.MemberList, x.Status });
            problemInfo.MemberListName = memberListName.Value;
            /* 发邮件 */
            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;//抄送人
            problemInfo.MemberListName = memberListName.Value;
            var email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var productIds = string.Join(',', productIdList);
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            if (!string.IsNullOrWhiteSpace(ccMailList))
            {
                ccMailList += ";" + newEmail;
            }
            else
            {
                ccMailList = newEmail;
            }
            email = string.Join(";", email.Split(";").Distinct());
            ccMailList = string.Join(";", ccMailList.Split(";").Distinct());
            //日志记录
            var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.FactoryAnalysis,
                StepStr = "工厂制程分析",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Opinon = dto.Prevention,
                Result = dto.Measures,
                Measures = $"{UserContext.Current.UserName},原因分析：{dto.Measures},制定对策：{dto.Prevention}",
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            await repository.SaveChangesAsync();
            var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
            var context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.EffectConfirm);
            await SendEmail(sendMail, email, ccMailList, taskNameThis, context, productIds);
            return log.Entity.ID;
        }
        #endregion
        #region 物料问题
        public async Task<int> FollowUpSQE(FollowUpSQEDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var oldStatus = problemInfo.Status;
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var ftable = GetfTable(problemInfo.ProblemType);
            var existTask = await _pubTaskService.IsExistTask(ftable + 4, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }

            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;//抄送人
            string email = "", context = "", desc = "", taskName = "";
            var keepEffect = false;

            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var productIds = string.Join(',', productIdList);
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            if (dto.IsDesignChange)
            {
                //修改问题当前责任人
                var memberListName = await _hrEmployeeService.GetNameByIDAsync(dto.DesignUser.ToString());
                problemInfo.MemberListName = memberListName;
                problemInfo.MemberList = dto.DesignUser.ToString();
                problemInfo.IsDesignChange = Convert.ToInt32(dto.IsDesignChange);
                problemInfo.DesignUser = dto.DesignUser;
                problemInfo.ReasonClass = dto.ReasonClass;
                problemInfo.ReasonClassRemark = dto.ReasonClassRemark;
                if (dto.IsSubmit)
                {
                    problemInfo.Status = (int)ZCTracking_ProblemStatusEnum.DesignChange;
                    //发起任务
                    taskName = "国内制程问题单【" + problemInfo.Numbers + "】待设计变更";
                    await _pubTaskService.AddTaskAsync(ftable + 5, dto.ProblemId, taskName, dto.DesignUser.Value, now, now.AddDays(3));
                    repository.Update(problemInfo, x => new { x.MemberListName, x.MemberList, x.Status, x.IsDesignChange, x.DesignUser, x.ReasonClass, x.ReasonClassRemark });

                    email = await _hrEmployeeService.GetEmailFromIDAsync(dto.DesignUser.ToString());
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    email = string.Join(";", email.Split(";").Distinct());
                    ccMailList = string.Join(";", ccMailList.Split(";").Distinct());
                }
                else
                {
                    repository.Update(problemInfo, x => new { x.IsDesignChange, x.DesignUser, x.ReasonClass, x.ReasonClassRemark });
                }
                desc = $"{UserContext.Current.UserName}，需要设计变更，责任人：{memberListName}，跟进结果：{dto.Remark}";
            }
            else
            {
                problemInfo.IsDesignChange = Convert.ToInt32(dto.IsDesignChange);
                problemInfo.ReasonClass = dto.ReasonClass;
                problemInfo.ReasonClassRemark = dto.ReasonClassRemark;
                if (dto.IsSubmit)
                {
                    keepEffect = await ApplyKeptEffectConfirmOnReenterAsync(problemInfo);
                    if (!keepEffect)
                    {
                        var memberListName = new SelectItem
                        {
                            Key = problemInfo.AddUser.ToString()
                        };
                        memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                        problemInfo.MemberListName = memberListName.Value;
                        problemInfo.MemberList = memberListName.Key;
                        problemInfo.Status = (int)ZCTracking_ProblemStatusEnum.EffectConfirm;
                        taskName = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                        await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskName, problemInfo.AddUser, now, now.AddDays(3));
                        email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                    }
                    repository.Update(problemInfo, x => new { x.MemberListName, x.MemberList, x.Status, x.IsDesignChange, x.ReasonClass, x.ReasonClassRemark });
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    email = string.Join(";", (email ?? "").Split(";").Distinct());
                    ccMailList = string.Join(";", ccMailList.Split(";").Distinct());
                    desc = $"{UserContext.Current.UserName}，不需要设计变更，跟进结果：{dto.Remark}";
                }
                else
                {
                    repository.Update(problemInfo, x => new { x.IsDesignChange, x.ReasonClass, x.ReasonClassRemark });
                }
            }
            //日志记录
            var logDb = repository.DbContext.Set<ZCTracking_ProblemSteplog>();
            var logId = 0;
            var log = await logDb.Where(x => x.ProblemId == dto.ProblemId).OrderByDescending(x => x.AddDate).FirstOrDefaultAsync();
            if (log.Step == ZCTracking_ProblemOpeEnum.FollowSQE.GetEnumIntValue())
            {
                logId = log.ID;
                log.AddUser = UserContext.Current.UserId;
                log.AddDate = now;
                log.Opinon = dto.Remark;
                log.Result = Convert.ToInt32(dto.IsDesignChange).ToString();
                log.Measures = desc;
                log.MemberList = UserContext.Current.UserId.ToString();
                logDb.Update(log);
            }
            else
            {
                var addLog = await logDb.AddAsync(new ZCTracking_ProblemSteplog
                {
                    ProblemId = dto.ProblemId,
                    Step = (int)ZCTracking_ProblemOpeEnum.FollowSQE,
                    StepStr = "SQE跟进",
                    AddUser = UserContext.Current.UserId,
                    AddDate = now,
                    Opinon = dto.Remark,
                    Result = Convert.ToInt32(dto.IsDesignChange).ToString(),
                    Measures = desc,
                    ProblemStatus = oldStatus,
                    MemberList = UserContext.Current.UserId.ToString(),
                });
                logId = addLog.Entity.ID;
            }
            await repository.SaveChangesAsync();
            if (dto.IsSubmit)
            {
                //完成任务
                await _pubTaskService.FinishTaskAsync(ftable + 4, dto.ProblemId);
                var urlHtml = "";
                if (dto.IsDesignChange)
                {
                    /* 发邮件 */
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ChangeDesign?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.DesignChange);
                    if (problemInfo.ProblemType == 3)
                    {
                        email += $";{await GetWLEmail(problemInfo.CInvCode)}";
                        ccMailList += $";{cuijuan}";
                    }
                    await SendEmail(sendMail, email, ccMailList.Trim(';'), taskName, context, productIds);
                }
                else if (keepEffect)
                {
                    await ResumePreventionOnlyAfterKeptEffectAsync(problemInfo, productIds, sendMail, ccMailList);
                }
                else
                {
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.EffectConfirm);
                    if (problemInfo.ProblemType == 3)
                    {
                        email += $";{await GetWLEmail(problemInfo.CInvCode)}";
                        ccMailList += $";{cuijuan}";
                    }
                    await ReenterParallelConfirmAsync(problemInfo, productIds, sendMail, ccMailList);
                    await SendEmail(sendMail, email, ccMailList.Trim(';'), taskName, context, productIds);
                }
            }
            return logId;
        }

        public async Task<int> DesignChange(DesignChangeDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var oldStatus = problemInfo.Status;
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var ftable = GetfTable(problemInfo.ProblemType);
            var existTask = await _pubTaskService.IsExistTask(ftable + 5, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }
            //完成任务
            await _pubTaskService.FinishTaskAsync(ftable + 5, dto.ProblemId);
            var designDateStr = string.Empty;
            var confirmResult = string.Empty;
            var memberListName = new SelectItem();

            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;//抄送人
            var email = "";
            var taskNameThis = "";
            var context = "";

            //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
            if (problemInfo.ProblemType == 3)
            {
                email = await GetWLEmail(problemInfo.CInvCode);
                ccMailList += $";{cuijuan}";
            }

            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var productIdList = products.Select(x => x.ProductId).ToList();
            var keepEffect = false;
            if (dto.ConfirmResult == 1) //如果是改善则走效果确认
            {
                keepEffect = await ApplyKeptEffectConfirmOnReenterAsync(problemInfo);
                if (!keepEffect)
                {
                    taskNameThis = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
                    await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskNameThis, problemInfo.AddUser, now, now.AddDays(3));
                    memberListName.Key = problemInfo.AddUser.ToString();
                    memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                    problemInfo.MemberList = memberListName.Key;
                    problemInfo.MemberListName = memberListName.Value;
                    problemInfo.Status = (int)ZCTracking_ProblemStatusEnum.EffectConfirm;
                }
                problemInfo.DesignConfirmResult = dto.ConfirmResult;
                problemInfo.DesignDate = dto.DesignDate;
                repository.Update(problemInfo, x => new { x.MemberListName, x.MemberList, x.Status, x.DesignConfirmResult, x.DesignDate });
                /* 发邮件 */
                if (!keepEffect)
                {
                    problemInfo.MemberListName = memberListName.Value;
                    email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                }
                var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
                var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
                newEmail += $";{scbEmail}";
                if (!string.IsNullOrWhiteSpace(ccMailList))
                {
                    ccMailList += ";" + newEmail;
                }
                else
                {
                    ccMailList = newEmail;
                }
                email = string.Join(";", email.Split(";").Distinct());
                ccMailList = string.Join(";", ccMailList.Split(";").Distinct());
                confirmResult = "改善";
                designDateStr = $"预计完成时间：{dto.DesignDate:yyyy/MM/dd}";
            }
            else //否则就SQE确认
            {
                //发起任务
                taskNameThis = "国内制程问题单【" + problemInfo.Numbers + "】待设计变更后SQE确认";
                //上一个步骤sqe责任人
                var problemLog = await zCTracking_ProblemSteplogService.GetStepLog(dto.ProblemId, ZCTracking_ProblemStatusEnum.FollowSQE);
                await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 6, dto.ProblemId, taskNameThis, int.Parse(problemLog.MemberList), now, now.AddDays(3));
                //修改问题当前责任人                
                memberListName.Key = problemLog.MemberList;
                memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                repository.Update(new ZCTracking_ProblemList
                {
                    ID = dto.ProblemId,
                    MemberListName = memberListName.Value,
                    MemberList = memberListName.Key,
                    DesignConfirmResult = dto.ConfirmResult,
                    Status = (int)ZCTracking_ProblemStatusEnum.ChangeConfirmSQE
                },
                    x => new { x.MemberListName, x.MemberList, x.Status, x.DesignConfirmResult });
                /* 发邮件 */
                problemInfo.MemberListName = memberListName.Value;
                problemInfo.DesignConfirmResult = dto.ConfirmResult;

                email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
                var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
                newEmail += $";{scbEmail}";
                if (!string.IsNullOrWhiteSpace(ccMailList))
                {
                    ccMailList += ";" + newEmail;
                }
                else
                {
                    ccMailList = newEmail;
                }
                email = string.Join(";", email.Split(";").Distinct());
                ccMailList = string.Join(";", ccMailList.Split(";").Distinct());
                confirmResult = dto.ConfirmResult == 3 ? "挂起" : "保持现状";
            }
            //日志记录
            var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.DesignChange,
                StepStr = "设计变更",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Result = dto.ConfirmResult.ToString(),
                Measures = $"{UserContext.Current.UserName},确认结果：{confirmResult},{designDateStr},原因说明:{dto.Remark}",
                Opinon = dto.Remark,
                ProblemStatus = oldStatus,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            await repository.SaveChangesAsync();
            var urlHtml = "";
            if (dto.ConfirmResult == 1)
            {
                urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.EffectConfirm);
            }
            else
            {
                urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/SQEConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ChangeConfirmSQE);
            }
            //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
            if (problemInfo.ProblemType == 3)
            {
                email += $";{await GetWLEmail(problemInfo.CInvCode)}";
                ccMailList += $";{cuijuan}";
            }
            if (dto.ConfirmResult == 1)
            {
                if (keepEffect)
                {
                    await ResumePreventionOnlyAfterKeptEffectAsync(problemInfo, string.Join(",", productIdList), sendMail, ccMailList);
                }
                else
                {
                    await ReenterParallelConfirmAsync(problemInfo, string.Join(",", productIdList), sendMail, ccMailList);
                    await SendEmail(sendMail, email, ccMailList, taskNameThis, context, productIdList);
                }
            }
            else
            {
                await SendEmail(sendMail, email, ccMailList, taskNameThis, context, productIdList);
            }
            return log.Entity.ID;
        }
        public async Task<int> ChangeConfirmSQE(ChangeConfirmSQEDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var ftable = GetfTable(problemInfo.ProblemType);
            var existTask = await _pubTaskService.IsExistTask(ftable + 6, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }
            //完成任务
            await _pubTaskService.FinishTaskAsync(ftable + 6, dto.ProblemId);

            var memberListName = new SelectItem();
            var taskNameThis = "国内制程问题单【" + problemInfo.Numbers + "】待效果确认";
            var keepEffect = await ApplyKeptEffectConfirmOnReenterAsync(problemInfo);
            if (!keepEffect)
            {
                await _pubTaskService.AddTaskAsync(xgfTable, dto.ProblemId, taskNameThis, problemInfo.AddUser, now, now.AddDays(3));
                memberListName.Key = problemInfo.AddUser.ToString();
                memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                problemInfo.MemberList = memberListName.Key;
                problemInfo.MemberListName = memberListName.Value;
                problemInfo.Status = (int)ZCTracking_ProblemStatusEnum.EffectConfirm;
            }
            repository.Update(problemInfo, x => new { x.MemberListName, x.MemberList, x.Status });
            /* 发邮件 */
            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;//抄送人
            var email = "";
            if (!keepEffect)
            {
                problemInfo.MemberListName = memberListName.Value;
                email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
            }

            //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
            if (problemInfo.ProblemType == 3)
            {
                email += $";{await GetWLEmail(problemInfo.CInvCode)}";
                ccMailList += $";{cuijuan}";
            }

            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            if (!string.IsNullOrWhiteSpace(ccMailList))
            {
                ccMailList += ";" + newEmail;
            }
            else
            {
                ccMailList = newEmail;
            }
            email = string.Join(";", email.Split(";").Distinct());
            ccMailList = string.Join(";", ccMailList.Split(";").Distinct());
            //日志记录
            var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.ChangeConfirmSQE,
                StepStr = "设计变更后SQE确认",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Measures = $"{UserContext.Current.UserName},意见:{dto.Remark}",
                Opinon = dto.Remark,
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            await repository.SaveChangesAsync();
            var productIds = string.Join(",", productIdList);
            if (keepEffect)
            {
                await ResumePreventionOnlyAfterKeptEffectAsync(problemInfo, productIds, sendMail, ccMailList);
            }
            else
            {
                var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ResultConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                var context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.EffectConfirm);
                if (problemInfo.ProblemType == 3)
                {
                    email += $";{await GetWLEmail(problemInfo.CInvCode)}";
                    ccMailList += $";{cuijuan}";
                }
                await ReenterParallelConfirmAsync(problemInfo, productIds, sendMail, ccMailList);
                await SendEmail(sendMail, email, ccMailList, taskNameThis, context, productIdList);
            }
            return log.Entity.ID;
        }
        public async Task<int> FillReturnNo(FillReturnNoDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var ftable = GetfTable(problemInfo.ProblemType);
            var existTask = await _pubTaskService.IsExistTask(ftable + 3, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }
            var stepStr = "";
            var step = 0;
            var save = 0;

            var memberListName = new SelectItem();
            if (dto.Status == 2)
            {
                step = (int)ZCTracking_ProblemOpeEnum.FillOrderNo;
                stepStr = "确认退货单号";
                memberListName.Key = await zCTrackingService.GetSQEByVenCode(problemInfo.VenCode);
                if (string.IsNullOrWhiteSpace(memberListName.Key))//没有的默认崔娟
                {
                    memberListName.Key = "1287";
                }
                memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                //修改问题当前责任人
                if (problemInfo.IsStop.Value == 1)
                {
                    problemInfo.StopStatus = 6;
                }
                repository.Update(new ZCTracking_ProblemList
                {
                    ID = dto.ProblemId,
                    OReturnOrderNo = dto.OReturnOrderNo,
                    SReturnOrderNo = dto.SReturnOrderNo,
                    ReStartSchemeUser = memberListName.Key,
                    StopStatus = problemInfo.StopStatus,
                    IQCStatus = null,
                    IQCMemberList = "",
                    IQCMemberListName = "",
                }, x => new { x.OReturnOrderNo, x.SReturnOrderNo, x.ReStartSchemeUser, x.StopStatus, x.IQCStatus, x.IQCMemberList, x.IQCMemberListName });
            }
            else
            {
                step = (int)ZCTracking_ProblemOpeEnum.SaveOrderNo;
                stepStr = "保存退货单号";
                repository.Update(new ZCTracking_ProblemList
                {
                    ID = dto.ProblemId,
                    OReturnOrderNo = dto.OReturnOrderNo,
                    SReturnOrderNo = dto.SReturnOrderNo
                }, x => new { x.OReturnOrderNo, x.SReturnOrderNo });

            }

            #region 在库
            if (dto.StockReceiving != null && dto.StockReceiving.Any())
            {
                var stockDbSet = repository.DbContext.Set<ZCTracking_Stock>();
                var stockReceiving = new List<ZCTracking_Stock>();
                foreach (var item in dto.StockReceiving)
                {
                    var stockEntity = await stockDbSet.FirstOrDefaultAsync(x => x.ID == item.Id);
                    stockEntity.ReceivingQty = item.ReturnQty;
                    stockReceiving.Add(stockEntity);
                }
                stockDbSet.UpdateRange(stockReceiving);
            }


            #endregion
            #region 在线收货
            if (dto.OnlineReceiving != null && dto.OnlineReceiving.Any())
            {
                var onlineDbSet = repository.DbContext.Set<ZCTracking_OnlineOrder>();
                var onlineReceiving = new List<ZCTracking_OnlineOrder>();
                foreach (var item in dto.OnlineReceiving)
                {
                    var entity = await onlineDbSet.FirstOrDefaultAsync(x => x.ID == item.Id);
                    entity.ReceivingQty = item.ReturnQty;
                    onlineReceiving.Add(entity);
                }
                onlineDbSet.UpdateRange(onlineReceiving);
            }

            #endregion
            #region 其他在线订单收货
            if (dto.OtherReceiving != null && dto.OtherReceiving.Any())
            {
                var otherReceiving = new List<ZCTracking_OtherOrder>();
                var otherDbSet = repository.DbContext.Set<ZCTracking_OtherOrder>();
                foreach (var item in dto.OtherReceiving)
                {
                    var entity = await otherDbSet.FirstOrDefaultAsync(x => x.ID == item.Id);
                    entity.ReceivingQty = item.ReturnQty;
                    otherReceiving.Add(entity);
                }
                otherDbSet.UpdateRange(otherReceiving);

            }

            #endregion
            #region CKD机型收货
            if (dto.CKDReceiving != null && dto.CKDReceiving.Any())
            {
                var ckdReceiving = new List<ZCTracking_CKDProduct>();
                var ckdDbSet = repository.DbContext.Set<ZCTracking_CKDProduct>();
                foreach (var item in dto.CKDReceiving)
                {
                    var entity = await ckdDbSet.FirstOrDefaultAsync(x => x.ID == item.Id);
                    entity.ReceivingQty = item.ReturnQty;
                    ckdReceiving.Add(entity);
                }
                ckdDbSet.UpdateRange(ckdReceiving);
            }
            #endregion
            //日志记录
            await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = step,
                StepStr = stepStr,
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Opinon = dto.Remark,
                Measures = $"{UserContext.Current.UserName},填写收货数量，在线退货单号：{dto.OReturnOrderNo}，在库退货单号：{dto.SReturnOrderNo}",
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            save = await repository.SaveChangesAsync();
            if (save > 0)
            {
                if (dto.Status == 2)
                {
                    //完成任务
                    await _pubTaskService.FinishTaskAsync(ftable + 3, dto.ProblemId);

                    var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
                    var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
                    var productIdList = products.Select(x => x.ProductId).ToList();
                    var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();

                    var email = "";
                    var sendMail = UserContext.Current.UserInfo.Email;
                    var ccMailList = "";
                    var taskNameThis = "国内制程问题单【" + problemInfo.Numbers + "】已填写退货单号";
                    var context = await GetEmailHtml(dto.ProblemId, string.Empty);

                    /* 发邮件 */
                    //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                    if (problemInfo.ProblemType == 3)
                    {
                        email = await GetWLEmail(problemInfo.CInvCode);
                        ccMailList = cuijuan;
                    }
                    ccMailList = sendMail;
                    email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                    var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
                    newEmail += $";{scbEmail}";
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                    if (problemInfo.ProblemType == 3)
                    {
                        email += $";{await GetWLEmail(problemInfo.CInvCode)}";
                        ccMailList += $";{cuijuan}";
                    }
                    await SendEmail(sendMail, email, ccMailList, taskNameThis, context, productIdList);

                    #region 停线任务
                    if (problemInfo.IsStop.Value == 1)
                    {
                        var stopTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待填写停线重启方案";
                        await _pubTaskService.AddTaskAsync(stopRsUser, dto.ProblemId, stopTaskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                        await SendEmail(sendMail, email, ccMailList, stopTaskName, context, productIdList);
                    }
                    #endregion

                }
            }

            return save;
        }

        public async Task<int> IQCConfirm(IQC_ConfirmDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo == null) throw new Exception("未找到制程问题");

            var now = DateTime.Now;
            var ftable = GetfTable(problemInfo.ProblemType);
            var existTask = await _pubTaskService.IsExistTask(ftable + 1, dto.ProblemId);
            // if (!existTask) throw new Exception("不存在任务");

            //完成任务
            await _pubTaskService.FinishTaskAsync(ftable + 1, dto.ProblemId);

            //从IQC责任人列表中移除当前用户（两个列表各自按值匹配删除，不依赖索引对应关系）
            var memberIds = problemInfo.IQCMemberList?.Split(',', StringSplitOptions.RemoveEmptyEntries).ToList() ?? new List<string>();
            var memberNames = problemInfo.IQCMemberListName?.Split(',', StringSplitOptions.RemoveEmptyEntries).ToList() ?? new List<string>();
            memberIds.Remove(UserContext.Current.UserId.ToString());
            memberNames.Remove(UserContext.Current.UserName);

            problemInfo.IQCMemberList = string.Join(",", memberIds);
            problemInfo.IQCMemberListName = string.Join(",", memberNames);
            repository.Update(problemInfo, x => new { x.IQCMemberList, x.IQCMemberListName });

            //日志记录
            await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.ConfirmIQC,
                StepStr = "IQC确认",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Measures = $"{UserContext.Current.UserName},填写库存、CKD机型需退货数量",
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });

            #region 库存
            if (dto.StockList != null && dto.StockList.Count > 0)
            {
                var stocks = await repository.DbContext.Set<ZCTracking_Stock>().Where(x => x.ProblemId == dto.ProblemId).ToListAsync();
                for (int i = 0, length = stocks.Count; i < length; i++)
                {
                    var entity = dto.StockList.FirstOrDefault(x => x.ID == stocks[i].ID);
                    stocks[i].ReturnType = entity?.ReturnType;
                    stocks[i].StockReturnQty = entity?.StockReturnQty;
                }
                repository.DbContext.Set<ZCTracking_Stock>().UpdateRange(stocks);
            }
            #endregion

            #region CKD机型
            if (dto.CKDPrudcts != null && dto.CKDPrudcts.Count > 0)
            {
                var ckdProducts = await repository.DbContext.Set<ZCTracking_CKDProduct>().Where(x => x.ProblemId == dto.ProblemId).ToListAsync();
                for (int i = 0, length = ckdProducts.Count; i < length; i++)
                {
                    var entity = dto.CKDPrudcts.FirstOrDefault(x => x.ID == ckdProducts[i].ID);
                    ckdProducts[i].ReturnType = entity?.ReturnType;
                    ckdProducts[i].ReturnQty = entity?.ReturnQty;
                }
                repository.DbContext.Set<ZCTracking_CKDProduct>().UpdateRange(ckdProducts);
            }
            #endregion

            var taskCount = 1;
            var member = new SelectItem();
            var unfinishedStep = true;

            var riskOrderInfo = await repository.DbContext.Set<ZCTracking_RiskOrderInfo>().Where(x => x.ProblemId == dto.ProblemId).FirstOrDefaultAsync();
            if (riskOrderInfo != null) //有风险订单
            {
                //修改问题当前责任人（先 Detach 之前追踪的同 ID 实体，避免 EF Core 追踪冲突）
                var trackedEntry4526 = repository.DbContext.ChangeTracker.Entries<ZCTracking_ProblemList>()
                    .FirstOrDefault(e => e.Entity.ID == dto.ProblemId);
                if (trackedEntry4526 != null) trackedEntry4526.State = EntityState.Detached;
                problemInfo.IQCMemberListName = "";
                problemInfo.IQCMemberList = "";
                problemInfo.IQCStatus = null;
                repository.Update(problemInfo, x => new { x.IQCMemberListName, x.IQCMemberList, x.IQCStatus });

                unfinishedStep = await repository.DbContext.Set<ZCTracking_RiskStream>()
                    .AsNoTracking()
                    .AnyAsync(x => x.ProblemId == dto.ProblemId && x.Step == 14 && x.Status == 1 && x.UserID != UserContext.Current.UserId);
                if (!unfinishedStep)
                {
                    var userIds = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, 3);
                    member.Key = GetWarehouseMemberKey(problemInfo.Factory, userIds);
                    await repository.DbContext.Set<ZCTracking_RiskStream>().AddAsync(new ZCTracking_RiskStream
                    {
                        ProblemId = dto.ProblemId,
                        Step = 15,
                        Status = 1,
                        UserID = int.Parse(member.Key),
                        Remark = "",
                        AddUser = UserContext.Current.UserId,
                        AddDate = now,
                    });
                    
                }
            }
            else
            {
                #region 判断工厂任务是否完成
                taskCount = await _pubTaskService.GetTaskCount(ftable + 2, dto.ProblemId);
                if (taskCount == 0)
                {
                    var userIds = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, 3);
                    member.Key = GetWarehouseMemberKey(problemInfo.Factory, userIds);
                    member.Value = await _hrEmployeeService.GetNameByIDAsync(member.Key);
                    //修改问题当前责任人

                    problemInfo.IQCMemberListName = member.Value;
                    problemInfo.IQCMemberList = member.Key;
                    problemInfo.IQCStatus = (int)ZCTracking_ProblemStatusEnum.FillOrderNo;
                    repository.Update(problemInfo, x => new { x.IQCMemberListName, x.IQCMemberList, x.IQCStatus });
                }
                #endregion
            }

            var save = await repository.SaveChangesAsync();
            if (save > 0)
            {
                if (riskOrderInfo != null && !unfinishedStep) //有风险订单，所有IQC均已确认
                {
                    var taskName = "国内制程问题单【" + problemInfo.Numbers + "】风险订单仓库确认";
                    await _pubTaskService.AddTaskAsync(ftable + 15, dto.ProblemId, taskName, int.Parse(member.Key), now, now.AddDays(3));
                    var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
                    var productIdList = products.Select(x => x.ProductId).ToList();
                    var urlHtml = $"<a href='{FreqUsedConst.webSite}/QualityManage/FillReturnNoRiskOrder?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    var context = await GetEmailHtml(dto.ProblemId, urlHtml);
                    var email = await _hrEmployeeService.GetEmailFromIDAsync(member.Key);
                    var ccMail = "";
                    if (problemInfo.ProblemType == 3)
                    {
                        email += $";{await GetWLEmail(problemInfo.CInvCode)}";
                        ccMail = cuijuan;
                    }
                    await SendEmail(UserContext.Current.Email, email, ccMail, taskName, context, productIdList);
                }
                else if (taskCount == 0)
                {
                    var taskName = "国内制程问题单【" + problemInfo.Numbers + "】填写退货单号";
                    await _pubTaskService.AddTaskAsync(ftable + 3, dto.ProblemId, taskName, int.Parse(member.Key), now, now.AddDays(3));
                    var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
                    var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
                    var sendMail = UserContext.Current.UserInfo.Email;
                    var urlHtml = $"<a href='{FreqUsedConst.webSite}/QualityManage/WriteQuitNo?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    var context = await GetEmailHtml(dto.ProblemId, urlHtml);
                    var email = await _hrEmployeeService.GetEmailFromIDAsync(member.Key);
                    var ccMailList = sendMail;
                    if (problemInfo.ProblemType == 3)
                    {
                        email += $";{await GetWLEmail(problemInfo.CInvCode)}";
                        ccMailList += $";{cuijuan}";
                    }
                    var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
                    var productIdList = products.Select(x => x.ProductId).ToList();
                    var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
                    ccMailList += $";{newEmail};{scbEmail}";
                    await SendEmail(sendMail, email, ccMailList, taskName, context, productIdList);
                }
            }
            return save;
        }

        /// <summary>
        /// 根据工厂代码从仓库成员列表中获取对应成员Key
        /// </summary>
        private static string GetWarehouseMemberKey(string factory, List<int> userIds)
        {
            if (factory == "04" || factory == "05") return userIds[1].ToString();
            return userIds[0].ToString(); //09 惠州百富及其他
        }

        public async Task<int> FactoryConfirm(IQC_FactoryConfirmDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var ftable = GetfTable(problemInfo.ProblemType);
            var existTask = await _pubTaskService.IsExistTask(ftable + 2, dto.ProblemId);
            if (!existTask)
            {
                throw new Exception("不存在任务");
            }
            //完成任务
            await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetFinishTaskSelfSql(ftable + 2, dto.ProblemId.ToString()));

            //从IQC责任人列表中移除当前用户（两个列表各自按值匹配删除，不依赖索引对应关系）
            var memberIds = problemInfo.IQCMemberList?.Split(',', StringSplitOptions.RemoveEmptyEntries).ToList() ?? new List<string>();
            var memberNames = problemInfo.IQCMemberListName?.Split(',', StringSplitOptions.RemoveEmptyEntries).ToList() ?? new List<string>();
            memberIds.Remove(UserContext.Current.UserId.ToString());
            memberNames.Remove(UserContext.Current.UserName);


            problemInfo.IQCMemberList = string.Join(",", memberIds);
            problemInfo.IQCMemberListName = string.Join(",", memberNames);
            repository.Update(problemInfo, x => new { x.IQCMemberList, x.IQCMemberListName });
            var save = 0;
            //日志记录
            await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.ConfirmFactory,
                StepStr = "工厂填写在线",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Measures = $"{UserContext.Current.UserName},填写在线、其他在线订单需退货数量",
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            #region 在线
            if (dto.OnlineOrder != null && dto.OnlineOrder.Count > 0)
            {
                var onlineOrder = repository.DbContext.Set<ZCTracking_OnlineOrder>().Where(x => x.ProblemId == dto.ProblemId).ToList();
                for (int i = 0, length = onlineOrder.Count; i < length; i++)
                {
                    var entity = dto.OnlineOrder.Find(x => x.ID == onlineOrder[i].ID);
                    if (entity != null)
                    {
                        onlineOrder[i].ReturnType = entity.ReturnType;
                        onlineOrder[i].Qty = entity.Qty;
                        onlineOrder[i].OReturnQty = entity.OReturnQty;
                    }
                }
                repository.DbContext.Set<ZCTracking_OnlineOrder>().UpdateRange(onlineOrder);
            }
            #endregion
            #region 其他在线
            if (dto.OtherOnline != null && dto.OtherOnline.Count > 0)
            {
                var otherOder = repository.DbContext.Set<ZCTracking_OtherOrder>().Where(x => x.ProblemId == dto.ProblemId).ToList();
                for (int i = 0, length = otherOder.Count; i < length; i++)
                {
                    var entity = dto.OtherOnline.Find(x => x.ID == otherOder[i].ID);
                    if (entity != null)
                    {
                        otherOder[i].ReturnType = entity.ReturnType;
                        otherOder[i].ReturnQty = entity.ReturnQty;
                    }
                }
                repository.DbContext.Set<ZCTracking_OtherOrder>().UpdateRange(otherOder);
            }

            #endregion

            var member = new SelectItem();
            #region 判断IQC任务是否完成
            var iqcTaskCount = await _pubTaskService.GetTaskCount(ftable + 1, dto.ProblemId);
            var factoryTaskCount = await _pubTaskService.GetTaskCount(ftable + 2, dto.ProblemId);
            if (iqcTaskCount == 0 && factoryTaskCount == 0)
            {
                //发起任务
                var userIds = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, 3);
                if (problemInfo.Factory == "04" || problemInfo.Factory == "05")
                {
                    member.Key = userIds[1].ToString();
                }
                if (problemInfo.Factory == "09")//惠州百富
                {
                    member.Key = userIds[0].ToString();
                }
                member.Value = await _hrEmployeeService.GetNameByIDAsync(member.Key);
                //修改问题当前责任人
                problemInfo.IQCMemberListName = member.Value;
                problemInfo.IQCMemberList = member.Key;
                problemInfo.IQCStatus = (int)ZCTracking_ProblemStatusEnum.FillOrderNo;
                repository.Update(problemInfo, x => new { x.IQCMemberListName, x.IQCMemberList, x.IQCStatus });

            }
            save = await repository.SaveChangesAsync();
            if (save > 0)
            {
                //邮件
                if (iqcTaskCount == 0 && factoryTaskCount == 0)
                {
                    var taskName = "国内制程问题单【" + problemInfo.Numbers + "】填写退货单号";
                    await _pubTaskService.AddTaskAsync(ftable + 3, dto.ProblemId, taskName, int.Parse(member.Key), now, now.AddDays(3));
                    /* 发邮件 */
                    var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
                    var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
                    var sendMail = UserContext.Current.UserInfo.Email;
                    var ccMailList = sendMail;//抄送人
                    var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/WriteQuitNo?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    var context = await GetEmailHtml(dto.ProblemId, urlHtml);
                    var email = await _hrEmployeeService.GetEmailFromIDAsync(member.Key);
                    //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                    if (problemInfo.ProblemType == 3)
                    {
                        email += $";{await GetWLEmail(problemInfo.CInvCode)}";
                        ccMailList += $";{cuijuan}";
                    }
                    var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
                    var productIdList = products.Select(x => x.ProductId).ToList();
                    var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
                    newEmail += $";{scbEmail}";
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    await SendEmail(sendMail, email, ccMailList, taskName, context, productIdList);
                }
            }
            #endregion       
            return save;
        }
        /// <summary>
        /// 物料问题
        /// 更新需退货数量
        /// </summary>
        /// <returns></returns>
        public async Task<int> UpdateReutrnQty(ReutrnQtyDto dto)
        {
            if (dto.IsIQC)
            {
                #region 库存

                if (dto.Stock != null)
                {
                    var stock = new List<ZCTracking_Stock>();
                    var stockDbSet = repository.DbContext.Set<ZCTracking_Stock>();
                    foreach (var item in dto.Stock)
                    {
                        var entity = await stockDbSet.FirstAsync(x => x.ID == item.Key);
                        entity.StockReturnQty = item.Value;
                        stock.Add(entity);
                    }
                    stockDbSet.UpdateRange(stock);
                }
                #endregion
                #region CKD
                if (dto.CKD != null)
                {
                    var ckds = new List<ZCTracking_CKDProduct>();
                    var ckdDbSet = repository.DbContext.Set<ZCTracking_CKDProduct>();
                    foreach (var item in dto.CKD)
                    {
                        var entity = await ckdDbSet.FirstAsync(x => x.ID == item.Key);
                        entity.ReturnQty = item.Value;
                        ckds.Add(entity);
                    }
                    ckdDbSet.UpdateRange(ckds);
                }
                #endregion
            }
            else
            {
                #region 在线

                if (dto.Online != null)
                {
                    var onlines = new List<ZCTracking_OnlineOrder>();
                    var onlineDbSet = repository.DbContext.Set<ZCTracking_OnlineOrder>();
                    foreach (var item in dto.Online)
                    {
                        var entity = await onlineDbSet.FirstAsync(x => x.ID == item.Key);
                        entity.OReturnQty = item.Value;
                        onlines.Add(entity);
                    }
                    onlineDbSet.UpdateRange(onlines);
                }

                #endregion
                #region 其他在线

                if (dto.OtherOnline != null)
                {
                    var otherOnlines = new List<ZCTracking_OtherOrder>();
                    var otherOnDbSet = repository.DbContext.Set<ZCTracking_OtherOrder>();
                    foreach (var item in dto.OtherOnline)
                    {
                        var entity = await otherOnDbSet.FirstAsync(x => x.ID == item.Key);
                        entity.ReturnQty = item.Value;
                        otherOnlines.Add(entity);
                    }
                    otherOnDbSet.UpdateRange(otherOnlines);
                }

                #endregion

            }
            return await repository.SaveChangesAsync();
        }

        public async Task<int> IQCOpinion(IQC_OpinionDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            if (problemInfo.Status != ZCTracking_ProblemStatusEnum.IQCOpinion.GetEnumIntValue())
            {
                throw new Exception("当前节点已审核，请刷新数据！");
            }
            #region 库存
            if (dto.StockList != null && dto.StockList.Count > 0)
            {
                #region 驳回的情况下，先删除
                var deleteList = repository.DbContext.Set<ZCTracking_Stock>().Where(x => x.ProblemId == dto.ProblemId);
                if (deleteList.Any()) repository.DbContext.Set<ZCTracking_Stock>().RemoveRange(deleteList);
                #endregion
                var stocks = new List<ZCTracking_Stock>();
                foreach (var item in dto.StockList)
                {
                    stocks.Add(new ZCTracking_Stock
                    {
                        ProblemId = dto.ProblemId,
                        WhCode = item.WhCode,
                        Warehouse = item.Warehouse,
                        Qty = item.Qty,
                        ReturnType = dto.IQCOpinion,
                        StockReturnQty = item.StockReturnQty,
                    });
                }
                await repository.DbContext.Set<ZCTracking_Stock>().AddRangeAsync(stocks);
            }

            #endregion
            #region CKD机型
            if (dto.CKDPrudcts != null && dto.CKDPrudcts.Count > 0)
            {
                #region 驳回的情况下，先删除
                var deleteList = repository.DbContext.Set<ZCTracking_CKDProduct>().Where(x => x.ProblemId == dto.ProblemId);
                if (deleteList.Any()) repository.DbContext.Set<ZCTracking_CKDProduct>().RemoveRange(deleteList);
                #endregion
                var ckdProducts = new List<ZCTracking_CKDProduct>();
                foreach (var item in dto.CKDPrudcts)
                {
                    ckdProducts.Add(new ZCTracking_CKDProduct
                    {
                        ProblemId = dto.ProblemId,
                        PO = item.PO,
                        Invoice = item.Invoice,
                        IssuedQty = item.IssuedQty,
                        PickupDate = item.PickupDate,
                        ReturnType = dto.IQCOpinion,
                        ReturnQty = item.ReturnQty,
                    });
                }
                await repository.DbContext.Set<ZCTracking_CKDProduct>().AddRangeAsync(ckdProducts);
            }

            #endregion
            #region 在线
            if (dto.OnlineOrder != null && dto.OnlineOrder.Count > 0)
            {
                #region 驳回的情况下，先删除
                var deleteList = repository.DbContext.Set<ZCTracking_OnlineOrder>().Where(x => x.ProblemId == dto.ProblemId);
                if (deleteList.Any()) repository.DbContext.Set<ZCTracking_OnlineOrder>().RemoveRange(deleteList);
                #endregion
                var onlineOrder = new List<ZCTracking_OnlineOrder>();
                foreach (var item in dto.OnlineOrder)
                {
                    onlineOrder.Add(new ZCTracking_OnlineOrder
                    {
                        ProblemId = dto.ProblemId,
                        ProductionType = item.ProductionType,
                        Qty = item.Qty,
                        ReturnType = dto.IQCOpinion,
                        OReturnQty = item.OReturnQty,
                    });
                }
                await repository.DbContext.Set<ZCTracking_OnlineOrder>().AddRangeAsync(onlineOrder);
            }

            #endregion
            #region 其他在线
            if (dto.OtherOnline != null && dto.OtherOnline.Count > 0)
            {
                #region 驳回的情况下，先删除
                var deleteList = repository.DbContext.Set<ZCTracking_OtherOrder>().Where(x => x.ProblemId == dto.ProblemId);
                if (deleteList.Any()) repository.DbContext.Set<ZCTracking_OtherOrder>().RemoveRange(deleteList);
                #endregion
                var otherOder = new List<ZCTracking_OtherOrder>();
                foreach (var item in dto.OtherOnline)
                {
                    otherOder.Add(new ZCTracking_OtherOrder
                    {
                        ProblemId = dto.ProblemId,
                        OrderNo = item.OrderNo,
                        ProductName = item.ProductName,
                        Qty = item.Qty,
                        IssuedQty = item.IssuedQty,
                        ReturnQty = item.ReturnQty,
                        ReturnType = dto.IQCOpinion,
                        PartNumber = item.PartNumber,
                        Factory = item.Factory,
                        FaliaoDate = item.FaliaoDate,
                        TotalinQty = item.TotalinQty,
                        IssQty = item.IssQty,
                    });
                }
                await repository.DbContext.Set<ZCTracking_OtherOrder>().AddRangeAsync(otherOder);
            }

            #endregion

            if (dto.IsEditProblemType)
            {
                return await IQCOpinionEditProblemType(dto);
            }
            else
            {
                var now = DateTime.Now;
                var ftable = GetfTable(problemInfo.ProblemType);
                var existTask = await _pubTaskService.IsExistTask(ftable + 7, dto.ProblemId);
                if (!existTask)
                {
                    throw new Exception("不存在任务");
                }
                var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
                var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
                var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
                var productIdList = products.Select(x => x.ProductId).ToList();
                var opinion = dto.IQCOpinion == 2 ? "退回" : "继续使用";

                //日志记录
                await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
                {
                    ProblemId = dto.ProblemId,
                    Step = (int)ZCTracking_ProblemOpeEnum.IQCOpinion,
                    StepStr = "IQC填写意见",
                    AddUser = UserContext.Current.UserId,
                    AddDate = now,
                    Opinon = dto.Remark,
                    Measures = $"{UserContext.Current.UserName},IQC意见：{opinion},备注：{dto.Remark}",
                    ProblemStatus = problemInfo.Status,
                    MemberList = UserContext.Current.UserId.ToString(),
                });

                var userId_IQC = 0;
                var userId_Factory = new List<int>();
                if (dto.IQCOpinion == 2) //退回
                {
                    //发起任务
                    var userIds_IQC = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, 1);
                    var userIds_Factory = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, 2);
                    #region 取不同工厂人员
                    var otherOrderList = await zCTrackingService.GetOtherOrder(problemInfo.CInvCode);
                    var factorys = otherOrderList.Select(x => x.Factory).Distinct().ToList();
                    if (factorys.Contains("04"))
                    {
                        userId_Factory.Add(userIds_Factory[1]);
                        await IsExistMenuAuth(userIds_Factory[1]);
                    }
                    if (factorys.Contains("05"))
                    {
                        userId_Factory.Add(userIds_Factory[2]);
                        await IsExistMenuAuth(userIds_Factory[2]);
                    }
                    if (factorys.Contains("09"))
                    {
                        userId_Factory.Add(userIds_Factory[0]);
                        await IsExistMenuAuth(userIds_Factory[0]);
                    }
                    #endregion

                    if (problemInfo.Factory == "04")//柯洱斯
                    {
                        userId_IQC = userIds_IQC[1];
                    }
                    if (problemInfo.Factory == "05")//亮亮
                    {
                        userId_IQC = userIds_IQC[1];
                    }
                    if (problemInfo.Factory == "09")//惠州百富
                    {
                        userId_IQC = userIds_IQC[0];
                    }
                    //IQC确认
                    problemInfo.IQCStatus = ZCTracking_ProblemStatusEnum.ConfirmIQC.GetEnumIntValue();
                    problemInfo.IQCMemberList = $"{userId_IQC},{string.Join(",", userId_Factory)}";
                    problemInfo.IQCMemberListName = await _hrEmployeeService.GetNameByIDAsync(problemInfo.IQCMemberList);
                }

                #region SQE跟进
                var memberListName = new SelectItem();
                //继续使用直接到“SQE跟进”
                memberListName.Key = await zCTrackingService.GetSQEByVenCode(problemInfo.VenCode);
                if (string.IsNullOrWhiteSpace(memberListName.Key))//没有的默认崔娟
                {
                    memberListName.Key = "1287";
                }
                memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                #endregion

                #region 更新问题主表
                problemInfo.MemberList = memberListName.Key;
                problemInfo.MemberListName = memberListName.Value;
                problemInfo.Status = (int)ZCTracking_ProblemStatusEnum.FollowSQE;
                problemInfo.IQCOpinion = dto.IQCOpinion;
                if (problemInfo.IsStop.Value == 1)
                {
                    problemInfo.ReStartSchemeUser = memberListName.Key;
                    problemInfo.StopStatus = 6;
                }
                repository.Update(problemInfo);
                #endregion

                var save = await repository.SaveChangesAsync();
                if (save > 0)
                {
                    string context = string.Empty, urlHtml = string.Empty;
                    var sendMail = UserContext.Current.UserInfo.Email;
                    var ccMailList = sendMail;//抄送人
                    //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                    string email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                    var sqeEmail = "";
                    if (problemInfo.ProblemType == 3)
                    {
                        sqeEmail = await GetWLEmail(problemInfo.CInvCode);
                        email += $";{sqeEmail}";
                        ccMailList += $";{cuijuan}";
                    }

                    var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
                    newEmail += $";{scbEmail}";
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    //完成任务
                    await _pubTaskService.FinishTaskAsync(ftable + 7, dto.ProblemId);
                    //SQE跟进任务
                    /* 发SQE邮件*/
                    var taskNameThis = "国内制程问题单【" + problemInfo.Numbers + "】待SQE跟进";
                    await _pubTaskService.AddTaskAsync(ftable + 4, dto.ProblemId, taskNameThis, int.Parse(memberListName.Key), now, now.AddDays(3));
                    urlHtml = $"<a href='{FreqUsedConst.webSite}/QualityManage/SQEFollowCheck?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    context = await GetEmailHtml(dto.ProblemId, urlHtml);
                    await SendEmail(sendMail, email, ccMailList, taskNameThis, context, productIdList);

                    #region 停线任务
                    if (problemInfo.IsStop.Value == 1)
                    {
                        var stopTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待填写停线重启方案";
                        await _pubTaskService.AddTaskAsync(stopRsUser, dto.ProblemId, stopTaskName, int.Parse(memberListName.Key), now, now.AddDays(3));
                        context = await GetEmailHtml(dto.ProblemId, "");
                        await SendEmail(sendMail, email, ccMailList, stopTaskName, context, productIdList);
                    }
                    #endregion                                    
                    //IQC确认邮件
                    if (dto.IQCOpinion == 2)
                    {
                        //发起任务
                        var iqcTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待IQC确认";
                        //var factoryTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待IQC确认";
                        await _pubTaskService.AddTaskAsync(GetfTable(problemInfo.ProblemType) + 1, dto.ProblemId, iqcTaskName, userId_IQC, now, now.AddDays(3));
                        await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(problemInfo.ProblemType) + 2, dto.ProblemId.ToString(), iqcTaskName, userId_Factory, now, now.AddDays(3)));

                        /* 发邮件 */
                        urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/IQCConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                        context = await GetEmailHtml(dto.ProblemId, urlHtml);
                        email = await _hrEmployeeService.GetEmailFromIDAsync(problemInfo.IQCMemberList);
                        //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                        if (problemInfo.ProblemType == 3)
                        {
                            sqeEmail = await GetWLEmail(problemInfo.CInvCode);
                            email += $";{sqeEmail}";
                            ccMailList += $";{cuijuan}";
                        }
                        await SendEmail(sendMail, email, ccMailList, iqcTaskName, context, productIdList);
                    }

                }
                return save;
            }
        }

        private async Task<int> IQCOpinionEditProblemType(IQC_OpinionDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var now = DateTime.Now;
            if (problemInfo == null)
            {
                throw new Exception("未找到制程问题");
            }
            var ftable = GetfTable(problemInfo.ProblemType);
            var existTask = await _pubTaskService.IsExistTask(ftable + 7, dto.ProblemId);
            if (!existTask) throw new Exception("不存在任务");

            string context = string.Empty, urlHtml = string.Empty;
            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;//抄送人
            string email = "";
            //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
            if (problemInfo.ProblemType == 3)
            {
                email = await GetWLEmail(problemInfo.CInvCode);
                ccMailList += $";{cuijuan}";
            }
            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var memberListName = new SelectItem();
            var newStatus = ZCTracking_ProblemStatusEnum.IQCOpinion;
            var save = 0;
            //日志记录
            await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
            {
                ProblemId = dto.ProblemId,
                Step = (int)ZCTracking_ProblemOpeEnum.IQCOpinion,
                StepStr = "IQC填写意见",
                AddUser = UserContext.Current.UserId,
                AddDate = now,
                Opinon = dto.Remark,
                Measures = $"{UserContext.Current.UserName},修改问题分类，原问题分类：{DicConst.ProblemTypeDic[problemInfo.ProblemType]},修改后问题分类：{DicConst.ProblemTypeDic[dto.ProblemType.Value]},备注：{dto.Remark}",
                ProblemStatus = problemInfo.Status,
                MemberList = UserContext.Current.UserId.ToString(),
            });
            save += await repository.SaveChangesAsync();
            problemInfo.Improve = dto.Improve;
            problemInfo.CInvCode = dto.CInvCode;
            problemInfo.VenCode = dto.VenCode;
            problemInfo.OldProblemType = problemInfo.ProblemType;
            problemInfo.ProblemType = dto.ProblemType.Value;

            #region 流程
            var stepId = 1;
            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";
            switch (dto.ProblemType.Value)
            {
                case 1:
                case 2:
                case 6:
                case 7:
                    newStatus = ZCTracking_ProblemStatusEnum.ResponsibleUser;
                    //发起任务
                    var taskName = "国内制程问题单【" + problemInfo.Numbers + "】待指定责任人";
                    memberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameRJ, stepId);
                    var userId = memberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType.Value) + stepId, dto.ProblemId.ToString(), taskName, userId, now, now.AddDays(3)));
                    //修改问题当前责任人
                    /* 发邮件 */
                    problemInfo.MemberListName = memberListName.Value;
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/QualityAssignDutyMan?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, newStatus);
                    email += ";" + await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    await SendEmail(sendMail, email, ccMailList, taskName, context, productIdList);
                    break;
                case 4:
                    newStatus = ZCTracking_ProblemStatusEnum.ConfirmVersion;
                    //发起任务
                    var zlTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待确认";
                    var zlmemberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameZL, stepId);
                    var zlUserId = zlmemberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(dto.ProblemType.Value) + stepId, dto.ProblemId.ToString(), zlTaskName, zlUserId, now, now.AddDays(3)));
                    //修改问题当前责任人
                    /* 发邮件 */
                    problemInfo.MemberListName = zlmemberListName.Value;
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/ProjectConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, newStatus);
                    email += ";" + await _hrEmployeeService.GetEmailFromIDAsync(zlmemberListName.Key);
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    await SendEmail(sendMail, email, ccMailList, zlTaskName, context, productIdList);
                    break;
                case 5:
                    newStatus = ZCTracking_ProblemStatusEnum.FactoryAnalysis;
                    //发起任务
                    var zcTaskName = "国内制程问题单【" + problemInfo.Numbers + "】待分析";
                    //修改问题当前责任人
                    var zcmemberList = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameZC, stepId);
                    var zcUserId = 0;
                    if (problemInfo.Factory == "04")//柯洱斯
                    {
                        zcUserId = zcmemberList[1];
                        memberListName.Key = zcUserId.ToString();
                    }
                    if (problemInfo.Factory == "05")//亮亮
                    {
                        zcUserId = zcmemberList[2];
                        memberListName.Key = zcUserId.ToString();
                    }
                    if (problemInfo.Factory == "09")//惠州百富
                    {
                        zcUserId = zcmemberList[0];
                        memberListName.Key = zcUserId.ToString();
                    }
                    memberListName.Value = await _hrEmployeeService.GetNameByIDAsync(memberListName.Key);
                    /* 发邮件 */
                    problemInfo.MemberListName = memberListName.Value;
                    await _pubTaskService.AddTaskAsync(GetfTable(dto.ProblemType.Value) + stepId, dto.ProblemId, zcTaskName, zcUserId, now, now.AddDays(3));
                    urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/FactoryConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, newStatus);
                    email += ";" + await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                    if (!string.IsNullOrWhiteSpace(ccMailList))
                    {
                        ccMailList += ";" + newEmail;
                    }
                    else
                    {
                        ccMailList = newEmail;
                    }
                    await SendEmail(sendMail, email, ccMailList, zcTaskName, context, productIdList);
                    break;
                default:
                    break;
            }
            #endregion

            #region 更新问题信息

            repository.Update(new ZCTracking_ProblemList
            {
                ID = dto.ProblemId,
                MemberList = memberListName.Key,
                MemberListName = memberListName.Value,
                Improve = dto.Improve,
                Status = (int)newStatus,
                CInvCode = dto.CInvCode,
                VenCode = dto.VenCode,
                ProblemType = dto.ProblemType.Value,
                OldProblemType = problemInfo.ProblemType,
            }
            , x => new { x.MemberList, x.MemberListName, x.Improve, x.Status, x.CInvCode, x.VenCode, x.ProblemType, x.OldProblemType });
            #endregion


            save += await repository.SaveChangesAsync();
            //完成任务
            await _pubTaskService.FinishTaskAsync(ftable + 7, dto.ProblemId);
            return save;
        }
        public async Task<RiskOrderDetailModel> GetRiskDetail(int problemId)
        {
            var riskInfo = await repository.DbContext.Set<ZCTracking_RiskOrderInfo>().AsNoTracking().FirstOrDefaultAsync(x => x.ProblemId == problemId);
            var riskOrderList = await repository.DbContext.Set<ZCTracking_RiskOrderList>().AsNoTracking().Where(x => x.ProblemId == problemId).ToListAsync();
            var riskStream = await repository.DbContext.Set<ZCTracking_RiskStream>().AsNoTracking().Where(x => x.ProblemId == problemId).ToListAsync();
            var riskStreamLog = await repository.DbContext.Set<ZCTracking_RiskStreamLog>().AsNoTracking().Where(x => x.ProblemId == problemId).ToListAsync();
            var riskDetail = new RiskOrderDetailModel();
            riskInfo.MapValueToEntity(riskDetail);

            if (riskOrderList.Any())
            {
                var moOrderNumbers = riskOrderList.Select(x => x.OrderNo).ToList();
                var moOrderList = await repository.DbContext.Set<MoOrder>().AsNoTracking().Where(x => moOrderNumbers.Contains(x.OrderNumber)).ToListAsync();
                riskDetail.RiskOrderList = new List<RiskOrderListModel>();
                foreach (var item in riskOrderList)
                {
                    riskDetail.RiskOrderList.Add(new RiskOrderListModel
                    {
                        ID = item.ID,
                        ProblemId = item.ProblemId,
                        Factory = item.Factory,
                        OrderNo = item.OrderNo,
                        PartNumber = item.PartNumber,
                        Qty = item.Qty,
                        TotalinQty = item.TotalinQty,
                        IssuedQty = item.IssuedQty,
                        IssQty = item.IssQty,
                        IsPatch = item.IsPatch,
                        IsRisk = item.IsRisk,
                        ReturnType = item.ReturnType,
                        RiskUsedQty = item.RiskUsedQty,
                        ReturnQty = item.ReturnQty,
                        ReceivingQty = item.ReceivingQty,
                        FaliaoDate = item.FaliaoDate,
                        ProductName = item.ProductName,
                        IsMoOrder = moOrderList.Any(x => x.OrderNumber == item.OrderNo)
                    });
                }
            }
            if (riskStream.Any())
            {
                riskDetail.RiskStreamList = riskStream.MapToObject<List<ZCTracking_RiskStream>, List<RiskStreamListModel>>(null);
                var streamUserIds = riskStream.Select(x => x.UserID).Distinct().ToList();
                var streamUserNames = await _hrEmployeeService.GetUserIdNameList(streamUserIds);
                riskDetail.RiskStreamList.ForEach(x =>
                {
                    x.UserName = streamUserNames.Find(f => f.Id == x.UserID)?.Name ?? "";
                });
            }
            if (riskStreamLog.Any())
            {
                riskDetail.RiskStreamLogList = riskStreamLog.MapToObject<List<ZCTracking_RiskStreamLog>, List<RiskStreamLogModel>>(null);
                var riskUserIds = riskStreamLog.Select(x => x.AddUser).Distinct().ToList();
                var userNameList = await _hrEmployeeService.GetUserIdNameList(riskUserIds);
                riskDetail.RiskStreamLogList.ForEach(x =>
                {
                    x.AddUserName = userNameList.Find(f => f.Id == x.AddUser).Name;
                });
            }
            riskDetail.FactoryUserList = await _pilotProductStreamItemService.GetUserIdsByStreamName("制程问题-物料问题", 2);
            return riskDetail;
        }
        public async Task<WebResponseContent> AddRiskOrder(AddOrEditRiskOrderModel dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo == null)
            {
                return WebResponseContent.Error_obj("未找到制程问题！");
            }
            if (!problemInfo.IQCOpinion.HasValue)
            {
                return WebResponseContent.Error_obj("IQC意见未完成确认，无法填写！");
            }
            var ftable = GetfTable(problemInfo.ProblemType);

            var riskOrderInfoDb = repository.DbContext.Set<ZCTracking_RiskOrderInfo>();
            var riskOrderListDb = repository.DbContext.Set<ZCTracking_RiskOrderList>();
            var riskStreamDb = repository.DbContext.Set<ZCTracking_RiskStream>();
            var riskStreamLogDb = repository.DbContext.Set<ZCTracking_RiskStreamLog>();

            #region 风险信息
            var riskOrderInfoEntity = new ZCTracking_RiskOrderInfo
            {
                ProblemId = dto.ProblemId,
                IsPatch = dto.IsPatch,
                BatchType = dto.BatchType,
                RiskBatch = dto.RiskBatch,
                DeliveryQty = dto.DeliveryQty,
                StockQty = dto.StockQty,
                IssuedQty = dto.IssuedQty,
                KESQty = dto.KESQty,
                LLQty = dto.LLQty,
                HZQty = dto.HZQty,
                CKDQty = dto.CKDQty,
                OtherQty = dto.OtherQty,
                Remark = dto.Remark,
                AddUser = UserContext.Current.UserId,
                AddDate = DateTime.Now,
            };
            await riskOrderInfoDb.AddAsync(riskOrderInfoEntity);
            #endregion

            #region 订单
            var riskOrderListAdd = new List<ZCTracking_RiskOrderList>();
            foreach (var item in dto.OrderList)
            {
                riskOrderListAdd.Add(new ZCTracking_RiskOrderList
                {
                    ProblemId = dto.ProblemId,
                    Factory = item.Factory,
                    OrderNo = item.OrderNo,
                    PartNumber = item.PartNumber,
                    Qty = item.Qty,
                    TotalinQty = item.TotalinQty,
                    IssuedQty = item.IssuedQty,
                    IssQty = item.IssQty,
                    IsPatch = item.IsPatch,
                    IsRisk = item.IsRisk,
                    FaliaoDate = item.FaliaoDate,
                    ProductName = item.ProductName,
                });
            }
            await riskOrderListDb.AddRangeAsync(riskOrderListAdd);
            #endregion

            riskStreamLogDb.AddAsync(new ZCTracking_RiskStreamLog
            {
                ProblemId = dto.ProblemId,
                Step = ZCTrackingRiskStreamLogEnum.AddRiskOrder.GetEnumIntValue(),
                Status = 2,
                UserID = 0,
                Remark = $"{UserContext.Current.UserName}：新增风险订单。",
                AddUser = UserContext.Current.UserId,
                AddDate = DateTime.Now,
            });
            var factoryUserId = new List<int>();
            if (dto.IsSubmit)
            {
                #region 分发不同工厂
                var userIds_Factory = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, 2);
                var factorys = dto.OrderList.Select(x => x.Factory).Distinct().ToList();

                if (factorys.Contains("04"))
                {
                    var addStream = new ZCTracking_RiskStream();
                    addStream.ProblemId = dto.ProblemId;
                    addStream.Step = ZCTrackingRiskStreamEnum.ReturnInfo.GetEnumIntValue();
                    addStream.Status = 1;
                    addStream.Remark = "";
                    addStream.AddUser = UserContext.Current.UserId;
                    addStream.AddDate = DateTime.Now;
                    addStream.UserID = userIds_Factory[1];
                    await IsExistMenuAuth(userIds_Factory[1]);
                    await riskStreamDb.AddAsync(addStream);
                    factoryUserId.Add(addStream.UserID);
                }
                if (factorys.Contains("05"))
                {
                    var addStream = new ZCTracking_RiskStream();
                    addStream.ProblemId = dto.ProblemId;
                    addStream.Step = ZCTrackingRiskStreamEnum.ReturnInfo.GetEnumIntValue();
                    addStream.Status = 1;
                    addStream.Remark = "";
                    addStream.AddUser = UserContext.Current.UserId;
                    addStream.AddDate = DateTime.Now;
                    addStream.UserID = userIds_Factory[1];
                    addStream.UserID = userIds_Factory[2];
                    await IsExistMenuAuth(userIds_Factory[2]);
                    await riskStreamDb.AddAsync(addStream);
                    factoryUserId.Add(addStream.UserID);
                }
                if (factorys.Contains("09"))
                {
                    var addStream = new ZCTracking_RiskStream();
                    addStream.ProblemId = dto.ProblemId;
                    addStream.Step = ZCTrackingRiskStreamEnum.ReturnInfo.GetEnumIntValue();
                    addStream.Status = 1;
                    addStream.Remark = "";
                    addStream.AddUser = UserContext.Current.UserId;
                    addStream.AddDate = DateTime.Now;
                    addStream.UserID = userIds_Factory[1];
                    addStream.UserID = userIds_Factory[0];
                    await IsExistMenuAuth(userIds_Factory[0]);
                    await riskStreamDb.AddAsync(addStream);
                    factoryUserId.Add(addStream.UserID);
                }
                #endregion

                //如果IQC确认任务已完成，清空IQC确认状态
                var iqcTaskCount = await _pubTaskService.GetTaskCount(ftable + 1, dto.ProblemId);
                if (iqcTaskCount == 0)
                {
                    problemInfo.IQCStatus = null;
                    problemInfo.IQCMemberList = "";
                    problemInfo.IQCMemberListName = "";
                    repository.Update(problemInfo, x => new { x.IQCStatus, x.IQCMemberList, x.IQCMemberListName });//清空IQC确认状态
                }
                else
                {
                    //IQC确认状态只保留IQC的任务，工厂的任务都关闭掉
                    var userIds_IQC = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, 1);
                    var userId_IQC = 0;
                    if (problemInfo.Factory == "04")//柯洱斯
                    {
                        userId_IQC = userIds_IQC[1];
                    }
                    if (problemInfo.Factory == "05")//亮亮
                    {
                        userId_IQC = userIds_IQC[1];
                    }
                    if (problemInfo.Factory == "09")//09惠州百富
                    {
                        userId_IQC = userIds_IQC[0];
                    }
                    problemInfo.IQCMemberList = userId_IQC.ToString();
                    problemInfo.IQCMemberListName = await _hrEmployeeService.GetNameByIDAsync(problemInfo.IQCMemberList);
                    repository.Update(problemInfo, x => new { x.IQCMemberList, x.IQCMemberListName });
                }
            }
            var save = await repository.SaveChangesAsync();
            if (save > 0)
            {
                if (dto.IsSubmit)
                {
                    #region 写入风险批次黑名单
                    var blacklistDb = repository.DbContext.Set<ZCTracking_RiskBlacklist>();
                    var now = DateTime.Now;
                    await blacklistDb.AddAsync(new ZCTracking_RiskBlacklist
                    {
                        RiskOrderId = riskOrderInfoEntity.ID,
                        ProblemId = dto.ProblemId,
                        Numbers = problemInfo.Numbers,
                        CInvCode = problemInfo.CInvCode,
                        BatchType = dto.BatchType ?? 0,
                        BatchInfo = dto.RiskBatch,
                        RiskStatus = 1,
                        OperateUser = UserContext.Current.UserId,
                        OperateDate = now,
                        AddUser = UserContext.Current.UserId,
                        AddDate = now,
                    });
                    await repository.SaveChangesAsync();
                    #endregion

                    //如果有工厂任务与仓库任务关闭掉
                    await _pubTaskService.FinishTaskAsync(ftable + 2, dto.ProblemId);
                    await _pubTaskService.FinishTaskAsync(ftable + 3, dto.ProblemId);

                    //发起任务
                    var taskName = "国内制程问题单【" + problemInfo.Numbers + "】风险订单工厂确认";
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(ftable + 14, dto.ProblemId.ToString(), taskName, factoryUserId, DateTime.Now, DateTime.Now.AddDays(3)));

                    /* 发邮件 */
                    var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
                    var productIdList = products.Select(x => x.ProductId).ToList();
                    var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/IQCConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    var context = await GetEmailHtml(dto.ProblemId, urlHtml);
                    var email = await _hrEmployeeService.GetEmailFromIDAsync(string.Join(',', factoryUserId));
                    var ccMail = "";
                    //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                    if (problemInfo.ProblemType == 3)
                    {
                        var sqeEmail = await GetWLEmail(problemInfo.CInvCode);
                        email += $";{sqeEmail}";
                        ccMail = $"{cuijuan}";
                    }
                    await SendEmail(UserContext.Current.Email, email, ccMail, taskName, context, productIdList);
                }
            }
            return WebResponseContent.OK_obj();
        }
        public async Task<WebResponseContent> EditRiskOrder(AddOrEditRiskOrderModel dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo == null)
            {
                return WebResponseContent.Error_obj("未找到制程问题！");
            }
            var ftable = GetfTable(problemInfo.ProblemType);

            var riskOrderInfoDb = repository.DbContext.Set<ZCTracking_RiskOrderInfo>();
            var riskOrderListDb = repository.DbContext.Set<ZCTracking_RiskOrderList>();
            var riskStreamDb = repository.DbContext.Set<ZCTracking_RiskStream>();
            var riskStreamLogDb = repository.DbContext.Set<ZCTracking_RiskStreamLog>();

            #region 风险信息
            var riskOrderInfo = await riskOrderInfoDb.FindAsync(dto.ID);
            riskOrderInfo.IsPatch = dto.IsPatch;
            riskOrderInfo.BatchType = dto.BatchType;
            riskOrderInfo.RiskBatch = dto.RiskBatch;
            riskOrderInfo.DeliveryQty = dto.DeliveryQty;
            riskOrderInfo.StockQty = dto.StockQty;
            riskOrderInfo.IssuedQty = dto.IssuedQty;
            riskOrderInfo.KESQty = dto.KESQty;
            riskOrderInfo.LLQty = dto.LLQty;
            riskOrderInfo.HZQty = dto.HZQty;
            riskOrderInfo.CKDQty = dto.CKDQty;
            riskOrderInfo.OtherQty = dto.OtherQty;
            riskOrderInfo.Remark = dto.Remark;
            riskOrderInfo.AddUser = UserContext.Current.UserId;
            riskOrderInfo.AddDate = DateTime.Now;
            riskOrderInfoDb.Update(riskOrderInfo);
            #endregion

            #region 订单
            var oldRiskOrderList = await riskOrderListDb.Where(x => x.ProblemId == dto.ProblemId).AsNoTracking().ToListAsync();
            riskOrderListDb.RemoveRange(oldRiskOrderList);

            var riskOrderListAdd = new List<ZCTracking_RiskOrderList>();
            foreach (var item in dto.OrderList)
            {
                var oldRiskOrder = oldRiskOrderList.Find(x => x.OrderNo == item.OrderNo && x.PartNumber == item.PartNumber);
                riskOrderListAdd.Add(new ZCTracking_RiskOrderList
                {
                    ProblemId = dto.ProblemId,
                    Factory = item.Factory,
                    OrderNo = item.OrderNo,
                    PartNumber = item.PartNumber,
                    Qty = item.Qty,
                    TotalinQty = item.TotalinQty,
                    IssuedQty = item.IssuedQty,
                    IssQty = item.IssQty,
                    IsPatch = item.IsPatch,
                    IsRisk = item.IsRisk,
                    ReturnType = oldRiskOrder?.ReturnType,
                    RiskUsedQty = oldRiskOrder?.RiskUsedQty,
                    ReturnQty = oldRiskOrder?.ReturnQty,
                    ReceivingQty = oldRiskOrder?.ReceivingQty,
                    FaliaoDate = item.FaliaoDate,
                    ProductName = item.ProductName,
                });
            }
            await riskOrderListDb.AddRangeAsync(riskOrderListAdd);
            #endregion

            #region 删除日志
            var oldStreams = await riskStreamDb.Where(x => x.ProblemId == dto.ProblemId).ToListAsync();
            riskStreamDb.RemoveRange(oldStreams);
            #endregion
            riskStreamLogDb.AddAsync(new ZCTracking_RiskStreamLog
            {
                ProblemId = dto.ProblemId,
                Step = ZCTrackingRiskStreamLogEnum.ModifyRiskOrder.GetEnumIntValue(),
                Status = 2,
                UserID = 0,
                Remark = $"{UserContext.Current.UserName}：修改风险订单。",
                AddUser = UserContext.Current.UserId,
                AddDate = DateTime.Now,
            });
            var factoryUserId = new List<int>();
            if (dto.IsSubmit)
            {

                #region 分发不同工厂
                var userIds_Factory = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, 2);
                var factorys = dto.OrderList.Select(x => x.Factory).Distinct().ToList();
                if (factorys.Contains("04"))
                {
                    var addStream = new ZCTracking_RiskStream();
                    addStream.ProblemId = dto.ProblemId;
                    addStream.Step = 14;
                    addStream.Status = 1;
                    addStream.Remark = "";
                    addStream.AddUser = UserContext.Current.UserId;
                    addStream.AddDate = DateTime.Now;
                    addStream.UserID = userIds_Factory[1];
                    await IsExistMenuAuth(userIds_Factory[1]);
                    await riskStreamDb.AddAsync(addStream);
                    factoryUserId.Add(addStream.UserID);
                }
                if (factorys.Contains("05"))
                {
                    var addStream = new ZCTracking_RiskStream();
                    addStream.ProblemId = dto.ProblemId;
                    addStream.Step = 14;
                    addStream.Status = 1;
                    addStream.Remark = "";
                    addStream.AddUser = UserContext.Current.UserId;
                    addStream.AddDate = DateTime.Now;
                    addStream.UserID = userIds_Factory[2];
                    await IsExistMenuAuth(userIds_Factory[2]);
                    await riskStreamDb.AddAsync(addStream);
                    factoryUserId.Add(addStream.UserID);
                }
                if (factorys.Contains("09"))
                {
                    var addStream = new ZCTracking_RiskStream();
                    addStream.ProblemId = dto.ProblemId;
                    addStream.Step = 14;
                    addStream.Status = 1;
                    addStream.Remark = "";
                    addStream.AddUser = UserContext.Current.UserId;
                    addStream.AddDate = DateTime.Now;
                    addStream.UserID = userIds_Factory[0];
                    await IsExistMenuAuth(userIds_Factory[0]);
                    await riskStreamDb.AddAsync(addStream);
                    factoryUserId.Add(addStream.UserID);
                }
                #endregion                

                //如果IQC确认任务已完成，清空IQC确认状态
                var iqcTaskCount = await _pubTaskService.GetTaskCount(ftable + 1, dto.ProblemId);
                if (iqcTaskCount == 0)
                {
                    problemInfo.IQCStatus = null;
                    problemInfo.IQCMemberList = "";
                    problemInfo.IQCMemberListName = "";
                    repository.Update(problemInfo, x => new { x.IQCStatus, x.IQCMemberList, x.IQCMemberListName });//清空IQC确认状态
                }
                else
                {
                    //IQC确认状态只保留IQC的任务，工厂的任务都关闭掉
                    var userIds_IQC = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, 1);
                    var userId_IQC = 0;
                    if (problemInfo.Factory == "04")//柯洱斯
                    {
                        userId_IQC = userIds_IQC[1];
                    }
                    if (problemInfo.Factory == "05")//亮亮
                    {
                        userId_IQC = userIds_IQC[1];
                    }
                    if (problemInfo.Factory == "09")//09惠州百富
                    {
                        userId_IQC = userIds_IQC[0];
                    }
                    problemInfo.IQCMemberList = userId_IQC.ToString();
                    problemInfo.IQCMemberListName = await _hrEmployeeService.GetNameByIDAsync(problemInfo.IQCMemberList);
                    repository.Update(problemInfo, x => new { x.IQCMemberList, x.IQCMemberListName });
                }
            }
            var save = await repository.SaveChangesAsync();
            if (save > 0)
            {
                //关闭掉正在进行中的工厂风险订单确认与仓库风险订单确认任务
                await _pubTaskService.FinishTaskAsync(ftable + 14, dto.ProblemId.ToString(), "SQE编辑，重新走流程关闭任务");
                await _pubTaskService.FinishTaskAsync(ftable + 15, dto.ProblemId.ToString(), "SQE编辑，重新走流程关闭任务");

                if (dto.IsSubmit)
                {
                    // 只在无黑名单记录时写入
                    var blacklistDb = repository.DbContext.Set<ZCTracking_RiskBlacklist>();
                    var existBlacklist = await blacklistDb.AnyAsync(x => x.RiskOrderId == dto.ID);
                    if (!existBlacklist)
                    {
                        var now = DateTime.Now;
                        await blacklistDb.AddAsync(new ZCTracking_RiskBlacklist
                        {
                            RiskOrderId = dto.ID ?? 0,
                            ProblemId = dto.ProblemId,
                            Numbers = problemInfo.Numbers,
                            CInvCode = problemInfo.CInvCode,
                            BatchType = dto.BatchType ?? 0,
                            BatchInfo = dto.RiskBatch,
                            RiskStatus = 1,
                            OperateUser = UserContext.Current.UserId,
                            OperateDate = now,
                            AddUser = UserContext.Current.UserId,
                            AddDate = now,
                        });
                        await repository.SaveChangesAsync();
                    }

                    //如果有工厂任务与仓库任务关闭掉
                    await _pubTaskService.FinishTaskAsync(ftable + 2, dto.ProblemId);
                    await _pubTaskService.FinishTaskAsync(ftable + 3, dto.ProblemId);

                    //发起任务
                    var taskName = "国内制程问题单【" + problemInfo.Numbers + "】风险订单工厂确认";
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(ftable + 14, dto.ProblemId.ToString(), taskName, factoryUserId, DateTime.Now, DateTime.Now.AddDays(3)));

                    /* 发邮件 */
                    var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
                    var productIdList = products.Select(x => x.ProductId).ToList();
                    var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/IQCConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    var context = await GetEmailHtml(dto.ProblemId, urlHtml);
                    var email = await _hrEmployeeService.GetEmailFromIDAsync(string.Join(',', factoryUserId));
                    var ccMail = "";
                    //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                    if (problemInfo.ProblemType == 3)
                    {
                        var sqeEmail = await GetWLEmail(problemInfo.CInvCode);
                        email += $";{sqeEmail}";
                        ccMail = $"{cuijuan}";
                    }
                    await SendEmail(UserContext.Current.Email, email, ccMail, taskName, context, productIdList);
                }
            }
            return WebResponseContent.OK_obj();
        }
        public async Task<WebResponseContent> FactoryConfirmRiskOrder(FactoryConfirmRiskOrderModel dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo == null)
            {
                return WebResponseContent.Error_obj("未找到制程问题！");
            }
            var ftable = GetfTable(problemInfo.ProblemType);
            var riskOrderListDb = repository.DbContext.Set<ZCTracking_RiskOrderList>();
            var riskStreamDb = repository.DbContext.Set<ZCTracking_RiskStream>();
            var riskStreamLogDb = repository.DbContext.Set<ZCTracking_RiskStreamLog>();
            var onlineOrderDb = repository.DbContext.Set<ZCTracking_OnlineOrder>();

            #region 订单
            var orderList = await riskOrderListDb.Where(x => x.ProblemId == dto.ProblemId).ToListAsync();
            if (dto.OrderList != null && dto.OrderList.Count > 0)
            {
                var orderDtoMap = dto.OrderList.ToDictionary(x => x.ID);
                foreach (var item in orderList)
                {
                    if (!orderDtoMap.TryGetValue(item.ID, out var order)) continue;
                    item.IsPatch = order.IsPatch;
                    item.ReturnType = order.ReturnType;
                    if (order.ReturnType == 2)
                    {
                        item.RiskUsedQty = order.RiskUsedQty;
                        item.ReturnQty = order.ReturnQty;
                    }
                    else
                    {
                        item.RiskUsedQty = null;
                        item.ReturnQty = null;
                    }
                }
            }
            riskOrderListDb.UpdateRange(orderList);
            #endregion

            #region 在线
            if (dto.OnlineOrder != null && dto.OnlineOrder.Count > 0)
            {
                var onlineOrder = await onlineOrderDb.Where(x => x.ProblemId == dto.ProblemId).ToListAsync();
                var onlineDtoMap = dto.OnlineOrder.Where(x => x.ID.HasValue).ToDictionary(x => x.ID.Value);
                foreach (var item in onlineOrder)
                {
                    if (!onlineDtoMap.TryGetValue(item.ID, out var entity)) continue;
                    item.Qty = entity.Qty;
                    item.ReturnType = entity.ReturnType;
                    item.OReturnQty = entity.ReturnType == 2 ? entity.OReturnQty : null;
                }
                onlineOrderDb.UpdateRange(onlineOrder);
            }
            #endregion

            await riskStreamLogDb.AddAsync(new ZCTracking_RiskStreamLog
            {
                ProblemId = dto.ProblemId,
                Step = ZCTrackingRiskStreamLogEnum.ReturnInfo.GetEnumIntValue(),
                Status = 2,
                UserID = 0,
                Remark = $"{UserContext.Current.UserName}：{(dto.IsSubmit ? "提交" : "保存")}退货信息。",
                AddUser = UserContext.Current.UserId,
                AddDate = DateTime.Now,
            });

            var factoryUserId = new List<int>();
            var unfinishedStep = true;
            var iqcTaskCount = 1;
            if (dto.IsSubmit)
            {
                var thisStream = await riskStreamDb.FirstOrDefaultAsync(x => x.ProblemId == dto.ProblemId && x.Step == 14 && x.UserID == UserContext.Current.UserId);
                if (thisStream == null) return WebResponseContent.Error_obj("未找到当前用户的工厂确认任务！");
                thisStream.Status = 2;
                thisStream.Remark = dto.Remark;
                riskStreamDb.Update(thisStream);
                //其他人任务已完成
                unfinishedStep = await riskStreamDb.AsNoTracking().AnyAsync(x => x.ProblemId == dto.ProblemId && x.Step == 14 && x.Status == 1 && x.UserID != UserContext.Current.UserId);
                //IQC已确认了CKD和库存
                iqcTaskCount = await _pubTaskService.GetTaskCount(ftable + 1, dto.ProblemId);
                if (!unfinishedStep && iqcTaskCount == 0)
                {
                    //发起仓库任务
                    var userIds = await _pilotProductStreamItemService.GetUserIdsByStreamName(streamNameWL, 3);
                    factoryUserId.Add(int.Parse(GetWarehouseMemberKey(problemInfo.Factory, userIds)));
                    await riskStreamDb.AddAsync(new ZCTracking_RiskStream
                    {
                        ProblemId = dto.ProblemId,
                        Step = ZCTrackingRiskStreamEnum.ReturnToInventory.GetEnumIntValue(),
                        Status = 1,
                        UserID = factoryUserId[0],
                        Remark = "",
                        AddUser = UserContext.Current.UserId,
                        AddDate = DateTime.Now,
                    });
                }
            }
            var save = await repository.SaveChangesAsync();
            if (save > 0 && dto.IsSubmit)
            {
                //完成任务
                await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetFinishTaskSelfSql(ftable + 14, dto.ProblemId.ToString()));
                if (!unfinishedStep && iqcTaskCount == 0)
                {
                    //发起仓库确认任务
                    var taskName = "国内制程问题单【" + problemInfo.Numbers + "】风险订单仓库确认";
                    await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(ftable + 15, dto.ProblemId.ToString(), taskName, factoryUserId, DateTime.Now, DateTime.Now.AddDays(3)));
                    /* 发邮件 */
                    var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
                    var productIdList = products.Select(x => x.ProductId).ToList();
                    var urlHtml = $"<a href='{FreqUsedConst.webSite}/QualityManage/IQCConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    var context = await GetEmailHtml(dto.ProblemId, urlHtml);
                    var email = await _hrEmployeeService.GetEmailFromIDAsync(string.Join(',', factoryUserId));
                    var ccMail = "";
                    //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                    if (problemInfo.ProblemType == 3)
                    {
                        var sqeEmail = await GetWLEmail(problemInfo.CInvCode);
                        email += $";{sqeEmail}";
                        ccMail = cuijuan;
                    }
                    await SendEmail(UserContext.Current.Email, email, ccMail, taskName, context, productIdList);
                }
            }
            return WebResponseContent.OK_obj();
        }

        public async Task<WebResponseContent> FillReturnNoRiskOrder(FillReturnNoRiskOrderModel dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            if (problemInfo == null)
            {
                return WebResponseContent.Error_obj("未找到制程问题！");
            }
            var ftable = GetfTable(problemInfo.ProblemType);
            var riskOrderListDb = repository.DbContext.Set<ZCTracking_RiskOrderList>();
            var riskStreamDb = repository.DbContext.Set<ZCTracking_RiskStream>();
            var riskStreamLogDb = repository.DbContext.Set<ZCTracking_RiskStreamLog>();

            #region 在库
            if (dto.StockReceiving != null && dto.StockReceiving.Any())
            {
                var stockDbSet = repository.DbContext.Set<ZCTracking_Stock>();
                var stockReceiving = new List<ZCTracking_Stock>();
                foreach (var item in dto.StockReceiving)
                {
                    var stockEntity = await stockDbSet.FirstOrDefaultAsync(x => x.ID == item.Id);
                    stockEntity.ReceivingQty = item.ReturnQty;
                    stockReceiving.Add(stockEntity);
                }
                stockDbSet.UpdateRange(stockReceiving);
            }


            #endregion
            #region 在线收货
            if (dto.OnlineReceiving != null && dto.OnlineReceiving.Any())
            {
                var onlineDbSet = repository.DbContext.Set<ZCTracking_OnlineOrder>();
                var onlineReceiving = new List<ZCTracking_OnlineOrder>();
                foreach (var item in dto.OnlineReceiving)
                {
                    var entity = await onlineDbSet.FirstOrDefaultAsync(x => x.ID == item.Id);
                    entity.ReceivingQty = item.ReturnQty;
                    onlineReceiving.Add(entity);
                }
                onlineDbSet.UpdateRange(onlineReceiving);
            }

            #endregion
            #region CKD机型收货
            if (dto.CKDReceiving != null && dto.CKDReceiving.Any())
            {
                var ckdReceiving = new List<ZCTracking_CKDProduct>();
                var ckdDbSet = repository.DbContext.Set<ZCTracking_CKDProduct>();
                foreach (var item in dto.CKDReceiving)
                {
                    var entity = await ckdDbSet.FirstOrDefaultAsync(x => x.ID == item.Id);
                    entity.ReceivingQty = item.ReturnQty;
                    ckdReceiving.Add(entity);
                }
                ckdDbSet.UpdateRange(ckdReceiving);
            }
            #endregion
            #region 风险订单       
            if (dto.OrderList.Any())
            {
                var orderList = await riskOrderListDb.Where(x => x.ProblemId == dto.ProblemId).ToListAsync();
                foreach (var item in orderList)
                {
                    var order = dto.OrderList.Find(x => x.Id == item.ID);
                    item.ReceivingQty = order.ReturnQty;
                }
                riskOrderListDb.UpdateRange(orderList);
            }
            #endregion

            problemInfo.OReturnOrderNo = dto.OReturnOrderNo;
            problemInfo.SReturnOrderNo = dto.SReturnOrderNo;
            repository.Update(problemInfo, x => new { x.OReturnOrderNo, x.SReturnOrderNo });

            riskStreamLogDb.AddAsync(new ZCTracking_RiskStreamLog
            {
                ProblemId = dto.ProblemId,
                Step = ZCTrackingRiskStreamLogEnum.ReturnToInventory.GetEnumIntValue(),
                Status = 1,
                UserID = 0,
                Remark = $"{UserContext.Current.UserName}：{(dto.IsSubmit ? "提交" : "保存")}退库信息。",
                AddUser = UserContext.Current.UserId,
                AddDate = DateTime.Now,
            });
            if (dto.IsSubmit)
            {
                var thisStream = await riskStreamDb.FirstOrDefaultAsync(x => x.ProblemId == dto.ProblemId && x.Step == 15 && x.UserID == UserContext.Current.UserId);
                thisStream.Status = 2;
                thisStream.Remark = dto.Remark;
                riskStreamDb.Update(thisStream);
            }
            var save = await repository.SaveChangesAsync();
            if (save > 0)
            {
                if (dto.IsSubmit)
                {
                    //完成任务            
                    await _pubTaskService.FinishTaskMultiAsync(ftable + 15, dto.ProblemId.ToString());
                    //发起任务
                    var taskName = "国内制程问题单【" + problemInfo.Numbers + "】已填写风险订单退库信息";
                    /* 发邮件 */
                    var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
                    var productIdList = products.Select(x => x.ProductId).ToList();
                    var urlHtml = $"<a  href='{FreqUsedConst.webSite}/QualityManage/IQCConfirm?id={dto.ProblemId}'>点击进入该链接页面</a>";
                    var context = await GetEmailHtml(dto.ProblemId, urlHtml);
                    //物料问题，要邮件给到对应的SQE，并抄送给崔娟。
                    var sqeEmail = await GetWLEmail(problemInfo.CInvCode);
                    var email = $"{sqeEmail}";
                    var ccMail = $"{cuijuan}";
                    await SendEmail(UserContext.Current.Email, email, ccMail, taskName, context, productIdList);
                }
            }
            return WebResponseContent.OK_obj();
        }
        #endregion
        #region 制程优化
        /// <summary>
        /// 生产角色确认
        /// </summary>
        /// <param name="dto"></param>
        /// <returns></returns>
        public async Task<WebResponseContent> ProblemConfirm(ProblemConfirmDto dto)
        {
            var problemInfo = await repository.FindAsyncFirst(x => x.ID == dto.ProblemId);
            var now = DateTime.Now;

            var products = await zCTracking_ProductNamesService.GetProductNamesByProblemId(dto.ProblemId);
            var problemOrders = await zCTracking_ProblemOrdersService.ProblemOrdersByProblemId(dto.ProblemId);
            var addXbOrders = await repository.DbContext.Set<ZCTracking_XBOrders>().Where(x => x.ProblemId == dto.ProblemId).ToListAsync();
            var orderNumberList = problemOrders.Select(x => x.OrderNumber).ToList();
            var productIdList = products.Select(x => x.ProductId).ToList();
            var newEmail = await GetNewEmail(problemInfo.ProblemType, problemInfo.VenCode, orderNumberList, productIdList);
            newEmail += $";{scbEmail}";

            var sendMail = UserContext.Current.UserInfo.Email;
            var ccMailList = sendMail;//抄送人     
            var oldProblemStatus = problemInfo.Status;
            if (dto.Result == 0)
            {
                problemInfo.Status = ZCTracking_ProblemStatusEnum.ProduceConfirmReject.GetEnumIntValue();
                problemInfo.ProduceConfirmDate = now;
                problemInfo.ProduceConfirmUser = UserContext.Current.UserId;
                problemInfo.ProduceConfirmRemark = dto.Remark;
                problemInfo.MemberListName = "";
                problemInfo.MemberList = "";

                repository.Update(problemInfo, x => new { x.IsDelete, x.Status, x.ProduceConfirmDate, x.ProduceConfirmUser, x.ProduceConfirmRemark, x.MemberList, x.MemberListName });
                //日志记录
                var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
                {
                    ProblemId = dto.ProblemId,
                    Step = (int)ZCTracking_ProblemOpeEnum.ProductionConfirm,
                    StepStr = "生产角色确认",
                    AddUser = UserContext.Current.UserId,
                    AddDate = now,
                    Measures = $"{now:yyyy/MM/dd},{UserContext.Current.UserName}确认:不同意",
                    Opinon = dto.Remark,
                    Result = dto.Result.ToString(),
                    ProblemStatus = oldProblemStatus,
                    MemberList = UserContext.Current.UserId.ToString(),
                });
                var save = await repository.SaveChangesAsync();

                var taskName = "国内制程问题单【" + problemInfo.Numbers + "】生产角色审核不同意";
                var context = await PersonLiableHtml("", problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ProduceConfirmReject, "", addXbOrders);
                var email = await _hrEmployeeService.GetEmailFromIDAsync(problemInfo.AddUser.ToString());
                if (!string.IsNullOrWhiteSpace(ccMailList))
                {
                    ccMailList += ";" + newEmail;
                }
                else
                {
                    ccMailList = newEmail;
                }
                await SendEmail(sendMail, email, ccMailList, taskName, context, productIdList);
            }
            else
            {
                var stepId = 1;
                var memberListName = await _pilotProductStreamItemService.GetUserNameByStreamName(streamNameRJ, stepId);

                problemInfo.Status = ZCTracking_ProblemStatusEnum.ResponsibleUser.GetEnumIntValue();
                problemInfo.ProduceConfirmDate = now;
                problemInfo.ProduceConfirmUser = UserContext.Current.UserId;
                problemInfo.ProduceConfirmRemark = dto.Remark;
                problemInfo.MemberListName = memberListName.Value;
                problemInfo.MemberList = memberListName.Key;
                repository.Update(problemInfo, x => new { x.Status, x.ProduceConfirmDate, x.ProduceConfirmUser, x.ProduceConfirmRemark, x.MemberList, x.MemberListName });
                //日志记录
                var log = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().AddAsync(new ZCTracking_ProblemSteplog
                {
                    ProblemId = dto.ProblemId,
                    Step = (int)ZCTracking_ProblemOpeEnum.ProductionConfirm,
                    StepStr = "生产角色确认",
                    AddUser = UserContext.Current.UserId,
                    AddDate = now,
                    Measures = $"{now:yyyy/MM/dd},{UserContext.Current.UserName}确认:同意",
                    Opinon = dto.Remark,
                    Result = dto.Result.ToString(),
                    ProblemStatus = oldProblemStatus,
                    MemberList = UserContext.Current.UserId.ToString(),
                });
                var save = await repository.SaveChangesAsync();

                //发起任务
                var taskName = "国内制程问题单【" + problemInfo.Numbers + "】待指定责任人";

                var userId = memberListName.Key.Split(",").Select(x => int.Parse(x)).ToList();
                await dapperHelperInfo.ExecuteAsync(_pubTaskService.GetAddTaskSql(GetfTable(problemInfo.ProblemType) + stepId, dto.ProblemId.ToString(), taskName, userId, now, now.AddDays(3)));
                /* 发邮件 */
                var urlHtml = $"<a href='{FreqUsedConst.webSite}/QualityManage/QualityAssignDutyMan?id={dto.ProblemId}'>点击进入该链接页面</a>";
                var context = await PersonLiableHtml(urlHtml, problemInfo, products, problemOrders, ZCTracking_ProblemStatusEnum.ResponsibleUser, "", addXbOrders);
                var email = await _hrEmployeeService.GetEmailFromIDAsync(memberListName.Key);
                email = string.Join(";", email.Split(";").Distinct());
                if (!string.IsNullOrWhiteSpace(ccMailList))
                {
                    ccMailList += ";" + newEmail;
                }
                else
                {
                    ccMailList = newEmail;
                }
                await SendEmail(sendMail, email, ccMailList, taskName, context, productIdList);
            }
            await _pubTaskService.FinishTaskAsync(GetfTable(problemInfo.ProblemType) + 5, problemInfo.ID);
            return WebResponseContent.OK_obj();
        }
        #endregion

        #region 任务邮件内容
        /// <summary>
        /// 指定责任人邮件内容
        /// </summary>
        /// <param name="problemInfo">问题</param>
        /// <param name="products">机型</param>
        /// <param name="orders">订单</param>
        /// <param name="status">状态</param>
        /// <param name="rejectRemark">驳回备注</param>
        /// <returns></returns>
        public async Task<string> PersonLiableHtml(string urlHtml, ZCTracking_ProblemList problemInfo, List<ZCTracking_ProductNames> products, List<ZCTracking_ProblemOrders> orders, ZCTracking_ProblemStatusEnum status, string rejectRemark = "", List<ZCTracking_XBOrders> xbOrders = null)
        {
            var productNameStr = string.Join(",", products.Select(x => x.ProductName));
            var addUserName = await _hrEmployeeService.GetNameByIDAsync(problemInfo.AddUser.ToString());
            var logList = await repository.DbContext.Set<ZCTracking_ProblemSteplog>().Where(x => x.ProblemId == problemInfo.ID).AsNoTracking().OrderByDescending(x => x.AddDate).ToListAsync();
            var reStartStep = ZCTracking_ProblemOpeEnum.ReStart.GetEnumIntValue();
            var reStartStepLog = logList.FirstOrDefault(x => x.Step == reStartStep);
            //var reStartExStepLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ReStart.GetEnumIntValue());
            if (problemInfo.MHead == "物料")
            {
                if (xbOrders == null)
                {
                    xbOrders = await repository.DbContext.Set<ZCTracking_XBOrders>().Where(x => x.ProblemId == problemInfo.ID).AsNoTracking().OrderBy(x => x.NoQty).ToListAsync();
                }
            }
            var riskInfo = await GetRiskDetail(problemInfo.ID);
            var html = "<html lang=\"en\">";
            html += "<head>";
            html += "<meta charset=\"UTF -8\">";
            html += "<meta http-equiv=\"X-UA-Compatible\" content=\"IE=edge\">";
            html += "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">";
            html += "<title>邮件详情模板</title>";
            html += @"<style>
    .detail-bd {
      width: 1100px;
      margin: 20px auto;
    }
    .header-bd {
      position: relative;
    }
    .number-bd {
      position: absolute;
      bottom: -8px;
      right: 3px;
      font-size: 13px;
    }
    .tab_header_title {
      color: #333;
      text-align: center;
      margin-bottom: 15px;
      font-size: 18px;
    }
    .tableModel {
      border-collapse: collapse;
      width: 100%;
    }
    .tableModel th {
      color: #666 !important;
      background-color: #f5f7fa;
      text-align: center;
      width: 115px;
    }
    .tableModel td {
      color: #222222;
      text-align: left;
    }
    .tableModel tr td,
    th {
      border: 1px solid #E4E7ED;
      padding: 8px 10px;
      text-overflow: ellipsis;
      vertical-align: middle;
      font-size: 14px;
      word-break: break-all;
    }
.add-date-span{
margin-left: 20px;
}
  </style>";
            html += "</head>";
            html += "<body>";
            html += "<div class=\"detail-bd\">";
            html += "<div class=\"header -bd\">";
            html += @$"<h3 class='tab_header_title'>制程问题详情";
            if (!string.IsNullOrWhiteSpace(urlHtml))
            {
                html += @$"<table width='90%' border='0' align='center' bordercolor='#e4e7ed' cellpadding='4'>        
<tbody>
    <tr>              
        <td align='center' colspan='4' class='html-style' style='font-weight: normal;'>{urlHtml}
        </td>        
    </tr>    
</tbody>
</table>";
            }
            html += @$"</h3>";
            html += $"<div class=\"number -bd\">单号:<span style=\"text-decoration: underline;margin-left:3px;\">{problemInfo.Numbers}</span>";
            html += "</div>";
            html += "</div>";
            html += "<table class=\"tableModel\">";
            html += " <tr>";
            html += "<th>加工厂</th>";
            html += $"<td style=\"width:200px;\">{(DicConst.FactoryDic.ContainsKey(problemInfo.Factory) ? DicConst.FactoryDic[problemInfo.Factory] : "")}</td>";
            html += "<th>机型</th>";
            html += $"<td style=\"width:200px;\">{(string.IsNullOrWhiteSpace(productNameStr) ? "物料" : productNameStr)}</td>";
            html += "<th>发现日期</th>";
            html += $"<td>{problemInfo.FoundDate.Value:yyyy-MM-dd}</td>";
            html += "</tr>";
            html += "<tr>";
            html += " <th>问题分类</th>";
            html += $"       <td>{(DicConst.ProblemTypeDic.ContainsKey(problemInfo.ProblemType) ? DicConst.ProblemTypeDic[problemInfo.ProblemType] : "")}</td>";
            html += "       <th>填单人</th>";
            html += $"       <td>{addUserName}</td>";
            html += "       <th>填单日期</th>";
            html += $"       <td>{problemInfo.AddDate:yyyy-MM-dd}</td>";
            html += "     </tr>";
            html += "     <tr>";
            html += "       <th>发现工位</th>";
            html += $"       <td>{problemInfo.Station}</td>";
            html += "       <th>版本</th>";
            html += $"       <td>{problemInfo.Version}</td>";
            html += "       <th>当前状态</th>";
            html += "       <td>";
            var displayStatus = problemInfo.Status;
            if (IsParallelConfirmStatus(problemInfo.Status))
            {
                displayStatus = await ResolveParallelConfirmStatusAsync(problemInfo.ID, problemInfo.ProblemType);
            }
            var preventionNames = "";
            if (IsParallelConfirmStatus(displayStatus))
            {
                var map = await GetPendingPreventionConfirmMembersMapAsync(new[] { problemInfo.ID });
                if (map.TryGetValue(problemInfo.ID, out var members))
                {
                    preventionNames = members.Names;
                }
                html += BuildParallelConfirmCurrentStatusHtml(displayStatus, problemInfo.ProblemType, problemInfo.MemberListName, preventionNames);
            }
            else
            {
                html += DicConst.ProblemStatusDic.ContainsKey((int)status) ? DicConst.ProblemStatusDic[(int)status] : "";
                if (problemInfo.Status != 32)
                {
                    html += $" <span style=\"color:red;\">{problemInfo.MemberListName}</span>";
                }
            }
            if (problemInfo.IQCStatus.HasValue)
            {
                html += @$"<div>
              <span>{(DicConst.ProblemStatusDic.ContainsKey(problemInfo.IQCStatus.Value) ? DicConst.ProblemStatusDic[problemInfo.IQCStatus.Value] : "")}</span>
              <span style=""color:red;"">{problemInfo.IQCMemberListName}</span>
            </div>";
            }
            if (riskInfo.RiskStreamList.Where(x => x.Status == 1).Any())
            {
                foreach (var group in riskInfo.RiskStreamList.Where(x => x.Status == 1).GroupBy(x => x.Step))
                {
                    var streamStepName = Enum.IsDefined(typeof(ZCTrackingRiskStreamEnum), group.Key)
                        ? ((ZCTrackingRiskStreamEnum)group.Key).GetEunmDesc()
                        : "";
                    var userNames = string.Join(",", group.Select(x => x.UserName));
                    html += @$"<div>
              <span>{streamStepName}</span>
              <span style=""color:red;"">{userNames}</span>
            </div>";
                }
            }
            html += "       </td>";
            html += "</tr>";
            html += "<tr>";
            html += "   <th >问题等级</th>";
            html += $"  <td style=\"width:200px;\">{problemInfo.ProblemLevel}</td>";
            if (problemInfo.OutPutStatus.HasValue)
            {
                html += "   <th>产品在制属性</th>";
                html += $"  <td colspan=\"3\">{DicConst.MoOrderAttrDic[problemInfo.OutPutStatus.Value]}</td>";
            }
            html += "</tr>";

            if (!string.IsNullOrWhiteSpace(problemInfo.AllReDepartment))
            {
                var departmentIds = problemInfo.AllReDepartment.Split(",").Select(x => int.Parse(x));
                var unitAllNames = await _hrEmployeeService.GetALLUnitAsync();
                var unitNames = string.Join(",", unitAllNames.Where(x => departmentIds.Contains(x.Id)).Select(x => x.Name).ToList());
                html += "<tr>";
                html += "<th>责任部门</th>";
                html += $"<td style=\"width:200px;\">{unitNames}</td>";
                html += "<th>原因分类</th>";
                html += $"<td colspan='3'>{problemInfo.ReasonClass}</td>";
                html += "</tr>";
                html += " <tr>";
                html += "   <th>原因分类说明</th>";
                html += $"   <td colspan=\"5\">{(!string.IsNullOrWhiteSpace(problemInfo.ReasonClassRemark) ? problemInfo.ReasonClassRemark.Replace("\n", "<br />") : "")}</td>";
                html += " </tr>";
            }
            if (orders.Any())
            {
                var orderQty = orders.Sum(x => x.OrderQty);
                var receiptyQty = orders.Sum(x => x.ReceiptQty);
                var onlineQty = orders.Sum(x => x.OnlineQty);
                html += "<tr>";
                html += "<th>生产订单</th>";
                html += "<td colspan=\"5\">";
                html += $"<div><table class=\"tableModel orderTable\">";
                html += "  <thead>";
                html += "    <th style=\"width: 55px; \">序号</th>";
                html += "    <th style=\"width: 100px; \">订单号</th>";
                html += "    <th style=\"width: 120px; \">发料日期</th>";
                html += "    <th style=\"width: 240px; \">PN</th>";
                html += "    <th>版本</th>";
                html += "    <th>订单数量</th>";
                html += "    <th>已入库数量</th>";
                html += "    <th>在线数量</th>";
                html += "  </thead>";
                html += "  <tbody>";
                for (int i = 0; i < orders.Count; i++)
                {
                    html += $"<tr><td>{i + 1}</td>";
                    html += $"<td>{orders[i].OrderNumber}</td>   ";
                    html += $"<td>{(orders[i].IssueDate.HasValue ? orders[i].IssueDate.Value.ToString("yyyy-MM-dd") : "")}</td>";
                    html += $"<td>{orders[i].PartName}</td>   ";
                    html += $"<td>{orders[i].Version}</td>   ";
                    html += $"<td style='text-align:center;'>{(orders[i].OrderQty > 0 ? orders[i].OrderQty.ToString("N0") : "")}</td>   ";
                    html += $"<td style='text-align:center;'>{(orders[i].ReceiptQty > 0 ? orders[i].ReceiptQty.ToString("N0") : "")}</td>   ";
                    html += $"<td style='text-align:center;'>{(orders[i].OnlineQty > 0 ? orders[i].OnlineQty.ToString("N0") : "")}</td></tr>";
                }
                html += $"<tr><th colspan='5' style='color: #333'>合计</th><th style='color: #333'>{(orderQty > 0 ? orderQty.ToString("N0") : "")}</th><th style='color: #333'>{(receiptyQty > 0 ? receiptyQty.ToString("N0") : "")}</th><th style='color: #333'>{(onlineQty > 0 ? onlineQty.ToString("N0") : "")}</th></tr>";
                html += "  </tbody>";
                html += "</table></div>";
                html += " </td>";
                html += "</tr>";
            }
            if (xbOrders != null)
            {
                if (xbOrders.Any())
                {
                    var orderQty = Convert.ToInt32(xbOrders.Sum(x => x.Qty));
                    var inQty = Convert.ToInt32(xbOrders.Sum(x => x.InQty));
                    var noQty = Convert.ToInt32(xbOrders.Sum(x => x.NoQty));
                    html += "<tr>";
                    html += "<th>小板订单</th>";
                    html += "<td colspan=\"5\">";
                    html += $"<div><table class=\"tableModel orderTable\">";
                    html += "  <thead>";
                    html += "    <th style=\"width: 50px; \">序号</th>";
                    html += "    <th style=\"width: 100px; \">订单号</th>";
                    html += "    <th style=\"width: 140px; \">订单类别</th>";
                    html += "    <th style=\"width: 200px; \">料号</th>";
                    html += "    <th style=\"width: 340px; \">描述</th>";
                    html += "    <th>数量</th>";
                    html += "    <th>入库数量</th>";
                    html += "    <th>未入库数量</th>";
                    html += "  </thead>";
                    html += "  <tbody>";
                    for (int i = 0; i < xbOrders.Count; i++)
                    {
                        html += $"<tr><td>{i + 1}</td>";
                        html += $"<td>{xbOrders[i].OrderNumber}</td>   ";
                        html += $"<td>{xbOrders[i].Description}</td>";
                        html += $"<td>{xbOrders[i].InvCode}</td>   ";
                        html += $"<td>{xbOrders[i].InvStd}</td>   ";
                        html += $"<td style='text-align:center;'>{(xbOrders[i].Qty > 0 ? Convert.ToInt32(xbOrders[i].Qty.Value).ToString("N0") : "")}</td>   ";
                        html += $"<td style='text-align:center;'>{(xbOrders[i].InQty > 0 ? Convert.ToInt32(xbOrders[i].InQty).ToString("N0") : "")}</td>   ";
                        html += $"<td style='text-align:center;'>{(xbOrders[i].NoQty > 0 ? Convert.ToInt32(xbOrders[i].NoQty).ToString("N0") : "")}</td></tr>";
                    }
                    html += $"<tr><th colspan='5' style='color: #333'>合计</th><th style='color: #333'>{(orderQty > 0 ? orderQty.ToString("N0") : "")}</th><th style='color: #333'>{(inQty > 0 ? inQty.ToString("N0") : "")}</th><th style='color: #333'>{(noQty > 0 ? noQty.ToString("N0") : "")}</th></tr>";
                    html += "  </tbody>";
                    html += "</table></div>";
                    html += " </td>";
                    html += "</tr>";
                }
            }
            if (string.IsNullOrWhiteSpace(problemInfo.MHead))
            {
                html += "<tr>";
                html += "   <th>影响数量</th>";
                html += $"  <td colspan=\"5\">{problemInfo.ImpactQty}</td>";
                html += "</tr>";
            }
            html += " <tr>";
            html += "   <th>生产数量</th>";
            html += $"   <td>{problemInfo.ProdQty}</td>";
            html += "   <th>不良数量</th>";
            html += $"   <td>{problemInfo.BadQty}</td>";
            html += "   <th>不良率</th>";
            html += $"   <td>{(problemInfo.Rate.HasValue ? ToolSet.ToRemoveZero(problemInfo.Rate.ToString()) : "")}%</td>";
            html += " </tr>";
            html += " <tr>";
            html += "   <th>是否需要停产</th>";
            html += $"   <td colspan=\"{(problemInfo.IsStop == 1 ? ' ' : '5')}\">{(problemInfo.IsStop == 1 ? '是' : '否')}</td>";
            if (problemInfo.IsStop == 1)
            {
                var stopStatusDic = new Dictionary<int, string>() {
                    {1,"停线中" } ,
                    {2,"已经重启" } ,
                    {3,"没有停线" } ,
                    {4,"重启审核中" } ,
                    {5,"审核通过" } ,
                    {6,"填写重启方案" } ,
                };
                html += "       <th>停线状态</th>";
                html += "       <td>";
                html += $"         {(problemInfo.StopStatus.HasValue ? stopStatusDic[problemInfo.StopStatus.Value] : "")}</td>";
                html += "       <th>停产日期</th>";
                html += $"       <td>{(problemInfo.StopDate.HasValue ? problemInfo.StopDate.Value.ToString("yyyy-MM-dd") : ' ')}</td>";
                if (new List<int> { 2, 4, 5 }.Contains(problemInfo.StopStatus.Value))
                {
                    var schemeLog = logList.Where(x => x.Step == ZCTracking_ProblemOpeEnum.ReStartScheme.GetEnumIntValue()).OrderByDescending(x => x.AddDate).FirstOrDefault();
                    if (schemeLog != null)
                    {
                        var schemeName = await _hrEmployeeService.GetNameByIDAsync(schemeLog.AddUser.ToString());
                        html += "     <tr>";
                        html += "       <th>重启方案</th>";
                        html += @$"       <td colspan='5'><div>{problemInfo.ReStartScheme}</div><div style='text-align: right; color: rgb(119, 119, 119); font-size: 12px;'>
                                        <span>{schemeName}</span> <span style='margin-left: 10px;'>{schemeLog.AddDate:yyyy-MM-dd HH:mm:ss}</span>
                                        </div></td>";
                        html += "     </tr>";
                    }
                }
                var stopExamine = logList.Where(x => x.Step == ZCTracking_ProblemOpeEnum.ReStartExamine.GetEnumIntValue()).OrderByDescending(x => x.AddDate).FirstOrDefault();
                if (stopExamine != null && new List<int> { 2, 5, 6 }.Contains(problemInfo.StopStatus.Value))
                {
                    var schemeName = await _hrEmployeeService.GetNameByIDAsync(stopExamine.AddUser.ToString());
                    html += "     <tr>";
                    html += "       <th>重启审核意见</th>";
                    html += @$"       <td colspan='5'><div>{(stopExamine.Result == "0" ? "不同意" : "同意")}</div><div>{stopExamine.Opinon}</div>
                                        <div style='text-align: right; color: rgb(119, 119, 119); font-size: 12px;'>
                                            <span>{schemeName}</span> <span style='margin-left: 10px;'>{stopExamine.AddDate:yyyy-MM-dd HH:mm:ss}</span>
                                        </div></td>";
                    html += "     </tr>";
                }
            }
            html += "</tr>";
            if (reStartStepLog != null)
            {
                html += "<tr>";
                html += "   <th>重启日期</th>";
                html += $"  <td colspan='{(!string.IsNullOrWhiteSpace(reStartStepLog.Opinon) ? ' ' : '5')}'>{reStartStepLog.Result}</td>";
                if (!string.IsNullOrWhiteSpace(reStartStepLog.Opinon))
                {
                    html += "   <th>重启备注</th>";
                    html += $"  <td colspan='3'>{reStartStepLog.Opinon.Replace("\n", "<br />")}</td>";
                }
                html += "</tr>";
            }
            var cInvDesc = string.Empty;
            var venName = string.Empty;
            if (!string.IsNullOrWhiteSpace(problemInfo.CInvCode))
            {
                cInvDesc = await zCTrackingService.GetInvStdByInvCode(problemInfo.CInvCode);
                html += "     <tr>";
                html += "       <th>料号&描述</th>";
                html += $"       <td colspan=\"5\">{problemInfo.CInvCode} <span style=\"margin-left: 10px;\"> {cInvDesc}</span></td>";
                html += "     </tr>";
            }
            if (!string.IsNullOrWhiteSpace(problemInfo.VenCode))
            {
                venName = await zCTrackingService.GetVenNameByVenCode(problemInfo.VenCode);
                html += "     <tr>";
                html += "       <th>供应商编号&名称</th>";
                html += $"       <td colspan=\"5\">{problemInfo.VenCode} <span style=\"margin-left: 10px;\"> {venName}</span></td>";
                html += "     </tr>";
            }
            html += "     <tr>";
            html += "       <th>问题描述</th>";
            html += $"       <td colspan=\"5\">{problemInfo.ProblemDesc}</td>";
            html += "     </tr>";
            if (!string.IsNullOrWhiteSpace(problemInfo.Improve))
            {
                html += "     <tr>";
                html += "       <th>改善建议</th>";
                html += $"       <td colspan=\"5\">{problemInfo.Improve}</td>";
                html += "     </tr>";
            }
            html += "     <tr>";
            html += "       <th>备注</th>";
            html += $"       <td colspan=\"5\" >{problemInfo.Remark}</td>";
            html += "     </tr>";
            if (!string.IsNullOrWhiteSpace(rejectRemark))
            {
                html += "     <tr>";
                html += "       <th>驳回原因</th>";
                html += $"       <td colspan=\"5\" >{rejectRemark}</td>";
                html += "     </tr>";
            }
            if (riskInfo.RiskStreamList.Any())
            {
                html += @$"
<tr><th colspan='6'>风险订单信息</th></tr>
<tr>
    <th>贴片物料
    </th>
    <td colspan=""5"">
    {(riskInfo.IsPatch == 1 ? '是' : '否')}
    </td>
</tr>
<tr>
    <th>风险批次
    </th>
    <td colspan=""5"">
    {riskInfo.RiskBatch}
    </td>
</tr>
<tr>
    <th>交货数量
    </th>
    <td >
    {riskInfo.DeliveryQty}
    </td>
    <th>库存数量
    </th>
    <td >
    {riskInfo.StockQty}
    </td>
    <th>发料数量<br>（柯洱斯）
    </th>
    <td >
    {riskInfo.KESQty}
    </td>
</tr>
<tr>

    <th>发料数量<br>（亮亮）
    </th>
    <td >
    {riskInfo.LLQty}
    </td>
    <th>发料数量<br>（惠州百富）
    </th>
    <td >
    {riskInfo.HZQty}
    </td>
    <th>发料数量<br>（CKD）
    </th>
    <td>
    {riskInfo.CKDQty}
    </td>
</tr>
<tr>
    <th>发料数量<br>（其它）
    </th>
    <td colspan=""5"">
    {riskInfo.OtherQty}
    </td>
</tr>
<tr>
    <th>备注
    </th>
    <td colspan=""5"">
    {riskInfo.Remark}
    </td>
</tr>
";
            }
            if (problemInfo.ProblemType == 7)
            {
                var productionConfirmLog = logList.Where(x => x.Step == ZCTracking_ProblemOpeEnum.ProductionConfirm.GetEnumIntValue()).FirstOrDefault();
                if (productionConfirmLog != null)
                {
                    html += "     <tr><th colspan='6'>生产角色确认</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(productionConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{productionConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>确认结果</th>";
                    html += $"       <td colspan=\"5\" >{(productionConfirmLog.Result == "0" ? "不同意" : "同意")}</td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>备注</th>";
                    html += $"       <td colspan=\"5\" >{productionConfirmLog.Opinon.Replace("\n", "<br />")}</td>";
                    html += "     </tr>";
                }
            }
            var Stock = await zCTracking_StockService.GetStockList(problemInfo.ID);
            var CKD = await zCTracking_CKDProductService.GetCKDProductList(problemInfo.ID);
            var OnlineOrder = await zCTracking_OnlineOrderService.GetOnlineOrders(problemInfo.ID);
            var OtherOrders = await zCTracking_OtherOrderService.GetOtherOrders(problemInfo.ID);
            //IQC意见
            var iqcLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.IQCOpinion.GetEnumIntValue());
            if (iqcLog != null && status.GetEnumIntValue() != ZCTracking_ProblemStatusEnum.IQCOpinion.GetEnumIntValue() && problemInfo.OldProblemType.HasValue && problemInfo.OldProblemType != problemInfo.ProblemType)
            {
                html += "     <tr><th colspan='6'>IQC意见</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(iqcLog.AddUser.ToString())}  <span class='add-date-span'>{iqcLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>是否修改分类</th>";
                html += $"      <td colspan=>是</td>";
                html += "       <th>改前问题分类</th>";
                html += $"       <td colspan=\"3\" >{(DicConst.ProblemTypeDic.ContainsKey(problemInfo.OldProblemType.Value) ? DicConst.ProblemTypeDic[problemInfo.OldProblemType.Value] : "")}</td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>备注</th>";
                html += $"       <td colspan=\"5\" >{iqcLog.Opinon}</td>";
                html += "     </tr>";
            }

            var resUserLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ResponsibleUser.GetEnumIntValue());
            if (resUserLog != null)
            {
                html += "     <tr><th colspan='6'>指定责任人</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(resUserLog.AddUser.ToString())}  <span class='add-date-span'>{resUserLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>责任人</th>";
                html += $"       <td colspan=\"5\" >{await _hrEmployeeService.GetNameByIDAsync(problemInfo.RUser)}    （{await _hrEmployeeService.GetUnitNameByUnitIdZLAsync(problemInfo.RDepartment.Value)}）</td>";
                html += "     </tr>";
            }
            var confirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.Confirm.GetEnumIntValue());
            var rConfirm = problemInfo.RConfirm.HasValue ? problemInfo.RConfirm.Value : 0;
            if (confirmLog != null)
            {
                html += "     <tr><th colspan='6'>责任人确认</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(confirmLog.AddUser.ToString())}  <span class='add-date-span'>{confirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>确认结果</th>";
                html += $"      <td {(rConfirm > 0 ? "" : "colspan='5'")}>{(rConfirm > 0 ? "是" : "否")}</td>";
                if (rConfirm > 0)
                {
                    html += "       <th>处理结果</th>";
                    html += $"      <td>{(problemInfo.DesignConfirmResult == 1 ? "改善" : problemInfo.DesignConfirmResult == 2 ? "保持现状" : "挂起")}</td>";
                    html += "       <th>计划完成时间</th>";
                    html += $"      <td>{(problemInfo.RCompleteTime.HasValue ? problemInfo.RCompleteTime.Value.ToString("yyyy-MM-dd") : "")}</td>";
                }
                html += "     </tr>";
                if (rConfirm > 0)
                {
                    if (!string.IsNullOrWhiteSpace(problemInfo.Reason))
                    {
                        html += "     <tr>";
                        html += "       <th>原因分析</th>";
                        html += $"      <td colspan=\"5\" >{problemInfo.Reason.Replace("\n", "<br />")}</td>";
                        html += "     </tr>";
                    }
                    html += "     <tr>";
                    html += "       <th>改善措施</th>";
                    html += $"       <td colspan=\"5\" >{problemInfo.Measures}</td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "     <tr>";
                    html += "       <th>预防对策</th>";
                    html += $"       <td colspan=\"5\" >{problemInfo.Prevention}</td>";
                    html += "     </tr>";
                }
                else
                {
                    html += "     <tr>";
                    html += "       <th>修改的问题分类</th>";
                    html += $"       <td colspan=\"5\" >{DicConst.ProblemTypeDic[problemInfo.ProblemType]}</td>";
                    html += "     </tr>";
                }
                html += "     <tr>";
                html += "       <th>备注</th>";
                html += $"       <td colspan=\"5\" >{confirmLog.Opinon}</td>";
                html += "     </tr>";
            }
            //物料问题
            if (problemInfo.ProblemType == 3)
            {
                //IQC意见
                if (iqcLog != null && status.GetEnumIntValue() != ZCTracking_ProblemStatusEnum.IQCOpinion.GetEnumIntValue())
                {
                    html += "     <tr><th colspan='6'>IQC意见</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='3' >{await _hrEmployeeService.GetNameByIDAsync(iqcLog.AddUser.ToString())}  <span class='add-date-span'>{iqcLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "       <th>是否修改分类</th>";
                    html += $"      <td colspan=>否</td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>处理意见</th>";
                    html += $"       <td colspan=\"5\" >{(problemInfo.IQCOpinion == 2 ? "退回仓库" : problemInfo.IQCOpinion == 3 ? "继续使用" : "")}</td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>备注</th>";
                    html += $"       <td colspan=\"5\" >{iqcLog.Opinon}</td>";
                    html += "     </tr>";
                    if (problemInfo.IQCOpinion == 3)
                    {
                        //库存
                        if (Stock.Any())
                        {
                            html += " <tr>";
                            html += "   <th>库存和在线</th>";
                            html += $"   <td colspan=\"5\" >";
                            html += $"<div><table class=\"tableModel orderTable\">";
                            html += "  <thead>";
                            html += "    <th style=\"width: 55px; \"></th>";
                            html += "    <th style=\"width: 100px; \">仓库</th>";
                            html += "    <th style=\"width: 100px; \">数量</th>";
                            html += "    <th style=\"width: 100px; \">合计</th>";
                            html += "  </thead>";
                            html += "  <tbody>";
                            var sumStock = Stock.Sum(x => x.Qty);
                            for (int i = 0; i < Stock.Count; i++)
                            {
                                html += $"<tr>";
                                if (i == 0) { html += $"<th rowspan='{Stock.Count}'>库存</th>"; }
                                html += $"<td>{Stock[i].Warehouse}</td>   ";
                                html += $"<td>{Stock[i].Qty:N0}</td>";
                                if (i == 0) { html += $"<td rowspan='{Stock.Count}'>{sumStock:N0}</td>"; }
                                html += $"</tr>";

                            }
                            html += "  </tbody>";
                            html += "</table></div>";
                            html += "   </td>";
                            html += "</tr>";
                        }
                        if (riskInfo.RiskStreamList.Any())
                        {
                            html += @$"
<tr>
    <th>风险订单</th>
    <td colspan=""5"" >
      <table class=""tableModel orderTable""><thead>
         <th style=""width:50px"">序号</th>
         <th style=""width:75px"">工厂</th>
         <th style=""width:75px"">订单号</th>        
         <th style="""">发料日期</th>
         <th style=""width:120px"">机型</th>
         <th style="""">订单数量</th>
         <th style="""">已入库数量</th>
         <th style="""">规划用量</th>
         <th style="""">发料数量</th>
         <th style="""">处理方式</th>
         {(riskInfo.IsPatch == 1 ? "<th style=''>是否贴片</th>" : "")}
         <th style="""">已使用数量</th>
         <th style="""">需退货数量</th>
         <th style="""">已收货数量</th>
        </thead><tbody>";
                            for (int i = 0; i < riskInfo.RiskOrderList.Count; i++)
                            {
                                var item = riskInfo.RiskOrderList[i];
                                html += $@"
         <tr>
            <td style=""text-align:center;"">{i + 1}</td>            
            <td>{item.Factory}</td>
            <td>{item.OrderNo}</td>
            <td>{item.FaliaoDate}</td>
            <td>{item.ProductName}</td>
            <td>{item.Qty:N0}</td>
            <td>{item.TotalinQty:N0}</td>
            <td>{item.IssuedQty:N0}</td>
            <td>{item.IssQty:N0}</td>
            <td>{(item.ReturnType == 1 ? "就地销毁" : item.ReturnType == 2 ? "退回仓库" : item.ReturnType == 3 ? "继续使用" : "")}</td>
            {(riskInfo.IsPatch == 1 ? $"<td>{(item.IsPatch.HasValue ? item.IsPatch.Value == 1 ? "是" : "否" : "")}</td>" : "")}
            <td>{item.RiskUsedQty:N0}</td>
            <td>{item.ReturnQty:N0}</td>
            <td>{item.ReceivingQty:N0}</td>
         </tr>";
                            }
                            html += @"</tbody></table></td></tr>";
                        }
                        else
                        {

                            //其他在线订单
                            if (OtherOrders.Any())
                            {
                                html += " <tr>";
                                html += "   <th>其他在线订单</th>";
                                html += $"   <td colspan=\"5\" >";
                                html += $"<div><table class=\"tableModel orderTable\">";
                                html += "  <thead>";
                                html += "    <th style=\"width: 55px; \">序号</th>";
                                html += "    <th style=\"width: 100px; \">工厂</th>";
                                html += "    <th style=\"width: 100px; \">订单号</th>";
                                html += "    <th style=\"width: 120px; \">物料发料日期</th>";
                                html += "    <th style=\"width: 240px; \">机型</th>"; ;
                                html += "    <th>订单数量</th>";
                                html += "    <th>已入库数量</th>";
                                html += "    <th>规划用量</th>";
                                html += "    <th>发料数量(含超领)</th>";
                                html += "  </thead>";
                                html += "  <tbody>";
                                for (int i = 0; i < OtherOrders.Count; i++)
                                {
                                    html += $"<tr><td>{i + 1}</td>";
                                    html += $"<td>{(DicConst.FactoryDic.ContainsKey(OtherOrders[i].Factory ?? "") ? DicConst.FactoryDic[OtherOrders[i].Factory] : "")}</td>";
                                    html += $"<td>{OtherOrders[i].OrderNo}</td>";
                                    html += $"<td>{(OtherOrders[i].FaliaoDate.HasValue ? OtherOrders[i].FaliaoDate.Value.ToString("yyyy-MM-dd") : "")}</td>   ";
                                    html += $"<td>{OtherOrders[i].ProductName}</td>   ";
                                    html += $"<td>{OtherOrders[i].Qty:N0}</td>   ";
                                    html += $"<td>{OtherOrders[i].TotalinQty:N0}</td>   ";
                                    html += $"<td>{OtherOrders[i].IssuedQty:N0}</td>";
                                    html += $"<td>{OtherOrders[i].IssQty:N0}</td></tr>";
                                }
                                html += "  </tbody>";
                                html += "</table></div>";
                                html += "   </td>";
                                html += "</tr>";
                            }
                        }
                        //ckd
                        if (CKD.Any())
                        {
                            html += " <tr>";
                            html += "   <th>CKD机型</th>";
                            html += $"   <td colspan=\"5\" >";
                            html += $"<div><table class=\"tableModel orderTable\">";
                            html += "  <thead>";
                            html += "    <th style=\"width: 55px; \">序号</th>";
                            html += "    <th style=\"min-width: 200px; \">PO</th>";
                            html += "    <th style=\"width: 200px; \">Invoice</th>";
                            html += "    <th style=\"width: 120px; \">发料数量</th>";
                            html += "    <th style=\"width: 120px; \">提货日期</th>"; ;
                            html += "  </thead>";
                            html += "  <tbody>";
                            for (int i = 0; i < CKD.Count; i++)
                            {
                                html += $"<tr><td>{i + 1}</td>";
                                html += $"<td>{CKD[i].PO}</td>";
                                html += $"<td>{CKD[i].Invoice}</td>";
                                html += $"<td>{CKD[i].IssuedQty:N0}</td>   ";
                                html += $"<td>{(CKD[i].PickupDate.HasValue ? CKD[i].PickupDate.Value.ToString("yyyy-MM-dd") : "")}</td>   ";
                            }
                            html += "  </tbody>";
                            html += "</table></div>";
                            html += "   </td>";
                            html += "</tr>";
                        }
                    }
                }
                //IQC确认
                var iqcConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ConfirmIQC.GetEnumIntValue());
                var factoryConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ConfirmFactory.GetEnumIntValue());
                if ((iqcConfirmLog != null || factoryConfirmLog != null) && status.GetEnumIntValue() >= ZCTracking_ProblemStatusEnum.ConfirmIQC.GetEnumIntValue())
                {
                    var addUserHtml = "";
                    if (iqcConfirmLog != null)
                    {
                        addUserHtml += $"<div>{iqcConfirmLog.StepStr}:  {await _hrEmployeeService.GetNameByIDAsync(iqcConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{iqcConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></div>";
                    }
                    if (factoryConfirmLog != null)
                    {
                        addUserHtml += $"<div>{factoryConfirmLog.StepStr}:  {await _hrEmployeeService.GetNameByIDAsync(factoryConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{factoryConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></div>";
                    }
                    var saveOrderNoLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.SaveOrderNo.GetEnumIntValue());
                    if (saveOrderNoLog != null)
                    {
                        addUserHtml += $"<div> <span>保存退货单号：</span>{await _hrEmployeeService.GetNameByIDAsync(saveOrderNoLog.AddUser.ToString())}  <span class='add-date-span'>{saveOrderNoLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></div>";
                    }
                    var fillOrderNoLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.FillOrderNo.GetEnumIntValue());
                    if (fillOrderNoLog != null)
                    {
                        addUserHtml += $"<div> <span>确认退货单号：</span>{await _hrEmployeeService.GetNameByIDAsync(fillOrderNoLog.AddUser.ToString())}  <span class='add-date-span'>{fillOrderNoLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></div>";
                    }
                    html += "     <tr><th colspan='6'>IQC确认</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{addUserHtml}</span></td>";
                    html += "     </tr>";
                    //库存
                    if (Stock.Any() || OnlineOrder.Any())
                    {
                        html += " <tr>";
                        html += "   <th>库存和在线</th>";
                        html += $"   <td colspan=\"5\" >";
                        html += $"<div><table class=\"tableModel orderTable\">";
                        html += "  <thead>";
                        html += "    <th style=\"width: 55px; \"></th>";
                        html += "    <th style=\"width: 100px; \">仓库</th>";
                        html += "    <th style=\"width: 100px; \">数量</th>";
                        html += "    <th style=\"width: 100px; \">合计</th>";
                        html += "    <th style=\"width: 100px; \">处理方式</th>";
                        html += "    <th>需退货数量</th>";
                        html += "    <th style=\"width: 110px; \">已收货数量</th>";
                        html += "  </thead>";
                        html += "  <tbody>";
                        var sumStock = Stock.Sum(x => x.Qty);
                        var sumOnlineOrder = OnlineOrder.Sum(x => x.Qty);
                        for (int i = 0; i < Stock.Count; i++)
                        {
                            html += $"<tr>";
                            if (i == 0) { html += $"<th rowspan='{Stock.Count}'>库存</th>"; }
                            html += $"<td>{Stock[i].Warehouse}</td>   ";
                            html += $"<td>{(Stock[i].Qty.HasValue ? Stock[i].Qty.ToString("N0") : "")}</td>";
                            if (i == 0)
                            {
                                html += $"<td rowspan='{Stock.Count}'>{sumStock:N0}</td>";
                                html += $"<td rowspan='{Stock.Count}'>{(Stock[i].ReturnType == 1 ? "就地销毁" : Stock[i].ReturnType == 2 ? "退回供应商" : Stock[i].ReturnType == 3 ? "继续使用" : "")}</td>";
                                html += $"<td rowspan='{Stock.Count}'>{(Stock[i].StockReturnQty.HasValue ? Stock[i].StockReturnQty.ToString("N0") : "")}</td>";
                                html += $"<td rowspan='{Stock.Count}'>{(Stock[i].ReceivingQty.HasValue ? Stock[i].ReceivingQty.ToString("N0") : "")}</td>";
                            }
                            html += $"</tr>";
                        }
                        for (int j = 0; j < OnlineOrder.Count; j++)
                        {
                            html += $"<tr>";
                            if (j == 0) { html += $"<th rowspan='{OnlineOrder.Count}'>在线</th>"; }
                            html += $"<td>{(OnlineOrder[j].ProductionType == 1 ? "已使用" : "未使用")}</td>";
                            html += $"<td>{(OnlineOrder[j].Qty.HasValue ? OnlineOrder[j].Qty.ToString("N0") : "")}</td>";
                            if (j == 0)
                            {
                                html += $"<td rowspan='{OnlineOrder.Count}'>{sumOnlineOrder:N0}</td>";
                            }
                            html += $"<td>{(OnlineOrder[j].ReturnType == 1 ? "就地销毁" : OnlineOrder[j].ReturnType == 2 ? "退回仓库" : OnlineOrder[j].ReturnType == 3 ? "继续使用" : "")}</td>";
                            html += $"<td>{(OnlineOrder[j].OReturnQty.HasValue ? OnlineOrder[j].OReturnQty.ToString("N0") : "")}</td>";
                            html += $"<td>{(OnlineOrder[j].ReceivingQty.HasValue ? OnlineOrder[j].ReceivingQty.ToString("N0") : "")}</td>";
                            html += $"</tr>";
                        }
                        html += "  </tbody>";
                        html += "</table></div>";
                        html += "   </td>";
                        html += "</tr>";
                    }
                    if (riskInfo.RiskStreamList.Any())
                    {
                        html += @$"
<tr>
    <th>风险订单</th>
    <td colspan=""5"" >
      <table class=""tableModel orderTable""><thead>
         <th style=""width:50px"">序号</th>
         <th style=""width:75px"">工厂</th>             
         <th style=""width:75px"">订单号</th>        
         <th style="""">发料日期</th>
         <th style=""width:120px"">机型</th>
         <th style="""">订单数量</th>
         <th style="""">已入库数量</th>
         <th style="""">规划用量</th>
         <th style="""">发料数量</th>
         <th style="""">处理方式</th>
         {(riskInfo.IsPatch == 1 ? "<th style=''>是否贴片</th>" : "")}
         <th style="""">已使用数量</th>
         <th style="""">需退货数量</th>
         <th style="""">已收货数量</th>
        </thead><tbody>";
                        for (int i = 0; i < riskInfo.RiskOrderList.Count; i++)
                        {
                            var item = riskInfo.RiskOrderList[i];
                            html += $@"
         <tr>
            <td style=""text-align:center;"">{i + 1}</td>            
            <td>{item.Factory}</td>
            <td>{item.OrderNo}</td>
            <td>{item.FaliaoDate}</td>
            <td>{item.ProductName}</td>
            <td>{item.Qty:N0}</td>
            <td>{item.TotalinQty:N0}</td>
            <td>{item.IssuedQty:N0}</td>
            <td>{item.IssQty:N0}</td>
            <td>{(item.ReturnType == 1 ? "就地销毁" : item.ReturnType == 2 ? "退回仓库" : item.ReturnType == 3 ? "继续使用" : "")}</td>
            {(riskInfo.IsPatch == 1 ? $"<td>{(item.IsPatch.HasValue ? item.IsPatch.Value == 1 ? "是" : "否" : "")}</td>" : "")}
            <td>{item.RiskUsedQty:N0}</td>
            <td>{item.ReturnQty:N0}</td>
            <td>{item.ReceivingQty:N0}</td>
         </tr>";
                        }
                        html += @"</tbody></table></td></tr>";
                    }
                    else
                    {
                        //其他在线订单
                        if (OtherOrders.Any())
                        {
                            html += " <tr>";
                            html += "   <th>其他在线订单</th>";
                            html += $"   <td colspan=\"5\" >";
                            html += $"<div><table class=\"tableModel orderTable\">";
                            html += "  <thead>";
                            html += "    <th style=\"width: 55px; \">序号</th>";
                            html += "    <th style=\"width: 100px; \">工厂</th>";
                            html += "    <th style=\"width: 100px; \">订单号</th>";
                            html += "    <th style=\"width: 120px; \">物料发料日期</th>";
                            html += "    <th style=\"width: 240px; \">机型</th>"; ;
                            html += "    <th >订单数量</th>";
                            html += "    <th style=\"width: 85px; \">已入库数量</th>";
                            html += "    <th >规划用量</th>";
                            html += "    <th style=\"width: 80px; \">发料数量(含超领)</th>";
                            html += "    <th style=\"width: 80px; \">处理方式</th>";
                            html += "    <th style=\"width: 90px; \">需退货数量</th>";
                            html += "    <th style=\"width: 90px; \">已收货数量</th>";
                            html += "  </thead>";
                            html += "  <tbody>";
                            for (int i = 0; i < OtherOrders.Count; i++)
                            {
                                html += $"<tr><td>{i + 1}</td>";
                                html += $"<td>{(DicConst.FactoryDic.ContainsKey(OtherOrders[i].Factory) ? DicConst.FactoryDic[OtherOrders[i].Factory] : "")}</td>";
                                html += $"<td>{OtherOrders[i].OrderNo}</td>";
                                html += $"<td>{(OtherOrders[i].FaliaoDate.HasValue ? OtherOrders[i].FaliaoDate.Value.ToString("yyyy-MM-dd") : "")}</td>   ";
                                html += $"<td>{OtherOrders[i].ProductName}</td>   ";
                                html += $"<td>{OtherOrders[i].Qty:N0}</td>   ";
                                html += $"<td>{OtherOrders[i].TotalinQty:N0}</td>   ";
                                html += $"<td>{OtherOrders[i].IssuedQty:N0}</td>";
                                html += $"<td>{OtherOrders[i].IssQty:N0}</td>";
                                html += $"<td>{(OtherOrders[i].ReturnType == 1 ? "就地销毁" : OtherOrders[i].ReturnType == 2 ? "退回仓库" : OtherOrders[i].ReturnType == 3 ? "继续使用" : "")}</td>";
                                html += $"<td>{OtherOrders[i].ReturnQty:N0}</td>";
                                html += $"<td>{OtherOrders[i].ReceivingQty:N0}</td></tr>";
                            }
                            html += "  </tbody>";
                            html += "</table></div>";
                            html += "   </td>";
                            html += "</tr>";
                        }
                    }
                    //ckd
                    if (CKD.Any())
                    {
                        html += " <tr>";
                        html += "   <th>CKD机型</th>";
                        html += $"   <td colspan=\"5\" >";
                        html += $"<div><table class=\"tableModel orderTable\">";
                        html += "  <thead>";
                        html += "    <th style=\"width: 55px; \">序号</th>";
                        html += "    <th style=\"min-width: 200px; \">PO</th>";
                        html += "    <th style=\"width: 200px; \">Invoice</th>";
                        html += "    <th style=\"width: 120px; \">发料数量</th>";
                        html += "    <th style=\"width: 120px; \">提货日期</th>";
                        html += "    <th style=\"width: 120px; \">处理方式</th>";
                        html += "    <th style=\"width: 120px; \">需退货数量</th>";
                        html += "    <th style=\"width: 120px; \">已收货数量</th>";
                        html += "  </thead>";
                        html += "  <tbody>";
                        for (int i = 0; i < CKD.Count; i++)
                        {
                            html += $"<tr><td>{i + 1}</td>";
                            html += $"<td>{CKD[i].PO}</td>";
                            html += $"<td>{CKD[i].Invoice}</td>";
                            html += $"<td>{CKD[i].IssuedQty:N0}</td>   ";
                            html += $"<td>{(CKD[i].PickupDate.HasValue ? CKD[i].PickupDate.Value.ToString("yyyy-MM-dd") : "")}</td>   ";
                            html += $"<td>{(CKD[i].ReturnType == 1 ? "就地销毁" : CKD[i].ReturnType == 2 ? "退回仓库" : CKD[i].ReturnType == 3 ? "继续使用" : CKD[i].ReturnType == 4 ? "待SQE确认" : "")}</td>";
                            html += $"<td>{CKD[i].ReturnQty:N0}</td>";
                            html += $"<td>{CKD[i].ReceivingQty:N0}</td></tr>";
                        }
                        html += "  </tbody>";
                        html += "</table></div>";
                        html += "   </td>";
                        html += "</tr>";
                    }
                    if (!string.IsNullOrWhiteSpace(problemInfo.OReturnOrderNo))
                    {
                        html += "     <tr>";
                        html += "       <th>在线退货单号</th>";
                        html += $"      <td colspan='5' >{problemInfo.OReturnOrderNo}</span></td>";
                        html += "     </tr>";
                    }
                    if (!string.IsNullOrWhiteSpace(problemInfo.SReturnOrderNo))
                    {
                        html += "     <tr>";
                        html += "       <th>在库退货单号</th>";
                        html += $"      <td colspan='5' >{problemInfo.SReturnOrderNo}</span></td>";
                        html += "     </tr>";
                    }
                    if (saveOrderNoLog != null || fillOrderNoLog != null)
                    {
                        if (fillOrderNoLog != null)
                        {
                            html += "     <tr>";
                            html += "       <th>备注</th>";
                            html += $"      <td colspan='5' >{fillOrderNoLog.Opinon}</span></td>";
                            html += "     </tr>";
                        }
                        else
                        {
                            html += "     <tr>";
                            html += "       <th>备注</th>";
                            html += $"      <td colspan='5' >{saveOrderNoLog.Opinon}</span></td>";
                            html += "     </tr>";
                        }
                    }
                }
                var sqeLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.FollowSQE.GetEnumIntValue());
                if (sqeLog != null)
                {
                    html += "     <tr><th colspan='6'>SQE跟进</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(sqeLog.AddUser.ToString())}  <span class='add-date-span'>{sqeLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>SQE跟进结果</th>";
                    html += $"       <td colspan=\"5\" >{sqeLog.Opinon}</td>";
                    html += "     </tr>";
                    if (problemInfo.ReasonClass != null && problemInfo.ReasonClass != "")
                    {
                        html += "     <tr>";
                        html += "       <th>原因分类</th>";
                        html += $"       <td colspan=\"5\" >{problemInfo.ReasonClass}</td>";
                        html += "     </tr>";
                        html += "     <tr>";
                        html += "       <th>原因说明</th>";
                        html += $"       <td colspan=\"5\" ><pre>{problemInfo.ReasonClassRemark}</pre></td>";
                        html += "     </tr>";
                    }
                    html += "     <tr>";
                    html += "       <th>是否设计更改</th>";
                    html += $"       <td colspan='{(sqeLog.Result == "1" ? "1" : "5")}' >{(sqeLog.Result == "1" ? "需要" : "不需要")}</td>";
                    if (sqeLog.Result == "1")
                    {
                        html += "    <th>责任人</th>";
                        html += $"   <td colspan='3'> {await _hrEmployeeService.GetNameByIDAsync(problemInfo.DesignUser.ToString())}</td>";
                    }
                    html += "     </tr>";
                }
                var disignLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.DesignChange.GetEnumIntValue());
                if (disignLog != null)
                {
                    html += "     <tr><th colspan='6'>设计更改</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(disignLog.AddUser.ToString())}  <span class='add-date-span'>{disignLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "        <th>确认结果</th>";
                    html += $"       <td {(problemInfo.DesignConfirmResult != 1 ? "colspan='5'" : "")}>{(problemInfo.DesignConfirmResult == 1 ? "改善" : problemInfo.DesignConfirmResult == 2 ? "保持现状" : "挂起")}</td>";
                    if (problemInfo.DesignConfirmResult == 1)
                    {
                        html += "    <th>预计完成时间</th>";
                        html += $"   <td colspan='3'> {(problemInfo.DesignDate.HasValue ? problemInfo.DesignDate.Value.ToString("yyyy-MM-dd") : "")}</td>";
                    }
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>原因说明</th>";
                    html += $"       <td colspan=\"5\" >{disignLog.Opinon}</td>";
                    html += "     </tr>";
                }
                var sqeConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ChangeConfirmSQE.GetEnumIntValue());
                if (sqeConfirmLog != null)
                {
                    html += "     <tr><th colspan='6'>SQE确认</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(sqeConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{sqeConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>SQE意见</th>";
                    html += $"       <td colspan=\"5\" >{sqeConfirmLog.Opinon}</td>";
                    html += "     </tr>";
                }
            }

            if (problemInfo.ProblemType == 4)
            {
                var confirmVersionLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ConfirmVersion.GetEnumIntValue());
                var zlConfirm = problemInfo.ZLConfirmResult.HasValue ? problemInfo.ZLConfirmResult.Value : 0;
                if (confirmVersionLog != null)
                {
                    html += "     <tr><th colspan='6'>工程确认</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(confirmVersionLog.AddUser.ToString())}  <span class='add-date-span'>{confirmVersionLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>确认结果</th>";
                    html += $"       <td colspan=\"5\" >{(zlConfirm > 0 ? "是" : "否")}</td>";
                    html += "     </tr>";
                    if (zlConfirm > 0)
                    {
                        html += "    <tr><th>处理结果</th>";
                        html += $"      <td colspan=\"5\">{(problemInfo.DesignConfirmResult == 1 ? "改善" : problemInfo.DesignConfirmResult == 2 ? "保持现状" : "挂起")}</td></tr>";
                        html += "    <tr><th>计划完成时间</th>";
                        html += $"      <td colspan=\"5\">{(problemInfo.RCompleteTime.HasValue ? problemInfo.RCompleteTime.Value.ToString("yyyy-MM-dd") : "")}</td></tr>";
                        html += "     <tr>";
                        html += "       <th>是否更改版本</th>";
                        html += $"       <td colspan=\"5\" >{(problemInfo.IsChangeOrderV == 1 ? "是" : "否")}  {problemInfo.OrderVersion}</td>";
                        html += "     </tr>";
                        if (!string.IsNullOrWhiteSpace(problemInfo.Reason))
                        {
                            html += "     <tr>";
                            html += "       <th>原因分析</th>";
                            html += $"      <td colspan=\"5\" >{problemInfo.Reason.Replace("\n", "<br />")}</td>";
                            html += "     </tr>";
                        }
                        html += "     <tr>";
                        html += "       <th>改善措施</th>";
                        html += $"       <td colspan=\"5\" >{problemInfo.Measures}</td>";
                        html += "     </tr>";
                        html += "     <tr>";
                        html += "     <tr>";
                        html += "       <th>预防对策</th>";
                        html += $"       <td colspan=\"5\" >{problemInfo.Prevention}</td>";
                        html += "     </tr>";
                    }
                    else
                    {
                        html += "     <tr>";
                        html += "       <th>修改的问题分类</th>";
                        html += $"       <td colspan=\"5\" >{DicConst.ProblemTypeDic[problemInfo.ProblemType]}</td>";
                        html += "     </tr>";
                    }
                    if (!string.IsNullOrWhiteSpace(confirmVersionLog.Opinon))
                    {
                        html += "     <tr>";
                        html += "       <th>备注</th>";
                        html += $"       <td colspan=\"5\" >{confirmVersionLog.Opinon}</td>";
                        html += "     </tr>";
                    }
                }
                var changeVersionLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ChangeVersion.GetEnumIntValue());
                if (changeVersionLog != null)
                {
                    html += "     <tr><th colspan='6'>PMC确认</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(changeVersionLog.AddUser.ToString())}  <span class='add-date-span'>{changeVersionLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>备注</th>";
                    html += $"       <td colspan=\"5\" >{changeVersionLog.Opinon}</td>";
                    html += "     </tr>";
                }
            }

            if (problemInfo.ProblemType == 5)
            {
                var factoryAnalysisLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.FactoryAnalysis.GetEnumIntValue());
                if (factoryAnalysisLog != null)
                {
                    html += "     <tr><th colspan='6'>工厂制程分析</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(factoryAnalysisLog.AddUser.ToString())}  <span class='add-date-span'>{factoryAnalysisLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>原因分析</th>";
                    html += $"       <td colspan=\"5\" >{factoryAnalysisLog.Result}</td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>制定对策</th>";
                    html += $"       <td colspan=\"5\" >{factoryAnalysisLog.Opinon}</td>";
                    html += "     </tr>";
                }
            }

            var preventionConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.PreventionConfirm.GetEnumIntValue());
            if (preventionConfirmLog != null)
            {
                html += "     <tr><th colspan='6'>预防对策确认</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(preventionConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{preventionConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>预防对策确认</th>";
                html += $"       <td colspan=\"5\" >{preventionConfirmLog.Opinon}</td>";
                html += "     </tr>";
            }

            var effectConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.EffectConfirm.GetEnumIntValue());
            if (effectConfirmLog != null)
            {
                html += "     <tr><th colspan='6'>效果确认</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(effectConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{effectConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>效果确认结果</th>";
                html += $"       <td colspan=\"5\" >{effectConfirmLog.Opinon}</td>";
                html += "     </tr>";
            }

            var closingConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ClosingConfirm.GetEnumIntValue());
            if (closingConfirmLog != null)
            {
                html += "     <tr><th colspan='6'>结案确认</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(closingConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{closingConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>结案结论</th>";
                html += $"       <td colspan=\"5\" >{closingConfirmLog.Opinon}</td>";
                html += "     </tr>";
            }
            html += "   </table>";
            html += " </div>";
            html += "</body></html>";
            return html;
        }

        public async Task<string> GetEmailHtml(int problemId, string url, string rejectRemark = "")
        {
            var detail = await GetProblemView(problemId);
            var productNameStr = string.Join(",", detail.ProductNames.Select(x => x.ProductName));
            var logList = detail.StepLogs;
            var reStartStep = ZCTracking_ProblemOpeEnum.ReStart.GetEnumIntValue();
            var reStartStepLog = logList.Find(x => x.Step == reStartStep);
            var xbOrders = detail.XBOrders.OrderBy(x => x.NoQty).ToList();
            var orders = detail.Orders;
            var riskInfo = await GetRiskDetail(problemId);
            var html = "<html lang=\"en\">";
            html += "<head>";
            html += "<meta charset=\"UTF -8\">";
            html += "<meta http-equiv=\"X-UA-Compatible\" content=\"IE=edge\">";
            html += "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">";
            html += "<title>邮件详情模板</title>";
            html += @"<style>
    .detail-bd {
      width: 1100px;
      margin: 20px auto;
    }
    .header-bd {
      position: relative;
    }
    .number-bd {
      position: absolute;
      bottom: -8px;
      right: 3px;
      font-size: 13px;
    }
    .tab_header_title {
      color: #333;
      text-align: center;
      margin-bottom: 15px;
      font-size: 18px;
    }
    .tableModel {
      border-collapse: collapse;
      width: 100%;
    }
    .tableModel th {
      color: #666 !important;
      background-color: #f5f7fa;
      text-align: center;
      width: 115px;
    }
    .tableModel td {
      color: #222222;
      text-align: left;
    }
    .tableModel tr td,
    th {
      border: 1px solid #E4E7ED;
      padding: 8px 10px;
      text-overflow: ellipsis;
      vertical-align: middle;
      font-size: 14px;
      word-break: break-all;
    }
.add-date-span{
margin-left: 20px;
}
  </style>";
            html += "</head>";
            html += "<body>";
            html += "<div class=\"detail-bd\">";
            html += "<div class=\"header -bd\">";
            html += @$"<h3 class='tab_header_title'>制程问题详情";
            if (!string.IsNullOrWhiteSpace(url))
            {
                html += @$"<table width='90%' border='0' align='center' bordercolor='#e4e7ed' cellpadding='4'>        
<tbody>
    <tr>              
        <td align='center' colspan='4' class='html-style' style='font-weight: normal;'>{url}
        </td>        
    </tr>    
</tbody>
</table>";
            }
            html += @$"</h3>";
            html += $"<div class=\"number -bd\">单号:<span style=\"text-decoration: underline;margin-left:3px;\">{detail.Numbers}</span>";
            html += "</div>";
            html += "</div>";
            html += "<table class=\"tableModel\">";
            html += " <tr>";
            html += "<th>加工厂</th>";
            html += $"<td style=\"width:200px;\">{(DicConst.FactoryDic.ContainsKey(detail.Factory) ? DicConst.FactoryDic[detail.Factory] : "")}</td>";
            html += "<th>机型</th>";
            html += $"<td style=\"width:200px;\">{(string.IsNullOrWhiteSpace(productNameStr) ? "物料" : productNameStr)}</td>";
            html += "<th>发现日期</th>";
            html += $"<td>{detail.FoundDate.Value:yyyy-MM-dd}</td>";
            html += "</tr>";
            html += "<tr>";
            html += " <th>问题分类</th>";
            html += $"       <td>{(DicConst.ProblemTypeDic.ContainsKey(detail.ProblemType) ? DicConst.ProblemTypeDic[detail.ProblemType] : "")}</td>";
            html += "       <th>填单人</th>";
            html += $"       <td>{detail.AddUserName}</td>";
            html += "       <th>填单日期</th>";
            html += $"       <td>{detail.AddDate:yyyy-MM-dd}</td>";
            html += "     </tr>";
            html += "     <tr>";
            html += "       <th>发现工位</th>";
            html += $"       <td>{detail.Station}</td>";
            html += "       <th>版本</th>";
            html += $"       <td>{detail.Version}</td>";
            html += "       <th>当前状态</th>";
            html += "       <td>";
            var parallelHtml = BuildParallelConfirmCurrentStatusHtml(detail.Status, detail.ProblemType, detail.MemberListName, detail.PreventionMemberListName);
            if (!string.IsNullOrEmpty(parallelHtml))
            {
                html += parallelHtml;
            }
            else
            {
                html += DicConst.ProblemStatusDic.ContainsKey(detail.Status) ? DicConst.ProblemStatusDic[detail.Status] : "";
                if (detail.Status != 32)
                {
                    html += $" <span style=\"color:red;\">{detail.MemberListName}</span>";
                }
            }
            if (detail.IQCStatus.HasValue)
            {
                html += @$"<div>
              <span>{(DicConst.ProblemStatusDic.ContainsKey(detail.IQCStatus.Value) ? DicConst.ProblemStatusDic[detail.IQCStatus.Value] : "")}</span>
              <span style=""color:red;"">{detail.IQCMemberListName}</span>
            </div>";
            }
            if (detail.RiskStatus.HasValue)
            {
                foreach (var group in riskInfo.RiskStreamList.Where(x => x.Status == 1).GroupBy(x => x.Step))
                {
                    var streamStepName = Enum.IsDefined(typeof(ZCTrackingRiskStreamEnum), group.Key)
                        ? ((ZCTrackingRiskStreamEnum)group.Key).GetEunmDesc()
                        : "";
                    var userNames = string.Join(",", group.Select(x => x.UserName));
                    html += @$"<div>
              <span>{streamStepName}</span>
              <span style=""color:red;"">{userNames}</span>
            </div>";
                }
            }
            html += "       </td>";
            html += "</tr>";
            html += "<tr>";
            html += "   <th >问题等级</th>";
            html += $"  <td style=\"width:200px;\">{detail.ProblemLevel}</td>";
            if (detail.OutPutStatus.HasValue)
            {
                html += "   <th>产品在制属性</th>";
                html += $"  <td colspan=\"3\">{DicConst.MoOrderAttrDic[detail.OutPutStatus.Value]}</td>";
            }
            html += "</tr>";

            if (!string.IsNullOrWhiteSpace(detail.AllReDepartment))
            {
                var departmentIds = detail.AllReDepartment.Split(",").Select(x => int.Parse(x));
                var unitAllNames = await _hrEmployeeService.GetALLUnitAsync();
                var unitNames = string.Join(",", unitAllNames.Where(x => departmentIds.Contains(x.Id)).Select(x => x.Name).ToList());
                html += "<tr>";
                html += "<th>责任部门</th>";
                html += $"<td style=\"width:200px;\">{unitNames}</td>";
                html += "<th>原因分类</th>";
                html += $"<td colspan='3'>{detail.ReasonClass}</td>";
                html += "</tr>";
                html += " <tr>";
                html += "   <th>原因分类说明</th>";
                html += $"   <td colspan=\"5\">{(!string.IsNullOrWhiteSpace(detail.ReasonClassRemark) ? detail.ReasonClassRemark.Replace("\n", "<br />") : "")}</td>";
                html += " </tr>";
            }
            if (orders.Any())
            {
                var orderQty = orders.Sum(x => x.OrderQty);
                var receiptyQty = orders.Sum(x => x.ReceiptQty);
                var onlineQty = orders.Sum(x => x.OnlineQty);
                html += "<tr>";
                html += "<th>生产订单</th>";
                html += "<td colspan=\"5\">";
                html += $"<div><table class=\"tableModel orderTable\">";
                html += "  <thead>";
                html += "    <th style=\"width: 55px; \">序号</th>";
                html += "    <th style=\"width: 100px; \">订单号</th>";
                html += "    <th style=\"width: 120px; \">发料日期</th>";
                html += "    <th style=\"width: 240px; \">PN</th>";
                html += "    <th>版本</th>";
                html += "    <th>订单数量</th>";
                html += "    <th>已入库数量</th>";
                html += "    <th>在线数量</th>";
                html += "  </thead>";
                html += "  <tbody>";
                for (int i = 0; i < orders.Count; i++)
                {
                    html += $"<tr><td>{i + 1}</td>";
                    html += $"<td>{orders[i].OrderNumber}</td>   ";
                    html += $"<td>{orders[i].IssueDate?.ToString("yyyy-MM-dd")}</td>";
                    html += $"<td>{orders[i].PartName}</td>   ";
                    html += $"<td>{orders[i].Version}</td>   ";
                    html += $"<td style='text-align:center;'>{(orders[i].OrderQty > 0 ? orders[i].OrderQty.ToString("N0") : "")}</td>   ";
                    html += $"<td style='text-align:center;'>{(orders[i].ReceiptQty > 0 ? orders[i].ReceiptQty.ToString("N0") : "")}</td>   ";
                    html += $"<td style='text-align:center;'>{(orders[i].OnlineQty > 0 ? orders[i].OnlineQty.ToString("N0") : "")}</td></tr>";
                }
                html += $"<tr><th colspan='5' style='color: #333'>合计</th><th style='color: #333'>{(orderQty > 0 ? orderQty.ToString("N0") : "")}</th><th style='color: #333'>{(receiptyQty > 0 ? receiptyQty.ToString("N0") : "")}</th><th style='color: #333'>{(onlineQty > 0 ? onlineQty.ToString("N0") : "")}</th></tr>";
                html += "  </tbody>";
                html += "</table></div>";
                html += " </td>";
                html += "</tr>";
            }
            if (detail.MHead == "物料")
            {
                if (xbOrders.Any())
                {
                    var orderQty = Convert.ToInt32(xbOrders.Sum(x => x.Qty));
                    var inQty = Convert.ToInt32(xbOrders.Sum(x => x.InQty));
                    var noQty = Convert.ToInt32(xbOrders.Sum(x => x.NoQty));
                    html += "<tr>";
                    html += "<th>小板订单</th>";
                    html += "<td colspan=\"5\">";
                    html += $"<div><table class=\"tableModel orderTable\">";
                    html += "  <thead>";
                    html += "    <th style=\"width: 50px; \">序号</th>";
                    html += "    <th style=\"width: 100px; \">订单号</th>";
                    html += "    <th style=\"width: 140px; \">订单类别</th>";
                    html += "    <th style=\"width: 200px; \">料号</th>";
                    html += "    <th style=\"width: 340px; \">描述</th>";
                    html += "    <th>数量</th>";
                    html += "    <th>入库数量</th>";
                    html += "    <th>未入库数量</th>";
                    html += "  </thead>";
                    html += "  <tbody>";
                    for (int i = 0; i < xbOrders.Count; i++)
                    {
                        html += $"<tr><td>{i + 1}</td>";
                        html += $"<td>{xbOrders[i].OrderNumber}</td>   ";
                        html += $"<td>{xbOrders[i].Description}</td>";
                        html += $"<td>{xbOrders[i].InvCode}</td>   ";
                        html += $"<td>{xbOrders[i].InvStd}</td>   ";
                        html += $"<td style='text-align:center;'>{(xbOrders[i].Qty > 0 ? Convert.ToInt32(xbOrders[i].Qty.Value).ToString("N0") : "")}</td>   ";
                        html += $"<td style='text-align:center;'>{(xbOrders[i].InQty > 0 ? Convert.ToInt32(xbOrders[i].InQty).ToString("N0") : "")}</td>   ";
                        html += $"<td style='text-align:center;'>{(xbOrders[i].NoQty > 0 ? Convert.ToInt32(xbOrders[i].NoQty).ToString("N0") : "")}</td></tr>";
                    }
                    html += $"<tr><th colspan='5' style='color: #333'>合计</th><th style='color: #333'>{(orderQty > 0 ? orderQty.ToString("N0") : "")}</th><th style='color: #333'>{(inQty > 0 ? inQty.ToString("N0") : "")}</th><th style='color: #333'>{(noQty > 0 ? noQty.ToString("N0") : "")}</th></tr>";
                    html += "  </tbody>";
                    html += "</table></div>";
                    html += " </td>";
                    html += "</tr>";
                }
            }
            if (string.IsNullOrWhiteSpace(detail.MHead))
            {
                html += "<tr>";
                html += "   <th>影响数量</th>";
                html += $"  <td colspan=\"5\">{detail.ImpactQty}</td>";
                html += "</tr>";
            }
            html += " <tr>";
            html += "   <th>生产数量</th>";
            html += $"   <td>{detail.ProdQty}</td>";
            html += "   <th>不良数量</th>";
            html += $"   <td>{detail.BadQty}</td>";
            html += "   <th>不良率</th>";
            html += $"   <td>{(detail.Rate.HasValue ? ToolSet.ToRemoveZero(detail.Rate.ToString()) : "")}%</td>";
            html += " </tr>";
            html += " <tr>";
            html += "   <th>是否需要停产</th>";
            html += $"   <td colspan=\"{(detail.IsStop == 1 ? ' ' : '5')}\">{(detail.IsStop == 1 ? '是' : '否')}</td>";
            if (detail.IsStop == 1)
            {
                var stopStatusDic = new Dictionary<int, string>() {
                    {1,"停线中" } ,
                    {2,"已经重启" } ,
                    {3,"没有停线" } ,
                    {4,"重启审核中" } ,
                    {5,"审核通过" } ,
                    {6,"填写重启方案" } ,
                };
                html += "       <th>停线状态</th>";
                html += "       <td>";
                html += $"         {(detail.StopStatus.HasValue ? stopStatusDic[detail.StopStatus.Value] : "")}</td>";
                html += "       <th>停产日期</th>";
                html += $"       <td>{(detail.StopDate.HasValue ? detail.StopDate.Value.ToString("yyyy-MM-dd") : ' ')}</td>";
                if (new List<int> { 2, 4, 5 }.Contains(detail.StopStatus.Value))
                {
                    var schemeLog = logList.Where(x => x.Step == ZCTracking_ProblemOpeEnum.ReStartScheme.GetEnumIntValue()).OrderByDescending(x => x.AddDate).FirstOrDefault();
                    if (schemeLog != null)
                    {
                        var schemeName = await _hrEmployeeService.GetNameByIDAsync(schemeLog.AddUser.ToString());
                        html += "     <tr>";
                        html += "       <th>重启方案</th>";
                        html += @$"       <td colspan='5'><div>{detail.ReStartScheme}</div><div style='text-align: right; color: rgb(119, 119, 119); font-size: 12px;'>
                                        <span>{schemeName}</span> <span style='margin-left: 10px;'>{schemeLog.AddDate:yyyy-MM-dd HH:mm:ss}</span>
                                        </div></td>";
                        html += "     </tr>";
                    }
                }
                var stopExamine = logList.Where(x => x.Step == ZCTracking_ProblemOpeEnum.ReStartExamine.GetEnumIntValue()).OrderByDescending(x => x.AddDate).FirstOrDefault();
                if (stopExamine != null && new List<int> { 2, 5, 6 }.Contains(detail.StopStatus.Value))
                {
                    var schemeName = await _hrEmployeeService.GetNameByIDAsync(stopExamine.AddUser.ToString());
                    html += "     <tr>";
                    html += "       <th>重启审核意见</th>";
                    html += @$"       <td colspan='5'><div>{(stopExamine.Result == "0" ? "不同意" : "同意")}</div><div>{stopExamine.Opinon}</div>
                                        <div style='text-align: right; color: rgb(119, 119, 119); font-size: 12px;'>
                                            <span>{schemeName}</span> <span style='margin-left: 10px;'>{stopExamine.AddDate:yyyy-MM-dd HH:mm:ss}</span>
                                        </div></td>";
                    html += "     </tr>";
                }
            }
            html += "</tr>";
            if (reStartStepLog != null)
            {
                html += "<tr>";
                html += "   <th>重启日期</th>";
                html += $"  <td colspan='{(!string.IsNullOrWhiteSpace(reStartStepLog.Opinon) ? ' ' : '5')}'>{reStartStepLog.Result}</td>";
                if (!string.IsNullOrWhiteSpace(reStartStepLog.Opinon))
                {
                    html += "   <th>重启备注</th>";
                    html += $"  <td colspan='3'>{reStartStepLog.Opinon.Replace("\n", "<br />")}</td>";
                }
                html += "</tr>";
            }
            var cInvDesc = string.Empty;
            var venName = string.Empty;
            if (!string.IsNullOrWhiteSpace(detail.CInvCode))
            {
                cInvDesc = await zCTrackingService.GetInvStdByInvCode(detail.CInvCode);
                html += "     <tr>";
                html += "       <th>料号&描述</th>";
                html += $"       <td colspan=\"5\">{detail.CInvCode} <span style=\"margin-left: 10px;\"> {cInvDesc}</span></td>";
                html += "     </tr>";
            }
            if (!string.IsNullOrWhiteSpace(detail.VenCode))
            {
                venName = await zCTrackingService.GetVenNameByVenCode(detail.VenCode);
                html += "     <tr>";
                html += "       <th>供应商编号&名称</th>";
                html += $"       <td colspan=\"5\">{detail.VenCode} <span style=\"margin-left: 10px;\"> {venName}</span></td>";
                html += "     </tr>";
            }
            html += "     <tr>";
            html += "       <th>问题描述</th>";
            html += $"       <td colspan=\"5\">{detail.ProblemDesc}</td>";
            html += "     </tr>";
            if (!string.IsNullOrWhiteSpace(detail.Improve))
            {
                html += "     <tr>";
                html += "       <th>改善建议</th>";
                html += $"       <td colspan=\"5\">{detail.Improve}</td>";
                html += "     </tr>";
            }
            html += "     <tr>";
            html += "       <th>备注</th>";
            html += $"       <td colspan=\"5\" >{detail.Remark}</td>";
            html += "     </tr>";
            if (!string.IsNullOrWhiteSpace(rejectRemark))
            {
                html += "     <tr>";
                html += "       <th>驳回原因</th>";
                html += $"       <td colspan=\"5\" >{rejectRemark}</td>";
                html += "     </tr>";
            }
            if (riskInfo.RiskStreamList.Any())
            {
                html += @$"
<tr><th colspan='6'>风险订单信息</th></tr>
<tr>
    <th>贴片物料
    </th>
    <td colspan=""5"">
    {(riskInfo.IsPatch == 1 ? '是' : '否')}
    </td>
</tr>
<tr>
    <th>风险批次
    </th>
    <td colspan=""5"">
    {riskInfo.RiskBatch}
    </td>
</tr>
<tr>
    <th>交货数量
    </th>
    <td >
    {riskInfo.DeliveryQty}
    </td>
    <th>库存数量
    </th>
    <td >
    {riskInfo.StockQty}
    </td>
    <th>发料数量<br>（柯洱斯）
    </th>
    <td >
    {riskInfo.KESQty}
    </td>
</tr>
<tr>

    <th>发料数量<br>（亮亮）
    </th>
    <td >
    {riskInfo.LLQty}
    </td>
    <th>发料数量<br>（惠州百富）
    </th>
    <td >
    {riskInfo.HZQty}
    </td>
    <th>发料数量<br>（CKD）
    </th>
    <td>
    {riskInfo.CKDQty}
    </td>
</tr>
<tr>
    <th>发料数量<br>（其它）
    </th>
    <td colspan=""5"">
    {riskInfo.OtherQty}
    </td>
</tr>
<tr>
    <th>备注
    </th>
    <td colspan=""5"">
    {riskInfo.Remark}
    </td>
</tr>
";
            }
            if (detail.ProblemType == 7)
            {
                var productionConfirmLog = logList.Where(x => x.Step == ZCTracking_ProblemOpeEnum.ProductionConfirm.GetEnumIntValue()).FirstOrDefault();
                if (productionConfirmLog != null)
                {
                    html += "     <tr><th colspan='6'>生产角色确认</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(productionConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{productionConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>确认结果</th>";
                    html += $"       <td colspan=\"5\" >{(productionConfirmLog.Result == "0" ? "不同意" : "同意")}</td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>备注</th>";
                    html += $"       <td colspan=\"5\" >{productionConfirmLog.Opinon.Replace("\n", "<br />")}</td>";
                    html += "     </tr>";
                }
            }
            var Stock = await zCTracking_StockService.GetStockList(detail.ID);
            var CKD = await zCTracking_CKDProductService.GetCKDProductList(detail.ID);
            var OnlineOrder = await zCTracking_OnlineOrderService.GetOnlineOrders(detail.ID);
            var OtherOrders = await zCTracking_OtherOrderService.GetOtherOrders(detail.ID);
            //IQC意见
            var iqcLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.IQCOpinion.GetEnumIntValue());
            if (iqcLog != null && detail.Status != ZCTracking_ProblemStatusEnum.IQCOpinion.GetEnumIntValue() && detail.OldProblemType.HasValue && detail.OldProblemType != detail.ProblemType)
            {
                html += "     <tr><th colspan='6'>IQC意见</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(iqcLog.AddUser.ToString())}  <span class='add-date-span'>{iqcLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>是否修改分类</th>";
                html += $"      <td colspan=>是</td>";
                html += "       <th>改前问题分类</th>";
                html += $"       <td colspan=\"3\" >{(DicConst.ProblemTypeDic.ContainsKey(detail.OldProblemType.Value) ? DicConst.ProblemTypeDic[detail.OldProblemType.Value] : "")}</td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>备注</th>";
                html += $"       <td colspan=\"5\" >{iqcLog.Opinon}</td>";
                html += "     </tr>";
            }

            var resUserLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ResponsibleUser.GetEnumIntValue());
            if (resUserLog != null)
            {
                html += "     <tr><th colspan='6'>指定责任人</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(resUserLog.AddUser.ToString())}  <span class='add-date-span'>{resUserLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>责任人</th>";
                html += $"       <td colspan=\"5\" >{await _hrEmployeeService.GetNameByIDAsync(detail.RUser)}    （{await _hrEmployeeService.GetUnitNameByUnitIdZLAsync(detail.RDepartment.Value)}）</td>";
                html += "     </tr>";
            }
            var confirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.Confirm.GetEnumIntValue());
            var rConfirm = detail.RConfirm.HasValue ? detail.RConfirm.Value : 0;
            if (confirmLog != null)
            {
                html += "     <tr><th colspan='6'>责任人确认</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(confirmLog.AddUser.ToString())}  <span class='add-date-span'>{confirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>确认结果</th>";
                html += $"      <td {(rConfirm > 0 ? "" : "colspan='5'")}>{(rConfirm > 0 ? "是" : "否")}</td>";
                if (rConfirm > 0)
                {
                    html += "       <th>处理结果</th>";
                    html += $"      <td>{(detail.DesignConfirmResult == 1 ? "改善" : detail.DesignConfirmResult == 2 ? "保持现状" : "挂起")}</td>";
                    html += "       <th>计划完成时间</th>";
                    html += $"      <td>{(detail.RCompleteTime.HasValue ? detail.RCompleteTime.Value.ToString("yyyy-MM-dd") : "")}</td>";
                }
                html += "     </tr>";
                if (rConfirm > 0)
                {
                    if (!string.IsNullOrWhiteSpace(detail.Reason))
                    {
                        html += "     <tr>";
                        html += "       <th>原因分析</th>";
                        html += $"      <td colspan=\"5\" >{detail.Reason.Replace("\n", "<br />")}</td>";
                        html += "     </tr>";
                    }
                    html += "     <tr>";
                    html += "       <th>改善措施</th>";
                    html += $"       <td colspan=\"5\" >{detail.Measures}</td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "     <tr>";
                    html += "       <th>预防对策</th>";
                    html += $"       <td colspan=\"5\" >{detail.Prevention}</td>";
                    html += "     </tr>";
                }
                else
                {
                    html += "     <tr>";
                    html += "       <th>修改的问题分类</th>";
                    html += $"       <td colspan=\"5\" >{DicConst.ProblemTypeDic[detail.ProblemType]}</td>";
                    html += "     </tr>";
                }
                html += "     <tr>";
                html += "       <th>备注</th>";
                html += $"       <td colspan=\"5\" >{confirmLog.Opinon}</td>";
                html += "     </tr>";
            }
            //物料问题
            if (detail.ProblemType == 3)
            {
                //IQC意见
                if (iqcLog != null && detail.Status != ZCTracking_ProblemStatusEnum.IQCOpinion.GetEnumIntValue())
                {
                    html += "     <tr><th colspan='6'>IQC意见</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='3' >{await _hrEmployeeService.GetNameByIDAsync(iqcLog.AddUser.ToString())}  <span class='add-date-span'>{iqcLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "       <th>是否修改分类</th>";
                    html += $"      <td colspan=>否</td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>处理意见</th>";
                    html += $"       <td colspan=\"5\" >{(detail.IQCOpinion == 2 ? "退回仓库" : detail.IQCOpinion == 3 ? "继续使用" : "")}</td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>备注</th>";
                    html += $"       <td colspan=\"5\" >{iqcLog.Opinon}</td>";
                    html += "     </tr>";
                    if (detail.IQCOpinion == 3)
                    {
                        //库存
                        if (Stock.Any())
                        {
                            html += " <tr>";
                            html += "   <th>库存和在线</th>";
                            html += $"   <td colspan=\"5\" >";
                            html += $"<div><table class=\"tableModel orderTable\">";
                            html += "  <thead>";
                            html += "    <th style=\"width: 55px; \"></th>";
                            html += "    <th style=\"width: 100px; \">仓库</th>";
                            html += "    <th style=\"width: 100px; \">数量</th>";
                            html += "    <th style=\"width: 100px; \">合计</th>";
                            html += "  </thead>";
                            html += "  <tbody>";
                            var sumStock = Stock.Sum(x => x.Qty);
                            for (int i = 0; i < Stock.Count; i++)
                            {
                                html += $"<tr>";
                                if (i == 0) { html += $"<th rowspan='{Stock.Count}'>库存</th>"; }
                                html += $"<td>{Stock[i].Warehouse}</td>   ";
                                html += $"<td>{Stock[i].Qty:N0}</td>";
                                if (i == 0) { html += $"<td rowspan='{Stock.Count}'>{sumStock:N0}</td>"; }
                                html += $"</tr>";

                            }
                            html += "  </tbody>";
                            html += "</table></div>";
                            html += "   </td>";
                            html += "</tr>";
                        }
                        if (riskInfo.RiskStreamList.Any())
                        {
                            html += @$"
<tr>
    <th>风险订单</th>
    <td colspan=""5"" >
      <table class=""tableModel orderTable""><thead>
         <th style=""width:50px"">序号</th>
         <th style=""width:75px"">工厂</th>             
         <th style=""width:75px"">订单号</th>        
         <th style="""">发料日期</th>
         <th style=""width:120px"">机型</th>
         <th style="""">订单数量</th>
         <th style="""">已入库数量</th>
         <th style="""">规划用量</th>
         <th style="""">发料数量</th>
         <th style="""">处理方式</th>
         {(riskInfo.IsPatch == 1 ? "<th style=''>是否贴片</th>" : "")}
         <th style="""">已使用数量</th>
         <th style="""">需退货数量</th>
         <th style="""">已收货数量</th>
        </thead><tbody>";
                            for (int i = 0; i < riskInfo.RiskOrderList.Count; i++)
                            {
                                var item = riskInfo.RiskOrderList[i];
                                html += $@"
         <tr>
            <td style=""text-align:center;"">{i + 1}</td>            
            <td>{item.Factory}</td>
            <td>{item.OrderNo}</td>
            <td>{item.FaliaoDate}</td>
            <td>{item.ProductName}</td>
            <td>{item.Qty:N0}</td>
            <td>{item.TotalinQty:N0}</td>
            <td>{item.IssuedQty:N0}</td>
            <td>{item.IssQty:N0}</td>
            <td>{(item.ReturnType == 1 ? "就地销毁" : item.ReturnType == 2 ? "退回仓库" : item.ReturnType == 3 ? "继续使用" : "")}</td>
            {(riskInfo.IsPatch == 1 ? $"<td>{(item.IsPatch.HasValue ? item.IsPatch.Value == 1 ? "是" : "否" : "")}</td>" : "")}
            <td>{item.RiskUsedQty:N0}</td>
            <td>{item.ReturnQty:N0}</td>
            <td>{item.ReceivingQty:N0}</td>
         </tr>";
                            }
                            html += @"</tbody></table></td></tr>";
                        }
                        else
                        {
                            //其他在线订单
                            if (OtherOrders.Any())
                            {
                                html += " <tr>";
                                html += "   <th>其他在线订单</th>";
                                html += $"   <td colspan=\"5\" >";
                                html += $"<div><table class=\"tableModel orderTable\">";
                                html += "  <thead>";
                                html += "    <th style=\"width: 55px; \">序号</th>";
                                html += "    <th style=\"width: 100px; \">工厂</th>";
                                html += "    <th style=\"width: 100px; \">订单号</th>";
                                html += "    <th style=\"width: 120px; \">物料发料日期</th>";
                                html += "    <th style=\"width: 240px; \">机型</th>"; ;
                                html += "    <th>订单数量</th>";
                                html += "    <th>已入库数量</th>";
                                html += "    <th>规划用量</th>";
                                html += "    <th>发料数量(含超领)</th>";
                                html += "  </thead>";
                                html += "  <tbody>";
                                for (int i = 0; i < OtherOrders.Count; i++)
                                {
                                    html += $"<tr><td>{i + 1}</td>";
                                    html += $"<td>{(DicConst.FactoryDic.ContainsKey(OtherOrders[i].Factory ?? "") ? DicConst.FactoryDic[OtherOrders[i].Factory] : "")}</td>";
                                    html += $"<td>{OtherOrders[i].OrderNo}</td>";
                                    html += $"<td>{(OtherOrders[i].FaliaoDate.HasValue ? OtherOrders[i].FaliaoDate.Value.ToString("yyyy-MM-dd") : "")}</td>   ";
                                    html += $"<td>{OtherOrders[i].ProductName}</td>   ";
                                    html += $"<td>{OtherOrders[i].Qty:N0}</td>   ";
                                    html += $"<td>{OtherOrders[i].TotalinQty:N0}</td>   ";
                                    html += $"<td>{OtherOrders[i].IssuedQty:N0}</td>";
                                    html += $"<td>{OtherOrders[i].IssQty:N0}</td></tr>";
                                }
                                html += "  </tbody>";
                                html += "</table></div>";
                                html += "   </td>";
                                html += "</tr>";
                            }
                        }

                        //ckd
                        if (CKD.Any())
                        {
                            html += " <tr>";
                            html += "   <th>CKD机型</th>";
                            html += $"   <td colspan=\"5\" >";
                            html += $"<div><table class=\"tableModel orderTable\">";
                            html += "  <thead>";
                            html += "    <th style=\"width: 55px; \">序号</th>";
                            html += "    <th style=\"min-width: 200px; \">PO</th>";
                            html += "    <th style=\"width: 200px; \">Invoice</th>";
                            html += "    <th style=\"width: 120px; \">发料数量</th>";
                            html += "    <th style=\"width: 120px; \">提货日期</th>"; ;
                            html += "  </thead>";
                            html += "  <tbody>";
                            for (int i = 0; i < CKD.Count; i++)
                            {
                                html += $"<tr><td>{i + 1}</td>";
                                html += $"<td>{CKD[i].PO}</td>";
                                html += $"<td>{CKD[i].Invoice}</td>";
                                html += $"<td>{CKD[i].IssuedQty:N0}</td>   ";
                                html += $"<td>{(CKD[i].PickupDate.HasValue ? CKD[i].PickupDate.Value.ToString("yyyy-MM-dd") : "")}</td>   ";
                            }
                            html += "  </tbody>";
                            html += "</table></div>";
                            html += "   </td>";
                            html += "</tr>";
                        }
                    }
                }
                //IQC确认
                var iqcConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ConfirmIQC.GetEnumIntValue());
                var factoryConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ConfirmFactory.GetEnumIntValue());
                if ((iqcConfirmLog != null || factoryConfirmLog != null) && detail.Status >= ZCTracking_ProblemStatusEnum.ConfirmIQC.GetEnumIntValue())
                {
                    var addUserHtml = "";
                    if (iqcConfirmLog != null)
                    {
                        addUserHtml += $"<div>{iqcConfirmLog.StepStr}:  {await _hrEmployeeService.GetNameByIDAsync(iqcConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{iqcConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></div>";
                    }
                    if (factoryConfirmLog != null)
                    {
                        addUserHtml += $"<div>{factoryConfirmLog.StepStr}:  {await _hrEmployeeService.GetNameByIDAsync(factoryConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{factoryConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></div>";
                    }
                    var saveOrderNoLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.SaveOrderNo.GetEnumIntValue());
                    if (saveOrderNoLog != null)
                    {
                        addUserHtml += $"<div> <span>保存退货单号：</span>{await _hrEmployeeService.GetNameByIDAsync(saveOrderNoLog.AddUser.ToString())}  <span class='add-date-span'>{saveOrderNoLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></div>";
                    }
                    var fillOrderNoLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.FillOrderNo.GetEnumIntValue());
                    if (fillOrderNoLog != null)
                    {
                        addUserHtml += $"<div> <span>确认退货单号：</span>{await _hrEmployeeService.GetNameByIDAsync(fillOrderNoLog.AddUser.ToString())}  <span class='add-date-span'>{fillOrderNoLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></div>";
                    }
                    html += "     <tr><th colspan='6'>IQC确认</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{addUserHtml}</span></td>";
                    html += "     </tr>";
                    //库存
                    if (Stock.Any() || OnlineOrder.Any())
                    {
                        html += " <tr>";
                        html += "   <th>库存和在线</th>";
                        html += $"   <td colspan=\"5\" >";
                        html += $"<div><table class=\"tableModel orderTable\">";
                        html += "  <thead>";
                        html += "    <th style=\"width: 55px; \"></th>";
                        html += "    <th style=\"width: 100px; \">仓库</th>";
                        html += "    <th style=\"width: 100px; \">数量</th>";
                        html += "    <th style=\"width: 100px; \">合计</th>";
                        html += "    <th style=\"width: 100px; \">处理方式</th>";
                        html += "    <th>需退货数量</th>";
                        html += "    <th style=\"width: 110px; \">已收货数量</th>";
                        html += "  </thead>";
                        html += "  <tbody>";
                        var sumStock = Stock.Sum(x => x.Qty);
                        var sumOnlineOrder = OnlineOrder.Sum(x => x.Qty);
                        for (int i = 0; i < Stock.Count; i++)
                        {
                            html += $"<tr>";
                            if (i == 0) { html += $"<th rowspan='{Stock.Count}'>库存</th>"; }
                            html += $"<td>{Stock[i].Warehouse}</td>   ";
                            html += $"<td>{(Stock[i].Qty.HasValue ? Stock[i].Qty.ToString("N0") : "")}</td>";
                            if (i == 0)
                            {
                                html += $"<td rowspan='{Stock.Count}'>{sumStock:N0}</td>";
                                html += $"<td rowspan='{Stock.Count}'>{(Stock[i].ReturnType == 1 ? "就地销毁" : Stock[i].ReturnType == 2 ? "退回供应商" : Stock[i].ReturnType == 3 ? "继续使用" : "")}</td>";
                                html += $"<td rowspan='{Stock.Count}'>{(Stock[i].StockReturnQty.HasValue ? Stock[i].StockReturnQty.ToString("N0") : "")}</td>";
                                html += $"<td rowspan='{Stock.Count}'>{(Stock[i].ReceivingQty.HasValue ? Stock[i].ReceivingQty.ToString("N0") : "")}</td>";
                            }
                            html += $"</tr>";
                        }
                        for (int j = 0; j < OnlineOrder.Count; j++)
                        {
                            html += $"<tr>";
                            if (j == 0) { html += $"<th rowspan='{OnlineOrder.Count}'>在线</th>"; }
                            html += $"<td>{(OnlineOrder[j].ProductionType == 1 ? "已使用" : "未使用")}</td>";
                            html += $"<td>{(OnlineOrder[j].Qty.HasValue ? OnlineOrder[j].Qty.ToString("N0") : "")}</td>";
                            if (j == 0)
                            {
                                html += $"<td rowspan='{OnlineOrder.Count}'>{sumOnlineOrder:N0}</td>";
                            }
                            html += $"<td>{(OnlineOrder[j].ReturnType == 1 ? "就地销毁" : OnlineOrder[j].ReturnType == 2 ? "退回仓库" : OnlineOrder[j].ReturnType == 3 ? "继续使用" : "")}</td>";
                            html += $"<td>{(OnlineOrder[j].OReturnQty.HasValue ? OnlineOrder[j].OReturnQty.ToString("N0") : "")}</td>";
                            html += $"<td>{(OnlineOrder[j].ReceivingQty.HasValue ? OnlineOrder[j].ReceivingQty.ToString("N0") : "")}</td>";
                            html += $"</tr>";
                        }
                        html += "  </tbody>";
                        html += "</table></div>";
                        html += "   </td>";
                        html += "</tr>";
                    }
                    if (riskInfo.RiskStreamList.Any())
                    {
                        html += @$"
<tr>
    <th>风险订单</th>
    <td colspan=""5"" >
      <table class=""tableModel orderTable""><thead>
         <th style=""width:50px"">序号</th>
         <th style=""width:75px"">工厂</th>             
         <th style=""width:75px"">订单号</th>        
         <th style="""">发料日期</th>
         <th style="""">机型</th>
         <th style="""">订单数量</th>
         <th style="""">已入库数量</th>
         <th style="""">规划用量</th>
         <th style="""">发料数量</th>
         <th style="""">处理方式</th>
         {(riskInfo.IsPatch == 1 ? "<th style='width:50px'>是否贴片</th>" : "")}
         <th style="""">已使用数量</th>
         <th style="""">需退货数量</th>
         <th style="""">已收货数量</th>
        </thead><tbody>";
                        for (int i = 0; i < riskInfo.RiskOrderList.Count; i++)
                        {
                            var item = riskInfo.RiskOrderList[i];
                            html += $@"
         <tr>
            <td style=""text-align:center;"">{i + 1}</td>            
            <td>{(DicConst.FactoryDic.ContainsKey(item.Factory) ? DicConst.FactoryDic[item.Factory] : "")}</td>
            <td>{item.OrderNo}</td>
            <td>{(item.FaliaoDate.HasValue ? item.FaliaoDate.Value.ToString("yyyy-MM-dd") : "")}</td>
            <td>{item.ProductName}</td>
            <td>{item.Qty:N0}</td>
            <td>{item.TotalinQty:N0}</td>
            <td>{item.IssuedQty:N0}</td>
            <td>{item.IssQty:N0}</td>        
            <td>{(item.ReturnType == 1 ? "就地销毁" : item.ReturnType == 2 ? "退回仓库" : item.ReturnType == 3 ? "继续使用" : "")}</td>
            {(riskInfo.IsPatch == 1 ? $"<td>{(item.IsPatch.HasValue ? item.IsPatch.Value == 1 ? "是" : "否" : "")}</td>" : "")}
            <td>{item.RiskUsedQty:N0}</td>
            <td>{item.ReturnQty:N0}</td>
            <td>{item.ReceivingQty:N0}</td>     
         </tr>";
                        }
                        html += @"</tbody></table></td></tr>";
                    }
                    else
                    {
                        //其他在线订单
                        if (OtherOrders.Any())
                        {
                            html += " <tr>";
                            html += "   <th>其他在线订单</th>";
                            html += $"   <td colspan=\"5\" >";
                            html += $"<div><table class=\"tableModel orderTable\">";
                            html += "  <thead>";
                            html += "    <th style=\"width: 55px; \">序号</th>";
                            html += "    <th style=\"width: 100px; \">工厂</th>";
                            html += "    <th style=\"width: 100px; \">订单号</th>";
                            html += "    <th style=\"width: 120px; \">物料发料日期</th>";
                            html += "    <th style=\"width: 240px; \">机型</th>"; ;
                            html += "    <th >订单数量</th>";
                            html += "    <th style=\"width: 85px; \">已入库数量</th>";
                            html += "    <th >规划用量</th>";
                            html += "    <th style=\"width: 80px; \">发料数量(含超领)</th>";
                            html += "    <th style=\"width: 80px; \">处理方式</th>";
                            html += "    <th style=\"width: 90px; \">需退货数量</th>";
                            html += "    <th style=\"width: 90px; \">已收货数量</th>";
                            html += "  </thead>";
                            html += "  <tbody>";
                            for (int i = 0; i < OtherOrders.Count; i++)
                            {
                                html += $"<tr><td>{i + 1}</td>";
                                html += $"<td>{(DicConst.FactoryDic.ContainsKey(OtherOrders[i].Factory) ? DicConst.FactoryDic[OtherOrders[i].Factory] : "")}</td>";
                                html += $"<td>{OtherOrders[i].OrderNo}</td>";
                                html += $"<td>{(OtherOrders[i].FaliaoDate.HasValue ? OtherOrders[i].FaliaoDate.Value.ToString("yyyy-MM-dd") : "")}</td>   ";
                                html += $"<td>{OtherOrders[i].ProductName}</td>   ";
                                html += $"<td>{OtherOrders[i].Qty:N0}</td>   ";
                                html += $"<td>{OtherOrders[i].TotalinQty:N0}</td>   ";
                                html += $"<td>{OtherOrders[i].IssuedQty:N0}</td>";
                                html += $"<td>{OtherOrders[i].IssQty:N0}</td>";
                                html += $"<td>{(OtherOrders[i].ReturnType == 1 ? "就地销毁" : OtherOrders[i].ReturnType == 2 ? "退回仓库" : OtherOrders[i].ReturnType == 3 ? "继续使用" : "")}</td>";
                                html += $"<td>{OtherOrders[i].ReturnQty:N0}</td>";
                                html += $"<td>{OtherOrders[i].ReceivingQty:N0}</td></tr>";
                            }
                            html += "  </tbody>";
                            html += "</table></div>";
                            html += "   </td>";
                            html += "</tr>";
                        }
                    }
                    //ckd
                    if (CKD.Any())
                    {
                        html += " <tr>";
                        html += "   <th>CKD机型</th>";
                        html += $"   <td colspan=\"5\" >";
                        html += $"<div><table class=\"tableModel orderTable\">";
                        html += "  <thead>";
                        html += "    <th style=\"width: 55px; \">序号</th>";
                        html += "    <th style=\"min-width: 200px; \">PO</th>";
                        html += "    <th style=\"width: 200px; \">Invoice</th>";
                        html += "    <th style=\"width: 120px; \">发料数量</th>";
                        html += "    <th style=\"width: 120px; \">提货日期</th>";
                        html += "    <th style=\"width: 120px; \">处理方式</th>";
                        html += "    <th style=\"width: 120px; \">需退货数量</th>";
                        html += "    <th style=\"width: 120px; \">已收货数量</th>";
                        html += "  </thead>";
                        html += "  <tbody>";
                        for (int i = 0; i < CKD.Count; i++)
                        {
                            html += $"<tr><td>{i + 1}</td>";
                            html += $"<td>{CKD[i].PO}</td>";
                            html += $"<td>{CKD[i].Invoice}</td>";
                            html += $"<td>{CKD[i].IssuedQty:N0}</td>   ";
                            html += $"<td>{(CKD[i].PickupDate.HasValue ? CKD[i].PickupDate.Value.ToString("yyyy-MM-dd") : "")}</td>   ";
                            html += $"<td>{(CKD[i].ReturnType == 1 ? "就地销毁" : CKD[i].ReturnType == 2 ? "退回仓库" : CKD[i].ReturnType == 3 ? "继续使用" : CKD[i].ReturnType == 4 ? "待SQE确认" : "")}</td>";
                            html += $"<td>{(CKD[i].ReturnQty.HasValue ? (CKD[i].ReturnQty.Value > 0 ? CKD[i].ReturnQty.ToString("N0") : "") : "")}</td>";
                            html += $"<td>{(CKD[i].ReceivingQty.HasValue ? (CKD[i].ReceivingQty.Value > 0 ? CKD[i].ReceivingQty.ToString("N0") : "") : "")}</td></tr>";
                        }
                        html += "  </tbody>";
                        html += "</table></div>";
                        html += "   </td>";
                        html += "</tr>";
                    }
                    if (!string.IsNullOrWhiteSpace(detail.OReturnOrderNo))
                    {
                        html += "     <tr>";
                        html += "       <th>在线退货单号</th>";
                        html += $"      <td colspan='5' >{detail.OReturnOrderNo}</span></td>";
                        html += "     </tr>";
                    }
                    if (!string.IsNullOrWhiteSpace(detail.SReturnOrderNo))
                    {
                        html += "     <tr>";
                        html += "       <th>在库退货单号</th>";
                        html += $"      <td colspan='5' >{detail.SReturnOrderNo}</span></td>";
                        html += "     </tr>";
                    }
                    if (saveOrderNoLog != null || fillOrderNoLog != null)
                    {
                        if (fillOrderNoLog != null)
                        {
                            html += "     <tr>";
                            html += "       <th>备注</th>";
                            html += $"      <td colspan='5' >{fillOrderNoLog.Opinon}</span></td>";
                            html += "     </tr>";
                        }
                        else
                        {
                            html += "     <tr>";
                            html += "       <th>备注</th>";
                            html += $"      <td colspan='5' >{saveOrderNoLog.Opinon}</span></td>";
                            html += "     </tr>";
                        }
                    }
                }
                var sqeLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.FollowSQE.GetEnumIntValue());
                if (sqeLog != null)
                {
                    html += "     <tr><th colspan='6'>SQE跟进</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(sqeLog.AddUser.ToString())}  <span class='add-date-span'>{sqeLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>SQE跟进结果</th>";
                    html += $"       <td colspan=\"5\" >{sqeLog.Opinon}</td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>是否设计更改</th>";
                    html += $"       <td colspan='{(sqeLog.Result == "1" ? "1" : "5")}' >{(sqeLog.Result == "1" ? "需要" : "不需要")}</td>";
                    if (sqeLog.Result == "1")
                    {
                        html += "    <th>责任人</th>";
                        html += $"   <td colspan='3'> {await _hrEmployeeService.GetNameByIDAsync(detail.DesignUser.ToString())}</td>";
                    }
                    html += "     </tr>";
                }
                var disignLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.DesignChange.GetEnumIntValue());
                if (disignLog != null)
                {
                    html += "     <tr><th colspan='6'>设计更改</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(disignLog.AddUser.ToString())}  <span class='add-date-span'>{disignLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "        <th>确认结果</th>";
                    html += $"       <td {(detail.DesignConfirmResult != 1 ? "colspan='5'" : "")}>{(detail.DesignConfirmResult == 1 ? "改善" : detail.DesignConfirmResult == 2 ? "保持现状" : "挂起")}</td>";
                    if (detail.DesignConfirmResult == 1)
                    {
                        html += "    <th>预计完成时间</th>";
                        html += $"   <td colspan='3'> {(detail.DesignDate.HasValue ? detail.DesignDate.Value.ToString("yyyy-MM-dd") : "")}</td>";
                    }
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>原因说明</th>";
                    html += $"       <td colspan=\"5\" >{disignLog.Opinon}</td>";
                    html += "     </tr>";
                }
                var sqeConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ChangeConfirmSQE.GetEnumIntValue());
                if (sqeConfirmLog != null)
                {
                    html += "     <tr><th colspan='6'>SQE确认</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(sqeConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{sqeConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>SQE意见</th>";
                    html += $"       <td colspan=\"5\" >{sqeConfirmLog.Opinon}</td>";
                    html += "     </tr>";
                }
            }

            if (detail.ProblemType == 4)
            {
                var confirmVersionLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ConfirmVersion.GetEnumIntValue());
                var zlConfirm = detail.ZLConfirmResult.HasValue ? detail.ZLConfirmResult.Value : 0;
                if (confirmVersionLog != null)
                {
                    html += "     <tr><th colspan='6'>工程确认</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(confirmVersionLog.AddUser.ToString())}  <span class='add-date-span'>{confirmVersionLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>确认结果</th>";
                    html += $"       <td colspan=\"5\" >{(zlConfirm > 0 ? "是" : "否")}</td>";
                    html += "     </tr>";
                    if (zlConfirm > 0)
                    {
                        html += "    <tr><th>处理结果</th>";
                        html += $"      <td colspan=\"5\">{(detail.DesignConfirmResult == 1 ? "改善" : detail.DesignConfirmResult == 2 ? "保持现状" : "挂起")}</td></tr>";
                        html += "    <tr><th>计划完成时间</th>";
                        html += $"      <td colspan=\"5\">{(detail.RCompleteTime.HasValue ? detail.RCompleteTime.Value.ToString("yyyy-MM-dd") : "")}</td></tr>";
                        html += "     <tr>";
                        html += "       <th>是否更改版本</th>";
                        html += $"       <td colspan=\"5\" >{(detail.IsChangeOrderV == 1 ? "是" : "否")}  {detail.OrderVersion}</td>";
                        html += "     </tr>";
                        if (!string.IsNullOrWhiteSpace(detail.Reason))
                        {
                            html += "     <tr>";
                            html += "       <th>原因分析</th>";
                            html += $"      <td colspan=\"5\" >{detail.Reason.Replace("\n", "<br />")}</td>";
                            html += "     </tr>";
                        }
                        html += "     <tr>";
                        html += "       <th>改善措施</th>";
                        html += $"       <td colspan=\"5\" >{detail.Measures}</td>";
                        html += "     </tr>";
                        html += "     <tr>";
                        html += "     <tr>";
                        html += "       <th>预防对策</th>";
                        html += $"       <td colspan=\"5\" >{detail.Prevention}</td>";
                        html += "     </tr>";
                    }
                    else
                    {
                        html += "     <tr>";
                        html += "       <th>修改的问题分类</th>";
                        html += $"       <td colspan=\"5\" >{DicConst.ProblemTypeDic[detail.ProblemType]}</td>";
                        html += "     </tr>";
                    }
                    if (!string.IsNullOrWhiteSpace(confirmVersionLog.Opinon))
                    {
                        html += "     <tr>";
                        html += "       <th>备注</th>";
                        html += $"       <td colspan=\"5\" >{confirmVersionLog.Opinon}</td>";
                        html += "     </tr>";
                    }
                }
                var changeVersionLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ChangeVersion.GetEnumIntValue());
                if (changeVersionLog != null)
                {
                    html += "     <tr><th colspan='6'>PMC确认</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(changeVersionLog.AddUser.ToString())}  <span class='add-date-span'>{changeVersionLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>备注</th>";
                    html += $"       <td colspan=\"5\" >{changeVersionLog.Opinon}</td>";
                    html += "     </tr>";
                }
            }

            if (detail.ProblemType == 5)
            {
                var factoryAnalysisLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.FactoryAnalysis.GetEnumIntValue());
                if (factoryAnalysisLog != null)
                {
                    html += "     <tr><th colspan='6'>工厂制程分析</th></tr>";
                    html += "     <tr>";
                    html += "       <th>处理人</th>";
                    html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(factoryAnalysisLog.AddUser.ToString())}  <span class='add-date-span'>{factoryAnalysisLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>原因分析</th>";
                    html += $"       <td colspan=\"5\" >{factoryAnalysisLog.Result}</td>";
                    html += "     </tr>";
                    html += "     <tr>";
                    html += "       <th>制定对策</th>";
                    html += $"       <td colspan=\"5\" >{factoryAnalysisLog.Opinon}</td>";
                    html += "     </tr>";
                }
            }

            var preventionConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.PreventionConfirm.GetEnumIntValue());
            if (preventionConfirmLog != null)
            {
                html += "     <tr><th colspan='6'>预防对策确认</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(preventionConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{preventionConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>预防对策确认</th>";
                html += $"       <td colspan=\"5\" >{preventionConfirmLog.Opinon}</td>";
                html += "     </tr>";
            }

            var effectConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.EffectConfirm.GetEnumIntValue());
            if (effectConfirmLog != null)
            {
                html += "     <tr><th colspan='6'>效果确认</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(effectConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{effectConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>效果确认结果</th>";
                html += $"       <td colspan=\"5\" >{effectConfirmLog.Opinon}</td>";
                html += "     </tr>";
            }

            var closingConfirmLog = logList.FirstOrDefault(x => x.Step == ZCTracking_ProblemOpeEnum.ClosingConfirm.GetEnumIntValue());
            if (closingConfirmLog != null)
            {
                html += "     <tr><th colspan='6'>结案确认</th></tr>";
                html += "     <tr>";
                html += "       <th>处理人</th>";
                html += $"      <td colspan='5' >{await _hrEmployeeService.GetNameByIDAsync(closingConfirmLog.AddUser.ToString())}  <span class='add-date-span'>{closingConfirmLog.AddDate.ToString("yyyy-MM-dd HH:mm:ss")}</span></td>";
                html += "     </tr>";
                html += "     <tr>";
                html += "       <th>结案结论</th>";
                html += $"       <td colspan=\"5\" >{closingConfirmLog.Opinon}</td>";
                html += "     </tr>";
            }
            html += "   </table>";
            html += " </div>";
            html += "</body></html>";
            return html;
        }
        #endregion

        #region 风险黑名单管理
        /// <summary>
        /// 获取风险批次黑名单分页列表
        /// </summary>
        /// <param name="dto">查询条件，含分页、排序、物料编号/批次信息/制程单号筛选</param>
        /// <returns>分页后的黑名单数据，含总记录数</returns>
        public async Task<PageModel<RiskBlacklistListDto>> GetRiskBlacklistPage(RiskBlacklistQueryDto dto)
        {
            // 使用参数化查询动态拼接 WHERE 条件，防止 SQL 注入
            var parameters = new Dapper.DynamicParameters();
            var where = " WHERE 1=1";
            if (!string.IsNullOrWhiteSpace(dto.CInvCode))
            {
                where += " AND bl.CInvCode LIKE @CInvCode";
                parameters.Add("CInvCode", $"%{dto.CInvCode}%");
            }
            if (!string.IsNullOrWhiteSpace(dto.BatchInfo))
            {
                where += " AND bl.BatchInfo LIKE @BatchInfo";
                parameters.Add("BatchInfo", $"%{dto.BatchInfo}%");
            }
            if (!string.IsNullOrWhiteSpace(dto.Numbers))
            {
                where += " AND bl.Numbers = @Numbers";
                parameters.Add("Numbers", dto.Numbers);
            }

            // 校正非法页码，计算分页偏移量
            var pageIndex = dto.Page < 1 ? 1 : dto.Page;
            var pageSize = dto.PageSize < 1 ? 20 : dto.PageSize;
            var skip = (pageIndex - 1) * pageSize;
            parameters.Add("skip", skip);
            parameters.Add("pageSize", pageSize);
            // 前端传入 OrderBy 则使用指定列排序，否则默认 ID 倒序（最新记录在前）
            var orderClause = !string.IsNullOrWhiteSpace(dto.OrderBy) ? $"{dto.OrderBy} {dto.Sort}" : "ID DESC";

            var sql = $@"
SELECT bl.ID, bl.ProblemId, bl.Numbers, bl.CInvCode, i.CInvName,
       bl.BatchType,
       CASE bl.BatchType WHEN 1 THEN '供应商批次' WHEN 2 THEN 'IQC批次号' WHEN 3 THEN '检验单号' ELSE '' END AS BatchTypeStr,
       bl.BatchInfo, bl.RiskStatus, bl.CancelReason,
       e.Name AS OperateUserName, bl.OperateDate
INTO #temp_bl
FROM dbo.ZCTracking_RiskBlacklist bl WITH(NOLOCK)
LEFT JOIN info.dbo.Employee e WITH(NOLOCK) ON e.ID = bl.OperateUser
LEFT JOIN info.dbo.Inventory i WITH(NOLOCK) ON i.cInvCode=bl.CInvCode
{where}

SELECT * FROM #temp_bl ORDER BY {orderClause} OFFSET @skip ROWS FETCH NEXT @pageSize ROWS ONLY
SELECT COUNT(*) FROM #temp_bl

DROP TABLE #temp_bl";

            return await dapperHelperCoreInfo.QueryMultipleAsync<RiskBlacklistListDto>(sql, parameters);
        }

        /// <summary>
        /// 批量取消风险批次黑名单，将风险状态从"风险中（1）"改为"已取消（0）"
        /// </summary>
        /// <param name="dto">包含要取消的ID列表（单次不超过200条）及取消原因</param>
        /// <returns>操作结果</returns>
        public async Task<WebResponseContent> CancelRiskBlacklist(CancelRiskBlacklistDto dto)
        {
            // 参数校验：ID 列表不能为空
            if (dto.Ids == null || dto.Ids.Count == 0)
            {
                return WebResponseContent.Error_obj("请选择要取消的记录！");
            }
            // 防止大批量操作造成性能问题，单次限制200条
            if (dto.Ids.Count > 200)
            {
                return WebResponseContent.Error_obj("单次最多取消 200 条记录！");
            }
            // 取消原因必填，确保操作可追溯（审计要求）
            if (string.IsNullOrWhiteSpace(dto.CancelReason))
            {
                return WebResponseContent.Error_obj("取消原因不能为空！");
            }

            var blacklistDb = repository.DbContext.Set<ZCTracking_RiskBlacklist>();
            // 仅查询 RiskStatus=1（风险中）的记录，已取消的自动跳过（幂等保护）
            var records = await blacklistDb.Where(x => dto.Ids.Contains(x.ID) && x.RiskStatus == 1).ToListAsync();
            if (records.Count == 0)
            {
                return WebResponseContent.Error_obj("未找到可取消的记录！");
            }

            // 批量更新状态，同步记录操作人和操作时间，用于审计追溯
            var now = DateTime.Now;
            var userId = UserContext.Current.UserId;
            foreach (var item in records)
            {
                item.RiskStatus = 0;
                item.CancelReason = dto.CancelReason;
                item.OperateUser = userId;
                item.OperateDate = now;
            }
            blacklistDb.UpdateRange(records);
            await repository.SaveChangesAsync();
            return WebResponseContent.Instance.OK("取消成功");
        }

        /// <summary>
        /// 获取风险库存批次黑名单分页列表（用于库存误判放行场景）
        /// </summary>
        /// <param name="dto">查询条件，含分页、排序、物料编号/检验单号/供应商批次筛选</param>
        /// <returns>分页后的库存黑名单数据，含料盘信息及风险状态</returns>
        public async Task<PageModel<RiskStockBlacklistListDto>> GetRiskStockBlacklistPage(RiskStockBlacklistQueryDto dto)
        {
            // 使用参数化查询动态拼接 WHERE 条件，防止 SQL 注入
            var parameters = new Dapper.DynamicParameters();
            var where = " WHERE 1=1";
            if (!string.IsNullOrWhiteSpace(dto.CInvCode))
            {
                where += " AND sb.CInvCode LIKE @CInvCode";
                parameters.Add("CInvCode", $"%{dto.CInvCode}%");
            }
            if (!string.IsNullOrWhiteSpace(dto.InspectNo))
            {
                where += " AND sb.InspectNo LIKE @InspectNo";
                parameters.Add("InspectNo", $"%{dto.InspectNo}%");
            }
            if (!string.IsNullOrWhiteSpace(dto.VenBatch))
            {
                where += " AND sb.VenBatch LIKE @VenBatch";
                parameters.Add("VenBatch", $"%{dto.VenBatch}%");
            }
            if (dto.ArrivalDateStart.HasValue)
            {
                where += " AND sb.ArrivalDate >= @ArrivalDateStart";
                parameters.Add("ArrivalDateStart", dto.ArrivalDateStart.Value.Date);
            }
            if (dto.ArrivalDateEnd.HasValue)
            {
                where += " AND sb.ArrivalDate < @ArrivalDateEnd";
                parameters.Add("ArrivalDateEnd", dto.ArrivalDateEnd.Value.Date.AddDays(1));
            }
            if (!string.IsNullOrWhiteSpace(dto.TrayId))
            {
                where += " AND sb.TrayId = @TrayId";
                parameters.Add("TrayId", dto.TrayId.Trim());
            }
            if (!string.IsNullOrWhiteSpace(dto.TrayNo))
            {
                where += " AND sb.TrayNo = @TrayNo";
                parameters.Add("TrayNo", dto.TrayNo.Trim());
            }

            // 校正非法页码，计算分页偏移量
            var pageIndex = dto.Page < 1 ? 1 : dto.Page;
            var pageSize = dto.PageSize < 1 ? 20 : dto.PageSize;
            var skip = (pageIndex - 1) * pageSize;
            parameters.Add("skip", skip);
            parameters.Add("pageSize", pageSize);
            // 前端传入 OrderBy 则使用指定列排序，否则默认 ID 倒序（最新记录在前）
            var orderClause = !string.IsNullOrWhiteSpace(dto.OrderBy) ? $"{dto.OrderBy} {dto.Sort}" : "ID DESC";

            var sql = $@"
SELECT sb.ID, sb.CInvCode, sb.InspectNo, sb.ArrivalDate,
       sb.TrayId, sb.TrayNo, sb.TrayQty, sb.OldTrayId, sb.VenBatch,
       sb.RiskStatus, sb.CancelReason,
       e.Name AS OperateUserName, sb.OperateDate
INTO #temp_sb
FROM dbo.ZCTracking_RiskStockBlacklist sb WITH(NOLOCK)
LEFT JOIN info.dbo.Employee e WITH(NOLOCK) ON e.ID = sb.OperateUser
{where}

SELECT * FROM #temp_sb ORDER BY {orderClause} OFFSET @skip ROWS FETCH NEXT @pageSize ROWS ONLY
SELECT COUNT(*) FROM #temp_sb

DROP TABLE #temp_sb";

            return await dapperHelperCoreInfo.QueryMultipleAsync<RiskStockBlacklistListDto>(sql, parameters);
        }

        /// <summary>
        /// 批量取消库存风险锁定，解除误判库存物料的锁定状态
        /// </summary>
        /// <param name="dto">包含要取消的记录ID列表及取消原因</param>
        /// <returns>操作结果</returns>
        public async Task<WebResponseContent> CancelRiskStock(CancelRiskStockDto dto)
        {
            if (dto.Ids == null || dto.Ids.Count == 0)
            {
                return WebResponseContent.Error_obj("请至少选择一条记录！");
            }
            if (string.IsNullOrWhiteSpace(dto.CancelReason))
            {
                return WebResponseContent.Error_obj("取消原因不能为空！");
            }

            var stockBlacklistDb = repository.DbContext.Set<ZCTracking_RiskStockBlacklist>();
            var records = await stockBlacklistDb
                .Where(x => dto.Ids.Contains(x.ID) && x.RiskStatus == 1)
                .ToListAsync();

            if (records.Count == 0)
            {
                return WebResponseContent.Error_obj("未找到可取消的记录，或记录均已被取消！");
            }

            var now = DateTime.Now;
            var userId = UserContext.Current.UserId;
            foreach (var record in records)
            {
                record.RiskStatus = 0;
                record.CancelReason = dto.CancelReason;
                record.OperateUser = userId;
                record.OperateDate = now;
            }
            stockBlacklistDb.UpdateRange(records);
            await repository.SaveChangesAsync();
            return WebResponseContent.Instance.OK(records.Count == 1 ? "取消成功" : $"成功取消 {records.Count} 条记录");
        }
        #endregion

        #region 5Why分析报告
        /// <summary>
        /// 5Why 待办类型常量
        /// </summary>
        private const string zcFiveWhyAnswerTask = "ZCFiveWhyAnswer";

        /// <summary>
        /// 获取制程问题单 5Why 列表（按提问时间升序）
        /// </summary>
        public async Task<List<ZCTrackingFiveWhyDto>> GetFiveWhyListByProblemId(int problemId)
        {
            var db = repository.DbContext.Set<ZCTracking_ProblemFiveWhy>();
            var rows = await db.AsNoTracking()
                .Where(x => x.ProblemId == problemId)
                .OrderBy(x => x.AddDate)
                .ThenBy(x => x.ID)
                .ToListAsync();
            var pendingRowIds = rows.Where(x => x.Status == 0).Select(x => x.ID).ToList();
            var reasonActorMap = await GetZCFiveWhyReasonActorUserMap(pendingRowIds);
            var list = new List<ZCTrackingFiveWhyDto>();
            foreach (var r in rows)
            {
                reasonActorMap.TryGetValue(r.ID, out var reasonActorUser);
                list.Add(new ZCTrackingFiveWhyDto
                {
                    ID = r.ID,
                    ProblemId = r.ProblemId,
                    Question = r.Question,
                    QuestionUser = r.AddUser,
                    QuestionUserName = await _hrEmployeeService.GetNameByIDAsync(r.AddUser.ToString()),
                    QuestionDate = r.AddDate,
                    Reason = r.Reason,
                    ReasonUser = r.UpdateUser,
                    ReasonUserName = r.UpdateUser.HasValue
                        ? await _hrEmployeeService.GetNameByIDAsync(r.UpdateUser.Value.ToString())
                        : "",
                    ReasonDate = r.UpdateDate,
                    Status = r.Status,
                    ReasonActorUser = r.Status == 0 && reasonActorUser > 0 ? reasonActorUser : (int?)null,
                });
            }
            return list;
        }

        /// <summary>
        /// 校验制程问题单是否可进行 5Why 编辑；失败返回错误文案，成功返回 null
        /// </summary>
        private static string ValidateZCFiveWhyEditable(ZCTracking_ProblemList main)
        {
            if (main == null)
                return "单据不存在";
            if (main.Status == 32)
                return "已结案单据不可操作5Why分析";
            return null;
        }

        /// <summary>
        /// 批量获取制程 5Why 待办责任人（frecID 为 5Why 行 ID）
        /// </summary>
        private async Task<Dictionary<int, int>> GetZCFiveWhyReasonActorUserMap(IEnumerable<int> rowIds)
        {
            var ids = rowIds?.Where(x => x > 0).Distinct().ToList() ?? new List<int>();
            var map = new Dictionary<int, int>();
            if (!ids.Any())
                return map;

            var sql = $@"select frecID, fuserID from INFO.dbo.tbTask
                where ftable='{zcFiveWhyAnswerTask}' and fstat=N'已接受'
                and frecID in ({string.Join(",", ids)})";
            var taskRows = await dapperHelperInfo.QueryAsync<dynamic>(sql);
            foreach (var taskRow in taskRows)
            {
                if (taskRow == null)
                    continue;
                if (!int.TryParse(taskRow.frecID?.ToString(), out int rowId) || rowId <= 0)
                    continue;
                if (!int.TryParse(taskRow.fuserID?.ToString(), out int userId) || userId <= 0)
                    continue;
                map[rowId] = userId;
            }
            return map;
        }

        /// <summary>
        /// 校验当前用户是否为该 5Why 行的原因填写责任人
        /// </summary>
        private async Task<string> ValidateZCFiveWhyReasonActor(int fiveWhyRowId, int userId)
        {
            if (UserContext.Current.IsSuperAdmin)
                return null;
            if (!await _pubTaskService.IsExistTask(zcFiveWhyAnswerTask, fiveWhyRowId, userId))
                return "仅责任人可填写原因";
            return null;
        }

        /// <summary>
        /// 5Why 邮件表格行
        /// </summary>
        private class ZCFiveWhyMailTableItem
        {
            public int SeqNo { get; set; }
            public string ActionType { get; set; }
            public string Question { get; set; }
            public string Reason { get; set; }
            public int QuestionUserID { get; set; }
        }

        private static string EncodeZCFiveWhyMailText(string text)
        {
            if (string.IsNullOrEmpty(text))
                return "";
            return WebUtility.HtmlEncode(text).Replace("\r\n", "<br/>").Replace("\n", "<br/>");
        }

        private static string FormatZCFiveWhyLogText(string text)
        {
            return string.IsNullOrWhiteSpace(text) ? "（空）" : text.Trim();
        }

        /// <summary>
        /// 构建 5Why 问题邮件表格（序号、类型、问题）
        /// </summary>
        private static string BuildZCFiveWhyQuestionMailTableHtml(List<ZCFiveWhyMailTableItem> items)
        {
            if (items == null || !items.Any())
                return "";

            var sb = new StringBuilder();
            sb.Append(@"<table width='90%' border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse;border-color:#e4e7ed;margin:8px 0;'>");
            sb.Append(@"<tr style='background-color:#d9e1f2;font-weight:bold;text-align:center;'>");
            sb.Append(@"<td width='10%'>序号</td><td width='12%'>类型</td><td>问题</td></tr>");
            foreach (var item in items.OrderBy(x => x.SeqNo))
            {
                sb.Append("<tr>");
                sb.AppendFormat("<td style='text-align:center;'>{0}</td>", item.SeqNo);
                sb.AppendFormat("<td style='text-align:center;'>{0}</td>", EncodeZCFiveWhyMailText(item.ActionType));
                sb.AppendFormat("<td style='text-align:left;vertical-align:top;'>{0}</td>", EncodeZCFiveWhyMailText(item.Question));
                sb.Append("</tr>");
            }
            sb.Append("</table>");
            return sb.ToString();
        }

        /// <summary>
        /// 构建 5Why 原因邮件表格（序号、类型、问题、原因）
        /// </summary>
        private static string BuildZCFiveWhyReasonMailTableHtml(List<ZCFiveWhyMailTableItem> items)
        {
            if (items == null || !items.Any())
                return "";

            var sb = new StringBuilder();
            sb.Append(@"<table width='90%' border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse;border-color:#e4e7ed;margin:8px 0;'>");
            sb.Append(@"<tr style='background-color:#d9e1f2;font-weight:bold;text-align:center;'>");
            sb.Append(@"<td width='8%'>序号</td><td width='10%'>类型</td><td width='36%'>问题</td><td>原因</td></tr>");
            foreach (var item in items.OrderBy(x => x.SeqNo))
            {
                sb.Append("<tr>");
                sb.AppendFormat("<td style='text-align:center;'>{0}</td>", item.SeqNo);
                sb.AppendFormat("<td style='text-align:center;'>{0}</td>", EncodeZCFiveWhyMailText(item.ActionType));
                sb.AppendFormat("<td style='text-align:left;vertical-align:top;'>{0}</td>", EncodeZCFiveWhyMailText(item.Question));
                sb.AppendFormat("<td style='text-align:left;vertical-align:top;'>{0}</td>", EncodeZCFiveWhyMailText(item.Reason));
                sb.Append("</tr>");
            }
            sb.Append("</table>");
            return sb.ToString();
        }

        /// <summary>
        /// 发送制程 5Why 通知邮件（含详情页链接）
        /// </summary>
        private void SendZCFiveWhyMail(int problemId, string mailTo, string mailCc, string mailSubject, string content)
        {
            if (string.IsNullOrWhiteSpace(mailTo))
                return;

            var sendMail = UserContext.Current.UserInfo.Email;
            var sendName = UserContext.Current.UserName;
            var link = $"{FreqUsedConst.webSite}/QualityManage/ProblemDetail?id={problemId}";
            var mailBody = @"<html><body style=""font-family:Verdana,Arial,sans-serif;font-size:14px;line-height:1.5;"">"
                + content
                + $@"<p style=""margin-top:16px;""><a target=""_blank"" href=""{link}"">点击进入制程问题浏览页面</a></p></body></html>";
            Mail.SendMailSMTPBeltGog(sendMail, sendName, mailTo, mailCc ?? "", "", mailSubject, mailBody, "2423", "制程问题追踪", problemId.ToString(), null);
        }

        /// <summary>
        /// 提交 5Why 问题：记录提问人/时间，向对应步骤责任人派发 3 日待办并邮件通知
        /// </summary>
        public async Task<WebResponseContent> SaveFiveWhyQuestion(SaveZCFiveWhyQuestionModel model)
        {
            if (model == null || model.ProblemId <= 0)
                return WebResponseContent.Error_obj("参数无效");
            if (string.IsNullOrWhiteSpace(model.Question))
                return WebResponseContent.Error_obj("请填写问题");

            var main = await GetProblemInfo(model.ProblemId);
            var validateMsg = ValidateZCFiveWhyEditable(main);
            if (validateMsg != null)
                return WebResponseContent.Error_obj(validateMsg);

            var db = repository.DbContext.Set<ZCTracking_ProblemFiveWhy>();
            var userId = UserContext.Current.UserId;
            var now = DateTime.Now;
            ZCTracking_ProblemFiveWhy row;

            if (model.ID > 0)
            {
                row = await db.FirstOrDefaultAsync(x => x.ID == model.ID && x.ProblemId == model.ProblemId);
                if (row == null)
                    return WebResponseContent.Error_obj("记录不存在");
                if (row.Status != 0 || !string.IsNullOrWhiteSpace(row.Question))
                    return WebResponseContent.Error_obj("该问题已提交，不可重复修改");
            }
            else
            {
                row = new ZCTracking_ProblemFiveWhy
                {
                    ProblemId = model.ProblemId,
                    AddUser = userId,
                    AddDate = now,
                    Status = 0,
                };
                await db.AddAsync(row);
            }

            row.Question = model.Question.Trim();

            if (await repository.SaveChangesAsync() <= 0)
                return WebResponseContent.Error_obj("保存失败");

            // 根据前端传入的 StepLogId 确定该步骤的处理人作为待办/邮件接收人
            if (model.StepLogId > 0)
            {
                var stepLogDb = repository.DbContext.Set<ZCTracking_ProblemSteplog>();
                var stepLog = await stepLogDb.AsNoTracking().FirstOrDefaultAsync(x => x.ID == model.StepLogId);
                if (stepLog != null && stepLog.AddUser > 0)
                {
                    var orderNumber = main.Numbers ?? string.Empty;
                    var title = $"制程问题单【{orderNumber}】5Why待答复，请于3日内填写原因";
                    var deadline = now.AddDays(3);
                    await _pubTaskService.AddTaskAsync(zcFiveWhyAnswerTask, row.ID, title, stepLog.AddUser, now, deadline,"",model.ProblemId.ToString());

                    var toEmail = await _hrEmployeeService.GetEmailFromIDAsync(stepLog.AddUser.ToString());
                    var questionUserName = await _hrEmployeeService.GetNameByIDAsync(userId.ToString());
                    var allQuestions = await db.AsNoTracking()
                        .Where(x => x.ProblemId == model.ProblemId && !string.IsNullOrWhiteSpace(x.Question))
                        .OrderBy(x => x.AddDate)
                        .ThenBy(x => x.ID)
                        .ToListAsync();
                    var seqNo = allQuestions.FindIndex(x => x.ID == row.ID) + 1;
                    if (seqNo <= 0)
                        seqNo = allQuestions.Count;

                    var questionMailRows = new List<ZCFiveWhyMailTableItem>
                    {
                        new ZCFiveWhyMailTableItem
                        {
                            SeqNo = seqNo,
                            ActionType = "新增",
                            Question = FormatZCFiveWhyLogText(row.Question)
                        }
                    };
                    var mailSubject = $"制程问题单【{orderNumber}】5Why已提交问题";
                    var mailIntro = "<p>您好，" + EncodeZCFiveWhyMailText(orderNumber) + " 的5Why问题已由 "
                        + EncodeZCFiveWhyMailText(questionUserName) + " 提交，请您在3个工作日内填写原因。</p>";
                    var questionTableHtml = BuildZCFiveWhyQuestionMailTableHtml(questionMailRows);
                    var mailContent = mailIntro + "<p><b>本次新增/修改的5Why问题：</b></p>" + questionTableHtml;
                    var ccEmail = UserContext.Current.UserInfo.Email;
                    SendZCFiveWhyMail(model.ProblemId, toEmail, ccEmail, mailSubject, mailContent);
                }
            }

            return WebResponseContent.OK_obj();
        }

        /// <summary>
        /// 提交 5Why 原因：记录答复人/时间，办结待办并邮件通知提问人
        /// </summary>
        public async Task<WebResponseContent> SaveFiveWhyReason(SaveZCFiveWhyReasonModel model)
        {
            if (model == null || model.ID <= 0)
                return WebResponseContent.Error_obj("参数无效");
            if (string.IsNullOrWhiteSpace(model.Reason))
                return WebResponseContent.Error_obj("请填写原因");

            var db = repository.DbContext.Set<ZCTracking_ProblemFiveWhy>();
            var row = await db.FirstOrDefaultAsync(x => x.ID == model.ID);
            if (row == null)
                return WebResponseContent.Error_obj("记录不存在");
            // Status：0待答复（责任人首次填写）；1已答复（仅原因填写人可改）
            if (row.Status != 0 && row.Status != 1)
                return WebResponseContent.Error_obj("该问题状态不可操作原因");

            var main = await GetProblemInfo(row.ProblemId);
            var validateMsg = ValidateZCFiveWhyEditable(main);
            if (validateMsg != null)
                return WebResponseContent.Error_obj(validateMsg);

            var userId = UserContext.Current.UserId;
            var newReason = model.Reason.Trim();
            var isUpdate = row.Status == 1;
            if (isUpdate)
            {
                if (!UserContext.Current.IsSuperAdmin && (!row.UpdateUser.HasValue || row.UpdateUser.Value != userId))
                    return WebResponseContent.Error_obj("仅原因填写人可修改该5Why原因");
                if (string.Equals((row.Reason ?? "").Trim(), newReason, StringComparison.Ordinal))
                    return WebResponseContent.Error_obj("原因未发生变化");
            }
            else
            {
                var reasonActorMsg = await ValidateZCFiveWhyReasonActor(row.ID, userId);
                if (reasonActorMsg != null)
                    return WebResponseContent.Error_obj(reasonActorMsg);
            }

            var oldReason = row.Reason;
            var now = DateTime.Now;
            row.Reason = newReason;
            row.Status = 1;
            row.UpdateUser = userId;
            row.UpdateDate = now;
            repository.Update(row);
            if (await repository.SaveChangesAsync() <= 0)
                return WebResponseContent.Error_obj("保存失败");

            // 仅首次填写办结待办；修改已答复原因时待办已办结，不再重复 Finish
            if (!isUpdate)
                await _pubTaskService.FinishTaskAsync(zcFiveWhyAnswerTask, row.ID);

            // 邮件通知提问人（答复人与提问人是否为同一人均发送）
            var toEmail = await _hrEmployeeService.GetEmailFromIDAsync(row.AddUser.ToString());
            if (!string.IsNullOrWhiteSpace(toEmail))
            {
                var orderNumber = main.Numbers ?? string.Empty;
                var reasonUserName = await _hrEmployeeService.GetNameByIDAsync(userId.ToString());
                var allQuestions = await db.AsNoTracking()
                    .Where(x => x.ProblemId == row.ProblemId && !string.IsNullOrWhiteSpace(x.Question))
                    .OrderBy(x => x.AddDate)
                    .ThenBy(x => x.ID)
                    .ToListAsync();
                var seqNo = allQuestions.FindIndex(x => x.ID == row.ID) + 1;
                if (seqNo <= 0)
                    seqNo = allQuestions.Count;

                var reasonMailRows = new List<ZCFiveWhyMailTableItem>
                {
                    new ZCFiveWhyMailTableItem
                    {
                        SeqNo = seqNo,
                        ActionType = isUpdate ? "修改" : "填写",
                        Question = row.Question ?? "",
                        Reason = isUpdate
                            ? "原因【" + FormatZCFiveWhyLogText(oldReason) + "】修改为【" + FormatZCFiveWhyLogText(newReason) + "】。"
                            : FormatZCFiveWhyLogText(row.Reason)
                    }
                };
                var mailSubject = $"制程问题单【{orderNumber}】5Why已填写原因";
                var reasonTableHtml = BuildZCFiveWhyReasonMailTableHtml(reasonMailRows);
                var mailContent = "<p>您好，" + EncodeZCFiveWhyMailText(orderNumber) + " 的5Why原因已由 "
                    + EncodeZCFiveWhyMailText(reasonUserName) + " 提交，详情如下。</p>"
                    + "<p><b>本次填写/修改的5Why原因（您提交的问题）：</b></p>" + reasonTableHtml;
                var ccEmail = UserContext.Current.UserInfo.Email;
                var problemId = model.ProblemId > 0 ? model.ProblemId : row.ProblemId;
                SendZCFiveWhyMail(problemId, toEmail, ccEmail, mailSubject, mailContent);
            }

            return WebResponseContent.OK_obj(isUpdate ? "原因已修改" : "原因已提交");
        }

        /// <summary>
        /// 批量提交 5Why 问题：一次保存多条草稿问题，合并发送一封通知邮件
        /// </summary>
        public async Task<WebResponseContent> SaveFiveWhyQuestionsBatch(SaveZCFiveWhyQuestionsBatchModel model)
        {
            if (model == null || model.ProblemId <= 0)
                return WebResponseContent.Error_obj("参数无效");
            var submitItems = (model.Items ?? new List<SaveZCFiveWhyQuestionBatchItemModel>())
                .Where(x => x != null && !string.IsNullOrWhiteSpace(x.Question))
                .Select(x => new SaveZCFiveWhyQuestionBatchItemModel { ID = x.ID, Question = x.Question.Trim() })
                .ToList();
            if (!submitItems.Any())
                return WebResponseContent.Error_obj("请至少填写一条问题");

            var main = await GetProblemInfo(model.ProblemId);
            var validateMsg = ValidateZCFiveWhyEditable(main);
            if (validateMsg != null)
                return WebResponseContent.Error_obj(validateMsg);

            var db = repository.DbContext.Set<ZCTracking_ProblemFiveWhy>();
            var userId = UserContext.Current.UserId;
            var now = DateTime.Now;
            var newRows = new List<ZCTracking_ProblemFiveWhy>();

            foreach (var item in submitItems)
            {
                ZCTracking_ProblemFiveWhy row;
                if (item.ID > 0)
                {
                    row = await db.FirstOrDefaultAsync(x => x.ID == item.ID && x.ProblemId == model.ProblemId);
                    if (row == null)
                        return WebResponseContent.Error_obj("记录不存在");
                    if (row.Status != 0 || !string.IsNullOrWhiteSpace(row.Question))
                        return WebResponseContent.Error_obj("该问题已提交，不可重复修改");
                    row.Question = item.Question;
                }
                else
                {
                    row = new ZCTracking_ProblemFiveWhy
                    {
                        ProblemId = model.ProblemId,
                        Question = item.Question,
                        AddUser = userId,
                        AddDate = now,
                        Status = 0,
                    };
                    await db.AddAsync(row);
                }
                newRows.Add(row);
            }

            if (await repository.SaveChangesAsync() <= 0)
                return WebResponseContent.Error_obj("保存失败");

            if (model.StepLogId > 0)
            {
                var stepLogDb = repository.DbContext.Set<ZCTracking_ProblemSteplog>();
                var stepLog = await stepLogDb.AsNoTracking().FirstOrDefaultAsync(x => x.ID == model.StepLogId);
                if (stepLog != null && stepLog.AddUser > 0)
                {
                    var orderNumber = main.Numbers ?? string.Empty;
                    var title = $"制程问题单【{orderNumber}】5Why待答复，请于3日内填写原因";
                    var deadline = now.AddDays(3);
                    var questionMailRows = new List<ZCFiveWhyMailTableItem>();
                    var allQuestions = await db.AsNoTracking()
                        .Where(x => x.ProblemId == model.ProblemId && !string.IsNullOrWhiteSpace(x.Question))
                        .OrderBy(x => x.AddDate)
                        .ThenBy(x => x.ID)
                        .ToListAsync();

                    foreach (var row in newRows)
                    {
                        await _pubTaskService.AddTaskAsync(zcFiveWhyAnswerTask, row.ID, title, stepLog.AddUser, now, deadline, "", model.ProblemId.ToString());
                        var seqNo = allQuestions.FindIndex(x => x.ID == row.ID) + 1;
                        if (seqNo <= 0)
                            seqNo = allQuestions.Count;
                        questionMailRows.Add(new ZCFiveWhyMailTableItem
                        {
                            SeqNo = seqNo,
                            ActionType = "新增",
                            Question = FormatZCFiveWhyLogText(row.Question)
                        });
                    }

                    var toEmail = await _hrEmployeeService.GetEmailFromIDAsync(stepLog.AddUser.ToString());
                    if (!string.IsNullOrWhiteSpace(toEmail) && questionMailRows.Any())
                    {
                        var questionUserName = await _hrEmployeeService.GetNameByIDAsync(userId.ToString());
                        var mailSubject = $"制程问题单【{orderNumber}】5Why已提交问题";
                        var mailIntro = "<p>您好，" + EncodeZCFiveWhyMailText(orderNumber) + " 的5Why问题已由 "
                            + EncodeZCFiveWhyMailText(questionUserName) + " 提交，请您在3个工作日内填写原因。</p>";
                        var questionTableHtml = BuildZCFiveWhyQuestionMailTableHtml(questionMailRows);
                        var mailContent = mailIntro + "<p><b>本次新增/修改的5Why问题：</b></p>" + questionTableHtml;
                        var ccEmail = UserContext.Current.UserInfo.Email;
                        SendZCFiveWhyMail(model.ProblemId, toEmail, ccEmail, mailSubject, mailContent);
                    }
                }
            }

            return WebResponseContent.OK_obj();
        }

        /// <summary>
        /// 批量修改 5Why 问题：仅提问人可修改自己提交的问题，并通知步骤处理人
        /// </summary>
        public async Task<WebResponseContent> UpdateFiveWhyQuestionsBatch(UpdateZCFiveWhyQuestionsBatchModel model)
        {
            if (model == null || model.ProblemId <= 0)
                return WebResponseContent.Error_obj("参数无效");
            var submitItems = (model.Items ?? new List<UpdateZCFiveWhyQuestionBatchItemModel>())
                .Where(x => x != null && x.ID > 0 && !string.IsNullOrWhiteSpace(x.Question))
                .Select(x => new UpdateZCFiveWhyQuestionBatchItemModel { ID = x.ID, Question = x.Question.Trim() })
                .ToList();
            if (!submitItems.Any())
                return WebResponseContent.Error_obj("请至少选择一条待修改的问题");

            var main = await GetProblemInfo(model.ProblemId);
            var validateMsg = ValidateZCFiveWhyEditable(main);
            if (validateMsg != null)
                return WebResponseContent.Error_obj(validateMsg);

            var db = repository.DbContext.Set<ZCTracking_ProblemFiveWhy>();
            var userId = UserContext.Current.UserId;
            var problemId = model.ProblemId;
            var updatedRows = new List<ZCTracking_ProblemFiveWhy>();
            var questionMailRows = new List<ZCFiveWhyMailTableItem>();
            var allQuestions = await db.AsNoTracking()
                .Where(x => x.ProblemId == problemId && !string.IsNullOrWhiteSpace(x.Question))
                .OrderBy(x => x.AddDate)
                .ThenBy(x => x.ID)
                .ToListAsync();

            foreach (var item in submitItems)
            {
                var row = await db.FirstOrDefaultAsync(x => x.ID == item.ID && x.ProblemId == problemId);
                if (row == null)
                    return WebResponseContent.Error_obj("记录不存在");
                if (string.IsNullOrWhiteSpace(row.Question))
                    return WebResponseContent.Error_obj("问题尚未提交，不可修改");
                if (!UserContext.Current.IsSuperAdmin && row.AddUser != userId)
                    return WebResponseContent.Error_obj("仅能修改自己提交的问题");
                if (string.Equals(row.Question.Trim(), item.Question, StringComparison.Ordinal))
                    continue;

                row.Question = item.Question;
                repository.Update(row);
                updatedRows.Add(row);
            }

            if (!updatedRows.Any())
                return WebResponseContent.Error_obj("没有需要保存的修改");

            if (await repository.SaveChangesAsync() <= 0)
                return WebResponseContent.Error_obj("保存失败");

            if (model.StepLogId > 0)
            {
                var stepLogDb = repository.DbContext.Set<ZCTracking_ProblemSteplog>();
                var stepLog = await stepLogDb.AsNoTracking().FirstOrDefaultAsync(x => x.ID == model.StepLogId);
                if (stepLog != null && stepLog.AddUser > 0)
                {
                    foreach (var row in updatedRows)
                    {
                        var seqNo = allQuestions.FindIndex(x => x.ID == row.ID) + 1;
                        if (seqNo <= 0)
                            seqNo = allQuestions.Count;
                        questionMailRows.Add(new ZCFiveWhyMailTableItem
                        {
                            SeqNo = seqNo,
                            ActionType = "修改",
                            Question = FormatZCFiveWhyLogText(row.Question)
                        });
                    }

                    var toEmail = await _hrEmployeeService.GetEmailFromIDAsync(stepLog.AddUser.ToString());
                    if (!string.IsNullOrWhiteSpace(toEmail) && questionMailRows.Any())
                    {
                        var orderNumber = main.Numbers ?? string.Empty;
                        var questionUserName = await _hrEmployeeService.GetNameByIDAsync(userId.ToString());
                        var mailSubject = $"制程问题单【{orderNumber}】5Why问题已修改";
                        var mailIntro = "<p>您好，" + EncodeZCFiveWhyMailText(orderNumber) + " 的5Why问题已由 "
                            + EncodeZCFiveWhyMailText(questionUserName) + " 修改，请您在3个工作日内填写原因。</p>";
                        var questionTableHtml = BuildZCFiveWhyQuestionMailTableHtml(questionMailRows);
                        var mailContent = mailIntro + "<p><b>本次修改的5Why问题：</b></p>" + questionTableHtml;
                        var ccEmail = UserContext.Current.UserInfo.Email;
                        SendZCFiveWhyMail(problemId, toEmail, ccEmail, mailSubject, mailContent);
                    }
                }
            }

            return WebResponseContent.OK_obj();
        }

        /// <summary>
        /// 批量提交/修改 5Why 原因：待答复由责任人首次填写；已答复仅原因填写人可改；合并通知各提问人
        /// </summary>
        public async Task<WebResponseContent> SaveFiveWhyReasonsBatch(SaveZCFiveWhyReasonsBatchModel model)
        {
            if (model == null || model.ProblemId <= 0)
                return WebResponseContent.Error_obj("参数无效");
            var submitItems = (model.Items ?? new List<SaveZCFiveWhyReasonBatchItemModel>())
                .Where(x => x != null && x.ID > 0 && !string.IsNullOrWhiteSpace(x.Reason))
                .Select(x => new SaveZCFiveWhyReasonBatchItemModel { ID = x.ID, Reason = x.Reason.Trim() })
                .ToList();
            if (!submitItems.Any())
                return WebResponseContent.Error_obj("请至少填写一条原因");

            var main = await GetProblemInfo(model.ProblemId);
            var validateMsg = ValidateZCFiveWhyEditable(main);
            if (validateMsg != null)
                return WebResponseContent.Error_obj(validateMsg);

            var db = repository.DbContext.Set<ZCTracking_ProblemFiveWhy>();
            var userId = UserContext.Current.UserId;
            var now = DateTime.Now;
            var firstFillRows = new List<ZCTracking_ProblemFiveWhy>();
            var reasonMailRows = new List<ZCFiveWhyMailTableItem>();
            var allQuestions = await db.AsNoTracking()
                .Where(x => x.ProblemId == model.ProblemId && !string.IsNullOrWhiteSpace(x.Question))
                .OrderBy(x => x.AddDate)
                .ThenBy(x => x.ID)
                .ToListAsync();

            foreach (var item in submitItems)
            {
                var row = await db.FirstOrDefaultAsync(x => x.ID == item.ID);
                if (row == null)
                    return WebResponseContent.Error_obj("记录不存在");
                if (row.ProblemId != model.ProblemId)
                    return WebResponseContent.Error_obj("记录与制程单不匹配");
                if (row.Status != 0 && row.Status != 1)
                    return WebResponseContent.Error_obj("存在不可操作的问题状态，请刷新后重试");

                var isUpdate = row.Status == 1;
                if (isUpdate)
                {
                    if (!UserContext.Current.IsSuperAdmin && (!row.UpdateUser.HasValue || row.UpdateUser.Value != userId))
                        return WebResponseContent.Error_obj("仅原因填写人可修改该5Why原因");
                    if (string.Equals((row.Reason ?? "").Trim(), item.Reason, StringComparison.Ordinal))
                        continue;
                }
                else
                {
                    var reasonActorMsg = await ValidateZCFiveWhyReasonActor(row.ID, userId);
                    if (reasonActorMsg != null)
                        return WebResponseContent.Error_obj(reasonActorMsg);
                }

                var oldReason = row.Reason;
                row.Reason = item.Reason;
                row.Status = 1;
                row.UpdateUser = userId;
                row.UpdateDate = now;
                repository.Update(row);
                if (!isUpdate)
                    firstFillRows.Add(row);

                var seqNo = allQuestions.FindIndex(x => x.ID == row.ID) + 1;
                if (seqNo <= 0)
                    seqNo = allQuestions.Count;
                reasonMailRows.Add(new ZCFiveWhyMailTableItem
                {
                    SeqNo = seqNo,
                    ActionType = isUpdate ? "修改" : "填写",
                    Question = row.Question ?? "",
                    Reason = isUpdate
                        ? "原因【" + FormatZCFiveWhyLogText(oldReason) + "】修改为【" + FormatZCFiveWhyLogText(item.Reason) + "】。"
                        : FormatZCFiveWhyLogText(row.Reason),
                    QuestionUserID = row.AddUser
                });
            }

            if (!reasonMailRows.Any())
                return WebResponseContent.Error_obj("没有需要保存的修改");

            if (await repository.SaveChangesAsync() <= 0)
                return WebResponseContent.Error_obj("保存失败");

            // 仅首次填写办结待办
            foreach (var row in firstFillRows)
            {
                await _pubTaskService.FinishTaskAsync(zcFiveWhyAnswerTask, row.ID);
            }

            var orderNumber = main.Numbers ?? string.Empty;
            var reasonUserName = await _hrEmployeeService.GetNameByIDAsync(userId.ToString());
            var mailSubject = $"制程问题单【{orderNumber}】5Why已填写原因";
            var ccEmail = UserContext.Current.UserInfo.Email;
            var questionUserIds = reasonMailRows.Select(x => x.QuestionUserID).Distinct().ToList();
            foreach (var questionUserId in questionUserIds)
            {
                var toEmail = await _hrEmployeeService.GetEmailFromIDAsync(questionUserId.ToString());
                if (string.IsNullOrWhiteSpace(toEmail))
                    continue;
                var recipientRows = reasonMailRows.Where(x => x.QuestionUserID == questionUserId).ToList();
                var reasonTableHtml = BuildZCFiveWhyReasonMailTableHtml(recipientRows);
                var mailContent = "<p>您好，" + EncodeZCFiveWhyMailText(orderNumber) + " 的5Why原因已由 "
                    + EncodeZCFiveWhyMailText(reasonUserName) + " 提交，详情如下。</p>"
                    + "<p><b>本次填写/修改的5Why原因（您提交的问题）：</b></p>" + reasonTableHtml;
                var problemId = model.ProblemId;
                SendZCFiveWhyMail(problemId, toEmail, ccEmail, mailSubject, mailContent);
            }

            return WebResponseContent.OK_obj(firstFillRows.Any() ? "原因已提交" : "原因已修改");
        }

        /// <summary>
        /// 获取制程 5Why 导出数据（批量导出复用；无数据时返回 null）
        /// </summary>
        public async Task<(FiveWhyExportDataDto ExportData, List<FiveWhyAnalysisReport> FiveWhyRows)?> TryGetZCTrackingFiveWhyExportPayload(int problemId)
        {
            if (problemId <= 0)
            {
                return null;
            }

            var main = await GetProblemInfo(problemId);
            if (main == null)
            {
                return null;
            }

            var orderNumber = main.Numbers ?? string.Empty;
            var exportData = new FiveWhyExportDataDto
            {
                Title = "国内制程问题",
                OrderNumber = orderNumber,
                ProductName = main.CInvCode ?? "",
                ProblemDesc = main.ProblemDesc ?? "",
                RootCause = main.Reason ?? "",
                ImprovementMeasure = main.Measures ?? "",
                SourceText = string.IsNullOrWhiteSpace(orderNumber) ? "制程问题" : "制程问题【" + orderNumber + "】",
                FileNamePrefix = string.IsNullOrWhiteSpace(orderNumber) ? "ZCTracking" : orderNumber,
            };

            var db = repository.DbContext.Set<ZCTracking_ProblemFiveWhy>();
            var rows = await db.AsNoTracking()
                .Where(x => x.ProblemId == problemId)
                .OrderBy(x => x.AddDate)
                .ThenBy(x => x.ID)
                .ToListAsync();

            var fiveWhyRows = rows
                .Where(r => !string.IsNullOrWhiteSpace(r.Question) || !string.IsNullOrWhiteSpace(r.Reason))
                .Select((r, index) => new FiveWhyAnalysisReport
                {
                    SeqNo = index + 1,
                    Question = r.Question,
                    Reason = r.Reason,
                })
                .ToList();

            if (!fiveWhyRows.Any())
            {
                return null;
            }

            return (exportData, fiveWhyRows);
        }

        /// <summary>
        /// 导出制程 5Why 分析报告 Excel
        /// </summary>
        public async Task<(byte[] FileBytes, string FileName)> ExportZCTrackingFiveWhyReport(int problemId)
        {
            if (problemId <= 0)
            {
                throw new Exception("参数错误！");
            }

            var payload = await TryGetZCTrackingFiveWhyExportPayload(problemId);
            if (payload == null)
            {
                var main = await GetProblemInfo(problemId);
                if (main == null)
                {
                    throw new Exception("单据不存在！");
                }
                throw new Exception("没有可导出的5Why数据！");
            }

            var (exportData, fiveWhyRows) = payload.Value;
            var fileBytes = FiveWhyExcelExportHelper.BuildWorkbook(exportData, fiveWhyRows);
            var fileName = (exportData.FileNamePrefix ?? "ZCTracking") + "_5Why分析报告.xlsx";
            return (fileBytes, fileName);
        }
        #endregion

    }
}
