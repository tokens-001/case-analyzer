# 判例助手 - Web版
# Flask后端：接收判例 → 调用DeepSeek分析 → 返回结果

import os, json, uuid, re
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session

# 加载 .env 文件（本地开发用；生产环境直接用系统环境变量）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ═══════════════════════════════════════════════════════════
# 法律技能库导入
# ═══════════════════════════════════════════════════════════
from skills.legal import (
    extract_dispute,
    extract_reasoning,
    find_unanswered,
    assess_transfer,
    generate_summary,
    find_counter_arguments,
    structure_judgment,
    audit_argument_chain,
    detect_missing_evidence,
    discover_opposing_laws,
)
from skills.legal.verify_laws import (
    count_law_citations,
    search_law_database,
    verify_law_citation_realness,
    verify_law_version,
    find_adjacent_laws,
)
from skills.legal.trace_citations import 执行 as trace_citations
from skills.legal.score_analysis import (
    validate_analysis_quality,
    generate_risk_list,
    compute_trust_score,
)
from skills.legal._base import 智能分段

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

# 智能分段 → 已迁移到 skills/legal/_base.py

# 问AI → 已迁移到 skills/legal/_base.py

# 九个分析维度函数 → 已迁移到 skills/legal/ 对应模块
# 溯源对比/法条统计/法条库查询 → 已迁移到 skills/legal/verify_laws.py + trace_citations.py

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

# 法条版本校验/风险列表/可信度评分 → 已迁移到 skills/legal/verify_laws.py + score_analysis.py

# 验证分析结果 → 已迁移到 skills/legal/score_analysis.py

# ---- 8. 存储 ----
def 存储为JSON(判例名, 分析1, 分析2, 分析3, 分析4, 反例, 总结, 结构, 论证链, 证据缺失, 相反法条):
    return _存储为JSON_内部(判例名, 分析1, 分析2, 分析3, 分析4, 反例, 总结, 结构, 论证链, 证据缺失, 相反法条)

def _存储为JSON_内部(判例名, 分析1, 分析2, 分析3, 分析4, 反例, 总结, 结构, 论证链, 证据缺失, 相反法条):
    文件夹 = 用户数据目录()
    今天 = str(date.today())
    文件名 = f"{文件夹}/{今天}_{判例名}.json"

    数据 = {
        "判例名": 判例名, "日期": 今天,
        "核心争议": 分析1, "推理链路": 分析2,
        "未回答问题": 分析3, "可平移性": 分析4,
        "反例检索": 反例, "总结": 总结, "结构化摘要": 结构,
        "论证链检测": 论证链, "证据缺失检测": 证据缺失, "相反法条发现": 相反法条
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
    """编排层：按顺序调度技能库中的分析技能，组装JSON返回"""
    # ── 限流 & 校验 ──
    uid = 获取用户ID()
    ip = 获取客户端IP()
    if not 消耗次数(uid, ip):
        剩余 = 剩余次数查询(uid, ip)
        return jsonify({"error": f"今日分析次数已用完（每人{每日上限}次），请明天再来。", "剩余": 0, "上限": 每日上限}), 429
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return jsonify({"error": "未设置 DEEPSEEK_API_KEY 环境变量"}), 500

    data = request.json
    判例名 = data.get("name", "").strip()
    判例 = data.get("text", "").strip()
    案发日期 = data.get("case_date", "").strip()

    if not 判例名:
        return jsonify({"error": "请输入判例名称"}), 400
    if len(判例名) > 80:
        return jsonify({"error": "判例名称过长（最多80字）"}), 400
    if not 案发日期:
        return jsonify({"error": "请选择案发日期（用于校验法条版本）"}), 400
    if len(判例) < 50:
        return jsonify({"error": "判例文字太短（少于50字），请输入完整判例内容"}), 400

    # ── 第一轮：四维基础分析（并行）──
    with ThreadPoolExecutor(max_workers=4) as executor:
        f1 = executor.submit(extract_dispute.执行, 判例, api_key)
        f2 = executor.submit(extract_reasoning.执行, 判例, api_key)
        f3 = executor.submit(find_unanswered.执行, 判例, api_key)
        f4 = executor.submit(assess_transfer.执行, 判例, api_key)
        分析1 = f1.result()
        分析2 = f2.result()
        分析3 = f3.result()
        分析4 = f4.result()

    # ── 第二轮：综合总结（依赖第一轮）──
    总结 = generate_summary.执行(判例, 分析1, 分析2, 分析3, 分析4, api_key)

    # ── 第三轮：深度五维（并行）──
    with ThreadPoolExecutor(max_workers=5) as executor:
        f5 = executor.submit(find_counter_arguments.执行, 判例, api_key)
        f6 = executor.submit(structure_judgment.执行, 判例, 分析1, 分析2, 分析3, 分析4, api_key)
        f7 = executor.submit(audit_argument_chain.执行, 判例, api_key)
        f8 = executor.submit(detect_missing_evidence.执行, 判例, api_key)
        f9 = executor.submit(discover_opposing_laws.执行, 判例, api_key)
        反例 = f5.result()
        结构 = f6.result()
        论证链 = f7.result()
        证据缺失 = f8.result()
        相反法条 = f9.result()

    # ── 第四轮：本地校验层（不调API，全部并行）──
    全部分析 = [分析1, 分析2, 分析3, 分析4, 反例, 论证链, 证据缺失, 相反法条]
    溯源 = trace_citations(判例, *全部分析)
    法条对照 = search_law_database(法条库目录, *全部分析)
    法条真实性警告 = verify_law_citation_realness(法条库目录, *全部分析)
    验证 = validate_analysis_quality(分析1, 分析2, 分析3, 分析4, 总结, count_law_citations)

    # ── 存储 ──
    存储为JSON(判例名, 分析1, 分析2, 分析3, 分析4, 反例, 总结, 结构, 论证链, 证据缺失, 相反法条)

    # ── 法条版本时间轴校验 ──
    if 案发日期 and 法条对照:
        for item in 法条对照:
            版本问题 = verify_law_version(案发日期, item)
            if 版本问题:
                item["版本警告"] = 版本问题

    # ── 组装返回 ──
    剩余 = 剩余次数查询(uid, ip)
    # 法条库数据不足，暂禁用相邻法条（扩库后改回 find_adjacent_laws(法条库目录, 法条对照)）
    相邻法条 = []
    可信度 = compute_trust_score(验证, 法条对照, 溯源, 法条真实性警告)
    风险列表 = generate_risk_list(验证, 法条对照, 溯源, 法条真实性警告)

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
            "反例检索": 反例,
            "总结": 总结,
            "结构化摘要": 结构,
            "论证链检测": 论证链,
            "证据缺失检测": 证据缺失,
            "相反法条发现": 相反法条,
        },
        "溯源": 溯源,
        "法条对照": 法条对照,
        "相邻法条": 相邻法条,
        "验证": 验证,
        "可信度": 可信度,
        "风险列表": 风险列表,
        "法条真实性警告": 法条真实性警告,
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
                "反例检索": d.get("反例检索", ""),
                "总结": d.get("总结", ""),
                "结构化摘要": d.get("结构化摘要", ""),
                "论证链检测": d.get("论证链检测", ""),
                "证据缺失检测": d.get("证据缺失检测", ""),
                "相反法条发现": d.get("相反法条发现", ""),
            },
            "溯源": None,
            "法条对照": None,
            "相邻法条": [],
            "验证": {"通过": True, "问题": [], "法条统计": "历史存档数据"},
            "可信度": None,
            "风险列表": [],
            # 判例存量不足，暂禁用关联（积累后改回 查关联判例(fname)）
            "关联判例": []
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

