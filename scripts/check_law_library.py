"""法条库体检：报告"这部法号称收了，里面却对不上"的所有情况。

为什么要有这个脚本：`verify_laws.classify_law_citations` 的判据是
`全文.find("第X条")` —— **库里没这个标题 = 疑似编造 🔴**。所以库文件只要
正文与标题错配、或者整条丢了，被冤枉的就是引用了真实法条的用户。
2026-09-20 第一次体检实测：11 个文件里 9 条整条缺失、5 处标题与正文错配、
41 处条号标题还粘在上一条正文里。这些在修之前**一个都看不见**。

跑法：
    python3 scripts/check_law_library.py        # 报告 + 非零退出码（可以进 CI）

三类问题分开列，因为处理方式不一样：
  缺号        —— 库里真没有这条正文，只能从权威文本补，**不能手打**
  错配        —— 标题下装的是上一条的尾巴，正文在文件里但配对配错了
  埋着的标题  —— 真标题粘在正文里（中文数字），`normalize_law_headings.py` 能切
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from normalize_law_headings import 中文数字, 切标题   # noqa: E402

根目录 = os.path.dirname(os.path.abspath(__file__)).rsplit("/scripts", 1)[0]
法条库 = os.path.join(根目录, "data", "laws")
标题行 = re.compile(r"(?m)^第(\d+)条$")
必填 = ["法名", "颁布日期", "施行日期", "状态"]
尾巴开头 = re.compile(r"^\s*(第[一二三四五六七八九十]+项|规定的|；|。|以及|但|前款|本条)")


def 体检(文件名, 全文):
    """返回 {问题类别: [描述]}"""
    出 = {"META": [], "缺号": [], "错配": [], "埋着的标题": []}
    元数据块 = re.search(r"#META\n(.*?)\n#END", 全文, re.DOTALL)
    if not 元数据块:
        出["META"].append("没有 #META 块 —— 时效校验读不到施行日期")
    else:
        键 = {行.split(":", 1)[0].strip() for 行 in 元数据块.group(1).split("\n") if ":" in 行}
        for 项 in 必填:
            if 项 not in 键:
                出["META"].append(f"缺字段 {项}")

    标题们 = list(标题行.finditer(全文))
    if not 标题们:
        出["缺号"].append("一个条号标题都没有")
        return 出
    号表 = [int(m.group(1)) for m in 标题们]
    for n in sorted(set(号表), key=号表.count, reverse=True):
        if 号表.count(n) > 1:
            出["错配"].append(f"第{n}条 出现 {号表.count(n)} 次")
    缺 = sorted(set(range(min(号表), max(号表) + 1)) - set(号表))
    if 缺:
        出["缺号"].append(f"{min(号表)}–{max(号表)} 里缺 {len(缺)} 条：{缺}")

    for i, m in enumerate(标题们):
        上界 = 标题们[i + 1].start() if i + 1 < len(标题们) else len(全文)
        正文 = 全文[m.end():上界].lstrip("\n")
        if 正文 and 尾巴开头.match(正文):
            出["错配"].append(f"第{m.group(1)}条 正文开头是上一条的尾巴：{正文[:20].strip()}…")
    修好, 可切 = 切标题(全文)
    for 新标题, 原文 in 可切:
        出["埋着的标题"].append(f"{原文} → {新标题}")
    # 切完之后仍留在正文里的「之N」中文条号 = 脚本不敢动的那一类（号对不上序列）
    剩下 = [x for x in re.findall(中文数字, 修好) if x[1]]
    if 剩下:
        出["埋着的标题"].append(f"另有 {len(剩下)} 处带「之N」的中文条号未切（序列对不上，需人工看）")
    return 出


def main():
    有问题的文件 = 0
    合计 = {"META": 0, "缺号": 0, "错配": 0, "埋着的标题": 0}
    for 文件名 in sorted(os.listdir(法条库)):
        if not 文件名.endswith(".txt") or 文件名 == "missing_laws.txt":
            continue
        with open(os.path.join(法条库, 文件名), encoding="utf-8") as f:
            全文 = f.read()
        出 = 体检(文件名, 全文)
        命中 = [k for k, v in 出.items() if v]
        for k, v in 出.items():
            合计[k] += len(v)
        if not 命中:
            continue
        有问题的文件 += 1
        print(f"\n{文件名}")
        for k in ("META", "缺号", "错配", "埋着的标题"):
            for 项 in 出[k]:
                print(f"  [{k}] {项}")
    print(f"\n{有问题的文件} 个文件有问题 · 合计 " +
          " ".join(f"{k}{v}" for k, v in 合计.items()))
    return 1 if 有问题的文件 else 0


if __name__ == "__main__":
    sys.exit(main())
