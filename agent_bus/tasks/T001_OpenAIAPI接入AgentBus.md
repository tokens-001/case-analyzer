<!-- STATUS: WAITING_GPT -->
<!-- CREATED: 2026-06-13 -->

# T001 — OpenAI API 接入 Agent Bus

---

## 【目标】

消除人肉中转。让 Agent Bus 能直接调用 GPT API：

```
task.md → bus.py → GPT API → 结果写回 task.md
```

不再需要打开 ChatGPT 网页、复制粘贴。

---

## 【GPT分析】

分四步：

**Goal 1：获得 OpenAI API key**
- 注册 platform.openai.com → 充 $5 → 拿 API key
- 独立于 ChatGPT 订阅，按量付费

**Goal 2：写最小调用脚本**
- `question.txt` → Python 调 GPT API → `answer.txt`
- 不需要 Agent，不需要 LangChain。就一个 HTTP 请求

**Goal 3：接入 Agent Bus**
- `bus.py ask-gpt T001` — 读取任务文件 → 调 GPT API → 写回【GPT分析】槽位
- `bus.py review-gpt T001` — 读取任务文件 → 调 GPT API → 写回【GPT评审】槽位

**Goal 4：继续收判例助手反馈**

---

## 【Claude执行】

（待执行：Goal 1 用户完成后，Goal 2+3 由 Claude 实现）

---

## 【GPT评审】

（待 GPT 填写）

---

## 【最终决策】

（待用户填写：什么时候开始？优先度：认知追平 > OpenAI API > Agent Bus > 反馈 > 平台）
