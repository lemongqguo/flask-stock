"""
多用户数据隔离的回归用例（2026-10-26）。

对应变更：[spec/changes/2026-10-26-multi-user-ownership.md](../spec/changes/2026-10-26-multi-user-ownership.md)

锁定四件事：

1. **可见性**：普通用户只见自己名下，admin 见全量；
2. **写权限**：编辑/删除/切换状态/改阈值/AI 分析，改别人的订单一律被拦，且**不落库**；
3. **归属写入**：新建订单的 `user_id` 取当前登录用户，**不接受客户端传值**；
4. **配套去重**：同一代码被多人持有时，监控一轮只取一次外部行情。
"""
import sys
import unittest
from unittest import mock

sys.path.insert(0, '.')

from flask import session

from app import app
from models.account_settings import prefs_for_user, recipients_for_user
from models.stock_alarm import StockAlarm
from models.stock_master import StockMaster
from models.stock_monitor import StockMonitor
from models.user import User
from utils.access import (
    NO_ACCESS,
    ROLE_ADMIN,
    ROLE_USER,
    build_owner_where,
    can_manage,
    is_admin,
    owner_scope,
)


class _FakeConfig:
    """监控线程构造所需的最小配置（参照 tests/test_monitor_service.py）。"""

    ALARM_COOLDOWN_SECONDS = 14400
    XUEQIU_NOTICE_INTERVAL = 3600
    IND_COOLDOWN_HOURS = 24
    ALARM_MAIL_ENABLED = False


# ----------------------------------------------------------------------
# 1. 判定入口本身
# ----------------------------------------------------------------------
class AccessUtilsTest(unittest.TestCase):

    def _context(self, user_id=1, role=ROLE_USER):
        ctx = app.test_request_context()
        return ctx

    def test_owner_scope_for_normal_user(self):
        with app.test_request_context():
            session['user_id'] = 7
            session['role'] = ROLE_USER
            self.assertEqual(owner_scope(), 7)
            self.assertFalse(is_admin())

    def test_owner_scope_for_admin_is_unlimited(self):
        with app.test_request_context():
            session['user_id'] = 7
            session['role'] = ROLE_ADMIN
            self.assertIsNone(owner_scope())
            self.assertTrue(is_admin())

    def test_owner_scope_without_session_is_no_access(self):
        """会话不完整必须查不到任何数据，而不是退化成"全量"。"""
        with app.test_request_context():
            self.assertEqual(owner_scope(), NO_ACCESS)
            self.assertFalse(is_admin())

    def test_build_owner_where(self):
        self.assertEqual(build_owner_where(None), ('', []))
        self.assertEqual(build_owner_where(3), ('`sm`.user_id = %s', [3]))
        self.assertEqual(build_owner_where(3, alias='sa'), ('`sa`.user_id = %s', [3]))
        # 哨兵：查不到任何行
        self.assertEqual(build_owner_where(NO_ACCESS), ('1 = 0', []))

    def test_build_owner_where_rejects_bad_alias(self):
        sql, _ = build_owner_where(1, alias='sm; DROP TABLE users')
        self.assertEqual(sql, '`sm`.user_id = %s')

    def test_can_manage(self):
        stock = {'id': 1, 'user_id': 1}
        with app.test_request_context():
            session['user_id'] = 1
            session['role'] = ROLE_USER
            self.assertTrue(can_manage(stock))

            # 别人的订单
            session['user_id'] = 2
            self.assertFalse(can_manage({'id': 1, 'user_id': 1}))

            # 归属缺失 / 行不存在：失败关闭
            self.assertFalse(can_manage({'id': 1}))
            self.assertFalse(can_manage(None))

            # 管理员可视即可管
            session['role'] = ROLE_ADMIN
            self.assertTrue(can_manage({'id': 1, 'user_id': 1}))


