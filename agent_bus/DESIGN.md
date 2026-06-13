# Agent Bus v0.1 — 系统设计

## 一、系统架构

### 1.1 定位

不是通用多智能体平台。是一个**单人使用的研发回路操作系统**。

三个角色：你 → GPT → Claude → 你。通信介质：本地文件系统。唯一事实源：Markdown。

### 1.2 目录结构

```
agent_bus/
├── bus.py              ← CLI 入口（唯一可执行文件）
├── template.md         ← 任务模板
├── DESIGN.md           ← 本文档
├── README.md           ← 使用说明
├── tasks/              ← 活跃任务
│   ├── T001_判例助手v3后续.md
│   └── T002_AgentBus设计.md
└── archive/            ← 已完成任务
    └── 2026-06-13_T001_判例助手v3后续.md
```

### 1.3 状态机

```
                    ┌─────────────────────────────┐
                    │                             │
                    ▼                             │
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌──────┐
│WAITING   │→│WAITING   │→│WAITING   │→│WAITING       │→│      │
│_GPT      │ │_CLAUDE   │ │_REVIEW   │ │_DECISION     │ │DONE  │
└──────────┘  └──────────┘  └──────────┘  └──────────────┘  └──────┘
     ↑              ↑              ↑              │             │
     │              │              │   决策"驳回"   │             │
     │              │              └──────────────┘             │
     │              │                                           │
     └──────────────┴───────────────────────────────────────────┘
                        任一阶段可 REJECTED → 回到 WAITING_GPT
```

6 个状态：

| 状态 | 含义 | 当前轮到谁 |
|------|------|-----------|
| WAITING_GPT | 待 GPT 分析 | GPT |
| WAITING_CLAUDE | 待 Claude 执行 | Claude |
| WAITING_REVIEW | 待 GPT 评审 | GPT |
| WAITING_DECISION | 待用户拍板 | 你 |
| DONE | 已完成 | — |
| REJECTED | 驳回重来 | GPT |

### 1.4 数据格式

每个任务一个 Markdown 文件。第一行是状态标记：

```markdown
<!-- STATUS: WAITING_GPT -->
<!-- CREATED: 2026-06-13 -->

# T00X — 任务名

## 【目标】
...

## 【GPT分析】
...

## 【Claude执行】
...

## 【GPT评审】
...

## 【最终决策】
...
```

状态存在 HTML 注释里，CLI 扫描第一行就能获取，人读 Markdown 不受干扰。

### 1.5 命令设计

```
python bus.py new "任务名"         创建新任务，从 template.md 生成
python bus.py list                 列出所有任务及状态
python bus.py next [role]          列出轮到该角色的任务
python bus.py status T00X [状态]   更新任务状态
python bus.py show T00X            显示任务全文
python bus.py archive T00X         归档已完成任务到 archive/
python bus.py reject T00X "原因"   驳回任务，回到 WAITING_GPT
```

---

## 二、潜在问题

### 2.1 状态信任问题 ⚠️ 核心风险

CLI 通过读取文件第一行的 `<!-- STATUS: xxx -->` 来判断状态。但**人可能手动编辑文件时忘记更新状态行**，导致 CLI 显示的状态与实际内容不一致。

**缓解措施**：`bus.py list` 同时显示状态和文件修改时间。如果文件 3 天前改过但状态没变，可能是人忘了。

**v0.2 方案**：自动检测——如果【GPT分析】槽位有内容但状态还是 WAITING_GPT，自动提示"状态可能已过期"。

### 2.2 并发修改 ⚠️ 低风险

单人使用，同一时刻只有一个角色在操作一个任务。真正的并发发生在"你同时打开两个终端"。文件系统层面没有锁。

**缓解措施**：`bus.py status` 更新状态时先读后写，检查文件是否被外部修改。如果检测到冲突，提示用户手动解决。

### 2.3 任务丢失

文件在本地磁盘。唯一的丢失风险：误删文件。

**缓解措施**：`bus.py archive` 是移动而非删除。tasks/ 和 archive/ 都在 git 管理下。`bus.py new` 创建文件后自动 `git add`。

### 2.4 归档策略

- `DONE` 的任务用 `bus.py archive T00X` 移动到 `archive/`
- 文件名格式：`{完成日期}_T00X_{任务名}.md`
- 归档后的任务可被 `bus.py show` 读取（自动搜索两个目录）
- Archive 目录不自动清理，靠 git 保留所有历史

### 2.5 CLI 无法检测"谁写了哪个槽位"

当前方案依赖**约定**：每个角色只写自己的槽位。CLI 无法强制执行。如果 GPT 写到了【Claude执行】槽位，CLI 也不会报错。

**v0.2 方案**：增加槽位校验——检测到不该有内容的槽位有内容时，发出警告。

### 2.6 任务膨胀

如果任务不归档、不清理，tasks/ 会堆积几十个文件。

**缓解措施**：`bus.py list` 按状态分组显示，DONE 超过 7 天的自动提醒归档。

---

## 三、v0.1 最简实现方案

### 技术约束

- 单文件 `bus.py`，300-500 行
- Python 标准库 only（argparse + pathlib + os + datetime + re）
- 不联网、不调 API、不要数据库
- macOS 优先，Linux 兼容

### 核心函数

```
create_task(name)       → 从 template.md 生成 T00X_xxx.md
list_tasks()            → 扫描 tasks/，解析状态，表格输出
next_for(role)          → 列出 WAITING_{role} 的任务
update_status(id, status) → 修改文件第一行的 STATUS 注释
show_task(id)           → 输出任务全文
archive_task(id)        → 移动文件到 archive/
reject_task(id, reason) → 状态改为 REJECTED，追加驳回原因
```

### 实现优先级

1. `list` — 看板是最核心的功能
2. `new` — 创建任务
3. `status` — 更新状态
4. `next` — 按角色筛选
5. `show` — 查看任务内容
6. `archive` — 归档
7. `reject` — 驳回

---

## 四、演进路线

### v0.2 — 智能检测

- 自动检测状态与内容不一致（槽位有内容但状态未更新）
- `git add` 自动集成
- 槽位校验（检测角色写了不该写的槽位）
- `bus.py stats` — 统计：各状态任务数、平均完成时间

### v0.3 — API 集成

- `bus.py review T00X` — 自动调用 GPT API 评审任务，写回【GPT评审】槽位
- 配置文件 `bus_config.json` 管理 API key
- `bus.py watch` — 监控 tasks/ 目录，有状态变更时自动执行下一步

### 未来 — Product OS 内核

- 任务完成后自动提取 learnings/ 和 decisions/
- 跨项目 patterns/ 交叉验证
- 与 case_studies/ 联动：每完成一个任务自动更新对应案例复盘
