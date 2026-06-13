"""
技能：溯源对比

输入：判例原始文字 + 多段AI分析结果
输出：AI引用段落号 vs 原文对照，检测越界/编造引用

纯本地运行，不调API。需要和AI使用同一套分段函数。
"""

import re
from ._base import 智能分段


def 执行(判例文字, *分析列表):
    """对比AI分析中的(见原文第X段)引用与原文实际分段，返回结构化结果"""
    段落列表 = 智能分段(判例文字)
    总段落数 = len(段落列表)

    引用集合 = set()
    for 分析 in 分析列表:
        引用列表 = re.findall(r'见原文第(\d+)段', 分析)
        for 号 in 引用列表:
            引用集合.add(int(号))

    if not 引用集合:
        return {"warning": "AI未标注任何原文引用", "items": [], "total_paras": 总段落数}

    items = []
    for 段号 in sorted(引用集合):
        if 1 <= 段号 <= 总段落数:
            items.append({"段号": 段号, "内容": 段落列表[段号 - 1][:200], "有效": True})
        else:
            items.append({"段号": 段号, "内容": f"⚠️ 段落号{段号}超出原文范围（共{总段落数}段），AI可能编造引用", "有效": False})

    return {"引用数": len(引用集合), "总段落数": 总段落数, "items": items}
