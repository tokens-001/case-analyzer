# 判例助手 - Web版
# Flask后端：接收判例 → 调用DeepSeek分析 → 返回结果

import os
import json
import re
import uuid
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session

# 加载 .env 文件（本地开发用；生产环境直接用系统环境变量）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ═══════════════════════════════════════════════════════════
# 法律技能库导入
# ═══════════════════════════════════════════════════════════
# 判决书模式技能（8维）
from skills.legal import (
    structure_summary,
    extract_dispute,
    extract_reasoning,
    analyze_law_application,
    find_opposing_paths,
    audit_argument_integrity,
    identify_procedural_issues,
    find_unanswered,
)
# 案情模式技能（5维）
from skills.legal import (
    identify_relationship,
    assess_facts_evidence,
    analyze_opposing_paths,
    project_risks,
    suggest_actions,
    summarize_case,
)
from skills.legal.verify_laws import (
    count_law_citations,
    classify_law_citations,
)
from skills.legal.verify_clauses import verify_clause_anchors
from skills.legal import contract_skills
from skills.legal.contract_types import 判定类型
import parse_doc
from skills.legal.trace_citations import 执行 as trace_citations
from skills.legal.score_analysis import (
    validate_analysis_quality,
    generate_risk_list,
    compute_trust_score,
    是失败产物,
)

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
# 不设这个，上传口子的 `档.read()` 会把对方发过来的整个请求体读进内存 ——
# 20MB 那道检查读的是已经读完的字节，晚了。给到 25MB：合同上传限 20MB，留点余量。
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

# 管理面口令：没设这个环境变量时，/dashboard 与 /feedback-data 对**任何人**都不开
# （只对自己这台机器开）。这两个口子会跨用户汇总数据，早先是无条件公开的。
管理口令 = os.environ.get("ADMIN_TOKEN", "")


def _是能管后台():
    """本机直接放行；远程必须带对口令。口令用常量时间比较，不拿 == 比。"""
    if request.remote_addr in ("127.0.0.1", "::1"):
        return True
    import hmac
    给 = request.args.get("token") or request.headers.get("X-Admin-Token", "")
    # compare_digest 拒绝拿**非 ASCII 的 str** 比较（访客传 `?token=错` 就是 TypeError → 500）。
    # 编成 bytes 再比：不相等就是不相等，返回 403，而不是把异常抛到公网上。
    return (bool(管理口令) and isinstance(给, str)
            and hmac.compare_digest(给.encode("utf-8"), 管理口令.encode("utf-8")))


@app.after_request
def add_cors_headers(response):
    """原来这里无条件发 `Access-Control-Allow-Origin: *` —— 删掉，不发。

    同源部署（页面就是这个 app 渲染的）不需要任何 CORS 头。留着它唯一的用处是：
    挂到公网之后，任何别的网页都能拿着用户的 cookie 来读他的历史、替他提交反馈。
    """
    response.headers.pop("Access-Control-Allow-Origin", None)
    return response

# 项目根目录：app.py 在 python/ 里，往上一级就是项目根
项目根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
法条库目录 = os.environ.get("LAWS_DIR", os.path.join(项目根, "data/laws"))
数据根目录 = os.environ.get("DATA_DIR", os.path.join(项目根, "data/case_data"))


