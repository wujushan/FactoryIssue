<!-- 总的操作流程记录 -->
<template>
  <div>
    <el-dialog :title="'操作记录 -- ' + Numbers" :visible.sync="logDialogVisible" width="1350px"
      :close-on-click-modal="false" top="40px">
      <div style="margin-top:-20px;">
        <el-table class="list-table" :data="StepLogs" style="width: 100%" border
          :max-height="base.getTableHeight() - 17">
          <el-table-column prop="AddUserStr" label="操作人" width="90" align="center"></el-table-column>
          <el-table-column prop="AddDate" label="操作时间" width="165" align="center" :formatter="base.formatterTime">
          </el-table-column>
          <el-table-column prop="StepStr" label="类型" width="145" align="center"></el-table-column>
          <el-table-column prop="Measures" label="内容" width="width" align="left" header-align="center">
            <template slot-scope="scope">
              <div v-html="scope.row.Measures"></div>
            </template>
          </el-table-column>
          <el-table-column prop="" label="附件" width="200" align="center">
            <template slot-scope="scope">
              <template v-for="item in scope.row.File">
                <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                  style="margin-right:15px;">{{ item.Key }}</a>
              </template>
            </template>
          </el-table-column>
        </el-table>


        <!-- StopStatus 1停线中，2已经重启，3没有停线，4重启审核，5审核通过  6责任人填写重启方案 -->
        <div style="margin-top: 40px;"
          v-if="detailData.StopStatus == 4 ? (CurrentUser == detailData.ReStartExamineUser || CurrentUser == schemeAddUser || $store.getters.getUserInfo().isSuperAdmin) : true">
          <el-divider content-position="left">重启操作日志</el-divider>
          <el-table class="list-table" :data="restartLogData" style="width: 100%" border
            :max-height="base.getTableHeight() - 17">
            <el-table-column prop="AddUserStr" label="操作人" width="90" align="center"></el-table-column>
            <el-table-column prop="AddDate" label="操作时间" width="165" align="center" :formatter="base.formatterTime">
            </el-table-column>
            <el-table-column prop="StepStr" label="类型" width="145" align="center"></el-table-column>
            <el-table-column prop="Measures" label="内容" width="width" align="left" header-align="center">
              <template slot-scope="scope">
                <div v-html="scope.row.Measures" v-if="scope.row.Measures"></div>
                <div v-else v-html="scope.row.Opinon"></div>
              </template>
            </el-table-column>
            <!-- <el-table-column prop="" label="附件" width="200" align="center">
            <template slot-scope="scope">
              <template v-for="item in scope.row.File">
                <a :href="item.Value" title="点击预览文件" rel="noopener noreferrer" target="_blank" :key="item.Key"
                  style="margin-right:15px;">{{ item.Key }}</a>
              </template>
            </template>
          </el-table-column> -->
          </el-table>
        </div>

        <div style="margin-top: 40px;">
          <el-divider content-position="left">风险订单操作日志</el-divider>
          <el-table class="list-table" :data="riskStreamLogList" style="width: 100%" border
            :max-height="base.getTableHeight() - 17">
            <el-table-column prop="AddUserName" label="操作人" width="90" align="center"></el-table-column>
            <el-table-column prop="AddDate" label="操作时间" width="165" align="center" :formatter="base.formatterTime">
            </el-table-column>
            <el-table-column prop="Step" label="类型" width="145" align="center">
              <template slot-scope="scope">
                <div>{{ scope.row.Step | stepFilter }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="Remark" label="内容" width="width" align="left" header-align="center">
            </el-table-column>
          </el-table>
        </div>

      </div>
      <div slot="footer" class="dialog-action-bd" style="margin-top:-20px;">
        <el-button @click="logDialogVisible = false" size="small">关闭</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import { filter } from 'lodash';

export default {
  name: 'QualityManage_StepLog',

  data() {
    return {
      CurrentUser: this.$store.getters.getUserInfo().id, //当前登录人
      logDialogVisible: false,
      StepLogs: [],
      Numbers: "",
      restartLogData: [],
      detailData: {},
      schemeAddUser: "",
      riskStreamLogList: [],
    }
  },

  filters: {
    stepFilter(step) {
      if (step == 35) {
        return '新增风险订单';
      } else if (step == 36) {
        return '填写退货信息';
      } else if (step == 37) {
        return '填写退库信息';
      } else if (step == 38) {
        return '修改风险订单';
      }
    },
  },
  watch: {},

  components: {},

  computed: {},

  created() { },

  mounted() { },

  methods: {
    show(isShow, StepLogs, detailData, schemeAddUser, riskStreamLogList) {
      this.logDialogVisible = isShow;
      // this.StepLogs = StepLogs;
      // StepId29 重启操作  34责任人填写重启方案 32上级领导重启审核
      this.StepLogs = StepLogs.filter(elem => elem.Step != 29 && elem.Step != 34 && elem.Step != 32);
      this.restartLogData = StepLogs.filter(elem => elem.Step == 29 || elem.Step == 34 || elem.Step == 32);
      this.Numbers = detailData.Numbers;
      this.detailData = detailData;
      this.schemeAddUser = schemeAddUser;
      this.riskStreamLogList = riskStreamLogList;
      console.log(this.riskStreamLogList);
    },
  }
}

</script>
<style lang='less' scoped>
/deep/ .el-divider__text {
  color: #409eff;
}

/deep/ .el-divider {
  background-color: #409eff;
}
</style>
