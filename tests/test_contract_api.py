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
    "谈判顺序": "- 【第一条】「乙方向甲方提供系统运维服务，详见附件一」 建议：把附件一并入正文或写明冲突时以正文为准",
}


# 每个维度的提示词里唯一的任务句 —— 用它认维度，顺带证明这些指令真的进了提示词
任务句 = {"风险清单": "逐条列出对我方的风险", "缺失条款": "对照上面的必查清单",
          "失衡条款": "权利义务不对等", "歧义表述": "无法执行的条款",
          "谈判顺序": "谈判清单"}


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
    # 桩里挂了 4 个锚点：第三条、第七条、第五条(无摘录)、第一条 → 对得上原文的是 2 处
    assert 校验["已校验数"] == 2, 校验
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


if __name__ == "__main__":
    测试们 = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for 名, t in 测试们:
        t()
        print(f"  ✓ {名}")
    print(f"\n{len(测试们)} 个测试全通过")
