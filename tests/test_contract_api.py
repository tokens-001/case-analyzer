"""合同审查这条链路的集成测试：走真实 Flask 路由，把 `问AI` 桩掉（不发 API 请求）。

覆盖的是单元测试碰不到的那一层 —— **接线**：解析→锚点→五个维度→三态→风险列表→可信度。
跑法：python3 -m pytest tests/ -q

⚠️ 桩返回的文本是**故意按格式写好的**，所以这里验的是"格式对了以后链路通不通"，
不验"模型会不会守格式" —— 后者只能真跑一次才知道，见 test_模型不守格式时不许判成通过
（在 test_contract_review.py 里，走的是同一对消费者函数）。
"""
import io
import os
import sys
import tempfile
import zipfile

# 两种跑法都要隔离：pytest 走 tests/conftest.py，直接 python3 tests/xxx.py 不走 conftest。
# 不隔离的话限流计数会写进 data/case_data/limit_ip_*.json —— 和人在浏览器里是同一个桶。
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="判例助手-测试数据-"))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-测试用不联网")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))

import app as app_mod        # noqa: E402

合同正文 = """甲方委托乙方提供系统运维服务。
第一条 标的。乙方向甲方提供系统运维服务，详见附件一。
第三条 费用。合同总价人民币12万元，按季度支付，验收合格后付尾款。
第五条 保密。双方对履行中知悉的商业秘密负保密义务，期限三年。"""

桩输出 = {
    "风险清单": "- 【第三条】「合同总价人民币12万元，按季度支付」 风险：先款后验 建议：尾款挂钩验收\n"
              "- 【第七条】「甲方有权随时终止合同」 风险：单方解除权失衡 建议：加对等条款",
    "缺失条款": "- 【第五条】 保密义务未约定起算点与例外情形",
    "失衡条款": "- 违约金条款只约束乙方，甲方逾期付款无对应责任",
    "歧义表述": "未发现可指认的问题。",
    "改法建议": "- 【第三条】「合同总价人民币12万元，按季度支付」 改成："
                "「合同总价人民币12万元。甲方应于每季度末支付该季度款项，"
                "尾款于验收合格后10个工作日内支付。」 理由：把付款节点挂到验收上",
    "谈判顺序": "- 【第一条】「乙方向甲方提供系统运维服务，详见附件一」 用改法建议第1条那份文字去提",
}


# 案发时间那几条用例用：多引一条**库里真有**的法，才有时效可比
_带法条 = dict(桩输出, 风险清单=桩输出["风险清单"]
               + "\n- 【第三条】「合同总价人民币12万元，按季度支付」 另需核对《劳动合同法》第40条的解除前置")


# 每个维度的提示词里唯一的任务句 —— 用它认维度，顺带证明这些指令真的进了提示词
任务句 = {"风险清单": "逐条列出对我方的风险", "缺失条款": "对照上面的必查清单",
          "失衡条款": "权利义务不对等", "歧义表述": "无法执行的条款",
          "改法建议": "逐条改写成可以直接替换进合同的条款文字", "谈判顺序": "谈判清单"}


def _装桩(表=None):
    表 = 表 or 桩输出

    def 假问AI(提示词, 判例文字, api_key, 附段落编号=True):
        for 名, 句 in 任务句.items():
            if 句 in 提示词:
                assert "【第N条】" in 提示词, f"{名} 的提示词没带锚点格式要求"
                return 表.get(名, "")
        return "综合结论：量级中等。签之前先解决付款节点与单方解除两件事，其余可谈判时逐条争取。" * 2
    app_mod.contract_skills.问AI = 假问AI


def _客户端():
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def test_合同模式端到端出三态与可信度():
    _装桩()
    回 = _客户端().post("/analyze", json={"name": "运维合同", "text": 合同正文, "mode": "contract"})
    assert 回.status_code == 200, 回.get_json()
    数 = 回.get_json()
    assert 数["合同类型"] == "服务/采购/外包", 数["合同类型"]
    assert 数["条数"] == 3, 数["条数"]
    校验 = 数["条款校验"]
    # 桩里挂了 5 个锚点：第三条（风险清单）、第七条（编的）、第五条（无摘录）、
    # 改法建议的第三条、第一条 → 对得上原文的是 3 处
    assert 校验["已校验数"] == 3, 校验
    assert [x["引用条号"] for x in 校验["疑似编造"]] == ["七"], 校验["疑似编造"]
    assert 校验["无摘录"] and 校验["无锚点条目"], 校验
    # 第七条合同里根本没有 ⇒ danger；可信度必须被压到"低"
    assert any(r["等级"] == "danger" and "第七条" in r["内容"] for r in 数["风险列表"]), 数["风险列表"]
    assert 数["可信度"]["等级"] == "低", 数["可信度"]


