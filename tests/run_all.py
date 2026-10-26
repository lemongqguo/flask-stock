"""
统一测试入口（不依赖 pytest，只用标准库 unittest）。

用法：
    python tests/run_all.py          # 跑全部用例
    python tests/run_all.py -v       # 详细输出
    python tests/run_all.py test_alarm_rules   # 只跑某个模块

退出码：0 全部通过；1 存在失败/错误。
"""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(BASE_DIR, 'tests')


def main(argv):
    # 保证可以在任意工作目录下执行
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

    verbosity = 2 if ('-v' in argv or '--verbose' in argv) else 1
    patterns = [a for a in argv if not a.startswith('-')]
    pattern = f'{patterns[0]}.py' if patterns else 'test_*.py'

    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=TESTS_DIR, pattern=pattern, top_level_dir=BASE_DIR)
    if loader.errors:
        for err in loader.errors:
            print(err)
        return 1

    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
