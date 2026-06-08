import requests
import os
import ast
from datetime import date

# ---- 公共函数 ----
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

# ---- 晚间评估 ----
def 晚间评估():
    print("\n=== 晚间评估 ===")
    print("回顾一下今天：\n")

    q1 = input("1. 今天脑子清晰吗？(1-10) ")
    q2 = input("2. 社交是否消耗了你？(没有社交/有但不累/有而且很累) ")
    q3 = input("3. 今天的任务启动顺利吗？(顺利/一般/卡住了) ")
    q4 = input("4. 今天有啥想说的？ ")

    今天 = str(date.today())
    记录 = "[" + q1 + ", " + repr(q2) + ", " + repr(q3) + ", " + repr(q4) + ", " + 今天 + "]"

    f = open("/Users/jingzhe/奇点/data/evening_log.txt", "a")
    f.write(记录 + "\n")
    f.close()

    print("\n晚间记录已保存。")

# ---- 早间评估 ----
def 状态评估():
    print("\n=== 今日状态评估 ===")

    # 读取最近一条晚间记录作为参考
    晚间参考 = ""
    try:
        f_evening = open("/Users/jingzhe/奇点/data/evening_log.txt", "r")
        lines = f_evening.readlines()
        f_evening.close()
        if len(lines) > 0:
            晚间参考 = "【用户昨晚的状态】" + lines[-1].strip() + "\n\n"
    except:
        pass

    print("AI 正在为你生成今日评估问题...\n")

    # 第一步：AI出题
    出题_prompt = "你是一个状态评估师。用户需要你帮他判断今天适合'重度脑力任务(编程、学新东西)'还是'轻量级任务(读书、复习、整理)'。\n\n" + 晚间参考 + "请生成3个针对性的问题来评估他当前状态。只要列出问题,每个问题占一行。"
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
        i = i + 1

    if len(答案列表) == 0:
        print("未输入任何答案，评估取消")
        return

    回答汇总 = "\n".join(答案列表)

    # 第三步：AI评估
    评估_prompt = f"""你刚才问了用户以下问题：
{问题列表}

用户的回答是：
{回答汇总}

请做两件事：
  1. 判断用户今天适合'重度脑力任务'还是'轻量级任务',给出1-2句具体建议。
  2. 给身体状态、情绪状态、精力状态分别打分(1-10分)。

  回复末尾必须单独一行，只输出「分数:[身体分,情绪分,精力分,类型]」。
  类型填"重"或"轻"。
  例如：分数:[7,5,8,重]"""

    结果 = 问AI(评估_prompt)
    print("\n" + "="*40)
    print("【AI 状态评估】")
    print(结果)
    print("="*40 + "\n")

    # 存储详细记录
    今天 = str(date.today())
    f1 = open("/Users/jingzhe/奇点/data/energy_detail.txt", "a")
    f1.write("=== " + 今天 + " ===\n" + 结果 + "\n\n")
    f1.close()

    # 提取分数行存energy_log.txt
    for line in 结果.split("\n"):
        if line.startswith("分数:["):
            分数行 = line.replace("分数:", "")
            f2 = open("/Users/jingzhe/奇点/data/energy_log.txt", "a")
            f2.write("[" + 分数行.strip().strip("[]") + "," + 今天 + "]\n")
            f2.close()
            print("分数已自动记录: " + 分数行)
            break

