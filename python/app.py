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
    search_law_database,
    verify_law_citation_realness,
)
from skills.legal.trace_citations import 执行 as trace_citations
from skills.legal.score_analysis import (
    validate_analysis_quality,
    generate_risk_list,
    compute_trust_score,
)
from skills.legal._base import 智能分段

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24).hex()

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

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

# 构建判例索引 / 查关联判例 → 已移除。法条库仅1个文件，关联功能无数据支撑。

# 法条版本校验/风险列表/可信度评分 → 已迁移到 skills/legal/verify_laws.py + score_analysis.py

# 验证分析结果 → 已迁移到 skills/legal/score_analysis.py

# ---- 8. 存储 ----
def _存储判决JSON(判例名, 结构, 争议, 推理, 法条精析, 对立路径, 论证检查, 程序问题, 未答):
    文件夹 = 用户数据目录()
    今天 = str(date.today())
    safe_name = 判例名.replace("/", "_").replace("..", "_") or "未命名"
    文件名 = f"{文件夹}/{今天}_{safe_name}.json"
    数据 = {
        "判例名": 判例名, "日期": 今天, "模式": "判决书分析",
        "结构化摘要": 结构, "核心争议": 争议,
        "推理链路": 推理, "法条适用精析": 法条精析,
        "对立解释路径": 对立路径, "论证完整性检查": 论证检查,
        "程序问题识别": 程序问题, "未回答问题": 未答,
    }
    os.makedirs(文件夹, exist_ok=True)
    with open(文件名, "w") as f:
        json.dump(数据, f)
    return 文件名

def _存储案情JSON(判例名, 法律关系, 事实证据, 对抗路径, 风险推演, 行动建议, 总结):
    文件夹 = 用户数据目录()
    今天 = str(date.today())
    safe_name = 判例名.replace("/", "_").replace("..", "_") or "未命名"
    文件名 = f"{文件夹}/{今天}_{safe_name}.json"
    数据 = {
        "判例名": 判例名, "日期": 今天, "模式": "案情分析",
        "法律关系": 法律关系, "事实与证据": 事实证据,
        "对抗路径": 对抗路径, "风险推演": 风险推演,
        "行动建议": 行动建议, "总结": 总结,
    }
    os.makedirs(文件夹, exist_ok=True)
    with open(文件名, "w") as f:
        json.dump(数据, f)
    return 文件名

# ---- 9. 每日次数限制 ----
每日上限 = int(os.environ.get("DAILY_LIMIT", "20"))

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
    if not 消耗次数(uid, ip):
        剩余 = 剩余次数查询(uid, ip)
        return jsonify({"error": f"今日分析次数已用完（每人{每日上限}次），请明天再来。", "剩余": 0, "上限": 每日上限}), 429
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return jsonify({"error": "未设置 DEEPSEEK_API_KEY 环境变量"}), 500

    data = request.json
    判例名 = data.get("name", "").strip()
    判例 = data.get("text", "").strip()
    分析模式 = data.get("mode", "judgment")  # "judgment"=判决书 "case"=案情分析
    子模式 = data.get("submode", "read")

    if len(判例名) > 80:
        return jsonify({"error": "判例名称过长（最多80字）"}), 400
    if len(判例) < 50:
        return jsonify({"error": "判例文字太短（少于50字），请输入完整判例内容"}), 400
    判例 = 判例[:15000]

    # 输入类型检测：非判决书/案情文本拒绝分析
    if 分析模式 == "judgment":
        judgment_keywords = ["法院", "判决", "原告", "被告", "裁定", "本院", "审理", "诉称", "辩称"]
        if not any(kw in 判例 for kw in judgment_keywords[:4]):
            return jsonify({"error": "输入文本不像判决书。判决书通常包含'原告''被告''法院'等主体信息。如确为判决书请继续；如为案情咨询请切换至'案情分析'模式。"}), 400

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
    except Exception as e:
        return jsonify({"error": f"分析过程异常: {str(e)[:300]}"}), 500

    if not 判例名:
        # 从案情原文提取关键词作名称
        import re as _re
        patterns = [
            r'(?:原被告|双方|当事人)?[因涉].{2,12}(?:纠纷|争议|合同|案件)',
            r'(?:原告|申请人).{2,6}(?:诉|申请).{2,6}(?:纠纷|案)',
            r'.{2,8}(?:合同|借贷|买卖|租赁|合伙|侵权|劳动|婚姻|继承|房产)纠纷',
        ]
        for p in patterns:
            m = _re.search(p, 判例)
            if m:
                判例名 = m.group()[:30].replace(" ", "")
                break
        if not 判例名:
            判例名 = 判例[:30].replace(" ", "").replace("\n", "") or "未命名"

    # ── 本地校验层（两种模式共用）──
    法条对照 = search_law_database(法条库目录, *全部分析)
    法条真实性警告 = verify_law_citation_realness(法条库目录, *全部分析)
    验证 = validate_analysis_quality(*全部分析[:4], 总结, count_law_citations)
    溯源 = trace_citations(判例, *全部分析) if 分析模式 != "case" else {"warning": "案情模式不适用溯源校验"}

    # ── 组装返回 ──
    剩余 = 剩余次数查询(uid, ip)
    可信度 = compute_trust_score(验证, 法条对照, 溯源, 法条真实性警告)
    风险列表 = generate_risk_list(验证, 法条对照, 溯源, 法条真实性警告)

    if 分析模式 == "case":
        分析结果 = {
            "法律关系": 法律关系, "事实与证据": 事实证据,
            "对抗路径": 对抗路径, "风险推演": 风险推演,
            "行动建议": 行动建议, "总结": 总结,
        }
        _存储案情JSON(判例名, 法律关系, 事实证据, 对抗路径, 风险推演, 行动建议, 总结)
    else:
        分析结果 = {
            "结构化摘要": 结构, "核心争议": 争议,
            "推理链路": 推理, "法条适用精析": 法条精析,
            "对立解释路径": 对立路径, "论证完整性检查": 论证检查,
            "程序问题识别": 程序问题, "未回答问题": 未答,
        }
        _存储判决JSON(判例名, 结构, 争议, 推理, 法条精析, 对立路径, 论证检查, 程序问题, 未答)

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
        # 通用格式：从存储数据提取所有分析字段
        分析字段 = {}
        for k, v in d.items():
            if k not in ("判例名", "日期", "字数", "模式"):
                分析字段[k] = v
        return jsonify({
            "判例名": d.get("判例名", ""),
            "字数": d.get("字数", 0),
            "分析": 分析字段,
            "溯源": None,
            "法条对照": None,
            "验证": {"通过": True, "问题": [], "法条统计": "历史存档数据"},
            "可信度": None,
            "风险列表": [],
        })
    except:
        return jsonify({"error": "读取失败"}), 500