def test_锚点表由服务端现算不认客户端回传():
    """客户端塞一张"条款表"进来 = 让它自己声明"我每条都对得上"。
    链路上根本没有这个入参，锚点只从被分析的那份文本派生。"""
    _装桩()
    回 = _客户端().post("/analyze", json={"name": "x", "text": 合同正文, "mode": "contract",
                                     "条款表": {"七": "第七条 甲方有权随时终止合同"}})
    数 = 回.get_json()
    assert [x["引用条号"] for x in 数["条款校验"]["疑似编造"]] == ["七"], "伪造的条款表生效了"


def test_纯散文输出落到未校验而不是通过():
    _装桩({k: "整体看风险中等，建议注意付款与解除条款。" for k in 任务句})
    数 = _客户端().post("/analyze", json={"name": "y", "text": 合同正文, "mode": "contract"}).get_json()
    assert 数["条款校验"]["已校验数"] == 0
    assert 数["可信度"]["等级"] != "高", 数["可信度"]      # 什么都没锚定，不许说"可信"


def test_parse_doc路由返回锚点文本():
    W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    体 = ''.join(f'<w:p><w:r><w:t>{t}</w:t></w:r></w:p>' for t in 合同正文.split("\n"))
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}"><w:body>{体}</w:body></w:document>'
    缓冲 = io.BytesIO()
    with zipfile.ZipFile(缓冲, 'w') as 档:
        档.writestr('[Content_Types].xml', '<Types/>')
        档.writestr('word/document.xml', xml)
    from io import BytesIO as _B
    客 = _客户端()
    回 = 客.post("/parse-doc", data={"file": (_B(缓冲.getvalue()), "合同.docx")},
                 content_type="multipart/form-data")
    数 = 回.get_json()
    assert 回.status_code == 200 and 数["条数"] == 3, 数
    assert "【第三条】" in 数["文本"]


def test_扫描件被拒绝而不是返回空文本():
    客 = _客户端()
    回 = 客.post("/parse-doc", data={"file": (io.BytesIO(b"%PDF-1.4 fake-not-parsable"), "扫的.pdf")},
                 content_type="multipart/form-data")
    数 = 回.get_json()
    assert 回.status_code == 400, 数
    # 没装 pypdf 时报"未安装"，装了则报"取不出文字"—— 两种都不许静默给空文本
    assert any(词 in 数["error"] for 词 in ("pypdf", "扫描件", "解析失败")), 数


def test_超长合同要说明被截断():
    _装桩()
    长 = 合同正文 + "\n第99条 补充约定。" * 2000
    数 = _客户端().post("/analyze", json={"name": "长", "text": 长, "mode": "contract"}).get_json()
    assert any("未参与本次审查" in r["内容"] for r in 数["风险列表"]), [r["内容"] for r in 数["风险列表"]]


def test_案发时间填了才有时效结论():
    """请求体里那个字段一路走到 法条校验 —— 以前 `app` 写死传空串，这一维永远不会跑。"""
    _装桩(_带法条)
    数 = _客户端().post("/analyze", json={"name": "运维合同", "text": 合同正文,
                                          "mode": "contract", "case_date": "2010年"}).get_json()
    命中 = [e for e in 数["法条对照"] if e["引用"] == "《劳动合同法》第40条"]
    assert 命中, 数["法条对照"]
    assert "早于本法条施行日期" in 命中[0]["版本警告"], 命中[0]   # 该法 2013-07-01 才施行
    assert 数["法条校验"]["案发日期已知"] is True, 数["法条校验"]
    assert any(r["等级"] == "danger" and "早于本法条施行日期" in r["内容"]
               for r in 数["风险列表"]), 数["风险列表"]


def test_案发时间读不懂要说出来不许默默当没填():
    _装桩(_带法条)
    数 = _客户端().post("/analyze", json={"name": "运维合同", "text": 合同正文,
                                          "mode": "contract", "case_date": "2019年左右"}).get_json()
    assert 数["法条校验"]["案发日期已知"] is False, 数["法条校验"]
    assert 数["法条校验"]["案发日期无法解析"] is True, 数["法条校验"]
    命中 = [e for e in 数["法条对照"] if e["引用"] == "《劳动合同法》第40条"][0]
    assert 命中["版本警告"] == "", 命中        # 读不懂的字符串不许冒充"比过了"
    assert any("没能识别" in r["内容"] for r in 数["风险列表"]), 数["风险列表"]
    assert 数["可信度"]["等级"] != "高", 数["可信度"]


