"""
统一日志配置（D-11）。

原实现把大量异常用 print 输出，既不落文件也不带堆栈，出问题无法排查。
本模块提供统一的 logger 工厂：控制台 + 轮转文件双输出，带时间与调用位置。

gunicorn 适配（2026-10-27）：
- 日志目录默认是**项目根目录下**的 `logs/`，不再依赖进程当前工作目录
  （在别的目录执行 `gunicorn` 时相对路径会写到意外位置，权限不足还会静默降级丢日志）；
- 级别、目录、是否落盘都支持环境变量：`LOG_LEVEL` / `LOG_DIR` / `LOG_TO_FILE` / `LOG_STREAM`；
- 控制台 handler 默认写 **stdout**，且每次写入重新解析流对象
  （`--capture-output` 会在 worker 启动后才替换 `sys.stdout`，固定引用会写进旧流）。
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录
DEFAULT_LOG_DIR = os.path.join(BASE_DIR, 'logs')
DEFAULT_FORMAT = '%(asctime)s %(levelname)-7s [%(name)s] %(message)s (%(filename)s:%(lineno)d)'
DEFAULT_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

_configured = False


def resolve_log_level(level=None):
    """
    确定日志级别（字符串）：显式参数 > `LOG_LEVEL` 环境变量 > INFO。

    非法值回退 INFO——宁可少打印，也不要因为环境变量拼错导致启动失败。
    """
    for candidate in (level, os.environ.get('LOG_LEVEL')):
        if not candidate:
            continue
        if isinstance(getattr(logging, str(candidate).upper(), None), int):
            return str(candidate).upper()
        logging.getLogger(__name__).warning('日志级别 %r 非法，回退 INFO', candidate)
    return 'INFO'


class _StreamProxy:
    """
    动态解析 `sys.stdout` / `sys.stderr` 的写入代理。

    两个用途：
    1. gunicorn `--capture-output` 在 worker 启动**之后**才替换 `sys.stdout`，
       若 handler 保存的是替换前的对象，日志就写去了别的流；
    2. 终端/工具层重定向之后无需重启应用即可生效。
    """

    _RESOLVERS = {'stdout': lambda: sys.stdout, 'stderr': lambda: sys.stderr}

    def __init__(self, name='stdout'):
        self._resolver = self._RESOLVERS.get(name) or self._RESOLVERS['stdout']

    def _stream(self):
        return self._resolver() or sys.__stdout__

    # --- 文件对象协议（logging.StreamHandler 只需要 write / flush） ---
    def write(self, message):
        self._stream().write(message)

    def flush(self):
        stream = self._resolver()
        if stream is not None:
            stream.flush()

    def isatty(self):
        stream = self._resolver()
        return bool(stream is not None and stream.isatty())


def _console_stream():
    """控制台输出目标：默认 stdout，可用 `LOG_STREAM=stderr` 切换。"""
    name = (os.environ.get('LOG_STREAM') or 'stdout').strip().lower()
    return _StreamProxy('stderr' if name in ('stderr', '2') else 'stdout')


def _env_flag(key, default=True):
    """读取布尔型环境变量（1/true/yes/on 视为真）。"""
    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def setup_logging(level=None, log_dir=None, log_filename='stock_app.log', to_file=None):
    """
    初始化根 logger。可重复调用，只有第一次生效。

    :param level: 日志级别；缺省依次取 `LOG_LEVEL` 环境变量、INFO
    :param log_dir: 日志目录；缺省依次取 `LOG_DIR` 环境变量、项目根目录下的 `logs/`
    :param log_filename: 日志文件名
    :param to_file: 是否输出到文件；缺省取 `LOG_TO_FILE` 环境变量（默认开启）
    """
    global _configured
    root = logging.getLogger()
    if _configured:
        return root

    root.setLevel(getattr(logging, resolve_log_level(level), logging.INFO))
    formatter = logging.Formatter(DEFAULT_FORMAT, datefmt=DEFAULT_DATE_FORMAT)

    console_handler = logging.StreamHandler(_console_stream())
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    if to_file is None:
        to_file = _env_flag('LOG_TO_FILE', True)

    if to_file:
        target_dir = log_dir or os.environ.get('LOG_DIR') or DEFAULT_LOG_DIR
        try:
            os.makedirs(target_dir, exist_ok=True)
            file_handler = RotatingFileHandler(
                os.path.join(target_dir, log_filename),
                maxBytes=5 * 1024 * 1024,
                backupCount=10,
                encoding='utf-8',
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            root.warning('日志文件创建失败（%s），仅输出到控制台: %s', target_dir, exc)

    _configured = True
    return root


def get_logger(name):
    """获取带统一格式的 logger。"""
    return logging.getLogger(name)
