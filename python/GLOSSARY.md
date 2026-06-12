# 编程名词速查 —— 从判例助手代码里提取

每个词只解释它在你代码里干什么，不展开。读代码时碰到不认识的就查。

---

## 一、程序骨架

| 词 | 一句话 | 在你代码哪里 |
|---|---|---|
| **import** | 从工具箱里拿一个现成的功能模块进来用，不用自己写 | `app.py` 第4行：`import os, json, re...` |
| **def** | 定义一个函数——给一段代码起个名字，以后叫名字就能执行它 | `app.py` 第25行：`def 获取用户ID():` |
| **return** | 函数执行完，把结果扔回去给调用者 | `app.py` 第29行：`return session["user_id"]` |
| **if / else** | 如果条件成立做A，否则做B | `app.py` 第210行：`if 已用 >= 每日上限:` |
| **for ... in** | 遍历一个列表，逐个取出来处理 | `app.py` 第104行：`for 段号 in sorted(引用集合):` |
| **try / except** | 尝试做一件事，如果出错就走except分支，不会崩溃 | `app.py` 第39行：`try: ... except Exception as e:` |
| **参数 / 实参** | def括号里的是形参（占位符），调用时传的是实参（真数据） | `def 问AI(问题, 判例, api_key):` |
| **注释** | `#` 开头的内容，程序不执行，是写给人看的 | `app.py` 第1行：`# 判例助手 - Web版` |

---

## 二、数据容器

| 词 | 一句话 | 在你代码哪里 |
|---|---|---|
| **变量** | 给数据贴个标签，后面用标签名就能拿到数据 | `app.py` 第72行：`法条提示 = "分析时..."` |
| **字符串 str** | 文本——"引号包住的任何东西" | `"判例文字:写在这里"` |
| **整数 int** | 整数——用于计数、编号、长度 | `总段落数 = len(段落列表)` |
| **列表 list** | 有序的一排数据，`[a, b, c]` 方括号包着 | `问题列表 = []` → 然后 `问题列表.append(描述)` |
| **字典 dict** | 键值对——像标签贴纸，{键: 值, 键: 值} 花括号包着 | `app.py` 第100行：`{"段号": 段号, "内容": ..., "有效": True}` |
| **JSON** | 字典/列表的字符串形式，用来存储和网络传输 | `app.py` 第209行：`json.dump(数据, f)` 写；`json.load(f)` 读 |
| **None / null** | "没有值"——不是0也不是空字符串，就是不存在 | 历史数据没溯源时返回`None` |
| **布尔 bool** | 只有两种可能：`True`（真/是）或 `False`（假/否） | `app.py` 第210行：`if 已用 >= 上限: return False` |

---

## 三、函数与控制

| 词 | 一句话 | 在你代码哪里 |
|---|---|---|
| **函数** | def定义的代码块，一个名字代表一组操作 | `def 核心争议(判例, api_key):` |
| **调用** | 使用函数——写函数名加括号，括号里放参数 | `问AI(提示, 判例, api_key)` |
| **异步 async/await** | 等待一个慢操作（如网络请求）时不卡住页面 | JS里：`async function 开始分析()` `await fetch(...)` |
| **回调函数** | 把一段代码当参数传给另一段代码，等它到时机再执行 | `reader.onload = function(e) {...}` 读完文件后触发 |
| **lambda** | 匿名短函数——`lambda x: x+1` 就是一行的临时函数 | （你代码里还没用到，爬虫常用） |

---

## 四、文件与路径

| 词 | 一句话 | 在你代码哪里 |
|---|---|---|
| **路径** | 文件在电脑里的地址 | `os.path.join(文件夹, 文件名)` |
| **os.path.join** | 智能拼接路径——自动处理斜杠，跨平台兼容 | `os.path.join(数据根目录, uid)` |
| **os.path.exists** | 检查文件或文件夹是否存在 | `if not os.path.exists(文件夹):` |
| **os.listdir** | 列出文件夹里所有文件名 | `os.listdir(法条库目录)` |
| **os.makedirs** | 创建文件夹（多层一并创建） | `os.makedirs(目录, exist_ok=True)` |
| **with open()** | 安全打开文件，用完自动关闭 | `with open(文件名, "r") as f:` |

---

## 五、网络与路由

| 词 | 一句话 | 在你代码哪里 |
|---|---|---|
| **Flask** | Python的Web框架——把Python函数变成网页接口 | `app.py` 第7行 import，第9行创建app |
| **路由 @app.route** | 把一个URL路径绑定到一个函数上 | `@app.route("/analyze")` → 访问/analyze就执行这个函数 |
| **GET** | 从服务器拿数据（打开网页、查历史） | `@app.route("/history")` 自动是GET |
| **POST** | 向服务器发送数据（提交表单、上传判例） | `@app.route("/analyze", methods=["POST"])` |
| **request** | Flask给的当前请求对象——拿到用户发来的数据 | `request.json` 拿JSON数据，`request.remote_addr` 拿IP |
| **jsonify()** | 把Python字典转成JSON字符串返回给浏览器 | `return jsonify({"结果": "..."})` |
| **fetch()** | JS里发网络请求的函数（前端用） | `fetch("/analyze", {method:"POST", body:...})` |
| **API** | 程序对程序的接口——不给人看网页，给代码调用的URL | `/analyze` 就是一个API端点 |
| **HTTP状态码** | 服务器回答的数字暗号：200=成功/400=请求有问题/429=次数用完/500=服务器崩了 | `return jsonify({...}), 429` |

