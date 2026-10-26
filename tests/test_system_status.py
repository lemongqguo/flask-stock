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
import os
import re
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
        self.assertEqual(status['monitor']['tone'], 'bad')

    def test_running(self):
        mon = StockMonitor(config=FakeConfig)
        mon.is_running = True
        status = build_system_status(mon)
        self.assertEqual(status['monitor']['text'], '运行中')
        self.assertEqual(status['monitor']['tone'], 'ok')

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
        self.assertEqual(status['xueqiu']['tone'], 'bad')

    def test_xueqiu_missing_token(self):
        with mock.patch('config.XueqiuToken.TOKEN', ''):
            status = build_system_status(StockMonitor(config=FakeConfig))
        self.assertEqual(status['xueqiu']['text'], '未配置 Token')
        self.assertEqual(status['xueqiu']['tone'], 'bad')

    def test_xueqiu_normal_is_ok(self):
        status = build_system_status(StockMonitor(config=FakeConfig))
        self.assertTrue(status['xueqiu']['ok'])
        self.assertEqual(status['xueqiu']['tone'], 'ok')

    def test_monitor_none_degrades_to_bad(self):
        """拿不到监控实例 = 异常，红色（而不是灰色让人以为"还行"）。"""
        self.assertEqual(build_system_status(None)['monitor']['tone'], 'bad')

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


def _fake_status(monitor_tone, xueqiu_tone):
    """构造 `build_system_status()` 的返回结构（只关心 tone 时用）。"""
    return {
        'monitor': {'running': monitor_tone == 'ok', 'tone': monitor_tone,
                    'text': '运行中' if monitor_tone == 'ok' else '已停止'},
        'session': {'key': 'closed', 'text': '已收盘'},
        'cooldown': {'seconds': 14400, 'text': '4 小时'},
        'xueqiu': {'ok': xueqiu_tone == 'ok', 'tone': xueqiu_tone,
                   'text': '正常' if xueqiu_tone == 'ok' else '限流退避中', 'reason': ''},
        'updated_at': '10:00:00',
    }


class SystemStatusRenderTest(unittest.TestCase):
    """首屏就要有值：侧栏底部 4 行 + 顶栏徽标。"""

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'

    def _body(self, monitor_tone, xueqiu_tone):
        status = _fake_status(monitor_tone, xueqiu_tone)
        with mock.patch('utils.system_status.build_system_status', return_value=status):
            return self.client.get('/stock/list').get_data(as_text=True)

    def test_healthy_status_is_green(self):
        body = self._body('ok', 'ok')
        self.assertEqual(body.count('class="status-ok"'), 2)   # 监控 + 雪球
        self.assertNotIn('status-bad', body)

    def test_abnormal_status_is_red(self):
        body = self._body('bad', 'bad')
        self.assertEqual(body.count('class="status-bad"'), 2)
        self.assertNotIn('status-ok', body)

    def test_monitor_and_xueqiu_colors_are_independent(self):
        """监控停了但雪球正常：只能各显示各的，不能整栏一个色。"""
        body = self._body('bad', 'ok')
        self.assertIn('class="status-bad"', body)
        self.assertIn('class="status-ok"', body)

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


class StatusColorCssTest(unittest.TestCase):
    """状态色的 CSS 契约：正常=绿、异常=红，且不能被 `.side-foot-row b` 的灰色压掉。"""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'static', 'css', 'theme.css'), encoding='utf-8') as fh:
            cls.css = fh.read()

    def _rule(self, selector):
        match = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', self.css)
        self.assertIsNotNone(match, '缺少样式规则 %s' % selector)
        return match.group(1)

    def test_ok_and_bad_rules_exist(self):
        self.assertIn('color: var(--ok)', self._rule('.side-foot-row b.status-ok'))
        self.assertIn('color: var(--bad)', self._rule('.side-foot-row b.status-bad'))

    def test_rules_outrank_neutral_row_style(self):
        """裸 `.status-ok` 会被 `.side-foot-row b`（特异性更高）的灰色覆盖——必须带前缀。"""
        self.assertFalse(re.search(r'^\.status-ok\s*\{', self.css, re.M))
        self.assertTrue(re.search(r'^\.side-foot-row b\.status-ok\s*\{', self.css, re.M))

    def test_aliases_point_to_green_and_red(self):
        """`--ok`/`--bad` 是语义别名：绿来自 --down、红来自 --up（红涨绿跌，down 才是绿）。"""
        root = re.search(r':root\s*\{([^}]*)\}', self.css).group(1)
        self.assertIn('--ok: var(--down)', root)
        self.assertIn('--bad: var(--up)', root)
        dark = re.search(r':root\[data-theme="dark"\]\s*\{(.*?)\}', self.css, re.S).group(1)
        light = re.search(r':root\[data-theme="light"\]\s*\{(.*?)\}', self.css, re.S).group(1)
        # 绿：青绿系（G 分量明显最高）；红：红系（R 分量最高）
        self.assertIn('--down: #12c78a', dark)
        self.assertIn('--down: #099268', light)
        self.assertIn('--up: #ff4d4f', dark)
        self.assertIn('--up: #d92d20', light)


if __name__ == '__main__':
    unittest.main()
