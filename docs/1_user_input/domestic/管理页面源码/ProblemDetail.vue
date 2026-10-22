<!-- 问题详情 -->
<template>
  <div class="problem-detail-bd" :style="{ 'width': detailData.ProblemType == 3 ? '1500px' : '1100px' }">
    <header class="header-bd">
      <div>
        <img style="margin-left: 5px" src="@/assets/logo.png" width="80" alt="logo" />
      </div>
      <div class="header-tips">
        <p>百富计算机技术(深圳)有限公司</p>
        <p style="font-weight: 600; font-size: 15px">
          PAX Computer Technology (Shenzhen) Co., Ltd.
        </p>
      </div>
    </header>
    <h3 class="tab_header_title" style="margin-top: 15px; color: #333; padding-bottom: 10px">制程问题详情</h3>
    <div>
      <div class="number-bd">
        单号:<span>{{ detailData.Numbers }}</span>
      </div>
      <table class="tableModel">
        <tr>
          <th style="width:130px;">加工厂</th>
          <td style="width:200px;">{{ detailData.FactoryName }}</td>
          <th>机型</th>
          <td style="width:300px;">{{ detailData.MHead ? '物料' : detailData.ProductNameStr }}</td>
          <th>发现日期</th>
          <td>{{ detailData.FoundDate ? detailData.FoundDate.substr(0, 10) : '' }}</td>
        </tr>
        <tr>
          <th>问题分类</th>
          <td>{{ detailData.ProblemType | problemTypeFilter }}</td>
          <th>填单人</th>
          <td>{{ detailData.AddUserName }}</td>
          <th>填单日期</th>
          <td>{{ detailData.AddDate ? detailData.AddDate.substr(0, 10) : '' }}</td>
        </tr>
        <tr>
          <th>发现工位</th>
          <td>{{ detailData.Station }}</td>
          <th>版本</th>
          <td>{{ detailData.Version }}</td>
          <th>当前状态</th>
          <td>
            <template v-if="parallelStatusLabels">
              <div v-for="(line, idx) in parallelStatusLabels" :key="'ps-' + idx">
                <span>{{ line }}</span>
                <span style="margin-left:8px;color:red;" v-if="detailData.Status != 32">{{ line === '预防对策确认'
                  ? detailData.PreventionMemberListName : detailData.MemberListName }}</span>
              </div>
            </template>
            <template v-else>
              <template v-if="detailData.StatusStr">
                <span>{{ detailData.StatusStr }}</span>
              </template>
              <template v-else>
                <span>{{ detailData.Status | StatusFilter }}</span>
              </template>
              <span style="margin-left:8px;color:red;" v-if="detailData.Status != 32">{{ detailData.MemberListName
                }}</span>
            </template>
            <div v-if="detailData.IQCStatus">
              <span>{{ detailData.IQCStatus | StatusFilter }}</span>
              <span style="margin-left:8px;color:red;">{{ detailData.IQCMemberListName }}</span>
            </div>
            <div v-if="detailData.RiskStatus">
              <span>{{ detailData.RiskStatus | StatusFilter }}</span>
              <span style="margin-left:8px;color:red;">{{ detailData.RiskMemberListName }}</span>
            </div>
          </td>
        </tr>
        <tr>
          <th>问题等级
            <el-popover placement="right" width="850" trigger="hover">
              <div v-html="LevelRemark" style="white-space: pre-wrap;word-wrap: break-word;"></div>
              <span class="iconfont icon-info th-icon" slot="reference"></span>
            </el-popover>
          </th>
          <td :colspan="!detailData.MHead ? '1' : '5'">{{ detailData.ProblemLevel }}</td>
          <template v-if="!detailData.MHead">
            <th>产品在制属性</th>
            <td colspan="3">
              <!-- {{ detailData.OutPutStatus | OutPutStatusFilter }} -->
              <span>{{ detailData.MoOrderAttrName }}</span>
            </td>
          </template>
        </tr>
        <tr v-if="detailData.AllReDepartmentName || detailData.ReasonClass">
          <template v-if="detailData.ProblemType != 3">
            <th>责任部门</th>
            <td>{{ detailData.AllReDepartmentName }}</td>
          </template>
          <th>原因分类</th>
          <td :colspan="detailData.ProblemType == 3 ? '5' : '3'">
            <div v-if="detailData.ReasonClass" v-html="base.formatterBr(detailData.ReasonClass)"></div>
          </td>
        </tr>
        <tr v-if="detailData.ReasonClassRemark">
          <th>原因说明</th>
          <td colspan="5">
            <div v-if="detailData.ReasonClassRemark" v-html="base.formatterBr(detailData.ReasonClassRemark)"></div>
          </td>
        </tr>
        <tr v-if="!detailData.MHead">
          <th>生产订单
            <i :class="produceOrderIsFold ? 'el-icon-circle-plus-outline' : 'el-icon-remove-outline'" class="fold-icon"
              @click="produceOrderIsFold = !produceOrderIsFold"
              :title="produceOrderIsFold ? '点击展开生产订单明细' : '点击隐藏生产订单明细'"></i>
          </th>
          <td colspan="5">
            <!-- <span class="table-column-link" style="text-decoration: none;"
              @click="produceOrderIsFold = !produceOrderIsFold">{{produceOrderIsFold ? '点击展开生产订单明细' : '点击隐藏生产订单明细'}}</span> -->

            <el-table :data="produceOrderList" class="detail-table" :max-height="500" style="width: 100%;" border
              show-summary :summary-method="getSummaries" id="produce-table" v-show="!produceOrderIsFold">
              <el-table-column type="index" label="序号" width="55" align="center"></el-table-column>
              <el-table-column prop="OrderNumber" label="订单号" width="80" align="center">
                <template slot-scope="scope">
                  <span class="table-column-link" @click="viewMoOrderDetail(scope.row.OrderNumber)" title="点击查看订单详情">
                    {{ scope.row.OrderNumber }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="IssueDate" label="发料日期" width="105" align="center" :formatter="base.formatterDate">
              </el-table-column>
              <el-table-column prop="PartName" label="PN" width="230" align="center">
                <template slot-scope="scope">
                  <div>{{ scope.row.PartName }} <br><span>{{ scope.row.PartNumber }}</span> </div>
                </template>
              </el-table-column>
              <el-table-column prop="Version" label="版本" width="170" align="center" header-align="center">
                <template slot-scope="scope">
                  <template v-if="scope.row.VerInfoList && scope.row.VerInfoList.length > 0">
                    <span v-for="(item, i) in scope.row.VerInfoList" :key="i" @click="viewVersionDetail(item.FID)"
                      class="table-column-link" style="text-decoration: none;" title="点击查看版本详情">{{ item.FName }}
                      <span v-if="i != scope.row.VerInfoList.length - 1">,</span>
                    </span>
                  </template>
                </template>
              </el-table-column>
              <el-table-column prop="OrderQty" label="订单数量" width="" align="center" :formatter="formatterQty">
              </el-table-column>
              <el-table-column prop="ReceiptQty" label="已入库数量" width="" align="center" :formatter="formatterQty">
              </el-table-column>
              <el-table-column prop="OnlineQty" label="在线数量" width="" align="center" :formatter="formatterQty">
              </el-table-column>
            </el-table>
          </td>
        </tr>
        <tr v-if="!detailData.MHead">
          <th>影响数量</th>
          <td colspan="5">{{ $numeral(detailData.ImpactQty).format('0,0') }}</td>
        </tr>
        <!-- 小板订单 -->
        <tr v-if="detailData.MHead">
          <th>小板订单
            <i :class="XBOrdersIsFold ? 'el-icon-circle-plus-outline' : 'el-icon-remove-outline'" class="fold-icon"
              @click="XBOrdersIsFold = !XBOrdersIsFold" :title="XBOrdersIsFold ? '点击展开小板订单明细' : '点击隐藏小板订单明细'"></i>
          </th>
          <td colspan="5">
            <template v-if="detailData.XBOrders">
              <el-table :data="detailData.XBOrders" class="common-table" border style="width: 100%"
                v-show="!XBOrdersIsFold" show-summary :summary-method="getXBOrderSummaries" id="xbOrder-table">
                <el-table-column type="index" label="序号" width="60" align="center"></el-table-column>
                <el-table-column prop="OrderNumber" label="订单号" width="90" align="center">
                  <template slot-scope="scope">
                    <span class="table-column-link" @click="viewMoOrderDetail(scope.row.OrderNumber)"
                      title="点击查看订单详情">{{ scope.row.OrderNumber }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="Description" label="订单类别" width="115" align="center"></el-table-column>
                <el-table-column prop="InvCode" label="料号" width="135" align="center"></el-table-column>
                <el-table-column prop="InvStd" label="描述" width="" align="left" header-align="center"></el-table-column>
                <el-table-column prop="Qty" label="数量" width="110" align="center"
                  :formatter="base.formatterQty"></el-table-column>
                <el-table-column prop="InQty" label="入库数量" width="110" align="center"
                  :formatter="base.formatterQty"></el-table-column>
                <el-table-column prop="NoQty" label="未入库数量" width="110" align="center"
                  :formatter="base.formatterQty"></el-table-column>
              </el-table>
            </template>
          </td>
        </tr>
        <tr>
          <th>生产数量</th>
          <td>{{ detailData.ProdQty ? $numeral(detailData.ProdQty).format('0,0') : '' }}</td>
          <th>不良数量</th>
          <td>{{ detailData.BadQty ? $numeral(detailData.BadQty).format('0,0') : '' }}</td>
          <th>不良率(%)</th>
          <td>
            <!-- {{ getShowRate(detailData.Rate) }} -->
            {{ detailData.Rate ? detailData.Rate + '%' : '' }}
          </td>
        </tr>
        <tr>
          <th>是否需要停产</th>
          <td :colspan="detailData.IsStop == 1 ? '' : '5'">{{ detailData.IsStop == 1 ? '是' : '否' }}</td>
          <template v-if="detailData.IsStop == 1">
            <th>停线状态</th>
            <td style="padding: 8px;">
              <!-- StopStatus 1停线中，2已经重启，3没有停线，4重启审核，5审核通过  6责任人填写重启方案 -->
              <span v-if="detailData.StopStatus == 4">重启审核中
                <span v-show="detailData.ReStartExamineUserName" style="margin-left:8px;color: red;">({{
                  detailData.ReStartExamineUserName }})</span>
              </span>
              <span v-else-if="detailData.StopStatus == 6">责任人填写重启方案
                <span v-show="detailData.ReStartSchemeUserName" style="color: red;">({{
                  detailData.ReStartSchemeUserName }})</span>
              </span>
              <span v-else>{{ detailData.StopStatus == 1 ? '停线中' : detailData.StopStatus == 2 ? '已经重启' :
                detailData.StopStatus == 5 ? '重启审核通过' : '没有停线' }}
              </span>
            </td>
            <th>停产日期</th>
            <td>{{ detailData.StopDate ? detailData.StopDate.substr(0, 10) : '' }}</td>
          </template>
        </tr>
        <!-- StopStatus 1停线中，2已经重启，3没有停线，4重启审核，5审核通过  6责任人填写重启方案 -->
        <template
          v-if="StepLogs[StepIdArr.lastIndexOf(29)] && (StepLogs[StepIdArr.lastIndexOf(29)].Result || StepLogs[StepIdArr.lastIndexOf(29)].Opinon)">
          <tr>
            <th>重启日期</th>
            <td :colspan="StepLogs[StepIdArr.lastIndexOf(29)].Opinon ? '1' : '5'">
              <span>{{ new Date(StepLogs[StepIdArr.lastIndexOf(29)].Result).toJSON().substr(0, 10) }}</span>
            </td>
            <template v-if="StepLogs[StepIdArr.lastIndexOf(29)].Opinon">
              <th>重启备注</th>
              <td colspan="3">
                <div v-html="base.formatterBr(StepLogs[StepIdArr.lastIndexOf(29)].Opinon)"></div>
              </td>
            </template>
          </tr>
        </template>
        <!-- 责任人填写重启方案  -->
        <template v-if="(detailData.StopStatus != 6) && StepLogs[StepIdArr.lastIndexOf(34)]">
          <tr
            v-if="detailData.StopStatus == 4 ? (CurrentUser == detailData.ReStartExamineUser || CurrentUser == StepLogs[StepIdArr.lastIndexOf(34)].AddUser || $store.getters.getUserInfo().isSuperAdmin) : true">
            <th>重启方案</th>
            <td colspan="5">
              <div v-html="base.formatterBr(StepLogs[StepIdArr.lastIndexOf(34)].Opinon)"
                v-if="StepLogs[StepIdArr.lastIndexOf(34)].Opinon"></div>
              <div style="text-align: right;color: #777;font-size: 12px;">
                <span>{{ StepLogs[StepIdArr.lastIndexOf(34)].AddUserStr }}</span>
                <span style="margin-left: 10px;">{{ StepLogs[StepIdArr.lastIndexOf(34)].AddDate ? new
                  Date(StepLogs[StepIdArr.lastIndexOf(34)].AddDate).toJSON() : '' }}</span>
              </div>
            </td>
          </tr>
        </template>
        <!-- 上级领导重启审核 StepId29 重启操作  34责任人填写重启方案 32上级领导重启审核-->
        <template
          v-if="(detailData.StopStatus != 4 && detailData.StopStatus != 6) && StepLogs[StepIdArr.lastIndexOf(32)]">
          <tr>
            <th>重启审核意见</th>
            <td colspan="5">
              <div>{{ StepLogs[StepIdArr.lastIndexOf(32)].Result == 1 ? '同意' :
                StepLogs[StepIdArr.lastIndexOf(32)].Result == 0 ? '不同意' : '' }}</div>

              <div v-html="base.formatterBr(StepLogs[StepIdArr.lastIndexOf(32)].Opinon)"
                v-if="StepLogs[StepIdArr.lastIndexOf(32)].Opinon">
              </div>
              <div style="text-align: right;color: #777;font-size: 12px;">
                <span>{{ StepLogs[StepIdArr.lastIndexOf(32)].AddUserStr }}</span>
                <span style="margin-left: 10px;">{{ StepLogs[StepIdArr.lastIndexOf(32)].AddDate ? new
                  Date(StepLogs[StepIdArr.lastIndexOf(32)].AddDate).toJSON() : '' }}</span>
              </div>
            </td>
          </tr>
          <!-- <tr>
            <th>重启审核意见</th>
            <td :colspan="StepLogs[StepIdArr.lastIndexOf(32)].Opinon ? '1' : '5'">
              <span>{{ StepLogs[StepIdArr.lastIndexOf(32)].Result == 1 ? '同意' :
                StepLogs[StepIdArr.lastIndexOf(32)].Result == 0 ? '不同意' : '' }}</span>
            </td>
            <template v-if="StepLogs[StepIdArr.lastIndexOf(32)].Opinon">
              <th>重启审核备注</th>
              <td colspan="3">
                <div v-html="base.formatterBr(StepLogs[StepIdArr.lastIndexOf(32)].Opinon)"></div>
              </td>
            </template>
</tr>
<tr>
  <th>重启审核人</th>
  <td>{{ StepLogs[StepIdArr.lastIndexOf(32)].AddUserStr }}</td>
  <th>重启审核时间</th>
  <td colspan="3">
    <span>{{ StepLogs[StepIdArr.lastIndexOf(32)].AddDate ?
      new Date(StepLogs[StepIdArr.lastIndexOf(32)].AddDate).toJSON() : '' }}
    </span>
  </td>
</tr> -->
        </template>

        <tr v-if="detailData.CInvCode || detailData.CInvDesc">
          <th>料号&描述</th>
          <td colspan="5">{{ detailData.CInvCode }} <span style="margin-left:10px;">{{ detailData.CInvDesc }}</span>
          </td>
        </tr>
        <tr v-if="detailData.VenCode || detailData.VenName">
          <th>供应商编号&名称</th>
          <td colspan="5">{{ detailData.VenCode }} <span style="margin-left:10px;">{{ detailData.VenName }}</span></td>
        </tr>

        <!-- 以前的单据可能没有问题现象、可能问题原因、可能的问题物料 -->
        <tr v-if="hasCheckedPhenomenonArr.length > 0">
          <th>问题现象</th>
          <td colspan="5">
            <div class="tag-td">
              <el-tag v-for="tag in hasCheckedPhenomenonArr" :key="tag.PhenomenonID" class="tag-item">
                <span :title="tag.TypeName + '->' + tag.ClassName + '->' + tag.PhenomenonDesc">{{
                  tag.PhenomenonDesc }}</span>
              </el-tag>
            </div>
          </td>
        </tr>
        <tr v-if="reasonList.length > 0">
          <th>可能问题原因</th>
          <td colspan="5">
            <p class="bold-p">根据选择的问题现象，系统分析可能原因如下：</p>
            <div class="scroll-bd">
              <p v-for="(subItem, j) in reasonList" :key="subItem.ID" style="padding: 3px 0 3px 16px;"
                class="scroll-bd-p">
                {{ (j + 1) }}、{{ subItem.ReasonDesc }}</p>
            </div>
          </td>
        </tr>
        <tr v-if="aboutMaterialList.length > 0">
          <th>可能的问题物料</th>
          <td colspan="5">
            <p class="bold-p">根据您选择的问题类别和外观现象，系统分析可能的涉及问题物料如下：</p>
            <div class="scroll-bd">
              <p v-for="(subItem, j) in aboutMaterialList" :key="subItem.InvCode" class="scroll-bd-p">
                {{ (j + 1) }}、{{ subItem.InvCode }} <span>{{ subItem.InvStd }}</span> </p>
            </div>
          </td>
        </tr>


        <tr>
          <th>问题描述
            <!-- 结案前责任人可以修改 -->
            <i class="el-icon-edit-outline table-column-link" title="修改问题描述"
              style="text-decoration: none;font-size: 16px;" @click="editReasonClick(5)"
              v-if="detailData.Status != 32 && (CurrentUser == detailData.AddUser || $store.getters.getUserInfo().isSuperAdmin)"></i>
          </th>
          <td colspan="5">
            <div class="problem-desc-td" v-html="detailData.ProblemDesc"></div>
            <template v-if="detailData.ProblemDescObj">
              <el-image v-for="(item, index) in detailData.ProblemDescObj.ImageSrcArr" :key="index" :src="item"
                fit="contain"></el-image>
            </template>
          </td>
        </tr>
        <tr v-if="detailData.Improve">
          <th>改善建议</th>
          <td colspan="5">
            <div class="problem-desc-td" v-html="detailData.Improve"></div>
            <template v-if="detailData.ImproveObj">
              <el-image v-for="(item, index) in detailData.ImproveObj.ImageSrcArr" :key="index" :src="item"
                fit="contain"></el-image>
            </template>
          </td>
        </tr>
        <tr v-if="detailData.Remark">
          <th>备注</th>
          <td colspan="5" v-html="detailData.Remark"></td>
        </tr>
        <tr v-if="detailData.StepLogs && detailData.StepLogs[0].File.length > 0">
          <th>附件</th>
          <td colspan="5">
            <template v-for="item in detailData.StepLogs[0].File">
              <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                style="margin-right:15px;">{{ item.Key }}</a>
            </template>
          </td>
        </tr>
        <tr v-if="problemType == 3">
          <th>CAR编号</th>
          <td colspan="5">
            <a :href="$store.state.system.appsettings.oldUrl + '/QualityManage/Vendor/VendorReportOutDetail.aspx?VendorReportOutID=' + detailData.CARID"
              target="_blank" style="color:#409eff;text-decoration: none;" rel="noopener noreferrer"
              title="点击查看CAR报告详情">{{
                detailData.CAR }}</a>
          </td>
        </tr>
        <tr>
          <th>操作记录</th>
          <td colspan="5">
            <span class="table-column-link" style="color:#409eff;text-decoration: none;"
              @click="viewStepLogs">点击查看</span>
          </td>
        </tr>
        <template v-if="RiskInfo.ID">
          <tr>
            <th colspan="6">风险订单信息</th>
          </tr>
          <tr>
            <th>贴片物料
            </th>
            <td colspan="5">
              {{ RiskInfo.IsPatch == 1 ? '是' : '否' }}
            </td>
          </tr>
          <tr>
            <th>风险批次类型
            </th>
            <td colspan="5">
              {{ RiskInfo.BatchType === 1 ? '供应商批次' : RiskInfo.BatchType === 2 ? 'IQC批次' : '检验单号' }}
            </td>
          </tr>
          <tr>
            <th>风险批次
            </th>
            <td colspan="5">
              {{ RiskInfo.RiskBatch }}
            </td>
          </tr>
          <tr>
            <th>交货数量
            </th>
            <td colspan="">
              {{ $numeral(RiskInfo.DeliveryQty).format('0,0') }}
            </td>
            <th>库存数量
            </th>
            <td colspan="">
              {{ $numeral(RiskInfo.StockQty).format('0,0') }}
            </td>
            <th>发料数量<br>（柯洱斯）
            </th>
            <td colspan="">
              {{ $numeral(RiskInfo.KESQty).format('0,0') }}
            </td>
          </tr>
          <tr>

            <th>发料数量<br>（亮亮）
            </th>
            <td colspan="">
              {{ $numeral(RiskInfo.LLQty).format('0,0') }}
            </td>
            <th>发料数量<br>（惠州百富）
            </th>
            <td colspan="">
              {{ $numeral(RiskInfo.HZQty).format('0,0') }}
            </td>
            <th>发料数量<br>（CKD）
            </th>
            <td>
              {{ $numeral(RiskInfo.CKDQty).format('0,0') }}
            </td>
          </tr>
          <tr>
            <th>发料数量<br>（其它）
            </th>
            <td colspan="5">
              {{ $numeral(RiskInfo.OtherQty).format('0,0') }}
            </td>
          </tr>
          <tr>
            <th>备注
            </th>
            <td colspan="5">
              {{ RiskInfo.Remark }}
            </td>
          </tr>
          <template v-if="RiskOrderList.length > 0">
            <tr>
              <th>风险订单
                <i :class="otherOrderIsFold ? 'el-icon-circle-plus-outline' : 'el-icon-remove-outline'"
                  class="fold-icon" @click="otherOrderIsFold = !otherOrderIsFold"
                  :title="otherOrderIsFold ? '点击展开其他在线订单明细' : '点击隐藏其他在线订单明细'" style="padding-right:0;"></i>
              </th>
              <td colspan="5">
                <!-- <span class="table-column-link" style="text-decoration: none;"
                  @click="otherOrderIsFold = !otherOrderIsFold">{{otherOrderIsFold ? '点击展开其他在线订单明细' : '点击隐藏其他在线订单明细'}}</span> -->
                <el-table class="list-table" :key="'risk-order-' + RiskInfo.IsPatch" :data="RiskOrderList" style="width: 100%;" border
                  v-show="!otherOrderIsFold" :max-height="500">
                  <el-table-column type="index" label="序号" width="55" align="center"></el-table-column>
                  <el-table-column prop="Factory" label="工厂" width="75" align="center" :formatter="formatterFactory">
                  </el-table-column>
                  <el-table-column prop="OrderNo" label="订单号" width="75" align="center">
                    <template slot-scope="scope">
                      <span v-if="scope.row.IsMoOrder" class="table-column-link" @click="viewMoOrderDetail(scope.row.OrderNo)" title="点击查看订单详情">{{
                        scope.row.OrderNo }}</span>                        
                      <span v-else>{{ scope.row.OrderNo }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="FaliaoDate" label="物料发料日期" width="100" align="center"
                    :formatter="base.formatterDate">
                  </el-table-column>
                  <el-table-column prop="ProductName" label="机型" width="185" align="center"></el-table-column>
                  <el-table-column prop="Qty" label="订单数量" width="width" align="center" :formatter="formatterQty">
                  </el-table-column>
                  <el-table-column prop="TotalinQty" label="已入库数量" width="85" align="center" :formatter="formatterQty">
                  </el-table-column>
                  <el-table-column prop="IssuedQty" label="规划用量" width="width" align="center" :formatter="formatterQty">
                  </el-table-column>
                  <el-table-column prop="IssQty" label="发料数量" width="80" align="center" :formatter="formatterQty">
                  </el-table-column>
                  <el-table-column prop="ReturnType" label="处理方式" width="80" align="center">
                    <template slot-scope="scope">
                      <div>
                        {{ scope.row.ReturnType == 1 ? '就地销毁' : scope.row.ReturnType == 2 ? '退回仓库' :
                          scope.row.ReturnType
                            == 3 ? '继续使用' : '' }}
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column v-if="Number(RiskInfo.IsPatch) === 1" prop="IsPatch" label="是否贴片" width="90" align="center">
                    <template slot-scope="scope">
                      <div>{{ scope.row.IsPatch === 1 ? '是' : scope.row.IsPatch === 0 ? '否' : '' }}</div>
                    </template>
                  </el-table-column>
                  <el-table-column prop="RiskUsedQty" label="已使用数量" width="90" align="center" :formatter="formatterQty">
                  </el-table-column>
                  <el-table-column prop="ReturnQty" label="需退货数量" width="90" align="center" :formatter="formatterQty">
                  </el-table-column>
                  <el-table-column prop="ReceivingQty" label="已收货数量" width="90" align="center"
                    :formatter="formatterQty"></el-table-column>
                </el-table>
              </td>
            </tr>
          </template>
        </template>
        <!-- 物料问题 -->
        <!-- IQC意见 有可能是在IQC意见节点中由物料问题转成其他问题-->
        <template
          v-if="StepIdArr.includes(14) && detailData.Status != 11 && detailData.OldProblemType && detailData.ProblemType != 3 && detailData.ProblemType != detailData.OldProblemType">
          <tr>
            <th colspan="6">IQC意见</th>
          </tr>
          <tr>
            <th>处理人</th>
            <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(14)].AddUserStr }}
              <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(14)].AddDate).toJSON() }}</span>
            </td>
          </tr>
          <tr>
            <th>是否修改分类</th>
            <td colspan="1">是</td>
            <th>改前问题分类</th>
            <!-- {detailData.OldProblemType | problemTypeFilter}} -->
            <!-- <td colspan="3">物料问题</td> -->
            <td colspan="3">{{ detailData.OldProblemType | problemTypeFilter }}</td>
          </tr>
          <tr>
            <th>备注</th>
            <td colspan="5" v-html="StepLogs[StepIdArr.lastIndexOf(14)].Opinon"></td>
          </tr>
        </template>

        <!-- 资料问题工程确认, 其他问题类别可能也有此项，因为有可能是从资料问题转其他问题类别的 -->
        <template
          v-if="
            StepIdArr.includes(4) && detailData.Status != 3 && !detailData.ZLConfirmResult && detailData.OldProblemType && detailData.ProblemType != 4 && detailData.ProblemType != detailData.OldProblemType">
          <tr>
            <th colspan="6">工程确认</th>
          </tr>
          <tr>
            <th>处理人</th>
            <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(4)].AddUserStr }}
              <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(4)].AddDate).toJSON() }}</span>
            </td>
          </tr>
          <tr>
            <th>确认结果</th>
            <td colspan="5">否</td>
          </tr>
          <tr>
            <th>修改的问题分类</th>
            <td colspan="5">{{ detailData.ProblemType | problemTypeFilter }}</td>
          </tr>
          <tr v-if="StepLogs[StepIdArr.lastIndexOf(4)].File.length > 0">
            <th>附件</th>
            <td colspan="5">
              <template v-for="item in detailData.StepLogs[StepIdArr.lastIndexOf(4)].File">
                <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                  style="margin-right:15px;">{{ item.Key }}</a>
              </template>
            </td>
          </tr>
          <tr v-if="StepLogs[StepIdArr.lastIndexOf(4)].Opinon">
            <th>备注</th>
            <td colspan="5" v-html="base.formatterBr(StepLogs[StepIdArr.lastIndexOf(4)].Opinon)"></td>
          </tr>
        </template>


        <!-- 针对制程优化类(ProblemType=7)，在提交问题后，先加一个生产角色确认节点 -->
        <template v-if="StepIdArr.length > 0 && StepIdArr.includes(33) && detailData.ProblemType == 7">
          <tr>
            <th colspan="6">生产角色确认</th>
          </tr>
          <tr>
            <th>处理人</th>
            <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(33)].AddUserStr }}
              <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(33)].AddDate).toJSON() }}</span>
            </td>
          </tr>
          <tr>
            <th>确认结果</th>
            <td colspan="5">
              <span>{{ StepLogs[StepIdArr.lastIndexOf(33)].Result == 0 ? '不同意' :
                StepLogs[StepIdArr.lastIndexOf(33)].Result == 1 ? '同意' : '' }}</span>
            </td>
          </tr>
          <tr v-if="StepLogs[StepIdArr.lastIndexOf(33)].Opinon">
            <th>备注</th>
            <td colspan="5">
              <div v-html="base.formatterBr(StepLogs[StepIdArr.lastIndexOf(33)].Opinon)"></div>
            </td>
          </tr>
        </template>
        <!-- 硬件、软件问题 -->
        <!-- 其他问题分类也有此项  其他问题分类可能是从硬件、软件问题修改的 -->
        <template v-if="StepIdArr.length > 0 && StepIdArr.includes(2) && detailData.Status > 1">
          <tr>
            <th colspan="6">指定责任人</th>
          </tr>
          <tr>
            <th>处理人</th>
            <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(2)].AddUserStr }}
              <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(2)].AddDate).toJSON() }}</span>
            </td>
          </tr>
          <tr>
            <th>责任人</th>
            <td colspan="5">{{ detailData.RUserStr }}
              <span style="margin-left:8px;" v-if="detailData.RDepartmentStr">({{ detailData.RDepartmentStr }})</span>
            </td>
          </tr>
        </template>

        <template v-if="StepIdArr.length > 0 && StepIdArr.includes(3) && detailData.Status > 2">
          <tr>
            <th colspan="6">责任人确认</th>
          </tr>
          <tr>
            <th>处理人</th>
            <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(3)].AddUserStr }}
              <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(3)].AddDate).toJSON() }}</span>
            </td>
          </tr>
          <tr>
            <th>确认结果</th>
            <td :colspan="detailData.RConfirm ? '1' : '5'">{{ detailData.RConfirm ? '是' : '否' }}</td>
            <th v-if="detailData.RConfirm">处理结果</th>
            <td v-if="detailData.RConfirm">
              {{ detailData.DesignConfirmResult | handleTypeFilter }}
            </td>
            <th v-if="detailData.RConfirm">计划完成时间</th>
            <td v-if="detailData.RConfirm">
              {{ detailData.RCompleteTime ? detailData.RCompleteTime.substr(0, 10) : '' }}</td>
          </tr>
          <tr v-if="detailData.RConfirm && detailData.Reason">
            <th>原因分析
              <!-- 结案前责任人可以修改 -->
              <i class="el-icon-edit-outline table-column-link" title="修改原因分析"
                style="text-decoration: none;font-size: 16px;" @click="editReasonClick(1)"
                v-if="detailData.Status != 32 && (CurrentUser == StepLogs[StepIdArr.lastIndexOf(3)].AddUser || $store.getters.getUserInfo().isSuperAdmin)"></i>
            </th>
            <td colspan="5">
              <div v-html="base.formatterBr(detailData.Reason)" class="html-style" @click="GoToImg($event)">
              </div>
            </td>
          </tr>
          <!-- 责任人确认步骤 5Why（硬件1/软件2/结构6/制程优化7） -->
          <process-five-why-analysis
            v-if="detailData.RConfirm && StepIdArr.includes(3)"
            :problem-id="problemId"
            :step-log-id="StepLogs[StepIdArr.lastIndexOf(3)].ID"
            :status="detailData.Status"
            :list="detailData.FiveWhyList || []"
            :is-detail-page="true"
            @refresh="getProblemDetail" />
          <tr v-if="detailData.RConfirm && detailData.Measures">
            <th>改善措施
              <!-- 结案前责任人可以修改 -->
              <i class="el-icon-edit-outline table-column-link" title="修改改善措施"
                style="text-decoration: none;font-size: 16px;" @click="editReasonClick(2)"
                v-if="detailData.Status != 32 && (CurrentUser == StepLogs[StepIdArr.lastIndexOf(3)].AddUser || $store.getters.getUserInfo().isSuperAdmin)"></i>
            </th>
            <td colspan="5">
              <div v-html="base.formatterBr(detailData.Measures)" class="html-style" @click="GoToImg($event)">
              </div>
            </td>
          </tr>
          <tr v-if="detailData.RConfirm && detailData.Prevention">
            <th>预防对策
              <!-- 结案前责任人可以修改 -->
              <i class="el-icon-edit-outline table-column-link" title="修改预防对策"
                style="text-decoration: none;font-size: 16px;" @click="editReasonClick(3)"
                v-if="detailData.Status != 32 && (CurrentUser == StepLogs[StepIdArr.lastIndexOf(3)].AddUser || $store.getters.getUserInfo().isSuperAdmin)"></i>
            </th>
            <td colspan="5">
              <div v-html="base.formatterBr(detailData.Prevention)" class="html-style" @click="GoToImg($event)">
              </div>
            </td>
          </tr>
          <tr v-if="!detailData.RConfirm">
            <th>修改的问题分类</th>
            <td colspan="5">{{ detailData.ProblemType | problemTypeFilter }}</td>
          </tr>
          <tr v-if="StepLogs[StepIdArr.lastIndexOf(3)].Opinon">
            <th>备注</th>
            <td colspan="5" v-html="base.formatterBr(StepLogs[StepIdArr.lastIndexOf(3)].Opinon)"></td>
          </tr>
        </template>
        <!-- 硬件、软件问题 -->

        <!-- 物料问题 -->
        <template v-if="problemType == 3 && StepIdArr.length > 0">
          <!-- IQC意见 -->
          <template v-if="StepIdArr.includes(14) && detailData.Status != 11">
            <tr>
              <th colspan="6">IQC意见</th>
            </tr>
            <tr>
              <th>处理人</th>
              <td colspan="3">{{ StepLogs[StepIdArr.lastIndexOf(14)].AddUserStr }}
                <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(14)].AddDate).toJSON() }}</span>
              </td>
              <th>是否修改分类</th>
              <td>否</td>
            </tr>

            <tr>
              <th>处理意见</th>
              <td colspan="5">{{ detailData.IQCOpinion == 2 ? '退回仓库' : detailData.IQCOpinion == 3 ? '继续使用' : '' }}</td>
            </tr>
            <tr>
              <th>备注</th>
              <td colspan="5" v-html="StepLogs[StepIdArr.lastIndexOf(14)].Opinon"></td>
            </tr>
            <!-- <OrderIQCOpinion :stockOrderData="stockOrderData" :onlineOrderData="onlineOrderData"
                  :otherOnlineOrderData="otherOnlineOrderData" :CKDOrderData="CKDOrderData"></OrderIQCOpinion> -->
            <template v-if="detailData.IQCOpinion == 3">
              <tr>
                <th>库存和在线</th>
                <td colspan="5">
                  <table class="tableModel order-table">
                    <tr class="first-tr" v-if="stockOrderData.length > 0">
                      <th style="width:130px;"></th>
                      <th style="width:150px;">仓库</th>
                      <th style="width:160px;">数量</th>
                      <th>合计</th>
                    </tr>
                    <template v-if="stockOrderData.length > 0">
                      <tr v-for="(item, index) in stockOrderData" :key="item.WhCode">
                        <th :rowspan="stockOrderData.length" v-if="index == 0">库存</th>
                        <td>{{ item.Warehouse }}</td>
                        <td>{{ item.Qty ? $numeral(item.Qty).format('0,0') : '' }}</td>
                        <!-- 合计 -->
                        <td :rowspan="stockOrderData.length" v-if="index == 0">{{ $numeral(stockTotalSum).format('0,0')
                        }}
                        </td>
                      </tr>
                    </template>
                    <template v-else>
                      <tr>
                        <th>库存</th>
                        <td colspan="6" class="td-center" style="color:#F56C6C;">暂无数据</td>
                      </tr>
                    </template>
                  </table>
                </td>
              </tr>
              <template v-if="RiskOrderList.length > 0">
              </template>
              <template v-else>
                <tr>
                  <th>其他在线订单
                    <i :class="otherOrderIsFold ? 'el-icon-circle-plus-outline' : 'el-icon-remove-outline'"
                      class="fold-icon" @click="otherOrderIsFold = !otherOrderIsFold"
                      :title="otherOrderIsFold ? '点击展开其他在线订单明细' : '点击隐藏其他在线订单明细'" style="padding-right:0;"></i>
                  </th>
                  <td colspan="5">
                    <el-table class="list-table" :data="otherOnlineOrderData" style="width: 100%;" border
                      v-show="!otherOrderIsFold" :max-height="500">
                      <el-table-column type="index" label="序号" width="60" align="center"></el-table-column>
                      <el-table-column prop="Factory" label="工厂" width="85" align="center"
                        :formatter="formatterFactory">
                      </el-table-column>
                      <el-table-column prop="OrderNo" label="订单号" width="90" align="center">
                        <template slot-scope="scope">
                          <span class="table-column-link" @click="viewMoOrderDetail(scope.row.OrderNo)"
                            title="点击查看订单详情">{{ scope.row.OrderNo }}</span>
                        </template>
                      </el-table-column>
                      <el-table-column prop="FaliaoDate" label="物料发料日期" width="120" align="center"
                        :formatter="base.formatterDate">
                      </el-table-column>
                      <el-table-column prop="ProductName" label="机型" width="" align="center"></el-table-column>
                      <el-table-column prop="Qty" label="订单数量" width="120" align="center" :formatter="formatterQty">
                      </el-table-column>
                      <el-table-column prop="TotalinQty" label="已入库数量" width="120" align="center"
                        :formatter="formatterQty">
                      </el-table-column>
                      <el-table-column prop="IssuedQty" label="规划用量" width="120" align="center"
                        :formatter="formatterQty">
                      </el-table-column>
                      <el-table-column prop="IssQty" label="发料数量(含超领)" width="120" align="center" :formatter="formatterQty">
                      </el-table-column>
                    </el-table>
                  </td>
                </tr>
              </template>
              <tr>
                <th>CKD机型
                  <i :class="CKDOrderIsFold ? 'el-icon-circle-plus-outline' : 'el-icon-remove-outline'"
                    class="fold-icon" @click="CKDOrderIsFold = !CKDOrderIsFold"
                    :title="CKDOrderIsFold ? '点击展开CKD机型订单明细' : '点击隐藏CKD机型订单明细'"></i>
                </th>
                <td colspan="5">
                  <el-table class="list-table" :data="CKDOrderData" style="width: 100%;" border v-show="!CKDOrderIsFold"
                    :max-height="500">
                    <el-table-column type="index" label="序号" width="60" align="center"></el-table-column>
                    <el-table-column prop="PO" label="PO" width="" align="center"></el-table-column>
                    <el-table-column prop="Invoice" label="Invoice" width="200" align="center"></el-table-column>
                    <el-table-column prop="IssuedQty" label="发料数量" width="140" align="center" :formatter="formatterQty">
                    </el-table-column>
                    <el-table-column prop="PickupDate" label="提货日期" width="140" align="center"
                      :formatter="base.formatterDate">
                    </el-table-column>
                  </el-table>
                </td>
              </tr>
            </template>
          </template>
          <!-- IQC确认 -->
          <template v-if="(StepIdArr.includes(7) || StepIdArr.includes(8)) && detailData.Status >= 6">
            <tr>
              <th colspan="6">IQC确认</th>
            </tr>
            <tr>
              <th>处理人</th>
              <td colspan="5">
                <div v-if="StepIdArr.includes(7)">
                  <span>{{ StepLogs[StepIdArr.lastIndexOf(7)].StepStr }}：</span>
                  {{ StepLogs[StepIdArr.lastIndexOf(7)].AddUserStr }}
                  <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(7)].AddDate).toJSON() }}</span>
                </div>
                <div v-if="StepIdArr.includes(8)">
                  <span>{{ StepLogs[StepIdArr.lastIndexOf(8)].StepStr }}：</span>
                  {{ StepLogs[StepIdArr.lastIndexOf(8)].AddUserStr }}
                  <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(8)].AddDate).toJSON() }}</span>
                </div>
                <div v-if="saveReturnIndex">
                  <span>保存退货单号：</span>
                  {{ StepLogs[saveReturnIndex].AddUserStr }}
                  <span class="add-date-span">{{ new Date(StepLogs[saveReturnIndex].AddDate).toJSON() }}</span>
                </div>
                <div v-if="confirmReturnIndex">
                  <span>确认退货单号：</span>
                  {{ StepLogs[confirmReturnIndex].AddUserStr }}
                  <span class="add-date-span">{{ new Date(StepLogs[confirmReturnIndex].AddDate).toJSON() }}</span>
                </div>
              </td>
            </tr>
            <tr>
              <th>库存和在线</th>
              <td colspan="5">
                <table class="tableModel order-table">
                  <tr>
                    <th style="width:100px;"></th>
                    <th style="width:180px;">仓库</th>
                    <th style="width:160px;">数量</th>
                    <th style="width:160px;">合计</th>
                    <th style="width:110px;">处理方式</th>
                    <th>需退货数量</th>
                    <th style="width:110px;">已收货数量</th>
                  </tr>
                  <template v-if="stockOrderData.length > 0">
                    <tr v-for="(item, index) in stockOrderData" :key="item.WhCode">
                      <th :rowspan="stockOrderData.length" v-if="index == 0">库存</th>
                      <td>{{ item.Warehouse }}</td>
                      <td>{{ item.Qty ? $numeral(item.Qty).format('0,0') : '' }}</td>
                      <!-- 合计 -->
                      <td :rowspan="stockOrderData.length" v-if="index == 0">
                        {{ stockTotalSum ? $numeral(stockTotalSum).format('0,0') : '' }}
                      </td>
                      <!-- 处理方式 -->
                      <td :rowspan="stockOrderData.length" v-if="index == 0">
                        {{ item.ReturnType == 1 ? '就地销毁' : item.ReturnType == 2 ? '退回供应商' : item.ReturnType == 3 ?
                          '继续使用'
                          : '' }}
                      </td>
                      <!-- 需退货数量 -->
                      <td :rowspan="stockOrderData.length" v-if="index == 0">
                        {{ item.StockReturnQty ? $numeral(item.StockReturnQty).format('0,0') : '' }}
                      </td>
                      <td :rowspan="stockOrderData.length" v-if="index == 0">
                        {{ item.ReceivingQty ? $numeral(item.ReceivingQty).format('0,0') : '' }}
                      </td>
                    </tr>
                  </template>
                  <template v-else>
                    <tr>
                      <th>库存</th>
                      <td colspan="6" class="td-center" style="color:#F56C6C;">暂无数据</td>
                    </tr>
                  </template>

                  <template v-if="onlineOrderData.length > 0">
                    <tr v-for="(item, index) in onlineOrderData" :key="item.WhCode">
                      <th :rowspan="onlineOrderData.length" v-if="index == 0">在线</th>
                      <td>{{ item.ProductionType == 1 ? '已使用' : '未使用' }}</td>
                      <td>
                        {{ item.Qty ? $numeral(item.Qty).format('0,0') : '' }}
                      </td>
                      <!-- 合计 -->
                      <td :rowspan="onlineOrderData.length" v-if="index == 0">
                        {{ onlineTotalSum ? $numeral(onlineTotalSum).format('0,0') : '' }}
                      </td>
                      <!-- 处理方式 -->
                      <td>
                        {{ item.ReturnType == 1 ? '就地销毁' : item.ReturnType == 2 ? '退回仓库' : item.ReturnType == 3 ? '继续使用'
                          : '' }}
                      </td>
                      <!-- 需退货数量 -->
                      <td>
                        {{ item.OReturnQty ? $numeral(item.OReturnQty).format('0,0') : '' }}
                      </td>
                      <td>
                        {{ item.ReceivingQty ? $numeral(item.ReceivingQty).format('0,0') : '' }}</td>
                    </tr>
                  </template>
                  <template v-else>
                    <tr>
                      <th>在线</th>
                      <td colspan="6" class="td-center" style="color:#F56C6C;">暂无数据</td>
                    </tr>
                  </template>
                </table>
              </td>
            </tr>
            <template v-if="RiskOrderList.length > 0">

            </template>
            <template v-else>
              <tr>
                <th>其他在线订单
                  <i :class="otherOrderIsFold ? 'el-icon-circle-plus-outline' : 'el-icon-remove-outline'"
                    class="fold-icon" @click="otherOrderIsFold = !otherOrderIsFold"
                    :title="otherOrderIsFold ? '点击展开其他在线订单明细' : '点击隐藏其他在线订单明细'" style="padding-right:0;"></i>
                </th>
                <td colspan="5">
                  <!-- <span class="table-column-link" style="text-decoration: none;"
                  @click="otherOrderIsFold = !otherOrderIsFold">{{otherOrderIsFold ? '点击展开其他在线订单明细' : '点击隐藏其他在线订单明细'}}</span> -->
                  <el-table class="list-table" :data="otherOnlineOrderData" style="width: 100%;" border
                    v-show="!otherOrderIsFold" :max-height="500">
                    <el-table-column type="index" label="序号" width="55" align="center"></el-table-column>
                    <el-table-column prop="Factory" label="工厂" width="75" align="center" :formatter="formatterFactory">
                    </el-table-column>
                    <el-table-column prop="OrderNo" label="订单号" width="75" align="center">
                      <template slot-scope="scope">
                        <span class="table-column-link" @click="viewMoOrderDetail(scope.row.OrderNo)"
                          title="点击查看订单详情">{{
                            scope.row.OrderNo }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column prop="FaliaoDate" label="物料发料日期" width="100" align="center"
                      :formatter="base.formatterDate">
                    </el-table-column>
                    <el-table-column prop="ProductName" label="机型" width="165" align="center"></el-table-column>
                    <el-table-column prop="Qty" label="订单数量" width="width" align="center" :formatter="formatterQty">
                    </el-table-column>
                    <el-table-column prop="TotalinQty" label="已入库数量" width="85" align="center"
                      :formatter="formatterQty">
                    </el-table-column>
                    <el-table-column prop="IssuedQty" label="规划用量" width="width" align="center"
                      :formatter="formatterQty">
                    </el-table-column>
                    <el-table-column prop="IssQty" label="发料数量(含超领)" width="80" align="center" :formatter="formatterQty">
                    </el-table-column>
                    <el-table-column prop="ReturnType" label="处理方式" width="80" align="center">
                      <template slot-scope="scope">
                        <div>
                          {{ scope.row.ReturnType == 1 ? '就地销毁' : scope.row.ReturnType == 2 ? '退回仓库' :
                            scope.row.ReturnType
                              == 3 ? '继续使用' : '' }}
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column prop="ReturnQty" label="需退货数量" width="90" align="center" :formatter="formatterQty">
                    </el-table-column>
                    <el-table-column prop="ReceivingQty" label="已收货数量" width="90" align="center"
                      :formatter="formatterQty"></el-table-column>
                  </el-table>
                </td>
              </tr>
            </template>
            <tr>
              <th>CKD机型
                <i :class="CKDOrderIsFold ? 'el-icon-circle-plus-outline' : 'el-icon-remove-outline'" class="fold-icon"
                  @click="CKDOrderIsFold = !CKDOrderIsFold"
                  :title="CKDOrderIsFold ? '点击展开CKD机型订单明细' : '点击隐藏CKD机型订单明细'"></i>
              </th>
              <td colspan="5">
                <!-- <span class="table-column-link" style="text-decoration: none;"
                  @click="CKDOrderIsFold = !CKDOrderIsFold">{{CKDOrderIsFold ? '点击展开CKD机型订单明细' : '点击隐藏CKD机型订单明细'}}</span> -->
                <el-table class="list-table" :data="CKDOrderData" style="width: 100%;" border v-show="!CKDOrderIsFold"
                  :max-height="500">
                  <el-table-column type="index" label="序号" width="55" align="center"></el-table-column>
                  <el-table-column prop="PO" label="PO" width="" align="center"></el-table-column>
                  <el-table-column prop="Invoice" label="Invoice" width="160" align="center"></el-table-column>
                  <el-table-column prop="IssuedQty" label="发料数量" width="120" align="center" :formatter="formatterQty">
                  </el-table-column>
                  <el-table-column prop="PickupDate" label="提货日期" width="130" align="center"
                    :formatter="base.formatterDate">
                  </el-table-column>
                  <el-table-column prop="ReturnType" label="处理方式" width="120" align="center">
                    <template slot-scope="scope">
                      <div>
                        {{ scope.row.ReturnType == 1 ? '就地销毁' : scope.row.ReturnType == 2 ? '退回仓库' :
                          scope.row.ReturnType== 3 ? '继续使用' :scope.row.ReturnType== 4 ? '待SQE确认' : '' }}
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column prop="ReturnQty" label="需退货数量" width="120" align="center" :formatter="formatterQty">
                  </el-table-column>
                  <el-table-column prop="ReceivingQty" label="已收货数量" width="120" align="center"
                    :formatter="formatterQty"></el-table-column>
                </el-table>
              </td>
            </tr>
            <tr v-if="detailData.OReturnOrderNo">
              <th>在线退货单号</th>
              <td colspan="5" class="td-left"> {{ detailData.OReturnOrderNo }}</td>
            </tr>
            <tr v-if="detailData.SReturnOrderNo">
              <th>在库退货单号</th>
              <td colspan="5" class="td-left">{{ detailData.SReturnOrderNo }}</td>
            </tr>
            <template v-if="confirmReturnIndex || saveReturnIndex">
              <template v-if="confirmReturnIndex">
                <tr v-if="StepLogs[confirmReturnIndex].Opinon">
                  <th>备注</th>
                  <td colspan="5" v-html="StepLogs[confirmReturnIndex].Opinon"></td>
                </tr>
              </template>
              <template v-else>
                <tr v-if="StepLogs[saveReturnIndex].Opinon">
                  <th>备注</th>
                  <td colspan="5" v-html="StepLogs[saveReturnIndex].Opinon">
                  </td>
                </tr>
              </template>
            </template>

          </template>

          <template v-if="StepIdArr.includes(10) && detailData.Status > 8">
            <tr>
              <th colspan="6">SQE跟进</th>
            </tr>
            <tr>
              <th>处理人</th>
              <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(10)].AddUserStr }}
                <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(10)].AddDate).toJSON() }}</span>
              </td>
            </tr>
            <tr>
              <th>SQE跟进结果</th>
              <td colspan="5" v-html="StepLogs[StepIdArr.lastIndexOf(10)].Opinon"></td>
            </tr>
            <!-- SQE跟进步骤 5Why（物料问题3） -->
            <process-five-why-analysis
              :problem-id="problemId"
              :step-log-id="StepLogs[StepIdArr.lastIndexOf(10)].ID"
              :status="detailData.Status"
              :list="detailData.FiveWhyList || []"
              :is-detail-page="true"
              @refresh="getProblemDetail" />
            <tr v-if="detailData.ReasonClass">
              <th>原因分类</th>
              <td colspan="5" v-html="base.formatterBr(detailData.ReasonClass)"></td>
            </tr>
            <tr v-if="detailData.ReasonClassRemark">
              <th>原因说明</th>
              <td colspan="5" v-html="base.formatterBr(detailData.ReasonClassRemark)"></td>
            </tr>
            <tr>
              <th>是否设计更改</th>
              <td :colspan="StepLogs[StepIdArr.lastIndexOf(10)].Result == 1 ? '1' : '5'">
                {{ StepLogs[StepIdArr.lastIndexOf(10)].Result == 1 ? '需要' : '不需要' }}</td>
              <template v-if="StepLogs[StepIdArr.lastIndexOf(10)].Result == 1">
                <th>责任人</th>
                <td colspan="3">{{ detailData.DesignUserName }}</td>
              </template>
            </tr>
            <tr v-if="detailData.StepLogs[StepIdArr.lastIndexOf(10)].File.length > 0">
              <th>附件</th>
              <td colspan="5">
                <template v-for="item in detailData.StepLogs[StepIdArr.lastIndexOf(10)].File">
                  <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                    style="margin-right:15px;">{{ item.Key }}</a>
                </template>
              </td>
            </tr>
          </template>

          <template v-if="StepIdArr.includes(11) && detailData.Status > 9">
            <tr>
              <th colspan="6">设计更改</th>
            </tr>
            <tr>
              <th>处理人</th>
              <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(11)].AddUserStr }}
                <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(11)].AddDate).toJSON() }}</span>
              </td>
            </tr>
            <tr>
              <th>确认结果</th>
              <!-- 取DesignConfirmResult 或者  流程表里的result都可StepLogs[StepIdArr.lastIndexOf(11)].Result -->
              <td :colspan="detailData.DesignConfirmResult != 1 ? '5' : ''">
                {{ detailData.DesignConfirmResult == 1 ? '改善' : detailData.DesignConfirmResult == 2 ? '保持现状' : '挂起' }}
              </td>
              <template v-if="detailData.DesignConfirmResult == 1">
                <th>预计完成时间</th>
                <td colspan="3">{{ detailData.DesignDate ? detailData.DesignDate.substr(0, 10) : '' }}</td>
              </template>
            </tr>
            <tr>
              <th>原因说明</th>
              <td colspan="5" v-html="StepLogs[StepIdArr.lastIndexOf(11)].Opinon"></td>
            </tr>
            <tr v-if="detailData.StepLogs[StepIdArr.lastIndexOf(11)].File.length > 0">
              <th>附件</th>
              <td colspan="5">
                <template v-for="item in detailData.StepLogs[StepIdArr.lastIndexOf(11)].File">
                  <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                    style="margin-right:15px;">{{ item.Key }}</a>
                </template>
              </td>
            </tr>
          </template>

          <template v-if="StepIdArr.includes(13) && detailData.Status > 10">
            <tr>
              <th colspan="6">SQE确认</th>
            </tr>
            <tr>
              <th>处理人</th>
              <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(13)].AddUserStr }}
                <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(13)].AddDate).toJSON() }}</span>
              </td>
            </tr>
            <tr>
              <th>SQE意见</th>
              <td colspan="5" v-html="StepLogs[StepIdArr.lastIndexOf(13)].Opinon"></td>
            </tr>
            <tr v-if="detailData.StepLogs[StepIdArr.lastIndexOf(13)].File.length > 0">
              <th>附件</th>
              <td colspan="5">
                <template v-for="item in detailData.StepLogs[StepIdArr.lastIndexOf(13)].File">
                  <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                    style="margin-right:15px;">{{ item.Key }}</a>
                </template>
              </td>
            </tr>
          </template>

        </template>
        <!-- 物料问题 -->


        <!-- 资料问题, 其他问题类别可能也有此项，因为有可能是从资料问题转其他问题类别的 -->
        <template v-if="problemType == 4 && StepIdArr.length > 0 && StepIdArr.includes(4) && detailData.Status > 3">
          <tr>
            <th colspan="6">工程确认</th>
          </tr>
          <tr>
            <th>处理人</th>
            <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(4)].AddUserStr }}
              <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(4)].AddDate).toJSON() }}</span>
            </td>
          </tr>
          <tr>
            <th>确认结果</th>
            <td :colspan="detailData.ZLConfirmResult ? '1' : '5'">{{ detailData.ZLConfirmResult ? '是' : '否' }}</td>
            <th v-if="detailData.ZLConfirmResult">处理结果</th>
            <td v-if="detailData.ZLConfirmResult">
              {{ detailData.DesignConfirmResult | handleTypeFilter }}
            </td>
            <th v-if="detailData.ZLConfirmResult">计划完成时间</th>
            <td v-if="detailData.ZLConfirmResult">
              {{ detailData.RCompleteTime ? detailData.RCompleteTime.substr(0, 10) : '' }}</td>
          </tr>
          <tr v-if="detailData.ZLConfirmResult">
            <th>是否更改版本</th>
            <td colspan="5">{{ detailData.IsChangeOrderV == 1 ? '是' : '否' }}
              <span style="margin-left:20px;" v-if="detailData.IsChangeOrderV">{{ detailData.OrderVersion }}</span>
            </td>
          </tr>
          <tr v-if="detailData.ZLConfirmResult && detailData.Reason">
            <th>原因分析
              <!-- 结案前责任人可以修改 -->
              <i class="el-icon-edit-outline table-column-link" title="修改原因分析"
                style="text-decoration: none;font-size: 16px;" @click="editReasonClick(1)"
                v-if="detailData.Status != 32 && (CurrentUser == StepLogs[StepIdArr.lastIndexOf(4)].AddUser || $store.getters.getUserInfo().isSuperAdmin)"></i>
            </th>
            <td colspan="5">
              <div v-html="base.formatterBr(detailData.Reason)" class="html-style" @click="GoToImg($event)">
              </div>
            </td>
          </tr>
          <!-- 工程确认步骤 5Why（资料问题4） -->
          <process-five-why-analysis
            v-if="detailData.ZLConfirmResult && StepIdArr.includes(4)"
            :problem-id="problemId"
            :step-log-id="StepLogs[StepIdArr.lastIndexOf(4)].ID"
            :status="detailData.Status"
            :list="detailData.FiveWhyList || []"
            :is-detail-page="true"
            @refresh="getProblemDetail" />
          <tr v-if="detailData.ZLConfirmResult && detailData.Measures">
            <th>改善措施
              <!-- 结案前责任人可以修改 -->
              <i class="el-icon-edit-outline table-column-link" title="修改改善措施"
                style="text-decoration: none;font-size: 16px;" @click="editReasonClick(2)"
                v-if="detailData.Status != 32 && (CurrentUser == StepLogs[StepIdArr.lastIndexOf(4)].AddUser || $store.getters.getUserInfo().isSuperAdmin)"></i>
            </th>
            <td colspan="5">
              <div v-html="base.formatterBr(detailData.Measures)" class="html-style" @click="GoToImg($event)">
              </div>
            </td>
          </tr>
          <tr v-if="detailData.ZLConfirmResult && detailData.Prevention">
            <th>预防对策
              <!-- 结案前责任人可以修改 -->
              <i class="el-icon-edit-outline table-column-link" title="修改预防对策"
                style="text-decoration: none;font-size: 16px;" @click="editReasonClick(3)"
                v-if="detailData.Status != 32 && (CurrentUser == StepLogs[StepIdArr.lastIndexOf(4)].AddUser || $store.getters.getUserInfo().isSuperAdmin)"></i>
            </th>
            <td colspan="5">
              <div v-html="base.formatterBr(detailData.Prevention)" class="html-style" @click="GoToImg($event)">
              </div>
            </td>
          </tr>
          <tr v-if="!detailData.ZLConfirmResult">
            <th>修改的问题分类</th>
            <td colspan="5">{{ detailData.ProblemType | problemTypeFilter }}</td>
          </tr>

          <tr v-if="StepLogs[StepIdArr.lastIndexOf(4)].File.length > 0">
            <th>附件</th>
            <td colspan="5">
              <template v-for="item in detailData.StepLogs[StepIdArr.lastIndexOf(4)].File">
                <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                  style="margin-right:15px;">{{ item.Key }}</a>
              </template>
            </td>
          </tr>
          <tr v-if="StepLogs[StepIdArr.lastIndexOf(4)].Opinon">
            <th>备注</th>
            <td colspan="5" v-html="base.formatterBr(StepLogs[StepIdArr.lastIndexOf(4)].Opinon)"></td>
          </tr>
        </template>
        <!-- 资料问题 -->
        <template v-if="problemType == 4 && StepIdArr.length > 0">
          <template v-if="StepIdArr.includes(5) && detailData.Status > 4">
            <tr>
              <th colspan="6">PMC确认</th>
            </tr>
            <tr>
              <th>处理人</th>
              <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(5)].AddUserStr }}
                <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(5)].AddDate).toJSON() }}</span>
              </td>
            </tr>
            <tr v-if="StepLogs[StepIdArr.lastIndexOf(5)].Opinon">
              <th>备注</th>
              <td colspan="5" v-html="StepLogs[StepIdArr.lastIndexOf(5)].Opinon"></td>
            </tr>
          </template>
        </template>

        <!-- 资料问题 -->

        <!-- 工厂制程 -->
        <template v-if="problemType == 5 && StepIdArr.length > 0 && StepIdArr.includes(6) && detailData.Status > 5">
          <tr>
            <th colspan="6">工厂制程分析</th>
          </tr>
          <tr>
            <th>处理人</th>
            <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(6)].AddUserStr }}
              <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(6)].AddDate).toJSON() }}</span>
            </td>
          </tr>
          <tr>
            <th>原因分析</th>
            <td colspan="5" v-html="StepLogs[StepIdArr.lastIndexOf(6)].Result"></td>
          </tr>
          <!-- 工厂制程分析步骤 5Why（工厂制程5） -->
          <process-five-why-analysis
            :problem-id="problemId"
            :step-log-id="StepLogs[StepIdArr.lastIndexOf(6)].ID"
            :status="detailData.Status"
            :list="detailData.FiveWhyList || []"
            :is-detail-page="true"
            @refresh="getProblemDetail" />
          <tr>
            <th>制定对策</th>
            <td colspan="5" v-html="StepLogs[StepIdArr.lastIndexOf(6)].Opinon"></td>
          </tr>
          <tr v-if="StepLogs[StepIdArr.lastIndexOf(6)].File.length > 0">
            <th>附件</th>
            <td colspan="5">
              <template v-for="item in detailData.StepLogs[StepIdArr.lastIndexOf(6)].File">
                <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                  style="margin-right:15px;">{{ item.Key }}</a>
              </template>
            </td>
          </tr>
        </template>
        <!-- 工厂制程 -->

        <template v-if="[1,2,3,4,6].includes(detailData.ProblemType) && StepIdArr.length > 0 && StepIdArr.includes(35)">
          <tr>
            <th colspan="6">预防对策确认
              <i class="el-icon-edit-outline table-column-link" title="修改预防对策确认"
                style="text-decoration: none;font-size: 16px;" @click="editPreventionConfirmClick()"
                v-if="(CurrentUser == StepLogs[StepIdArr.lastIndexOf(35)].AddUser) || $store.getters.getUserInfo().isSuperAdmin"></i>
            </th>
          </tr>
          <tr>
            <th>处理人</th>
            <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(35)].AddUserStr }}
              <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(35)].AddDate).toJSON() }}</span>
            </td>
          </tr>
          <tr>
            <th>预防对策确认</th>
            <td colspan="5" v-html="base.formatterBr(StepLogs[StepIdArr.lastIndexOf(35)].Opinon)"></td>
          </tr>
          <tr v-if="StepLogs[StepIdArr.lastIndexOf(35)].File && StepLogs[StepIdArr.lastIndexOf(35)].File.length > 0">
            <th>附件</th>
            <td colspan="5">
              <template v-for="item in detailData.StepLogs[StepIdArr.lastIndexOf(35)].File">
                <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                  style="margin-right:15px;">{{ item.Key }}</a>
              </template>
            </td>
          </tr>
        </template>

        <template v-if="StepIdArr.length > 0 && StepIdArr.includes(30) && (detailData.Status == 31 || detailData.Status == 32 || detailData.Status == 37)">
          <tr>
            <th colspan="6">效果确认
              <i class="el-icon-edit-outline table-column-link" title="修改效果确认"
                style="text-decoration: none;font-size: 16px;" @click="editResultConfirmClick()"
                v-if="(CurrentUser == StepLogs[StepIdArr.lastIndexOf(30)].AddUser) || $store.getters.getUserInfo().isSuperAdmin"></i>
            </th>
          </tr>
          <tr>
            <th>处理人</th>
            <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(30)].AddUserStr }}
              <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(30)].AddDate).toJSON() }}</span>
            </td>
          </tr>
          <tr>
            <th>效果确认结果</th>
            <td colspan="5" v-html="StepLogs[StepIdArr.lastIndexOf(30)].Opinon"></td>
          </tr>
          <tr v-if="StepLogs[StepIdArr.lastIndexOf(30)].File.length > 0">
            <th>附件</th>
            <td colspan="5">
              <template v-for="item in detailData.StepLogs[StepIdArr.lastIndexOf(30)].File">
                <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                  style="margin-right:15px;">{{ item.Key }}</a>
              </template>
            </td>
          </tr>
        </template>

        <!-- 工厂制程没有结案确认(problemType != 5), 后续需求改为工厂制程也有结案确认由程玉兰负责 -->
        <template v-if="StepIdArr.length > 0 && StepIdArr.includes(31) && detailData.Status == 32">
          <tr>
            <th colspan="6">结案确认</th>
          </tr>
          <tr>
            <th>处理人</th>
            <td colspan="5">{{ StepLogs[StepIdArr.lastIndexOf(31)].AddUserStr }}
              <span class="add-date-span">{{ new Date(StepLogs[StepIdArr.lastIndexOf(31)].AddDate).toJSON() }}</span>
            </td>
          </tr>
          <tr>
            <th>结案结论
              <!-- 已完成的制程单仅限处理人(有权限的)可编辑 -->
              <i class="el-icon-edit-outline table-column-link" title="修改结案结论"
                style="text-decoration: none;font-size: 16px;" @click="editReasonClick(4)"
                v-if="(CurrentUser == StepLogs[StepIdArr.lastIndexOf(31)].AddUser) || $store.getters.getUserInfo().isSuperAdmin"></i>
            </th>
            <td colspan="5">
              <div v-html="base.formatterBr(StepLogs[StepIdArr.lastIndexOf(31)].Opinon)"
                v-if="StepLogs[StepIdArr.lastIndexOf(31)].Opinon"></div>
            </td>
          </tr>
          <tr v-if="StepLogs[StepIdArr.lastIndexOf(31)].File.length > 0">
            <th>附件</th>
            <td colspan="5">
              <template v-for="item in detailData.StepLogs[StepIdArr.lastIndexOf(31)].File">
                <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                  style="margin-right:15px;">{{ item.Key }}</a>
              </template>
            </td>
          </tr>
        </template>
      </table>
    </div>
    <step-log ref="StepLog"></step-log>

    <!-- 修改原因分析 -->
    <el-dialog
      :title="editReasonType == 1 ? '责任人修改原因分析' : editReasonType == 2 ? '责任人修改改善措施' : editReasonType == 3 ? '责任人修改预防对策' : '修改结案结论'"
      :visible.sync="dialogVisible" width="1000px" :close-on-click-modal="false" @close="closeDialog" top="30px">
      <div style="margin-top:-20px;">
        <table class="tableModel" v-if="editReasonType">
          <tr>
            <th class="required-th" style="width:110px;">{{ editReasonType == 1 ? '原因分析' : editReasonType == 2 ? '改善措施'
              : editReasonType == 3 ? '预防对策' : '结案结论' }}</th>
            <td>
              <template v-if="editReasonType == 4">
                <el-input type="textarea" :autosize="{ minRows: 5, maxRows: 10 }" v-model="editReasonVal"
                  placeholder="请输入" clearable maxlength="525"></el-input>
              </template>
              <template v-else>
                <tinymce id="myedit" ref="editor" v-model="editReasonVal" :initEditor="initEditor" />
              </template>
            </td>
          </tr>
        </table>
      </div>
      <div slot="footer" class="dialog-action-bd" style="margin-top:0;">
        <el-button @click="dialogVisible = false" size="small">取消</el-button>
        <el-button type="primary" @click="editReasonConfirm" size="small">确定</el-button>
      </div>
    </el-dialog>
    <!-- 修改效果确认 -->
    <el-dialog title="修改效果确认" :visible.sync="resultConfirm.resultConfirmVisible" width="1000px"
      :close-on-click-modal="false" top="30px">
      <div style="margin-top: -20px;">
        <table class="tableModel">
          <tr>
            <th class="required-th" style="width: 120px;">效果确认结果</th>
            <td>
              <el-input type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" v-model="resultConfirm.confirmation"
                placeholder="请输入" clearable maxlength="525"></el-input>
            </td>
          </tr>
          <tr>
            <th style="width: 120px;">附件</th>
            <td>
              <el-upload class="upload-switch-bd" multiple :action="uploadUrl" ref="UploadFile" :auto-upload="false"
                :headers="resultConfirm.importHeaders" :file-list="resultConfirm.fileList" :on-remove="fileRemove"
                :before-remove="beforeRemove" :on-change="FileChange" style="display:flex;">
                <span class="table-column-link" style="text-decoration: none;margin-bottom:0px;"><i
                    class="el-icon-upload"></i>上传附件</span>
              </el-upload>
            </td>
          </tr>
        </table>
      </div>
      <div slot="footer" class="dialog-action-bd" style="margin-top:0;">
        <el-button @click="resultConfirm.resultConfirmVisible = false" size="small">取消</el-button>
        <el-button type="primary" @click="editResultConfirm" size="small">确定</el-button>
      </div>
    </el-dialog>
    <!-- 修改预防对策确认 -->
    <el-dialog title="修改预防对策确认" :visible.sync="preventionEdit.visible" width="1000px"
      :close-on-click-modal="false" top="30px">
      <div style="margin-top: -20px;">
        <table class="tableModel">
          <tr>
            <th class="required-th" style="width: 140px;">预防对策确认</th>
            <td>
              <el-input type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" v-model="preventionEdit.opinon"
                placeholder="请输入" clearable maxlength="2000"></el-input>
            </td>
          </tr>
          <tr>
            <th style="width: 140px;">附件</th>
            <td>
              <el-upload class="upload-switch-bd" multiple :action="uploadUrl" ref="PreventionUploadFile" :auto-upload="false"
                :headers="preventionEdit.importHeaders" :file-list="preventionEdit.fileList"
                :on-remove="preventionFileRemove" :before-remove="beforeRemove"
                :on-change="preventionFileChange" style="display:flex;">
                <span class="table-column-link" style="text-decoration: none;margin-bottom:0px;"><i
                    class="el-icon-upload"></i>上传附件</span>
              </el-upload>
            </td>
          </tr>
        </table>
      </div>
      <div slot="footer" class="dialog-action-bd" style="margin-top:0;">
        <el-button @click="preventionEdit.visible = false" size="small">取消</el-button>
        <el-button type="primary" @click="editPreventionConfirm" size="small">确定</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import {
  statusArr,
  problemList,
  factoryArr,
  getParallelStatusLabels
} from "./problem.js";
import globalFun from '@/global/globalFun';
import StepLog from '@/views/QualityManage/ProcessProblem/StepLog.vue'
import OrderIQCOpinion from '@/views/QualityManage/ProcessProblem/OrderIQCOpinion.vue'
import tinymce from "@/components/tinymce.vue";
import ProcessFiveWhyAnalysis from '@/views/QualityManage/ProcessProblem/ProcessFiveWhyAnalysis.vue';
export default {
  name: 'QualityManage_ProblemDetail',

  data() {
    return {
      XBOrdersIsFold: false, //true 隐藏  false 展开
      editReasonVal: "",
      editReasonType: "",
      initEditor: {
        height: 600,
        images_upload_handler: this.upload, // 上传图片
      },
      dialogVisible: false, //修改原因分析
      CurrentUser: this.$store.getters.getUserInfo().id, //用于判断审核人的操作权限
      produceOrderIsFold: false, //true 隐藏  false 展开
      otherOrderIsFold: false, //true 隐藏  false 展开
      CKDOrderIsFold: false, //true 隐藏  false 展开
      produceOrderList: [],
      problemType: "",
      problemId: "",
      detailData: {},
      StepLogs: [],
      StepIdArr: [],
      onlineQtySum: "",
      onlineReturnType: "",
      stockQtySum: "",
      onlineReturnType: "",
      onlineOrderData: [],
      stockOrderData: [],
      otherOnlineOrderData: [],
      RiskInfo: {},
      RiskOrderList: [],
      RiskStreamLogList: [],
      CKDOrderData: [],
      saveReturnIndex: null, //保存退货单号在流程日志的索引
      confirmReturnIndex: null, //确认退货单号在流程日志的索引
      LevelRemark: "",

      hasCheckedPhenomenonArr: [],  //已选问题现象
      reasonList: [], //可能问题原因
      aboutMaterialList: [],//可能问题物料      
      uploadUrl: `${this.$store.state.system.appsettings.apiUrl}api/Upload/ProblemFileDocUpload`,
      resultConfirm: { //效果确认
        resultConfirmVisible: false,
        confirmation: '',
        fileList: [],
        importHeaders: {
          Authorization: this.$store.getters.getToken()
        },
      },
      preventionEdit: {
        visible: false,
        opinon: '',
        fileList: [],
        importHeaders: {
          Authorization: this.$store.getters.getToken()
        },
      }
    }
  },

  watch: {},

  components: {
    StepLog,
    OrderIQCOpinion,
    tinymce,
    ProcessFiveWhyAnalysis
  },

  filters: {
    problemTypeFilter(val) {
      let item = problemList.find(elem => elem.id == val);
      return item ? item.label : '';
    },
    OutPutStatusFilter(val) {
      let str = '';
      switch (val) {
        case 5:
          str = '首次量产'; break;
        case 6:
          str = '首次量产爬坡'; break;
        case 7:
          str = '正常量产'; break;
        case 8:
          str = '正常量产爬坡'; break;
        case 9:
          str = '未释放PN生产'; break;
        case 194:
          str = '原型机试产'; break;
        case 197:
          str = '工程机试产'; break;
        case 196:
          str = '小批量试产'; break;
        case 195:
          str = '物料试产'; break;
        default:
          str = ''; break;
      }
      return str;
    },
    StatusFilter(val) {
      let item = statusArr.find(elem => elem.id == val);
      return item ? item.label : '';
    },

    handleTypeFilter(val) {
      // 1改善，2保持现状,3挂起
      if (val == 1) {
        return "改善";
      } else if (val == 2) {
        return "保持现状";
      } else if (val == 3) {
        return "挂起";
      } else {
        return "";
      }
    },
  },

  computed: {
    parallelStatusLabels() {
      return getParallelStatusLabels(this.detailData.Status, this.detailData.ProblemType);
    },
    //库存合计数量
    stockTotalSum() {
      let total = 0;
      this.stockOrderData.forEach(elem => {
        total = this.base.numberAction.accAdd(total, elem.Qty);
      })
      return total == 0 ? '' : total;
    },
    //在线合计数量
    onlineTotalSum() {
      let total = 0;
      this.onlineOrderData.forEach(elem => {
        total = this.base.numberAction.accAdd(total, elem.Qty);
      })
      return total == 0 ? '' : total;
    },
  },

  created() {
    this.problemId = this.$route.query.id;
    this.getProblemDetail();
    this.GetGetUrgencyRemark();
    this.getRiskOrderDetail();
  },

  mounted() { },

  methods: {
    // 跳转订单详情
    viewMoOrderDetail(orderNumber) {
      globalFun.viewPageInNewTab("/MoOrder/MoOrderDetail", {
        no: orderNumber
      })
    },
    formatterQty(row, column, cellValue, index) {
      if (!cellValue) return "";
      return this.$numeral(cellValue).format('0,0');
    },
    formatterFactory(row, column, cellValue, index) {
      if (!cellValue) return "";
      let item = factoryArr.find(elem => elem.code == cellValue);
      return item ? item.label : "";
    },
    getShowRate(rate) {
      //   超过1 % 用百分号显示 百分位两位小数
      //   低于1 % 用千分号显示 千分位四位小数
      //   不能显示成百分之0 .100 要显示成0 .1 %
      if (rate) {
        let tempRate = "",
          showRate = "";
        tempRate = this.base.numberAction.accDiv(this.detailData.BadQty, this.detailData.ProdQty) * 100; //百分号
        if (tempRate >= 1) {
          showRate = Number(tempRate.toFixed(2)) ? Number(tempRate.toFixed(2)) + '%' : '';
        } else {
          // showRate = rate ? rate + '‰' : '';
          let initRate = Number((this.base.numberAction.accDiv(this.detailData.BadQty, this.detailData.ProdQty) * 1000).toFixed(4));
          showRate = initRate ? initRate + '‰' : '';
        }
        return showRate;
      } else {
        return "";
      }
    },
    viewVersionDetail(versionId) {
      globalFun.viewVersionDetail(versionId);
    },
    /* 查看总的流程操作记录 */
    viewStepLogs() {
      let schemeAddUser = this.StepLogs[this.StepIdArr.lastIndexOf(34)] ? this.StepLogs[this.StepIdArr.lastIndexOf(34)].AddUser : this.detailData.ReStartSchemeUser;
      this.$refs.StepLog.show(true, this.StepLogs, this.detailData, schemeAddUser, this.RiskStreamLogList);
    },
    closeDialog() {
      this.editReasonVal = "";
      this.editReasonType = "";
    },
    //硬件问题、软件问题责任人确认原因分析 
    editReasonClick(type) {
      this.dialogVisible = true;
      this.editReasonType = type;
      // 1修改原因分析 2修改改善措施 3修改预防对策 4修改结案结论
      if (type == 1) {
        this.editReasonVal = this.detailData.Reason ? this.detailData.Reason.replace(/\n/g, "<br/>") : '';
      } else if (type == 2) {
        this.editReasonVal = this.detailData.Measures ? this.detailData.Measures.replace(/\n/g, "<br/>") : '';
      } else if (type == 3) {
        this.editReasonVal = this.detailData.Prevention ? this.detailData.Prevention.replace(/\n/g, "<br/>") : '';
      } else if (type == 4) {
        let tempObj = this.StepLogs[this.StepIdArr.lastIndexOf(31)];
        this.editReasonVal = tempObj && tempObj.Opinon ? tempObj.Opinon.replace(/<br\/>/g, "\n") : '';
      } else if (type == 5) {
        this.editReasonVal = this.detailData.ProblemDesc ? this.detailData.ProblemDesc.replace(/\n/g, "<br/>") : '';
      }
    },
    //跳转图片
    GoToImg($event) {
      if ($event.target.nodeName.toLowerCase() == 'img') {
        window.open($event.target.currentSrc, '_blank');
      }
    },

    editReasonConfirm() {
      if (!this.editReasonVal || this.editReasonVal.trim().length == 0) {
        let message = '';
        if (this.editReasonType == 1) {
          message = "请输入原因分析！";
          apiUrl = "/api/ZCTracking/EditReason";
        } else if (this.editReasonType == 2) {
          message = "请输入改善措施！";
          apiUrl = "/api/ZCTracking/EditMeasures";
        } else if (this.editReasonType == 3) {
          message = "请输入预防对策！";
          apiUrl = "/api/ZCTracking/EditPrevention";
        } else if (this.editReasonType == 4) {
          message = "请输入结案结论！";
          apiUrl = "/api/ZCTracking/EditEndConfirmDesc";
        } else if (this.editReasonType == 5) {
          message = "请输入问题描述！";
          apiUrl = "/api/ZCTracking/EditProblemDesc";
        }
        this.$message.error(message);
        return;
      }
      let apiUrl = "";
      // 1修改原因分析 2修改改善措施 3修改预防对策
      if (this.editReasonType == 1) {
        apiUrl = "/api/ZCTracking/EditReason";
      } else if (this.editReasonType == 2) {
        apiUrl = "/api/ZCTracking/EditMeasures";
      } else if (this.editReasonType == 3) {
        apiUrl = "/api/ZCTracking/EditPrevention";
      } else if (this.editReasonType == 4) {
        apiUrl = "/api/ZCTracking/EditEndConfirmDesc";
      } else if (this.editReasonType == 5) {
        apiUrl = "/api/ZCTracking/EditProblemDesc";
      }
      this.http.post(apiUrl, {
        ProblemId: this.problemId,
        Reason: this.editReasonVal.trim()
      }, "加载中...").then(res => {
        this.$message({
          type: res.Status ? 'success' : 'error',
          message: res.Message
        })
        if (res.Status) {
          this.getProblemDetail();
          this.dialogVisible = false;
        }
      })
    },


    /* 编辑器上传图片 */
    upload(blobInfo, success, failure, progress) {
      let formData = new FormData();
      formData.append("file", blobInfo.blob(), blobInfo.filename());
      this.http.post("/api/Upload/ProblemFileUpload", formData).then(res => {
        if (res.Status) {
          success(res.Data);
        } else {
          failure(res.Message);
        }
      });
    },
    /* 涉及的生产订单合计行 */
    getSummaries(param) {
      const {
        columns,
        data
      } = param;
      const sums = [];
      columns.forEach((column, index) => {
        if (index === 0) {
          sums[index] = '合计'
          return
        }
        if (column.property === 'OrderQty' || column.property === 'ReceiptQty' || column.property ===
          'OnlineQty') {
          const values = data.map(item => Number(item[column.property]));
          if (!values.every(value => isNaN(value))) {
            let sum = values.reduce((prev, curr) => {
              const value = Number(curr)
              if (!isNaN(value)) {
                return this.base.numberAction.accAdd(prev, curr);
              } else {
                return prev;
              }
            }, 0)
            // this.base.splitKOfMoney()
            sums[index] = this.$numeral(sum).format('0,0');
          } else {
            sums[index] = ''
          }
        } else {
          sums[index] = ''
        }
      })
      /* 合计行合并 */
      setTimeout(() => {
        const tds = document.querySelectorAll('#produce-table .el-table__footer-wrapper tr>td');
        tds[0].style.textAlign = 'center';
        tds[0].colSpan = 5;
        tds[1].style.display = 'none';
        tds[2].style.display = 'none';
        tds[3].style.display = 'none';
        tds[4].style.display = 'none';
      }, 50)

      return sums;
    },

    getXBOrderSummaries(param) {
      const {
        columns,
        data
      } = param;
      const sums = [];
      columns.forEach((column, index) => {
        if (index === 0) {
          sums[index] = '合计'
          return
        }
        if (column.property === 'Qty' || column.property === 'InQty' || column.property ===
          'NoQty') {
          const values = data.map(item => Number(item[column.property]));
          if (!values.every(value => isNaN(value))) {
            let sum = values.reduce((prev, curr) => {
              const value = Number(curr)
              if (!isNaN(value)) {
                return this.base.numberAction.accAdd(prev, curr);
              } else {
                return prev;
              }
            }, 0)
            // this.base.splitKOfMoney()
            sums[index] = this.$numeral(sum).format('0,0');
          } else {
            sums[index] = ''
          }
        } else {
          sums[index] = ''
        }
      })
      /* 合计行合并 */
      setTimeout(() => {
        const tds = document.querySelectorAll('#xbOrder-table .el-table__footer-wrapper tr>td');
        tds[0].style.textAlign = 'center';
        tds[0].colSpan = 5;
        tds[1].style.display = 'none';
        tds[2].style.display = 'none';
        tds[3].style.display = 'none';
        tds[4].style.display = 'none';
      }, 50)

      return sums;
    },


    async getRiskOrderDetail() {
      let res = await this.http.get('/api/ZCTracking/GetRiskDetail', {
        problemId: this.problemId
      }, '加载中');
      if (res.Status) {
        this.RiskInfo = res.Data;
        this.RiskOrderList = res.Data.RiskOrderList;
        this.RiskStreamLogList = res.Data.RiskStreamLogList;
      }
    },

    /* 获取问题详情 */
    async getProblemDetail() {
      if (!this.problemId) return;
      let res = await this.http.get('/api/ZCTracking/GetProblemView', {
        problemId: this.problemId
      }, '加载中');
      res.Data.FactoryName = res.Data.Factory == '04' ? '柯洱斯' : res.Data.Factory == '05' ? '亮亮' : '惠州百富';
      res.Data.ProductNameStr = res.Data.ProductNames.map(elem => elem.ProductName).join(',');
      res.Data.ProblemDescObj = globalFun.getImageAndVideoURL(res.Data.ProblemDesc);
      res.Data.ImproveObj = res.Data.Improve ? globalFun.getImageAndVideoURL(res.Data.Improve) : null;
      this.detailData = res.Data;
      this.problemType = res.Data.ProblemType;
      res.Data.StepLogs.forEach(elem => {
        elem.File = elem.File ? elem.File : [];
      });
      this.StepLogs = res.Data.StepLogs ? res.Data.StepLogs : [];
      this.StepIdArr = res.Data.StepLogs.map(elem => elem.Step);
      this.produceOrderList = res.Data.Orders;

      if (this.problemType == 3) {
        let saveIndexArr = [];
        res.Data.StepLogs.forEach((elem, i) => {
          if (elem.StepStr == '保存退货单号') {
            saveIndexArr.push(i);
          }
          if (elem.StepStr == '确认退货单号') {
            this.confirmReturnIndex = i;
          }
        })
        if (saveIndexArr.length > 0) {
          this.saveReturnIndex = saveIndexArr[saveIndexArr.length - 1];
        }
      }

      if (this.problemType == 3 && ((this.StepIdArr.includes(14) && this.detailData.IQCOpinion == 3) || (this
        .StepIdArr.includes(7) || this.StepIdArr.includes(8)))) {
        this.GetIQCOrderList();
      }
      /* 已选问题现象 */
      if (this.detailData && this.detailData.AfterSaleIssueCheckReasonList &&
        this.detailData.AfterSaleIssueCheckReasonList.length > 0) {
        let hasCheckedArr = [];
        let PhenomenonIDArr = Array.from(new Set(this.detailData.AfterSaleIssueCheckReasonList.map(q => q
          .PhenomenonID)));
        PhenomenonIDArr.forEach(q => {
          let item = this.detailData.AfterSaleIssueCheckReasonList.find(k => k.PhenomenonID == q);
          hasCheckedArr.push({
            ...item
          })
        })
        this.hasCheckedPhenomenonArr = hasCheckedArr;  //已选问题现象
        this.reasonList = this.detailData.AfterSaleIssueCheckReasonList.filter(q => q.ReasonDesc); //问题原因
      }
      this.aboutMaterialList = this.detailData && this.detailData.PossibleInvCodeList &&
        this.detailData.PossibleInvCodeList.length > 0 ? this.detailData.PossibleInvCodeList : [];
    },

    /* 获取相关订单列表 */
    async GetIQCOrderList() {
      if (!this.problemId) return;
      let res = await this.http.get("/api/ZCTracking/GetIQCAndFactoryOrderList", {
        problemId: this.problemId,
      }, "正在加载...");
      if (!res.Data) return;
      this.onlineOrderData = res.Data.OnlineOrder ? res.Data.OnlineOrder : []; //在线订单
      this.stockOrderData = res.Data.Stock ? res.Data.Stock : []; //库存
      this.otherOnlineOrderData = res.Data.OtherOrders ? res.Data.OtherOrders : []; //其他在线订单
      this.CKDOrderData = res.Data.CKD ? res.Data.CKD : []; //CKD机型
    },

    //获取等级描述
    async GetGetUrgencyRemark() {
      let res = await this.http.get("/api/AfterService/AfterProblemHanding/GetUrgencyRemark");
      this.LevelRemark = res.Message;
    },

    //修改效果确认
    editResultConfirmClick() {
      this.resultConfirm.resultConfirmVisible = true;
      var stepLog = this.StepLogs[this.StepIdArr.lastIndexOf(30)];
      this.resultConfirm.confirmation = stepLog.Opinon;
      this.resultConfirm.fileList = [];
      stepLog.File.map(e => {
        this.resultConfirm.fileList.push({ name: e.Key, url: e.Value, fileID: e.FileId, stepLogID: stepLog.ID })
      });

    },
    async editResultConfirm() {
      if (this.resultConfirm.confirmation.trim().length == 0) {
        this.$message.error('请填写效果确认结果');
        return;
      }
      this.http.post("/api/ZCTracking/EditResultConfirm", {
        ProblemId: this.problemId,
        Confirmation: this.resultConfirm.confirmation.trim().replace(/\n/g, "<br/>"),
      }, '加载中...').then(res => {
        this.$message({
          type: res.Status ? 'success' : 'error',
          message: res.Status ? '操作成功' : res.Message
        })
        if (res.Status) {
          if (res.Data) {
            setTimeout(() => {
              this.uploadProblemFile(res.Data);
            }, 0)
          }
          this.getProblemDetail();
          this.resultConfirm.resultConfirmVisible = false;
        }
      })
    },
    //删除
    fileRemove(file, fileList) {
      console.log(file, fileList)
      if (file.fileID) {
        this.deleteFileFn(file.stepLogID, file.fileID);
      }

    },
    beforeRemove(file, fileList) {
      return this.$confirm(`确定移除 ${file.name}？`);
    },
    /* 选择文件改变 添加文件、上传成功和上传失败时都会被调用 */
    FileChange(file, fileList) {
      this.resultConfirm.fileList = fileList;
    },
    /* 自定义上传文件（不使用elementUi el-upload组件自带方法） */
    uploadProblemFile(resData) {
      if (this.resultConfirm.fileList.length == 0) {
        return;
      }
      let fileList = this.resultConfirm.fileList.filter(e => !e.fileID);
      if (fileList.length == 0) {
        return;
      }
      const formData = new FormData();
      fileList.forEach(elem => {
        formData.append("files", elem.raw);
      })
      formData.append("Id", resData);
      this.http.uploadFilePost(this.uploadUrl, formData, false).then(res => {
        if (!res.Status) {
          this.$message.error('附件上传失败');
        }
        this.getProblemDetail();
      }).catch(error => {
        this.$message.error('附件上传失败');
      })
    },
    deleteFileFn(logId, fileIds) {
      this.http.get("/api/Upload/ProblemFileDelete", {
        logId: logId,
        fileIds: fileIds,
      }, '删除中...').then(res => {
        this.$message({
          type: res.Status ? 'success' : 'error',
          message: res.Status ? '删除成功！' : res.Message
        })
        if (res.Status) this.getProblemDetail();
        // this.fileList = fileList.filter(elem => elem.FileId != file.FileId);
      })
    },
    editPreventionConfirmClick() {
      this.preventionEdit.visible = true;
      var stepLog = this.StepLogs[this.StepIdArr.lastIndexOf(35)];
      this.preventionEdit.opinon = stepLog.Opinon ? String(stepLog.Opinon).replace(/<br\s*\/?>/gi, '\n') : '';
      this.preventionEdit.fileList = [];
      (stepLog.File || []).map(e => {
        this.preventionEdit.fileList.push({ name: e.Key, url: e.Value, fileID: e.FileId, stepLogID: stepLog.ID })
      });
    },
    async editPreventionConfirm() {
      if (this.preventionEdit.opinon.trim().length == 0) {
        this.$message.error('请填写预防对策确认结果');
        return;
      }
      this.http.post("/api/ZCTracking/EditPreventionConfirm", {
        ProblemId: this.problemId,
        Opinon: this.preventionEdit.opinon.trim().replace(/\n/g, "<br/>"),
      }, '加载中...').then(res => {
        this.$message({
          type: res.Status ? 'success' : 'error',
          message: res.Status ? '操作成功' : res.Message
        })
        if (res.Status) {
          if (res.Data) {
            setTimeout(() => {
              this.uploadPreventionFile(res.Data);
            }, 0)
          }
          this.getProblemDetail();
          this.preventionEdit.visible = false;
        }
      })
    },
    preventionFileRemove(file, fileList) {
      this.preventionEdit.fileList = fileList;
      if (file.fileID) {
        this.deleteFileFn(file.stepLogID, file.fileID);
      }
    },
    preventionFileChange(file, fileList) {
      this.preventionEdit.fileList = fileList;
    },
    uploadPreventionFile(resData) {
      if (this.preventionEdit.fileList.length == 0) {
        return;
      }
      let fileList = this.preventionEdit.fileList.filter(e => !e.fileID);
      if (fileList.length == 0) {
        return;
      }
      const formData = new FormData();
      fileList.forEach(elem => {
        formData.append("files", elem.raw);
      })
      formData.append("Id", resData);
      this.http.uploadFilePost(this.uploadUrl, formData, false).then(res => {
        if (!res.Status) {
          this.$message.error('附件上传失败');
        }
        this.getProblemDetail();
      }).catch(() => {
        this.$message.error('附件上传失败');
      })
    },
  }
}

