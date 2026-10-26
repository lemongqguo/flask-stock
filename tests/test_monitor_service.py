"""
监控服务行为测试（D-02 / D-03 / D-04 / D-05）。

全部外部依赖（数据库模型、雪球、SMTP）都用 mock 替换，不产生真实副作用。
"""
import threading
import unittest
from unittest import mock

import models.stock_monitor as monitor_module
from models.stock_monitor import StockMonitor
from utils.alarm_rules import (
    ALARM_TYPE_PRICE,
    ALARM_TYPE_SELL,
    NOTIFY_SENT,
    NOTIFY_SKIPPED,
)


class FakeConfig:
    """监控服务依赖的最小配置集合。"""

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
    stock_name = '测试股'
    stock_code = 'SZ000001'


class FakeWarehouse:
    sell_rate = None
    stock_valueone = None
    stock_valuetwo = None
    stock_valuethree = None

    def __init__(self, sell_rate=None, v1=None, v2=None, v3=None):
        self.sell_rate = sell_rate
        self.stock_valueone = v1
        self.stock_valuetwo = v2
        self.stock_valuethree = v3


class FakeInfo:
    def __init__(self, v1=None, v2=None, v3=None, prefix='pe'):
        setattr(self, f'{prefix}_valueone', v1)
        setattr(self, f'{prefix}_valuetwo', v2)
        setattr(self, f'{prefix}_valuethree', v3)


def _recipients(addresses, source='env'):
    """构造 `resolve_alarm_recipients()` 的返回值形状。"""
    return {'recipients': list(addresses), 'source': source if addresses else '', 'email': ''}


class SendAlertMailTest(unittest.TestCase):
    """D-02：收件人为空时必须明确跳过，而不是把空字符串丢给 SMTP。"""

    def setUp(self):
        self.monitor = StockMonitor(config=FakeConfig())
        # 通知偏好默认全部打开；不想让"偏好关闭"干扰这里的跳过判定
        self.prefs_patcher = mock.patch.object(
            monitor_module, 'notify_enabled', return_value=True
        )
        self.prefs_patcher.start()
        self.addCleanup(self.prefs_patcher.stop)

    def test_skips_when_no_recipients(self):
        with mock.patch.object(monitor_module, 'recipients_for_user',
                               return_value=_recipients([])):
            with mock.patch.object(monitor_module, 'send_mail') as send:
                ok = self.monitor._send_alert_mail('s', 'b')
        self.assertFalse(ok)
        send.assert_not_called()

    def test_skips_when_mail_disabled(self):
        self.monitor.config.ALARM_MAIL_ENABLED = False
        with mock.patch.object(monitor_module, 'recipients_for_user',
                               return_value=_recipients(['a@b.com'])):
            with mock.patch.object(monitor_module, 'send_mail') as send:
                ok = self.monitor._send_alert_mail('s', 'b')
        self.assertFalse(ok)
        send.assert_not_called()

    def test_sends_when_recipients_present(self):
        with mock.patch.object(monitor_module, 'recipients_for_user',
                               return_value=_recipients(['a@b.com'])):
            with mock.patch.object(monitor_module, 'send_mail', return_value=True) as send:
                ok = self.monitor._send_alert_mail('s', 'b')
        self.assertTrue(ok)
        send.assert_called_once_with(subject='s', body='b', recipients=['a@b.com'])

    def test_skips_when_notify_pref_disabled(self):
        """账户设置里关掉该类告警 → 仍落库、不发信（2026-10-23 账户设置）。"""
        with mock.patch.object(monitor_module, 'notify_enabled', return_value=False):
            with mock.patch.object(monitor_module, 'recipients_for_user',
                                   return_value=_recipients(['a@b.com'])):
                with mock.patch.object(monitor_module, 'send_mail') as send:
                    status = self.monitor._send_alert_mail_status(
                        's', 'b', alarm_type=ALARM_TYPE_PRICE)
        self.assertEqual(status, NOTIFY_SKIPPED)
        send.assert_not_called()


