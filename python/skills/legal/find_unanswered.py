"""
技能：未回答问题发现

输入：判例文字 + API key
输出：判决中尚未解决的法律问题列表

依赖：DeepSeek API
"""

from ._base import 问AI, 法条提示

def 执行(判例, api_key):
    提示 = f"这份判例的法院判决中，还有哪些法律问题未被回答？每个结论后标注(见原文第X段)。{法条提示}"
    return 问AI(提示, 判例, api_key)
