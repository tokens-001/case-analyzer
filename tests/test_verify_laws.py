"""冒烟测试：锁住法条三态校验与两个消费者的一致性。

跑法：python3 tests/test_verify_laws.py   或   python3 -m pytest tests/ -q

⚠️ 用真法条库的那几条**只测"查得到"和"有法无条"两类** —— 库里没这部法的用例
   会走 `_记录库外引用`，往 data/laws/missing_laws.txt 追加内容（那是真数据）。
   测"库外"一律用 tmp 目录造一个假库，别碰真的。
"""
import os
import shutil
import sys
import tempfile

# 让 skills 包可导入（skills 在 python/ 下）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))

from skills.legal import verify_laws, score_analysis

法条库 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "laws")

格式通过 = {"通过": True, "问题": [], "法条统计": "引用法条 1 条"}
空校验 = {"可验证": [], "疑似编造": [], "库外": [], "未识别": [], "无条号引用": [],
          "已校验数": 0, "覆盖不足数": 0, "未校验数": 0, "案发日期已知": True}


def _假法条库():
    """造一个临时法条库，含一部'现行有效'和一部'已废止'的法。"""
    目录 = tempfile.mkdtemp(prefix="法条库-")
    with open(os.path.join(目录, "测试法.txt"), "w", encoding="utf-8") as f:
        f.write("#META\n法名: 测试法\n施行日期: 2020-01-01\n状态: 现行有效\n#END\n\n"
                "第5条\n测试条文正文。\n\n第6条\n另一条。\n")
    with open(os.path.join(目录, "旧测试法.txt"), "w", encoding="utf-8") as f:
        f.write("#META\n法名: 旧测试法\n施行日期: 2010-01-01\n状态: 已废止\n取代: 测试法\n#END\n\n"
                "第3条\n旧条文。\n")
    return 目录


# ─────────────── 提取与数字归一 ───────────────

def test_中文条文号转数字():
    assert verify_laws._文章号转数字("六百六十七") == 667
    assert verify_laws._文章号转数字("123") == 123


def test_统计条数时截断要说明():
    文 = "、".join(f"《测试法》第{i}条" for i in range(1, 9))
    结果 = verify_laws.count_law_citations(文)
    assert "引用法条 8 条" in 结果 and "另有 3 条未列出" in 结果, 结果


# ─────────────── 三态本身 ───────────────

def test_真实法条判为可验证():
    结果 = verify_laws.classify_law_citations(法条库, "", "《民法典》第1165条")
    assert [e["引用"] for e in 结果["可验证"]] == ["《民法典》第1165条"]
    assert 结果["疑似编造"] == [] and 结果["未识别"] == []
    assert 结果["已校验数"] == 1 and 结果["未校验数"] == 0


def test_可验证条目带原文与元数据():
    结果 = verify_laws.classify_law_citations(法条库, "", "《民法典》第1165条")
    条目 = 结果["可验证"][0]
    assert 条目["状态"] == "现行有效" and 条目["施行日期"] == "2021-01-01"
    assert "第1165条" in 条目["条文"]
    assert 条目["版本警告"] == ""            # 该键以前没有任何地方写，两个消费者却都在读


def test_有法无条判为疑似编造():
    结果 = verify_laws.classify_law_citations(法条库, "", "《民法典》第99999条")
    assert 结果["疑似编造"] == ["《民法典》第99999条"]
    assert 结果["库外"] == []


def test_库外法不等于疑似编造():
    """整部法不在库里 = 覆盖不足。原来这一类和"有法无条"混成同一个列表，
    而风险侧把它指控成"AI引用了不存在的条文"—— 实测《电子签名法》第3条
    （真实存在）就是这么被指控的。"""
    结果 = verify_laws.classify_law_citations(法条库, "", "《电子签名法》第3条")
    assert 结果["库外"] == ["《电子签名法》第3条"]
    assert 结果["疑似编造"] == []
    assert 结果["覆盖不足数"] == 1


