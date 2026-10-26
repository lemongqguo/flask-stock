"""
账户设置的回归用例（个人资料 / 默认基准指数 / 告警通知）。

对应变更：[2026-10-23 账户设置](../spec/archive/changes/2026-10-23-account-profile.md)

锁三件事：
1. **真值入口唯一**：页面显示与监控发信共用 `models.account_settings` 的解析函数
   （收件人 / 基准指数 / 通知开关），不允许各写一套；
2. **开关真的拦邮件**：关掉某类告警后该类不发送，但告警仍落库；
3. **资料校验**：用户名重名 / 邮箱非法 / 基准不在白名单 → 一律不落库。
"""
import unittest
from unittest import mock

import models.stock_monitor as monitor_module
from models.account_settings import (
    BENCHMARK_CHOICES,
    BENCHMARK_CODES,
    DEFAULT_NOTIFY_PREFS,
    NOTIFY_FIELDS,
    UserNotifyPref,
    notify_enabled,
    resolve_alarm_recipients,
    resolve_bench_code,
)
from models.stock_alarm import StockAlarm
from utils.alarm_rules import (
    ALARM_TYPE_INDICATOR,
    ALARM_TYPE_PB,
    ALARM_TYPE_PE,
    ALARM_TYPE_PRICE,
    ALARM_TYPE_SELL,
    ALARM_TYPE_UNKNOWN,
    build_daily_summary,
)


class FakeUser:
    """视图层用的最小用户对象（避免用例依赖真实库里的用户行）。"""

    def __init__(self, user_id=1, username='tester', email='me@example.com'):
        self.id = user_id
        self.username = username
        self.email = email
        self.phone = None
        self.bench_code = None
        self.last_login = None
        self.updated_at = None
        self.password_hash = 'x'


def _prefs(**overrides):
    prefs = dict(DEFAULT_NOTIFY_PREFS)
    prefs['user_id'] = 1
    prefs.update(overrides)
    return prefs


class RecipientResolutionTest(unittest.TestCase):
    """收件人：环境变量优先，为空才回退账户邮箱；页面与发信必须同源。"""

    def test_env_wins(self):
        with mock.patch('config.get_alarm_recipients', return_value=['ops@x.com']):
            with mock.patch('models.account_settings.latest_account',
                            return_value={'email': 'me@x.com'}):
                result = resolve_alarm_recipients()
        self.assertEqual(result['recipients'], ['ops@x.com'])
        self.assertEqual(result['source'], 'env')

    def test_fallback_to_account_email(self):
        with mock.patch('config.get_alarm_recipients', return_value=[]):
            with mock.patch('models.account_settings.latest_account',
                            return_value={'email': 'me@x.com'}):
                result = resolve_alarm_recipients()
        self.assertEqual(result['recipients'], ['me@x.com'])
        self.assertEqual(result['source'], 'account')

    def test_empty_when_both_missing(self):
        with mock.patch('config.get_alarm_recipients', return_value=[]):
            with mock.patch('models.account_settings.latest_account',
                            return_value={'email': 'not-an-email'}):
                result = resolve_alarm_recipients()
        self.assertEqual(result['recipients'], [])
        self.assertEqual(result['source'], '')

    def test_query_error_degrades_to_empty(self):
        with mock.patch('config.get_alarm_recipients', return_value=[]):
            with mock.patch('models.account_settings.latest_account',
                            side_effect=RuntimeError('db down')):
                result = resolve_alarm_recipients()
        self.assertEqual(result['recipients'], [])


class BenchResolutionTest(unittest.TestCase):
    """默认基准指数：账户设置 > IND_BENCH > 沪深300；非法值回退。"""

    def setUp(self):
        self._patcher = mock.patch('models.account_settings.latest_account')
        self.latest = self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_uses_account_choice(self):
        self.latest.return_value = {'bench_code': 'SZ399006'}
        self.assertEqual(resolve_bench_code(), 'SZ399006')

    def test_falls_back_to_config(self):
        self.latest.return_value = {'bench_code': None}
        self.assertEqual(resolve_bench_code(default='SH000001'), 'SH000001')

    def test_ignores_unknown_code(self):
        self.latest.return_value = {'bench_code': 'BADCODE'}
        self.assertEqual(resolve_bench_code(default='SH000300'), 'SH000300')

    def test_choices_cover_required_indexes(self):
        """设计稿要求的四个指数缺一不可。"""
        names = {item['name'] for item in BENCHMARK_CHOICES}
        self.assertEqual(names, {'上证指数', '沪深300', '创业板指', '恒生指数'})
        self.assertEqual(set(BENCHMARK_CODES),
                         {'SH000001', 'SH000300', 'SZ399006', 'HKHSI'})


