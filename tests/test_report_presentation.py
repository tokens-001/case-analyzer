"""页面结构与前两份"叫法表"的回归。

为什么这些断言放得住：它们查的都是**会自己骗自己**的那类错 ——
一个 id 出现两次，`getElementById` 只会拿到第一个，第二份节点就变成永远不被更新的
死标记（而它恰好是那条"✅ 验证通过"的色块，一进页面就在）；
多一个 `</div>` 会把 `.main` 提前收掉，历史区落到居中栏外面；
卡片标题换成了人话、反馈问卷却还在问内部键名，等于人话化只做了一半。
这些都是读一遍就能发现、但没有任何一只测试会红的东西。

跑法：python3 -m pytest tests/ -q
"""
import os
import re
import sys
from html.parser import HTMLParser

os.environ.setdefault("DATA_DIR", "/tmp/判例助手-展示层测试-不会写盘")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))

页面路径 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "python", "templates", "index.html")
页面 = open(页面路径, encoding='utf-8').read()


class _计(HTMLParser):
    """数 id、跟嵌套，顺手记下「某个元素在不在某个元素里面」。"""

    def __init__(s):
        super().__init__()
        s.ids, s.stack, s.stray, s.包含 = {}, [], [], {}
        s.空标签 = ('br', 'input', 'meta', 'img', 'hr', 'link')

    def _祖先(s):
        # 栈里存的是 (标签, id, class)，id 和 class 都算"是谁"
        return {i for _, i, _ in s.stack if i} | {c for _, _, c in s.stack if c}

    def handle_starttag(s, tag, attrs):
        d = dict(attrs)
        if 'id' in d:
            s.ids[d['id']] = s.ids.get(d['id'], 0) + 1
        if tag in s.空标签:
            return
        # 先记录再入栈：判的是"它被谁包着"
        if d.get('id') == 'feedback-section':
            s.包含['反馈区在结果区内'] = 'results' in s._祖先()
        if 'history-section' in (d.get('class') or ''):
            s.包含['历史区在主栏内'] = any('main' in c for _, _, c in s.stack)
        s.stack.append((tag, d.get('id'), d.get('class') or ''))

    def handle_endtag(s, tag):
        顶层 = s.stack[-1][0] if s.stack else None
        if 顶层 == tag:
            s.stack.pop()
        elif not s.stack:
            s.stray.append(tag)


def _解析():
    p = _计()
    p.feed(页面)
    return p


def test_页面里没有重复的id():
    p = _解析()
    重 = {k: v for k, v in p.ids.items() if v > 1}
    assert not 重, f"重复 id：{重} —— getElementById 只认第一个，多出来的那份永远不会被更新"


def test_标签闭合平衡():
    p = _解析()
    assert not p.stray, f"多余的闭合标签：{p.stray}"
    残留 = [t for t, _, _ in p.stack if t not in ('html', 'body')]
    assert not 残留, f"没闭合的标签：{残留}"


def test_历史区在主栏内_反馈区在结果区内():
    p = _解析()
    assert p.包含.get('历史区在主栏内'), "历史区落在 .main 之外 —— 宽屏时它顶到窗口两边"
    assert p.包含.get('反馈区在结果区内'), "反馈区不在 #results 里 —— 点「清空」结果没了、问卷还留着"


def test_不再有_9999_那种魔数判断():
    代码行 = [行 for 行 in 页面.splitlines()
             if '9999' in 行 and not 行.strip().startswith(('//', '*', '/*'))]
    assert not 代码行, f"还在拿 9999 当『不限』用：{代码行} —— 后端早就改成 null 了"


def _innerHTML_语句():
    """把 script 里每一条 `X.innerHTML = ...` 赋值整段抠出来（赋值可能跨几行）。

    收行规则只认一个终止符：**行尾的 `;`**。曾经还顺带认 `}`，结果把
    `格.innerHTML = ""; return 节; }` 后面整个 forEach 都收了进来，
    测试开始因为不相干的地方红 —— 一根会误报的绳子不如没有。
    """
    行们 = 页面.splitlines()
    语句, 当前, 收集中 = [], [], False
    for 行 in 行们:
        if not 收集中 and '.innerHTML' not in 行:
            continue
        if not 收集中:
            收集中 = True
            当前 = [行]
        else:
            当前.append(行)
        if 行.rstrip().endswith(';'):
            语句.append("\n".join(当前))
            当前, 收集中 = [], False
    return [s for s in 语句 if 'innerHTML' in s]