def test_无条号援引被单独计数():
    """法条正则要求出现"第…条"，所以这类串根本不进提取集合 ——
    不单独抓一遍的话，它会静默通过，让"已校验"这个绿灯覆盖到没校验过的东西。"""
    结果 = verify_laws.classify_law_citations(
        法条库, "", "依据《民法典》合同编的有关规定，借款人应按约定期限支付利息。")
    assert 结果["无条号引用"] == ["《民法典》"]
    assert 结果["未校验数"] == 1 and 结果["已校验数"] == 0


def test_同时有条号和无条号引用时分得开():
    结果 = verify_laws.classify_law_citations(
        法条库, "", "《民法典》第1165条规定了过错责任；此外依据《民法典》侵权责任编的相关精神还可从宽。")
    assert 结果["已校验数"] == 1, 结果
    assert 结果["无条号引用"] == ["《民法典》"], 结果


def test_指代式引用判为未识别():
    """"参照本法第X条"不是"库里缺这部法" —— 补库清单里不该出现"本法"。"""
    结果 = verify_laws.classify_law_citations(法条库, "", "参照本法第七百九十三条的规定")
    assert 结果["未识别"] == ["参照本法第七百九十三条"], 结果
    assert 结果["库外"] == [] and 结果["疑似编造"] == []
    assert 结果["覆盖不足数"] == 0 and 结果["未校验数"] == 1


def test_长法名司法解释不被静默吞掉():
    """法名长度上限原来是 20 字，而《…民间借贷…若干问题的规定》27 字、
    《…时间效力的若干规定》31 字 —— 超限就不是"少校验一条"，是连未校验数都不进。"""
    全名 = ["《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》第25条",
            "《最高人民法院关于适用〈中华人民共和国民法典〉时间效力的若干规定》第2条"]
    for 引用 in 全名:
        assert verify_laws._提取法条引用(引用) == [引用], 引用


def test_库外司法解释只出note不出danger():
    目录 = _假法条库()
    try:
        结果 = verify_laws.classify_law_citations(
            目录, "", "依据《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》第25条认定利息上限。")
        assert 结果["库外"] and not 结果["疑似编造"], 结果
        风险 = score_analysis.generate_risk_list(格式通过, 结果, None)
        assert all(r["等级"] != "danger" for r in 风险), 风险
        assert any(r["等级"] == "note" for r in 风险), 风险
        assert score_analysis.compute_trust_score(格式通过, 结果, None)["等级"] == "中"
    finally:
        shutil.rmtree(目录, ignore_errors=True)


# ─────────────── 时效校验真的接上了 ───────────────

def test_已废止法条出danger():
    目录 = _假法条库()
    try:
        结果 = verify_laws.classify_law_citations(目录, "", "《旧测试法》第3条")
        assert 结果["可验证"][0]["版本警告"], 结果["可验证"][0]
        风险 = score_analysis.generate_risk_list(格式通过, 结果, None)
        assert any(r["等级"] == "danger" and "已废止" in r["内容"] for r in 风险), 风险
    finally:
        shutil.rmtree(目录, ignore_errors=True)


def test_案发早于施行出danger():
    目录 = _假法条库()
    try:
        结果 = verify_laws.classify_law_citations(目录, "2019-06-01", "《测试法》第5条")
        assert "早于" in 结果["可验证"][0]["版本警告"], 结果
    finally:
        shutil.rmtree(目录, ignore_errors=True)


def test_未给案发日期时说清并压住等级():
    目录 = _假法条库()
    try:
        结果 = verify_laws.classify_law_citations(目录, "", "《测试法》第5条")
        assert 结果["案发日期已知"] is False
        assert 结果["未校验数"] == 0          # 引用层面都校验到了，缺的是时效这一层
        风险 = score_analysis.generate_risk_list(格式通过, 结果, None)
        assert any("案发日期" in r["内容"] for r in 风险), 风险
        可信度 = score_analysis.compute_trust_score(格式通过, 结果, None)
        assert 可信度["等级"] == "中", 可信度      # 有原文可验证，但时效未校验 → 不给"高"
    finally:
        shutil.rmtree(目录, ignore_errors=True)