</script>
<style lang='less' scoped>
.problem-detail-bd {
  width: 1200px;
  margin: 0 auto;
  padding-bottom: 40px;

  .header-bd {
    display: flex;
    align-items: center;
    border-bottom: 1px solid #dcdfe6;

    .header-tips {
      font-size: 16px;
      margin-left: 160px;
    }
  }

  .number-bd {
    text-align: right;
    color: #333;
    font-size: 14px;
    margin-bottom: 5px;

    span {
      text-decoration: underline;
      margin-left: 10px;
    }
  }
}

.tableModel {
  table-layout: fixed;

  >tr>th {
    width: 130px;
    padding: 8px 10px;
  }

  >tr>td {
    text-align: left;
    padding: 8px 10px;
  }
}

.add-date-span {
  margin-left: 20px;
}

.problem-desc-td {
  /deep/ img {
    display: none !important;
  }

  /deep/ span,
  /deep/ div,
  /deep/ p {
    white-space: pre-line;
    word-wrap: break-word;
    word-break: break-all;
  }
}

/deep/ .detail-table td {
  padding: 3px 0;
}

/deep/ .detail-table th {
  padding: 8px 0;
}

.order-table tr td {
  text-align: center;
}

/deep/.list-table td {
  padding: 5px 0;
}


