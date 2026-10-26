"""
统一日志配置（D-11）。

原实现把大量异常用 print 输出，既不落文件也不带堆栈，出问题无法排查。
本模块提供统一的 logger 工厂：控制台 + 轮转文件双输出，带时间与调用位置。
"""
import logging
import os
from logging.handlers import RotatingFileHandler

DEFAULT_FORMAT = '%(asctime)s %(levelname)-7s [%(name)s] %(message)s (%(filename)s:%(lineno)d)'
DEFAULT_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

_configured = False


def setup_logging(level='INFO', log_dir='logs', log_filename='stock_app.log', to_file=True):
    """
    初始化根 logger。可重复调用，只有第一次生效。

    :param level: 日志级别，默认 INFO
    :param log_dir: 日志目录
    :param log_filename: 日志文件名
    :param to_file: 是否输出到文件
    """
    global _configured
    root = logging.getLogger()
    if _configured:
        return root

    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    formatter = logging.Formatter(DEFAULT_FORMAT, datefmt=DEFAULT_DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    if to_file:
        try:
            if not os.path.isdir(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            file_handler = RotatingFileHandler(
                os.path.join(log_dir, log_filename),
                maxBytes=5 * 1024 * 1024,
                backupCount=10,
                encoding='utf-8',
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            root.warning('日志文件创建失败，仅输出到控制台: %s', exc)

    _configured = True
    return root


def get_logger(name):
    """获取带统一格式的 logger。"""
    return logging.getLogger(name)
