"""锁住 API 失败路径：`问AI` 在出错时必须返回**能解析的 JSON 错误体**。

起因：`_base.py` 里 4 处 `json.dumps(...)` 全在异常分支上，而模块**没有 import json**
⇒ 一超时/断网/返回异常，本应给出的结构化错误自己先抛 `NameError`。
这类"错误路径才是最先炸的地方"只有走一次失败才会暴露，所以直接拿假 requests 走一遍。

跑法：python3 -m pytest tests/ -q   或   python3 tests/test_base_error_paths.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))

from skills.legal import _base  # noqa: E402


class _假requests:
    """只装 `问AI` 会碰到的那几个异常类型，post 一律抛。"""

    class exceptions:
        class Timeout(Exception):
            pass

        class ConnectionError(Exception):
            pass

    @staticmethod
    def post(**kwargs):
        raise _假requests.exceptions.Timeout("connect timed out")


def _跑一次(异常类):
    真requests = _base.requests
    _base.requests = _假requests
    try:
        _假requests.post = lambda **kw: (_ for _ in ()).throw(异常类("boom"))
        return _base.问AI("提示", "判例正文", "sk-假key")
    finally:
        _base.requests = 真requests


def test_超时返回可解析的JSON错误体():
    出 = _跑一次(_假requests.exceptions.Timeout)
    解析 = json.loads(出)          # NameError 会在这一步之前炸；解析失败也会炸
    assert 解析["error"] is True and 解析["type"] == "timeout", 出


def test_断网返回可解析的JSON错误体():
    解析 = json.loads(_跑一次(_假requests.exceptions.ConnectionError))
    assert 解析["type"] == "network", 解析


def test_其他异常也归到unknown而不是抛出():
    解析 = json.loads(_跑一次(RuntimeError))
    assert 解析["type"] == "unknown" and "boom" in 解析["detail"], 解析


# ───────────── 错误体不许当分析正文往下走 ─────────────

from skills.legal.score_analysis import validate_analysis_quality          # noqa: E402
from skills.legal.verify_laws import count_law_citations                    # noqa: E402


def test_API错误体不会被当成分析正文():
    """问AI 失败时 return 的是错误 JSON（except 里没有 raise），一行就有几十字，
    所以**字数检查天生拦不住它** —— 必须认形状。"""
    出 = _跑一次(_假requests.exceptions.Timeout)
    验证 = validate_analysis_quality(出, 出, 出, 出, 出 + "补足到五十字以上" * 4,
                                    count_law_citations)
    assert 验证["通过"] is False
    # 第 5 段（总结）也以错误体开头，所以五条都该被认出来
    assert sum(1 for q in 验证["问题"] if "API 失败产物" in q) == 5, 验证["问题"]


def test_future兜底失败标记也被认出():
    文 = "【法律关系失败】connection reset by peer"
    验证 = validate_analysis_quality(文, 文, 文, 文, 文 + "凑够五十字" * 8, count_law_citations)
    assert all("API 失败产物" in q for q in 验证["问题"][:4]), 验证["问题"]


def test_段落名由调用方给不再写死一套():
    """旧代码把名字写死成"核心争议/推理链路/未回答/可平移性"，而两种模式都不产出
    "可平移性" —— 报出来的名字和实际内容不符，人照着核对就会对错段落。"""
    文 = "【风险推演失败】boom"
    验证 = validate_analysis_quality(文, 文, 文, 文, 文 + "凑够五十字" * 8,
                                     count_law_citations, 段落名=["甲", "乙", "丙", "丁", "总结"])
    assert any("甲 是 API 失败产物" in q for q in 验证["问题"]), 验证["问题"]
    assert not any("可平移性" in q for q in 验证["问题"]), 验证["问题"]


def test_总结的字数下限仍是五十字():
    正常 = "这是一段足够长度的分析内容。" * 3
    assert validate_analysis_quality(正常, 正常, 正常, 正常, 正常,
                                     count_law_citations)["通过"] is False   # 没引用法条
    短总结 = 正常[:30]
    验证 = validate_analysis_quality(正常, 正常, 正常, 正常, 短总结, count_law_citations)
    assert any("总结字数过少" in q for q in 验证["问题"]), 验证["问题"]


if __name__ == "__main__":
    测试们 = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for 名, t in 测试们:
        t()
        print(f"  ✓ {名}")
    print(f"\n{len(测试们)} 个测试全通过")
