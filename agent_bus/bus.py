#!/usr/bin/env python3
"""
Agent Bus v0.1 — 个人 AI 研发回路操作系统

三个角色：你 → GPT → Claude → 你
通信介质：本地 Markdown 文件
唯一事实源：tasks/*.md

用法：
  python bus.py new "任务名"          创建新任务
  python bus.py list                  列出所有任务及状态
  python bus.py next [role]           列出轮到该角色的任务
  python bus.py status T00X [状态]    更新任务状态
  python bus.py show T00X             显示任务全文
  python bus.py archive T00X          归档已完成任务
  python bus.py reject T00X "原因"    驳回任务
"""

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

BUS_DIR = Path(__file__).parent.absolute()
TASKS_DIR = BUS_DIR / "tasks"
ARCHIVE_DIR = BUS_DIR / "archive"
TEMPLATE = BUS_DIR / "template.md"

STATES = ["WAITING_GPT", "WAITING_CLAUDE", "WAITING_REVIEW", "WAITING_DECISION", "DONE", "REJECTED"]

ROLE_MAP = {
    "gpt": "WAITING_GPT",
    "claude": "WAITING_CLAUDE",
    "review": "WAITING_REVIEW",
    "decision": "WAITING_DECISION",
}

ROLE_LABELS = {
    "WAITING_GPT": "待GPT分析",
    "WAITING_CLAUDE": "待Claude执行",
    "WAITING_REVIEW": "待GPT评审",
    "WAITING_DECISION": "待用户拍板",
    "DONE": "已完成",
    "REJECTED": "已驳回",
}

STATUS_RE = re.compile(r'<!--\s*STATUS:\s*(\w+)\s*-->')

# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def _task_files():
    """返回 tasks/ 目录下所有 .md 文件（按创建时间排序）"""
    if not TASKS_DIR.exists():
        return []
    files = sorted(TASKS_DIR.glob("*.md"), key=lambda f: f.stat().st_ctime)
    return [f for f in files if f.name != "template.md"]


def _read_status(filepath):
    """读取文件第一行的 STATUS 注释"""
    try:
        with open(filepath, "r") as f:
            first = f.readline().strip()
        match = STATUS_RE.search(first)
        return match.group(1) if match else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _write_status(filepath, new_status):
    """更新文件第一行的 STATUS 注释"""
    with open(filepath, "r") as f:
        lines = f.readlines()

    # 修改或插入第一行
    new_line = f"<!-- STATUS: {new_status} -->\n"
    if lines and STATUS_RE.search(lines[0]):
        lines[0] = new_line
    else:
        lines.insert(0, new_line)

    with open(filepath, "w") as f:
        f.writelines(lines)


def _next_id():
    """生成下一个任务 ID"""
    existing = [f.stem[:4] for f in _task_files()]  # 只取前4位（T001）
    for i in range(1, 1000):
        tid = f"T{i:03d}"
        if tid not in existing:
            return tid
    return "T???"


def _find_task(task_id):
    """在 tasks/ 和 archive/ 中查找任务文件"""
    # 支持 T001 或 T001_判例助手 两种输入
    for d in [TASKS_DIR, ARCHIVE_DIR]:
        for f in d.glob(f"{task_id}*.md"):
            return f
    return None


# ═══════════════════════════════════════════════════════════
# 命令实现
# ═══════════════════════════════════════════════════════════

def cmd_new(args):
    """创建新任务"""
    tid = _next_id()
    safe_name = args.title.replace(" ", "").replace("/", "-")[:40]
    filename = f"{tid}_{safe_name}.md"
    filepath = TASKS_DIR / filename

    if not TEMPLATE.exists():
        print("❌ 模板文件不存在: template.md")
        sys.exit(1)

    with open(TEMPLATE, "r") as f:
        content = f.read()

    content = content.replace("{id}", tid)
    content = content.replace("{title}", args.title)
    content = content.replace("{date}", str(date.today()))

    with open(filepath, "w") as f:
        f.write(content)

    print(f"✅ 创建任务: {filename}")
    print(f"   状态: WAITING_GPT → 请把此文件发给 GPT")
    print(f"   路径: {filepath}")


def cmd_list(args):
    """列出所有任务"""
    files = _task_files()
    if not files:
        print("📭 暂无任务。用 `python bus.py new \"任务名\"` 创建。")
        return

    print(f"{'ID':6} {'状态':16} {'标题':30} {'修改时间'}")
    print("-" * 70)
    for f in files:
        status = _read_status(f)
        # 提取标题（# 开头的行）
        title = f.stem
        try:
            with open(f, "r") as fh:
                for line in fh:
                    if line.startswith("# ") and not line.startswith("# ") :
                        pass
                    if line.startswith("# ") and "—" not in line:
                        title = line.strip("# ").strip()
                        break
        except:
            pass
        label = ROLE_LABELS.get(status, status)
        mtime = date.fromtimestamp(f.stat().st_mtime).isoformat()
        icon = _status_icon(status)
        print(f"{f.stem[:6]:6} {icon} {label:14} {title[:28]:30} {mtime}")

    # 分组统计
    counts = {}
    for f in files:
        s = _read_status(f)
        counts[s] = counts.get(s, 0) + 1
    print(f"\n📊 统计: ", end="")
    parts = [f"{ROLE_LABELS.get(s, s)} x{c}" for s, c in sorted(counts.items())]
    print(" | ".join(parts))


