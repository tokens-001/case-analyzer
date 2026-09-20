"""存储 → 历史 → 下载 → 反馈 → 看板 这条"事后"链路。

这一层原来**一只测试都没有**：改坏了不会红，于是三份要给别人看的东西
（存下来的报告、下载下来的 txt、汇到看板的计数）可以各说各话。
这里挑的都是"会在真人面前说假话或丢数据"的那几条。

跑法：python3 -m pytest tests/ -q
"""
import datetime
import glob
import json
import os
import sys
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="判例助手-路由测试-"))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-测试用不联网")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))

import app as app_mod                                        # noqa: E402
from test_contract_api import 合同正文, 桩输出, _装桩, _客户端   # noqa: E402


def _找存储文件(名片段):
    """按名字片段找落盘的报告。

    不能在测试里调 `app.用户数据目录()` —— 那个函数读 session，脱离请求上下文直接
    RuntimeError。测试客户端的 uid 就藏在它自己的 cookie 里，glob 整个数据目录反而
    是**不依赖实现细节**的那一种拿法。
    """
    中 = [f for f in glob.glob(os.path.join(app_mod.数据根目录, "*", f"*{名片段}*.json"))
          if not os.path.basename(f).startswith(("limit_", "session_secret"))]
    assert len(中) == 1, 中
    return 中[0]


def _分析一次(名字="运维合同", 客户端=None):
    _装桩()
    客 = 客户端 or _客户端()
    回 = 客.post("/analyze", json={"name": 名字, "text": 合同正文, "mode": "contract"})
    assert 回.status_code == 200, 回.get_json()
    return 客, 回.get_json()


# ── 存储与历史 ──

def test_存下来的报告带着当时的核验读数():
    """原来只存分析文字。于是"这份报告当时核到多少条"这个问题**没有任何地方能回答**，
    复盘不了，误指控率也就永远算不出来。"""
    客, 数 = _分析一次("带读数的合同")
    存 = json.load(open(_找存储文件("带读数的合同"), encoding='utf-8'))
    assert 存["核验"]["核验"], 存.keys()
    assert 存["模式"] == "合同审查"
    assert 存["核验"]["核验"]["引用总数"] == 数["可信度"]["核验"]["引用总数"], "存下来的数和返回的数不是同一个"


def test_历史列表不把次数表当报告列出来():
    """`limit_日期.json` 和分析结果住在同一个目录，而且按倒序排它还在最前面。"""
    客, _ = _分析一次("列历史")
    目录 = os.path.dirname(_找存储文件("列历史"))
    # 看板数的是**所有用户**的目录，别的测试也往里写过 —— 所以拿前后差值，不拿绝对值
    看板前 = json.loads(客.get("/dashboard").get_data())["分析总数"]
    for n in range(3):
        json.dump({f"u{n}": n}, open(os.path.join(目录, f"limit_2026-01-0{n}.json"), "w"))
    列 = 客.get("/history").get_json()
    assert all(not x["文件名"].startswith("limit_") for x in 列), 列
    assert len(列) == 1, 列
    assert 列[0]["模式"] == "合同审查", 列[0]
    # 看板数的是同一个目录 —— 那里的漏法一模一样，但那句判断在两个函数里各写了一遍，
    # 所以两边都得测（只测 /history 的话，把 后台面板 那句删了也不会红）。
    看板后 = json.loads(客.get("/dashboard").get_data())["分析总数"]
    assert 看板后 == 看板前, f"三份次数表被当成了三份报告：{看板前} → {看板后}"


def test_详情路由不走出自己的目录():
    """⚠️ 这条**不能**靠发请求来测：URL 里的 `..` 在进路由之前就被 Werkzeug 折掉了，
    发出去的请求永远到不了那道防线，测试会因为"根本到不了"而绿 —— 那是装饰不是测试。
    只能直接调路由函数，把带 `..` 的文件名当作参数喂进去。
    """
    客, _ = _分析一次("越界")
    我的目录 = os.path.dirname(_找存储文件("越界"))
    别 = os.path.join(app_mod.数据根目录, "别人的目录")
    os.makedirs(别, exist_ok=True)
    json.dump({"判例名": "别人的秘密", "模式": "合同审查", "风险清单": "不该被你看到的一段"},
              open(os.path.join(别, "x.json"), "w"), ensure_ascii=False)
    def _直调(名):
        # 直接调视图函数拿到的是 `return jsonify(...), 404` 那个元组，
        # make_response 才是测试客户端内部做的那一步转换。
        with 客.application.test_request_context("/case/x"):
            return 客.application.make_response(app_mod.详情路由(名))
    回 = _直调("../别人的目录/x.json")
    assert 回.status_code == 404, 回.status_code
    assert "别人的秘密" not in 回.get_data().decode("utf-8"), "读到别人那份报告了"
    assert _直调(os.path.basename(我的目录) + "/../../别人的目录/x.json").status_code == 404
    assert _直调(_找存储文件("越界")).status_code == 404, "绝对路径也算越界"


