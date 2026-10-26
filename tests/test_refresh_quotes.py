"""
列表页「刷新行情」按钮的回归用例。

对应变更：[2026-10-22 订单列表新增「刷新行情」按钮](../spec/changes/2026-10-22-refresh-quotes-button.md)

**用户纠正过的两点**（首版实现方向错了，这里锁住正确行为）：

1. **只刷新当前页**，不是全表活跃订单；
2. **不请求雪球 API**——监控线程在后台持续采集落库，页面刷新只是重新读库。
   一次点击打几十次外部请求既慢又容易触发限流。

用例据此验证：接口纯查库、按传入 ids 取数、数值与直接查询一致、不触发任何取数调用。
"""
import sys
import unittest
from unittest import mock

sys.path.insert(0, '.')

from app import app
from models.stock_master import StockMaster
from models.stock_monitor import monitor


def _field(record, name):
    """兼容两种返回类型（dict 行 / 模型对象）。"""
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


class RefreshScopedToPageTest(unittest.TestCase):
    """刷新范围 = 当前页 ids，且只查库。"""

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'
        # 取两个真实订单 id
        rows = StockMaster.get_all_with_details(page=1, per_page=5)[0]
        self.rows = rows
        self.ids = [r['id'] for r in rows[:2]]

    def test_returns_only_requested_ids(self):
        resp = self.client.post('/stock/refresh_quotes', json={'ids': self.ids})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(sorted(q['id'] for q in data['quotes']), sorted(self.ids))

    def test_matches_database_values(self):
        """返回的就是库里的值——不是重新采集，也不是缓存。"""
        resp = self.client.post('/stock/refresh_quotes', json={'ids': self.ids})
        for q in resp.get_json()['quotes']:
            row = [r for r in self.rows if r['id'] == q['id']][0]
            # 库里是 DECIMAL，接口转成了 float——比数值不比类型
            self.assertAlmostEqual(q['current_price'],
                                   float(row['current_price']) if row['current_price'] else 0.0)
            self.assertAlmostEqual(q['current_pe'],
                                   float(row['current_pe']) if row['current_pe'] else 0.0)

    def test_does_not_call_xueqiu(self):
        """最关键的契约：刷新不能打雪球 API。"""
        with mock.patch.object(monitor, 'get_stock_data') as fetch:
            resp = self.client.post('/stock/refresh_quotes', json={'ids': self.ids})
        self.assertEqual(resp.status_code, 200)
        fetch.assert_not_called()

    def test_no_ids_never_refreshes_whole_table(self):
        """不传 ids 时只能拿到空结果，绝不能退化成"刷新全表"。"""
        with mock.patch('models.stock_master.StockMaster.get_quotes_by_ids',
                        return_value=[]) as query:
            resp = self.client.post('/stock/refresh_quotes', json={})
        self.assertEqual([], query.call_args[0][0], '空请求也必须只查空 id 集合')
        self.assertEqual(resp.get_json()['quotes'], [])

    def test_ids_capped(self):
        """防止构造超大请求把整表拉出来。"""
        with mock.patch('models.stock_master.StockMaster.get_quotes_by_ids',
                        return_value=[]) as query:
            self.client.post('/stock/refresh_quotes', json={'ids': list(range(1, 500))})
        self.assertLessEqual(len(query.call_args[0][0]), 200)

    def test_requires_login(self):
        resp = app.test_client().post('/stock/refresh_quotes', json={'ids': self.ids})
        self.assertEqual(resp.status_code, 302)


class ModelQueryTest(unittest.TestCase):
    """模型层：只查库、参数化、失败降级。"""

    def test_empty_ids(self):
        self.assertEqual(StockMaster.get_quotes_by_ids([]), [])

    def test_real_query_shape(self):
        rows = StockMaster.get_all_with_details(page=1, per_page=3)[0]
        result = StockMaster.get_quotes_by_ids([rows[0]['id']])
        self.assertEqual(len(result), 1)
        for key in ('id', 'current_price', 'current_pe', 'current_pb'):
            self.assertIn(key, result[0])


class RefreshButtonRenderTest(unittest.TestCase):
    """按钮在「添加订单」左边，结构与行标识齐全。"""

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'
        self.body = self.client.get('/stock/list').get_data(as_text=True)

    def test_button_before_create_link(self):
        """只在 page-actions 区域内比较——侧栏里也有「添加订单」链接。"""
        import re
        block = re.search(r'<div class="page-actions">(.*?)</div>', self.body, re.S)
        self.assertIsNotNone(block, '缺少 page-actions 操作区')
        inner = block.group(1)
        self.assertLess(inner.find('data-refresh-quotes'), inner.find('/stock/create'))

    def test_button_contract(self):
        self.assertIn('btn btn-ghost', self.body)
        self.assertIn('#i-refresh', self.body)
        self.assertIn('data-refresh-url="/stock/refresh_quotes"', self.body)
        self.assertIn('type="button"', self.body)  # 不是 submit，避免误提交表单

    def test_rows_carry_id_and_cells(self):
        """前端靠 data-id 收集当前页、靠 data-col 定位单元格。"""
        self.assertIn('data-id=', self.body)
        self.assertIn('data-col="price"', self.body)
        self.assertIn('data-col="pe"', self.body)
        self.assertIn('data-col="pb"', self.body)


if __name__ == '__main__':
    unittest.main()
