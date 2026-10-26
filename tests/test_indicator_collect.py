"""
指标落库与采集测试（006 指标监控）。

模型层全部用 mock 替换 `BaseModel.execute_query / execute_update`，不产生真实写库。
监控链路（`StockMonitor`）依赖 `models.stock_kline` → pandas，环境里 pandas 不可用时自动跳过。
"""
import unittest
from unittest import mock

from models.stock_indicator import (
    StockBenchKline,
    StockIndicator,
    StockIndicatorConfig,
)
from utils.indicator_rules import n_day_return

try:  # pandas 与 numpy 二进制不兼容时（本机环境现状）无法 import，跳过监控链路测试
    import models.stock_monitor as monitor_module  # noqa: F401
    from models.stock_monitor import StockMonitor
    MONITOR_IMPORTABLE = True
    MONITOR_IMPORT_ERROR = ''
except Exception as exc:  # noqa: BLE001 - 环境依赖问题，不是被测行为
    MONITOR_IMPORTABLE = False
    MONITOR_IMPORT_ERROR = str(exc)


TRADING_DATE = '2026-10-22'

# 四条同时成立的样例（2026-10-23 起只有这种情况才告警）：
# 距 52 周低 1.67%（≤5%）、回撤 -39%（≤-35%）、20 日跑输 -18pp（≤-15pp）、
# 5 日倍数 4.02 倍（≥2.5 倍，个股跌 8.05% ≥3%、基准跌 2% ≥0.5%）
COMBO_QUOTE = {'current': 61.0, 'high52w': 100.0, 'low52w': 60.0}
COMBO_STOCK_CLOSES = [10.0] * 15 + [8.7] * 5 + [8.0]
COMBO_BENCH_CLOSES = [100.0] * 20 + [98.0]


class ComputeAndSaveTest(unittest.TestCase):
    """compute_and_save：算完即按 (stock_master_id, trade_date) 幂等 upsert。"""

    SNAPSHOT = {
        'price': 70.0, 'high52w': 100.0, 'low52w': 68.0,
        'ret_5d': -8.0, 'ret_20d': -20.0,
        'bench_ret_5d': -2.0, 'bench_ret_20d': -2.0,
    }

    def test_returns_metrics_and_hits(self):
        with mock.patch.object(StockIndicator, 'execute_update', return_value=1) as upd:
            result = StockIndicator.compute_and_save(
                1, TRADING_DATE, 'SH000300', self.SNAPSHOT, None
            )
        self.assertEqual(upd.call_count, 1)
        self.assertIn('low52w', result['hits'])
        self.assertIn('rs20', result['hits'])
        self.assertIn('rs5', result['hits'])
        self.assertNotIn('drawdown', result['hits'])
        self.assertAlmostEqual(result['metrics']['drawdown_52w'], -30.0)
        self.assertAlmostEqual(result['metrics']['rs_5d_ratio'], 4.0)

    def test_upsert_sql_uses_unique_key(self):
        """同一标的同一天重复执行必须是 UPDATE，而不是插第二行。"""
        with mock.patch.object(StockIndicator, 'execute_update', return_value=1) as upd:
            StockIndicator.compute_and_save(1, TRADING_DATE, 'SH000300', self.SNAPSHOT)
        sql = ' '.join(str(upd.call_args[0][0]).split())
        self.assertIn('INSERT INTO stock_indicator', sql)
        self.assertIn('ON DUPLICATE KEY UPDATE', sql)
        params = upd.call_args[0][1]
        self.assertEqual(params[0], 1)                 # stock_master_id
        self.assertEqual(params[1], TRADING_DATE)      # trade_date

    def test_notified_at_is_not_overwritten(self):
        """已通知状态不能被后续刷新清掉——这是 24h 冷却的依据。"""
        with mock.patch.object(StockIndicator, 'execute_update', return_value=1) as upd:
            StockIndicator.compute_and_save(1, TRADING_DATE, 'SH000300', self.SNAPSHOT)
        sql = upd.call_args[0][0]
        self.assertNotIn('notified_at', sql)

    def test_write_failure_returns_none(self):
        with mock.patch.object(StockIndicator, 'execute_update',
                               side_effect=RuntimeError('deadlock')):
            self.assertIsNone(StockIndicator.compute_and_save(
                1, TRADING_DATE, 'SH000300', self.SNAPSHOT
            ))

    def test_flagged_tinyint_values(self):
        with mock.patch.object(StockIndicator, 'execute_update', return_value=1) as upd:
            StockIndicator.compute_and_save(
                1, TRADING_DATE, 'SH000300',
                {'price': 120.0, 'high52w': 100.0, 'low52w': 68.0},
            )
        params = upd.call_args[0][1]
        flags = dict(zip(
            ['price', 'high52w', 'low52w', 'pct_from_low52w', 'drawdown_52w',
             'ret_5d', 'ret_20d', 'bench_ret_5d', 'bench_ret_20d', 'rs_20d',
             'rs_5d_ratio', 'flag_low52w', 'flag_drawdown', 'flag_rs20', 'flag_rs5'],
            params[3:],
        ))
        self.assertEqual(flags['flag_low52w'], 0)
        self.assertEqual(flags['flag_drawdown'], 0)

    def test_mark_notified(self):
        with mock.patch.object(StockIndicator, 'execute_update', return_value=1) as upd:
            ok = StockIndicator.mark_notified(1, TRADING_DATE)
        self.assertTrue(ok)
        self.assertEqual(upd.call_args[0][1], (1, TRADING_DATE))

    def test_list_recent_failure_returns_empty(self):
        with mock.patch.object(StockIndicator, 'execute_query',
                               side_effect=RuntimeError('conn')):
            self.assertEqual(StockIndicator.list_recent(1), [])