def test_从历史打开不会凭空亮一个验证通过():
    """这是这批里最要脸的一条：旧实现给每次"打开历史"都现编 `{"通过": True}`，
    于是页面上一条绿勾，而这一次点击**一次校验都没做**。
    """
    客, 数 = _分析一次("要重开的合同")
    档 = os.path.basename(_找存储文件("要重开的合同"))
    打 = 客.get(f"/case/{档}").get_json()
    assert 打["可信度"], "存了核验读数却没带出来"
    assert 打["可信度"]["等级"] == 数["可信度"]["等级"], 打["可信度"]
    assert 打["验证"]["通过"] == 数["验证"]["通过"], 打["验证"]
    assert 打["风险列表"], "重开一份报告，要人去核实的东西不该变空"

    # 再伪造一份"改数据之前就存下来的"旧报告：没存核验读数
    json.dump({"判例名": "旧记录", "日期": "2026-01-01", "模式": "合同审查",
               "风险清单": "- 【第三条】「合同总价人民币12万元」 风险：先款后验"},
              open(os.path.join(os.path.dirname(_找存储文件("要重开的合同")),
                                "2026-01-01_旧记录.json"), "w"),
              ensure_ascii=False)
    旧 = 客.get("/case/2026-01-01_旧记录.json").get_json()
    assert 旧["验证"] is None, 旧["验证"]
    assert 旧["可信度"] is None, 旧["可信度"]
    assert 旧["风险列表"] == [], 旧["风险列表"]
    assert "验证通过" not in json.dumps(旧, ensure_ascii=False), "还是在替旧记录宣布验证通过"
    assert (旧["验证"] or {}).get("通过") is not True, 旧["验证"]


def test_响应带着报告文件名():
    """逐条反馈要落到**具体那份报告**上，靠的就是这个字段；历史详情也得给，
    否则从旧报告上点出来的"没看懂"会挂在一个空标识上，事后没法 join。"""
    客, 数 = _分析一次("带标识的报告")
    assert 数["报告文件"] and not os.path.isabs(数["报告文件"]), 数["报告文件"]
    assert 数["报告文件"] in os.path.basename(_找存储文件("带标识的报告")), 数["报告文件"]
    打 = 客.get(f"/case/{数['报告文件']}").get_json()
    assert 打["报告文件"] == 数["报告文件"], 打.get("报告文件")


def test_存进去的元数据不会变成一张卡片():
    """前端把 分析 里的每个键都渲染成一张卡。核验/合同类型/时间基准漏进去，
    报告页就凭空多出一张「📌 核验」。"""
    客, _ = _分析一次("元数据别冒出来")
    打 = 客.get(f"/case/{os.path.basename(_找存储文件('元数据别冒出来'))}").get_json()
    assert set(打["分析"]) == set(桩输出) | {"总结"}, 打["分析"].keys()
    assert 打["合同类型"], "类型该从顶层读，而不是混进分析里"


# ── 反馈 ──

def _交(客, 名字, 备注):
    return 客.post("/feedback", json={"case_name": 名字, "helpfulness": "very",
                                      "most_valuable": ["风险清单"], "comment": 备注})


def test_同日同名不再互相覆盖():
    """问卷是决定下一版砍哪个模块的唯一输入。原来文件名是 `日期_判例名_反馈.json`，
    而"劳动合同"是最常见的那种名字 —— 实测两条只剩一条。"""
    客 = _客户端()
    assert _交(客, "劳动合同", "甲的意见").status_code == 200
    assert _交(客, "劳动合同", "乙的意见").status_code == 200
    全 = 客.get("/my-feedback").get_json()["反馈"]
    assert len(全) == 2, 全
    assert {x["备注"] for x in 全} == {"甲的意见", "乙的意见"}, 全


