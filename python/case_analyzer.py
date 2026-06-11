# 导入外部工具库
import requests 
import os  
import json
from datetime import date

# ---- 函数定义区 ----
def 字数(判例):
    return len(判例) 

def 问AI(问题,判例,api_key): 
    try:
        response = requests.post(
            url="https://api.deepseek.com/v1/chat/completions", 
            headers={"Authorization": f"Bearer {api_key}"}, 
            json={"model": "deepseek-chat",  "messages": [{  "role": "user", "content": f"{问题}\n判例文字:{判例}" }]},
            timeout=60          )
        data = response.json()  
        return data["choices"][0]["message"]["content"] 
    except:
      return "【错误】API请求失败,请检查网络或Key后重试。"
                     
def 核心争议(判例,api_key):
    return 问AI("请分析以下判例的核心争议是什么？", 判例,api_key)
def 推理链路(判例,api_key):
    return 问AI("根据上述判例，法院的推理链路是什么？",判例,api_key)                  
def 未回答问题(判例,api_key):
    return 问AI("这份判例的法院判决中，还有哪些法律问题未被回答？",判例,api_key) 
def 可平移性(判例,api_key):
    return 问AI("这份判例的分析框架可以平移到哪些法律领域？",判例,api_key) 
def 案例总结(判例, 分析1, 分析2, 分析3, 分析4, api_key):
    总结问题 = f"""请将以下判例和四段分析整合成一段完整总结。
要求:只输出一段文字(不超过300字),不要分点列出,不要给每段单独总结。

判例：{判例}

核心争议分析：{分析1}

推理链路分析：{分析2}

未回答问题分析：{分析3}

可平移性分析：{分析4}

整合成一段完整总结，涵盖：案件性质、核心裁判逻辑、法律意义。不要分点，不要编号。"""
    return 问AI(总结问题, 判例, api_key)

# ---- 主程序：外层循环，可多次分析 ----
def 启动():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    while True:
        # 第一步：接收多行判例输入
        lines = []  # 空列表，装每一行文字
        判例名 = input("请输入判例名称：")
        print("请输入判例:")  # 提示用户输入
        while True:  # 内层循环：逐行读取
            line = input()  # 读一行
            if line == "":  # 空行=输入完毕
                break  # 退出内层循环
            lines.append(line)  # 把这行加进列表

        判例 = "\n".join(lines)  # 把列表所有行拼成一段完整文字
        分析1 = 核心争议(判例,api_key)
        分析2 = 推理链路(判例,api_key)
        分析3 = 未回答问题(判例,api_key)
        分析4 = 可平移性(判例,api_key)
        总结 = 案例总结(判例, 分析1, 分析2, 分析3, 分析4, api_key)
        存储为JSON(判例名, 分析1, 分析2, 分析3, 分析4, 总结)
        
        print("\n" + "="*50)
        print(字数(判例))
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

        # 第五步：问用户要继续还是退出
        reply = input("继续或者退出：")
        if reply == "退出": 
           break  

def 存储为JSON(判例名, 分析1, 分析2, 分析3, 分析4, 总结):
      # 如果文件夹不存在就创建，已存在则跳过
      os.makedirs("/Users/jingzhe/奇点/data/case_data", exist_ok=True)

      # 拼文件名
      今天 = str(date.today())
      文件名 = "/Users/jingzhe/奇点/data/case_data/" + 今天+ "_" + 判例名 +".json"

       # 打包数据
      数据 = {
          "判例名": 判例名,
          "日期": 今天,
          "核心争议": 分析1,
          "推理链路": 分析2,
          "未回答问题": 分析3,
          "可平移性": 分析4,
          "总结": 总结
            } 
      
      # 写入 JSON 文件
      f = open(文件名, "w")
      json.dump(数据, f)
      f.close()

启动()