class EmitAlarmCooldownTest(unittest.TestCase):
    """D-03：条件持续满足时只告警一次。"""

    def setUp(self):
        self.monitor = StockMonitor(config=FakeConfig())
        self.create_patcher = mock.patch.object(
            monitor_module.StockAlarm, 'create', return_value=1001
        )
        self.create_mock = self.create_patcher.start()
        self.addCleanup(self.create_patcher.stop)

        # 落库后需回写通知状态，此处 mock 掉避免真实写库
        self.status_patcher = mock.patch.object(
            monitor_module.StockAlarm, 'update_notify_status', return_value=True
        )
        self.status_mock = self.status_patcher.start()
        self.addCleanup(self.status_patcher.stop)

        self.mail_patcher = mock.patch.object(monitor_module, 'send_mail', return_value=True)
        self.mail_mock = self.mail_patcher.start()
        self.addCleanup(self.mail_patcher.stop)

        recipients_patcher = mock.patch.object(
            monitor_module, 'recipients_for_user',
            return_value=_recipients(['a@b.com'])
        )
        recipients_patcher.start()
        self.addCleanup(recipients_patcher.stop)

        prefs_patcher = mock.patch.object(monitor_module, 'notify_enabled', return_value=True)
        prefs_patcher.start()
        self.addCleanup(prefs_patcher.stop)

    def test_same_key_alerts_only_once(self):
        for _ in range(5):
            self.monitor._emit_alarm(FakeStock, '1:price:1', 's', 'b')
        self.assertEqual(self.create_mock.call_count, 1)
        self.assertEqual(self.mail_mock.call_count, 1)

    def test_different_keys_alert_separately(self):
        self.monitor._emit_alarm(FakeStock, '1:price:1', 's', 'b')
        self.monitor._emit_alarm(FakeStock, '1:price:2', 's', 'b')
        self.monitor._emit_alarm(FakeStock, '1:sell', 's', 'b')
        self.assertEqual(self.create_mock.call_count, 3)

    def test_stats_counter_increments_once(self):
        for _ in range(3):
            self.monitor._emit_alarm(FakeStock, '1:price:1', 's', 'b')
        self.assertEqual(self.monitor.stats['alarms'], 1)

    def test_alarm_persisted_before_mail(self):
        """落库与发信都要发生，且正文一致。"""
        self.monitor._emit_alarm(FakeStock, '1:sell', '标题', '正文', alarm_type=ALARM_TYPE_SELL)
        self.create_mock.assert_called_once_with(
            1, '正文', alarm_type=ALARM_TYPE_SELL, alarm_subtype=None, alarm_level=None
        )
        self.mail_mock.assert_called_once()

    def test_notify_status_written_back(self):
        """发信后必须把通知状态回写到刚插入的那条告警。"""
        self.monitor._emit_alarm(FakeStock, '1:sell', 's', 'b', alarm_type=ALARM_TYPE_SELL)
        self.status_mock.assert_called_once_with(1001, NOTIFY_SENT)


