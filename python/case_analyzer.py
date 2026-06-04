import requests
import os
def 字数(判例):
    return len(判例)
def 核心争议(判例):
    return "核心争议：占位"
def 推理链路(判例):
    return "推理链路：占位"
def 未回答问题(判例):
    return "未回答：占位"
def 可平移性(判例):
    return "可平移性：占位"
while True:
    lines=[]
    print("请输入判例:")
    while True:
        line=input()
        if line=="":
            break
        lines.append(line)
    判例="\n".join(lines)
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    response = requests.post(
        url="https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": "deepseek-chat", "messages": [{"role": "user", "content":
                                                        f"请用以下四问分析这段判例:核心争议是什么？ 推理链路是什么？还有那些未回答的问题？这个框架可以平移到哪些领域？判例文字：{判例}"""}]})

    data = response.json()
    ai_reply = data["choices"][0]["message"]["content"]
    print("AI回复:", ai_reply)
    reply=input("继续或者退出：")
    if reply=="退出":
        break