六、反例检索
{'─'*40}
{data.get('反例检索', '')}

七、结构化摘要
{'─'*40}
{data.get('结构化摘要', '')}

	八、论证链检测
	{'─'*40}
{data.get('论证链检测', '')}

	九、证据缺失检测
	{'─'*40}
{data.get('证据缺失检测', '')}

	十、相反法条发现
	{'─'*40}
{data.get('相反法条发现', '')}

	十一、法条统计
	{'─'*40}
{data.get('法条统计', '')}

	十二、法条对照
	{'─'*40}
"""
    for 条目 in data.get('法条对照', []):
        报告 += f"\n【{条目.get('法名', '')}】{条目.get('引用', '')}\n{条目.get('条文', '')}\n"

    报告 += f"""
	十三、溯源对比
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

@app.route("/feedback", methods=["POST"])
def 反馈路由():
    """接收结构化反馈：有帮助程度 + 最有/最没用模块 + 必须保留模块 + 问题类型 + 可选文字"""
    data = request.json
    判例名 = data.get("case_name", "未知")
    分析日期 = data.get("date", str(date.today()))
    有帮助程度 = data.get("helpfulness", "")
    最有价值 = data.get("most_valuable", [])
    最没用 = data.get("least_valuable", [])
    必须保留 = data.get("keep_three", [])
    问题类型 = data.get("issue_types", [])
    备注 = data.get("comment", "").strip()

    if 有帮助程度 not in ("very", "somewhat", "little", "none"):
        return jsonify({"error": "请选择有帮助程度"}), 400

    反馈数据 = {
        "判例名": 判例名,
        "分析日期": 分析日期,
        "有帮助程度": 有帮助程度,
        "最有价值模块": 最有价值,
        "最没用模块": 最没用,
        "必须保留模块": 必须保留,
        "问题类型": 问题类型,
        "备注": 备注,
        "提交时间": str(date.today()),
    }

    反馈目录 = os.path.join(用户数据目录(), "feedback")
    os.makedirs(反馈目录, exist_ok=True)
    文件名 = f"{date.today()}_{判例名}_反馈.json"
    with open(os.path.join(反馈目录, 文件名), "w") as f:
        json.dump(反馈数据, f, ensure_ascii=False)

    return jsonify({"ok": True, "message": "感谢反馈！"})


if __name__ == "__main__":
    print("判例助手网页版已启动 → http://127.0.0.1:5050")
    app.run(debug=True, host="0.0.0.0", port=5050)
