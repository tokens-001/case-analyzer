"""
技能：可平移性评估

输入：判例文字 + API key
输出：本案分析框架可推广到哪些法律领域的评估

依赖：DeepSeek API
"""

from ._base import 问AI, 法条提示

def 执行(判例, api_key):
    提示 = f"这份判例的分析框架可以平移到哪些法律领域？每个结论后标注(见原文第X段)。{法条提示}"
    return 问AI(提示, 判例, api_key)
