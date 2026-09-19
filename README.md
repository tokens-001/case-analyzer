# 判例助手（Case Analyzer）

[![Test](https://github.com/tokens-001/case-analyzer/actions/workflows/test.yml/badge.svg)](https://github.com/tokens-001/case-analyzer/actions/workflows/test.yml)

AI 驱动的法律判例分析工具。输入一份判决书或案情描述，自动产出多维度法律分析报告，
并对 AI 引用的法条做可验证性校验（三态：可验证 / 疑似编造 / 库外）、原文溯源和可信度评分。

## 功能

### 两种分析模式

**判决书分析（8 个维度）**

- 结构化摘要、核心争议提取、推理链路提取、法条适用精析
- 对立解释路径、论证完整性检查、程序问题识别、未回答问题发现

**案情分析（5 个维度 + 总结）**

- 法律关系识别、事实与证据评估、对抗路径分析、风险推演、行动建议

### 本地校验层（不依赖 LLM，防 AI 幻觉）

- **法条三态校验**：AI 引用的每条法条分成三类 —— **可验证**（库里有这部法、查到这一条，附原文）/
  **疑似编造**（库里有这部法、却没有这个条号）/ **库外**（本工具没收这部法，不代表引用有误）。
  只有前两类里的问题会亮红牌，"库外"降级为说明，避免误伤真实法条导致红牌常亮。
- **未校验项显式暴露**：只写"《某法》相关规定"而不给条号的援引、"参照本法第X条"这类指代、
  以及未提供案发日期导致的时效未校验，都会单独计数并出现在风险提示里 ——
  **可信度"高"要求零未校验项**，字数达标不算证据。
- **溯源对比**：逐段定位每条分析结论对应的原文依据，段号越界即为编造
- **法条时效**：对照元数据检查已废止 / 已修订 / 案发早于施行
- **可信度评分 + 风险列表**：判据由 `verify_laws.classify_law_citations` 一处算出，
  风险列表与可信度评分都读同一份结果

### 自检：这套校验到底覆盖了多少（`scripts/audit_history.py`）

校验层自己也得有数，不然"防幻觉"只是一句声明。这条命令读**本机历史分析**重放一遍三态，
只读、不花 API 钱（历史日志是运行期产物，不在版本库里；新克隆会退到自带的
`data/sample_analysis.txt` 演示一遍，那时读数是样例的、不是全量的）：

```bash
python3 scripts/audit_history.py
```

本地 27 段历史分析、58 处法条引用的当前读数：

| 项 | 数 | 含义 |
|---|---|---|
| 可验证 | 15（26%） | 库里有这部法、且查到了这一条 |
| 疑似编造 | 0 | 有法无条 —— 这批样本里没抓到 |
| 库外 | 8 | 库里没这部法，**不代表引用有误** |
| 无条号援引 | 35（60%） | 只写"《某法》相关规定"，结构上无法校验 |

两个结论值得记下来：**改造前亮出的 8 次红牌全部是误伤**（把《著作权法》《电子签名法》
这类真实存在的法指控成编造），真阳性 0；**另有 60% 的援引旧版根本看不见**。
根因是法条库（11 部）与历史用例（AI 著作权、算法歧视案）不匹配。
样本仅 27 段，读数说明的是覆盖面，不是模型的行为率。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3 + Flask 3.0 + gunicorn |
| LLM | DeepSeek API（多技能并行调用）|
| 前端 | 原生 HTML / JS（Flask 模板渲染）|
| 存储 | JSON 文件（会话隔离）|
| 法条库 | 13 部法律文本（民法典各编、刑法、公司法等）|

## 快速开始

```bash
# 1. 安装依赖
cd python && pip install -r requirements.txt

# 2. 配置 DeepSeek API Key
export DEEPSEEK_API_KEY=sk-xxx

# 3. 启动（或直接 bash run.sh）
python3 app.py
# → 打开 http://127.0.0.1:5050
```

生产部署使用 gunicorn：

```bash
gunicorn app:app --chdir python --bind 0.0.0.0:5050
```

## 项目结构

```
case-analyzer/
├── python/
│   ├── app.py               # Flask 后端：编排层，调度各分析技能
│   ├── requirements.txt
│   ├── skills/
│   │   └── legal/           # 21 个技能模块，接口统一
│   │       ├── 判决书分析   # structure_summary / extract_dispute / ...
│   │       ├── 案情分析     # identify_relationship / project_risks / ...
│   │       └── 本地校验     # verify_laws / trace_citations / score_analysis
│   └── templates/           # cover / index / report 三个页面
├── data/
│   ├── laws/                # 法条库：11 部法（民法典按编拆成 7 个文件）+ 格式说明
│   ├── case_input/          # 样例输入（公开判例，已匿名）
│   ├── sample_analysis.txt  # 样例输出（上面那份的一次真实结果）
│   └── case_log.txt         # 本机分析日志 —— 运行期产物，不在版本库里
├── scripts/audit_history.py # 给校验层自己算覆盖面（只读、不花 API 钱）
├── run.sh                   # 一键启动脚本
└── .gitignore
```

## 设计要点

- **技能模块化**：21 个技能统一接口「输入文字 → 输出结构化结果」，AI 技能与本地校验技能分离
- **并行编排**：`ThreadPoolExecutor` 并行调度多个分析维度，一次分析同时跑 5–8 个技能
- **双层校验**：AI 生成分析 → 本地校验层按三态核查（可验证 / 疑似编造 / 库外），
  并把没被校验到的部分（无条号援引、案发日期缺失）显式说出来 —— 见 `scripts/audit_history.py` 的覆盖面读数
- **工程细节**：会话隔离（UUID）、每日限流（UID + IP 双轨）、结构化反馈收集、访问统计面板

## License

MIT
