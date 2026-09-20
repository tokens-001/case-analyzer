"""跑一次真模型，只打印**校验读数** —— 提示词改完到底有没有用，看这个。

为什么只比数字不比文字：模型换个说法不是回归。把"输出变了"当红灯，只会让人
学会忽略红灯 —— 而这套东西唯一有用的输出就是那些红灯。所以要看的量是
「无条号引用从 30 处降到几处」「覆盖度从 43% 升到多少」这种能跨次比较的数。

跑法：
    cd python && DEEPSEEK_API_KEY=sk-… python3 ../scripts/smoke_model.py
    … --存基线     把这次的读数写到 data/smoke_baseline.json（跟踪进仓库，能对比）
    … --桩         不调 API、不占配额，只验这个脚本自己的读数和打印通不通

⚠️ 一次运行 = 6~8 个并行 DeepSeek 调用，**占掉当日 1 次配额**，而且限流按 IP 归并 ——
   和你在浏览器里点"开始分析"是同一个桶。所以它故意不进 CI：CI 里放 key
   等于把花费和秘密挂到每次 push 上，而且模型输出不稳定会让门变成随机红。
"""
import json
import os
import sys
import tempfile

根目录 = os.path.dirname(os.path.abspath(__file__)).rsplit("/scripts", 1)[0]
sys.path.insert(0, os.path.join(根目录, "python"))

输入 = os.path.join(根目录, "data", "case_input", "好意规劝不担责案.txt")
基线 = os.path.join(根目录, "data", "smoke_baseline.json")


def _装桩():
    """把每个技能模块里的 问AI 换成假回答：只用来验脚本，不碰网络、不占配额。"""
    from skills import legal
    答 = ("依据《中华人民共和国民法典》第1165条，行为人因过错侵害他人民事权益造成损害的，应当承担侵权责任。"
           "【第一条】「段某在电梯内吸烟，邻居杨某劝阻」 风险：示例\n")

    def 假问AI(提示词, 判例文字, api_key, 附段落编号=True):
        return 答

    数 = 0
    for 名 in dir(legal):
        模 = getattr(legal, 名)
        if hasattr(模, "问AI"):
            模.问AI = 假问AI
            数 += 1
    return 数


def _读数(数):
    法 = 数.get("法条校验") or {}
    条 = 数.get("条款校验") or {}
    信 = 数.get("可信度") or {}
    出 = {
        # ⚠️ `可验证` 不在 法条校验 里 —— app 把它单独放在响应的 `法条对照` 键上
        #   （同一份数据塞两遍没意义）。从 法条校验 数它会永远得 0，
        #   于是这份"读数"最左边那一栏在真跑时也是假的。
        "可验证": len(数.get("法条对照") or 法.get("可验证") or []),
        "疑似编造": len(法.get("疑似编造", [])),
        "库外": 法.get("覆盖不足数", 0),
        "无条号引用": len(法.get("无条号引用", [])),
        "未识别": len(法.get("未识别", [])),
        "条款可定位": len(条.get("可验证", [])),
        "条款对不上": len(条.get("疑似编造", [])),
        "未校验数": 信.get("未校验数", 0),
        "等级": 信.get("等级"),
        "覆盖度": 信.get("覆盖度"),
        "核到": (信.get("核验") or {}).get("核到"),
        "引用总数": (信.get("核验") or {}).get("引用总数"),
    }
    return 出


def main():
    文本 = open(输入, encoding="utf-8").read()
    桩 = "--桩" in sys.argv
    if 桩:
        # ⚠️ 必须在 import app **之前**改 DATA_DIR：`数据根目录` 在模块加载时就定下来了。
        #   不隔离的话 --桩 会走真实的限流文件 —— 它虽然不调 API，但 `消耗次数`
        #   在校验之后、模型之前，照样扣一次配额（实测把 2/20 变成 1/20）。
        os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="判例助手-冒烟桩-")
        if not os.environ.get("DEEPSEEK_API_KEY"):
            os.environ["DEEPSEEK_API_KEY"] = "sk-桩不需要真key"
    import app as 应用
    桩数 = _装桩() if 桩 else 0
    if not 桩 and not os.environ.get("DEEPSEEK_API_KEY"):
        print("缺 DEEPSEEK_API_KEY。要么带上：\n"
              "    cd python && DEEPSEEK_API_KEY=sk-… python3 ../scripts/smoke_model.py\n"
              "要么先用 --桩 验脚本本身（不花配额）。")
        return 2

    应用.app.config["TESTING"] = True
    客 = 应用.app.test_client()
    回 = 客.post("/analyze", json={"name": "冒烟-好意规劝", "text": 文本,
                                   "mode": "judgment", "case_date": "2017-12-13"})
    数 = 回.get_json()
    if 回.status_code != 200:
        print(f"HTTP {回.status_code}：{数}")
        return 1

    本 = _读数(数)
    print(f"输入：{os.path.basename(输入)}（{len(文本)} 字）· 模式 judgment"
          + (f" · 桩替换 {桩数} 个模块" if 桩数 else ""))
    print(f"剩余配额：{数.get('剩余次数')}/{数.get('今日上限')}")
    for 键, 值 in 本.items():
        print(f"  {键:10} {值}")
    print("  明细：")
    for 项 in (数.get("可信度") or {}).get("明细", []):
        print(f"    {项['方向']:2} {项['来源']}")

    上 = json.load(open(基线, encoding="utf-8")) if os.path.exists(基线) else None
    if 上:
        变 = [(k, 上.get(k), v) for k, v in 本.items() if 上.get(k) != v]
        print("\n与上次基线的差别：" + ("无" if not 变 else ""))
        for k, 旧, 新 in 变:
            print(f"  {k}: {旧} → {新}")
    else:
        print("\n（还没有基线；加 --存基线 写一份）")

    if "--存基线" in sys.argv:
        json.dump(本, open(基线, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"基线已写入 {os.path.relpath(基线, 根目录)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