def test_反馈字段乱传不该500():
    客 = _客户端()
    回 = 客.post("/feedback", json={"case_name": {"a": 1}, "helpfulness": "very",
                                    "comment": ["不是字符串"], "most_valuable": "不是列表",
                                    "issue_types": None, "date": "昨天"})
    assert 回.status_code == 200, 回.get_json()
    条 = 客.get("/my-feedback").get_json()["反馈"][-1]
    assert 条["判例名"] == "未命名", 条
    assert 条["备注"] == "", 条
    assert 条["最有价值模块"] == [], 条
    assert 条["分析日期"] == str(datetime.date.today()), 条


def test_反馈缺必填要出声而且不入库():
    客 = _客户端()
    回 = 客.post("/feedback", json={"case_name": "x", "helpfulness": "也许"})
    assert 回.status_code == 400, 回.get_json()
    assert 客.get("/my-feedback").get_json()["总数"] == 0


def test_我的反馈只看得到自己的():
    甲, 乙 = _客户端(), _客户端()
    _交(甲, "甲的合同", "甲的意见")
    _交(乙, "乙的合同", "乙的意见")
    看甲 = 甲.get("/my-feedback").get_json()
    assert 看甲["总数"] == 1, 看甲
    assert 看甲["反馈"][0]["判例名"] == "甲的合同", 看甲
    assert 乙.get("/my-feedback").get_json()["反馈"][0]["判例名"] == "乙的合同"


# ── 逐条反馈 ──

def _点(客, 维度="风险清单", 评价="helpful", 标记="点赞用例", **extra):
    体 = {"dimension": 维度, "rating": 评价, "report": f"2026-09-20_{标记}.json",
           "case_name": 标记, "等级": "中", "覆盖度": 0.84}
    体.update(extra)
    return 客.post("/rate", json=体)


def test_逐条点赞落到看板上():
    """点两下比"你觉得哪个模块最没用"准得多 —— 但前提是它真能被汇总出来。"""
    客 = _客户端()
    前 = len(_收集("点赞用例"))
    assert _点(客, "风险清单", "helpful").status_code == 200
    assert _点(客, "风险清单", "unclear").status_code == 200
    assert _点(客, "谈判顺序", "unclear").status_code == 200
    assert len(_收集("点赞用例")) == 前 + 3
    统 = _逐条(客, "点赞用例")
    assert 统["风险清单"] == {"有用": 1, "没看懂": 1, "看不懂率": 0.5}, 统
    assert 统["谈判顺序"]["没看懂"] == 1, 统
    assert list(统)[0] == "风险清单", "按点数排序，最该看的排前面"


def test_逐条反馈认不出的一律不收():
    客 = _客户端()
    前 = len(_收集("拒收用例"))
    assert _点(客, 维度="不存在的模块", 标记="拒收用例").status_code == 400
    assert _点(客, 评价="还行", 标记="拒收用例").status_code == 400
    assert len(_收集("拒收用例")) == 前, "被拒的评价还是落盘了"


def test_逐条反馈带得上下的核验读数():
    """只存"点了什么"就浪费了：连等级/覆盖度一起存，才能回答
    "覆盖度低的报告是不是更让人觉得没用" —— 那是决定要不要继续投入的证据。"""
    客 = _客户端()
    _点(客, 维度="改法建议", 标记="读数用例", 覆盖度=0.42, 等级="低")
    记 = _收集("读数用例")
    assert 记[0]["覆盖度"] == 0.42 and 记[0]["等级"] == "低", 记
    assert 记[0]["报告"] == "2026-09-20_读数用例.json", 记


def _逐条(客, 标记):
    """看板数的是所有用户，所以先按标记把这一维的计数从汇总里对出来。"""
    板 = json.loads(客.get("/dashboard").get_data())["逐条评价"]
    return 板


def _收集(标记):
    """按标记捞自己那几条 —— ratings 目录是**所有用户共用**的临时盘，
    直接 glob 会把别的用例卷进来（第一版就这么假失败过）。"""
    出 = []
    for f in sorted(glob.glob(os.path.join(app_mod.数据根目录, "*", "ratings", "*.json"))):
        d = json.load(open(f, encoding='utf-8'))
        if d.get("判例名") == 标记:
            出.append(d)
    return 出


def test_逐条反馈字段乱传不该500():
    客 = _客户端()
    回 = 客.post("/rate", json={"dimension": "风险清单", "rating": "helpful",
                                "case_name": "乱传用例", "report": {"不是": "字符串"},
                                "覆盖度": "0.8", "等级": None})
    assert 回.status_code == 200, 回.get_data()
    记 = _收集("乱传用例")[-1]
    assert 记["报告"] == "" and 记["覆盖度"] is None and 记["等级"] == "", 记


