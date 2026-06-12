# 判例助手 - Web版
# Flask后端：接收判例 → 调用DeepSeek分析 → 返回结果

import os, json, re, requests, uuid
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session

# 加载 .env 文件（本地开发用；生产环境直接用系统环境变量）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

app = Flask(__name__)
# secret_key: 生产环境从环境变量读，本地开发自动生成
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24).hex()

# 项目根目录：app.py 在 python/ 里，往上一级就是项目根
项目根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
法条库目录 = os.environ.get("LAWS_DIR", os.path.join(项目根, "data/laws"))
数据根目录 = os.environ.get("DATA_DIR", os.path.join(项目根, "data/case_data"))

# ---- 0. 会话管理：每个浏览器一个独立ID，数据隔离 ----
def 获取用户ID():
    """首次访问时在session里写入一个UUID，之后一直用同一个"""
    if "user_id" not in session:
        session["user_id"] = uuid.uuid4().hex[:12]
    return session["user_id"]

def 用户数据目录():
    """返回当前用户专属的存储目录"""
    uid = 获取用户ID()
    目录 = os.path.join(数据根目录, uid)
    os.makedirs(目录, exist_ok=True)
    return 目录

# ---- 1. 智能分段（AI引用段落号前，先统一拆分方式）----
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

# ---- 2. API调用 ----
def 问AI(问题, 判例, api_key):
    """发送请求前，先把判例文字加上段落编号，保证AI引用和代码拆分一致"""
    段落列表 = 智能分段(判例)
    编号段落 = "\n\n".join(f"[第{i+1}段] {p}" for i, p in enumerate(段落列表))
    try:
        response = requests.post(
            url="https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": f"{问题}\n判例文字:\n{编号段落}"}],
            },
            timeout=120
        )
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"【错误】API请求失败: {str(e)}"

# ---- 3. 四个分析维度 ----
法条提示 = "【硬性要求】必须引用本案应适用的具体法律条文，写明'《XX法》第X条'或'XX法第X条'，至少引用2条。不引用法律条文的分析视为不合格。"

def 核心争议(判例, api_key):
    提示 = f"请分析以下判例的核心争议是什么？每个结论后标注(见原文第X段)。{法条提示}"
    return 问AI(提示, 判例, api_key)

def 推理链路(判例, api_key):
    提示 = f"根据上述判例，法院的推理链路是什么？每个结论后标注(见原文第X段)。{法条提示}"
    return 问AI(提示, 判例, api_key)

def 未回答问题(判例, api_key):
    提示 = f"这份判例的法院判决中，还有哪些法律问题未被回答？每个结论后标注(见原文第X段)。{法条提示}"
    return 问AI(提示, 判例, api_key)

def 可平移性(判例, api_key):
    提示 = f"这份判例的分析框架可以平移到哪些法律领域？每个结论后标注(见原文第X段)。{法条提示}"
    return 问AI(提示, 判例, api_key)

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

# ---- 4. 溯源对比（返回结构化数据而非打印）----
def 溯源对比(判例, *分析列表):
    段落列表 = 智能分段(判例)
    总段落数 = len(段落列表)

    引用集合 = set()
    for 分析 in 分析列表:
        引用列表 = re.findall(r'见原文第(\d+)段', 分析)
        for 号 in 引用列表:
            引用集合.add(int(号))

    if not 引用集合:
        return {"warning": "AI未标注任何原文引用", "items": [], "total_paras": 总段落数}

    items = []
    for 段号 in sorted(引用集合):
        if 1 <= 段号 <= 总段落数:
            items.append({"段号": 段号, "内容": 段落列表[段号 - 1][:200], "有效": True})
        else:
            items.append({"段号": 段号, "内容": f"⚠️ 段落号{段号}超出原文范围（共{总段落数}段），AI可能编造引用", "有效": False})

    return {"引用数": len(引用集合), "总段落数": 总段落数, "items": items}

