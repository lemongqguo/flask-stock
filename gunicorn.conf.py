"""
gunicorn 配置：让本项目可以直接 `gunicorn -c gunicorn.conf.py app:app` 启动。

背景：`gunicorn app:app` 只做 **import**，不会执行 `app.py` 的 `__main__` 块，
于是监控线程、退出处理器、启动自检全被跳过——现象是"服务起来了但半天没有一行日志"。
解决办法是把这些副作用收敛到 `app.prepare_runtime()`，在 worker 的 `post_fork` 里调用。

必须单进程（workers=1）的原因：
- 告警冷却（`utils/alarm_throttle`）、运行时 AI 密钥、监控线程都是**进程内内存状态**；
  多进程会让冷却失效、雪球请求翻倍、每个进程各跑一个监控线程。
- 本项目是 I/O 密集型，用 gthread 的线程池放大并发即可，不需要多进程。

常用环境变量：
- `BIND`：监听地址，缺省 `FLASK_HOST:FLASK_PORT`（默认 0.0.0.0:5000）
- `LOG_LEVEL`：日志级别，同时作用于 gunicorn 自身日志与应用日志（默认 info）
- `LOG_DIR`：应用日志文件目录（默认项目根目录下 `logs/`）
- `GUNICORN_THREADS` / `GUNICORN_TIMEOUT` / `GUNICORN_GRACEFUL_TIMEOUT`：并发与超时
"""
import os
import sys

try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:  # pragma: no cover - 极端情况下配置被 exec 而未提供 __file__
    BASE_DIR = os.getcwd()

# 保证无论从哪个目录执行 gunicorn，都能 import 到 app / config
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 导入 config 会自动加载项目根目录的 .env（见 config.load_dotenv）
from config import Config  # noqa: E402

# --- 监听地址 ---------------------------------------------------------------
bind = os.environ.get('BIND') or '%s:%s' % (Config.HOST, Config.PORT)

# --- 并发模型 ---------------------------------------------------------------
workers = 1                      # 见文件头说明：本项目必须单进程
worker_class = 'gthread'         # 只有 gthread 支持 threads，sync 会忽略该参数
threads = int(os.environ.get('GUNICORN_THREADS') or 8)
# 不预加载：master 里 import app 会预先建好 MySQL 连接池，fork 后父子共享连接 socket；
# 单 worker 下预加载也省不了内存，因此统一由 worker 自加载。
preload_app = False

# --- 超时 -------------------------------------------------------------------
# AI 分析最坏要等到 AI_TIMEOUT（默认 60s），默认 30s 的 worker timeout 会被 arbiter 判定卡死
timeout = int(os.environ.get('GUNICORN_TIMEOUT') or 120)
keepalive = int(os.environ.get('GUNICORN_KEEPALIVE') or 5)
graceful_timeout = int(os.environ.get('GUNICORN_GRACEFUL_TIMEOUT') or 30)

# --- 日志：全部打到终端（stdout / stderr），同时仍由应用自己落盘 logs/ --------
accesslog = '-'                  # '-' = stdout/stderr
errorlog = '-'
capture_output = True            # 把 worker 的 print / 第三方库输出收进 error log
loglevel = (os.environ.get('LOG_LEVEL') or 'info').lower()


def post_fork(server, worker):
    """worker fork 之后启动监控线程等运行时副作用（**不能在 preload 的 master 里做**）。

    install_signals=False：gunicorn 自己接管了 SIGINT/SIGTERM，重复注册会破坏 graceful 退出。
    """
    from app import prepare_runtime

    prepare_runtime(strict=True, install_signals=False)


def worker_exit(server, worker):
    """worker 退出前停掉监控线程，避免线程残留拖住进程。"""
    from models.stock_monitor import monitor

    monitor.stop_monitoring()
