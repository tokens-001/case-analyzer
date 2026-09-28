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
from urllib.parse import quote

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
import report_render
import contract_revise
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
# ⚠️ `立场` 也在里面：它和 `时间基准` 一样是**关于这份报告本身的元信息**，
# 不是分析维度 —— 漏了它，报告页会凭空多出一张「立场」卡片。
元数据键 = ("判例名", "日期", "模式", "字数", "合同类型", "时间基准", "立场", "核验")


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
        # 🔴 **`warning` 这一档原来整个不存**（2026-09-28 实测）：风险列表有三档，
        # 快照只收了 danger 和 note ⇒ 详情路由从快照重建列表时，**warning 那几条静默消失**
        # （实测 7 条 → 4 条，其中就包括「未提供签署日期 —— 时效未做校验」）。
        # ⚠️ **发给别人的下载件不受影响**（它取的是实时响应），丢的是**从历史重开**这条路。
        "结论边界": [p["内容"] for p in 风险列表 if p.get("等级") == "warning"],
        "边界说明": [p["内容"] for p in 风险列表 if p.get("等级") == "note"],
        "法条对照": 法条对照 or [],
        "条款校验": ({k: v for k, v in 条款校验.items() if not isinstance(v, list)}
                    if 条款校验 else None),
    }


