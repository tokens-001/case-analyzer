"""
法律技能库 —— 共享基础设施

提供所有 skill 共用的：DeepSeek API 调用、智能分段。
（法条库目录由调用方传入，本模块不解析路径。）
不包含任何法律分析逻辑。
"""

import json
import re
import requests

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

# 格式的**定义在 verify_laws 里**（和检查它的那段判据同一个文件），这里只负责拼进提示词。
# 原来这里是一句自己写的软要求："如能确定…请引用…不确定的不要编造" ——
# 措辞是"如能确定"，模型完全可以理解为"不确定就不写条号"，于是大量引用退化成
# 只给《法名》，而那种引用结构上校验不了。实测历史分析里 52% 的引用是这一种。
from .verify_laws import 法条引用格式要求   # noqa: E402

法条提示 = "如能确定本案应适用的法律条文，按下面的格式引用；不确定的一律不要编造。\n" + 法条引用格式要求


# ═══════════════════════════════════════════════════════════
# API 调用
# ═══════════════════════════════════════════════════════════

def 问AI(提示词, 判例文字, api_key, 附段落编号=True):
    """发送请求给 DeepSeek。

    `附段落编号=False`：合同模式用。那条路自己插了【第N条】锚点，
    再套一层 [第X段] 会让模型改去引用段号 —— 而本地校验认的是条号锚点，
    两套编号同时在场时它引哪一个就成了运气。
    """
    if 附段落编号:
        段落列表 = 智能分段(判例文字)
        编号段落 = "\n\n".join(f"[第{i+1}段] {p}" for i, p in enumerate(段落列表))
    else:
        编号段落 = 判例文字
    try:
        response = requests.post(
            url="https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "你是一个法律分析系统。直接输出分析结果，禁止寒暄客套。每个分析维度控制在300字以内，精炼不啰嗦。"},
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
