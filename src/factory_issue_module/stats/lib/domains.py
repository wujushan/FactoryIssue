"""按域取视图（S2 只有国内；巴西、海外随 S3 加进来）。"""

from factory_issue_module.stats.lib.derive_domestic import cn_enums, cn_view


def dm_view(domain, data, P):
    """本步某一域的「一单一行」视图；该域还没接上时返回 None。"""
    if domain == "国内":
        return cn_view(data, cn_enums(P["enums"]["国内"]), P["desc"].get("国内", "未填"))
    return None
