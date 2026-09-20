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
    （真实存在）就是这么被指控的。
    ⚠️ 用例故意**不依赖真库**：电子签名法 2026-09-20 已经补进库了，
    拿真库当"库里没有"的判据，补一部法就会红一条 —— 这条测的是分类规则，
    不是库的清单。"""
    目录 = _假法条库()
    try:
        结果 = verify_laws.classify_law_citations(目录, "", "《完全没这部法》第1条")
        assert 结果["库外"] == ["《完全没这部法》第1条"]
        assert 结果["疑似编造"] == []
        assert 结果["覆盖不足数"] == 1
    finally:
        shutil.rmtree(目录, ignore_errors=True)


def test_真库里查不到的法仍判库外不判编造():
    """同一件事在真库上再验一次，但用一部**确实没补进来的**法，
    免得哪天补进来又把用例弄红。"""
    for 引 in ["《证券法》第八十条", "《消费者权益保护法》第55条", "《个人信息保护法》第13条"]:
        结果 = verify_laws.classify_law_citations(法条库, "", 引)
        assert 结果["库外"] == [引], 结果
        assert 结果["疑似编造"] == [], 结果


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


def test_缺施行日期不影响已废止告警():
    """`if not 施行日期: return None` 原来排在状态判断前面 —— 一部没写施行日期的库文件
    哪怕标着"已废止"也会静默返回 None。缺一份元数据，不该把另一条无关的判据一起吞掉。"""
    目录 = tempfile.mkdtemp(prefix="法条库-")
    try:
        with open(os.path.join(目录, "无日期法.txt"), "w", encoding="utf-8") as f:
            f.write("#META\n法名: 无日期法\n状态: 已废止\n#END\n\n第1条\n旧条文。\n")
        结果 = verify_laws.classify_law_citations(目录, "", "《无日期法》第1条")
        assert "已废止" in 结果["可验证"][0]["版本警告"], 结果
    finally:
        shutil.rmtree(目录, ignore_errors=True)


# ─────────────── 案发时间怎么认 ───────────────

def test_案发时间认这几种写法():
    对 = {"2023-04-05": "2023-04-05", "2023/4/5": "2023-04-05", "2023.4.5": "2023-04-05",
          "2023年4月5日": "2023-04-05", "2019年5月": "2019-05-01",
          "2023-04": "2023-04-01", "2023": "2023-01-01", "2023年": "2023-01-01",
          "  2023年  ": "2023-01-01"}
    for 原始, 期望 in 对.items():
        assert verify_laws.规范案发日期(原始) == 期望, 原始
    # 只到年/月时补 1 号：往早取，"案发早于施行"才不会因补到月末而漏报


def test_读不懂的案发时间一律不收():
    for 坏 in ["", "   ", None, 2023, "2019年左右", "前几年", "2023-13-01", "2023-02-30",
               "第五十条", "2023-04-05 至 2023-06-01"]:
        assert verify_laws.规范案发日期(坏) is None, 坏


def test_填了但读不懂的案发时间不能点亮绿灯():
    """这条是整个改动的落点：悄悄把垃圾当"没填"，用户会以为时效比过了。"""
    目录 = _假法条库()
    try:
        结果 = verify_laws.classify_law_citations(目录, "2019年左右", "《测试法》第5条")
        assert 结果["案发日期已知"] is False, 结果
        assert 结果["案发日期无法解析"] is True and 结果["案发日期原文"] == "2019年左右", 结果
        assert 结果["可验证"][0]["版本警告"] == "", 结果   # 没日期就不许凭空比出个结论
        可信度 = score_analysis.compute_trust_score(格式通过, 结果, None)
        assert 可信度["等级"] == "中", 可信度
        风险 = score_analysis.generate_risk_list(格式通过, 结果, None)
        assert any("没能识别" in r["内容"] for r in 风险), 风险   # 要说得出是用户填错了
    finally:
        shutil.rmtree(目录, ignore_errors=True)


def test_中文写法的案发时间能过时效这道门():
    """绿灯本来就存在，只是 `app` 写死传空串 ⇒ 永不可达。前端补了输入框，这里锁住
    "填了能认、认了真比、比过才抬等级"整条判据。"""
    目录 = _假法条库()
    try:
        结果 = verify_laws.classify_law_citations(目录, "2021年3月", "《测试法》第5条")
        assert 结果["案发日期已知"] is True, 结果
        assert 结果["可验证"][0]["版本警告"] == "", 结果        # 施行 2020-01-01，案发在其后
        可信度 = score_analysis.compute_trust_score(格式通过, 结果, None)
        assert 可信度["等级"] == "高", 可信度
        assert any("时效已按案发时间" in s["来源"] for s in 可信度["明细"]), 可信度
    finally:
        shutil.rmtree(目录, ignore_errors=True)


# ─────────────── 条号写法：中文数字、带零、带"之一" ───────────────

def test_中文条号带零不能被截断():
    """民法典 989 条以后全是"第一千零七十九条"这种写法，而数字类正则漏了 零，
    于是被截成"《民法典》第一千"落进未识别 —— 永远校验不了。
    `data/laws/missing_laws.txt` 里那条"《中华人民共和国民法典》第一千"就是证据。"""
    for 引用 in ["《民法典》第一千零七十九条", "《民法典》第一千零四十六条", "《民法典》第一千一百六十八条"]:
        assert verify_laws._提取法条引用(引用) == [引用], 引用
        结果 = verify_laws.classify_law_citations(法条库, "", 引用)
        assert 结果["可验证"], 结果
        assert 结果["未识别"] == [] and 结果["疑似编造"] == [], 结果


def test_中文与阿拉伯写法必须判到同一条原文():
    甲 = verify_laws.classify_law_citations(法条库, "", "《民法典》第一千零七十九条")
    乙 = verify_laws.classify_law_citations(法条库, "", "《民法典》第1079条")
    assert [e["条文"] for e in 甲["可验证"]] == [e["条文"] for e in 乙["可验证"]], (甲, 乙)


def test_条号之一不能拿基条冒充():
    """原来"之一"整个被丢掉：《刑法》第133条之一（危险驾驶罪）返回的是
    第133条（交通肇事罪）的原文，还照样算"可验证" —— 这是假绿灯。"""
    变体 = verify_laws.classify_law_citations(法条库, "", "《刑法》第133条之一")["可验证"][0]
    基条 = verify_laws.classify_law_citations(法条库, "", "《刑法》第133条")["可验证"][0]
    assert 变体["条文"].startswith("第133条之一"), 变体["条文"]
    assert 变体["条文"] != 基条["条文"]


def test_基条在库而变体不在时判未校验不判编造():
    """库里有第5条、没有"第5条之一" ⇒ 这是库不全，不是有人编造。"""
    目录 = _假法条库()
    try:
        结果 = verify_laws.classify_law_citations(目录, "", "《测试法》第5条之一")
        assert 结果["未识别"] == ["《测试法》第5条之一"], 结果
        assert 结果["疑似编造"] == [], 结果
        assert 结果["未校验数"] == 1 and 结果["已校验数"] == 0, 结果
        # 基条也不在库里，才轮到"疑似编造"
        另一个 = verify_laws.classify_law_citations(目录, "", "《测试法》第99条之一")
        assert 另一个["疑似编造"] == ["《测试法》第99条之一"], 另一个
    finally:
        shutil.rmtree(目录, ignore_errors=True)


def test_全称法名要能落到库里的短文件名():
    """判决书里写的是《中华人民共和国著作权法》这种全称。原来归一化靠一张写死的
    简称白名单（只有民法典/刑法/宪法/行政法/民诉/刑诉六个），名单外的全称带着
    "中华人民共和国"前缀去比文件名 ⇒ 判成"库里没这部法"。"""
    assert verify_laws._解析法名("《中华人民共和国著作权法》第三条") == "著作权法"
    assert verify_laws._解析法名("《中华人民共和国公司法》第107条") == "公司法"
    结果 = verify_laws.classify_law_citations(法条库, "", "《中华人民共和国著作权法》第三条")
    assert 结果["可验证"], 结果
    assert 结果["库外"] == [], 结果


def test_无书名号的法名不能把前面的词一起吞进来():
    """字符类漏掉括号和星号时，"*公平责任**（民法典第1186条"整段被当成法名，
    全靠白名单子串命中才救回来 —— 正则修好后这条得自己站得住。"""
    assert verify_laws._解析法名("*公平责任**（民法典第1186条") == "民法典"
    assert verify_laws._解析法名("参照本法第七百九十三条") == "参照本法"   # 交给相对指代判


def test_库里新增著作权法后历史那几条不再是库外():
    """补库的落点：这几条是 missing_laws.txt 里真实出现过的引用。"""
    for 引 in ["《著作权法》第24条", "《著作权法》第四十九条", "《中华人民共和国著作权法》第三条"]:
        结果 = verify_laws.classify_law_citations(法条库, "", 引)
        assert 结果["可验证"], 结果
        assert 结果["库外"] == [] and 结果["疑似编造"] == [], 结果


def test_合同附件与内部制度不算法规引用():
    """桌面那份劳动合同里出现的是《员工手册》《保密协议》《竞业限制协议》
    《岗位说明书》—— 它们不是法。原来两条分支都走错：
      带条号 → 判"库外" → 写进 missing_laws.txt，等于让人去补一部不存在的法；
      不带条号 → 计入未校验数 → 把可信度无端封顶在「中」。
    未校验数的意思是"本工具没说它对了"，掺进非法规引用就污染了这个读数。"""
    目录 = _假法条库()
    try:
        结果 = verify_laws.classify_law_citations(
            目录, "", "按《竞业限制协议》第3条执行；依据《员工手册》考核；《保密协议》第5条约定违约金。")
        assert 结果["库外"] == [], 结果
        assert 结果["无条号引用"] == [], 结果
        assert sorted(结果["未识别"]) == ["《保密协议》第5条", "《竞业限制协议》第3条"], 结果
        assert not os.path.exists(os.path.join(目录, "missing_laws.txt")), "补库清单被写进了非法规"
    finally:
        shutil.rmtree(目录, ignore_errors=True)


def test_像法规的名字仍按老规则判():
    """反向兜底：加了白名单不能把真法也一起放过。"""
    目录 = _假法条库()
    try:
        结果 = verify_laws.classify_law_citations(
            目录, "", "依据《劳动合同法》相关规定解除；另见《完全没这部法》第1条；按《XX管理办法》第2条办理。")
        assert 结果["无条号引用"] == ["《劳动合同法》"], 结果
        assert set(结果["库外"]) == {"《完全没这部法》第1条", "《XX管理办法》第2条"}, 结果
        assert 结果["未识别"] == [], 结果
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


# ─────────────── 两格读数：核到多少 / 有多少没法核 ───────────────

def _可验证(n):
    return [{"引用": f"《民法典》第{i}条", "状态": "现行有效", "版本警告": ""} for i in range(1, n + 1)]


def test_等级相同的两份报告覆盖度要能分出差别():
    """单看等级：一份核到 3 条、一份核到 1 条，都是"中"，读者分不出来。
    拆成两格就是让"核了多少"和"有多少压根没法核"各自可见。"""
    甲 = dict(空校验, 可验证=_可验证(3), 已校验数=3, 无条号引用=["《民法典》"], 未校验数=1)
    乙 = dict(空校验, 可验证=_可验证(1), 已校验数=1,
              无条号引用=["《民法典》"] * 5, 未校验数=5)
    信甲 = score_analysis.compute_trust_score(格式通过, 甲, None)
    信乙 = score_analysis.compute_trust_score(格式通过, 乙, None)
    assert 信甲["等级"] == 信乙["等级"] == "中"          # 等级确实分不出来 —— 所以才要拆
    assert (信甲["核验"]["核到"], 信甲["覆盖度"]) == (3, 0.75), 信甲
    assert (信乙["核验"]["核到"], 信乙["覆盖度"]) == (1, 0.17), 信乙
    assert 信乙["核验"]["没法核"] == 5, 信乙


def test_对不上的也算核过不是没核过():
    """覆盖度问的是"这条有没有拿到一个结论"，结论是"编造"也算拿到了。
    把它算进"没法核"会让覆盖度变成"只统计好消息"。"""
    校验 = dict(空校验, 可验证=_可验证(1), 疑似编造=["《民法典》第99999条"], 已校验数=2)
    可信度 = score_analysis.compute_trust_score(格式通过, 校验, None)
    assert 可信度["核验"] == {"核到": 1, "对不上": 1, "没法核": 0, "库外": 0, "引用总数": 2}, 可信度["核验"]
    assert 可信度["覆盖度"] == 1.0, 可信度
    assert 可信度["等级"] == "低", 可信度               # 有编造 → 等级照低压


def test_库外算进分母但不算核过():
    校验 = dict(空校验, 可验证=_可验证(1), 已校验数=1, 库外=["《证券法》第80条"], 覆盖不足数=1)
    可信度 = score_analysis.compute_trust_score(格式通过, 校验, None)
    assert 可信度["核验"]["库外"] == 1 and 可信度["核验"]["引用总数"] == 2, 可信度["核验"]
    assert 可信度["覆盖度"] == 0.5, 可信度


def test_合同条款锚点也算进核到():
    """真合同实测：核到的 50 处里有 48 处是条款锚点。漏算锚点，读数会从
    "核到 50 · 覆盖 94%" 掉到 "核到 2 · 覆盖 4%" —— 而等级一个字都不变，
    等于把一个跑得很好的校验层报成没跑。"""
    条款 = {"可验证": [{"引用条号": str(i)} for i in range(1, 49)], "疑似编造": [],
            "无摘录": [], "无锚点条目": [], "已校验数": 48, "未校验数": 0}
    校验 = dict(空校验, 可验证=_可验证(1), 已校验数=1)
    信 = score_analysis.compute_trust_score(格式通过, 校验, None, 条款校验=条款)
    assert 信["核验"]["核到"] == 49, 信["核验"]
    assert 信["核验"]["引用总数"] == 49, 信["核验"]
    assert 信["覆盖度"] == 1.0, 信


def test_一条依据都没有时不给覆盖度():
    """引用总数 0 → 分母为 0。硬算成 0% 会被读成"一条都没核过"，
    而真实情况是"模型一条可核的依据都没给" —— 得让前端能说这句话。"""
    可信度 = score_analysis.compute_trust_score(格式通过, dict(空校验), None)
    assert 可信度["核验"]["引用总数"] == 0, 可信度
    assert 可信度["覆盖度"] is None, 可信度


# ─────────────── 提示词与判据同源 ───────────────

def test_提示词里的引用格式与校验判据同源():
    """历史分析 58 处引用里 30 处（52%）只写了《法名》没给条号 —— 那种引用结构上
    校验不了。原来 `_base.法条提示` 是一句软要求（"如能确定…请引用…"），
    模型完全可以理解成"不确定就不写条号"。现在格式定义在 verify_laws 里，
    和检查它的判据同一个文件，两边不会再各说各话。"""
    from skills.legal import _base
    assert verify_laws.法条引用格式要求 in _base.法条提示, "提示词与判据漂移了"
    assert "必须写到条号" in _base.法条提示, _base.法条提示


def test_法条提示真的进了各维度的提示词():
    """拼好了但没被任何技能用上 = 白改。这里拿一个维度实际构造一次提示词来验。"""
    from skills.legal import extract_dispute
    收到 = {}

    def 假问AI(提示词, 判例文字, api_key, 附段落编号=True):
        收到["提示词"] = 提示词
        return "### 争议一：合同是否成立"

    原 = extract_dispute.问AI
    extract_dispute.问AI = 假问AI
    try:
        extract_dispute.执行("原告与被告因借款合同成讼。" * 30, "sk-测试")
        assert "必须写到条号" in 收到.get("提示词", ""), 收到.get("提示词", "")[-200:]
    finally:
        extract_dispute.问AI = 原


if __name__ == "__main__":
    测试们 = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for 名, t in 测试们:
        t()
        print(f"  ✓ {名}")
    print(f"\n{len(测试们)} 个测试全通过")
