"""
技能：核心争议提取

输入：判例文字 + API key
输出：案件的核心法律争议焦点分析文本

依赖：DeepSeek API
"""

from ._base import 问AI, 法条提示

def 执行(判例, api_key):
    提示 = f"请分析以下判例的核心争议是什么？每个结论后标注(见原文第X段)。{法条提示}"
    return 问AI(提示, 判例, api_key)
