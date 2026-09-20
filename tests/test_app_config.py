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
    """扣次数是有副作用的一步。"正文太短 / 不像判决书 / 请求体不是 JSON"都是一句话
    就能改对的失败，原来它们排在 消耗次数 之后 —— 试错的成本被算成用户的一天一次。

    ⚠️ 探针用**陌生 IP + 上限 1**，靠"有没有落计数文件"来判断走没走到那一步。
    以前这里用 每日上限=0，而 0 现在的含义是"不限次"，那个探针就失效了 ——
    换成状态码也一样不行：坏请求无论顺序对错都返回 400，看不出区别。
    """
    目录 = tempfile.mkdtemp(prefix="判例助手-配额-")
    原目录, 原上限 = app_mod.数据根目录, app_mod.每日上限
    app_mod.数据根目录 = 目录
    app_mod.每日上限 = 1
    app_mod.app.config["TESTING"] = True
    还原 = _装桩模型()
    客 = app_mod.app.test_client()
    远端 = "203.0.113.20"
    try:
        for 参 in [{"json": {"text": "太短了", "mode": "judgment"}},
                   {"json": {"text": "双方经友好协商达成如下合作意向。" * 12, "mode": "judgment"}},
                   {"data": "这根本不是一份 JSON", "content_type": "text/plain"}]:
            回 = 客.post("/analyze", environ_base={"REMOTE_ADDR": 远端}, **参)
            assert 回.status_code == 400, (参, 回.status_code)
        assert not _计数文件(目录), f"被拒绝的请求留下了计数痕迹：{_计数文件(目录)}"

        好 = 客.post("/analyze", json={"text": 正文, "mode": "judgment"},
                     environ_base={"REMOTE_ADDR": 远端})
        assert 好.status_code == 200, 好.get_json()
        assert _计数文件(目录), "合法请求该落计数文件（否则上面那条断言是在测空气）"
        第二次 = 客.post("/analyze", json={"text": 正文, "mode": "judgment"},
                         environ_base={"REMOTE_ADDR": 远端})
        assert 第二次.status_code == 429, 第二次.get_json()
    finally:
        还原()
        app_mod.数据根目录 = 原目录
        app_mod.每日上限 = 原上限
        shutil.rmtree(目录, ignore_errors=True)


def _装桩模型():
    """把各技能模块里的 问AI 换成假回答 —— 这些用例测的是限流，不该真打 API。

    ⚠️ 必须记下原值并在用例结束时还原：`skills.legal._base` 自己也在遍历范围内，
    不还原的话 `test_base_error_paths` 那几条测的就是我的桩而不是真 问AI 了。
    """
    from skills import legal
    原 = []

    def 假问AI(提示词, 判例文字, api_key, 附段落编号=True):
        return "依据《中华人民共和国民法典》第1165条，行为人因过错侵害他人民事权益造成损害的，应当承担侵权责任。"

    for 名 in dir(legal):
        模 = getattr(legal, 名)
        if hasattr(模, "问AI"):
            原.append((模, 模.问AI))
            模.问AI = 假问AI

    def 还原():
        for 模, 旧 in 原:
            模.问AI = 旧
    return 还原


正文 = "原告段某诉被告杨某生命权纠纷一案，法院审理认为，劝阻吸烟属正当行为。" * 3


def _计数文件(目录):
    """只看限流那几个文件。数据目录里本来就会有 per-uid 的报告目录和
    session_secret.key，拿"目录空不空"当断言会把这些正常产物也算成违规。"""
    return sorted(f for f in os.listdir(目录) if f.startswith("limit_"))


def _打一次(客, 远端="127.0.0.1", 头=None):
    env = {"REMOTE_ADDR": 远端}
    for k, v in (头 or {}).items():
        env["HTTP_" + k.upper().replace("-", "_")] = v
    return 客.post("/analyze", json={"text": 正文, "mode": "judgment"}, environ_base=env)


