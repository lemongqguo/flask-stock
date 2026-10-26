"""
优雅退出测试（Ctrl+C / SIGTERM 无法退出的回归保护）。

回归背景：ThreadPoolExecutor 的工作线程是非 daemon 线程，解释器退出时会 join；
监控任务最长休眠 300 秒，导致按下 Ctrl+C 后进程迟迟不退出。
"""
import logging
import os
import signal
import threading
import time
import unittest
from unittest import mock

from utils import shutdown as shutdown_module
from utils.shutdown import GracefulShutdown


class GracefulShutdownTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        # timeout=0 关闭看门狗：否则残留的看门狗会在其它用例里真的 os._exit 掉测试进程
        self.controller = GracefulShutdown(timeout=0)

    def _sigint(self):
        with self.assertRaises(KeyboardInterrupt):
            self.controller(signal.SIGINT, None)

    def test_first_signal_runs_callbacks(self):
        self.controller.register(lambda: self.calls.append('stop'))
        self._sigint()
        self.assertEqual(self.calls, ['stop'])
        self.assertTrue(self.controller.triggered)

    def test_callback_exception_is_isolated(self):
        """某个回调炸了，其余回调仍要执行。"""

        def boom():
            raise RuntimeError('boom')

        self.controller.register(boom)
        self.controller.register(lambda: self.calls.append('after'))
        with self.assertLogs('utils.shutdown', level='ERROR'):
            self._sigint()
        self.assertEqual(self.calls, ['after'])

    def test_second_signal_forces_exit(self):
        self._sigint()
        with mock.patch.object(shutdown_module.os, '_exit') as exit_mock:
            self.controller(signal.SIGINT, None)
        exit_mock.assert_called_once_with(130)

    def test_watchdog_forces_exit_when_stuck(self):
        """看门狗必须在超时后强退，这是 Ctrl+C 卡死的兜底。"""
        controller = GracefulShutdown(timeout=0.02)
        controller.register(lambda: None)
        with mock.patch.object(shutdown_module.os, '_exit') as exit_mock:
            with self.assertRaises(KeyboardInterrupt):
                controller(signal.SIGINT, None)
            deadline = time.time() + 3
            while time.time() < deadline and not exit_mock.called:
                time.sleep(0.02)
        self.assertTrue(exit_mock.called, '看门狗未在超时后强制退出')

    def test_force_exit_flushes_logs(self):
        handler = mock.MagicMock()
        handler.level = 0  # logging 会比较 level，必须是可用的整数
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            with mock.patch.object(shutdown_module.os, '_exit'):
                self.controller.force_exit(130)
        finally:
            root.removeHandler(handler)
        handler.flush.assert_called()

    def test_timeout_zero_disables_watchdog(self):
        controller = GracefulShutdown(timeout=0)
        controller.register(lambda: None)
        with self.assertRaises(KeyboardInterrupt):
            controller(signal.SIGINT, None)
        self.assertIsNone(controller._watchdog)

    def test_install_and_uninstall_restore_handler(self):
        previous = signal.getsignal(signal.SIGINT)
        controller = GracefulShutdown(timeout=0)
        controller.install(signals=(signal.SIGINT,))
        try:
            self.assertEqual(signal.getsignal(signal.SIGINT), controller)
        finally:
            controller.uninstall()
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)


class SocketTimeoutTest(unittest.TestCase):
    def test_set_and_disable(self):
        import socket

        original = socket.getdefaulttimeout()
        try:
            self.assertTrue(shutdown_module.set_socket_default_timeout(12.5))
            self.assertEqual(socket.getdefaulttimeout(), 12.5)
            self.assertFalse(shutdown_module.set_socket_default_timeout(0))
        finally:
            socket.setdefaulttimeout(original)


class MonitorExecutorShutdownTest(unittest.TestCase):
    """监控停止时必须取消排队任务，否则工作线程会拖住进程退出。"""

    def setUp(self):
        import models.stock_monitor as monitor_module
        self.monitor_module = monitor_module
        self.monitor = monitor_module.StockMonitor(config=FakeConfig())

    def test_lazy_executor_created_once(self):
        first = self.monitor._get_executor()
        self.assertIs(first, self.monitor._get_executor())

    def test_shutdown_executor_cancels_pending_tasks(self):
        """max_workers=2：前两个占满线程，第三个排队，应被 cancel_futures 取消。"""
        started = threading.Event()
        counter = {'n': 0}
        gate = threading.Event()

        def slow():
            counter['n'] += 1
            if counter['n'] >= 2:
                started.set()
            gate.wait(5)

        executor = self.monitor._get_executor()  # max_workers=2
        executor.submit(slow)
        executor.submit(slow)
        pending = executor.submit(slow)
        self.assertTrue(started.wait(3), '前两个任务未启动')

        self.assertTrue(self.monitor.shutdown_executor())
        gate.set()
        self.assertTrue(pending.cancelled(), '排队中的任务应被取消')
        self.assertIsNone(self.monitor._executor)

    def test_shutdown_executor_is_idempotent(self):
        self.monitor._get_executor()
        self.assertTrue(self.monitor.shutdown_executor())
        self.assertFalse(self.monitor.shutdown_executor())

    def test_stop_monitoring_shuts_down_executor(self):
        self.monitor.is_running = True
        self.monitor._get_executor()
        with mock.patch.object(self.monitor, 'monitor_thread', None):
            self.monitor.stop_monitoring(join_timeout=0)
        self.assertIsNone(self.monitor._executor)
        self.assertFalse(self.monitor.is_running)

    def test_check_and_alert_skipped_when_stopping(self):
        self.monitor._stop_event.set()
        with mock.patch.object(self.monitor, 'get_stock_data') as fetch:
            self.monitor.check_and_alert(FakeStock)
        fetch.assert_not_called()

    def test_process_stops_dispatching_after_shutdown(self):
        self.monitor.is_running = True
        self.monitor._stop_event.set()
        with mock.patch.object(self.monitor, 'check_and_alert') as check:
            self.monitor._process_stocks([{'id': 1, 'stock_code': 'SZ1', 'stock_name': 'x'}])
        check.assert_not_called()


class FakeConfig:
    ALARM_COOLDOWN_SECONDS = 3600
    ALARM_MAIL_ENABLED = True
    MONITOR_MAX_WORKERS = 2
    MONITOR_MAX_STOCKS = 10
    MONITOR_ERROR_SLEEP = 1
    MONITOR_OFF_HOURS_SLEEP = 1
    MONITOR_ROUND_INTERVAL = 0
    MONITOR_OFF_HOURS_ROUND_INTERVAL = 1
    FETCH_MIN_DELAY = 0
    FETCH_MAX_DELAY = 0
    MONITOR_OFF_HOURS_FETCH_MIN_DELAY = 0
    MONITOR_OFF_HOURS_FETCH_MAX_DELAY = 0
    XUEQIU_BACKOFF_SECONDS = 600
    XUEQIU_NOTICE_INTERVAL = 300


class FakeStock:
    id = 1
    stock_code = 'SZ300124'
    stock_name = '测试股'


if __name__ == '__main__':
    unittest.main()
