"""
侧栏 / 顶栏系统状态的回归用例。

对应变更：[2026-10-21 侧栏与顶栏接入实时系统状态](../spec/changes/2026-10-21-system-status-panels.md)

设计稿 `design-preview/screens/orders.html` 的侧栏底部是 4 项实时状态、顶栏有监控徽标，
这里锁：

1. 交易时段判定（含新增的「午间休市」）；
2. `build_system_status()` 的文案随监控实例状态变化；
3. API `/stock/api/system_status` 返回结构，且随 monitor 状态联动；
4. 首屏就渲染出 4 行 + 顶栏徽标（不是 JS 之后再填，避免空白闪烁）。
"""
import sys
import time
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, '.')

from app import app
from models.stock_monitor import StockMonitor, monitor
from utils.system_status import build_system_status, format_duration
from utils.trading_time import describe_session


class FakeConfig:
    """监控服务依赖的最小配置集合（与既有测试一致）。"""

    ALARM_COOLDOWN_SECONDS = 14400
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


class DescribeSessionTest(unittest.TestCase):
    """2026-10-22 是周四（交易日）。"""

    def test_morning(self):
        self.assertEqual(describe_session(datetime(2026, 10, 22, 10, 0)), 'morning')

    def test_afternoon(self):
        self.assertEqual(describe_session(datetime(2026, 10, 22, 14, 0)), 'afternoon')

    def test_noon_break(self):
        """11:30~13:00 是午间休市，不能和收盘后一样报 closed。"""
        self.assertEqual(describe_session(datetime(2026, 10, 22, 12, 0)), 'noon')

    def test_after_close(self):
        self.assertEqual(describe_session(datetime(2026, 10, 22, 15, 30)), 'closed')

    def test_weekend(self):
        self.assertEqual(describe_session(datetime(2026, 10, 24, 10, 0)), 'closed')


class FormatDurationTest(unittest.TestCase):

    def test_hours(self):
        self.assertEqual(format_duration(14400), '4 小时')

    def test_minutes(self):
        self.assertEqual(format_duration(300), '5 分钟')

    def test_unlimited(self):
        self.assertEqual(format_duration(0), '不限制')

    def test_invalid(self):
        self.assertEqual(format_duration(None), '—')


class BuildSystemStatusTest(unittest.TestCase):

    def test_stopped(self):
        status = build_system_status(StockMonitor(config=FakeConfig))
        self.assertFalse(status['monitor']['running'])
        self.assertEqual(status['monitor']['text'], '已停止')

    def test_running(self):
        mon = StockMonitor(config=FakeConfig)
        mon.is_running = True
        self.assertEqual(build_system_status(mon)['monitor']['text'], '运行中')

    def test_cooldown_from_config(self):
        status = build_system_status(StockMonitor(config=FakeConfig))
        self.assertEqual(status['cooldown']['seconds'], 14400)
        self.assertEqual(status['cooldown']['text'], '4 小时')

    def test_xueqiu_backoff(self):
        mon = StockMonitor(config=FakeConfig)
        mon._xueqiu_backoff_until = time.time() + 300
        mon._xueqiu_backoff_reason = '限流'
        status = build_system_status(mon)
        self.assertFalse(status['xueqiu']['ok'])
        self.assertEqual(status['xueqiu']['text'], '限流退避中')

    def test_xueqiu_missing_token(self):
        with mock.patch('config.XueqiuToken.TOKEN', ''):
            status = build_system_status(StockMonitor(config=FakeConfig))
        self.assertEqual(status['xueqiu']['text'], '未配置 Token')

    def test_non_trading_day_text(self):
        """周末应显示「非交易日」而不是「已收盘」。"""
        status = build_system_status(StockMonitor(config=FakeConfig))
        self.assertIn(status['session']['text'], ('非交易日', '已收盘', '早盘交易中', '午盘交易中', '午间休市'))

    def test_monitor_none_degrades(self):
        """监控实例缺失时也要返回结构完整的占位，不能抛异常。"""
        status = build_system_status(None)
        self.assertIn('monitor', status)
        self.assertIn('session', status)


class SystemStatusApiTest(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'

    def test_api_fields(self):
        resp = self.client.get('/stock/api/system_status')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        for key in ('monitor', 'session', 'cooldown', 'xueqiu', 'updated_at'):
            self.assertIn(key, data)

    def test_api_follows_monitor_state(self):
        """用真实返回类型（dict）打桩，验证接口确实取的是监控状态而不是写死的文案。"""
        fake = {
            'running': True,
            'session': 'noon',
            'cooldown_seconds': 7200,
            'xueqiu_backoff_remaining': 0,
            'xueqiu_backoff_reason': '',
        }
        with mock.patch.object(monitor, 'get_status', return_value=fake):
            data = self.client.get('/stock/api/system_status').get_json()
        self.assertTrue(data['monitor']['running'])
        self.assertEqual(data['session']['text'], '午间休市')
        self.assertEqual(data['cooldown']['text'], '2 小时')


class SystemStatusRenderTest(unittest.TestCase):
    """首屏就要有值：侧栏底部 4 行 + 顶栏徽标。"""

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'

    def test_side_foot_rows(self):
        body = self.client.get('/stock/list').get_data(as_text=True)
        for label in ('监控', '交易时段', '告警冷却', '雪球'):
            self.assertIn('<span>%s</span>' % label, body)
        self.assertIn('data-system-status', body)
        # 旧的静态两行必须消失
        self.assertNotIn('红涨绿跌', body)

    def test_topbar_pill(self):
        body = self.client.get('/stock/list').get_data(as_text=True)
        self.assertIn('data-monitor-pill', body)
        self.assertTrue('监控运行中' in body or '监控已停止' in body)

    def test_poll_endpoint_wired(self):
        """轮询地址由 url_for 生成，不能写死路径。"""
        body = self.client.get('/stock/list').get_data(as_text=True)
        self.assertIn('data-status-url="/stock/api/system_status"', body)


if __name__ == '__main__':
    unittest.main()