# ----------------------------------------------------------------------
# 2. 可见性（列表页 / 统计 / 搜索）
# ----------------------------------------------------------------------
class VisibilityTest(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        self._login()

    def _login(self, user_id=1, role=ROLE_USER):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = 'u%s' % user_id
            sess['role'] = role

    def _get_list(self):
        with mock.patch('views.stock_orders.StockMaster.get_all_with_details',
                        return_value=([], 0)) as listing, \
                mock.patch('views.stock_orders.StockKline.get_low_52w_batch',
                           return_value={}), \
                mock.patch('views.stock_orders.StockKline.get_latest_signal',
                           return_value='normal'), \
                mock.patch('views.stock_orders.StockMaster.count_by_status',
                           return_value=0), \
                mock.patch('views.stock_orders.StockMaster.count_alarm_active',
                           return_value=0):
            resp = self.client.get('/stock/list')
        return resp, listing

    def test_list_is_scoped_to_owner(self):
        _, listing = self._get_list()
        self.assertEqual(listing.call_args.kwargs['owner_user_id'], 1)

    def test_admin_list_is_unlimited(self):
        self._login(user_id=9, role=ROLE_ADMIN)
        _, listing = self._get_list()
        self.assertIsNone(listing.call_args.kwargs['owner_user_id'])

    def test_page_stats_use_same_scope(self):
        self._login(user_id=4)
        with mock.patch('views.stock_orders.StockMaster.get_all_with_details',
                        return_value=([], 0)), \
                mock.patch('views.stock_orders.StockKline.get_low_52w_batch',
                           return_value={}), \
                mock.patch('views.stock_orders.StockKline.get_latest_signal',
                           return_value='normal'), \
                mock.patch('views.stock_orders.StockMaster.count_by_status',
                           return_value=0) as active_counter, \
                mock.patch('views.stock_orders.StockMaster.count_alarm_active',
                           return_value=0) as alarm_counter:
            self.client.get('/stock/list')
        self.assertEqual(active_counter.call_args.kwargs['owner_user_id'], 4)
        self.assertEqual(alarm_counter.call_args.kwargs['owner_user_id'], 4)

    def test_indicator_page_is_scoped(self):
        with mock.patch('views.stock_orders.StockMaster.get_all',
                        return_value=([], 0)) as listing, \
                mock.patch('views.stock_orders.StockIndicator.get_latest_batch',
                           return_value={}), \
                mock.patch('views.stock_orders.StockIndicatorConfig.get_map',
                           return_value={}):
            self.client.get('/stock/indicator')
        self.assertEqual(listing.call_args.kwargs['owner_user_id'], 1)

    def test_alarm_history_is_scoped(self):
        with mock.patch('views.stock_orders.StockAlarm.get_all_alarms',
                        return_value=([], 0)) as listing, \
                mock.patch('views.stock_orders.StockAlarm.get_stats',
                           return_value={}) as stats:
            self.client.get('/stock/recent_alarms')
        self.assertEqual(listing.call_args.kwargs['owner_user_id'], 1)
        self.assertEqual(stats.call_args.kwargs['owner_user_id'], 1)


# ----------------------------------------------------------------------
# 3. 写权限（越权必须被拦且不落库）
# ----------------------------------------------------------------------
class WriteGuardTest(unittest.TestCase):

    OTHER = {'id': 5, 'user_id': 2, 'status': 'active'}

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'alice'
            sess['role'] = ROLE_USER

    def _patch_others_stock(self):
        return mock.patch('views.stock_orders.StockMaster.get_by_id',
                          return_value=dict(self.OTHER))

    def test_cannot_edit_others_order(self):
        with self._patch_others_stock(), \
                mock.patch('views.stock_orders.StockMaster.update') as updater:
            resp = self.client.post('/stock/edit/5', data={
                'stock_name': '别人的票', 'stock_code': 'SZ000001'})
        self.assertFalse(updater.called)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/stock/list', resp.headers['Location'])

    def test_cannot_delete_others_order(self):
        with self._patch_others_stock(), \
                mock.patch('views.stock_orders.StockMaster.delete') as deleter:
            self.client.post('/stock/delete/5')
        self.assertFalse(deleter.called)

    def test_cannot_toggle_others_order(self):
        with self._patch_others_stock(), \
                mock.patch('views.stock_orders.StockMaster.update') as updater:
            self.client.post('/stock/toggle_status/5')
        self.assertFalse(updater.called)

    def test_cannot_change_others_thresholds(self):
        with self._patch_others_stock(), \
                mock.patch('views.stock_orders.StockWarehouse.create') as creator, \
                mock.patch('views.stock_orders.StockWarehouse.update_by_stock_master_id') as updater:
            self.client.post('/stock/alarm_settings',
                             data={'stock_id': 5, 'alarm_type': 'warehouse',
                                   'sell_rate': '99'})
        self.assertFalse(creator.called)
        self.assertFalse(updater.called)

    def test_alarm_settings_get_hides_others_stock(self):
        with self._patch_others_stock():
            body = self.client.get('/stock/alarm_settings?stock_id=5').get_data(as_text=True)
        self.assertNotIn('stock_id="5"', body)

    def test_kline_api_forbidden_for_others(self):
        with mock.patch('views.stock_orders.StockMaster.get_by_id',
                        return_value=dict(self.OTHER)), \
                mock.patch('database.get_connection') as conn:
            resp = self.client.get('/stock/api/kline/5')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(conn.called)

    def test_kline_api_allowed_for_owner(self):
        cursor = mock.MagicMock()
        cursor.fetchall.return_value = []
        connection = mock.MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor

        with mock.patch('views.stock_orders.StockMaster.get_by_id',
                        return_value={'id': 5, 'user_id': 1}), \
                mock.patch('database.get_connection', return_value=connection):
            resp = self.client.get('/stock/api/kline/5')
        self.assertEqual(resp.status_code, 200)

    def test_refresh_quotes_carries_scope(self):
        with mock.patch('views.stock_orders.StockMaster.get_quotes_by_ids',
                        return_value=[]) as quotes:
            self.client.post('/stock/refresh_quotes', json={'ids': [1, 5]})
        self.assertEqual(quotes.call_args.kwargs['owner_user_id'], 1)


# ----------------------------------------------------------------------
# 4. 归属写入
# ----------------------------------------------------------------------
class CreationOwnershipTest(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'alice'
            sess['role'] = ROLE_USER

    def _post_create(self, extra=None):
        data = {'stock_name': '测试股', 'stock_code': 'SZ002027'}
        data.update(extra or {})
        with mock.patch('views.stock_orders.StockMaster.get_by_stock_code',
                        return_value=None) as lookup, \
                mock.patch('views.stock_orders.StockMaster.create') as creator:
            self.client.post('/stock/create', data=data)
        return lookup, creator

    def test_new_order_belongs_to_current_user(self):
        _, creator = self._post_create()
        self.assertEqual(creator.call_args.kwargs['user_id'], 1)

    def test_client_cannot_set_owner(self):
        """表单里塞 user_id=999 无效：归属只认 session。"""
        _, creator = self._post_create({'user_id': 999})
        self.assertEqual(creator.call_args.kwargs['user_id'], 1)

    def test_duplicate_check_is_scoped_to_owner(self):
        """同一代码允许被别人持有，查重只能查自己名下。"""
        lookup, _ = self._post_create()
        self.assertEqual(lookup.call_args.kwargs['owner_user_id'], 1)


# ----------------------------------------------------------------------
# 5. 模型层：SQL 真的带上了归属条件
# ----------------------------------------------------------------------
class ModelScopeSqlTest(unittest.TestCase):

    def test_get_all_with_details_filters_owner(self):
        with mock.patch.object(StockMaster, 'execute_query', return_value=[]) as query:
            StockMaster.get_all_with_details(page=1, per_page=10, owner_user_id=3)
        sql, params = query.call_args_list[0][0]
        self.assertIn('user_id', sql)
        self.assertIn(3, list(params))

    def test_get_all_with_details_without_owner_has_no_filter(self):
        with mock.patch.object(StockMaster, 'execute_query', return_value=[]) as query:
            StockMaster.get_all_with_details(page=1, per_page=10)
        sql, _ = query.call_args_list[0][0]
        self.assertNotIn('sm`.user_id', sql)

    def test_count_by_status_filters_owner(self):
        with mock.patch.object(StockMaster, 'execute_query',
                               return_value=[{'count': 0}]) as query:
            StockMaster.count_by_status('active', owner_user_id=8)
        sql, params = query.call_args[0]
        self.assertIn('user_id', sql)
        self.assertIn(8, list(params))

    def test_count_alarm_active_filters_owner(self):
        with mock.patch.object(StockMaster, 'execute_query',
                               return_value=[{'count': 0}]) as query:
            StockMaster.count_alarm_active(owner_user_id=8)
        sql, params = query.call_args[0]
        self.assertIn('user_id', sql)
        self.assertIn(8, list(params))

    def test_get_quotes_by_ids_filters_owner(self):
        with mock.patch.object(StockMaster, 'execute_query', return_value=[]) as query:
            StockMaster.get_quotes_by_ids([1, 2], owner_user_id=6)
        sql, params = query.call_args[0]
        self.assertIn('user_id', sql)
        self.assertIn(6, list(params))

    def test_get_by_stock_code_filters_owner(self):
        """同代码可跨用户重复，查重必须限定归属才能拿到"自己那条"。"""
        with mock.patch.object(StockMaster, 'execute_query', return_value=[]) as query:
            StockMaster.get_by_stock_code('SZ002027', owner_user_id=2)
        sql, params = query.call_args[0]
        self.assertIn('user_id', sql)
        self.assertIn(2, list(params))

    def test_get_active_stocks_is_not_filtered(self):
        """监控线程必须照看所有人的订单，这里**不能**加归属过滤。"""
        with mock.patch.object(StockMaster, 'execute_query', return_value=[]) as query:
            StockMaster.get_active_stocks(limit=10)
        sql, _ = query.call_args[0]
        self.assertNotIn('user_id', sql)

    def test_alarm_list_filters_owner(self):
        with mock.patch.object(StockAlarm, 'execute_query', return_value=[]) as query:
            StockAlarm.get_all_alarms(owner_user_id=4)
        sql, params = query.call_args_list[0][0]
        self.assertIn('user_id', sql)
        self.assertIn(4, list(params))

    def test_alarm_stats_filters_owner(self):
        with mock.patch.object(StockAlarm, 'execute_query',
                               return_value=[{'total': 0}]) as query:
            StockAlarm.get_stats(owner_user_id=4)
        sql, params = query.call_args[0]
        self.assertIn('JOIN stock_master', sql)
        self.assertIn(4, list(params))

    def test_nav_badge_filters_owner(self):
        with mock.patch.object(StockAlarm, 'execute_query',
                               return_value=[{'total': 0}]) as query:
            StockAlarm.count_recent_indicator(24, owner_user_id=4)
        sql, params = query.call_args[0]
        self.assertIn('JOIN stock_master', sql)
        self.assertIn(4, list(params))


# ----------------------------------------------------------------------
# 6. AI 页：别人的标的既不展示也不分析
# ----------------------------------------------------------------------
class AiScopeTest(unittest.TestCase):

    def test_load_context_rejects_others_stock(self):
        from views.ai_analysis import _load_context

        with mock.patch('views.ai_analysis.StockMaster.get_by_id',
                        return_value={'id': 5, 'user_id': 2}):
            with app.test_request_context():
                session['user_id'] = 1
                session['role'] = ROLE_USER
                stock, context = _load_context(5)
        self.assertIsNone(stock)
        self.assertIsNone(context)

    def test_load_context_allows_owner(self):
        from views.ai_analysis import _load_context

        with mock.patch('views.ai_analysis.StockMaster.get_by_id',
                        return_value={'id': 5, 'user_id': 1}), \
                mock.patch('views.ai_analysis.StockWarehouse.get_by_stock_master_id',
                           return_value=None), \
                mock.patch('views.ai_analysis.StockIndicator.get_latest',
                           return_value=None), \
                mock.patch('views.ai_analysis.StockKline.get_recent_closes',
                           return_value=[]):
            with app.test_request_context():
                session['user_id'] = 1
                session['role'] = ROLE_USER
                stock, context = _load_context(5)
        self.assertIsNotNone(stock)
        self.assertIsNotNone(context)

    def test_search_and_total_are_scoped(self):
        app.config['TESTING'] = True
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 3
            sess['username'] = 'carol'
            sess['role'] = ROLE_USER

        with mock.patch('views.ai_analysis.StockMaster.get_all',
                        return_value=([], 0)) as listing:
            client.get('/stock/ai/api/search?q=SZ')
        self.assertEqual(listing.call_args.kwargs['owner_user_id'], 3)


# ----------------------------------------------------------------------
# 7. 监控配套：同代码只取一次 + 收件人按归属人
# ----------------------------------------------------------------------
class MonitorDedupeTest(unittest.TestCase):

    def setUp(self):
        self.monitor = StockMonitor(config=_FakeConfig())
        self.monitor._reset_round_cache()

    def test_same_code_fetched_once(self):
        calls = []

        def producer():
            calls.append('fetched')
            return {'current': 10.0}

        first = self.monitor._shared_result('quote', 'SZ002027', producer)
        second = self.monitor._shared_result('quote', 'SZ002027', producer)
        self.assertEqual(calls, ['fetched'])
        self.assertEqual(first, second)

    def test_different_codes_not_shared(self):
        calls = []

        def producer(code):
            return lambda: calls.append(code) or {'current': 1.0}

        self.monitor._shared_result('quote', 'SZ002027', producer('SZ002027'))
        self.monitor._shared_result('quote', 'SH600000', producer('SH600000'))
        self.assertEqual(calls, ['SZ002027', 'SH600000'])

    def test_failure_is_not_cached(self):
        """失败不缓存：否则一次超时会让同一代码的所有订单整轮拿不到行情。"""
        calls = []

        def producer():
            calls.append(1)
            return None

        self.assertIsNone(self.monitor._shared_result('quote', 'SZ002027', producer))
        self.assertIsNone(self.monitor._shared_result('quote', 'SZ002027', producer))
        self.assertEqual(len(calls), 2)

    def test_cache_cleared_each_round(self):
        calls = []

        def producer():
            calls.append(1)
            return {'current': 1.0}

        self.monitor._shared_result('quote', 'SZ002027', producer)
        self.monitor._reset_round_cache()
        self.monitor._shared_result('quote', 'SZ002027', producer)
        self.assertEqual(len(calls), 2)

    def test_check_and_alert_shares_quote_between_owners(self):
        """两人各持有一条同代码订单：本轮只对雪球请求一次。"""
        self.monitor._reset_round_cache()
        stock_a = StockMaster(id=1, stock_name='A', stock_code='SZ002027', user_id=1)
        stock_b = StockMaster(id=2, stock_name='B', stock_code='SZ002027', user_id=2)

        with mock.patch.object(self.monitor, 'get_stock_data',
                               return_value={'current': 10.0}) as fetch, \
                mock.patch.object(self.monitor, '_persist_quote', return_value=None), \
                mock.patch.object(self.monitor, '_sync_kline'), \
                mock.patch.object(self.monitor, '_check_indicators'), \
                mock.patch.object(self.monitor, '_check_ratio_alarm'):
            self.monitor.check_and_alert(stock_a)
            self.monitor.check_and_alert(stock_b)

        self.assertEqual(fetch.call_count, 1)


class OwnerRecipientTest(unittest.TestCase):

    def test_uses_owner_email_first(self):
        with mock.patch('models.account_settings.UserNotifyPref.execute_query',
                        return_value=[{'email': 'owner@example.com'}]):
            result = recipients_for_user(5)
        self.assertEqual(result['recipients'], ['owner@example.com'])
        self.assertEqual(result['source'], 'owner_email')

    def test_falls_back_to_env_when_owner_has_no_email(self):
        with mock.patch('models.account_settings.UserNotifyPref.execute_query',
                        return_value=[{'email': ''}]), \
                mock.patch('config.get_alarm_recipients',
                           return_value=['ops@example.com']):
            result = recipients_for_user(5)
        self.assertEqual(result['recipients'], ['ops@example.com'])
        self.assertEqual(result['source'], 'env')

    def test_none_owner_keeps_global_behaviour(self):
        with mock.patch('models.account_settings.resolve_alarm_recipients',
                        return_value={'recipients': ['old@example.com'],
                                      'source': 'env', 'email': ''}):
            result = recipients_for_user(None)
        self.assertEqual(result['recipients'], ['old@example.com'])

    def test_prefs_for_user_reads_own_row(self):
        row = {'notify_price': 0, 'notify_valuation': 1,
               'notify_indicator': 0, 'notify_daily': 1}
        with mock.patch('models.account_settings.UserNotifyPref.get',
                        return_value=row):
            prefs = prefs_for_user(4)
        self.assertEqual(prefs['notify_price'], 0)
        self.assertEqual(prefs['notify_daily'], 1)

    def test_prefs_for_unknown_user_defaults(self):
        with mock.patch('models.account_settings.UserNotifyPref.get',
                        return_value=None):
            prefs = prefs_for_user(4)
        self.assertEqual(prefs['notify_price'], 1)
        self.assertEqual(prefs['notify_daily'], 0)


# ----------------------------------------------------------------------
# 8. 角色
# ----------------------------------------------------------------------
class UserRoleTest(unittest.TestCase):

    def _create(self, user_count):
        with mock.patch.object(User, 'count_users', return_value=user_count), \
                mock.patch.object(User, 'get_by_username', return_value=None), \
                mock.patch.object(User, 'get_user_id_by_username', return_value=1), \
                mock.patch.object(User, 'execute_update', return_value=1):
            return User.create('someone', 'secret123')

    def test_first_user_becomes_admin(self):
        """全库第一个用户必须是管理员，否则没人能看到全部订单。"""
        self.assertEqual(self._create(0).role, ROLE_ADMIN)

    def test_later_users_are_normal(self):
        self.assertEqual(self._create(1).role, ROLE_USER)

    def test_set_role_rejects_unknown_value(self):
        self.assertFalse(User.set_role(1, 'superuser'))


if __name__ == '__main__':
    unittest.main()
