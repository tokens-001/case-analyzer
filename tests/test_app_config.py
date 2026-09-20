"""服务端配置的两条回归：会话密钥要稳定、key 只能取 DeepSeek 那份。

跑法：python3 -m pytest tests/ -q
"""
import importlib
import os
import shutil
import sys
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="判例助手-测试数据-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))

import app as app_mod        # noqa: E402


def _隔离密钥目录():
    目录 = tempfile.mkdtemp(prefix="判例助手-密钥-")
    原 = app_mod.数据根目录
    app_mod.数据根目录 = 目录
    return 目录, 原


def test_会话密钥落盘复用而不是每次随机():
    """uid 存在签了名的 session 里，而 uid **就是用户数据目录名** ——
    密钥每次随机等于每次重启都把别人的历史和报告锁在门外。"""
    目录, 原 = _隔离密钥目录()
    原env = os.environ.pop("FLASK_SECRET_KEY", None)
    try:
        第一 = app_mod._会话密钥()
        assert 第一 and 第一 == app_mod._会话密钥(), "同一个数据目录该拿到同一份密钥"
        路径 = os.path.join(目录, "session_secret.key")
        assert os.path.exists(路径), "密钥没落盘，下次重启还是随机的"
        assert (os.stat(路径).st_mode & 0o777) == 0o600, "密钥文件权限过宽"
    finally:
        app_mod.数据根目录 = 原
        shutil.rmtree(目录, ignore_errors=True)
        if 原env is not None:
            os.environ["FLASK_SECRET_KEY"] = 原env


def test_没给环境变量时密钥落盘并且重启后还是同一份():
    """⚠️ 这条测的是**接线**，不是 `_会话密钥()` 这个函数 —— 前面几条把目录一换、
    直接调函数，把 `app.secret_key = _会话密钥()` 改回 `os.urandom(...)` 一条都不会红
    （而且 conftest 原先还 setdefault 了一个 FLASK_SECRET_KEY，让 env 分支把整条路径
    短路掉）。这里用"重新导入一次 app 模块"当真·重启：两次拿到的必须是同一份。"""
    目录 = tempfile.mkdtemp(prefix="判例助手-重启-")
    原env, 原DATA = os.environ.pop("FLASK_SECRET_KEY", None), os.environ.get("DATA_DIR")
    原模块 = sys.modules.pop("app", None)
    try:
        os.environ["DATA_DIR"] = 目录
        第一 = importlib.import_module("app").app.secret_key
        sys.modules.pop("app", None)
        第二 = importlib.import_module("app").app.secret_key
        assert 第一 and 第一 == 第二, "重启一次就不是同一份密钥 —— session 会全体作废"
        assert os.path.exists(os.path.join(目录, "session_secret.key")), "密钥没落盘"
    finally:
        sys.modules.pop("app", None)
        if 原模块 is not None:
            sys.modules["app"] = 原模块
        os.environ["DATA_DIR"] = 原DATA or ""
        if 原env is not None:
            os.environ["FLASK_SECRET_KEY"] = 原env
        shutil.rmtree(目录, ignore_errors=True)


def test_环境变量指定的密钥优先():
    目录, 原 = _隔离密钥目录()
    原env = os.environ.get("FLASK_SECRET_KEY")
    try:
        os.environ["FLASK_SECRET_KEY"] = "写死的密钥"
        assert app_mod._会话密钥() == "写死的密钥"
        assert not os.path.exists(os.path.join(目录, "session_secret.key")), "有 env 就不该落盘"
    finally:
        app_mod.数据根目录 = 原
        shutil.rmtree(目录, ignore_errors=True)
        if 原env is None:
            os.environ.pop("FLASK_SECRET_KEY", None)
        else:
            os.environ["FLASK_SECRET_KEY"] = 原env


def test_只配了anthropic的token时不再往下走():
    """`_base.问AI` 打的是 api.deepseek.com，Anthropic 的 token 发过去必然 401，
    而报错会把人引到"我明明配了 key"上。现在直接说缺哪个变量。"""
    原深, 原安 = os.environ.pop("DEEPSEEK_API_KEY", None), os.environ.get("ANTHROPIC_AUTH_TOKEN")
    os.environ["ANTHROPIC_AUTH_TOKEN"] = "sk-ant-测试用不联网"
    try:
        app_mod.app.config["TESTING"] = True
        回 = app_mod.app.test_client().post("/analyze", json={
            "text": "原告诉被告借款合同纠纷，法院审理认为……" * 4, "mode": "judgment"})
        assert 回.status_code == 500, 回.status_code
        assert "DEEPSEEK_API_KEY" in 回.get_json()["error"], 回.get_json()
    finally:
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        if 原安:
            os.environ["ANTHROPIC_AUTH_TOKEN"] = 原安
        if 原深:
            os.environ["DEEPSEEK_API_KEY"] = 原深


def test_被拒绝的请求不许扣配额():
    """扣次数是有副作用的一步。原来"正文太短/不像判决书/请求体不是 JSON"这些
    一句就能改对的失败，都排在 消耗次数 之后 —— 试错的成本被算成用户的一天一次。

    ⚠️ 这条用例故意把 每日上限 设成 0 当探针：如果顺序又被人换回去，
    坏请求会先撞上 429 而不是 400 —— 那样这条测试就只是在测"返回了个错"，
    换不回来看不出区别。现在两种失败码是分开的，顺序一错就红。
    """
    目录 = tempfile.mkdtemp(prefix="判例助手-配额-")
    原目录, 原上限 = app_mod.数据根目录, app_mod.每日上限
    原key = os.environ.get("DEEPSEEK_API_KEY")
    os.environ["DEEPSEEK_API_KEY"] = "sk-测试用不联网"
    app_mod.数据根目录 = 目录
    app_mod.每日上限 = 0                    # 一被调用就必然不够 → 用状态码区分"有没有走到这一步"
    app_mod.app.config["TESTING"] = True
    客 = app_mod.app.test_client()
    try:
        坏请求 = [
            {"json": {"text": "太短了", "mode": "judgment"}},                       # 正文不足 50 字
            {"json": {"text": "双方经友好协商达成如下合作意向。" * 12, "mode": "judgment"}},  # 不像判决书
            {"data": "这根本不是一份 JSON", "content_type": "text/plain"},            # 请求体形状错
        ]
        for 参 in 坏请求:
            回 = 客.post("/analyze", **参)
            assert 回.status_code == 400, (参, 回.status_code, 回.get_json())
        assert not os.listdir(目录), f"被拒绝的请求留下了计数痕迹：{os.listdir(目录)}"

        好 = 客.post("/analyze", json={"text": "原告诉被告借款合同纠纷一案，法院审理认为。" * 10,
                                       "mode": "judgment"})
        assert 好.status_code == 429, 好.get_json()      # 走到限流了 —— 上面三条根本没走到
    finally:
        app_mod.数据根目录 = 原目录
        app_mod.每日上限 = 原上限
        if 原key is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = 原key
        shutil.rmtree(目录, ignore_errors=True)


if __name__ == "__main__":
    测试们 = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for 名, t in 测试们:
        t()
        print(f"  ✓ {名}")
    print(f"\n{len(测试们)} 个测试全通过")