def test_本机访问不受每日上限管():
    """限流是给陌生访客准备的。作者自己在 127.0.0.1 上改一次提示词试一次，
    不该被"20 次/天"挡住 —— 今天就是这么被挡住了一次（配额烧到 0/20）。"""
    目录 = tempfile.mkdtemp(prefix="判例助手-限流-")
    原目录, 原上限 = app_mod.数据根目录, app_mod.每日上限
    app_mod.数据根目录 = 目录
    app_mod.每日上限 = 2
    app_mod.app.config["TESTING"] = True
    还原 = _装桩模型()
    客 = app_mod.app.test_client()
    try:
        for 次 in range(1, 5):
            assert _打一次(客).status_code == 200, f"本机第 {次} 次被限流了"
        assert 客.get("/remaining").get_json()["上限"] is None, "本机该报不限次"
        assert not _计数文件(目录), f"本机不该写限流计数，却写了：{_计数文件(目录)}"
    finally:
        还原()
        app_mod.数据根目录 = 原目录
        app_mod.每日上限 = 原上限
        shutil.rmtree(目录, ignore_errors=True)


def test_陌生IP仍然按上限拦():
    目录 = tempfile.mkdtemp(prefix="判例助手-限流-")
    原目录, 原上限 = app_mod.数据根目录, app_mod.每日上限
    app_mod.数据根目录 = 目录
    app_mod.每日上限 = 2
    app_mod.app.config["TESTING"] = True
    还原 = _装桩模型()
    客 = app_mod.app.test_client()
    try:
        assert _打一次(客, "203.0.113.7").status_code == 200
        assert _打一次(客, "203.0.113.7").status_code == 200
        回 = _打一次(客, "203.0.113.7")
        assert 回.status_code == 429, 回.get_json()
        assert _计数文件(目录), "陌生 IP 该留下计数文件"
    finally:
        还原()
        app_mod.数据根目录 = 原目录
        app_mod.每日上限 = 原上限
        shutil.rmtree(目录, ignore_errors=True)


def test_换一个转发头刷不出配额():
    """X-Forwarded-For 是客户端自己写的。原来 获取客户端IP 无条件优先取它 ——
    每次请求换一个值，桶就换一个，上限等于没有。

    ⚠️ 每发一次就换一个**新 client**：限流是 uid / IP 双轨取 max，而 test_client
    会带 session cookie —— 复用同一个 client 时 uid 那条轨就会先把请求拦下，
    IP 轨有没有被绕过根本测不到（第一版就是这么"通过"的）。
    """
    目录 = tempfile.mkdtemp(prefix="判例助手-限流-")
    原目录, 原上限 = app_mod.数据根目录, app_mod.每日上限
    app_mod.数据根目录 = 目录
    app_mod.每日上限 = 2
    app_mod.app.config["TESTING"] = True
    还原 = _装桩模型()
    try:
        状态 = [_打一次(app_mod.app.test_client(), "198.51.100.9",
                        {"X-Forwarded-For": f"10.0.0.{次}"}).status_code
                for 次 in range(1, 4)]
        assert 状态 == [200, 200, 429], f"换 XFF 就绕过了上限：{状态}"
    finally:
        还原()
        app_mod.数据根目录 = 原目录
        app_mod.每日上限 = 原上限
        shutil.rmtree(目录, ignore_errors=True)


def test_远程请求冒充本机拿不到豁免():
    """豁免只看 socket 对端。要是它去看 X-Forwarded-For，
    外面一个 `X-Forwarded-For: 127.0.0.1` 就能把整套上限绕干净。"""
    目录 = tempfile.mkdtemp(prefix="判例助手-限流-")
    原目录, 原上限 = app_mod.数据根目录, app_mod.每日上限
    app_mod.数据根目录 = 目录
    app_mod.每日上限 = 1
    app_mod.app.config["TESTING"] = True
    还原 = _装桩模型()
    客 = app_mod.app.test_client()
    try:
        assert _打一次(客, "192.0.2.5", {"X-Forwarded-For": "127.0.0.1"}).status_code == 200
        回 = _打一次(客, "192.0.2.5", {"X-Forwarded-For": "127.0.0.1"})
        assert 回.status_code == 429, "远程地址伪装 127.0.0.1 拿到了本机豁免"
    finally:
        还原()
        app_mod.数据根目录 = 原目录
        app_mod.每日上限 = 原上限
        shutil.rmtree(目录, ignore_errors=True)


if __name__ == "__main__":
    测试们 = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for 名, t in 测试们:
        t()
        print(f"  ✓ {名}")
    print(f"\n{len(测试们)} 个测试全通过")
