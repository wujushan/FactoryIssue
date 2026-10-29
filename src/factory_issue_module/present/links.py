"""链接（设计 §9.1；`link_rules.md`）。S2 接上国内、海外的制程单链接；巴西加密链接随 S3，附件、CAR 报告随 S4。

- 站点地址是本环境的 INFO 站点，测试环境与正式环境不同，放在模块配置 `link_sites.toml`（管理员在 Console
  上传，`config/files.py::LinkSites`），由调用方每轮读一次传进来；没传时不生成链接，问题编号照常给出文字。
- 链接参数里的 ID 是内部主键，只出现在 URL 里，可点击文字用问题编号。
"""

from __future__ import annotations

from typing import Any

from factory_issue_module.config.files import LinkSites
from factory_issue_module.declarations import Domain

_PATHS = {
    Domain.DOMESTIC: "/#/QualityManage/ProblemDetail?id=",
    Domain.OVERSEAS: "/#/QualityManage/OverseasProblemAllDetail?id=",
}


def issue(sites: LinkSites | None, domain: Any, number: Any, pid: Any) -> str:
    """问题编号 → Markdown 链接；站点地址没配、域还没接上或没有 ID 时只给编号文字。"""
    text = str(number)
    base = sites.issue if sites is not None else None
    path = _PATHS.get(domain)
    if not base or path is None or pid is None:
        return text
    return f"[{text}]({base}{path}{int(pid)})"
