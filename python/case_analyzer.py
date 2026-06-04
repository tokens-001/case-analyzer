# 导入外部工具库
import requests  # 发HTTP请求的库
import os  # 读系统环境变量的库

# ---- 函数定义区 ----
def 字数(判例):
    return len(判例)  # 返回判例文字的字数

def 核心争议(判例):
    return "核心争议：占位"  # 待升级：独立调用API

def 推理链路(判例):
    return "推理链路：占位"  # 待升级：独立调用API

def 未回答问题(判例):
    return "未回答：占位"  # 待升级：独立调用API

def 可平移性(判例):
    return "可平移性：占位"  # 待升级：独立调用API

# ---- 主程序：外层循环，可多次分析 ----
while True:
    # 第一步：接收多行判例输入
    lines = []  # 空列表，装每一行文字
    print("请输入判例:")  # 提示用户输入
    while True:  # 内层循环：逐行读取
        line = input()  # 读一行
        if line == "":  # 空行=输入完毕
            break  # 退出内层循环
        lines.append(line)  # 把这行加进列表
    判例 = "\n".join(lines)  # 把列表所有行拼成一段完整文字

    # 第二步：从环境变量取出API密钥
    api_key = os.environ.get("DEEPSEEK_API_KEY")

    # 第三步：发API请求
    response = requests.post(
        url="https://api.deepseek.com/v1/chat/completions",  # DeepSeek地址
        headers={"Authorization": f"Bearer {api_key}"},  # 身份认证
        json={  # 包裹内容
            "model": "deepseek-chat",  # 使用的模型
            "messages": [{  # 发给AI的消息列表
                "role": "user",  # 谁在说话：user=你
                "content": f"请用以下四问分析这段判例:核心争议是什么？ 推理链路是什么？还有那些未回答的问题？这个框架可以平移到哪些领域？判例文字：{判例}"  # 四问指令+判例
            }]
        })

    # 第四步：拆解API返回的结果
    data = response.json()  # 把返回内容转成Python字典
    ai_reply = data["choices"][0]["message"]["content"]  # 从字典里扒出AI的回复
    print("AI回复:", ai_reply)  # 打印结果

    # 第五步：问用户要继续还是退出
    reply = input("继续或者退出：")
    if reply == "退出":  # 输入"退出"就结束
        break  # 退出外层循环，程序结束
