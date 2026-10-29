"""派生与统计函数（设计 §1.4、§6.2、§8.1）。

这里的源码由 `stats/runner.py` 按文本拼进沙箱脚本，所以只用沙箱白名单里的东西：pandas、numpy、re、json、
datetime、math、statistics、collections、itertools、functools；不定义类（沙箱没有 `__build_class__`），
不用 getattr、hasattr、type。文件之间的 `from factory_issue_module… import` 在拼接时去掉（名字已在同一个
命名空间里），所以各文件的顶层名字不能重名。单测直接 import 这些函数测。
"""
