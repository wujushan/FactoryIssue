"""S4 的小件：详情用到的枚举对照与 `2_landed` 一致、剥图（设计 §13）、链接与详情块的选取。"""

from __future__ import annotations

from factory_issue_module import landed
from factory_issue_module.domains import enums
from factory_issue_module.textnorm import RICH_LIMIT, rich_display


def _doc(rel: str) -> str:
    return landed.read(rel)


def test_detail_enums_match_landed():
    """枚举翻成人话的对照（设计 §9.1）：显示文字都出现在对应的 `2_landed` 文件里，防两边漂移。"""
    domestic = _doc("domestic/business_description.md")
    assert all(name in domestic for name in enums.CN_DETAIL_STAGES.values())
    other = _doc("db_description/db_CoreINFO_dbo_ZCTracking_OtherOrder.md")
    assert all(f"{k}={v}" in other for k, v in enums.CN_RETURN_TYPE.items())
    five = _doc("db_description/db_CoreINFO_dbo_ZCTracking_ProblemFiveWhy.md")
    assert all(f"{k}={v}" in five for k, v in enums.CN_FIVE_WHY_STATUS.items())
    steps = _doc("db_description/db_CoreINFO_dbo_ZCTracking_ProblemSteplog.md")
    assert "1 = 同意，0 = 不同意" in steps and "0 = 不需要，1 = 需要" in steps and "0 = 不同意，其余 = 同意" in steps
    assert all(f"| {c} |" in steps for c in (enums.CN_STEP_FILL, enums.CN_STEP_REJECT, *enums.CN_RESTART_STEPS))
    docs = _doc("db_description/db_info_dbo_DocumentList.md")
    assert all(f"'{t}'" in docs for t in (enums.BR_DOC_8D, enums.BR_DOC_CLAIM, enums.BR_DOC_DESIGN))
    overseas = _doc("overseas/business_description.md")
    assert all(s in overseas for s in (enums.OS_STEP_ASSIGN, enums.OS_STEP_CONFIRM, enums.OS_STEP_EFFECT,
                                       enums.OS_STEP_FACTORY, enums.OS_STEP_SQE))


def test_rich_display_strips_inline_images_and_tags():
    raw = ('<p>按键<img src="data:image/png;base64,' + "QUJD" * 500 + '" />手感差&nbsp;&amp;偏软</p>'
           '<p><img src="https://files.test.local/a.png"/></p><br/>第二段&#26469;')
    text, cut = rich_display(raw)
    assert text == "按键手感差 &偏软\n[图片](https://files.test.local/a.png)\n第二段来" and not cut
    assert rich_display(None) == ("", False) and rich_display(float("nan")) == ("", False)
    assert rich_display("<p> </p><p>&nbsp;</p>") == ("", False)  # 只剩空的格式标记
    long_text, cut = rich_display("字" * (RICH_LIMIT + 5))
    assert cut and len(long_text) == RICH_LIMIT