# ---- 5. 法条统计 ----
def 法条统计(分析文字):
    # 通用模式：《XX法》第X条 / XX法第X条 / 民法典第X条（含书名号或无书名号）
    法条列表 = re.findall(
        r'(?:《[^》]{2,20}》|[^\s，。；]{2,10}法)\s*第\s*\d+\s*(?:条(?:\s*之\s*[一二三四五六七八九十]+)?)?',
        分析文字
    )
    法条集合 = list(set(法条列表))
    if 法条集合:
        return f"引用法条 {len(法条集合)} 条：" + "、".join(法条集合[:5])
    return "未引用法律条文"

# ---- 6. 法条库查询（返回结构化数据）----
def 解析法条元数据(文件路径):
    """从法条文件中提取元数据（#META...#END 块）。返回字典或空字典"""
    try:
        with open(文件路径, "r") as f:
            内容 = f.read()
        元数据匹配 = re.search(r'#META\n(.*?)\n#END', 内容, re.DOTALL)
        if not 元数据匹配:
            return {}
        元数据 = {}
        for 行 in 元数据匹配.group(1).split("\n"):
            if ":" in 行:
                键, 值 = 行.split(":", 1)
                元数据[键.strip()] = 值.strip()
        return 元数据
    except:
        return {}

def 法条库查询(*分析列表):
    if not os.path.exists(法条库目录):
        return []

    合并分析文字 = " ".join(分析列表)
    法条引用列表 = re.findall(
        r'(?:《[^》]{2,20}》|[^\s，。；]{2,10}法)\s*第\s*\d+\s*(?:条(?:\s*之\s*[一二三四五六七八九十]+)?)?',
        合并分析文字
    )
    查找列表 = list(set(法条引用列表))

    结果列表 = []
    法条文件列表 = os.listdir(法条库目录)
    for 引用 in 查找列表[:5]:
        法名匹配 = re.search(r'《?([^》\s]{2,20}?法)》?', 引用)
        if not 法名匹配:
            if '民法典' in 引用:
                法名 = '民法典'
            else:
                continue
        else:
            法名 = 法名匹配.group(1)
        for 法条文件 in 法条文件列表:
            if 法名 in 法条文件:
                try:
                    文件路径 = os.path.join(法条库目录, 法条文件)
                    with open(文件路径, "r") as f:
                        全文 = f.read()
                    元数据 = 解析法条元数据(文件路径)
                    条文号匹配 = re.search(r'(第\s*\d+\s*条)', 引用)
                    if 条文号匹配:
                        条文标记 = 条文号匹配.group(1)
                        位置 = 全文.find(条文标记)
                        if 位置 >= 0:
                            开始 = max(0, 位置)
                            结束 = min(len(全文), 位置 + 300)
                            结果列表.append({
                                "引用": 引用,
                                "法名": 法名,
                                "条文": 全文[开始:结束].strip() + "……",
                                "状态": 元数据.get("状态", "未知"),
                                "施行日期": 元数据.get("施行日期", ""),
                                "取代": 元数据.get("取代", ""),
                            })
                except:
                    pass
    # ---- 记录缺失法条：AI引用过但法条库里没有的，写到missing文件方便以后补 ----
    已找到引用 = {item["引用"] for item in 结果列表}
    缺失引用 = [r for r in 查找列表[:5] if r not in 已找到引用]
    if 缺失引用:
        缺失日志 = os.path.join(法条库目录, "missing_laws.txt")
        try:
            已有 = set()
            if os.path.exists(缺失日志):
                with open(缺失日志, "r") as f:
                    for line in f:
                        已有.add(line.strip())
            新增 = [r for r in 缺失引用 if r not in 已有]
            if 新增:
                with open(缺失日志, "a") as f:
                    for r in 新增:
                        f.write(f"{date.today()}\t{r}\n")
        except:
            pass
    return 结果列表