def _读送检文本(报告文件名):
    """按报告文件名推它的同源送检文本（`<同名>.送检文本.txt`），读回来。

    ⚠️ **必须挡路径穿越**：`报告文件名` 从前端来。只认 basename，
    并且拼出来的路径必须真的落在用户数据目录里。
    """
    if not isinstance(报告文件名, str) or not 报告文件名.strip():
        return ""
    import os.path as _p
    文件夹 = 用户数据目录()
    名 = _p.basename(报告文件名.strip())
    if not 名.endswith(".json"):
        return ""
    路径 = _p.join(文件夹, 名[:-5] + ".送检文本.txt")
    if not _p.realpath(路径).startswith(_p.realpath(文件夹) + _p.sep):
        return ""
    try:
        with open(路径, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _写判决JSON(判例名, 数据):
    """三种模式共用的落盘：文件名一律过 安全名，不给 "/" 和 ".." 留通路。

    返回的是**裸文件名**（不带目录）—— 它会被回给前端当"这份报告"的标识，
    逐条反馈靠它把"哪一维没用"落到具体那份报告上；给绝对路径等于把目录结构泄露出去。
    """
    文件夹 = 用户数据目录()
    今天 = str(date.today())
    名 = f"{今天}_{_安全名(判例名)}.json"
    os.makedirs(文件夹, exist_ok=True)
    with open(os.path.join(文件夹, 名), "w", encoding="utf-8") as f:
        json.dump(数据, f, ensure_ascii=False)
    return 名


def _安全名(判例名):
    return 判例名.replace("/", "_").replace("..", "_").replace("\x00", "_") or "未命名"


def _存送检文本(判例名, 文本):
    """把**送进分析链路的那份文本**和报告存在一起（同年月日同名，后缀 `.送检文本.txt`）。

    🔴 **为什么要存**（2026-09-28 真机）：报告里到处是**位置标注**（`【第一条第4款】`），
    而复核它的判据要拿标注去原文里核对。原来**只存报告、不存输入** ⇒ 事后想核
    "第一条到底几款"**没有比对物**，只能信报告自己 —— 真机上我就卡在这儿，
    判不了那条指控（`第一条第4款` 对不上）到底谁错。

    ⚠️ **存的不是裸输入，是加过 `【第N条】` 锚点的那一份**（`判例` 那个变量）。
    这是**有意的**，两点理由：
      · 复核位置标注要的就是**带锚点的那份** —— 判据数"第几条几款"数的就是它；
        存裸输入的话，复核时得把锚点再切一遍，而切法一改就对不上了；
      · 锚点只是**插入行**，原文字面一字不少 ⇒ 内容上不丢东西。

    ⚠️ **存成旁边一个独立文件，不塞进报告 JSON**：报告 JSON 会被 `/download`
    按"跳过表之外的全部键"渲染成给别人看的文件 ⇒ 塞进去等于**把整份合同导出去**
    （而下载件本来就是发给律师/HR/对方的）。

    ⚠️ **文件名与 `_写判决JSON` 同源**（同一个 `date.today()` + `_安全名`）：
    两份东西按名字就能对上，不需要在报告里再记一个指针（多一个会漂的字段）。
    同名重复分析＝两份一起被覆盖，与报告本身的行为一致。
    """
    文件夹 = 用户数据目录()
    名 = f"{date.today()}_{_安全名(判例名)}.送检文本.txt"
    with open(os.path.join(文件夹, 名), "w", encoding="utf-8") as f:
        f.write(文本 or "")
    return 名


def _存储判决JSON(判例名, 结构, 争议, 推理, 法条精析, 对立路径, 论证检查, 程序问题, 未答, 核验=None):
    return _写判决JSON(判例名, {
        "判例名": 判例名, "日期": str(date.today()), "模式": "判决书分析",
        "结构化摘要": 结构, "核心争议": 争议,
        "推理链路": 推理, "法条适用精析": 法条精析,
        "对立解释路径": 对立路径, "论证完整性检查": 论证检查,
        "程序问题识别": 程序问题, "未回答问题": 未答,
        "核验": 核验,
    })

def _存储合同JSON(判例名, 合同类型, 分析结果, 核验=None, 时间基准=None, 字数=0, 立场=""):
    return _写判决JSON(判例名, {
        "判例名": 判例名, "日期": str(date.today()), "模式": "合同审查",
        # 🔴 **立场必须进报告**（2026-09-28）：报告里「我方」出现过 52 次，
        # 而交代"我方是谁"的说法一次都没有 ⇒ 收件人得自己猜，**猜反了整份意思反过来**。
        "合同类型": 合同类型, "时间基准": 时间基准, "立场": 立场, "字数": 字数,
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
    报告文件 = ""
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
            # 「我方是哪一方」——**用户选的**（2026-09-28）。`contract_skills.立场文本`
            # 自己会把认不出的值落回"中立"，这里不重复一份白名单（两份必然漂）。
            合同视角 = contract_skills.规范视角(data.get("side"))
            # 前 4 维并行，谈判顺序在它们之后（见下方注释）；这里只列并行的那 4 个
            维度 = {
                "风险清单": contract_skills.风险清单,
                "缺失条款": contract_skills.缺失条款,
                "失衡条款": contract_skills.失衡条款,
                "歧义表述": contract_skills.歧义表述,
            }
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {名: executor.submit(fn, 判例, 合同类型, api_key, 视角=合同视角)
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
                二波 = {名: executor.submit(fn, 判例, 合同类型, api_key,
                                           已有=dict(上波), 视角=合同视角)
                        for 名, fn in 第二波.items()}
                for 名, f in 二波.items():
                    try: 结果[名] = f.result()
                    except Exception as e: 结果[名] = f"【{名}失败】{str(e)[:200]}"
            try:
                结果["谈判顺序"] = contract_skills.谈判顺序(
                    判例, 合同类型, api_key, 已有=dict(结果), 视角=合同视角)
            except Exception as e:
                结果["谈判顺序"] = f"【谈判顺序失败】{str(e)[:200]}"
            全部分析 = [结果[k] for k in list(维度) + ["改法建议", "新增条款", "谈判顺序"]]
            # ⚠️ 逐条回查的范围**不含 新增条款**：那一维给的是合同里还不存在的整条新文字，
            # 拿现有条款表去比它，等于对正确输出亮红牌。它引用的法条仍走 法条库校验。
            锚点范围 = [结果[k] for k in list(维度) + ["改法建议", "谈判顺序"]]
            try:
                总结 = contract_skills.总结(判例, 合同类型, 结果, api_key, 视角=合同视角)
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
    # 🔴 **这里给的是"报出来给人看的名"**（见 `validate_analysis_quality` 的 docstring：
    #    它存在的理由就是"免得人照着名字去核对时对错段落"）⇒ 合同那一档必须过一遍 `叫法()`，
    #    不能直接把内部键名交出去。原来交的是键名，于是告警写成
    #    「歧义表述字数过少，可能API异常」——**术语漏进了给外人看的下载件**（2026-09-28 测试抓到）。
    段落名 = {"case": ["法律关系", "事实与证据", "对抗路径", "风险推演", "总结"],
              "contract": [叫法("风险清单"), 叫法("缺失条款"), 叫法("失衡条款"), 叫法("歧义表述"), "总结"],
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
        报告文件 = _存储合同JSON(判例名, 合同类型, 分析结果, 核验=核验,
                          时间基准=法条校验.get("案发日期") or 案发时间, 字数=len(判例),
                          立场=合同视角)
    elif 分析模式 == "case":
        分析结果 = {
            "法律关系": 法律关系, "事实与证据": 事实证据,
            "对抗路径": 对抗路径, "风险推演": 风险推演,
            "行动建议": 行动建议, "总结": 总结,
        }
        报告文件 = _存储案情JSON(判例名, 法律关系, 事实证据, 对抗路径, 风险推演, 行动建议,
                            总结, 核验=核验)
    else:
        分析结果 = {
            "结构化摘要": 结构, "核心争议": 争议,
            "推理链路": 推理, "法条适用精析": 法条精析,
            "对立解释路径": 对立路径, "论证完整性检查": 论证检查,
            "程序问题识别": 程序问题, "未回答问题": 未答,
        }
        报告文件 = _存储判决JSON(判例名, 结构, 争议, 推理, 法条精析, 对立路径, 论证检查,
                          程序问题, 未答, 核验=核验)

    # 送检文本和报告存一起 —— 三个模式都在这一句覆盖到（理由见 `_存送检文本`）。
    # ⚠️ 它**不进响应**：前端不需要，而多回一个字段就多一个会被存进盘/发给别人的机会。
    _存送检文本(判例名, 判例)

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
        "报告文件": 报告文件,
        "立场": 合同视角 if 分析模式 == "contract" else "",
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
            "报告文件": os.path.basename(路径),
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
                        # warning 有两个来源：格式检查的问题，以及快照里的「结论边界」。
                        # ⚠️ 少了下半句，从历史重开的报告就会比实时少几条（实测 7→4）。
                        + [{"等级": "warning", "内容": x}
                           for x in ((核验 or {}).get("格式检查") or {}).get("问题", [])]
                        + [{"等级": "warning", "内容": x}
                           for x in (核验 or {}).get("结论边界", [])]
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
    # 总结这个键两种模式共用：合同模式是「能不能签 + 先解决什么 + 对方不让步的退路」，
    # 案情模式是「一句话结论 + 最核心的一条行动建议」—— 两边都是"结论 + 下一步"，
    # 所以标签取中间那个说法，不偏向任何一个模式。
    "歧义表述": "写得含糊、日后会吵的", "谈判顺序": "先争哪条、后让哪条", "总结": "结论和下一步",
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
    # 🔴 **整份报告交给 `report_render` 合成**（2026-09-28）：
    # 原来这里是"七个维度原样拼接"，跑出来 32,338 字 / 554 行 ——
    # 24/24 条被提到的条款都在 2~4 个维度里各说了一遍，而结论被压在最后。
    # 合并的规则、去重的代价、哪一块没参与去重，都写在那个模块的头部。
    # 三份（2026-09-28 用户拍板）：给人读的 / 给人照着改合同的 / 给人查证的。
    部分 = str(data.get("部分") or "报告").strip()
    if 部分 == "附录":
        报告 = report_render.渲染附录(data)
        后缀 = "_法条原文.txt"
    elif 部分 == "对照表":
        # ⚠️ **它需要原文**（要逐条对照"这一款原来怎么写"）。
        # 优先取**盘上的送检文本**（分析当初真正看到的那一份，最权威）；
        # 取不到就退回**前端手里的那份合同文本** —— 两者正文行是一致的
        # （送检文本只是在正文行之间**插了锚点行**）。
        # 🔴 **为什么要有兜底**：盘上那份是按 **session 的用户目录**存的 ⇒
        #    cookie 一清、或密钥换了（见 `_会话密钥` 的注释），旧报告就认不回来了。
        #    那时另外两份（报告/附录）还能出，这一份却 400 —— 那是白挡。
        送检 = _读送检文本(data.get("报告文件")) or str(data.get("原文") or "")
        if not 送检.strip():
            return jsonify({"error": "拿不到这份合同的原文（盘上的送检文本没了、"
                                     "前端也没带过来）。改动对照表要拿原文逐条对照，缺了它做不出来。"}), 400
        报告 = contract_revise.渲染对照表(送检, data)
        后缀 = "_改动对照表.txt"
    else:
        报告 = report_render.渲染(data)
        后缀 = "_分析报告.txt"
    from flask import Response
    # 🔴 **纯文本**（2026-09-28 用户实测后改回来）：我一度输出 Markdown，理由是
    # "微信/钉钉/编辑器都认得" —— **那话是错的**：那些地方认得的是聊天里发的；
    # 而下载成文件、在手机里打开，`#` `**` 全是字面的噪音（用户原话「一对符号文字
    # 对一起，我都看不下去」）。版面靠分隔线+缩进+空行做，见 `report_render` 的版式一节。
    名 = (data.get("判例名") or "报告").strip().replace("/", "_").replace("\"", "_")[:40]
    return Response(
        报告,
        # ⚠️ 只给类型 —— 写成 "text/markdown; charset=utf-8" 会被 Werkzeug 再加一遍，
            #    变成 `text/markdown; charset=utf-8; charset=utf-8`（实测过两次）
            mimetype="text/plain",
        headers={
            # RFC 5987：中文文件名要写成 filename*，否则浏览器拿到一串乱码。
            # ⚠️ 这条**只对「直接打开这个 URL」有用** —— 页面上的下载按钮走的是
            #    blob URL，那一步**取不到 Content-Disposition**，所以下面另发一个头。
            "Content-Disposition":
                f"attachment; filename=report.txt; filename*=UTF-8''{quote(名 + 后缀)}",
            # 🔴 **文件名只在这里定**（2026-09-28）。前端原来自己拼
            #    `判例名 + "_分析报告.txt"`，我加了三份却没跟着改 ⇒
            #    **报告 / 改动对照表 / 法条原文 三份下载下来是同一个名字**（用户实测发现）。
            #    发成一个头让前端读，避免「服务端一份、前端一份」两份名字迟早漂。
            #    ⚠️ HTTP 头只能放 ASCII ⇒ 百分号编码，前端 `decodeURIComponent` 解回来。
            "X-Filename": quote(名 + 后缀),
            # ⚠️ 这里**别再写一遍 Content-Type**： 已经设过了，
            #    再设一次会拼成 `text/markdown; charset=utf-8; charset=utf-8`（实测过）。
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


@app.route("/rate", methods=["POST"])
def 逐条反馈路由():
    """某一维「有用 / 没看懂」—— 比整份报告级那句"哪个模块最没用"准得多。

    为什么值得多这一个口子：问卷问的是"你觉得哪块没用"，用户得先回忆再抽象；
    点卡片角上那两下问的是"这一条你看完能不能用"。而且这里连**当时的核验读数**
    一起存，于是能回答一个真正影响产品的问题：覆盖度低的报告，用户是不是更觉得没用。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体不是一份 JSON 对象"}), 400
    维度 = data.get("dimension")
    评价 = data.get("rating")
    if 评价 not in ("helpful", "unclear"):
        return jsonify({"error": "评价只能是「有用」或「没看懂」"}), 400
    if not isinstance(维度, str) or 维度 not in 人话标题:
        # 只收认识的维度名：否则打错一个字就多出一个没人统计的桶
        return jsonify({"error": "不认识的模块名"}), 400
    记录 = {
        "维度": 维度, "评价": 评价,
        "报告": (data.get("report") if isinstance(data.get("report"), str) else "")[:120],
        "判例名": (data.get("case_name") if isinstance(data.get("case_name"), str) else "")[:80],
        "等级": (data.get("等级") if isinstance(data.get("等级"), str) else "")[:4],
        "覆盖度": data.get("覆盖度") if isinstance(data.get("覆盖度"), (int, float)) else None,
        "时间": str(datetime.now())[:19],
    }
    目录 = os.path.join(用户数据目录(), "ratings")
    os.makedirs(目录, exist_ok=True)
    名 = f"{date.today()}_{datetime.now().strftime('%H%M%S-%f')}_{'好' if 评价 == 'helpful' else '懵'}.json"
    with open(os.path.join(目录, 名), "w", encoding="utf-8") as f:
        json.dump(记录, f, ensure_ascii=False)
    return jsonify({"ok": True})


def _收集逐条(uids):
    全部 = []
    for uid in uids:
        目录 = os.path.join(数据根目录, uid, "ratings")
        if not os.path.isdir(目录):
            continue
        for fname in sorted(os.listdir(目录)):
            try:
                with open(os.path.join(目录, fname), encoding="utf-8") as f:
                    全部.append(json.load(f))
            except Exception:
                pass
    return 全部


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
            "逐条评价": _逐条统计(_收集逐条(os.listdir(数据根目录)) if os.path.exists(数据根目录) else []),
        }, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8"
    )


def _逐条统计(记录列表):
    """按维度汇总「有用 / 没看懂」，并给一个看得懂的排序键。

    看不懂率单独摆出来：它高说明**话术**有问题，不是分析有问题 —— 这两件事
    会被同一个"这模块没用"混掉。
    """
    计 = {}
    for x in 记录列表:
        名 = x.get("维度") or "未标注"
        桶 = 计.setdefault(名, {"有用": 0, "没看懂": 0})
        if x.get("评价") == "helpful":
            桶["有用"] += 1
        elif x.get("评价") == "unclear":
            桶["没看懂"] += 1
    for 名, 桶 in 计.items():
        总 = 桶["有用"] + 桶["没看懂"]
        桶["看不懂率"] = round(桶["没看懂"] / 总, 2) if 总 else None
    return dict(sorted(计.items(), key=lambda kv: -(kv[1]["没看懂"] + kv[1]["有用"])))


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
