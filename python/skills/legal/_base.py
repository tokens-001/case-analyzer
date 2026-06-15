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

法条提示 = "如能确定本案应适用的法律条文，请引用'《XX法》第X条'或'XX法第X条'。不确定的不要编造。"


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
                "messages": [
                    {"role": "system", "content": "你是一个法律分析系统。直接输出分析结果，禁止使用\"好的\"\"以下是\"\"综上所述\"\"为您提供\"等寒暄语，禁止在开头或结尾加任何客套话。"},
                    {"role": "user", "content": f"{提示词}\n判例文字:\n{编号段落}"}
                ],
                "temperature": 0.1,
            },
            timeout=120
        )
        data = response.json()
        if "choices" not in data:
            return json.dumps({"error": True, "type": "api", "detail": data.get("error", {}).get("message", "API返回异常")}, ensure_ascii=False)
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        return json.dumps({"error": True, "type": "timeout", "detail": "API请求超时，请稍后重试"}, ensure_ascii=False)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": True, "type": "network", "detail": "网络连接失败，请检查网络"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": True, "type": "unknown", "detail": f"API请求异常: {str(e)[:100]}"}, ensure_ascii=False)
