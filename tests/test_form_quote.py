"""
订单编辑页「实时行情」取数的回归用例。

对应变更：[2026-10-21 修复订单编辑页「实时行情」现价不准](../spec/changes/2026-10-21-order-form-current-price.md)

背景：`stock_master` 表**没有 current_price 列**，现价由监控线程写入 `stock_warehouse`。
编辑页曾误用 `stock.current_price`（恒为空）→ 现价显示 0.00、阶梯百分比算不出。

锁三件事：

1. 现价取自 warehouse 且等于库内真实值（真实库查询，不用 mock）；
2. 阶梯 `data-current` 有值（否则前端"距现价百分比"失效）；
3. POST 校验失败重渲染时仍带 pe_record——隐藏字段为空会把已有备注清空。
"""
import re
import sys
import unittest

sys.path.insert(0, '.')

from app import app
from models.stock_warehouse import StockWarehouse


def _body(client, path):
    return client.get(path).get_data(as_text=True)


def _field(record, name):
    """取字段值：兼容两种返回类型。

    注意两个模型的实现不一致——`StockMaster.get_by_id` 返回 **dict 行**，
    而 `StockWarehouse / StockPe / StockPb.get_by_stock_master_id` 返回**模型对象**。
    """
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def _rail_value(body, label):
    """取出 rail 里某行的值：<span>label</span><b ...>值</b>。"""
    row = re.search(r'<span>' + label + r'</span>.*?<b[^>]*>(.*?)</b>', body, re.S)
    return re.sub(r'<[^>]+>', '', row.group(1)).strip() if row else None


class EditQuoteTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """挑一个库内确实有现价的订单（现价在 warehouse 表）。"""
        cls.stock_id = None
        for sid in range(1, 100):
            w = StockWarehouse.get_by_stock_master_id(sid)
            if w and _field(w, 'current_price'):
                cls.stock_id = sid
                cls.price = float(_field(w, 'current_price'))
                break
        if cls.stock_id is None:
            raise unittest.SkipTest('库中没有带现价的订单')

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'

    def test_rail_price_matches_warehouse(self):
        """现价必须等于 warehouse 当前值，且不能是 0.00。"""
        body = _body(self.client, '/stock/edit/%d' % self.stock_id)
        value = _rail_value(body, '现价')
        self.assertIsNotNone(value, 'rail 里没有「现价」行')
        self.assertAlmostEqual(float(value.replace(',', '')), self.price, places=2)
        self.assertNotEqual(value, '0.00')

    def test_rail_shows_quote_time(self):
        """暂停监控的订单不再采集，只给数字会让人以为是实时的。"""
        body = _body(self.client, '/stock/edit/%d' % self.stock_id)
        self.assertIn('行情时间', body)
        self.assertIsNotNone(_rail_value(body, '行情时间'))

    def test_ladder_has_current_price(self):
        body = _body(self.client, '/stock/edit/%d' % self.stock_id)
        current = re.search(r'class="ladder" data-current="([^"]*)"', body)
        self.assertIsNotNone(current, '阶梯缺少 data-current')
        self.assertNotEqual(current.group(1).strip(), '', 'data-current 为空，百分比算不出来')
        self.assertAlmostEqual(float(current.group(1)), self.price, places=2)


class EditPostFailureKeepsMemoTest(unittest.TestCase):
    """POST 校验失败重渲染：隐藏字段必须保留原值，否则再提交会清空备注。"""

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'

    def test_missing_name_rerender_keeps_memo(self):
        """找一个 pe_memo 非空的订单；找不到就跳过（此时无数据可丢）。"""
        from models.stock_pe import StockPe

        target = None
        for sid in range(1, 100):
            pe = StockPe.get_by_stock_master_id(sid)
            if pe and (_field(pe, 'memo') or '').strip():
                target, memo = sid, _field(pe, 'memo').strip()
                break
        if target is None:
            raise unittest.SkipTest('库中没有 pe_memo 非空的订单')

        resp = self.client.post('/stock/edit/%d' % target,
                                data={'stock_name': '', 'stock_code': 'x'})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        hidden = re.search(r'<input type="hidden" name="pe_memo" value="([^"]*)"', body)
        self.assertIsNotNone(hidden, '重渲染页面缺少 pe_memo 隐藏字段')
        self.assertEqual(hidden.group(1).strip(), memo, '重渲染丢失了 PE 备注原值')


if __name__ == '__main__':
    unittest.main()
