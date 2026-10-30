"""导出（设计 §9.3；总述「排名、长清单与导出」「清单默认列」「按编号查单」）。

- 每域一页的 xlsx 用 openpyxl 自己写，再 `ctx.files.save_bytes(…)`（`save_dataframe` 只写一页）。正文写
  「完整 N 张见附件：链接（24 小时内有效）」，N 由沙箱给。
- 表头是沙箱给的显示名（与表格同一套列名），不出现字段名；问题编号给文字，不带链接。
- 这里只搬值：把沙箱产出的行原样写进单元格，不算数。numpy 标量转回原生类型，空值写「未填」。
- `ctx.files` 为 None 或保存出错时返回 None，调用方答「完整清单导出失败，请稍后再试」，表格照给（§14）。
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import structlog

from factory_issue_module.turn import errors

logger = structlog.get_logger(__name__)

LIST_FILENAME = "制程问题清单.xlsx"
ISSUE_FILENAME = "按问题编号查单.xlsx"
VALID_TEXT = "24 小时内有效"
#: Excel 的工作表名最多 31 个字符，且不能含这几个字符
_SHEET_MAX = 31
_SHEET_BAD = set('[]:*?/\\')
_BLANK = "未填"


def _cell(value: Any) -> Any:
    if value is None:
        return _BLANK
    if not isinstance(value, (list, tuple, set, dict)):
        try:
            if pd.isna(value):  # NaN、NaT、pd.NA
                return _BLANK
        except (TypeError, ValueError):
            pass
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if not isinstance(value, (str, bytes, list, tuple, set)) and hasattr(value, "item"):  # numpy 标量
        try:
            value = value.item()
        except (ValueError, TypeError):
            value = str(value)
    if isinstance(value, float) and value != value:
        return _BLANK
    if isinstance(value, (list, tuple, set)):
        return "、".join(str(v) for v in value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _title(name: str, used: set[str]) -> str:
    title = "".join("_" if ch in _SHEET_BAD else ch for ch in str(name or "Sheet"))[:_SHEET_MAX] or "Sheet"
    base, k = title, 2
    while title in used:
        suffix = f"_{k}"
        title, k = base[: _SHEET_MAX - len(suffix)] + suffix, k + 1
    used.add(title)
    return title


def workbook_bytes(sheets: Sequence[tuple[str, Sequence[str], Sequence[Sequence[Any]]]]) -> bytes:
    """[(页名, 列名, 行)] → xlsx 字节。"""
    from openpyxl import Workbook

    wb = Workbook()
    used: set[str] = set()
    for k, (name, cols, rows) in enumerate(sheets):
        ws = wb.active if k == 0 else wb.create_sheet()
        ws.title = _title(name, used)
        ws.append([str(c) for c in cols])
        for row in rows:
            ws.append([_cell(v) for v in row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def frame_sheet(name: str, frame: pd.DataFrame) -> tuple[str, list[str], list[list[Any]]]:
    """沙箱经数据帧通道回传的明细帧（列名已是显示名）→ 一页。"""
    return name, [str(c) for c in frame.columns], frame.astype(object).values.tolist()


async def save_lists(ctx: Any, counts: Sequence[Sequence[Any]], frames: Mapping[str, pd.DataFrame],
                     filename: str) -> str:
    """清单式的导出（沙箱经数据帧通道回传的 `export_<域>`）：每域一页写成一个文件，返回正文里那一句。
    张数取自沙箱（`counts`：[[域, 张数]…]）；失败时返回「完整清单导出失败」那一句（§14）。"""
    pairs = [(str(d), n) for d, n in counts]
    sheets = [frame_sheet(d, frames["export_" + d]) for d, _n in pairs if "export_" + d in frames]
    ref = await save(ctx, sheets, filename) if sheets else None
    if ref is None:
        return f"{errors.EXPORT_FAILED}。"
    if len(pairs) == 1:
        return f"完整 {pairs[0][1]} 张见附件：{ref.markdown}（{VALID_TEXT}）。"
    per = "、".join(f"{d} {n} 张" for d, n in pairs)
    return f"完整清单见附件（每域一页：{per}）：{ref.markdown}（{VALID_TEXT}）。"


async def save(ctx: Any, sheets: Sequence[tuple[str, Sequence[str], Sequence[Sequence[Any]]]], filename: str) -> Any:
    """写成一个 xlsx 交 `ctx.files`；返回 `FileRef`，失败返回 None（异常只进日志）。"""
    files = getattr(ctx, "files", None)
    if files is None or not sheets:
        logger.warning("factory_issue_export_unavailable", has_files=files is not None)
        return None
    try:
        return await files.save_bytes(workbook_bytes(sheets), filename)
    except Exception as exc:  # noqa: BLE001 —— 表格照给，正文说导出失败（§14）
        logger.warning("factory_issue_export_failed", error=type(exc).__name__)
        return None
