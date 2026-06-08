import requests
import os
import ast

def 问AI(prompt):
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    try:
        response = requests.post(
            url="https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]},
            timeout=60
        )
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except:
        return "【API出错】"

def 状态评估():
    print("\n=== 今日状态评估 ===")
    print("AI 正在为你生成今日评估问题...\n")

    # 第一步：AI出题
    出题_prompt = "你是一个状态评估师。用户需要你帮他判断今天适合重度脑力任务（编程、学新东西）还是轻量级任务（读书、复习、整理）。请生成3个针对性的问题来评估他当前状态。只要列出问题，每个问题占一行。"
    问题列表 = 问AI(出题_prompt)
    if 问题列表 == "【API出错】":
        print("出题失败，请检查网络")
        return

    print("【AI提问】")
    print(问题列表 + "\n")

    # 第二步：用户回答
    答案列表 = []
    i = 1
    while True:
        answer = input(f"回答{i}（直接回车结束）：")
        if answer == "":
            break
        答案列表.append(answer)
        i += 1

    if len(答案列表) == 0:
        print("未输入任何答案，评估取消")
        return

    回答汇总 = "\n".join(答案列表)

    # 第三步：AI评估
    评估_prompt = f"""你刚才问了用户以下问题：
{问题列表}

用户的回答是：
{回答汇总}

请根据以上信息判断用户今天适合'重度脑力任务'还是'轻量级任务',并给出1-2句具体建议。"""

    结果 = 问AI(评估_prompt)
    print("\n" + "="*40)
    print("【AI 状态评估】")
    print(结果)
    print("="*40 + "\n")

def 记录():
    scores = []
    body = input("身体状态(1-10): ")
    mood = input("情绪状态(1-10): ")
    energy = input("精力状态(1-10): ")
    scores.append(body)
    scores.append(mood)
    scores.append(energy)
    print("今日记录: " + str(scores))
    f = open("/Users/jingzhe/奇点/energy_log.txt", "a")
    f.write(str(scores) + "\n")
    f.close()
    all_entries = []
    f = open("/Users/jingzhe/奇点/energy_log.txt", "r")
    for line in f:
        all_entries.append(line)
    f.close()
    print(all_entries)
    all_body = 0
    all_mood = 0
    all_energy = 0
    days = 0
    for line in all_entries:
        data = ast.literal_eval(line.strip())
        all_body = all_body + int(data[0])
        all_mood = all_mood + int(data[1])
        all_energy = all_energy + int(data[2])
        days = days + 1
    print("身体平均值: " + str(round(all_body/days, 2)))
    print("情绪平均值: " + str(round(all_mood/days, 2)))
    print("精力平均值: " + str(round(all_energy/days, 2)))
    print("总天数: " + str(days))

def 启动():
    while True:
        print("\n== 能量日记 ==")
        print("1. 今日状态评估（AI）")
        print("2. 记录分数")
        print("0. 返回")
        choice = input("选一个：")
        if choice == "1":
            状态评估()
        elif choice == "2":
            记录()
        elif choice == "0":
            break
        else:
            print("选项不存在")