class ConfigOverrideTest(unittest.TestCase):
    def test_resolve_applies_override(self):
        row = {'stock_master_id': 1, 'low52w_near_pct': 10.0, 'rs20_pct': None}
        with mock.patch.object(StockIndicatorConfig, 'get_by_stock_master_id',
                               return_value=row):
            thresholds = StockIndicatorConfig.resolve_for(1)
        self.assertEqual(thresholds['low52w_near_pct'], 10.0)
        self.assertEqual(thresholds['rs20_pct'], 15.0)

    def test_resolve_without_row_uses_globals(self):
        with mock.patch.object(StockIndicatorConfig, 'get_by_stock_master_id',
                               return_value=None):
            thresholds = StockIndicatorConfig.resolve_for(1)
        self.assertEqual(thresholds['low52w_near_pct'], 5.0)

    def test_upsert_ignores_unknown_fields(self):
        """未知字段不得进 SQL（防注入式的字段白名单）。"""
        with mock.patch.object(StockIndicatorConfig, 'execute_update',
                               return_value=1) as upd:
            StockIndicatorConfig.upsert(1, low52w_near_pct=8.0, dangerous='x')
        sql = upd.call_args[0][0]
        self.assertIn('low52w_near_pct', sql)
        self.assertNotIn('dangerous', sql)

    def test_upsert_nothing_returns_false(self):
        self.assertFalse(StockIndicatorConfig.upsert(1, unknown=1))


class BenchKlineTest(unittest.TestCase):
    def test_recent_closes_is_ascending(self):
        """查库是 DESC，返回给 n_day_return 必须先转成升序。"""
        rows = [{'close_price': '3000.0'}, {'close_price': '2900.0'}]
        with mock.patch.object(StockBenchKline, 'execute_query', return_value=rows):
            closes = StockBenchKline.get_recent_closes('SH000300', limit=2)
        self.assertEqual(closes, [2900.0, 3000.0])

    def test_recent_closes_failure_returns_empty(self):
        with mock.patch.object(StockBenchKline, 'execute_query',
                               side_effect=RuntimeError('conn')):
            self.assertEqual(StockBenchKline.get_recent_closes('SH000300'), [])

    def test_return_uses_trading_day_count(self):
        closes = [100.0] * 20 + [80.0]
        self.assertAlmostEqual(n_day_return(closes, 20), -20.0)
        self.assertIsNone(n_day_return(closes, 40))

    def test_snowball_payload_parsed_without_pandas(self):
        payload = {
            'data': {
                'column': ['timestamp', 'volume', 'open', 'high', 'low', 'close',
                           'chg', 'percent'],
                'item': [[1600000000000, 1, 1, 1, 1, 10.5, 0, 0]],
            }
        }
        rows = StockBenchKline._split_snowball_kline(payload)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][1], 10.5)
        self.assertEqual(rows[0][0].isoformat(), '2020-09-13')

    def test_snowball_payload_missing_field(self):
        rows = StockBenchKline._split_snowball_kline({'data': {'column': [], 'item': []}})
        self.assertEqual(rows, [])

    def test_sync_without_token_returns_zero(self):
        with mock.patch('models.stock_indicator.XueqiuToken') as token:
            token.TOKEN = ''
            self.assertEqual(StockBenchKline.sync_from_snowball('SH000300'), 0)

    def test_sync_saves_parsed_rows(self):
        payload = {
            'data': {
                'column': ['timestamp', 'close'],
                'item': [[1600000000000, 10.5]],
            }
        }
        with mock.patch('models.stock_indicator.XueqiuToken') as token, \
             mock.patch('models.stock_indicator.ball') as ball_mock:
            token.TOKEN = 'x'  # noqa: S105 - 仅占位符，非真实凭据
            ball_mock.kline.return_value = payload
            with mock.patch.object(StockBenchKline, 'save_closes',
                                   return_value=1) as save:
                self.assertEqual(StockBenchKline.sync_from_snowball('SH000300'), 1)
            saved = save.call_args[0][1]
            self.assertEqual(len(saved), 1)
            self.assertAlmostEqual(saved[0][1], 10.5)


