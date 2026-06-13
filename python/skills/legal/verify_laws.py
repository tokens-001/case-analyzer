"""
技能集：法条校验

包含5个技能：
- count_law_citations: 从分析文本中统计法条引用
- search_law_database: 在本地法条库中查找AI引用的法条原文
- verify_law_citation_realness: 校验AI引用的法条是否在法条库中存在
- verify_law_version: 比对案发日期与法条施行日期
- find_adjacent_laws: 发现引用法条附近±2条的相关条文

全部本地运行，不调API。法条库路径和用户数据目录由调用方传入。
"""

import os, re, json
from datetime import date


# ═══════════════════════════════════════════════════════════
# 共享正则 & 工具
# ═══════════════════════════════════════════════════════════

法条正则 = r'(?:《[^》]{2,20}》|[^\s，。；]{2,10}法)\s*第\s*\d+\s*(?:条(?:\s*之\s*[一二三四五六七八九十]+)?)?'

def _提取法条引用(文字):
    return list(set(re.findall(法条正则, 文字)))


def _解析法名(引用):
    """从法条引用中提取法名，如'《民法典》第1165条'→'民法典'"""
    法名匹配 = re.search(r'《?([^》\s]{2,20}?法)》?', 引用)
    if 法名匹配:
        return 法名匹配.group(1)
    if '民法典' in 引用:
        return '民法典'
    return None


def _解析法条元数据(文件路径):
    """从法条文件中提取#META...#END元数据块"""
    try:
        with open(文件路径, "r") as f:
            内容 = f.read()
        元数据匹配 = re.search(r'#META\n(.*?)\n#END', 内容, re.DOTALL)
        if not 元数据匹配:
            return {}
        元数据 = {}
        for 行 in 元数据匹配.group(1).split("\n"):
            if ":" in 行:
                键, 值 = 行.split(":", 1)
                元数据[键.strip()] = 值.strip()
        return 元数据
    except:
        return {}


# ═══════════════════════════════════════════════════════════
# Skill 1: 法条引用统计
# ═══════════════════════════════════════════════════════════

def count_law_citations(*分析列表):
    """统计AI分析中引用了多少条法律条文"""
    合并 = " ".join(分析列表)
    法条集合 = _提取法条引用(合并)
    if 法条集合:
        return f"引用法条 {len(法条集合)} 条：" + "、".join(list(法条集合)[:5])
    return "未引用法律条文"


# ═══════════════════════════════════════════════════════════
# Skill 2: 法条库查询
# ═══════════════════════════════════════════════════════════

def search_law_database(法条库目录, *分析列表):
    """在本地法条库中查找AI引用的法条原文，返回结构化对照列表"""
    if not os.path.exists(法条库目录):
        return []

    合并 = " ".join(分析列表)
    查找列表 = _提取法条引用(合并)
    法条文件列表 = os.listdir(法条库目录)
    结果列表 = []

    for 引用 in list(查找列表)[:5]:
        法名 = _解析法名(引用)
        if not 法名:
            continue
        for 法条文件 in 法条文件列表:
            if 法名 in 法条文件:
                try:
                    文件路径 = os.path.join(法条库目录, 法条文件)
                    with open(文件路径, "r") as f:
                        全文 = f.read()
                    元数据 = _解析法条元数据(文件路径)
                    条文号匹配 = re.search(r'(第\s*\d+\s*条)', 引用)
                    if 条文号匹配:
                        条文标记 = 条文号匹配.group(1)
                        位置 = 全文.find(条文标记)
                        if 位置 >= 0:
                            开始 = max(0, 位置)
                            结束 = min(len(全文), 位置 + 300)
                            结果列表.append({
                                "引用": 引用,
                                "法名": 法名,
                                "条文": 全文[开始:结束].strip() + "……",
                                "状态": 元数据.get("状态", "未知"),
                                "施行日期": 元数据.get("施行日期", ""),
                                "取代": 元数据.get("取代", ""),
                            })
                except:
                    pass

    # 记录缺失法条到 missing_laws.txt
    已找到引用 = {item["引用"] for item in 结果列表}
    缺失引用 = [r for r in list(查找列表)[:5] if r not in 已找到引用]
    if 缺失引用:
        缺失日志 = os.path.join(法条库目录, "missing_laws.txt")
        try:
            已有 = set()
            if os.path.exists(缺失日志):
                with open(缺失日志, "r") as f:
                    for line in f:
                        已有.add(line.strip())
            新增 = [r for r in 缺失引用 if r not in 已有]
            if 新增:
                with open(缺失日志, "a") as f:
                    for r in 新增:
                        f.write(f"{date.today()}\t{r}\n")
        except:
            pass

    return 结果列表


