"""
雪球接口错误处理测试。

要求：Token 失效等业务错误**只给提示**，不打 ERROR 堆栈、不中断监控。
"""
import unittest
from unittest import mock

from utils import snowball_errors as se


class ParseErrorTest(unittest.TestCase):
    """pysnowball 抛的是 bytes JSON，需要能解析出来。"""

    RAW = (
        b'{"error_description":"\xe9\x81\x87\xe5\x88\xb0\xe9\x94\x99\xe8\xaf\xaf\xef\xbc\x8c'
        b'\xe8\xaf\xb7\xe5\x88\xb7\xe6\x96\xb0\xe9\xa1\xb5\xe9\x9d\xa2\xe6\x88\x96\xe8\x80\x85'
        b'\xe9\x87\x8d\xe6\x96\xb0\xe7\x99\xbb\xe5\xbd\x95\xe8\xb4\xa6\xe5\x8f\xb7\xe5\x90\x8e'
        b'\xe5\x86\x8d\xe8\xaf\x95","error_uri":"/v5/stock/quote.json",'
        b'"error_data":null,"error_code":"400016"}'
    )

    def test_parses_bytes_exception(self):
        exc = Exception(self.RAW)
        code, desc = se.parse_xueqiu_error(exc)
        self.assertEqual(code, '400016')
        self.assertTrue(desc)

    def test_parses_str_exception(self):
        code, desc = se.parse_xueqiu_error(Exception('{"error_code":"400017"}'))
        self.assertEqual(code, '400017')
        self.assertEqual(desc, '')

    def test_returns_none_for_unknown_exception(self):
        self.assertEqual(se.parse_xueqiu_error(Exception('connection reset')), (None, None))
        self.assertEqual(se.parse_xueqiu_error(Exception('')), (None, None))
        self.assertEqual(se.parse_xueqiu_error(Exception('{not json}')), (None, None))

    def test_classification(self):
        self.assertTrue(se.is_auth_error('400016'))
        self.assertTrue(se.is_rate_limit_error('400017'))
        self.assertTrue(se.should_backoff('400016'))
        self.assertTrue(se.should_backoff('400017'))
        self.assertFalse(se.should_backoff('400015'))

    def test_describe_is_human_readable(self):
        text = se.describe('400016', 'x')
        self.assertIn('Token', text)
        self.assertIn('400016', text)
        self.assertIn('限流', se.describe('400017', ''))


class MonitorHandlesApiErrorTest(unittest.TestCase):
    """Token 失效时监控必须静默降级，而不是抛栈。"""

    def setUp(self):
        import models.stock_monitor as monitor_module
        self.monitor_module = monitor_module
        self.monitor = monitor_module.StockMonitor(config=FakeConfig())

        token_patcher = mock.patch.object(
            monitor_module.XueqiuToken, 'TOKEN', 'fake-token'
        )
        token_patcher.start()
        self.addCleanup(token_patcher.stop)

    @staticmethod
    def _api_error(code='400016', desc='遇到错误'):
        import json
        payload = json.dumps(
            {'error_description': desc, 'error_code': code}, ensure_ascii=False
        ).encode('utf-8')
        return Exception(payload)

    def test_auth_error_logs_warning_not_exception(self):
        with mock.patch.object(
            self.monitor_module.ball, 'quote_detail', side_effect=self._api_error()
        ):
            with self.assertLogs('models.stock_monitor', level='WARNING') as captured:
                result = self.monitor.get_stock_data('SZ300124')

        self.assertIsNone(result)
        # 只提示，不打堆栈（没有 ERROR 记录）
        self.assertEqual(
            [r.levelname for r in captured.records], ['WARNING']
        )
        self.assertIn('Token', captured.records[0].getMessage())

    def test_auth_error_enters_backoff(self):
        with mock.patch.object(
            self.monitor_module.ball, 'quote_detail', side_effect=self._api_error()
        ):
            self.monitor.get_stock_data('SZ300124')

        self.assertGreater(self.monitor.xueqiu_backoff_remaining, 0)

    def test_backoff_skips_further_requests(self):
        with mock.patch.object(
            self.monitor_module.ball, 'quote_detail', side_effect=self._api_error()
        ) as quote:
            self.monitor.get_stock_data('SZ300124')
            calls_after_first = quote.call_count
            for _ in range(3):
                self.monitor.get_stock_data('SZ300124')
            self.assertEqual(quote.call_count, calls_after_first)

    def test_backoff_notice_appears_only_once(self):
        """退避期内重复调用不应重复刷日志。"""
        with mock.patch.object(
            self.monitor_module.ball, 'quote_detail', side_effect=self._api_error()
        ):
            with self.assertLogs('models.stock_monitor', level='WARNING') as captured:
                for _ in range(5):
                    self.monitor.get_stock_data('SZ300124')
        self.assertEqual(len(captured.records), 1)

    def test_kline_sync_skipped_during_backoff(self):
        self.monitor._enter_xueqiu_backoff('test')
        with mock.patch.object(
            self.monitor_module.StockKline, 'get_kline_data_from_snowball'
        ) as kline:
            self.monitor._sync_kline(FakeStock)
        kline.assert_not_called()

    def test_unknown_error_still_logs_exception(self):
        with mock.patch.object(
            self.monitor_module.ball, 'quote_detail', side_effect=RuntimeError('boom')
        ):
            with self.assertLogs('models.stock_monitor', level='ERROR'):
                self.assertIsNone(self.monitor.get_stock_data('SZ300124'))

    def test_not_found_error_does_not_enter_backoff(self):
        with mock.patch.object(
            self.monitor_module.ball, 'quote_detail',
            side_effect=self._api_error('400015', 'not exist'),
        ):
            self.monitor.get_stock_data('SZ999999')
        self.assertEqual(self.monitor.xueqiu_backoff_remaining, 0)

    def test_get_status_exposes_backoff(self):
        status = self.monitor.get_status()
        self.assertIn('xueqiu_backoff_remaining', status)
        self.assertIn('xueqiu_backoff_reason', status)


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
    stock_name = '测试股'
    stock_code = 'SZ300124'


if __name__ == '__main__':
    unittest.main()