PANDAS_SKIP_REASON = f'pandas/numpy 环境不可用（{MONITOR_IMPORT_ERROR}）'


class FakeConfig:
    """监控所需的最小配置，显式列出新增的指标项，避免漏配导致 AttributeError。"""

    ALARM_COOLDOWN_SECONDS = 3600
    ALARM_MAIL_ENABLED = False
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
    XUEQIU_BACKOFF_SECONDS = 0
    XUEQIU_NOTICE_INTERVAL = 300
    IND_ENABLED = True
    IND_BENCH = 'SH000300'
    IND_LOW52W_NEAR_PCT = 5.0
    IND_DRAWDOWN_52W_PCT = 35.0
    IND_RS20_PCT = 15.0
    IND_RS5_RATIO = 2.5
    IND_RS5_MIN_DROP_PCT = 3.0
    IND_RS5_MIN_BENCH_DROP_PCT = 0.5
    IND_COOLDOWN_HOURS = 24
    IND_BENCH_WINDOW_DAYS = 40


class FakeStock:
    id = 1
    stock_name = '测试股'
    stock_code = 'SZ000001'


@unittest.skipUnless(MONITOR_IMPORTABLE, PANDAS_SKIP_REASON)
class MonitorIndicatorFlowTest(unittest.TestCase):
    """监控链路：取数 → 落库 → 24h 冷却告警 → 回写通知时间。"""

    def setUp(self):
        self.monitor = StockMonitor(config=FakeConfig())
        self.create_mock = mock.patch.object(
            monitor_module.StockAlarm, 'create', return_value=1001
        ).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(monitor_module.StockAlarm, 'update_notify_status',
                          return_value=True).start()
        notifier = mock.patch.object(StockIndicator, 'mark_notified',
                                     return_value=True).start()
        self.notified_mock = notifier

    def _run(self, quote, stock_closes, bench_closes):
        with mock.patch.object(monitor_module.StockKline, 'get_recent_closes',
                               return_value=stock_closes), \
             mock.patch.object(StockBenchKline, 'get_recent_closes',
                               return_value=bench_closes), \
             mock.patch.object(StockIndicatorConfig, 'get_by_stock_master_id',
                               return_value=None), \
             mock.patch.object(StockIndicator, 'execute_update', return_value=1):
            self.monitor._check_indicators(FakeStock, quote)

    def test_combo_writes_single_alarm(self):
        """四项同时成立：只写一条 indicator / combo 告警，不是四条。"""
        self._run(COMBO_QUOTE, COMBO_STOCK_CLOSES, COMBO_BENCH_CLOSES)

        self.assertEqual(self.create_mock.call_count, 1)
        body = self.create_mock.call_args[0][1]
        kwargs = self.create_mock.call_args[1]
        self.assertEqual(kwargs['alarm_type'], 'indicator')
        self.assertEqual(kwargs['alarm_subtype'], 'combo')
        # 一条邮件交代四项
        for token in ('距 52 周低', '52 周回撤', '20 日跑输', '5 日倍数'):
            self.assertIn(token, body)

    def test_combo_within_24h_only_once(self):
        """持续状态不能每轮一条：第二次调用被 24h 冷却拦下。"""
        self._run(COMBO_QUOTE, COMBO_STOCK_CLOSES, COMBO_BENCH_CLOSES)
        self._run(COMBO_QUOTE, COMBO_STOCK_CLOSES, COMBO_BENCH_CLOSES)
        self.assertEqual(self.create_mock.call_count, 1)

    def test_single_subtype_hit_never_alerts(self):
        """只命中 52 周新低（回撤 -33.7% 不达 -35%、相对强弱均不满足）→ 不得告警。"""
        self._run({'current': 61.0, 'high52w': 92.0, 'low52w': 60.0},
                  [10.0] * 21, [100.0] * 20 + [98.0])
        self.create_mock.assert_not_called()

    def test_three_of_four_still_no_alert(self):
        """AND 语义：三条命中、差一条（52 周回撤不足）同样不告警。"""
        self._run({'current': 70.0, 'high52w': 100.0, 'low52w': 68.0},
                  COMBO_STOCK_CLOSES, COMBO_BENCH_CLOSES)
        self.create_mock.assert_not_called()

    def test_missing_bench_data_no_combo_alarm(self):
        """基准没采到 → 相对强弱不参与判定，组合不成立，宁可不报。"""
        self._run(COMBO_QUOTE, COMBO_STOCK_CLOSES, [])
        self.assertEqual(self.create_mock.call_count, 0)

    def test_new_stock_no_combo_alarm(self):
        """上市不足 20 个交易日：ret_20d 为 None → 组合不成立，不告警。"""
        self._run(COMBO_QUOTE, [10.0] * 10, COMBO_BENCH_CLOSES)
        self.assertEqual(self.create_mock.call_count, 0)

    def test_disabled_by_config(self):
        self.monitor.config.IND_ENABLED = False
        with mock.patch.object(StockIndicator, 'execute_update') as upd:
            self.monitor._check_indicators(FakeStock, {'current': 61.0, 'low52w': 60.0})
        upd.assert_not_called()
        self.create_mock.assert_not_called()

    def test_exception_does_not_propagate(self):
        with mock.patch.object(monitor_module.StockKline, 'get_recent_closes',
                               side_effect=RuntimeError('boom')):
            self.monitor._check_indicators(FakeStock, {'current': 61.0, 'low52w': 60.0})
        self.assertEqual(self.monitor.stats['errors'], 1)

    def test_condition_cleared_then_reappears_alerts_again(self):
        """条件消失应解除冷却，再次命中能重新告警（与价格告警一致的语义）。"""
        clear_quote = dict(COMBO_QUOTE, current=80.0)  # 距 52 周低 33%，组合不成立
        self._run(COMBO_QUOTE, COMBO_STOCK_CLOSES, COMBO_BENCH_CLOSES)
        self._run(clear_quote, COMBO_STOCK_CLOSES, COMBO_BENCH_CLOSES)
        self._run(COMBO_QUOTE, COMBO_STOCK_CLOSES, COMBO_BENCH_CLOSES)
        self.assertEqual(self.create_mock.call_count, 2)

    def test_notified_at_written_back(self):
        self._run(COMBO_QUOTE, COMBO_STOCK_CLOSES, COMBO_BENCH_CLOSES)
        self.assertTrue(self.notified_mock.called)


