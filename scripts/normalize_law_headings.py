"""把法条库里"粘在上一条正文里"的条号标题切出来。

起因：`data/laws/*.txt` 是从整篇文本转出来的，转换时漏了一类 ——
标题没换行、还留着中文数字，于是它**不是标题**。实测：

    第1197条 …未采取必要措施的，与该网络用户承担连带责任。第一千一百九十八条宾馆、商场…

`verify_laws.classify_law_citations` 用 `全文.find("第1198条")` 定位，找不到就判
**疑似编造** 🔴 —— 而《民法典》第1198条（安全保障义务）是侵权案里被引最多的条文之一。
库里"号称收了这部法、却没有这个条号"的，全都会变成对真实法条的误指控。

⚠️ 只切**序列上确实是下一条**的中文数字标题：
    上一条阿拉伯标题是 N，正文里出现"第N+1条"或"第N条之M" ⇒ 那是被粘住的标题
    否则不动 —— 因为"依照本法第一千一百九十八条规定"这种**引用**长得一模一样，
    一刀切会把正文里的引用切成标题，把库改坏。

跑法：
    python3 scripts/normalize_law_headings.py            # 只报告，不改文件
    python3 scripts/normalize_law_headings.py --写回      # 改文件（改完自己 diff 看一遍）
"""
import os
import re
import sys

根目录 = os.path.dirname(os.path.abspath(__file__)).rsplit("/scripts", 1)[0]
法条库 = os.path.join(根目录, "data", "laws")

D = "零一二三四五六七八九"
中文数字 = re.compile(r"第([〇零一二三四五六七八九十百千]+)条(?:之([一二三四五六七八九十]+))?")
阿拉伯标题 = re.compile(r"(?m)^第\s*(\d+)\s*条(?:\s*之([一二三四五六七八九十]+))?")


def 转数字(写):
    """中文数字 → 阿拉伯整数；不是合法数字返回 None"""
    写 = 写.replace("〇", "零")
    值, 段 = 0, 0
    for 字 in 写:
        if 字 == "千":
            值 += (段 or 1) * 1000; 段 = 0
        elif 字 == "百":
            值 += (段 or 1) * 100; 段 = 0
        elif 字 == "十":
            值 += (段 or 1) * 10; 段 = 0
        elif 字 == "零":
            continue
        else:
            段 = D.index(字)
    return 值 + 段


def 切标题(全文):
    """返回 (新全文, 改动列表)。改动 = (新标题, 原来粘着的中文写法)"""
    标题们 = list(阿拉伯标题.finditer(全文))
    if not 标题们:
        return 全文, []
    # 已经成正文标题的号，一个都不再制造第二份 —— 没有这道闸，
    # "第1101条 正文里埋着 第一千一百零二条"会被切成第二个 第1102条，
    # 而库里本来就有一个 第1102条（它装的是 1102 的后半段）。
    已有 = {int(m.group(1)): m for m in 标题们}
    候选 = []
    # 只认"序列上确实是下一条"的中文数字标题，正文里的引用长得一样但不能动
    for i, m in enumerate(标题们):
        上界 = 标题们[i + 1].start() if i + 1 < len(标题们) else len(全文)
        本条 = int(m.group(1))
        for 内 in 中文数字.finditer(全文, m.end(), 上界):
            值 = 转数字(内.group(1))
            缀 = 内.group(2) or ""
            if 值 is None:
                continue
            if 值 == 本条 + 1 and not 缀 and 值 not in 已有:   # 被粘住的下一条
                候选.append((内.start(), 内.group(), f"第{值}条"))
            elif 值 == 本条 and 缀:                             # 第133条之一 这种
                候选.append((内.start(), 内.group(), f"第{本条}条之{缀}"))
    改动 = []
    # 从后往前替换，否则前面的插入会让后面的偏移失效
    for 位置, 原文, 新标题 in sorted(候选, reverse=True):
        全文 = 全文[:位置] + "\n\n" + 新标题 + "\n" + 全文[位置 + len(原文):]
        改动.append((新标题, 原文))
    return 全文, 改动


def main():
    写回 = "--写回" in sys.argv
    总改动 = 0
    for 文件名 in sorted(os.listdir(法条库)):
        if not 文件名.endswith(".txt") or 文件名 == "missing_laws.txt":
            continue
        路径 = os.path.join(法条库, 文件名)
        with open(路径, encoding="utf-8") as f:
            原 = f.read()
        新, 改动 = 切标题(原)
        if not 改动:
            continue
        总改动 += len(改动)
        print(f"{文件名}: 粘住的标题 {len(改动)} 处 → " +
              "、".join(f"{旧}→{新标题}" for 新标题, 旧 in 改动))
        if 写回:
            with open(路径, "w", encoding="utf-8") as f:
                f.write(新)
    print(("已写回" if 写回 else "只是报告，没动文件") + f"：共 {总改动} 处")
    if not 写回 and 总改动:
        print("加 --写回 才会改文件")


if __name__ == "__main__":
    main()
