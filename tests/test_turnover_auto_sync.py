# -*- coding: utf-8 -*-
"""
009 市场成交额自动同步（监控线程挂钩，ADR-008）：纯逻辑单测（不连数据库、不打真实接口）。

运行：python -m unittest tests.test_turnover_auto_sync -v

最小配置对象构造 StockMonitor（与 004 监控测试同范式）；
mock 仅替换 MarketDailyTurnover.count / sync_from_source，验证调度语义：
开关 / 到点判定 / 空库守护 / 失败也计间隔 / 间隔下限 / 非法间隔回落默认 / 调用点在雪球退避之前（静态契约）。
"""
import os
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from models.market_turnover import MarketDailyTurnover
from models.stock_monitor import StockMonitor


def _monitor(**overrides):
    config = SimpleNamespace(
        ALARM_COOLDOWN_SECONDS=0,
        XUEQIU_NOTICE_INTERVAL=0,
        TURNOVER_AUTO_SYNC_ENABLED=True,
        TURNOVER_AUTO_SYNC_INTERVAL=10800,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return StockMonitor(config=config)


class MaybeSyncTurnoverTest(unittest.TestCase):
    def test_disabled_switch(self):
        monitor = _monitor(TURNOVER_AUTO_SYNC_ENABLED=False)
        with mock.patch.object(MarketDailyTurnover, 'count') as count:
            self.assertFalse(monitor._maybe_sync_turnover())
        count.assert_not_called()
        self.assertEqual(monitor._turnover_next_sync_at, 0.0)

    def test_not_due_yet(self):
        monitor = _monitor()
        monitor._turnover_next_sync_at = time.monotonic() + 9999
        with mock.patch.object(MarketDailyTurnover, 'count') as count:
            self.assertFalse(monitor._maybe_sync_turnover())
        count.assert_not_called()

    def test_empty_library_skips_but_counts_interval(self):
        monitor = _monitor()
        before = time.monotonic()
        with mock.patch.object(MarketDailyTurnover, 'count', return_value=0), \
                mock.patch.object(MarketDailyTurnover, 'sync_from_source') as sync:
            self.assertFalse(monitor._maybe_sync_turnover())
        sync.assert_not_called()
        # 空库跳过也计间隔，避免每轮都查库打日志；跳过不算失败
        self.assertGreaterEqual(monitor._turnover_next_sync_at, before + 10800)
        self.assertIsNone(monitor._turnover_last_ok)

    def test_success(self):
        monitor = _monitor()
        before = time.monotonic()
        summary = {'source': '腾讯行情', 'mode': 'incremental', 'days': 60}
        with mock.patch.object(MarketDailyTurnover, 'count', return_value=8807), \
                mock.patch.object(MarketDailyTurnover, 'sync_from_source', return_value=summary) as sync:
            self.assertTrue(monitor._maybe_sync_turnover())
        sync.assert_called_once_with('auto')
        self.assertTrue(monitor._turnover_last_ok)
        self.assertIsNotNone(monitor._turnover_last_at)
        self.assertGreaterEqual(monitor._turnover_next_sync_at, before + 10800)
        self.assertEqual(monitor.stats['errors'], 0)

    def test_failure_also_counts_interval(self):
        monitor = _monitor()
        before = time.monotonic()
        with mock.patch.object(MarketDailyTurnover, 'count', return_value=8807), \
                mock.patch.object(MarketDailyTurnover, 'sync_from_source',
                                  side_effect=RuntimeError('源不可用')) as sync:
            self.assertFalse(monitor._maybe_sync_turnover())
            # 失败后立即再判定：仍被间隔挡住，不会每轮重试（交易时段轮间隔为 0）
            self.assertFalse(monitor._maybe_sync_turnover())
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(monitor.stats['errors'], 1)
        self.assertFalse(monitor._turnover_last_ok)
        self.assertGreaterEqual(monitor._turnover_next_sync_at, before + 10800)

    def test_interval_floor_60s(self):
        monitor = _monitor(TURNOVER_AUTO_SYNC_INTERVAL=1)
        before = time.monotonic()
        with mock.patch.object(MarketDailyTurnover, 'count', return_value=0):
            monitor._maybe_sync_turnover()
        self.assertGreaterEqual(monitor._turnover_next_sync_at, before + 60)

    def test_invalid_interval_falls_back_default(self):
        # 非数字字符串间隔：不抛异常，回落默认 10800s；先置位再执行，失败也计间隔
        monitor = _monitor(TURNOVER_AUTO_SYNC_INTERVAL='abc')
        before = time.monotonic()
        with mock.patch.object(MarketDailyTurnover, 'count', return_value=8807), \
                mock.patch.object(MarketDailyTurnover, 'sync_from_source',
                                  side_effect=RuntimeError('源不可用')) as sync:
            self.assertFalse(monitor._maybe_sync_turnover())
            # 失败后立即再判定：仍被默认间隔挡住，不会每轮报错重试（交易时段轮间隔为 0）
            self.assertFalse(monitor._maybe_sync_turnover())
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(monitor.stats['errors'], 1)
        self.assertFalse(monitor._turnover_last_ok)
        self.assertGreaterEqual(monitor._turnover_next_sync_at, before + 10800)


class MonitorHookContractTest(unittest.TestCase):
    """静态契约：调用点在雪球退避检查之前 + 状态字段暴露（不连库不起线程）。"""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(__file__), '..', 'models', 'stock_monitor.py')
        with open(path, encoding='utf-8') as f:
            cls.source = f.read()

    def test_hook_before_xueqiu_backoff(self):
        loop = self.source.split('def monitor_loop', 1)[1]
        hook = loop.index('self._maybe_sync_turnover()')
        backoff = loop.index('backoff = self._xueqiu_backoff_remaining()')
        self.assertLess(hook, backoff)

    def test_hook_wrapped_in_try(self):
        loop = self.source.split('def monitor_loop', 1)[1]
        self.assertIn('try:\n                self._maybe_sync_turnover()', loop)

    def test_status_fields_exposed(self):
        self.assertIn("'turnover_last_sync_at': self._turnover_last_at", self.source)
        self.assertIn("'turnover_last_sync_ok': self._turnover_last_ok", self.source)


if __name__ == '__main__':
    unittest.main()