# ---- 6b. 判例关联图谱（基于法条引用同现）----
def 构建判例索引():
    """扫描全部已存判例JSON，返回 {法条引用: [判例列表]} 的映射"""
    索引 = {}
    文件夹 = 用户数据目录()
    if not os.path.exists(文件夹):
        return 索引
    for fname in os.listdir(文件夹):
        if not fname.endswith(".json") or fname.startswith("limit_"):
            continue
        try:
            with open(os.path.join(文件夹, fname), "r") as f:
                d = json.load(f)
            # 合并四维分析文字，用正则提取法条引用
            分析文字 = " ".join([
                d.get("核心争议", ""), d.get("推理链路", ""),
                d.get("未回答问题", ""), d.get("可平移性", "")
            ])
            法条列表 = re.findall(
                r'(?:《[^》]{2,20}》|[^\s，。；]{2,10}法)\s*第\s*\d+\s*(?:条(?:\s*之\s*[一二三四五六七八九十]+)?)?',
                分析文字
            )
            for 法条 in set(法条列表):
                if 法条 not in 索引:
                    索引[法条] = []
                索引[法条].append({
                    "文件名": fname,
                    "判例名": d.get("判例名", ""),
                    "日期": d.get("日期", ""),
                    "总结": d.get("总结", "")[:80]
                })
        except:
            pass
    return 索引

def 查关联判例(判例文件名):
    """根据一个判例引用的法条，找到其他引用相同法条的判例"""
    文件夹 = 用户数据目录()
    路径 = os.path.join(文件夹, 判例文件名)
    if not os.path.exists(路径):
        return []
    try:
        with open(路径, "r") as f:
            d = json.load(f)
        分析文字 = " ".join([
            d.get("核心争议", ""), d.get("推理链路", ""),
            d.get("未回答问题", ""), d.get("可平移性", "")
        ])
        本文法条 = set(re.findall(
            r'(?:《[^》]{2,20}》|[^\s，。；]{2,10}法)\s*第\s*\d+\s*(?:条(?:\s*之\s*[一二三四五六七八九十]+)?)?',
            分析文字
        ))
    except:
        return []

    if not 本文法条:
        return []

    索引 = 构建判例索引()
    关联集合 = {}  # 文件名 → {判例名, 日期, 共同法条列表}
    for 法条 in 本文法条:
        for 判例 in 索引.get(法条, []):
            if 判例["文件名"] == 判例文件名:
                continue  # 不包含自己
            if 判例["文件名"] not in 关联集合:
                关联集合[判例["文件名"]] = {
                    "判例名": 判例["判例名"],
                    "日期": 判例["日期"],
                    "文件名": 判例["文件名"],
                    "总结": 判例["总结"],
                    "共同法条": []
                }
            关联集合[判例["文件名"]]["共同法条"].append(法条)

    # 按共同法条数量排序，最多的在前面
    结果 = sorted(关联集合.values(), key=lambda x: len(x["共同法条"]), reverse=True)
    return 结果[:10]

# ---- 7. 验证 ----
def 验证分析结果(分析1, 分析2, 分析3, 分析4, 总结):
    问题列表 = []
    if len(分析1) < 20: 问题列表.append("核心争议字数过少，可能API异常")
    if len(分析2) < 20: 问题列表.append("推理链路字数过少，可能API异常")
    if len(分析3) < 20: 问题列表.append("未回答问题字数过少，可能API异常")
    if len(分析4) < 20: 问题列表.append("可平移性字数过少，可能API异常")
    if len(总结) < 50: 问题列表.append("总结字数过少")

    法条结果 = 法条统计(分析1 + 分析2 + 分析3 + 分析4)
    if 法条结果 == "未引用法律条文":
        问题列表.append("四段分析均未引用法律条文")

    return {"通过": len(问题列表) == 0, "问题": 问题列表, "法条统计": 法条结果}

# ---- 8. 存储 ----
def 存储为JSON(判例名, 分析1, 分析2, 分析3, 分析4, 总结):
    """存储到当前用户的专属目录"""
    # 注意：这里不能用 session，因为 analyze 路由可能还没有初始化 session
    # 所以存储直接调用 用户数据目录() 获取或创建用户目录
    return _存储为JSON_内部(判例名, 分析1, 分析2, 分析3, 分析4, 总结)

def _存储为JSON_内部(判例名, 分析1, 分析2, 分析3, 分析4, 总结):
    文件夹 = 用户数据目录()
    今天 = str(date.today())
    文件名 = f"{文件夹}/{今天}_{判例名}.json"

    数据 = {
        "判例名": 判例名, "日期": 今天,
        "核心争议": 分析1, "推理链路": 分析2,
        "未回答问题": 分析3, "可平移性": 分析4,
        "总结": 总结
    }
    with open(文件名, "w") as f:
        json.dump(数据, f)
    return 文件名

