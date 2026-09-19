#!/usr/bin/env python3
"""用历史分析报告给校验层算三个数 —— 不花 API 钱，也不改任何数据。

    python3 scripts/audit_history.py [日志路径]

读 `data/case_log.txt`（历次真实跑出来的分析文本），把每段分析喂给
`verify_laws.classify_law_citations`，汇总：

    可验证率      旧版和新版都算得出，但旧版把它和"库外"混在一起
    旧版红牌误伤率  旧版 `未找到` 那批里，有多少其实只是"库里没这部法"
    静默逃逸率     旧版**根本看不见**的引用（只写《某法》不给条号、"参照本法第X条"）

⚠️ 只读：法条库拷到临时目录再跑，否则会把"库外"引用追加进
   data/laws/missing_laws.txt —— 那是真数据，补库清单不该被一次统计污染。
"""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))

from skills.legal.verify_laws import classify_law_citations, _提取法条引用  # noqa: E402

根目录 = os.path.dirname(os.path.abspath(__file__)).rsplit("/scripts", 1)[0]
法条库源 = os.path.join(根目录, "data", "laws")
默认日志 = os.path.join(根目录, "data", "case_log.txt")
def _切段(日志路径):
    """按分隔线切成一段段分析文本（每段 = 一个技能的输出）。

    写入时每条前面是 `判例\\n` + 50 个 `=`，但**记录数按 = 串切才对**
    （实测 = 串 27 处、整行「判例」只有 9 处 —— 一个案件的三个技能共用一次"判例"抬头）。
    """
    with open(日志路径, encoding="utf-8") as f:
        全文 = f.read()
    段 = []
    for 块 in re.split(r"={10,}", 全文):
        块 = re.sub(r"^\s*判例\s*", "", 块.strip()).strip()
        if 块:
            段.append(块)
    return 段


def _临时法条库():
    目录 = tempfile.mkdtemp(prefix="审计-法条库-")
    for 文件 in os.listdir(法条库源):
        if 文件.endswith(".txt") and 文件 != "missing_laws.txt":
            shutil.copy(os.path.join(法条库源, 文件), 目录)
    return 目录


def 审计(日志路径):
    段列表 = _切段(日志路径)
    临时库 = _临时法条库()
    合计 = {"可验证": 0, "疑似编造": 0, "库外": 0, "未识别": 0, "无条号": 0, "提取到的引用": 0}
    编造清单, 库外清单 = [], []
    含引用的段数 = 0
    try:
        for 段 in 段列表:
            结果 = classify_law_citations(临时库, "", 段)
            提取 = len(_提取法条引用(段))
            if 提取:
                含引用的段数 += 1
            合计["提取到的引用"] += 提取
            合计["可验证"] += len(结果["可验证"])
            合计["疑似编造"] += len(结果["疑似编造"])
            合计["库外"] += len(结果["库外"])
            合计["未识别"] += len(结果["未识别"])
            合计["无条号"] += len(结果["无条号引用"])
            for 引用 in 结果["疑似编造"]:
                编造清单.append(引用)
            for 引用 in 结果["库外"]:
                库外清单.append(引用)
    finally:
        shutil.rmtree(临时库, ignore_errors=True)

    指控总数 = 合计["疑似编造"] + 合计["库外"]      # 旧版会一起标 danger 的那一批
    未校验 = 合计["无条号"] + 合计["未识别"]
    全部 = 合计["提取到的引用"] + 合计["无条号"] + 合计["未识别"]
    return {
        "段数": len(段列表), "含引用的段数": 含引用的段数, "全部引用": 全部, "合计": 合计,
        "可验证率": 合计["可验证"] / 全部 if 全部 else 0.0,
        "旧版红牌数": 指控总数,
        "旧版红牌误伤率": (合计["库外"] / 指控总数) if 指控总数 else 0.0,
        "静默逃逸数": 未校验,
        "静默逃逸率": 未校验 / 全部 if 全部 else 0.0,
        "编造清单": 编造清单, "库外清单": 库外清单,
    }


def main():
    日志 = sys.argv[1] if len(sys.argv) > 1 else 默认日志
    if not os.path.exists(日志):
        print(f"找不到日志：{日志}", file=sys.stderr)
        return 2
    r = 审计(日志)
    c = r["合计"]
    print(f"数据源：{日志}")
    print(f"历史分析 {r['段数']} 段，其中 {r['含引用的段数']} 段含法条引用；"
          f"共 {r['全部引用']} 处引用\n")
    print(f"  可验证     {c['可验证']:>4}  ({c['可验证'] / max(1, r['全部引用']):.0%})")
    print(f"  疑似编造   {c['疑似编造']:>4}   ← 库里有这部法、却没有这个条号")
    print(f"  库外       {c['库外']:>4}   ← 库里没这部法，**不代表引用有误**")
    print(f"  无条号援引 {c['无条号']:>4}   ← 只写《某法》不给条号")
    print(f"  无法定位   {c['未识别']:>4}   ← 如「参照本法第X条」\n")
    print(f"旧版会亮红牌的 {r['旧版红牌数']} 次里，{r['旧版红牌误伤率']:.0%} 属于"
          f"『其实只是库里没这部法』")
    print(f"另有 {r['静默逃逸数']} 处援引（{r['静默逃逸率']:.0%}）旧版**完全看不见** —— "
          f"不进红牌、也不进任何提示")
    if r["编造清单"]:
        print("\n真·疑似编造：" + "、".join(sorted(set(r["编造清单"]))))
    if r["库外清单"]:
        print("待补库（去重后）：" + "、".join(sorted(set(r["库外清单"]))[:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