class CheckAndAlertTest(unittest.TestCase):
    """单只股票检查流程（含冷却与写回）。"""

    def setUp(self):
        self.monitor = StockMonitor(config=FakeConfig())

        for target, name in (
            (monitor_module.StockMaster, 'update'),
            (monitor_module.StockWarehouse, 'update_by_stock_master_id'),
            (monitor_module.StockKline, 'save_kline_data'),
            (monitor_module.StockAlarm, 'create'),
        ):
            p = mock.patch.object(target, name, return_value=True)
            setattr(self, f'{name}_mock', p.start())
            self.addCleanup(p.stop)

        for target, name in (
            (monitor_module.StockKline, 'get_kline_data_from_snowball'),
            (monitor_module.StockPe, 'get_by_stock_master_id'),
            (monitor_module.StockPb, 'get_by_stock_master_id'),
        ):
            p = mock.patch.object(target, name, return_value=None)
            p.start()
            self.addCleanup(p.stop)

        mail_patcher = mock.patch.object(monitor_module, 'send_mail', return_value=True)
        self.mail_mock = mail_patcher.start()
        self.addCleanup(mail_patcher.stop)

        recipients_patcher = mock.patch.object(
            monitor_module, 'recipients_for_user',
            return_value=_recipients(['a@b.com'])
        )
        recipients_patcher.start()
        self.addCleanup(recipients_patcher.stop)

        prefs_patcher = mock.patch.object(monitor_module, 'notify_enabled', return_value=True)
        prefs_patcher.start()
        self.addCleanup(prefs_patcher.stop)

        bench_patcher = mock.patch.object(
            monitor_module, 'resolve_bench_code', return_value='SH000300'
        )
        bench_patcher.start()
        self.addCleanup(bench_patcher.stop)

    def _set_warehouse(self, warehouse):
        p = mock.patch.object(
            monitor_module.StockWarehouse, 'get_by_stock_master_id', return_value=warehouse
        )
        p.start()
        self.addCleanup(p.stop)

    def _set_quote(self, data):
        p = mock.patch.object(self.monitor, 'get_stock_data', return_value=data)
        p.start()
        self.addCleanup(p.stop)

    def test_no_quote_skips_everything(self):
        self._set_quote(None)
        self.monitor.check_and_alert(FakeStock)
        self.create_mock.assert_not_called()
        self.update_mock.assert_not_called()

    def test_price_gear_alarm_fires_once_then_cooldown(self):
        self._set_warehouse(FakeWarehouse(v1=10.0, v2=9.0, v3=8.0))
        self._set_quote({'current': 8.5, 'pe_ttm': 10, 'pb': 1, 'dividend_yield': 2, 'name': 'x'})

        self.monitor.check_and_alert(FakeStock)
        self.monitor.check_and_alert(FakeStock)

        self.assertEqual(self.create_mock.call_count, 1)
        body = self.create_mock.call_args[0][1]
        self.assertIn('第二档', body)

    def test_sell_alarm_fires(self):
        self._set_warehouse(FakeWarehouse(sell_rate=20.0))
        self._set_quote({'current': 21.0, 'pe_ttm': 10, 'pb': 1, 'dividend_yield': 2, 'name': 'x'})

        self.monitor.check_and_alert(FakeStock)

        self.create_mock.assert_called_once()
        self.assertIn('目标卖出价', self.create_mock.call_args[0][1])

    def test_condition_cleared_then_reappears_alerts_again(self):
        """价格回到阈值上方应清除冷却，再次下探时能重新告警。"""
        self._set_warehouse(FakeWarehouse(v1=10.0))
        quote = {'current': 9.0, 'pe_ttm': 10, 'pb': 1, 'dividend_yield': 2, 'name': 'x'}

        with mock.patch.object(self.monitor, 'get_stock_data', return_value=quote):
            self.monitor.check_and_alert(FakeStock)
            self.assertEqual(self.create_mock.call_count, 1)

            quote['current'] = 11.0
            self.monitor.check_and_alert(FakeStock)
            self.assertEqual(self.create_mock.call_count, 1)

            quote['current'] = 9.0
            self.monitor.check_and_alert(FakeStock)
            self.assertEqual(self.create_mock.call_count, 2)

    def test_pe_gear_alarm(self):
        self._set_warehouse(FakeWarehouse())
        self._set_quote({'current': 9.0, 'pe_ttm': 8.0, 'pb': None, 'dividend_yield': 2, 'name': 'x'})
        pe_patcher = mock.patch.object(
            monitor_module.StockPe, 'get_by_stock_master_id',
            return_value=FakeInfo(15.0, 10.0, 9.0, prefix='pe'),
        )
        pe_patcher.start()
        self.addCleanup(pe_patcher.stop)

        self.monitor.check_and_alert(FakeStock)

        self.create_mock.assert_called_once()
        self.assertIn('PE达到第三档', self.create_mock.call_args[0][1])

    def test_missing_warehouse_does_not_crash(self):
        self._set_warehouse(None)
        self._set_quote({'current': 9.0, 'pe_ttm': 8.0, 'pb': 1.0, 'dividend_yield': 2, 'name': 'x'})
        self.monitor.check_and_alert(FakeStock)
        self.create_mock.assert_not_called()

    def test_quote_exception_does_not_propagate(self):
        p = mock.patch.object(self.monitor, 'get_stock_data', side_effect=RuntimeError('boom'))
        p.start()
        self.addCleanup(p.stop)
        self.monitor.check_and_alert(FakeStock)  # 不应抛出
        self.assertEqual(self.monitor.stats['errors'], 1)


class LifecycleTest(unittest.TestCase):
    """D-05：监控线程全局唯一。"""

    def setUp(self):
        self.monitor = StockMonitor(config=FakeConfig())
        # 用不访问数据库的假循环替换真实 monitor_loop
        self._orig_loop = self.monitor.monitor_loop
        self.monitor.monitor_loop = lambda: self.monitor._stop_event.wait(30)

    def tearDown(self):
        self.monitor.monitor_loop = self._orig_loop
        self.monitor.stop_monitoring()

    def test_start_then_idempotent(self):
        self.assertTrue(self.monitor.start_monitoring())
        self.assertFalse(self.monitor.start_monitoring())
        self.assertFalse(self.monitor.start_monitoring())
        self.assertTrue(self.monitor.is_running)
        self.assertTrue(self.monitor.stop_monitoring())

    def test_only_one_thread_alive(self):
        self.monitor.start_monitoring()
        names = [t.name for t in threading.enumerate() if t.name == 'stock-monitor']
        self.assertEqual(len(names), 1)

    def test_stop_then_restart(self):
        self.monitor.start_monitoring()
        self.monitor.stop_monitoring()
        self.assertFalse(self.monitor.is_running)
        self.assertTrue(self.monitor.start_monitoring())

    def test_get_status_fields(self):
        status = StockMonitor(config=FakeConfig()).get_status()
        for key in ('running', 'thread_alive', 'in_trading_hours', 'session',
                    'cooldown_seconds', 'recipients', 'stats'):
            self.assertIn(key, status)


if __name__ == '__main__':
    unittest.main()