class NotifyPrefTest(unittest.TestCase):
    """通知偏好：默认口径、开关映射、保存 SQL。"""

    def test_effective_defaults_without_row(self):
        with mock.patch.object(UserNotifyPref, 'execute_query', return_value=[]):
            prefs = UserNotifyPref.effective()
        for field, expected in DEFAULT_NOTIFY_PREFS.items():
            self.assertEqual(prefs[field], expected)
        self.assertIsNone(prefs['user_id'])

    def test_effective_reads_latest_row(self):
        row = {'user_id': 7, 'notify_price': 0, 'notify_valuation': 1,
               'notify_indicator': 0, 'notify_daily': 1}
        with mock.patch.object(UserNotifyPref, 'execute_query', return_value=[row]):
            prefs = UserNotifyPref.effective()
        self.assertEqual(prefs['notify_price'], 0)
        self.assertEqual(prefs['notify_daily'], 1)
        self.assertEqual(prefs['user_id'], 7)

    def test_effective_degrades_on_error(self):
        with mock.patch.object(UserNotifyPref, 'execute_query',
                               side_effect=RuntimeError('db down')):
            prefs = UserNotifyPref.effective()
        self.assertEqual(prefs['notify_price'], 1)   # 查询失败按"照常发信"处理
        self.assertEqual(prefs['notify_daily'], 0)

    def test_type_mapping(self):
        prefs = _prefs(notify_price=0, notify_valuation=0, notify_indicator=0)
        self.assertFalse(notify_enabled(ALARM_TYPE_PRICE, prefs))
        self.assertFalse(notify_enabled(ALARM_TYPE_SELL, prefs))
        self.assertFalse(notify_enabled(ALARM_TYPE_PE, prefs))
        self.assertFalse(notify_enabled(ALARM_TYPE_PB, prefs))
        self.assertFalse(notify_enabled(ALARM_TYPE_INDICATOR, prefs))

    def test_valuation_switch_covers_pe_and_pb(self):
        prefs = _prefs(notify_price=1, notify_valuation=1, notify_indicator=1)
        self.assertTrue(notify_enabled(ALARM_TYPE_PE, prefs))
        self.assertTrue(notify_enabled(ALARM_TYPE_PB, prefs))

    def test_unknown_type_never_blocked(self):
        """未知类型一律放行：宁可多发，也不能静默吞掉告警。"""
        prefs = _prefs(notify_price=0, notify_valuation=0, notify_indicator=0)
        self.assertTrue(notify_enabled(ALARM_TYPE_UNKNOWN, prefs))
        self.assertTrue(notify_enabled(None, prefs))

    def test_save_writes_all_fields_and_touches_updated_at(self):
        captured = []
        flags = {'notify_price': True, 'notify_valuation': True,
                 'notify_indicator': True, 'notify_daily': False}
        with mock.patch.object(UserNotifyPref, 'execute_update',
                               side_effect=lambda q, p: captured.append((q, p)) or 1):
            ok = UserNotifyPref.save(3, **flags)
        self.assertTrue(ok)
        query, params = captured[0]
        for field in NOTIFY_FIELDS:
            self.assertIn(field, query)
        self.assertIn('updated_at = NOW()', query)
        self.assertEqual(params[0], 3)
        self.assertEqual(params[1:], (1, 1, 1, 0))   # price/valuation/indicator/daily

    def test_save_ignores_unknown_fields(self):
        with mock.patch.object(UserNotifyPref, 'execute_update') as update:
            self.assertFalse(UserNotifyPref.save(3, notify_spam=True))


