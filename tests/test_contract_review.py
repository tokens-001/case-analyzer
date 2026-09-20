"""合同审查这条链路的离线测试：解析 → 条款锚点三态 → 可信度封顶。

全本地、不调 API。跑法：python3 -m pytest tests/ -q

⚠️ 这里能验的是**校验层**，验不了模型会不会守 `【第N条】「摘录」` 的格式 ——
那要真跑一次。所以下面专门有一条 test_模型不守格式时不许判成通过，
保证"提示词没被执行"这种情况落到『未校验』而不是『通过』。
"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))

import parse_doc                                            # noqa: E402
from skills.legal import score_analysis, verify_clauses     # noqa: E402

条款正文 = {
    '一': '第一条 标的。乙方向甲方提供系统运维服务，详见附件一。',
    '三': '第三条 费用。合同总价人民币12万元，按季度支付，验收合格后付尾款。',
    '五': '第五条 保密。双方对履行中知悉的商业秘密负保密义务，期限三年。',
}


def _造docx(段落):
    """最小可用 docx：zip + word/document.xml。不引 python-docx 就是为了这个测试能裸跑。"""
    W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    体 = ''.join(f'<w:p><w:r><w:t>{t}</w:t></w:r></w:p>' for t in 段落)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}"><w:body>{体}</w:body></w:document>'
    缓冲 = io.BytesIO()
    with zipfile.ZipFile(缓冲, 'w') as 档:
        档.writestr('[Content_Types].xml', '<Types/>')
        档.writestr('word/document.xml', xml)
    return 缓冲.getvalue()


# ─────────────── 解析 ───────────────

def test_docx解析出条款表与锚点文本():
    字节 = _造docx(['甲方委托乙方提供运维服务。'] + [条款正文[k] for k in ('一', '三', '五')])
    出 = parse_doc.解析(字节, '合同.docx')
    assert 出['错误'] is None and 出['条数'] == 3, 出
    assert set(出['条款']) == {'前言', '一', '三', '五'}
    assert '【第三条】' in 出['文本']
    # 锚点单独成行，正文原样 —— 摘录取证要拿模型引的话跟原文逐字比
    assert '\n' + 条款正文['三'] in 出['文本'].replace('【第三条】\n', '\n【第三条】\n')


def test_解析不出文字时拒绝而不是交空文本():
    出 = parse_doc.解析(_造docx(['第一条']), 'a.docx')      # 合法 docx，但内容只有 3 字
    assert 出['错误'] and '扫描件' in 出['错误'], 出
    assert 出['文本'] == ''          # 绝不把空文本交给模型：那会换来一份漂亮的假风险清单
    assert '不是 zip' in parse_doc.解析(b'', '空.docx')['错误']   # 空字节流是另一回事


def test_没有条号结构时要出声():
    出 = parse_doc.解析(('这是一份没有任何条款编号的协议正文。' * 6).encode('utf-8'), 'a.txt')
    assert 出['条数'] == 0 and any('锚点校验无法建立' in w for w in 出['警告']), 出


def test_老doc与未知后缀都明确拒绝():
    assert '不是 zip' in parse_doc.解析(b'plain', 'a.docx')['错误']
    assert '.doc' in parse_doc.解析(b'x', 'a.doc')['错误']


# ─────────────── 条款锚点三态 ───────────────

def test_摘录对得上才算可验证():
    分 = "- 【第三条】「合同总价人民币12万元，按季度支付」付款节点对我方不利"
    果 = verify_clauses.verify_clause_anchors(条款正文, 分)
    assert len(果['可验证']) == 1 and 果['未校验数'] == 0, 果


def test_条号不存在判疑似编造():
    分 = "- 【第九条】「甲方有权单方变更价格」"
    果 = verify_clauses.verify_clause_anchors(条款正文, 分)
    assert 果['疑似编造'] and '没有第九条' in 果['疑似编造'][0]['原因'], 果


def test_条号在但摘录不在也判疑似编造():
    """合同场景最常见的一种幻觉：引用一个真实存在的条号，挂一句那条里根本没有的话。"""
    分 = "- 【第三条】「乙方不得承接任何第三方同类业务」"
    果 = verify_clauses.verify_clause_anchors(条款正文, 分)
    assert len(果['疑似编造']) == 1 and '没有这句话' in 果['疑似编造'][0]['原因'], 果


def test_摘录中间省略号不影响匹配():
    分 = "- 【第三条】「合同总价人民币12万元……验收合格后付尾款」"
    assert len(verify_clauses.verify_clause_anchors(条款正文, 分)['可验证']) == 1


def test_标点全半角差异不影响匹配():
    分 = '- 【第三条】「合同总价人民币12万元,按季度支付」'      # 半角逗号
    assert len(verify_clauses.verify_clause_anchors(条款正文, 分)['可验证']) == 1


def test_只给条号不给摘录算未校验():
    果 = verify_clauses.verify_clause_anchors(条款正文, "- 【第五条】 保密期限未约定起算点")
    assert 果['无摘录'] and 果['未校验数'] == 1 and 果['已校验数'] == 0, 果


def test_风险条目没挂条号算未校验():
    果 = verify_clauses.verify_clause_anchors(条款正文, "- 合同没有约定解除条件\n- 违约金计算方式不清")
    assert len(果['无锚点条目']) == 2 and 果['未校验数'] == 2, 果


# ─────────────── 与两个消费者接上 ───────────────

def _合同校验(**盖):
    基 = {'可验证': [], '疑似编造': [], '无摘录': [], '无锚点条目': [],
          '已校验数': 0, '未校验数': 0}
    基.update(盖)
    return 基


def test_疑似编造条款进danger而只给条号进warning():
    校验 = _合同校验(疑似编造=[{'引用条号': '九', '摘录': 'x', '原因': '合同里没有第九条'}],
                     无摘录=[{'引用条号': '五'}], 未校验数=1)
    风险 = score_analysis.generate_risk_list({"问题": []}, _合同校验(), None, 条款校验=校验)
    assert any(r['等级'] == 'danger' and '第九条' in r['内容'] for r in 风险), 风险
    assert any(r['等级'] == 'warning' and '未摘原文' in r['内容'] for r in 风险), 风险


# ─────────────── 款级锚点：【第N条第M款】 ───────────────

多条款表 = {
    '二': '第二条 工作内容。\n1、乙方担任运维岗位工作。\n2、乙方工作地点为甲方注册地。\n'
          '3、甲方可根据生产经营需要调整乙方工作岗位。\n4、双方另行协商培训安排。',
    '五': '第五条 保密。双方对商业秘密负保密义务，期限三年。',   # 不分款的合同
}


def test_带款后缀的锚点不能静默消失():
    """真合同实测：模型 48 个锚点里 19 个写成【第二条第3款】。原正则要求 `条` 后紧跟 `】`，
    整体匹配不上；而"无锚点条目"那道兜底又用 `'【' not in 行` 把这种行排除 —— 两边都不管，
    这 19 条既不判可验证、也不判疑似编造、更不计进未校验，等于**看不见就当过了**。"""
    校 = verify_clauses.verify_clause_anchors(
        多条款表, "- 【第二条第3款】「甲方可根据生产经营需要调整乙方工作岗位」 风险：单方调岗")
    assert len(校["可验证"]) == 1, 校
    assert 校["疑似编造"] == [] and 校["锚点无法解析"] == [], 校


def test_款级锚点下的编造摘录必须被抓到():
    """这条是上面那个洞的正面证据：修之前这句话谁都不判，修之后必须落 疑似编造。"""
    校 = verify_clauses.verify_clause_anchors(
        多条款表, "- 【第二条第3款】「乙方可以随时拒绝任何岗位调整且不承担任何后果」 风险：x")
    assert 校["可验证"] == [], 校
    assert len(校["疑似编造"]) == 1, 校
    assert "第3款里没有这句话" in 校["疑似编造"][0]["原因"], 校


def test_款号超出该条款数时判编造():
    校 = verify_clauses.verify_clause_anchors(
        多条款表, "- 【第二条第9款】「甲方可根据生产经营需要调整乙方工作岗位」 风险：x")
    assert 校["可验证"] == [], 校
    assert len(校["疑似编造"]) == 1 and "只有 4 款" in 校["疑似编造"][0]["原因"], 校


def test_不分款的合同不拿款号指控():
    """有些合同不写"1、2、"而写"（一）"或根本不分款。这时款号无从数起，
    指控"没有第2款"就是误伤 —— 退回整条比对。"""
    校 = verify_clauses.verify_clause_anchors(
        多条款表, "- 【第五条第2款】「双方对商业秘密负保密义务，期限三年」 风险：x")
    assert len(校["可验证"]) == 1, 校
    assert 校["疑似编造"] == [], 校


def test_摘录在别款里却挂到这款也要抓到():
    """款定位要是退化成"整条都比一遍"，这条就漏了 —— 摘的是第1款的话却挂【第3款】，
    对读者来说就是"这条依据核对过了"，而它指向的位置根本没有这句话。"""
    校 = verify_clauses.verify_clause_anchors(
        多条款表, "- 【第二条第3款】「乙方担任运维岗位工作」 风险：x")
    assert 校["可验证"] == [], 校
    assert len(校["疑似编造"]) == 1, 校
    assert "第3款里没有这句话" in 校["疑似编造"][0]["原因"], 校
    # 同一句话挂对款号就该过 —— 证明上面那条不是误伤
    对 = verify_clauses.verify_clause_anchors(
        多条款表, "- 【第二条第1款】「乙方担任运维岗位工作」 风险：x")
    assert len(对["可验证"]) == 1, 对


def test_解析不了的引用形状要计进未校验():
    """兜底本身也得有证据：写成一个正则吃不下的样子（第2条之3），
    不许它悄悄过去，也不许把已经认得的写法误报进来。"""
    校 = verify_clauses.verify_clause_anchors(
        多条款表, "- 【第2条之3】「甲方可根据生产经营需要调整乙方工作岗位」 风险：x")
    assert 校["锚点无法解析"] == ["【第2条之3】"], 校
    assert 校["未校验数"] >= 1, 校
    正常 = verify_clauses.verify_clause_anchors(多条款表, "- 【第二条】「乙方担任运维岗位工作」 风险：x")
    assert 正常["锚点无法解析"] == [], 正常     # 认得的写法一条都不能误报


def test_认不出的引用要在风险列表里说一声():
    """计入未校验数只是封顶；用户得知道**为什么**被封顶。少了这条，
    读数会变成"有 1 处未校验"却看不出是哪一处、为什么。"""
    校 = verify_clauses.verify_clause_anchors(
        多条款表, "- 【第2条之3】「甲方可根据生产经营需要调整乙方工作岗位」 风险：x")
    风险 = score_analysis.generate_risk_list({"问题": []}, None, None, 条款校验=校)
    assert any(r["等级"] == "warning" and "本地校验认不出来" in r["内容"] for r in 风险), 风险
    assert any("【第2条之3】" in r["内容"] for r in 风险), 风险


def test_模型不守格式时不许判成通过():
    """提示词写了格式也不保证模型照做。真没照做时，读数的正确形状是"什么都没校验到"
    （→ 可信度封顶在中），而不是 0/0 的假绿灯。"""
    乱写 = "该合同风险较高，建议谈判时注意违约金条款与保密条款。"
    果 = verify_clauses.verify_clause_anchors(条款正文, 乱写)
    assert 果['已校验数'] == 0
    可信度 = score_analysis.compute_trust_score({"通过": True, "问题": []}, _合同校验(), None,
                                               条款校验=果)
    assert 可信度['等级'] == '中', 可信度


def test_有可验证锚点且无未校验项才判高():
    法条 = {'可验证': [{'引用': '《民法典》第1165条', '状态': '现行有效', '版本警告': ''}],
            '疑似编造': [], '库外': [], '未识别': [], '无条号引用': [],
            '已校验数': 1, '覆盖不足数': 0, '未校验数': 0, '案发日期已知': True}
    条款 = _合同校验(可验证=[{'引用条号': '三'}], 已校验数=1)
    可信度 = score_analysis.compute_trust_score({"通过": True, "问题": []}, 法条, None, 条款校验=条款)
    assert 可信度['等级'] == '高', 可信度


if __name__ == "__main__":
    测试们 = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for 名, t in 测试们:
        t()
        print(f"  ✓ {名}")
    print(f"\n{len(测试们)} 个测试全通过")