@app.route("/download", methods=["POST"])
def 下载路由():
    """把分析结果转成可下载的文本报告（通用）"""
    data = request.json
    报告 = f"""法律分析报告
{'='*50}
名称：{data.get('判例名', '')}
日期：{date.today()}
"""
    跳过 = {'判例名', '法条统计', '法条对照', '溯源'}
    for key, val in data.items():
        if key in 跳过 or not val:
            continue
        报告 += f"""

{key}
{'─'*40}
{val}
"""
    报告 += f"""
法条统计
{'─'*40}
{data.get('法条统计', '')}

法条对照
{'─'*40}
"""
    for 条目 in data.get('法条对照', []):
        报告 += f"\n【{条目.get('法名', '')}】{条目.get('引用', '')}\n{条目.get('条文', '')}\n"

    报告 += f"""
溯源
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
        headers={
            "Content-Disposition": "attachment; filename=report.txt",
            "Content-Type": "text/plain; charset=utf-8"
        }
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

@app.route("/feedback-data")
def 反馈数据路由():
    """查看所有用户反馈汇总"""
    if not os.path.exists(数据根目录):
        return jsonify({"总数": 0, "反馈": []})
    全部 = []
    for uid in os.listdir(数据根目录):
        反馈目录 = os.path.join(数据根目录, uid, "feedback")
        if not os.path.isdir(反馈目录):
            continue
        for fname in sorted(os.listdir(反馈目录), reverse=True):
            try:
                with open(os.path.join(反馈目录, fname), "r") as f:
                    d = json.load(f)
                d["用户ID"] = uid[:8]
                全部.append(d)
            except:
                pass
    from flask import Response
    return Response(
        json.dumps({"总数": len(全部), "反馈": 全部[-50:]}, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8"
    )


@app.route("/dashboard")
def 后台面板():
    """访问量统计面板"""
    import collections
    分析总数 = 0
    判决书数 = 0
    案情数 = 0
    用户集合 = set()
    if os.path.exists(数据根目录):
        for uid in os.listdir(数据根目录):
            user_dir = os.path.join(数据根目录, uid)
            if not os.path.isdir(user_dir):
                continue
            用户集合.add(uid)
            for fname in os.listdir(user_dir):
                if fname.endswith(".json") and not fname.startswith("limit"):
                    分析总数 += 1
                    try:
                        with open(os.path.join(user_dir, fname)) as f:
                            d = json.load(f)
                        if d.get("模式") == "案情分析":
                            案情数 += 1
                        else:
                            判决书数 += 1
                    except:
                        pass
    反馈数 = 0
    if os.path.exists(数据根目录):
        for uid in os.listdir(数据根目录):
            fb_dir = os.path.join(数据根目录, uid, "feedback")
            if os.path.isdir(fb_dir):
                反馈数 += len([f for f in os.listdir(fb_dir) if f.endswith(".json")])
    from flask import Response
    return Response(
        json.dumps({
            "分析总数": 分析总数,
            "判决书分析": 判决书数,
            "案情分析": 案情数,
            "用户数": len(用户集合),
            "反馈数": 反馈数,
        }, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8"
    )


if __name__ == "__main__":
    print("判例助手网页版已启动 → http://127.0.0.1:5050")
    app.run(debug=True, host="0.0.0.0", port=5050)