def cmd_next(args):
    """列出轮到指定角色的任务"""
    role = args.role.lower()
    if role not in ROLE_MAP:
        print(f"❌ 未知角色: {role}")
        print(f"   可用: {', '.join(ROLE_MAP.keys())}")
        sys.exit(1)

    target = ROLE_MAP[role]
    files = _task_files()
    matched = [f for f in files if _read_status(f) == target]

    if not matched:
        print(f"📭 没有 {ROLE_LABELS[target]} 的任务。")
        return

    for f in matched:
        print(f"\n{'='*60}")
        with open(f, "r") as fh:
            content = fh.read()
        print(content[:1500])  # 限制输出长度
        if len(content) > 1500:
            print(f"\n... (全文共 {len(content)} 字，用 `python bus.py show {f.stem[:6]}` 查看)")


def cmd_status(args):
    """更新任务状态"""
    filepath = _find_task(args.task_id)
    if not filepath:
        print(f"❌ 找不到任务: {args.task_id}")
        sys.exit(1)

    new_status = args.status.upper()
    if new_status not in STATES:
        print(f"❌ 无效状态: {new_status}")
        print(f"   可用: {', '.join(STATES)}")
        sys.exit(1)

    old_status = _read_status(filepath)
    _write_status(filepath, new_status)

    old_label = ROLE_LABELS.get(old_status, old_status)
    new_label = ROLE_LABELS.get(new_status, new_status)
    print(f"✅ {args.task_id}: {old_label} → {_status_icon(new_status)} {new_label}")


def cmd_show(args):
    """显示任务全文"""
    filepath = _find_task(args.task_id)
    if not filepath:
        print(f"❌ 找不到任务: {args.task_id}")
        sys.exit(1)

    status = _read_status(filepath)
    print(f"状态: {_status_icon(status)} {ROLE_LABELS.get(status, status)}")
    print(f"{'='*60}")
    with open(filepath, "r") as f:
        print(f.read())


def cmd_archive(args):
    """归档已完成任务"""
    filepath = _find_task(args.task_id)
    if not filepath:
        print(f"❌ 找不到任务: {args.task_id}")
        sys.exit(1)

    status = _read_status(filepath)
    if status != "DONE":
        print(f"⚠️  任务状态是 {status}，不是 DONE。确定归档？(y/N): ", end="")
        if input().strip().lower() != "y":
            print("已取消。")
            return

    # 移动到 archive/，加日期前缀
    today = str(date.today())
    new_name = f"{today}_{filepath.name}"
    dest = ARCHIVE_DIR / new_name
    filepath.rename(dest)
    print(f"✅ 已归档: {filepath.name} → archive/{new_name}")


def cmd_reject(args):
    """驳回任务"""
    filepath = _find_task(args.task_id)
    if not filepath:
        print(f"❌ 找不到任务: {args.task_id}")
        sys.exit(1)

    _write_status(filepath, "REJECTED")

    # 在文件末尾追加驳回原因
    with open(filepath, "a") as f:
        f.write(f"\n\n---\n## ⚠️ 驳回 ({date.today()})\n\n{args.reason}\n")

    print(f"✅ {args.task_id} 已驳回 → WAITING_GPT")
    print(f"   原因: {args.reason}")


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════

def _status_icon(status):
    icons = {
        "WAITING_GPT": "🤖",
        "WAITING_CLAUDE": "💻",
        "WAITING_REVIEW": "🔍",
        "WAITING_DECISION": "👤",
        "DONE": "✅",
        "REJECTED": "↩️",
    }
    return icons.get(status, "❓")


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Agent Bus v0.1 — 个人 AI 研发回路操作系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python bus.py new "判例助手反馈分析"    创建新任务
  python bus.py list                      查看所有任务
  python bus.py next gpt                  查看待GPT处理的任务
  python bus.py status T001 WAITING_CLAUDE 更新状态
  python bus.py show T001                 显示任务全文
  python bus.py archive T001              归档已完成任务
  python bus.py reject T001 "需求不清"     驳回任务
        """
    )
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # new
    p_new = sub.add_parser("new", help="创建新任务")
    p_new.add_argument("title", help="任务名称")

    # list
    sub.add_parser("list", help="列出所有任务")

    # next
    p_next = sub.add_parser("next", help="列出轮到指定角色的任务")
    p_next.add_argument("role", help="角色: gpt / claude / review / decision")

    # status
    p_status = sub.add_parser("status", help="更新任务状态")
    p_status.add_argument("task_id", help="任务ID，如 T001")
    p_status.add_argument("status", help="新状态: WAITING_GPT / WAITING_CLAUDE / WAITING_REVIEW / WAITING_DECISION / DONE / REJECTED")

    # show
    p_show = sub.add_parser("show", help="显示任务全文")
    p_show.add_argument("task_id", help="任务ID，如 T001")

    # archive
    p_archive = sub.add_parser("archive", help="归档已完成任务")
    p_archive.add_argument("task_id", help="任务ID，如 T001")

    # reject
    p_reject = sub.add_parser("reject", help="驳回任务")
    p_reject.add_argument("task_id", help="任务ID，如 T001")
    p_reject.add_argument("reason", help="驳回原因")

    args = parser.parse_args()

    if args.command == "new":
        cmd_new(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "next":
        cmd_next(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "archive":
        cmd_archive(args)
    elif args.command == "reject":
        cmd_reject(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
