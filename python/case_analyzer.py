# 导入外部工具库
import requests
import os
import json
import re
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
    return 问AI("请分析以下判例的核心争议是什么？每个结论后标注(见原文第X段)", 判例, api_key)
def 推理链路(判例,api_key):
    return 问AI("根据上述判例，法院的推理链路是什么？每个结论后标注(见原文第X段)", 判例, api_key)
def 未回答问题(判例,api_key):
    return 问AI("这份判例的法院判决中，还有哪些法律问题未被回答？每个结论后标注(见原文第X段)", 判例, api_key)
def 可平移性(判例,api_key):
    return 问AI("这份判例的分析框架可以平移到哪些法律领域？每个结论后标注(见原文第X段)", 判例, api_key)

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
        # 第一步：选择模式
        print("\n1. 分析判例")
        print("2. 检索历史")
        print("3. 批量分析")
        print("4. 搜索案例库（外部）")
        print("0. 退出")
        模式 = input("选一个：")

        if 模式 == "0":
            break
        elif 模式 == "2":
            检索判例()
            continue
        elif 模式 == "3":
            批量分析()
            continue
        elif 模式 == "4":
            关键词 = input("请输入搜索关键词：")
            结果, 提示 = 搜索案例库(关键词)
            print(提示)
            continue
        elif 模式 != "1":
            print("选项不存在")
            continue

        # 第二步：选择输入方式
        print("\n判例来源:")
        print("1. 输入案例")
        print("2. 读取案例")
        来源 = input("请选择：")

        if 来源 == "1":
            判例名 = input("请输入判例名称：")
            print("请输入判例（空行结束）:")
            lines = []
            while True:
                line = input()
                if line == "":
                    break
                lines.append(line)
            判例 = "\n".join(lines)

        elif 来源 == "2":
            路径 = input("请输入判例文件路径：")
            try:
                f = open(路径, "r")
                判例 = f.read()
                f.close()
                判例名 = input("请输入判例名称：")
            except:
                print("文件读取失败，请检查路径。")
                continue

        else:
            print("选项不存在")
            continue

        分析1 = 核心争议(判例,api_key)
        分析2 = 推理链路(判例,api_key)
        分析3 = 未回答问题(判例,api_key)
        分析4 = 可平移性(判例,api_key)
        总结 = 案例总结(判例, 分析1, 分析2, 分析3, 分析4, api_key)
        溯源对比(判例, 分析1, 分析2, 分析3, 分析4)
        法条库查询(分析1 + 分析2 + 分析3 + 分析4)
        验证分析结果(分析1, 分析2, 分析3, 分析4, 总结)
        存储为JSON(判例名, 分析1, 分析2, 分析3, 分析4, 总结)

        print("\n" + "="*50)
        print("判例字数：" + str(字数(判例)))
        print("="*50)
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

        reply = input("继续（回车）或输入'退出'：")
        if reply == "退出":
            break

def 搜索案例库(关键词):
    # 预留接口：接北大法宝/威科先行等法律数据库API
    # 使用时在此填入 API URL + Token
    法律库API = os.environ.get("LAW_DB_API_URL")
    法律库Token = os.environ.get("LAW_DB_TOKEN")

    if not 法律库API or not 法律库Token:
        return None, "案例库API未配置。请在环境变量中设置 LAW_DB_API_URL 和 LAW_DB_TOKEN。"

    # 未来实现：requests.get(法律库API, params={"keyword": 关键词}, headers={...})
    # 返回 (案例列表, "找到 N 条案例")
    return None, "案例库API已配置但尚未对接。请补充 API 请求逻辑。"

def 检索判例():
    关键词 = input("请输入检索关键词：")
    文件夹 = "/Users/jingzhe/奇点/data/case_data"

    if not os.path.exists(文件夹):
        print("暂无判例数据。")
        return

    文件列表 = os.listdir(文件夹)
    找到结果 = False

    for 文件名 in 文件列表:
        try:
            f = open(文件夹 + "/" + 文件名, "r")
            数据 = json.load(f)
            f.close()

            if 关键词 in 数据["判例名"] or 关键词 in 数据["核心争议"] or 关键词 in 数据["总结"]:
                print("\n" + "="*40)
                print("【" + 数据["判例名"] + "】")
                print("日期：" + 数据["日期"])
                print("-"*40)
                print("核心争议：" + 数据["核心争议"])
                print("-"*40)
                print("推理链路：" + 数据["推理链路"])
                print("-"*40)
                print("未回答问题：" + 数据["未回答问题"])
                print("-"*40)
                print("可平移性：" + 数据["可平移性"])
                print("-"*40)
                print("总结：" + 数据["总结"])
                print("="*40)
                找到结果 = True
        except:
            pass

    if not 找到结果:
        print("未找到包含'" + 关键词 + "'的判例。")

def 溯源对比(判例, 分析1, 分析2, 分析3, 分析4):
    段落列表 = 判例.split("\n\n")
    总段落数 = len(段落列表)

    # 从四段分析中提取所有段落引用
    引用集合 = set()
    for 分析 in [分析1, 分析2, 分析3, 分析4]:
        引用列表 = re.findall(r'见原文第(\d+)段', 分析)
        for 号 in 引用列表:
            引用集合.add(int(号))

    if len(引用集合) == 0:
        print("\n【溯源提醒】AI未标注任何原文引用。")
        return

    print("\n" + "="*50)
    print("【溯源对比】共引用 " + str(len(引用集合)) + " 个段落")
    print("判例共 " + str(总段落数) + " 段")
    print("="*50)

    for 段号 in sorted(引用集合):
        print("\n--- 原文第" + str(段号) + "段 ---")
        if 段号 <= 总段落数 and 段号 >= 1:
            print(段落列表[段号 - 1][:200])
        else:
            print("⚠️ 段落号" + str(段号) + "超出原文范围（共" + str(总段落数) + "段），AI可能编造引用")