# ---- 9. 每日次数限制 ----
每日上限 = int(os.environ.get("DAILY_LIMIT", "3"))

def 获取客户端IP():
    """获取真实客户端IP，优先取代理转发的头（PythonAnywhere会设X-Forwarded-For）"""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "未知IP"

def 剩余次数查询(uid, ip):
    """仅查询剩余次数，不消耗。返回 {'剩余': int, '上限': int}"""
    今天 = str(date.today())
    用户计数文件 = os.path.join(用户数据目录(), f"limit_{今天}.json")
    IP计数文件 = os.path.join(数据根目录, f"limit_ip_{今天}.json")

    def 读计数(路径):
        if os.path.exists(路径):
            with open(路径, "r") as f:
                return json.load(f)
        return {}

    用户计数 = 读计数(用户计数文件)
    IP计数 = 读计数(IP计数文件)

    已用 = max(用户计数.get(uid, 0), IP计数.get(ip, 0))
    return {"剩余": max(0, 每日上限 - 已用), "上限": 每日上限}

def 消耗次数(uid, ip):
    """消耗一次分析次数（UID+IP双轨记录）。返回True=可用，False=已用完"""
    今天 = str(date.today())
    用户计数文件 = os.path.join(用户数据目录(), f"limit_{今天}.json")
    IP计数文件 = os.path.join(数据根目录, f"limit_ip_{今天}.json")
    os.makedirs(数据根目录, exist_ok=True)

    def 读计数(路径):
        if os.path.exists(路径):
            with open(路径, "r") as f:
                return json.load(f)
        return {}

    用户计数 = 读计数(用户计数文件)
    IP计数 = 读计数(IP计数文件)

    已用 = max(用户计数.get(uid, 0), IP计数.get(ip, 0))
    if 已用 >= 每日上限:
        return False

    已用 += 1
    用户计数[uid] = 已用
    IP计数[ip] = 已用
    with open(用户计数文件, "w") as f:
        json.dump(用户计数, f)
    with open(IP计数文件, "w") as f:
        json.dump(IP计数, f)
    return True

# ============================================================
# Flask 路由
# ============================================================

@app.route("/")
def 首页():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def 分析路由():
    """接收判例文字，返回完整分析结果（JSON）"""
    # ---- 每日次数限制 ----
    uid = 获取用户ID()
    ip = 获取客户端IP()
    if not 消耗次数(uid, ip):
        剩余 = 剩余次数查询(uid, ip)
        return jsonify({"error": f"今日分析次数已用完（每人{每日上限}次），请明天再来。", "剩余": 0, "上限": 每日上限}), 429
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return jsonify({"error": "未设置 DEEPSEEK_API_KEY 环境变量"}), 500

    data = request.json
    判例名 = data.get("name", "").strip() or "未命名判例"
    判例 = data.get("text", "").strip()

    if len(判例) < 50:
        return jsonify({"error": "判例文字太短（少于50字），请输入完整判例内容"}), 400

    # ---- 并行跑四个分析（ThreadPoolExecutor）----
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_1 = executor.submit(核心争议, 判例, api_key)
        future_2 = executor.submit(推理链路, 判例, api_key)
        future_3 = executor.submit(未回答问题, 判例, api_key)
        future_4 = executor.submit(可平移性, 判例, api_key)

        分析1 = future_1.result()
        分析2 = future_2.result()
        分析3 = future_3.result()
        分析4 = future_4.result()

    # 总结依赖前面四个结果，不能并行
    总结 = 案例总结(判例, 分析1, 分析2, 分析3, 分析4, api_key)

    # 溯源、法条、验证、存储
    溯源 = 溯源对比(判例, 分析1, 分析2, 分析3, 分析4)
    法条对照 = 法条库查询(分析1, 分析2, 分析3, 分析4)
    验证 = 验证分析结果(分析1, 分析2, 分析3, 分析4, 总结)
    存储为JSON(判例名, 分析1, 分析2, 分析3, 分析4, 总结)

    剩余 = 剩余次数查询(uid, ip)

    return jsonify({
        "判例名": 判例名,
        "字数": len(判例),
        "剩余次数": 剩余["剩余"],
        "今日上限": 剩余["上限"],
        "分析": {
            "核心争议": 分析1,
            "推理链路": 分析2,
            "未回答问题": 分析3,
            "可平移性": 分析4,
            "总结": 总结,
        },
        "溯源": 溯源,
        "法条对照": 法条对照,
        "验证": 验证,
    })

