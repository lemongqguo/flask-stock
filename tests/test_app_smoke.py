"""
应用装配冒烟测试（D-05 / D-11）。

验证：蓝图注册齐全、关键路由存在、启动期数据库不可用不会让进程崩溃。
不连接真实数据库。
"""
import importlib
import sys
import unittest
from unittest import mock

import database


def _import_app_without_db():
    """在数据库不可用的前提下导入 app 模块。"""
    if 'app' in sys.modules:
        return sys.modules['app']
    with mock.patch.object(database, 'get_pool', side_effect=RuntimeError('no database')):
        return importlib.import_module('app')


class AppSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_module = _import_app_without_db()
        cls.app = cls.app_module.app
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

    def _login(self, user_id=1, username='tester'):
        """在测试客户端上模拟已登录状态（不访问数据库）。"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _ensure_anonymous(self):
        """清除客户端会话，避免用例之间相互污染。"""
        with self.client.session_transaction() as sess:
            sess.pop('user_id', None)
            sess.pop('username', None)

    def test_blueprints_registered(self):
        self.assertIn('auth', self.app.blueprints)
        self.assertIn('stock', self.app.blueprints)

    def test_auth_routes_exist(self):
        rules = {rule.rule for rule in self.app.url_map.iter_rules()}
        for path in ('/login', '/register', '/logout', '/profile', '/change_password'):
            self.assertIn(path, rules)

    def test_stock_routes_exist(self):
        rules = {rule.rule for rule in self.app.url_map.iter_rules()}
        for path in (
            '/stock/list', '/stock/create', '/stock/edit/<int:id>',
            '/stock/delete/<int:id>', '/stock/alarm_settings',
            '/stock/recent_alarms', '/stock/api/kline/<int:stock_id>',
        ):
            self.assertIn(path, rules)

    def test_error_handlers_registered(self):
        # 应用级错误处理器挂在 error_handler_spec[None] 下，键为状态码
        handlers = self.app.error_handler_spec[None]
        for code in (403, 404, 500):
            self.assertIn(code, handlers)

    def test_unauthenticated_request_redirects_to_login(self):
        self._ensure_anonymous()
        resp = self.client.get('/stock/list')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    def test_public_pages_render(self):
        self._ensure_anonymous()
        for path in ('/login', '/register'):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, path)

    def test_unknown_route_redirects_when_anonymous(self):
        """登录拦截先于路由分派，匿名访问未知路径也只会被导向登录页（不泄露路由是否存在）。"""
        self._ensure_anonymous()
        resp = self.client.get('/definitely-not-a-route')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    def test_404_page_for_logged_in_user(self):
        self._login()
        try:
            resp = self.client.get('/definitely-not-a-route')
            self.assertEqual(resp.status_code, 404)
        finally:
            self._ensure_anonymous()

    def test_no_debug_by_default(self):
        self.assertFalse(self.app.config['DEBUG'])

    def test_monitor_start_skipped_when_disabled(self):
        with mock.patch.object(self.app_module.Config, 'MONITOR_ENABLED', False):
            with mock.patch.object(self.app_module.monitor, 'start_monitoring') as start:
                self.assertFalse(self.app_module.start_monitoring_on_startup())
        start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