def test_库外引用只进补库清单不误报警():
    目录 = _假法条库()
    try:
        结果 = verify_laws.classify_law_citations(目录, "", "《完全没这部法》第1条")
        assert 结果["库外"] == ["《完全没这部法》第1条"]
        日志 = os.path.join(目录, "missing_laws.txt")
        assert open(日志, encoding="utf-8").read().count("《完全没这部法》第1条") == 1
        # 再跑一次不该重复记（原来按整行去重、比对却用裸引用 ⇒ 去重形同虚设）
        verify_laws.classify_law_citations(目录, "", "《完全没这部法》第1条")
        assert open(日志, encoding="utf-8").read().count("《完全没这部法》第1条") == 1
    finally:
        shutil.rmtree(目录, ignore_errors=True)


# ─────────────── 两个消费者不许各判各的 ───────────────

def test_库外引用不进danger():
    结果 = dict(空校验, 库外=["《电子签名法》第3条"], 覆盖不足数=1)
    风险 = score_analysis.generate_risk_list(格式通过, 结果, None)
    assert all(r["等级"] != "danger" for r in 风险), 风险
    assert any(r["等级"] == "note" and "不代表引用有误" in r["内容"] for r in 风险), 风险


def test_疑似编造才进danger():
    结果 = dict(空校验, 疑似编造=["《民法典》第99999条"])
    风险 = score_analysis.generate_risk_list(格式通过, 结果, None)
    assert [r["等级"] for r in 风险] == ["danger"], 风险


def test_溯源段号越界进danger():
    溯源 = {"引用数": 2, "总段落数": 3,
            "items": [{"段号": 2, "有效": True}, {"段号": 9, "有效": False}]}
    风险 = score_analysis.generate_risk_list(格式通过, dict(空校验), 溯源)
    assert any(r["等级"] == "danger" and "第9段" in r["内容"] for r in 风险), 风险


# ─────────────── 定级：绿灯必须有证据 ───────────────

def test_字数达标不能把可信度抬到高():
    """原来 `正面信号 >= 1` 里那一项来自"每段字数≥20"的格式检查，
    于是一份什么都没校验到的分析会显示"可信"。"""
    可信度 = score_analysis.compute_trust_score(格式通过, dict(空校验), None)
    assert 可信度["等级"] == "中", 可信度


def test_有库内原文且无未校验才判高():
    结果 = dict(空校验, 可验证=[{"引用": "《民法典》第1165条", "状态": "现行有效", "版本警告": ""}],
                已校验数=1)
    可信度 = score_analysis.compute_trust_score(格式通过, 结果, None)
    assert 可信度["等级"] == "高", 可信度


def test_有一条没校验就最多判中():
    结果 = dict(空校验, 可验证=[{"引用": "《民法典》第1165条", "状态": "现行有效", "版本警告": ""}],
                无条号引用=["《民法典》"], 未校验数=1, 已校验数=1)
    assert score_analysis.compute_trust_score(格式通过, 结果, None)["等级"] == "中"


def test_疑似编造直接判低():
    结果 = dict(空校验, 疑似编造=["《民法典》第99999条"])
    assert score_analysis.compute_trust_score(格式通过, 结果, None)["等级"] == "低"


def test_旧报告缺键不炸():
    """历史 JSON 里没有 法条校验 这个键，消费者要能降级而不是抛。"""
    assert isinstance(score_analysis.generate_risk_list(格式通过, None, None), list)
    assert score_analysis.compute_trust_score(格式通过, None, None)["等级"] == "中"


if __name__ == "__main__":
    测试们 = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for 名, t in 测试们:
        t()
        print(f"  ✓ {名}")
    print(f"\n{len(测试们)} 个测试全通过")
