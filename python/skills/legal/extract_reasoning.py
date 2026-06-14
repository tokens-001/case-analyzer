"""
技能：推理链路提取

输入：判例文字 + API key
输出：法院从事实到结论的完整推理过程分析

依赖：DeepSeek API
"""

from ._base import 问AI, 法条提示

def 执行(判例, api_key):
    提示 = f"根据上述判例，法院的推理链路是什么？每个结论后标注(见原文第X段)。{法条提示}"
    return 问AI(提示, 判例, api_key)