class DailySummaryTest(unittest.TestCase):
    """每日汇总：开关、每日一次、无内容不发、不受分类开关影响。"""

    def setUp(self):
        self.monitor = monitor_module.StockMonitor(config=_FakeConfig())
        self.summaries = [{'hours': 24, 'total': 3,
                           'by_type': {'price': 2, 'pe': 1},
                           'samples': [{'alarm_time': '2026-10-23 09:31:00',
                                        'alarm_type': 'price',
                                        'stock_name': '测试股',
                                        'alarm_text': '正文'}]}]
        patcher = mock.patch.object(monitor_module.StockAlarm, 'summarize_since',
                                    side_effect=lambda hours: self.summaries.pop(0))
        self.summary_mock = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = mock.patch.object(monitor_module.StockMonitor, '_send_alert_mail_status',
                                    return_value='sent')
        self.send_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def _at(self, hhmm='09:00'):
        """把监控里的时间固定在当天 09:00（晚于默认 08:30）。"""
        patcher = mock.patch.object(
            monitor_module.time, 'strftime',
            side_effect=lambda fmt: hhmm if fmt == '%H:%M' else '2026-10-23')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_disabled_switch_skips(self):
        with mock.patch.object(monitor_module.UserNotifyPref, 'effective',
                               return_value=_prefs(notify_daily=0)):
            self.assertFalse(self.monitor._maybe_send_daily_summary())
        self.send_mock.assert_not_called()

    def test_before_send_time_skips(self):
        self._at('07:00')
        with mock.patch.object(monitor_module.UserNotifyPref, 'effective',
                               return_value=_prefs(notify_daily=1)):
            self.assertFalse(self.monitor._maybe_send_daily_summary())
        self.send_mock.assert_not_called()

    def test_sends_once_per_day(self):
        self._at('09:00')
        with mock.patch.object(monitor_module.UserNotifyPref, 'effective',
                               return_value=_prefs(notify_daily=1)):
            self.assertTrue(self.monitor._maybe_send_daily_summary())
            self.summaries.append({'hours': 24, 'total': 3, 'by_type': {}, 'samples': []})
            self.assertFalse(self.monitor._maybe_send_daily_summary())  # 同一天不再发
        self.assertEqual(self.send_mock.call_count, 1)

    def test_no_content_no_mail(self):
        self._at('09:00')
        self.summaries[0] = {'hours': 24, 'total': 0, 'by_type': {}, 'samples': []}
        with mock.patch.object(monitor_module.UserNotifyPref, 'effective',
                               return_value=_prefs(notify_daily=1)):
            self.assertFalse(self.monitor._maybe_send_daily_summary())
        self.send_mock.assert_not_called()

    def test_summary_mail_not_filtered_by_type_switch(self):
        """汇总邮件不属于任何单一告警类型：即使三类告警开关全关也要能发。"""
        self._at('09:00')
        with mock.patch.object(monitor_module.UserNotifyPref, 'effective',
                               return_value=_prefs(notify_daily=1)):
            with mock.patch.object(monitor_module, 'notify_enabled', return_value=False):
                self.assertTrue(self.monitor._maybe_send_daily_summary())
        # 汇总邮件不属于任何单一告警类型：调用时不带 alarm_type，因此不会被分类开关拦住
        self.assertNotIn('alarm_type', self.send_mock.call_args.kwargs)

    def test_summary_query_error_is_silent(self):
        self._at('09:00')
        self.summaries[0] = None
        with mock.patch.object(monitor_module.UserNotifyPref, 'effective',
                               return_value=_prefs(notify_daily=1)):
            self.assertFalse(self.monitor._maybe_send_daily_summary())
        self.send_mock.assert_not_called()


class _FakeConfig:
    ALARM_COOLDOWN_SECONDS = 3600
    ALARM_MAIL_ENABLED = True
    DAILY_SUMMARY_TIME = '08:30'
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


class SummaryContentTest(unittest.TestCase):
    """每日汇总文案与汇总查询（纯函数 + SQL 契约）。"""

    def test_build_daily_summary_text(self):
        subject, body = build_daily_summary({
            'hours': 24, 'total': 5,
            'by_type': {'price': 3, 'pe': 2},
            'samples': [{'alarm_time': '2026-10-23 09:31:00', 'alarm_type': 'price',
                         'stock_name': '测试股', 'alarm_text': '达到第一档'}],
        })
        self.assertIn('5 条', subject)
        self.assertIn('价格 3 条', body)
        self.assertIn('PE 2 条', body)
        self.assertIn('测试股', body)

    def test_summarize_since_queries(self):
        captured = []

        def fake_query(query, params=None):
            captured.append((query, params))
            return [{'total': 4, 'cnt': 4, 'alarm_type': 'price'}]

        with mock.patch.object(StockAlarm, 'execute_query', side_effect=fake_query):
            summary = StockAlarm.summarize_since(24)
        self.assertEqual(len(captured), 3)
        for query, params in captured:
            self.assertIn('DATE_SUB(NOW(), INTERVAL %s HOUR)', query)
            self.assertEqual(params, (24,))
        self.assertEqual(summary['total'], 4)

    def test_summarize_since_error_returns_none(self):
        with mock.patch.object(StockAlarm, 'execute_query',
                               side_effect=RuntimeError('db down')):
            self.assertIsNone(StockAlarm.summarize_since(24))

    def test_summarize_since_illegal_hours(self):
        captured = []
        with mock.patch.object(StockAlarm, 'execute_query',
                               side_effect=lambda q, p: captured.append(p) or []):
            StockAlarm.summarize_since('abc')
        self.assertEqual(captured[0], (24,))


