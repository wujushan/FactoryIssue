"""按域取视图（设计 §6.2、§6.4）：三域各自派生成同一套辅助列的「一单一行」视图。"""

from factory_issue_module.stats.lib.derive_brazil import br_enums, br_view
from factory_issue_module.stats.lib.derive_domestic import cn_enums, cn_view
from factory_issue_module.stats.lib.derive_overseas import os_enums, os_view


def dm_view(domain, data, P):
    """本步某一域的「一单一行」视图（主表帧为空或没传时是空视图）；不认识的域返回 None。"""
    desc = P["desc"].get(domain, "未填")
    if domain == "国内":
        return cn_view(data, cn_enums(P["enums"]["国内"]), desc)
    if domain == "巴西":
        return br_view(data, br_enums(P["enums"]["巴西"]), desc)
    if domain == "海外":
        return os_view(data, os_enums(P["enums"]["海外"]), desc)
    return None
