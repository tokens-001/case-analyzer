"""冒烟测试：锁住法条校验核心路径（真法条不误报，假法条被标记）。

运行：python3 tests/test_verify_laws.py
"""
import os
import sys

# 让 skills 包可导入（skills 在 python/ 下）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))

from skills.legal import verify_laws

法条库 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "laws")


def test_中文条文号转数字():
    assert verify_laws._文章号转数字("六百六十七") == 667
    assert verify_laws._文章号转数字("123") == 123


def test_真实法条不被误报():
    # 《民法典》第1165条 真实存在于 民法典-侵权责任编.txt
    assert verify_laws.verify_law_citation_realness(法条库, "《民法典》第1165条") == []


def test_伪造法条被标记():
    # 第99999条 在任何法条文件中都不存在 → 应被标记为找不到
    未找到 = verify_laws.verify_law_citation_realness(法条库, "《民法典》第99999条")
    assert "《民法典》第99999条" in 未找到


def test_不存在的法律被标记():
    # 整部法都不在法条库 → 应被标记
    未找到 = verify_laws.verify_law_citation_realness(法条库, "《测试不存在法》第1条")
    assert "《测试不存在法》第1条" in 未找到


if __name__ == "__main__":
    测试们 = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in 测试们:
        t()
        print(f"  ✓ {t.__name__}")
    print(f"\n{len(测试们)} 个测试全通过")
