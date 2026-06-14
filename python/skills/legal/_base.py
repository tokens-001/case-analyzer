"""
法律技能库 —— 共享基础设施

提供所有 skill 共用的：DeepSeek API 调用、智能分段、法条库路径解析。
不包含任何法律分析逻辑。
"""

import os, re, requests

# ═══════════════════════════════════════════════════════════
# 智能分段
# ═══════════════════════════════════════════════════════════

def 智能分段(判例):
    """把判例文字拆成段落。依次尝试空行→单换行→句号拆分"""
    段落 = [p.strip() for p in 判例.split("\n\n") if p.strip()]
    if len(段落) >= 3:
        return 段落
    段落 = [p.strip() for p in 判例.split("\n") if p.strip()]
    if len(段落) >= 3:
        return 段落
    raw = re.split(r'(?<=[。！？])', 判例)
    段落 = [p.strip() for p in raw if p.strip() and len(p.strip()) > 5]
    if len(段落) >= 2:
        return 段落
    return [判例]


# ═══════════════════════════════════════════════════════════
# 共享 Prompt 片段
# ═══════════════════════════════════════════════════════════

法条提示 = "【硬性要求】必须引用本案应适用的具体法律条文，写明'《XX法》第X条'或'XX法第X条'，至少引用2条。不引用法律条文的分析视为不合格。"


# ═══════════════════════════════════════════════════════════
# API 调用
# ═══════════════════════════════════════════════════════════

def 问AI(提示词, 判例文字, api_key):
    """发送请求给 DeepSeek，判例文字自动加段落编号"""
    段落列表 = 智能分段(判例文字)
    编号段落 = "\n\n".join(f"[第{i+1}段] {p}" for i, p in enumerate(段落列表))
    try:
        response = requests.post(
            url="https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": f"{提示词}\n判例文字:\n{编号段落}"}],
            },
            timeout=120
        )
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"【错误】API请求失败: {str(e)}"
