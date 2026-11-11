"""配置内容不合格时抛的错误（设计 §11）。单独成文件，`files.py` 与 `polish_rules.py` 都用它而不互相导入。"""

from __future__ import annotations


class ConfigFormatError(ValueError):
    """配置内容不合格。消息直接给管理员看。"""