def test_每条innerHTML里的数据都必须先过转义():
    """规则只有一条：走 innerHTML 的地方，每个 `${}` 都得直接写 转义(...)。
    （只有 `innerHTML = ""` 这种清空例外 —— 它没有插值。）
    """
    for 语句 in _innerHTML_语句():
        for 插值 in re.findall(r'\$\{[^{}]*\}', 语句):
            assert '转义(' in 插值, \
                f"innerHTML 那行里有个没转义的插值：{插值} —— 换成本地别名再调 转义 也算违规，" \
                f"这条规则要一眼看得出来"


def test_模型输出不再被拼进可执行的字符串():
    """历史上每一条都是真存在过的注入点：拿 .map 拼一段 HTML 再塞进 innerHTML，
    被拼进去的都是模型输出或用户自己上传的文件名。
    （`${文本}` 走 textContent/元素() 是允许的，所以这里不查插值本身，只查"拼 HTML"。）
    """
    for 危险 in ('.innerHTML = data.', 'innerHTML = trace.items.map', 'innerHTML = items.map',
               '.innerHTML = `', 'onclick="加载历史详情(', 'chipHTML', 'value="${'):
        assert 危险 not in 页面, f"这条又把外部数据拼进了 HTML/JS：{危险}"
    assert 'function 转义' in 页面 and 'function 元素' in 页面, "转义/建节点的工具被删了"


def test_两份叫法表覆盖同一批键():
    """app.py 的 人话标题 负责下载件，index.html 的那份负责屏幕。

    两份分开写就一定会漂 —— 漂了的现场是"屏幕说『哪些条款对你不利』、
    下载下来的 txt 写着『风险清单』"。这条测试就是那根把两边拴在一起的绳子。
    """
    import app as app_mod
    js表 = re.search(r'const 人话标题 = \{(.*?)\n\s*\};', 页面, re.S)
    assert js表, "index.html 里那份 人话标题 找不到了"
    js = dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', js表.group(1)))
    后 = app_mod.人话标题
    assert set(js) == set(后), f"两份表覆盖的键不一样：只有前端有 {set(js) - set(后)}；只有后端有 {set(后) - set(js)}"
    assert {k: js[k] for k in 后 if js[k] != 后[k]} == {}, \
        f"同一个键两边叫法不同：{ {k: (后[k], js[k]) for k in 后 if js.get(k) != 后[k]} }"


def test_三种模式的每个维度都有人话叫法():
    """没起名字的键会被原样当卡片标题渲染出来（`合同类型` 曾经就是这么冒出来的）。"""
    import app as app_mod
    全 = set(app_mod.人话标题)
    模式键 = {
        "contract": {"风险清单", "缺失条款", "失衡条款", "歧义表述", "改法建议", "谈判顺序", "总结"},
        "case": {"法律关系", "事实与证据", "对抗路径", "风险推演", "行动建议", "总结"},
        "judgment": {"结构化摘要", "核心争议", "推理链路", "法条适用精析",
                     "对立解释路径", "论证完整性检查", "程序问题识别", "未回答问题"},
    }
    for 模式, 键 in 模式键.items():
        assert not (键 - 全), f"{模式} 模式有维度没起人话名字：{键 - 全}"


def test_反馈问卷不再拿必填拦住想给好评的人():
    assert 'id="q-keep"' not in 页面, "「只能保留3个模块」那题又回来了"
    assert 页面.count('请至少选一个') == 0, "还有把多选设成必填的提示"


if __name__ == "__main__":
    测试们 = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for 名, t in 测试们:
        t()
        print(f"  ✓ {名}")
    print(f"\n{len(测试们)} 个测试全通过")
