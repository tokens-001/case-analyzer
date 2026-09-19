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


if __name__ == "__main__":
    测试们 = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for 名, t in 测试们:
        t()
        print(f"  ✓ {名}")
    print(f"\n{len(测试们)} 个测试全通过")
