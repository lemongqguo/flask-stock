"""
优雅退出处理。

问题背景（控制台按 Ctrl+C 无反应的根因）：

1. ``concurrent.futures.ThreadPoolExecutor`` 的工作线程是**非 daemon 线程**；
2. CPython 在解释器退出时通过 ``concurrent.futures.thread._python_exit``
   （由 ``threading._register_atexit`` 注册）**逐个 join** 这些工作线程；
3. 监控任务的节流休眠最长 300s，且 ``pysnowball`` 的网络调用默认无超时，
   工作线程可能长时间不返回；

于是主线程的 ``KeyboardInterrupt`` 其实已经处理完了，进程却卡在 join 上，
表现就是"按 Ctrl+C 没反应、关不掉"。

需要注意：``executor.shutdown(wait=False, cancel_futures=True)`` 只能取消**排队中**的任务，
已经在跑的任务（例如正卡在 300 秒节流休眠里的那一个）仍要等它自己返回，
``_threads_queues`` 里的线程也就还会被 join。因此真正兜底的是看门狗。

解决策略（三层）：

1. 捕获 ``SIGINT`` / ``SIGTERM``，主动停止监控线程并取消尚未开始的任务
   （休眠用 ``threading.Event.wait`` 实现，可被停止信号立即打断；
   网络调用由 ``SOCKET_TIMEOUT`` 兜底，不会永久挂起）；
2. 起一个看门狗，超时（默认 ``SHUTDOWN_TIMEOUT`` = 5 秒）仍未退出就 ``os._exit`` 强退；
3. 再按一次中断信号立即强退。

用法::

    from utils.shutdown import install_graceful_shutdown
    install_graceful_shutdown(timeout=8, callbacks=[monitor.stop_monitoring])
"""
import logging
import os
import signal
import threading

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 8.0

# 0 表示不启用看门狗（不推荐）
EXIT_CODE = 130  # 128 + SIGINT，与 shell 惯例一致


def default_signals():
    """
    默认监听的信号：``SIGINT``（Ctrl+C）与 ``SIGTERM``（``docker stop`` / ``kill``）。

    **故意不接管** Windows 的 ``SIGBREAK``（Ctrl+Break）：它走操作系统默认行为
    ``TerminateProcess``，是"优雅退出也失效"时最后可用的强制杀进程手段。
    一旦注册 Python 处理器，这个逃生通道就没了。
    """
    return (signal.SIGINT, signal.SIGTERM)


class GracefulShutdown:
    """可被多次触发的退出控制器。"""

    def __init__(self, timeout=DEFAULT_TIMEOUT):
        self.timeout = timeout
        self._callbacks = []
        self._triggered = threading.Event()
        self._watchdog = None
        self._previous_handlers = {}

    # ------------------------------------------------------------------
    # 装配
    # ------------------------------------------------------------------
    def register(self, callback):
        """注册停止回调，触发时按注册顺序调用（异常被隔离）。"""
        self._callbacks.append(callback)
        return callback

    def install(self, signals=None):
        """安装信号处理器。非主线程或无信号支持的平台上静默跳过。"""
        for sig in (default_signals() if signals is None else signals):
            try:
                self._previous_handlers[sig] = signal.signal(sig, self)
            except (ValueError, OSError, AttributeError):
                logger.debug('无法注册信号处理器: %s', sig)
        return self

    def uninstall(self):
        """恢复原有信号处理器（供测试使用）。"""
        for sig, handler in self._previous_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError, AttributeError):
                pass
        self._previous_handlers.clear()

    @property
    def triggered(self):
        """是否已经收到过中断信号。"""
        return self._triggered.is_set()

    # ------------------------------------------------------------------
    # 信号处理
    # ------------------------------------------------------------------
    def __call__(self, signum, frame):
        name = getattr(signal.Signals(signum), 'name', str(signum))

        if self._triggered.is_set():
            logger.warning('再次收到 %s，立即强制退出', name)
            self.force_exit(EXIT_CODE)
            return

        self._triggered.set()
        logger.warning(
            '收到 %s，正在停止监控服务…（再按一次 Ctrl+C 可立即强制退出）', name
        )
        self._run_callbacks()
        self._start_watchdog()

        # 抛回主线程，让 werkzeug / 主循环正常走收尾流程
        raise KeyboardInterrupt

    def _run_callbacks(self):
        for callback in self._callbacks:
            try:
                callback()
            except Exception:
                logger.exception('退出回调执行失败: %r', callback)

    def _start_watchdog(self):
        """看门狗：超时仍未退出则强制结束，避免卡在 join 非 daemon 线程上。"""
        if not self.timeout or self.timeout <= 0:
            return
        self._watchdog = threading.Timer(self.timeout, self.force_exit, (EXIT_CODE,))
        self._watchdog.name = 'shutdown-watchdog'
        self._watchdog.daemon = True
        self._watchdog.start()

    # ------------------------------------------------------------------
    # 退出
    # ------------------------------------------------------------------
    def force_exit(self, code=EXIT_CODE):
        """强制结束进程：绕过 atexit 与非 daemon 线程的 join。"""
        logger.warning('%.1f 秒内未正常退出，强制结束进程', self.timeout or 0)
        self.flush_logs()
        os._exit(code)

    @staticmethod
    def flush_logs():
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:
                pass


def install_graceful_shutdown(timeout=DEFAULT_TIMEOUT, callbacks=()):
    """
    安装优雅退出处理器。

    :param timeout: 看门狗超时秒数，超过即强退；``0``/``None`` 表示不启用
    :param callbacks: 收到信号时依次调用的停止回调
    :return: ``GracefulShutdown`` 实例
    """
    controller = GracefulShutdown(timeout=timeout)
    for callback in callbacks:
        controller.register(callback)
    controller.install()
    return controller


def set_socket_default_timeout(seconds):
    """
    设置全局 socket 默认超时。

    ``pysnowball`` 底层用 ``requests`` 且未传 ``timeout``，网络异常时可能永久挂起，
    进而让工作线程无法退出。设一个兜底超时可以保证线程最终能返回。
    """
    import socket

    if seconds and seconds > 0:
        socket.setdefaulttimeout(float(seconds))
        return True
    return False
