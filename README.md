# 测试相关依赖（可选，测试本身也兼容标准库 unittest）
# 安装：pip install -r requirements-dev.txt
-r requirements.txt

# 用例基于 unittest.TestCase，因此 pytest 仅作为更强的 runner/报告器，
# 不装也能通过 `python -m unittest discover -s tests -t .` 运行。
pytest>=7.4

# 代码质量（可选，按需启用）
flake8>=6.1

########################################################################
### 生成环境pro安装部署
# ‌警告‌：Flask 内置的开发服务器（Werkzeug）性能低且不安全，‌严禁‌直接用于生产环境。
# 生产环境应使用专业的 WSGI 服务器，如 ‌Gunicorn‌ 或 ‌uWSGI‌，并通常配合 ‌Nginx‌ 作为反向代理。
pip install gunicorn

# 启动 Gunicorn
# 假设你的 Flask 应用实例在 app.py 文件中，变量名为 app：
gunicorn -w 4 -b 0.0.0.0:8000 app:app

-w 4：启动 4 个工作进程（建议设置为 2 * CPU核心数 + 1）。
-b 0.0.0.0:8000：绑定所有网络接口的 8000 端口。
app:app：格式为 模块名:应用实例名