def 法条统计(分析文字):
    法条列表 = re.findall(r'(?:民法典|刑法|合同法|公司法|劳动法|行政诉讼法|民事诉讼法|刑事诉讼法)\s*第\s*\d+\s*条', 分析文字)
    法条集合 = set(法条列表)
    if len(法条集合) > 0:
        return "引用法条 " + str(len(法条集合)) + " 条：" + "、".join(list(法条集合)[:5])
    else:
        return "未引用法律条文"

def 法条库查询(分析文字):
    法条文件夹 = "/Users/jingzhe/奇点/data/laws"
    if not os.path.exists(法条文件夹):
        return

    # 从分析中提取所有法条引用（民法典第X条、刑法第X条等）
    法条引用列表 = re.findall(r'(?:民法典|刑法|合同法|公司法|劳动法)\s*第\s*\d+\s*条', 分析文字)
    if len(法条引用列表) == 0:
        return

    查找列表 = list(set(法条引用列表))

    print("\n" + "="*50)
    print("【法条库对照】")

    法条文件列表 = os.listdir(法条文件夹)
    for 引用 in 查找列表[:5]:  # 最多查5条
        法名匹配 = re.match(r'(民法典|刑法|合同法|公司法|劳动法)', 引用)
        if not 法名匹配:
            continue
        法名 = 法名匹配.group(1)
        for 法条文件 in 法条文件列表:
            if 法名 in 法条文件:
                try:
                    f = open(法条文件夹 + "/" + 法条文件, "r")
                    全文 = f.read()
                    f.close()

                    # 在法条全文中搜索被引用的条文
                    条文号匹配 = re.search(r'(第\s*\d+\s*条)', 引用)
                    if 条文号匹配:
                        条文标记 = 条文号匹配.group(1)
                        # 在全文里找这个条文号的位置
                        位置 = 全文.find(条文标记)
                        if 位置 >= 0:
                            开始 = max(0, 位置)
                            结束 = min(len(全文), 位置 + 300)
                            print("\n" + 法名 + " " + 引用 + "：")
                            print(全文[开始:结束].strip() + "……")
                except:
                    pass
    print("="*50)

def 验证分析结果(分析1, 分析2, 分析3, 分析4, 总结):
    问题列表 = []

    # 非空检查
    if len(分析1) < 20:
        问题列表.append("核心争议字数过少,可能API异常")
    if len(分析2) < 20:
        问题列表.append("推理链路字数过少,可能API异常")
    if len(分析3) < 20:
        问题列表.append("未回答问题字数过少,可能API异常")
    if len(分析4) < 20:
        问题列表.append("可平移性字数过少,可能API异常")
    if len(总结) < 50:
        问题列表.append("总结字数过少")

    # 法条统计
    法条结果 = 法条统计(分析1 + 分析2 + 分析3 + 分析4)
    if 法条结果 == "未引用法律条文":
        问题列表.append("四段分析均未引用法律条文")

    # 输出
    if len(问题列表) > 0:
        print("\n【验证警告】")
        for 问题 in 问题列表:
            print("⚠️ " + 问题)
        print("   " + 法条结果)
    else:
        print("\n【验证通过】")
        print("   " + 法条结果)

def 批量分析():
    输入文件夹 = "/Users/jingzhe/奇点/data/case_input"
    if not os.path.exists(输入文件夹):
        print("请先在 finder 中创建 data/case_input/ 文件夹，放入 .txt 判例文件。")
        return

    文件列表 = os.listdir(输入文件夹)
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    print("共发现 " + str(len(文件列表)) + " 个文件，开始批量分析...\n")

    for 文件名 in 文件列表:
        if not 文件名.endswith(".txt"):
            continue
        文件路径 = 输入文件夹 + "/" + 文件名
        判例名 = 文件名.replace(".txt", "")
        print("正在分析：" + 判例名)

        try:
            f = open(文件路径, "r")
            判例 = f.read()
            f.close()

            分析1 = 核心争议(判例, api_key)
            分析2 = 推理链路(判例, api_key)
            分析3 = 未回答问题(判例, api_key)
            分析4 = 可平移性(判例, api_key)
            总结 = 案例总结(判例, 分析1, 分析2, 分析3, 分析4, api_key)

            溯源对比(判例, 分析1, 分析2, 分析3, 分析4)
            法条库查询(分析1 + 分析2 + 分析3 + 分析4)
            验证分析结果(分析1, 分析2, 分析3, 分析4, 总结)
            存储为JSON(判例名, 分析1, 分析2, 分析3, 分析4, 总结)
            print("  ✓ 已完成\n")
        except:
            print("  ✗ 分析失败：" + 判例名 + "\n")

    print("批量分析结束。")

def 存储为JSON(判例名, 分析1, 分析2, 分析3, 分析4, 总结):
    # 如果文件夹不存在就创建，已存在则跳过
    os.makedirs("/Users/jingzhe/奇点/data/case_data", exist_ok=True)

    # 拼文件名
    今天 = str(date.today())
    文件名 = "/Users/jingzhe/奇点/data/case_data/" + 今天 + "_" + 判例名 + ".json"

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

