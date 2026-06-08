import requests
import os

def 问AI(问题,判例,api_key):
    try:
        response = requests.post(
            url="https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization":f"Bearer {api_key}"},
            json={"model":"deepseek-chat","messages":[{"role":"user","content":f"{问题}\n判例文字:{判例}"}]}
                                )
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except:
        return "【错误】API请求失败,请检查网络或Key后重试。"
                         
def 核心争议(判例,api_key):
    return 问AI("请分析以下判例的核心争议是什么？",判例,api_key)
def 推理链路(判例,api_key):
    return 问AI("这份判例中法院的推理链路是什么？",判例,api_key)
def 未回答问题(判例,api_key):
    return 问AI("这份判例的法院判决中,未回答的法律问题是什么？",判例,api_key)
def 可平移性(判例,api_key):
    return 问AI("这份判例的分析框架可以平移到哪些法律领域？",判例,api_key)

api_key =os.environ.get("DEEPSEEK_API_KEY")
while True:
    lines=[]
    print("请输入判例:")
    while True:
        line=input()
        if line=="":
            break
        lines.append(line)
        判例="\n".join(lines)

    分析1 = 核心争议(判例,api_key)
    分析2 = 推理链路(判例,api_key)
    分析3 = 未回答问题(判例,api_key)
    分析4 = 可平移性(判例,api_key)

    print("\n" + "="*50)
    print("【核心争议】")
    print(分析1)
    print("\n" + "="*50)
    print("【推理链路】")
    print(分析2)
    print("\n" + "="*50)
    print("【未回答问题】")
    print(分析3)
    print("\n" + "="*50)
    print("【可平移性】")
    print(分析4)
    print("="*50)

    f=open("/Users/jingzhe/奇点/case_log.txt","a")
    f.write("判例\n"+"="*50+分析1+"\n"+"="*50+分析2+"\n"+"="*50+分析3+"\n"+分析4)
    f.close()

    reply = input("继续或者退出：")
    if reply == "退出": 
           break

