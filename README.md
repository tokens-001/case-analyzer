# 判例助手（Case Analyzer）

AI 驱动的法律判例分析工具。输入一份判决书或案情描述，自动产出多维度法律分析报告，并对 AI 引用的法条做真实性校验、溯源和可信度评分。

## 功能

### 两种分析模式

**判决书分析（8 个维度）**

- 结构化摘要、核心争议提取、推理链路提取、法条适用精析
- 对立解释路径、论证完整性检查、程序问题识别、未回答问题发现

**案情分析（5 个维度 + 总结）**

- 法律关系识别、事实与证据评估、对抗路径分析、风险推演、行动建议

### 本地校验层（不依赖 LLM，防 AI 幻觉）

- **法条真实性校验**：对照内置法条库，检测 AI 是否编造不存在的法条
- **溯源对比**：逐段定位每条分析结论对应的原文依据
- **可信度评分 + 风险列表**：综合校验结果，给出整体可信度和风险提示

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
│   ├── laws/                # 13 部法条库（txt）
│   ├── case_input/          # 案例输入样例
│   └── case_log.txt         # 分析日志
├── run.sh                   # 一键启动脚本
└── .gitignore
```

## 设计要点

- **技能模块化**：21 个技能统一接口「输入文字 → 输出结构化结果」，AI 技能与本地校验技能分离
- **并行编排**：`ThreadPoolExecutor` 并行调度多个分析维度，一次分析同时跑 5–8 个技能
- **双层校验**：AI 生成分析 → 本地校验层对照法条库核查，专门解决 LLM 编造法条的问题
- **工程细节**：会话隔离（UUID）、每日限流（UID + IP 双轨）、结构化反馈收集、访问统计面板

## License

MIT