@app.route("/remaining")
def 剩余路由():
    """返回当前用户+IP的剩余分析次数"""
    uid = 获取用户ID()
    ip = 获取客户端IP()
    return jsonify(剩余次数查询(uid, ip))

@app.route("/history")
def 历史路由():
    """返回当前用户已存储的判例列表（最新20条）"""
    文件夹 = 用户数据目录()
    if not os.path.exists(文件夹):
        return jsonify([])

    files = sorted(os.listdir(文件夹), reverse=True)
    结果 = []
    for fname in files[:20]:
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(文件夹, fname), "r") as f:
                d = json.load(f)
            结果.append({
                "文件名": fname,
                "判例名": d.get("判例名", ""),
                "日期": d.get("日期", ""),
                "总结": d.get("总结", "")[:120]
            })
        except:
            pass
    return jsonify(结果)

@app.route("/case/<fname>")
def 详情路由(fname):
    """返回单条判例的完整分析数据，格式与/analyze返回一致"""
    文件夹 = 用户数据目录()
    路径 = os.path.join(文件夹, fname)
    if ".." in fname or not os.path.exists(路径):
        return jsonify({"error": "文件不存在"}), 404
    try:
        with open(路径, "r") as f:
            d = json.load(f)
        # 包成和/analyze一样的格式，历史数据缺失的字段填空
        return jsonify({
            "判例名": d.get("判例名", ""),
            "字数": d.get("字数", len(d.get("核心争议", ""))),
            "分析": {
                "核心争议": d.get("核心争议", ""),
                "推理链路": d.get("推理链路", ""),
                "未回答问题": d.get("未回答问题", ""),
                "可平移性": d.get("可平移性", ""),
                "总结": d.get("总结", ""),
            },
            "溯源": None,
            "法条对照": None,
            "验证": {"通过": True, "问题": [], "法条统计": "历史存档数据"},
            "关联判例": 查关联判例(fname)
        })
    except:
        return jsonify({"error": "读取失败"}), 500

@app.route("/related/<fname>")
def 关联路由(fname):
    """返回与指定判例引用相同法条的其他判例"""
    return jsonify(查关联判例(fname))

@app.route("/download", methods=["POST"])
def 下载路由():
    """把分析结果转成可下载的文本报告"""
    data = request.json
    报告 = f"""判例分析报告
{'='*50}
判例名称：{data.get('判例名', '')}
分析日期：{date.today()}

一、核心争议
{'─'*40}
{data.get('核心争议', '')}

二、推理链路
{'─'*40}
{data.get('推理链路', '')}

三、未回答问题
{'─'*40}
{data.get('未回答问题', '')}

四、可平移性
{'─'*40}
{data.get('可平移性', '')}

五、综合总结
{'─'*40}
{data.get('总结', '')}

六、法条统计
{'─'*40}
{data.get('法条统计', '')}

七、法条对照
{'─'*40}
"""
    for 条目 in data.get('法条对照', []):
        报告 += f"\n【{条目.get('法名', '')}】{条目.get('引用', '')}\n{条目.get('条文', '')}\n"

    报告 += f"""
八、溯源对比
{'─'*40}
"""
    for item in data.get('溯源', {}).get('items', []):
        mark = "" if item.get('有效') else "⚠️ "
        报告 += f"\n{mark}原文第{item.get('段号', '')}段：\n{item.get('内容', '')}\n"

    报告 += f"""
{'='*50}
判例助手自动生成 | {date.today()}
"""

    from flask import Response
    return Response(
        报告,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={data.get('判例名', 'report')}_分析报告.txt"}
    )

if __name__ == "__main__":
    print("判例助手网页版已启动 → http://127.0.0.1:5050")
    app.run(debug=True, host="0.0.0.0", port=5050)
