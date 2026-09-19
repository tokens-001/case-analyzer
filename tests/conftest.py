"""测试隔离：把运行期数据目录指到临时目录，别写进真实的 data/case_data/。

为什么必须有这个文件：`app.py` 的 `数据根目录` 在**导入时**就读 `DATA_DIR`，
而限流计数写在 `{数据根目录}/limit_ip_{今天}.json` —— 按 **IP** 归并。
测试客户端的 IP 就是 127.0.0.1，和人在本机浏览器打开的是**同一个桶**，
所以跑一次集成测试会直接吃掉人当天的剩余次数（实测：16/20 被测试用掉）。

顺带把 API key 也设成假值：`/analyze` 在 key 缺失时是先扣次数再报错，
没有 key 的测试跑法会把配额烧在根本不可能成功的请求上。
"""
import os
import tempfile

_临时 = tempfile.mkdtemp(prefix="判例助手-测试数据-")
os.environ["DATA_DIR"] = _临时
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-测试用不联网")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")