# ── 管理口 ──

def _远程():
    客 = app_mod.app.test_client()
    return 客, {"REMOTE_ADDR": "203.0.113.7"}


def test_看板与反馈汇总对陌生人关门():
    客, 环境 = _远程()
    原 = app_mod.管理口令
    app_mod.管理口令 = "s3cret"
    try:
        for 路 in ("/dashboard", "/feedback-data"):
            assert 客.get(路, environ_base=环境).status_code == 403, f"{路} 没把门"
            assert 客.get(路 + "?token=错", environ_base=环境).status_code == 403, f"{路} 口令没验"
            回 = 客.get(路 + "?token=s3cret", environ_base=环境)
            assert 回.status_code == 200, (路, 回.status_code)
    finally:
        app_mod.管理口令 = 原


def test_没设口令时远程一律关本机放行():
    客, 环境 = _远程()
    原 = app_mod.管理口令
    app_mod.管理口令 = ""
    try:
        assert 客.get("/dashboard", environ_base=环境).status_code == 403
        assert 客.get("/dashboard?token=猜一个", environ_base=环境).status_code == 403
        assert 客.get("/dashboard").status_code == 200        # test client 的对端是 127.0.0.1
    finally:
        app_mod.管理口令 = 原


def test_看板按模式点名而不是把合同算成判决书():
    """原来只有两个桶，第二个是 else：每一份合同报告都被计进"判决书分析"。"""
    前 = json.loads(_客户端().get("/dashboard").get_data())      # 别的测试也往同一个临时目录里写过
    客, _ = _分析一次("看板计数")
    板 = json.loads(客.get("/dashboard").get_data())
    assert 板["分模式"]["合同审查"] - 前["分模式"]["合同审查"] == 1, (前, 板)
    assert 板["分模式"]["判决书分析"] == 前["分模式"]["判决书分析"], \
        f"合同分析被算进了『判决书分析』这一桶：{板['分模式']}"
    assert 板["分析总数"] - 前["分析总数"] == 1, (前, 板)


# ── 下载件 ──

def test_下载件带着核验读数和免责():
    客, 数 = _分析一次("要下载的")
    体 = {"判例名": "要下载的", **数["分析"],
          "法条统计": 数["验证"]["法条统计"], "法条对照": 数["法条对照"], "溯源": 数["溯源"],
          "核验读数": 数["可信度"]["核验"], "覆盖度": 数["可信度"]["覆盖度"],
          "等级": 数["可信度"]["等级"],
          "待核实": [x["内容"] for x in 数["风险列表"] if x["等级"] != "note"],
          "工具边界": [x["内容"] for x in 数["风险列表"] if x["等级"] == "note"]}
    报 = 客.post("/download", json=体).get_data().decode("utf-8")
    assert "这份报告核对到什么程度" in 报, 报[:400]
    assert "逐条核到原文" in 报 and "没法核" in 报, 报
    assert "请带原件找执业律师核实" in 报, 报
    assert "哪些条款对你不利" in 报, "分节标题还是内部键名，普通人看不懂这份要转给别人看的东西"
    assert "风险清单" not in 报.replace("风险清单：", ""), 报[-500:]


def test_下载件字段缺一项不该500():
    """历史里存的老报告没有 溯源/法条对照（是 null），下载走的却是同一个口子。"""
    客 = _客户端()
    回 = 客.post("/download", json={"判例名": "残缺", "总结": "一段结论" * 20,
                                    "法条对照": None, "溯源": None})
    assert 回.status_code == 200, 回.get_data()[:200]
    assert "残缺" in 回.get_data().decode("utf-8")
    assert 客.post("/download", data="不是 JSON", content_type="text/plain").status_code == 400


# ── 响应头 ──

def test_不再对所有网站开放接口():
    客 = _客户端()
    for 路 in ("/", "/remaining"):
        头 = 客.get(路).headers
        assert 头.get("Access-Control-Allow-Origin") != "*", 路
        assert "Access-Control-Allow-Origin" not in 头, f"{路} 还在发 CORS 头：{头.get('Access-Control-Allow-Origin')}"


if __name__ == "__main__":
    测试们 = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for 名, t in 测试们:
        t()
        print(f"  ✓ {名}")
    print(f"\n{len(测试们)} 个测试全通过")
