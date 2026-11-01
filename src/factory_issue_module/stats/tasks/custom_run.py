"""临时统计的第二次沙箱调用：模型写的脚本外面的一层（设计 §5.5、§8.1）。

`stats/runner.py::custom_script` 按这个顺序拼：公共库（含 `stats/lib/custom.py` 的口径函数）、模型写的脚本、一行
`cs_user_run = run`、本模板。harness 只认 `run(data)` 一个入口，模型写的 `run` 先改名为 `cs_user_run`，下面这个
`run` 才是入口：把帧的列名写进口径函数要用的 `CS_NAMES`，调模型的 `run`，返回值经 `cs_finish` 整理后放在 `out`。
"""

from factory_issue_module.stats.lib.custom import CS_NAMES, cs_finish

PARAMS = {}

CS_NAMES.update(PARAMS.get("names") or {})


def run(data):
    return {"out": cs_finish(cs_user_run({"issues": data["issues"]}))}  # noqa: F821 —— 拼接时由模型的 run 改名而来