---

## 六、正则表达式

| 词 | 一句话 | 在你代码哪里 |
|---|---|---|
| **正则 re** | 用规则匹配文本——"找出所有电话号码格式的东西" | `re.findall(模式, 文字)` |
| **\d+** | 匹配一个或多个数字 | `第(\d+)段` → 匹配"第3段"拿到3 |
| **\s*** | 匹配0或多个空白（空格、tab） | `第\s*\d+\s*条` → 允许"第 3 条" |
| **(?:...)** | 非捕获组——括号里的内容参与匹配但不单独提取 | `(?:民法典|刑法)` 匹配民法典或刑法 |
| **(...)** | 捕获组——括号里匹配的内容会被提取出来 | `re.findall(r'见原文第(\d+)段', 分析)` → 只提取数字 |
| **re.findall** | 找出所有匹配的字符串，返回列表 | `re.findall(r'第\d+条', 文字)` 返回所有"第X条" |
| **re.search** | 找到第一个匹配就停，返回匹配对象（含位置） | `re.search(r'第\s*\d+\s*条', 引用)` |
| **re.split** | 按匹配的位置切分字符串 | `re.split(r'(?<=[。！？])', 判例)` 按句号切 |

---

## 七、并发与异步

| 词 | 一句话 | 在你代码哪里 |
|---|---|---|
| **ThreadPoolExecutor** | 线程池——让多个任务同时跑，不等上一个结束 | `app.py` 第282行：4个分析并行调用AI |
| **executor.submit** | 把一个函数提交到线程池里跑 | `executor.submit(核心争议, 判例, api_key)` |
| **future.result()** | 等待线程池里的任务跑完，取回结果 | `分析1 = future_1.result()` |

---

## 八、Git 版本管理

| 词 | 一句话 | 你常用的命令 |
|---|---|---|
| **commit** | 一次快照——把当前所有改动存成一个版本节点 | `git commit -m "描述"` |
| **push** | 把本地的commit推送到GitHub | `git push origin main` |
| **pull** | 从GitHub拉取最新代码到本地 | `git pull origin main` |
| **staging area** | 暂存区——`git add`把改动加进来，`git commit`才真正提交 | `git add 文件` → `git commit` |
| **gitignore** | 黑名单文件——列在里面的文件不会被git跟踪 | `.env` 在gitignore里，不会被上传 |
| **origin/main** | origin=GitHub远程仓库，main=主分支 | 你的代码都在main分支上 |
| **diff** | 看改了什么——改动前后的对比 | `git diff` |

---

## 九、HTML/CSS 前端

| 词 | 一句话 | 在你代码哪里 |
|---|---|---|
| **HTML** | 网页骨架——用标签定义"这有个按钮""那有个输入框" | `index.html` 里的 `<button>` `<textarea>` `<div>` |
| **CSS** | 网页皮肤——控制颜色、大小、位置、动画 | `<style>` 标签里的 `.btn-primary { background: #5b8def; }` |
| **id / class** | id是独生子（一个页面只能一个`#caseName`），class可以批处理（`.card`可以有很多个） | JS里`getElementById("caseName")`拿单个，CSS里`.card`管一类 |
| **div** | 万能盒子——用来包裹和分组其他元素 | `<div class="card">` 装一个分析卡片 |
| **onclick** | 点击这个元素时执行一段JS代码 | `<button onclick="开始分析()">` |
| **DOM** | 浏览器把HTML变成一棵节点树，JS可以操作它 | `document.getElementById("r-core").textContent = ...` 就是在改DOM |

---

## 十、运行环境

| 词 | 一句话 | 在你项目里 |
|---|---|---|
| **虚拟环境 venv** | 项目独立的Python小隔间——装的包不影响别的项目 | `python/venv/` |
| **环境变量** | 存在操作系统里的键值对，程序通过`os.environ.get()`读取 | `DEEPSEEK_API_KEY`、`DAILY_LIMIT` |
| **.env文件** | 存放环境变量的本地文件，不提交到git | `python/.env` |
| **PythonAnywhere** | 在线Python托管平台——你的网站就跑在上面 | 部署地址就是PythonAnywhere给你的域名 |
| **Gunicorn** | 生产环境的Python应用服务器——比Flask自带的更强 | `requirements.txt` 里的 `gunicorn>=22.0` |
| **pip** | Python的包管理器——`pip install 包名` 安装第三方库 | `pip install flask python-dotenv` |
