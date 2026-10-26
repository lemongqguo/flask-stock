"""
收盘后照常采集（2026-10-23）：非交易时段不再跳过整轮，只是放慢。

对应变更：spec/changes/2026-10-23-offhours-collection.md

锁定三件事：

1. **收盘后仍然采集**：非交易时段必须跑完整一轮（原本直接 `continue` 掉，导致收盘价 / 当日 K 线不落库）；
2. **轮间隔按时段取**：交易时段 `MONITOR_ROUND_INTERVAL`、非交易时段 `MONITOR_OFF_HOURS_ROUND_INTERVAL`；
3. **每只标的的拉取节流按时段切换**：收盘后区间更长（慢采），但绝不是不采。
"""
import unittest
from unittest import mock

from models.stock_monitor import StockMonitor


class FakeConfig:
    """监控服务依赖的最小配置集合（与既有测试一致）。"""

    ALARM_COOLDOWN_SECONDS = 3600
    ALARM_MAIL_ENABLED = False
    MONITOR_MAX_WORKERS = 2
    MONITOR_MAX_STOCKS = 10
    MONITOR_ERROR_SLEEP = 1
    MONITOR_OFF_HOURS_SLEEP = 1
    MONITOR_ROUND_INTERVAL = 7
    MONITOR_OFF_HOURS_ROUND_INTERVAL = 4242
    FETCH_MIN_DELAY = 1.0
    FETCH_MAX_DELAY = 2.0
    MONITOR_OFF_HOURS_FETCH_MIN_DELAY = 11.0
    MONITOR_OFF_HOURS_FETCH_MAX_DELAY = 22.0
    XUEQIU_BACKOFF_SECONDS = 0
    XUEQIU_NOTICE_INTERVAL = 300


ACTIVE_ROWS = [{'id': 1, 'stock_name': '测试股', 'stock_code': 'SZ000001'}]


class OffHoursCollectionTest(unittest.TestCase):
    """`_sleep` 一律返回 True（等价于收到停止信号），因此每轮跑完即退出。"""

    def setUp(self):
        self.monitor = StockMonitor(config=FakeConfig())
        self.monitor.is_running = True

    def _one_round(self, trading):
        slept = []
        with mock.patch('models.stock_monitor.is_trading_time', return_value=trading), \
                mock.patch.object(self.monitor, '_maybe_send_daily_summary'), \
                mock.patch.object(self.monitor, '_maybe_sync_bench'), \
                mock.patch('models.stock_monitor.StockMaster.get_active_stocks',
                           return_value=ACTIVE_ROWS), \
                mock.patch.object(self.monitor, '_process_stocks') as process, \
                mock.patch.object(self.monitor, '_sleep',
                                  side_effect=lambda seconds: slept.append(seconds) or True):
            self.monitor.monitor_loop()
        return process, slept

    def test_after_close_still_collects(self):
        """变更的核心：收盘后照常跑整轮，而不是睡一觉跳过。"""
        process, slept = self._one_round(trading=False)
        self.assertEqual(process.call_count, 1, '收盘后必须照常采集，不能跳过整轮')
        self.assertEqual(slept, [FakeConfig.MONITOR_OFF_HOURS_ROUND_INTERVAL])

    def test_trading_hours_use_short_interval(self):
        process, slept = self._one_round(trading=True)
        self.assertEqual(process.call_count, 1)
        self.assertEqual(slept, [FakeConfig.MONITOR_ROUND_INTERVAL])

    def test_off_hours_interval_is_longer(self):
        """收盘后整体更稀：轮间隔必须大于交易时段。"""
        self.assertGreater(FakeConfig.MONITOR_OFF_HOURS_ROUND_INTERVAL,
                           FakeConfig.MONITOR_ROUND_INTERVAL)


class FetchDelayRangeTest(unittest.TestCase):
    """每只标的的拉取节流：开盘短、收盘后长（但都采）。"""

    def setUp(self):
        self.monitor = StockMonitor(config=FakeConfig())

    def test_trading_hours_range(self):
        with mock.patch('models.stock_monitor.is_trading_time', return_value=True):
            self.assertEqual(self.monitor._fetch_delay_range(),
                             (FakeConfig.FETCH_MIN_DELAY, FakeConfig.FETCH_MAX_DELAY))

    def test_off_hours_range_is_slower_but_not_zero(self):
        with mock.patch('models.stock_monitor.is_trading_time', return_value=False):
            low, high = self.monitor._fetch_delay_range()
        self.assertEqual((low, high), (FakeConfig.MONITOR_OFF_HOURS_FETCH_MIN_DELAY,
                                       FakeConfig.MONITOR_OFF_HOURS_FETCH_MAX_DELAY))
        self.assertGreater(low, FakeConfig.FETCH_MIN_DELAY, '收盘后每只标的的间隔应更长')
        self.assertGreater(high, 0, '收盘后仍要采集，节流不能是 0 以外的"停采"语义')


if __name__ == '__main__':
    unittest.main()