# ---- 统计 ----
def 统计():
    all_entries = []
    try:
        f = open("/Users/jingzhe/奇点/data/energy_log.txt", "r")
        for line in f:
            all_entries.append(line.strip())
        f.close()
    except:
        print("暂无记录数据")
        return

    if len(all_entries) == 0:
        print("暂无记录数据")
        return

    print("\n=== 统计报告 ===")

    月份数据 = {}
    for line in all_entries:
        data = ast.literal_eval(line)
        日期 = data[4]
        月份 = 日期[:7]
        if 月份 not in 月份数据:
            月份数据[月份] = []
        月份数据[月份].append(data)

    for 月份 in sorted(月份数据.keys()):
        records = 月份数据[月份]
        total = len(records)
        body_sum = 0
        mood_sum = 0
        energy_sum = 0
        heavy = 0
        light = 0
        for 每条记录 in records:
            body_sum = body_sum + 每条记录[0]
            mood_sum = mood_sum + 每条记录[1]
            energy_sum = energy_sum + 每条记录[2]
            if 每条记录[3] == "重":
                heavy = heavy + 1
            else:
                light = light + 1
        print(月份 + " | 平均: 身体" + str(round(body_sum/total, 1)) + " 情绪" + str(round(mood_sum/total, 1)) + " 精力" + str(round(energy_sum/total, 1)) + " | 重度" + str(heavy) + "天 轻度" + str(light) + "天")

    # 晚间统计
    晚间数据 = {}
    try:
        f = open("/Users/jingzhe/奇点/data/evening_log.txt", "r")
        for line in f:
            data = ast.literal_eval(line.strip())
            日期 = data[4]
            月份 = 日期[:7]
            if 月份 not in 晚间数据:
                晚间数据[月份] = []
            晚间数据[月份].append(data)
        f.close()
    except:
        pass

    if len(晚间数据) > 0:
        print("\n--- 晚间数据（按月） ---")
        for 月份 in sorted(晚间数据.keys()):
            records = 晚间数据[月份]
            total = len(records)
            清晰度总和 = 0
            启动情况 = {"顺利": 0, "一般": 0, "卡住了": 0}
            社交情况 = {"没有社交": 0, "有但不累": 0, "有而且很累": 0}
            for 每条记录 in records:
                清晰度总和 = 清晰度总和 + int(每条记录[0])
                启动 = 每条记录[2].strip("'")
                社交 = 每条记录[1].strip("'")
                if 启动 in 启动情况:
                    启动情况[启动] = 启动情况[启动] + 1
                if 社交 in 社交情况:
                    社交情况[社交] = 社交情况[社交] + 1
            print(月份 + " | 清晰度均值: " + str(round(清晰度总和/total, 1)))
            print("  启动: 顺利" + str(启动情况["顺利"]) + "天 一般" + str(启动情况["一般"]) + "天 卡住" + str(启动情况["卡住了"]) + "天")
            print("  社交: 无社交" + str(社交情况["没有社交"]) + "天 有但不累" + str(社交情况["有但不累"]) + "天 很累" + str(社交情况["有而且很累"]) + "天")

        # 按年统计
        print("\n--- 晚间数据（按年） ---")
        年数据 = {}
        for records in 晚间数据.values():
            for 每条记录 in records:
                日期 = r[4]
                年份 = 日期[:4]
                if 年份 not in 年数据:
                    年数据[年份] = []
                年数据[年份].append(r)
        for 年份 in sorted(年数据.keys()):
            records = 年数据[年份]
            total = len(records)
            清晰度总和 = 0
            启动情况 = {"顺利": 0, "一般": 0, "卡住了": 0}
            社交情况 = {"没有社交": 0, "有但不累": 0, "有而且很累": 0}
            for 每条记录 in records:
                清晰度总和 = 清晰度总和 + int(每条记录[0])
                启动 = 每条记录[2].strip("'")
                社交 = 每条记录[1].strip("'")
                if 启动 in 启动情况:
                    启动情况[启动] = 启动情况[启动] + 1
                if 社交 in 社交情况:
                    社交情况[社交] = 社交情况[社交] + 1
            print(年份 + " | 清晰度均值: " + str(round(清晰度总和/total, 1)))
            print("  启动: 顺利" + str(启动情况["顺利"]) + "天 一般" + str(启动情况["一般"]) + "天 卡住" + str(启动情况["卡住了"]) + "天")
            print("  社交: 无社交" + str(社交情况["没有社交"]) + "天 有但不累" + str(社交情况["有但不累"]) + "天 很累" + str(社交情况["有而且很累"]) + "天")

# ---- 菜单 ----
def 启动():
    while True:
        print("\n== 能量日记 ==")
        print("1. 早间状态评估(AI)")
        print("2. 晚间评估")
        print("3. 统计")
        print("0. 返回")
        choice = input("选一个：")
        if choice == "1":
            状态评估()
        elif choice == "2":
            晚间评估()
        elif choice == "3":
            统计()
        elif choice == "0":
            break
        else:
            print("选项不存在")