def test_不填签署时间时等级封顶在中():
    """合同模式下这个基准日叫"签署日"，不叫"案发"。

    ⚠️ 断言写死在"签署"这个词上是有意的：`generate_risk_list` 的时间词是个参数，
    把它改成常量"签署"，这条仍然绿；但下面那条 默认时间词 会红 —— 判决书读者
    会凭空看到"签署日期"。两条一起才把"按模式换词"这件事钉住。
    """
    _装桩(_带法条)
    数 = _客户端().post("/analyze", json={"name": "运维合同", "text": 合同正文,
                                          "mode": "contract"}).get_json()
    assert 数["法条校验"]["案发日期已知"] is False, 数["法条校验"]
    assert 数["法条校验"].get("案发日期无法解析") is False, 数["法条校验"]   # 没填 ≠ 填错
    assert any("未提供签署日期" in r["内容"] for r in 数["风险列表"]), 数["风险列表"]
    assert not any("未提供案发日期" in r["内容"] for r in 数["风险列表"]), 数["风险列表"]


def _抓提示词():
    """跑一次合同分析，把每一维实际收到的提示词留下。测"谁看到了谁"只能这样测。"""
    抓到 = {}

    def 假问AI(提示词, 判例文字, api_key, 附段落编号=True):
        for 名, 句 in 任务句.items():
            if 句 in 提示词:
                抓到.setdefault(名, 提示词)
                return 桩输出.get(名, "")
        return "综合结论：量级中等。签之前先解决付款节点与单方解除两件事。" * 2
    原 = app_mod.contract_skills.问AI
    app_mod.contract_skills.问AI = 假问AI
    try:
        _客户端().post("/analyze", json={"name": "运维合同", "text": 合同正文, "mode": "contract"})
    finally:
        app_mod.contract_skills.问AI = 原
    return 抓到


def test_改法建议看得到四维结论而且自带格式要求():
    抓 = _抓提示词()
    assert "改法建议" in 抓, sorted(抓)
    提示 = 抓["改法建议"]
    for 名 in ("风险清单", "失衡条款", "歧义表述"):
        assert f"【{名}】" in 提示, f"改法建议 的提示词里没带 {名} 的实际结论"
    assert "先款后验" in 提示, "带的是占位文字而不是前四维的输出内容"
    # 提示词里的格式和检查它的判据必须同源：漂移的后果是"每一行正确输出都被判未校验"
    from skills.legal import verify_clauses
    assert verify_clauses.改法格式要求 in 提示, "改法建议 用的不是 verify_clauses 那份格式要求"
    assert "『合同里根本没有这条』（缺失条款）不要出现在这里" in 提示, \
        "没提醒它别接缺失条款 —— 没有原文可摘的问题一旦进这一维，" \
        "模型只能编一条锚点，而那会被校验器判成疑似编造"


def test_谈判顺序排的是改法文字而不是另拟一版():
    """两版条款文字不一致，谈判桌上就会自己跟自己打架。"""
    抓 = _抓提示词()
    assert "改法建议" in 抓["谈判顺序"], "谈判顺序 没看到改法建议的输出"
    assert "甲方应于每季度末支付该季度款项" in 抓["谈判顺序"], "带的是占位而不是改法文字"
    assert "不要另拟一版条款文字" in 抓["谈判顺序"], "提示词没约束它别另拟"


def test_串行顺序不能退回去():
    """四维并行 → 改法建议 → 谈判顺序 → 总结。改法建议 和 谈判顺序 一旦并行发，
    后者就又看不到前者了 —— 这正是当初 谈判顺序 的毛病。"""
    抓 = _抓提示词()
    提示 = 抓["谈判顺序"]
    assert all(f"【{k}】" in 提示 for k in
               ("风险清单", "缺失条款", "失衡条款", "歧义表述", "改法建议")), \
        "谈判顺序 的上下文缺一段：" + str([k for k in 抓 if k not in 提示])


