import {
  MessageBox
} from 'element-ui';

/** 硬件/软件/物料/资料/结构需要预防对策确认 */
export function needPreventionConfirm(problemType) {
  return [1, 2, 3, 4, 6].indexOf(Number(problemType)) !== -1;
}

/**
 * 并行阶段当前状态文案：30 两者未完成，36 仅效果未完成，37 仅预防对策未完成。
 * 非并行节点返回 null。
 */
export function getParallelStatusLabels(status, problemType) {
  const s = Number(status);
  if (s === 36) {
    return ['效果确认'];
  }
  if (s === 37) {
    return ['预防对策确认'];
  }
  if (s === 30) {
    return needPreventionConfirm(problemType)
      ? ['预防对策确认', '效果确认']
      : ['效果确认'];
  }
  return null;
}

/**
 * 并行阶段当前责任人，顺序与 getParallelStatusLabels 一致。
 */
export function getParallelResponsibleNames(row) {
  if (!row) {
    return null;
  }
  const labels = getParallelStatusLabels(row.Status, row.ProblemType);
  if (!labels) {
    return null;
  }
  const effectName = row.MemberListName || '';
  const preventionName = row.PreventionMemberListName || row.preventionMemberListName || '';
  return labels.map(function (label) {
    return label === '预防对策确认' ? preventionName : effectName;
  });
}

/**
 * 列表当前状态与当前责任人共用的节点行（含 IQC、退库），保证一一对应。
 * type: text=并行文案，main/iqc/rs=走 StatusFilter。
 */
export function getCurrentNodeRows(row) {
  if (!row) {
    return [];
  }
  const rows = [];
  const labels = getParallelStatusLabels(row.Status, row.ProblemType);
  if (labels) {
    const names = getParallelResponsibleNames(row) || [];
    labels.forEach(function (label, i) {
      rows.push({ type: 'text', label: label, name: names[i] || '' });
    });
  } else {
    rows.push({ type: 'main', label: '', name: row.MemberListName || '', status: row.Status });
  }
  if (row.IQCStatus) {
    rows.push({ type: 'iqc', label: '', name: row.IQCMemberListName || '', status: row.IQCStatus });
  }
  if (row.RsStep) {
    rows.push({ type: 'rs', label: '', name: row.RsUserNames || '', status: row.RsStep });
  }
  return rows;
}

export const statusArr = [{
    id: "",
    label: "全部",
    path: ""
  },
  {
    id: 1,
    stepId: 2,
    label: "指定责任人",
    path: "/QualityManage/QualityAssignDutyMan"
  },
  {
    id: 2,
    stepId: 3,
    label: "责任人确认",
    path: "/QualityManage/QualityDutyManConfirm"
  },
  {
    id: 3,
    stepId: 4,
    label: "工程确认",
    path: "/QualityManage/ProjectConfirm"
  },
  {
    id: 4,
    stepId: 5,
    label: "PMC确认",
    path: "/QualityManage/PMCConfirm"
  },
  {
    id: 5,
    stepId: 6,
    label: "工厂制程分析",
    path: "/QualityManage/FactoryConfirm"
  },
  {
    id: 11,
    stepId: 14,
    label: "IQC意见",
    path: "/QualityManage/IQCOpinion"
  },
  {
    id: 6,
    stepId: 7, //7是IQC确认  8 工厂填写在线
    label: "IQC确认",
    path: "/QualityManage/IQCConfirm"
  },
  {
    id: 7,
    // stepId: "",  12 保存退货单号    9 确认退货单号  
    label: "填写退货单号",
    path: "/QualityManage/WriteQuitNo"
  },
  {
    id: 8,
    stepId: 10,
    label: "SQE跟进",
    path: "/QualityManage/SQEFollowCheck"
  },
  {
    id: 9,
    stepId: 11,
    label: "设计更改",
    path: "/QualityManage/ChangeDesign"
  },
  {
    id: 10,
    stepId: 13,
    label: "SQE确认",
    path: "/QualityManage/SQEConfirm"
  },
  {
    id: 30,
    stepId: 30,
    label: "效果确认",
    path: "/QualityManage/ResultConfirm"
  },
  {
    id: 36,
    stepId: 30,
    label: "效果确认",
    path: "/QualityManage/ResultConfirm"
  },
  {
    id: 37,
    stepId: 35,
    label: "预防对策确认",
    path: "/QualityManage/PreventionConfirm"
  },
  {
    id: 31,
    stepId: 31,
    label: "结案确认",
    path: "/QualityManage/EndConfirm"
  },
  {
    id: 32,
    stepId: "",
    label: "已完成"
  },
  {
    id: 12,
    stepId: 33,
    label: "生产角色确认",
    path: "/QualityManage/ProduceConfirm"
  },
  {
    id: 13,
    stepId: "",
    label: "生产角色驳回",
    path: ""
  },
  {
    id: 14,
    stepId: "",
    label: "填写退货信息",
    path: "/QualityManage/ConfirmFactoryRiskOrder"
  },
  {
    id: 15,
    stepId: "",
    label: "填写退库信息",
    path: "/QualityManage/FillReturnNoRiskOrder"
  },
]

export const problemList = [{
    id: 1,
    label: "硬件问题",
    desc: "硬件设计问题，结构设计问题除外",
  },
  {
    id: 6,
    label: "结构问题",
    desc: "结构设计问题，如结构设计干涉或结合不良、结构设计防水或防尘不良、开槽不当拆装困难等",
  },
  {
    id: 2,
    label: "软件问题",
    desc: "固件、应用和测试程序等软件设计问题",
  },
  {
    id: 4,
    label: "资料问题",
    desc: "BOM错误、工程改动单错误、版本信息错误等资料问题",
  },
  {
    id: 3,
    label: "物料问题",
    desc: "物料品质问题，与承认书和样品不符",
  },
  {
    id: 7,
    label: "制程优化",
    desc: "精益生产，生产过程中发现通过优化产品设计或生产工艺提高生产效率或降低生产难度等",
  },
  {
    id: 5,
    label: "工厂制程",
    desc: "工厂制程管控不当导致的质量问题",
  }
]
export const factoryArr = [{
    code: "04",
    label: "柯洱斯"
  },
  {
    code: "05",
    label: "亮亮"
  },
  {
    code: "09",
    label: "惠州百富"
  }
]
export function msgAlert(message) {
  MessageBox.alert(message, '提示', {
    type: "error",
    confirmButtonText: '确定',
    dangerouslyUseHTMLString: true
  })
}
