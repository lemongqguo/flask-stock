"""
测试包。

测试不依赖真实数据库与网络：只导入纯逻辑模块（告警规则、冷却、交易时段、
SQL 构造、配置解析），并用假时钟 / 假连接做隔离。

运行方式：
    python -m unittest discover -s tests -v
    python tests/run_all.py
也可被 pytest 收集（测试类均继承 unittest.TestCase）。
"""
