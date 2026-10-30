"""链接（设计 §9.1；`link_rules.md`）。国内、海外的制程单链接 S2；巴西加密链接 S3；附件、CAR 报告 S4。

- CAR 报告链接对所有用户生成（不看本助手的 CAR 报告权限），可点击文字是 CAR 编号；附件预览链接要摘要，摘要要的
  那一项值在另一个私有模块里，还没有值或出错时只给文档名称，异常只记类型。

- 站点地址是本环境的 INFO 站点，测试环境与正式环境不同，放在模块配置 `link_sites.toml`（管理员在 Console
  上传，`config/files.py::LinkSites`），由调用方每轮读一次传进来；没传时不生成链接，问题编号照常给出文字。
- 链接参数里的 ID 是内部主键，只出现在 URL 里，可点击文字用问题编号。
- 巴西链接的两个参数照 `link_rules.md` 巴西参数那一节：原文 UTF-8，分组链接、PKCS7 补齐，结果转大写十六进制，
  拼进地址时不做 URL 编码。要用的两项值在一个私有模块里（§9.1 的放法）；还没有值、或出错时只给编号文字，
  异常只记类型，不进日志、事件与异常文本。
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import structlog

from factory_issue_module.config.files import LinkSites
from factory_issue_module.declarations import Domain
from factory_issue_module.present import _blk, _p7, _q3

logger = structlog.get_logger(__name__)

#: CAR 报告页面（`link_rules.md`「CAR 报告链接」：地址里没有 `#/`，站点沿用国内 / 海外制程单那一项）
_CAR_PATH = "/QualityManage/Vendor/VendorReportOutDetail.aspx?VendorReportOutID="
#: 附件预览（`link_rules.md`「附件预览链接」）
_DOC_PATH = "/#/DocumentBusinessView?id={id}&digest={digest}"


def _label(text: Any) -> str:
    """链接的可点击文字：方括号转义，免得文档名称里的括号把链接截断。"""
    return str(text).replace("[", "\\[").replace("]", "\\]")


def car(sites: LinkSites | None, text: Any, car_id: Any) -> str:
    """CAR 编号 → CAR 报告页面链接（对所有用户生成，不看本助手的 CAR 报告权限）；站点没配时只给文字。"""
    shown = str(text)
    if sites is None or not sites.issue or car_id is None:
        return shown
    return f"[{_label(shown)}]({sites.issue}{_CAR_PATH}{int(car_id)})"


def _digest(doc_id: int) -> str | None:
    """`link_rules.md`「GetDigest」：两头各接一段、UTF-8 取 MD5、Base64，去掉末尾的 `=` 与所有 `+`。"""
    head = _q3.word()
    if head is None:
        return None
    try:
        raw = hashlib.md5(f"{head}{int(doc_id)}{head}".encode()).digest()
        return base64.b64encode(raw).decode("ascii").rstrip("=").replace("+", "")
    except Exception as exc:  # noqa: BLE001 —— 只给文档名称；异常只记类型
        logger.warning("factory_issue_link_param_failed", error=type(exc).__name__)
        return None


def attachment_ready() -> bool:
    """附件链接要的那一项值是否已经写进代码（没有时附件只给文档名称）。"""
    return _q3.word() is not None


def attachment(sites: LinkSites | None, name: Any, doc_id: Any) -> str:
    """文档名称 → 附件预览链接；站点没配、没有 ID 或那一项值还没有时只给文档名称。"""
    shown = str(name)
    base = sites.attachment if sites is not None else None
    if not base or doc_id is None:
        return shown
    digest = _digest(int(doc_id))
    if digest is None:
        return shown
    return f"[{_label(shown)}]({base}{_DOC_PATH.format(id=int(doc_id), digest=digest)})"

_PATHS = {
    Domain.DOMESTIC: "/#/QualityManage/ProblemDetail?id=",
    Domain.OVERSEAS: "/#/QualityManage/OverseasProblemAllDetail?id=",
}
_BRAZIL_PATH = "/#/BrazilProblem/AddBrazilProblemPage?type={type}&ID={id}"
#: 只读查看（`link_rules.md`：type 只用 check）
_BRAZIL_TYPE = "check"


def _brazil_param(text: str) -> str | None:
    got = _p7.pair()
    if got is None:
        return None
    try:
        return _blk.seal(text.encode("utf-8"), *got).hex().upper()
    except Exception as exc:  # noqa: BLE001 —— 只给编号文字；异常只记类型
        logger.warning("factory_issue_link_param_failed", error=type(exc).__name__)
        return None


def brazil_ready() -> bool:
    """巴西链接的两项值是否已经写进代码（没有时巴西问题编号只给文字）。"""
    return _p7.pair() is not None


def issue(sites: LinkSites | None, domain: Any, number: Any, pid: Any) -> str:
    """问题编号 → Markdown 链接；站点地址没配、没有 ID 或巴西参数还没有时只给编号文字。"""
    text = str(number)
    if sites is None or pid is None:
        return text
    if domain is Domain.BRAZIL:
        base = sites.brazil
        kind, ident = _brazil_param(_BRAZIL_TYPE), _brazil_param(str(int(pid)))
        if not base or kind is None or ident is None:
            return text
        return f"[{text}]({base}{_BRAZIL_PATH.format(type=kind, id=ident)})"
    base = sites.issue
    path = _PATHS.get(domain)
    if not base or path is None:
        return text
    return f"[{text}]({base}{path}{int(pid)})"