def _会话密钥():
    """session 签名密钥：环境变量优先，否则**落盘一份**复用。

    ⚠️ 原来这里是 `os.environ.get(...) or os.urandom(24).hex()` —— 每次起进程换一个。
    而 uid 就存在签了名的 session 里、并且**是用户数据目录的名字**（`用户数据目录`），
    所以密钥一变：历史、已存的报告、按人计的配额全部认不回来（文件还在盘上，但没人
    能再叫出那个目录名）。gunicorn 多 worker 时更糟 —— 各 worker 各签各的，
    同一个浏览器在请求之间被轮流拒签，等于每次访问都是新用户。
    """
    指定 = os.environ.get("FLASK_SECRET_KEY")
    if 指定:
        return 指定
    路径 = os.path.join(数据根目录, "session_secret.key")
    os.makedirs(数据根目录, exist_ok=True)
    try:
        with open(路径, encoding="utf-8") as f:
            存 = f.read().strip()
        if 存:
            return 存
    except FileNotFoundError:
        pass
    新 = os.urandom(24).hex()
    try:
        # O_EXCL：并发首启时谁先建谁说了算，后建的读那份 —— 不能各写各的
        with os.fdopen(os.open(路径, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                       "w", encoding="utf-8") as f:
            f.write(新)
    except FileExistsError:
        with open(路径, encoding="utf-8") as f:
            return f.read().strip() or 新
    return 新


app.secret_key = _会话密钥()

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

# 智能分段 → 已迁移到 skills/legal/_base.py

# 问AI → 已迁移到 skills/legal/_base.py

# 九个分析维度函数 → 已迁移到 skills/legal/ 对应模块
# 溯源对比/法条统计/法条库查询 → 已迁移到 skills/legal/verify_laws.py + trace_citations.py

# 构建判例索引 / 查关联判例 → 已移除。法条库仅1个文件，关联功能无数据支撑。

# 法条版本校验/风险列表/可信度评分 → 已迁移到 skills/legal/verify_laws.py + score_analysis.py

# 验证分析结果 → 已迁移到 skills/legal/score_analysis.py

# ---- 8. 存储 ----
# 这些键不属于"分析维度"，不能进卡片列表：前端把 分析 里的每个键都当一张卡渲染，
# 存进去就等于在报告页凭空多出一张「核验」卡。
元数据键 = ("判例名", "日期", "模式", "字数", "合同类型", "时间基准", "核验")


def _核验快照(可信度, 验证, 风险列表, 法条对照, 条款校验):
    """把此刻的核验读数压成一份可复盘的快照，跟着报告一起落盘。

    为什么必须存：原来只存分析文字，于是从历史打开一份旧报告时，页面上没有任何
    东西能说明"当时核到了多少、有几条对不上" —— 要么显示不出来，要么得现编一个
    "✅ 验证通过"（原来就是后者，见 详情路由）。存下来之后，历史页报的数就是
    当初那个数，而且这份报告第一次变得可以复盘（误指控率需要这个）。
    """
    return {
        "等级": 可信度.get("等级"),
        "覆盖度": 可信度.get("覆盖度"),
        "核验": 可信度.get("核验"),
        "格式检查": {"通过": 验证.get("通过"), "问题": 验证.get("问题", []),
                     "法条统计": 验证.get("法条统计", "")},
        "要核实": [p["内容"] for p in 风险列表 if p.get("等级") == "danger"],
        "边界说明": [p["内容"] for p in 风险列表 if p.get("等级") == "note"],
        "法条对照": 法条对照 or [],
        "条款校验": ({k: v for k, v in 条款校验.items() if not isinstance(v, list)}
                    if 条款校验 else None),
    }


def _写判决JSON(判例名, 数据):
    """三种模式共用的落盘：文件名一律过 安全名，不给 "/" 和 ".." 留通路。"""
    文件夹 = 用户数据目录()
    今天 = str(date.today())
    文件名 = os.path.join(文件夹, f"{今天}_{_安全名(判例名)}.json")
    os.makedirs(文件夹, exist_ok=True)
    with open(文件名, "w", encoding="utf-8") as f:
        json.dump(数据, f, ensure_ascii=False)
    return 文件名


def _安全名(判例名):
    return 判例名.replace("/", "_").replace("..", "_").replace("\x00", "_") or "未命名"


def _存储判决JSON(判例名, 结构, 争议, 推理, 法条精析, 对立路径, 论证检查, 程序问题, 未答, 核验=None):
    return _写判决JSON(判例名, {
        "判例名": 判例名, "日期": str(date.today()), "模式": "判决书分析",
        "结构化摘要": 结构, "核心争议": 争议,
        "推理链路": 推理, "法条适用精析": 法条精析,
        "对立解释路径": 对立路径, "论证完整性检查": 论证检查,
        "程序问题识别": 程序问题, "未回答问题": 未答,
        "核验": 核验,
    })

def _存储合同JSON(判例名, 合同类型, 分析结果, 核验=None, 时间基准=None, 字数=0):
    return _写判决JSON(判例名, {
        "判例名": 判例名, "日期": str(date.today()), "模式": "合同审查",
        "合同类型": 合同类型, "时间基准": 时间基准, "字数": 字数,
        **分析结果, "核验": 核验,
    })

def _存储案情JSON(判例名, 法律关系, 事实证据, 对抗路径, 风险推演, 行动建议, 总结, 核验=None):
    return _写判决JSON(判例名, {
        "判例名": 判例名, "日期": str(date.today()), "模式": "案情分析",
        "法律关系": 法律关系, "事实与证据": 事实证据,
        "对抗路径": 对抗路径, "风险推演": 风险推演,
        "行动建议": 行动建议, "总结": 总结,
        "核验": 核验,
    })


@app.route("/parse-doc", methods=["POST"])
def 解析文档路由():
    """上传 docx/pdf/txt → 解析成带【第N条】锚点的文本，填回前端的文本框。

    只解析、不分析、不计次数。刻意不把分析也做了：让用户先看见解析出来的文本长什么样，
    扫描件/表格型合同这类解析质量差的情况能被**人眼当场发现**，而不是让模型对着
    一份空文本编出一份像模像样的风险清单。
    """
    档 = request.files.get("file")
    if 档 is None or not 档.filename:
        return jsonify({"error": "没收到文件"}), 400
    字节 = 档.read()
    if len(字节) > 20 * 1024 * 1024:
        return jsonify({"error": "文件超过 20MB"}), 400
    出 = parse_doc.解析(字节, 档.filename)
    if 出['错误']:
        return jsonify({"error": 出['错误']}), 400
    return jsonify({"文本": 出['文本'], "条数": 出['条数'], "警告": 出['警告']})


# ---- 9. 每日次数限制 ----
# 0 = 不限。这个上限是给**陌生访客**准备的：线上部署时防止别人拿你的 key 刷钱。
# 本机访问（socket 对端是 127.x / ::1）不受它管 —— 见下面 是本机访问()。
每日上限 = int(os.environ.get("DAILY_LIMIT", "20"))
# 只有确认前面挂了反向代理时才读 X-Forwarded-For；直连时那个头是客户端自己写的。
信任代理头 = os.environ.get("USE_PROXY_HEADERS") == "1"

def 获取客户端IP():
    """限流用的客户端地址：以 **socket 对端** 为准。

    ⚠️ 原来无条件优先取 `X-Forwarded-For` —— 那是客户端可以自己编的请求头，
    等于任何人都能靠换一个头把自己的配额刷新成无限，这个上限就只剩装饰作用。
    确实挂在反代后面时（USE_PROXY_HEADERS=1）才读它，并且取**最右**一跳：
    那一跳是你自己的代理追加的，外面伪造不了。
    """
    if 信任代理头:
        列 = [x.strip() for x in request.headers.get("X-Forwarded-For", "").split(",") if x.strip()]
        if 列:
            return 列[-1]
    return request.remote_addr or "未知IP"

def 是本机访问():
    """作者自己在这台机器上用，不该被"防陌生人"的门挡住。

    只看 `request.remote_addr`，**不看 X-Forwarded-For** —— 否则一个头就能从外面
    冒充本机、把配额整个绕过去。
    """
    地址 = request.remote_addr or ""
    return 地址 == "::1" or 地址.startswith("127.")

def 不限次():
    """这一路请求要不要计次。两种豁免：显式关掉上限（DAILY_LIMIT=0），或本机访问。

    限流是给**陌生访客**准备的（防止线上被人拿你的 key 刷钱）。作者自己在这台
    机器上调试时，它只会变成"每改一次提示词就只能试 20 次"这种纯摩擦 ——
    而本机浏览器和测试客户端的 socket 对端都是 127.0.0.1，正是被误伤的那一批。
    """
    return 每日上限 <= 0 or 是本机访问()

def 剩余次数查询(uid, ip):
    """仅查询剩余次数，不消耗。返回 {'剩余': int|None, '上限': int|None}
    —— None = 这一路不受限（本机访问，或 DAILY_LIMIT=0）。"""
    if 不限次():
        return {"剩余": None, "上限": None}
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
    if 不限次():
        return True         # 不写计数文件：本机调试不该往盘上堆当天没用的计数
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

@app.route("/report")
def 报告页():
    return render_template("report.html")

@app.route("/cover")
def 封面页():
    return render_template("cover.html")

@app.route("/analyze", methods=["POST"])
def 分析路由():
    """编排层：按顺序调度技能库中的分析技能，组装JSON返回"""
    # ── 限流 & 校验 ──
    uid = 获取用户ID()
    ip = 获取客户端IP()
    # 先确认服务端能干活，再扣次数：原来先扣后查 key，配置缺失时
    # 每次请求都白烧一次配额，而用户看到的是"次数用完了"，原因却在服务端。
    # 只有一个端点：`_base.问AI` 打的是 api.deepseek.com。原来这里还兜底读
    # ANTHROPIC_AUTH_TOKEN —— Anthropic 的 token 发给 DeepSeek 必然 401，
    # 而报错会把人指向错的方向（"我明明配了 key"）。要接第二家得先有
    # provider 表（名字→地址/模型名/取哪个 env），别在这里靠 or 猜。
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return jsonify({"error": "服务端未设置 DEEPSEEK_API_KEY 环境变量"
                                 "（本机可放 python/.env，部署方在进程环境里给）"}), 500

    # ── 先把请求本身验完，再扣次数 ──
    # 顺序很要紧：扣次数是**有副作用**的一步，而"名称过长/正文太短/不像判决书"
    # 都是客户端一句就能改对的事。原来这些校验排在 消耗次数 之后，
    # 于是一次打错字的请求、一个非 JSON 的请求体，都白烧用户一天一次的配额
    # （实测：探测用的短文本被 400 挡下，次数照样少了一次）。
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体不是一份 JSON 对象"}), 400
    判例名 = (data.get("name") or "").strip()
    判例 = (data.get("text") or "").strip()
    分析模式 = data.get("mode", "judgment")  # judgment=判决书 case=案情分析 contract=合同审查
    # 报错文案是给**贴这份文件的人**看的：审合同的人被告知"判例文字太短"，会先愣一下
    # 再怀疑自己走错了工具。同一个字段内部仍叫 判例（键名不动，见 元数据键）。
    份 = {"contract": "合同", "case": "案情"}.get(分析模式, "判例")
    子模式 = data.get("submode", "read")
    # 案发时间：可选。不填只是"时效这一维没校验"（校验层会把它算进未校验，等级封顶在 中），
    # 填了但读不懂也一样封 —— 区别只在于要出声告诉用户他填坏了。
    # 这里原样透传：认不认、截多长都由 规范案发日期 判，别在边界上再实现一遍校验。
    案发时间 = data.get("case_date")

    if len(判例名) > 80:
        return jsonify({"error": f"{份}名称过长（最多80字）"}), 400
    if len(判例) < 50:
        return jsonify({"error": f"{份}文字太短（少于50字），请把{份}内容完整贴进来 —— "
                                 f"只看开头一段，「没写的那部分」和「没找到」是两回事"}), 400
    # 截断必须说出来：合同审查里"没看到的那部分"恰恰可能藏着缺的条款。
    # 不标的话，后段条款在界面上与"合同里没有"长得一模一样。
    被截断 = len(判例) > 15000
    判例 = 判例[:15000]

    # 输入类型检测：非判决书/案情文本拒绝分析
    if 分析模式 == "judgment":
        judgment_keywords = ["法院", "判决", "原告", "被告", "裁定", "本院", "审理", "诉称", "辩称"]
        if not any(kw in 判例 for kw in judgment_keywords[:4]):
            return jsonify({"error": "输入文本不像判决书。判决书通常包含'原告''被告''法院'等主体信息。如确为判决书请继续；如为案情咨询请切换至'案情分析'模式。"}), 400

    if not 消耗次数(uid, ip):
        剩余 = 剩余次数查询(uid, ip)
        return jsonify({"error": f"今日分析次数已用完（每人{每日上限}次），请明天再来。", "剩余": 0, "上限": 每日上限}), 429


    # 合同模式才有的变量，先给默认值 —— 下面那段校验就不用到处判模式
    条款表, 无条号警告, 合同类型, 类型得分 = {}, [], "", {}
    各维输出, 锚点范围 = {}, []

    try:
        if 分析模式 == "case":
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    "法律关系识别": executor.submit(identify_relationship.执行, 判例, api_key),
                    "事实与证据评估": executor.submit(assess_facts_evidence.执行, 判例, api_key),
                    "对抗路径分析": executor.submit(analyze_opposing_paths.执行, 判例, api_key),
                    "风险推演": executor.submit(project_risks.执行, 判例, api_key),
                    "行动建议": executor.submit(suggest_actions.执行, 判例, api_key),
                }
                结果 = {}
                for name, f in futures.items():
                    try: 结果[name] = f.result()
                    except Exception as e: 结果[name] = f"【{name}失败】{str(e)[:200]}"
            法律关系 = 结果["法律关系识别"]
            事实证据 = 结果["事实与证据评估"]
            对抗路径 = 结果["对抗路径分析"]
            风险推演 = 结果["风险推演"]
            行动建议 = 结果["行动建议"]
            try: 总结 = summarize_case.执行(判例, 法律关系, 事实证据, 对抗路径, 风险推演, 行动建议, api_key)
            except Exception as e: 总结 = f"【总结失败】{str(e)[:200]}"
            全部分析 = [法律关系, 事实证据, 对抗路径, 风险推演, 行动建议]
            各维输出 = {"法律关系": 法律关系, "事实与证据": 事实证据, "对抗路径": 对抗路径,
                        "风险推演": 风险推演, "行动建议": 行动建议, "总结": 总结}
        elif 分析模式 == "contract":
            # 锚点表**服务端现算**：只从即将喂给模型的这份文本里派生。
            # 收客户端传来的条款表，等于让它自己声明「我每条都对得上」。
            带锚点文本, 条款表, 条数, 无条号警告 = parse_doc.规范化(判例)
            合同类型, 类型得分 = 判定类型(带锚点文本)
            判例 = 带锚点文本
            # 前 4 维并行，谈判顺序在它们之后（见下方注释）；这里只列并行的那 4 个
            维度 = {
                "风险清单": contract_skills.风险清单,
                "缺失条款": contract_skills.缺失条款,
                "失衡条款": contract_skills.失衡条款,
                "歧义表述": contract_skills.歧义表述,
            }
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {名: executor.submit(fn, 判例, 合同类型, api_key)
                           for 名, fn in 维度.items()}
                结果 = {}
                for 名, f in futures.items():
                    try: 结果[名] = f.result()
                    except Exception as e: 结果[名] = f"【{名}失败】{str(e)[:200]}"
            # 顺序：四维并行 → [改法建议 ∥ 新增条款] → 谈判顺序 → 总结。
            # 后三维的提示词写的都是"把上面几类问题……"，并行发出去等于让每一段自己想象
            # 上文（谈判顺序 单独踩过这个坑：它当时和前四维并行，只能另拟一套清单）。
            # 改法建议 与 新增条款 互不依赖 —— 一个改已有的条，一个补没有的条，所以同波并行。
            第二波 = {"改法建议": contract_skills.改法建议, "新增条款": contract_skills.新增条款}
            with ThreadPoolExecutor(max_workers=2) as executor:
                上波 = dict(结果)
                二波 = {名: executor.submit(fn, 判例, 合同类型, api_key, 已有=dict(上波))
                        for 名, fn in 第二波.items()}
                for 名, f in 二波.items():
                    try: 结果[名] = f.result()
                    except Exception as e: 结果[名] = f"【{名}失败】{str(e)[:200]}"
            try:
                结果["谈判顺序"] = contract_skills.谈判顺序(判例, 合同类型, api_key, 已有=dict(结果))
            except Exception as e:
                结果["谈判顺序"] = f"【谈判顺序失败】{str(e)[:200]}"
            全部分析 = [结果[k] for k in list(维度) + ["改法建议", "新增条款", "谈判顺序"]]
            # ⚠️ 逐条回查的范围**不含 新增条款**：那一维给的是合同里还不存在的整条新文字，
            # 拿现有条款表去比它，等于对正确输出亮红牌。它引用的法条仍走 法条库校验。
            锚点范围 = [结果[k] for k in list(维度) + ["改法建议", "谈判顺序"]]
            try:
                总结 = contract_skills.总结(判例, 合同类型, 结果, api_key)
            except Exception as e:
                总结 = f"【总结失败】{str(e)[:200]}"
            各维输出 = dict(结果, 总结=总结)
        else:
            tasks = {"结构化摘要": structure_summary, "程序问题识别": identify_procedural_issues}
            if 子模式 == "audit":
                tasks.update({"未回答问题": find_unanswered, "对立解释路径": find_opposing_paths, "论证完整性检查": audit_argument_integrity})
            else:
                tasks.update({"核心争议": extract_dispute, "推理链路": extract_reasoning, "法条适用精析": analyze_law_application})
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {name: executor.submit(fn.执行, 判例, api_key) for name, fn in tasks.items()}
                结果 = {}
                for name, f in futures.items():
                    try: 结果[name] = f.result()
                    except Exception as e: 结果[name] = f"【{name}失败】{str(e)[:200]}"
            结构 = 结果.get("结构化摘要", "")
            争议 = 结果.get("核心争议", "")
            推理 = 结果.get("推理链路", "")
            未答 = 结果.get("未回答问题", "")
            法条精析 = 结果.get("法条适用精析", "")
            对立路径 = 结果.get("对立解释路径", "")
            论证检查 = 结果.get("论证完整性检查", "")
            程序问题 = 结果.get("程序问题识别", "")
            总结 = 结构
            全部分析 = [争议, 推理, 未答, 法条精析, 对立路径, 论证检查, 程序问题]
            各维输出 = dict(结果, 总结=总结)
    except Exception as e:
        return jsonify({"error": f"分析过程异常: {str(e)[:300]}"}), 500

    if not 判例名:
        # 从案情原文提取关键词作名称
        patterns = [
            r'(?:原被告|双方|当事人)?[因涉].{2,12}(?:纠纷|争议|合同|案件)',
            r'(?:原告|申请人).{2,6}(?:诉|申请).{2,6}(?:纠纷|案)',
            r'.{2,8}(?:合同|借贷|买卖|租赁|合伙|侵权|劳动|婚姻|继承|房产)纠纷',
        ]
        for p in patterns:
            m = re.search(p, 判例)
            if m:
                判例名 = m.group()[:30].replace(" ", "")
                break
        if not 判例名:
            判例名 = 判例[:30].replace(" ", "").replace("\n", "") or "未命名"

    # ── 本地校验层（各模式共用，判据只算一次）──
    # classify_law_citations / verify_clause_anchors 各自是其维度的唯一出口，
    # 风险列表与可信度评分都读结果，不各自判断真伪。
    法条校验 = classify_law_citations(法条库目录, 案发时间, *全部分析)
    法条对照 = 法条校验["可验证"]          # 前端沿用这个键，契约不变
    条款校验 = verify_clause_anchors(条款表, *锚点范围) if 分析模式 == "contract" else None
    审查警告 = list(无条号警告)
    if 分析模式 == "contract":
        # 一维被排除在逐条回查之外，必须自己说出来 —— 不然读者以为"62 处全核过了"
        # 里面包含那份要新增的条款。它没有原文可核，这是范围问题，不是漏核。
        审查警告.append(f"『{叫法('新增条款')}』那一维给的是合同里**还不存在**的新文字，"
                        "没有原文可逐字比对，因此不在逐条回查范围内"
                        "（不是没核到，是没有可核的东西）；它引用的法律条文仍然走法条库校验")
    if 分析模式 == "contract" and 被截断:
        审查警告.append(f"合同超出 {15000} 字的部分未参与本次审查 —— "
                        f"『没找到某条款』在截断范围内不成立")
    # "通用" 是一张兜底表，不是判出来的类型。它决定"缺失条款"这一维照着哪张清单查，
    # 判成通用却不说，等于用一张放之四海皆准的表报"你合同里缺这缺那"。
    if 分析模式 == "contract" and 合同类型 == "通用":
        命中 = {类: 分 for 类, 分 in 类型得分.items() if 分}
        审查警告.append("没能确定合同类型（" +
                        (f"特征词命中：{'、'.join(f'{类}{分}词' for 类, 分 in 命中.items())}"
                         if 命中 else "一类特征词都没命中") +
                        "），改按通用清单查『缺了哪一条』—— 这类结论的针对性比专用清单低")
    # 前 4 位对应 全部分析[:4]，第 5 位对应被单独检查的 总结（判决书模式下它是"结构化摘要"）
    段落名 = {"case": ["法律关系", "事实与证据", "对抗路径", "风险推演", "总结"],
              "contract": ["风险清单", "缺失条款", "失衡条款", "歧义表述", "总结"],
              }.get(分析模式, ["核心争议", "推理链路", "未回答问题", "法条适用精析", "总结（结构化摘要）"])
    验证 = validate_analysis_quality(*全部分析[:4], 总结, count_law_citations, 段落名=段落名)
    # ⚠️ 上面那只检查只看 5 个槽位，而一次分析最多有 6 路输出（合同的谈判顺序是第 6 路、
    # 案情的"行动建议"、判决的"程序问题识别"都不在槽位里）。哪一路返回的是 API 失败
    # 产物，就得在哪一路出声 —— 否则一段 `{"error": true…}` 会原样躺在报告里当内容。
    失败维 = [名 for 名, 文 in 各维输出.items() if 是失败产物(文)]
    if 失败维:
        验证["通过"] = False
        验证["问题"].append("这些维度返回的是 API 失败产物、不是分析内容："
                            + "、".join(f"『{名}』" for 名 in 失败维))
    # 段号溯源只有判决书模式做得到（合同按条号锚点核，案情压根没有原文段号可引）。
    # 原来合同模式也回一句"案情模式不适用段号溯源；合同模式按条号锚点校验" ——
    # 于是审合同的人点开那一栏，看到的是一句在跟他解释**另一个模式**的话。
    # 没有内容就回 null，前端那一栏直接不出现；案情留一句，是因为它确实少了一维。
    溯源 = (None if 分析模式 == "contract"
            else {"warning": "案情分析没有判决书原文可回查，这一维不适用；"
                             "能核的是法条那一部分（见下方法条库对照）"}
            if 分析模式 == "case"
            else trace_citations(判例, *全部分析))

    # ── 组装返回 ──
    剩余 = 剩余次数查询(uid, ip)
    # 合同读者看到"案发"两个字会以为自己在被打官司 —— 同一个基准日在这条链路上叫签署日
    时间词 = "签署" if 分析模式 == "contract" else "案发"
    可信度 = compute_trust_score(验证, 法条校验, 溯源, 条款校验=条款校验, 时间词=时间词)
    风险列表 = generate_risk_list(验证, 法条校验, 溯源, 条款校验=条款校验, 时间词=时间词)
    for 警 in 审查警告:
        风险列表.append({"等级": "note", "内容": 警})
    核验 = _核验快照(可信度, 验证, 风险列表, 法条对照, 条款校验)

    if 分析模式 == "contract":
        分析结果 = {名: 结果[名] for 名 in ("风险清单", "缺失条款", "失衡条款", "歧义表述",
                                        "改法建议", "新增条款", "谈判顺序")}
        分析结果["总结"] = 总结
        _存储合同JSON(判例名, 合同类型, 分析结果, 核验=核验,
                     时间基准=法条校验.get("案发日期") or 案发时间, 字数=len(判例))
    elif 分析模式 == "case":
        分析结果 = {
            "法律关系": 法律关系, "事实与证据": 事实证据,
            "对抗路径": 对抗路径, "风险推演": 风险推演,
            "行动建议": 行动建议, "总结": 总结,
        }
        _存储案情JSON(判例名, 法律关系, 事实证据, 对抗路径, 风险推演, 行动建议, 总结, 核验=核验)
    else:
        分析结果 = {
            "结构化摘要": 结构, "核心争议": 争议,
            "推理链路": 推理, "法条适用精析": 法条精析,
            "对立解释路径": 对立路径, "论证完整性检查": 论证检查,
            "程序问题识别": 程序问题, "未回答问题": 未答,
        }
        _存储判决JSON(判例名, 结构, 争议, 推理, 法条精析, 对立路径, 论证检查, 程序问题, 未答,
                     核验=核验)

    return jsonify({
        "判例名": 判例名,
        "字数": len(判例),
        "剩余次数": 剩余["剩余"],
        "今日上限": 剩余["上限"],
        "分析": 分析结果,
        "溯源": 溯源,
        "法条对照": 法条对照,
        "验证": 验证,
        "可信度": 可信度,
        "风险列表": 风险列表,
        # 三态读数（可验证那一份已经在上面的 法条对照 里，别重复塞进响应）
        "法条校验": {k: v for k, v in 法条校验.items() if k != "可验证"},
        # 合同模式专有：条款锚点三态 + 类型 + 条数（类型判不准时是"通用"，照实说）
        "条款校验": ({k: v for k, v in 条款校验.items()} if 条款校验 else None),
        "合同类型": 合同类型, "条数": len([k for k in 条款表 if k != '前言']),
        # 键名 → 人话：下载件在这里翻译，前端用它自己的那份表（测试核对两边覆盖一致）。
        # 为什么后端也要带一份：`/download` 收到的就是 分析 那个 dict，翻译不在这里做
        # 就得在客户端做，而客户端翻译过的东西存进盘里还是行话。
        "分析人话": {k: 叫法(k) for k in 分析结果},
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
    for fname in files:
        # 同一个目录里还住着别的 json：`limit_日期.json` 是当天的次数表。
        # 不排掉的话它会被当成一份"判例"列出来（按倒序它甚至排在最前），
        # 点开就是一张内容为空的假报告。
        if not fname.endswith(".json") or fname.startswith(("limit_", "session_secret")):
            continue
        if len(结果) >= 20:
            break
        try:
            with open(os.path.join(文件夹, fname), encoding="utf-8") as f:
                d = json.load(f)
            结果.append({
                "文件名": fname,
                "判例名": d.get("判例名", ""),
                "日期": d.get("日期", ""),
                "模式": d.get("模式", ""),
                "总结": d.get("总结", "")[:120]
            })
        except Exception:
            pass
    return jsonify(结果)


@app.route("/case/<fname>")
def 详情路由(fname):
    """打开一份存下来的报告。

    ⚠️ 这里原来在数据缺失时**现编一个"验证通过"**：
        `"验证": {"通过": True, "问题": [], "法条统计": "历史存档数据"}, "可信度": None`
    于是从历史打开任何一份旧报告，页面都亮一条绿勾，而这次打开一次校验都没做 ——
    一份当时"0 条对不上"的报告和一份当时"7 条对不上"的报告看起来一模一样。
    现在只有当时存下了核验快照才报数；没存下就明说没数（`验证: None` →
    前端渲染成"这次打开没有重跑校验"）。
    """
    文件夹 = 用户数据目录()
    路径 = os.path.realpath(os.path.join(文件夹, fname))
    if ".." in fname or not 路径.startswith(os.path.realpath(文件夹) + os.sep):
        return jsonify({"error": "文件不存在"}), 404
    if not os.path.exists(路径):
        return jsonify({"error": "文件不存在"}), 404
    try:
        with open(路径, encoding="utf-8") as f:
            d = json.load(f)
        核验 = d.get("核验")
        # 通用格式：从存储数据提取所有分析字段（元数据键不算分析维度，别渲染成卡片）
        分析字段 = {k: v for k, v in d.items() if k not in 元数据键}
        return jsonify({
            "判例名": d.get("判例名", ""),
            "字数": d.get("字数", 0),
            "模式": d.get("模式", ""),
            "合同类型": d.get("合同类型", ""),
            "分析": 分析字段,
            "溯源": None,
            "法条对照": (核验 or {}).get("法条对照") or None,
            "验证": (核验 or {}).get("格式检查"),
            "可信度": ({"等级": 核验["等级"], "覆盖度": 核验["覆盖度"], "核验": 核验["核验"],
                        "明细": [], "已校验数": 0, "未校验数": 0}
                       if 核验 and 核验.get("核验") else None),
            "风险列表": ([{"等级": "danger", "内容": x} for x in (核验 or {}).get("要核实", [])]
                        + [{"等级": "warning", "内容": x}
                           for x in ((核验 or {}).get("格式检查") or {}).get("问题", [])]
                        + [{"等级": "note", "内容": x} for x in (核验 or {}).get("边界说明", [])])
                           if 核验 else [],
        })
    except Exception:
        return jsonify({"error": "读取失败"}), 500

# 内部键名 → 给人看的叫法。前端有一份同名的表（index.html 的 人话标题），
# 两份都要对得上，测试 tests/test_report_presentation.py 逐个模式核一遍键覆盖。
人话标题 = {
    "结构化摘要": "这份文件在说什么", "核心争议": "双方在争什么", "推理链路": "法院是怎么推的",
    "法条适用精析": "依据的是哪几条法律", "程序问题识别": "程序上有没有问题",
    "未回答问题": "这份判决没说清的", "对立解释路径": "对方还能怎么解释", "论证完整性检查": "说理有没有说圆",
    "法律关系": "你们之间是什么关系", "事实与证据": "手上有什么证据", "对抗路径": "双方会怎么争",
    "风险推演": "可能发生什么坏事", "行动建议": "接下来可以做什么",
    "风险清单": "哪些条款对你不利", "缺失条款": "合同里没写的", "失衡条款": "权利义务不对等的",
    "歧义表述": "写得含糊、日后会吵的", "谈判顺序": "先争哪条、后让哪条", "总结": "一句话结论",
    "改法建议": "改成这样（可直接替换）", "新增条款": "缺的条款，补这么写",
    "合同类型": "我们把它当成哪类合同",
}


def 叫法(键):
    return 人话标题.get(键, 键)


@app.route("/download", methods=["POST"])
def 下载路由():
    """把分析结果转成可下载的文本报告（通用）。

    下载件是拿去**给别人看**的（律师、HR、对方），所以必须带上核验读数：
    只带分析文字的话，看的人无从知道这份东西核对过什么、没核对什么。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        # 不给个默认的 {}：那等于"传错了也给你出一份空报告"，用户拿到手还以为下载成功了
        return jsonify({"error": "请求体不是一份 JSON 对象"}), 400
    头 = f"""法律分析报告
{'='*50}
名称：{data.get('判例名', '')}
日期：{date.today()}
"""
    # 读数排在正文之前：拿给别人看的时候，第一屏就该说清这份东西凭什么可信、
    # 以及哪些地方工具没核过。
    核 = data.get('核验读数') or {}
    if 核 or data.get('等级'):
        头 += f"""
这份报告核对到什么程度
{'─'*40}
可信度等级：{data.get('等级') or '未评'}"""
        if 核:
            头 += (f"\n依据共 {核.get('引用总数', '?')} 处："
                   f"逐条核到原文 {核.get('核到', 0)} 处"
                   f"、对不上 {核.get('对不上', 0)} 处"
                   f"、没法核 {核.get('没法核', 0)} 处"
                   f"（其中 {核.get('库外', 0)} 处是本工具没收录的法律）")
        if data.get('覆盖度') is not None:
            头 += f"\n核对覆盖：{round(data['覆盖度'] * 100)}%"
    for 标题, 键 in (("要你人去核实的", '待核实'), ("本工具的覆盖边界（不代表结论有误）", '工具边界')):
        列 = data.get(键) or []
        if 列:
            头 += f"\n\n{标题}\n{'─'*40}\n" + "\n".join(f"· {x}" for x in 列)

    跳过 = {'判例名', '法条统计', '法条对照', '溯源', '核验读数', '覆盖度', '等级',
            '待核实', '工具边界'}
    正文 = ""
    for key, val in data.items():
        if key in 跳过 or not val or isinstance(val, (dict, list)):
            continue
        正文 += f"""

{叫法(key)}
{'─'*40}
{val}
"""
    附录 = ""
    if data.get('法条统计'):
        附录 += f"\n\n法条统计\n{'─'*40}\n{data['法条统计']}\n"
    for 条目 in (data.get('法条对照') or []):
        if not isinstance(条目, dict):
            continue
        附 = []
        if 条目.get('施行日期'):
            附.append(f"施行: {条目['施行日期']}")
        if 条目.get('取代'):
            附.append(条目['取代'])
        附录 += (f"\n【{条目.get('法名', '')}】{条目.get('引用', '')}"
                 f"（{条目.get('状态') or '状态未知'}）"
                 + (f" {' · '.join(附)}" if 附 else "")
                 + f"\n{条目.get('条文', '')}\n")
    溯源块 = ""
    溯源数据 = data.get('溯源') if isinstance(data.get('溯源'), dict) else {}
    for item in (溯源数据.get('items') or []):
        mark = "" if item.get('有效') else "⚠️ 原文里没有这一段："
        溯源块 += f"\n{mark}原文第{item.get('段号', '')}段：\n{item.get('内容', '')}\n"
    if 附录 or 溯源块:
        附录 = f"\n\n核到的法条原文\n{'─'*40}\n{附录}{溯源块}"

    报告 = 头 + 正文 + 附录 + f"""

{'='*50}
本报告由「判例助手」自动生成 | {date.today()}
它做的事情只有一件：把报告里引用的每一条法律、每一段合同原文拿回去逐字核对。
它没有判断法律结论对不对，也看不到你手上的完整材料。
真要签字或真要打官司之前，请带原件找执业律师核实。
"""
    from flask import Response
    return Response(
        报告,
        mimetype="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=report.txt",
            "Content-Type": "text/plain; charset=utf-8"
        }
    )

def _列表内字符串(值, 上限=20):
    """客户端传来的"模块名列表"：只留字符串、去重、截上限。非列表 → 空。"""
    if not isinstance(值, list):
        return []
    出 = []
    for x in 值:
        if isinstance(x, str) and x.strip() and x.strip() not in 出:
            出.append(x.strip()[:60])
    return 出[:上限]


@app.route("/feedback", methods=["POST"])
def 反馈路由():
    """接收结构化反馈：有帮助程度 + 用得上/希望删掉的模块 + 问题类型 + 可选文字。

    ⚠️ 原来文件名是 `f"{今天}_{判例名}_反馈.json"`：同一天两个人对同名合同（"劳动合同"
    是最常见的那种）提交反馈，**后一条会把前一条原地覆盖掉**，而且是静默的。
    这份问卷是决定下一版砍哪个模块的唯一输入，丢一条就是丢一票。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体不是一份 JSON 对象"}), 400
    有帮助程度 = data.get("helpfulness", "")
    if 有帮助程度 not in ("very", "somewhat", "little", "none"):
        return jsonify({"error": "请先选一下这份结果对你有帮助吗"}), 400

    判例名 = data.get("case_name")
    判例名 = 判例名.strip()[:80] if isinstance(判例名, str) and 判例名.strip() else "未命名"
    备注 = data.get("comment", "")
    备注 = 备注.strip()[:2000] if isinstance(备注, str) else ""
    分析日期 = data.get("date")
    if not (isinstance(分析日期, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', 分析日期)):
        分析日期 = str(date.today())

    反馈数据 = {
        "判例名": 判例名,
        "分析日期": 分析日期,
        "有帮助程度": 有帮助程度,
        "最有价值模块": _列表内字符串(data.get("most_valuable")),
        "最没用模块": _列表内字符串(data.get("least_valuable")),
        "问题类型": _列表内字符串(data.get("issue_types"), 上限=5),
        "备注": 备注,
        "提交时间": str(date.today()),
    }

    反馈目录 = os.path.join(用户数据目录(), "feedback")
    os.makedirs(反馈目录, exist_ok=True)
    # 名字里带微秒时间戳而不是"当天第几条"：数条数再 +1 在并发下会撞（两个请求读到
    # 同一个数），而这条链路的整个主题就是"别让反馈静默丢掉"。
    戳 = datetime.now().strftime("%H%M%S-%f")
    文件名 = f"{date.today()}_{戳}_{_安全名(判例名)}_反馈.json"
    with open(os.path.join(反馈目录, 文件名), "w", encoding="utf-8") as f:
        json.dump(反馈数据, f, ensure_ascii=False)
    return jsonify({"ok": True, "message": "感谢反馈！"})


def _收集反馈(uids):
    全部 = []
    for uid in uids:
        反馈目录 = os.path.join(数据根目录, uid, "feedback")
        if not os.path.isdir(反馈目录):
            continue
        for fname in sorted(os.listdir(反馈目录), reverse=True):
            try:
                with open(os.path.join(反馈目录, fname), encoding="utf-8") as f:
                    d = json.load(f)
                d["用户ID"] = uid[:8]
                全部.append(d)
            except Exception:
                pass
    return 全部


@app.route("/feedback-data")
def 反馈数据路由():
    """跨用户汇总 —— 所以它得把门。没设 ADMIN_TOKEN 时只对本机开。"""
    if not _是能管后台():
        return jsonify({"error": "需要管理权限（本机直接访问，或带 ?token=ADMIN_TOKEN）"}), 403
    if not os.path.exists(数据根目录):
        return jsonify({"总数": 0, "反馈": []})
    全部 = _收集反馈(os.listdir(数据根目录))
    from flask import Response
    return Response(
        json.dumps({"总数": len(全部), "反馈": 全部[-50:]}, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8"
    )


@app.route("/my-feedback")
def 我的反馈路由():
    """给普通用户看**自己**交过什么 —— 原来唯一的口子是跨用户的 /feedback-data，
    想"我能不能看到自己的反馈"只能把管理口子的地址给他，那就变成所有人都能看别人的。
    """
    uid = 获取用户ID()
    全部 = _收集反馈([uid])
    return jsonify({"总数": len(全部), "反馈": 全部[-20:]})


@app.route("/dashboard")
def 后台面板():
    """访问量统计。跨用户汇总 —— 和管理口一样把门，没设 ADMIN_TOKEN 时只对本机开。"""
    if not _是能管后台():
        return jsonify({"error": "需要管理权限（本机直接访问，或带 ?token=ADMIN_TOKEN）"}), 403
    # ⚠️ 原来只有两个桶，第二个是 else 兜底："判决书分析"。合同审查模式上线之后，
    # 每一份合同报告都被算进"判决书分析"里 —— 也就是说这个看板上唯一和现在产品
    # 对得上的数字，从第一天起就是错的。改成按 模式 字段逐个点名。
    分模式 = {"合同审查": 0, "案情分析": 0, "判决书分析": 0}
    分析总数 = 0
    用户集合 = set()
    if os.path.exists(数据根目录):
        for uid in os.listdir(数据根目录):
            user_dir = os.path.join(数据根目录, uid)
            if not os.path.isdir(user_dir):
                continue
            用户集合.add(uid)
            for fname in os.listdir(user_dir):
                if not fname.endswith(".json") or fname.startswith(("limit_", "session_secret")):
                    continue
                分析总数 += 1
                try:
                    with open(os.path.join(user_dir, fname), encoding="utf-8") as f:
                        d = json.load(f)
                    名 = d.get("模式") or "未标注"
                    分模式[名] = 分模式.get(名, 0) + 1
                except Exception:
                    pass
    全部反馈 = _收集反馈(os.listdir(数据根目录)) if os.path.exists(数据根目录) else []
    有帮助 = sum(1 for x in 全部反馈 if x.get("有帮助程度") in ("very", "somewhat"))
    from flask import Response
    return Response(
        json.dumps({
            "分析总数": 分析总数,
            "分模式": 分模式,
            "用户数": len(用户集合),
            "反馈数": len(全部反馈),
            "反馈觉得有帮助": 有帮助,
            # 这两项是决定"要不要砍掉某个模块"的直接输入，原来得自己去翻文件
            "被点名要删的模块": _计数(全部反馈, "最没用模块"),
            "被点名有用的模块": _计数(全部反馈, "最有价值模块"),
        }, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8"
    )


def _计数(反馈列表, 键):
    计 = {}
    for x in 反馈列表:
        for 模块 in (x.get(键) or []):
            计[模块] = 计.get(模块, 0) + 1
    return dict(sorted(计.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    地址 = os.environ.get("BIND_HOST", "127.0.0.1")
    端口 = int(os.environ.get("PORT", "5050"))
    print(f"判例助手网页版已启动 → http://{地址}:{端口}")
    # 原来这里写死 host="0.0.0.0" —— 在这台机器上一启动，局域网里任何人都能打开它，
    # 而 是本机访问() 就不再豁免，等于把自己的开发服务挂成了公网服务。
    # 要给别人访问时自己说：BIND_HOST=0.0.0.0。
    app.run(debug=True, host=地址, port=端口)
