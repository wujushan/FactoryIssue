"""按词匹配（设计 §7.1 ②；`topic_terms.md`「怎么读」；G2「查询期怎么用」② 三点）。只用沙箱白名单里的库。

- 原文逐字归一化（全角转半角、转小写、连续空白压成一个空格），记下每个字在原文里的位置，命中位置据此换回原文截
  上下文；不用 `seg_norm` 的偏移（它压过空白，与原文对不上）。
- 中文说法（含夹带英文的「IC卡」「NFC天线」）忽略空格按包含匹配；纯英文缩写在不去空格的文字上匹配，要求前后不是
  英文字母或数字（不用数据库正则的词边界：它把汉字也当作词的一部分）。
- 不算的说法：先把出现处换成去空格也删不掉的占位，再判断算的说法；屏蔽处两侧的文字不连起来比对。
"""

import re

from factory_issue_module.textnorm import has_cjk, normalize, to_halfwidth

TX_MASK = "\x01"
TX_SIDE = 40
_TX_ALNUM = re.compile(r"[a-z0-9]")


def tx_chars(text):
    """原文 → (归一化后的字符列表, 每个字符在原文里的下标)。连续空白压成一个空格，首尾空白去掉。"""
    out, pos = [], []
    space = True
    for i, ch in enumerate(text):
        c = to_halfwidth(ch).lower()[:1] or ch
        if c.isspace():
            if space:
                continue
            out.append(" ")
            pos.append(i)
            space = True
        else:
            out.append(c)
            pos.append(i)
            space = False
    if out and out[-1] == " ":
        out.pop()
        pos.pop()
    return out, pos


def tx_term(text):
    """一个说法 → 匹配用的形态：{"raw", "key", "cjk"}。中文说法去掉全部空白，英文缩写只归一化。"""
    raw = str(text)
    cjk = has_cjk(raw)
    key = re.sub(r"\s+", "", normalize(raw)) if cjk else normalize(raw)
    return {"raw": raw, "key": key, "cjk": cjk}


def tx_spans(chars, term):
    """说法在归一化字符列表里的全部出现：[(起, 止)]（止不含）。"""
    key = term["key"]
    if not key:
        return []
    out = []
    if term["cjk"]:
        idx = [i for i, c in enumerate(chars) if c != " "]
        flat = "".join(chars[i] for i in idx)
        start = flat.find(key)
        while start >= 0:
            out.append((idx[start], idx[start + len(key) - 1] + 1))
            start = flat.find(key, start + 1)
        return out
    flat = "".join(chars)
    start = flat.find(key)
    while start >= 0:
        end = start + len(key)
        before = flat[start - 1] if start > 0 else ""
        after = flat[end] if end < len(flat) else ""
        if not _TX_ALNUM.match(before) and not _TX_ALNUM.match(after):
            out.append((start, end))
        start = flat.find(key, start + 1)
    return out


def tx_mask(chars, excluded):
    """把不算的说法出现处换成占位（去空格也删不掉），返回新的字符列表。"""
    masked = list(chars)
    for term in excluded:
        for a, b in tx_spans(chars, term):
            for k in range(a, b):
                masked[k] = TX_MASK
    return masked


def tx_context(text, pos, span, side=TX_SIDE):
    """命中处前后各约 `side` 个字，命中的说法用【】标出。`span` 是归一化字符列表里的下标。"""
    a, b = pos[span[0]], pos[span[1] - 1] + 1
    left, right = max(0, a - side), min(len(text), b + side)
    snippet = text[left:a] + "【" + text[a:b] + "】" + text[b:right]
    snippet = re.sub(r"\s+", " ", snippet).strip()
    return ("…" if left > 0 else "") + snippet + ("…" if right < len(text) else "")


def tx_match(text, terms, excluded):
    """一段文字里命中了哪些说法：[(说法原文, 上下文)]，按说法的先后，每个说法只取第一处。"""
    if not text:
        return []
    chars, pos = tx_chars(text)
    masked = tx_mask(chars, excluded) if excluded else chars
    out = []
    for term in terms:
        spans = tx_spans(masked, term)
        if spans:
            out.append((term["raw"], tx_context(text, pos, spans[0])))
    return out


def tx_body(seg_text, title):
    """分段表 `seg_text` 去掉开头的「栏目名：」。"""
    text = str(seg_text or "")
    head = str(title or "") + "："
    return text[len(head):] if title and text.startswith(head) else text


def tx_lines(text, drop_heads):
    """处理步骤三列的文字按条目拆开，开头是 `drop_heads` 里某个「环节名称：」的条目去掉。"""
    lines = [x for x in str(text or "").split("\n") if x.strip()]
    if not drop_heads:
        return lines
    return [x for x in lines if not any(x.startswith(h + "：") for h in drop_heads)]