def test_合同结果里不该出现别的模式的说明():
    """原来审合同的人点开"原文回查"那一栏，看到的是一句在跟他解释**案情模式**的话。
    一栏没有内容就别留一栏 —— 而留着的那句必须说的是他现在这件事。"""
    _装桩()
    数 = _客户端().post("/analyze", json={"name": "运维合同", "text": 合同正文,
                                          "mode": "contract"}).get_json()
    assert 数["溯源"] is None, 数["溯源"]
    # 只查**会印到屏幕上的那几串字**。`法条校验.案发日期` 这类是内部键名（后端契约、
    # 存储的 JSON、别的测试都押在上面），改键名等于把一次话术调整扩散成一次接口变更。
    展示文本 = ([r["内容"] for r in 数["风险列表"]] + 数["验证"]["问题"]
              + [d["来源"] for d in 数["可信度"]["明细"]])
    串 = "\n".join(展示文本)
    assert "案情" not in 串, [x for x in 展示文本 if "案情" in x]
    assert "案发" not in 串, "合同里比对时效的基准日叫签署日，不叫案发"


def test_默认时间词是案发():
    """不传 时间词（判决书/案情那条调用路径）时，措辞必须还是"案发"。"""
    from skills.legal.score_analysis import generate_risk_list
    法条校验 = {"可验证": [], "疑似编造": [], "库外": [], "未识别": [], "无条号引用": [],
                "案发日期已知": False, "案发日期无法解析": False, "未校验数": 0, "覆盖不足数": 0}
    风险 = generate_risk_list({"通过": True, "问题": [], "法条统计": ""}, 法条校验, None)
    assert any("未提供案发日期" in r["内容"] for r in 风险), 风险


def test_合同类型判成通用时要说出来():
    """"通用"是一张兜底清单，不是判出来的类型。它决定『缺失条款』照着哪张表查 ——
    不告诉读者，等于用一张放之四海皆准的表报"你合同里缺这缺那"。"""
    _装桩()
    数 = _客户端().post("/analyze", json={"name": "一份什么特征词都没有的协议",
                                          "text": "第1条 甲方与乙方经友好协商，就合作事宜达成一致意见。\n"
                                                  "第2条 双方本着平等互利的原则，约定如下内容并共同遵守执行。\n"
                                                  "第3条 本协议自双方签字盖章之日起生效并正式开始实施。",
                                          "mode": "contract"}).get_json()
    assert 数["合同类型"] == "通用", 数["合同类型"]
    assert any("没能确定合同类型" in r["内容"] for r in 数["风险列表"]), 数["风险列表"]


def test_谈判顺序拿得到前四维的结论():
    """提示词写着"把上面几类问题收成一份谈判清单"，而它曾经和前四维**并行**发出 ——
    那时"上面"还是空的。这条测的是接线：桩在这里断言喂进来的确有前四维的原文。"""
    抓到 = {}

    def 假问AI(提示词, 判例文字, api_key, 附段落编号=True):
        for 名, 句 in 任务句.items():
            if 句 in 提示词:
                if 名 == "谈判顺序":
                    抓到[名] = 提示词
                return 桩输出.get(名, "")
        return "综合结论：量级中等。签之前先解决付款节点与单方解除两件事，其余可谈判时逐条争取。" * 2
    原 = app_mod.contract_skills.问AI
    app_mod.contract_skills.问AI = 假问AI
    try:
        _客户端().post("/analyze", json={"name": "运维合同", "text": 合同正文, "mode": "contract"})
    finally:
        app_mod.contract_skills.问AI = 原
    assert "谈判顺序" in 抓到, "谈判顺序 没被调用"
    提示 = 抓到["谈判顺序"]
    for 名 in ("风险清单", "失衡条款", "歧义表述"):
        assert f"【{名}】" in 提示, f"谈判顺序 的提示词里没带 {名} 的实际结论"
    assert "先款后验" in 提示, "带的是占位文字而不是前四维的输出内容"


def test_某一维返回失败产物时必须出声():
    """`validate_analysis_quality` 只看 5 个槽位，而合同一次有 6 路输出。
    谈判顺序是第 6 路 —— 它挂了的话，那段 {"error": true} 会当成"谈判清单"排版给用户。"""
    坏 = dict(桩输出, 谈判顺序='{"error": true, "type": "timeout", "detail": "API请求超时，请稍后重试"}')
    _装桩(坏)
    数 = _客户端().post("/analyze", json={"name": "运维合同", "text": 合同正文,
                                          "mode": "contract"}).get_json()
    assert 数["验证"]["通过"] is False, 数["验证"]
    assert any("谈判顺序" in p for p in 数["验证"]["问题"]), 数["验证"]["问题"]


if __name__ == "__main__":
    测试们 = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for 名, t in 测试们:
        t()
        print(f"  ✓ {名}")
    print(f"\n{len(测试们)} 个测试全通过")