class ProfileViewTest(unittest.TestCase):
    """`/profile` 的保存与校验（POST 用 mock 挡住真实写库）。"""

    def setUp(self):
        from app import app

        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'tester'

        self.user = FakeUser()
        patcher = mock.patch('views.auth.User.get_by_id', return_value=self.user)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.update = mock.patch('views.auth.User.update_profile', return_value=True)
        self.update_mock = self.update.start()
        self.addCleanup(self.update.stop)

        self.save_prefs = mock.patch.object(UserNotifyPref, 'save', return_value=True)
        self.save_mock = self.save_prefs.start()
        self.addCleanup(self.save_prefs.stop)

        patcher = mock.patch('models.account_settings.latest_account',
                             return_value={'email': 'me@x.com', 'bench_code': 'SH000300'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, **overrides):
        data = {
            'username': 'tester',
            'email': 'me@example.com',
            'phone': '13800000000',
            'bench_code': 'SZ399006',
            'notify_price': '1',
            'notify_indicator': '1',
        }
        data.update(overrides)
        return self.client.post('/profile', data=data)

    def test_profile_post_persists(self):
        response = self._post()
        self.assertEqual(response.status_code, 302)
        self.update_mock.assert_called_once_with(
            1, username='tester', email='me@example.com',
            phone='13800000000', bench_code='SZ399006')
        self.assertEqual(self.save_mock.call_args[0][0], 1)
        self.assertTrue(self.save_mock.call_args[1]['notify_price'])
        self.assertFalse(self.save_mock.call_args[1]['notify_daily'])  # 未勾选即关

    def test_rejects_empty_username(self):
        self._post(username='')
        self.update_mock.assert_not_called()
        self.save_mock.assert_not_called()

    def test_rejects_duplicate_username(self):
        other = FakeUser(user_id=2, username='other')
        with mock.patch('views.auth.User.get_by_username', return_value=other):
            self._post(username='other')
        self.update_mock.assert_not_called()

    def test_allows_keeping_own_username(self):
        with mock.patch('views.auth.User.get_by_username', return_value=FakeUser()):
            self._post(username='tester')
        self.update_mock.assert_called_once()

    def test_rejects_bad_email(self):
        self._post(email='not-an-email')
        self.update_mock.assert_not_called()

    def test_rejects_unknown_bench(self):
        self._post(bench_code='NASDAQ')
        self.update_mock.assert_not_called()

    def test_save_failure_flashes_error(self):
        self.update_mock.return_value = False
        response = self._post()
        self.assertEqual(response.status_code, 200)


class AccountPageRenderTest(unittest.TestCase):
    """账户页渲染契约：四个基准、四个开关、收件人与发信同源。"""

    def setUp(self):
        from app import app

        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'tester'

        patcher = mock.patch('views.auth.User.get_by_id', return_value=FakeUser())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _body(self):
        """渲染时把偏好固定住，避免用例依赖库里是否已有偏好行。"""
        with mock.patch('models.account_settings.latest_account',
                        return_value={'email': 'me@x.com', 'bench_code': 'SZ399006'}):
            with mock.patch.object(UserNotifyPref, 'effective',
                                   return_value=_prefs(notify_daily=1)):
                with mock.patch('config.get_alarm_recipients', return_value=['ops@x.com']):
                    return self.client.get('/profile').get_data(as_text=True)

    def test_four_benchmark_options(self):
        body = self._body()
        for code in ('SH000001', 'SH000300', 'SZ399006', 'HKHSI'):
            self.assertIn('value="%s"' % code, body)

    def test_notify_toggles_rendered(self):
        body = self._body()
        for field in NOTIFY_FIELDS:
            self.assertIn('name="%s"' % field, body)
            self.assertIn('type="checkbox"', body)

    def test_toggle_state_follows_prefs(self):
        """开关的勾选与"开/关"视觉态必须来自同一份偏好，不能各写一套。"""
        body = self._body()   # _prefs(notify_daily=1)：默认三类开 + 汇总开
        for field in NOTIFY_FIELDS:
            self.assertRegex(body, r'name="%s"[^>]*checked' % field)
        self.assertEqual(body.count('class="status on"'), len(NOTIFY_FIELDS))

    def test_recipient_shown_matches_sender(self):
        """页面显示的地址必须与发信解析结果一致（同一函数，两种用法）。"""
        with mock.patch('models.account_settings.latest_account',
                        return_value={'email': 'me@x.com', 'bench_code': 'SZ399006'}):
            with mock.patch('config.get_alarm_recipients', return_value=['ops@x.com']):
                body = self.client.get('/profile').get_data(as_text=True)
                recipients = resolve_alarm_recipients()['recipients']
        self.assertEqual(recipients, ['ops@x.com'])
        self.assertIn('ops@x.com', body)

    def test_logout_entry_in_side_nav(self):
        body = self._body()
        self.assertIn('退出登录', body)
        self.assertIn('href="/logout"', body)


if __name__ == '__main__':
    unittest.main()