@unittest.skipUnless(MONITOR_IMPORTABLE, PANDAS_SKIP_REASON)
class BenchSyncGuardTest(unittest.TestCase):
    """基准日线每交易日只同步一次。"""

    def setUp(self):
        self.monitor = StockMonitor(config=FakeConfig())
        self.addCleanup(mock.patch.stopall)

    def test_syncs_once_per_day(self):
        with mock.patch.object(StockBenchKline, 'get_latest_trade_date',
                               return_value=None), \
             mock.patch.object(StockBenchKline, 'sync_from_snowball',
                               return_value=40) as sync:
            self.assertTrue(self.monitor._maybe_sync_bench())
            self.assertFalse(self.monitor._maybe_sync_bench())
        self.assertEqual(sync.call_count, 1)

    def test_skips_when_data_exists(self):
        with mock.patch.object(StockBenchKline, 'get_latest_trade_date',
                               return_value='2026-10-21'), \
             mock.patch.object(StockBenchKline, 'sync_from_snowball') as sync:
            self.assertFalse(self.monitor._maybe_sync_bench())
        sync.assert_not_called()

    def test_indicator_cooldown_in_status(self):
        """指标冷却要在 get_status 可观测，排障时才知道为什么没再发信。"""
        self.assertEqual(self.monitor.get_status()['indicator_cooldown_seconds'],
                         24 * 3600)


if __name__ == '__main__':
    unittest.main()
