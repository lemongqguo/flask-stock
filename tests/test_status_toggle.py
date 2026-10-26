"""
订单列表内联切换监控状态的回归用例。

对应变更：[2026-10-21 订单列表内联切换监控状态](../spec/changes/2026-10-21-order-status-toggle.md)

重点锁定两条容易退化的约定：

1. 目标状态由**服务端取反**得出，不接受客户端传值；
2. 跳转 `next` 必须是站内相对路径，否则回落列表首页（防开放重定向）。
"""
import sys
import unittest
from unittest import mock

sys.path.insert(0, '.')

from app import app


def _fake_stock(status):
    """必须返回 dict：StockMaster.get_by_id 的真实返回类型是 dict 行，
    不是模型对象。早期这里用 mock.Mock(status=...) ，属性访问在真实路径上会抛
    AttributeError（列表页点击开关 500），问题被 mock 掩盖了。"""
    return {'id': 1, 'status': status, 'user_id': 1}


class ToggleStatusTest(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'

    def _post(self, stock, next_url=None, order_id=1):
        data = {}
        if next_url is not None:
            data['next'] = next_url
        with mock.patch('views.stock_orders.StockMaster.get_by_id', return_value=stock), \
             mock.patch('views.stock_orders.StockMaster.update', return_value=True) as updater:
            resp = self.client.post('/stock/toggle_status/%d' % order_id, data=data)
        return resp, updater

    def test_active_flips_to_inactive(self):
        resp, updater = self._post(_fake_stock('active'))
        updater.assert_called_once_with(1, status='inactive')
        self.assertEqual(resp.status_code, 302)

    def test_inactive_flips_to_active(self):
        resp, updater = self._post(_fake_stock('inactive'))
        updater.assert_called_once_with(1, status='active')

    def test_client_cannot_force_status(self):
        """即使请求里塞了 status，也必须以库内当前值的取反结果为准。"""
        with mock.patch('views.stock_orders.StockMaster.get_by_id', return_value=_fake_stock('active')), \
             mock.patch('views.stock_orders.StockMaster.update', return_value=True) as updater:
            self.client.post('/stock/toggle_status/1', data={'status': 'active'})
        updater.assert_called_once_with(1, status='inactive')

    def test_missing_order_flashes_error(self):
        with mock.patch('views.stock_orders.StockMaster.get_by_id', return_value=None), \
             mock.patch('views.stock_orders.StockMaster.update') as updater:
            resp = self.client.post('/stock/toggle_status/999')
        self.assertFalse(updater.called)
        self.assertIn('/stock/list', resp.headers['Location'])

    def test_update_failure_flashes_error(self):
        with mock.patch('views.stock_orders.StockMaster.get_by_id', return_value=_fake_stock('active')), \
             mock.patch('views.stock_orders.StockMaster.update', side_effect=RuntimeError('db down')):
            resp = self.client.post('/stock/toggle_status/1')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/stock/list', resp.headers['Location'])

    def test_internal_next_preserved(self):
        resp, _ = self._post(_fake_stock('active'), next_url='/stock/list?page=2&search=a')
        self.assertEqual(resp.headers['Location'], '/stock/list?page=2&search=a')

    def test_external_next_rejected(self):
        """开放重定向防护：协议相对、绝对地址、反斜杠变体一律回落到列表首页。"""
        for bad in ('//evil.com/stock/list', 'http://evil.com/x', '/\\evil.com', 'https://evil.com'):
            resp, _ = self._post(_fake_stock('active'), next_url=bad)
            self.assertEqual(resp.headers['Location'], '/stock/list',
                             '非法 next 未被拦截: %s' % bad)

    def test_requires_login(self):
        with self.client.session_transaction() as sess:
            sess.clear()
        resp = self.client.post('/stock/toggle_status/1')
        self.assertIn(resp.status_code, (302, 401))
        if resp.status_code == 302:
            self.assertIn('login', resp.headers['Location'])


if __name__ == '__main__':
    unittest.main()