# ═══════════════════════════════════════════════════════════
# Skill 3: 法条引用真实性校验
# ═══════════════════════════════════════════════════════════

def verify_law_citation_realness(法条库目录, *分析列表):
    """提取AI引用的所有法条，和法条库交叉比对，返回库里找不到的引用列表"""
    if not os.path.exists(法条库目录):
        return []
    合并 = " ".join(分析列表)
    所有引用 = _提取法条引用(合并)
    if not 所有引用:
        return []

    法条文件列表 = os.listdir(法条库目录)
    未找到 = []
    for 引用 in 所有引用:
        法名 = _解析法名(引用)
        if not 法名:
            continue
        找到 = any(法名 in f for f in 法条文件列表)
        if not 找到:
            未找到.append(引用)
    return 未找到


# ═══════════════════════════════════════════════════════════
# Skill 4: 法条版本校验
# ═══════════════════════════════════════════════════════════

def verify_law_version(案发日期, 法条条目):
    """比对案发时间与法条版本，返回警告文字或None"""
    施行日期 = 法条条目.get("施行日期", "")
    状态 = 法条条目.get("状态", "")
    if not 施行日期:
        return None
    try:
        案发 = date.fromisoformat(案发日期)
        施行 = date.fromisoformat(施行日期)
        if 案发 < 施行:
            return f"⚠️ 案发时间({案发日期})早于本法条施行日期({施行日期})，可能适用旧法"
    except:
        pass
    if 状态 == "已废止":
        return f"⚠️ 本法条已废止，请核实是否仍可援引"
    if 状态 == "已修订":
        return f"⚠️ 本法条已修订，请核实案发时适用的版本"
    return None


# ═══════════════════════════════════════════════════════════
# Skill 5: 相邻法条发现
# ═══════════════════════════════════════════════════════════

def find_adjacent_laws(法条库目录, 法条对照):
    """扫描法条库，找到AI引用法条附近的相关条文（前2条+后2条）"""
    if not 法条对照 or not os.path.exists(法条库目录):
        return []
    相关列表 = []
    for item in 法条对照:
        引用 = item.get("引用", "")
        条文号匹配 = re.search(r'第\s*(\d+)\s*条', 引用)
        if not 条文号匹配:
            continue
        当前号 = int(条文号匹配.group(1))
        法名 = item.get("法名", "")
        for 法条文件 in os.listdir(法条库目录):
            if 法名 not in 法条文件:
                continue
            try:
                with open(os.path.join(法条库目录, 法条文件), "r") as f:
                    全文 = f.read()
                for 偏移 in [-2, -1, 1, 2]:
                    相邻号 = 当前号 + 偏移
                    if 相邻号 < 1:
                        continue
                    标记 = f"第{相邻号}条"
                    位置 = 全文.find(标记)
                    if 位置 >= 0:
                        结束 = min(len(全文), 位置 + 120)
                        相关列表.append({
                            "引用法条": 引用,
                            "相邻条文": 标记,
                            "内容": 全文[位置:结束].strip().replace("\n", " ")[:100] + "……",
                            "关系": "前条" if 偏移 < 0 else "后条"
                        })
            except:
                pass
    # 去重
    已见 = set()
    去重 = []
    for r in 相关列表:
        key = r["相邻条文"]
        if key not in 已见:
            已见.add(key)
            去重.append(r)
    return 去重[:8]