/deep/ .list-table th {
  padding: 8px 0;
  color: #666;
  user-select: auto;
}

/deep/ .list-table .cell {
  padding-left: 5px;
  padding-right: 5px;
}


.fold-icon {
  color: #409EFF;
  font-size: 16px;
  padding: 0 5px 0 0;
  cursor: pointer;
}

/* 将合计行text字体加粗 */
/deep/ #produce-table .el-table__footer-wrapper tbody td {
  color: #333;
  font-weight: 600;
}

.th-icon {
  color: rgb(230, 162, 60);
  font-weight: 600;
  cursor: pointer;
}

/deep/.html-style {
  width: 100%;

  img {
    width: auto;
    max-width: 100%;
    cursor: pointer;
  }
}

/deep/ .el-tag {
  margin: 0 8px 8px 0;
}

.bold-p {
  font-weight: 600;
}

.scroll-bd {
  max-height: 240px;
  overflow-y: auto;

  .scroll-bd-p {
    padding: 3px 0 3px 16px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

}

/deep/ #xbOrder-table .el-table__footer-wrapper tbody td {
  color: #333;
  font-weight: 600;
}

.table-column-link {
  text-decoration: none;
}

/deep/ .el-upload-list__item:first-child {
  margin: 0 0 0 30px;
}

/deep/ .el-upload-list__item {
  margin-left: 30px;
}

/deep/ .el-upload-list__item.is-success.focusing .el-icon-close-tip {
  display: none !important;
}
</style>
