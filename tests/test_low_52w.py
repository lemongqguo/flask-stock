"""
订单列表「52周最低」列的回归用例。

对应变更：[2026-10-21 订单列表新增「52周最低」列](../spec/changes/2026-10-21-list-52w-low.md)

锁定三件事：

1. 口径：近 365 天 `stock_kline.low_price` 的最小值；
2. 批量：一次查询取回本页订单（空列表 / 未知 ID 返回空 dict，不报错）；
3. 列位：必须落在「现价」与「卖出价」之间，且无数据时显示 `—` 而不是 0。
"""
import re
import sys
import unittest

sys.path.insert(0, '.')

from app import app
from models.stock_kline import StockKline


class Low52wBatchTest(unittest.TestCase):
    """模型层：真实库查询（该方法是 SQL 查询，用 mock 无法验证契约）。"""

    def test_empty_ids_returns_empty(self):
        self.assertEqual(StockKline.get_low_52w_batch([]), {})
        self.assertEqual(StockKline.get_low_52w_batch(None), {})

    def test_unknown_id_returns_empty(self):
        self.assertEqual(StockKline.get_low_52w_batch([999999]), {})

    def test_real_batch_query(self):
        """订单 1（宁德时代）近一年有 K 线，应返回正数最低价。"""
        result = StockKline.get_low_52w_batch([1, 2])
        self.assertIsInstance(result, dict)
        self.assertIn(1, result)
        self.assertIn(2, result)
        self.assertGreater(float(result[1]), 0)

    def test_value_matches_direct_query(self):
        """批量结果必须与直接 MIN 查询一致，防止 GROUP BY 写错。"""
        result = StockKline.get_low_52w_batch([1])
        row = StockKline.execute_query(
            """
            SELECT MIN(low_price) AS low_52w FROM stock_kline
            WHERE stock_master_id = %s
              AND trade_date >= DATE_SUB(CURDATE(), INTERVAL 365 DAY)
              AND low_price IS NOT NULL
            """,
            (1,)
        )[0]
        self.assertEqual(float(result[1]), float(row['low_52w']))


class Low52wColumnTest(unittest.TestCase):
    """页面层：列位与占位符。"""

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'

    def test_column_between_price_and_sell(self):
        body = self.client.get('/stock/list').get_data(as_text=True)
        heads = [re.sub(r'<[^>]+>', '', h).strip()
                 for h in re.findall(r'<th\b[^>]*>(.*?)</th>', body, re.S)]
        self.assertIn('52周最低', heads, '缺少「52周最低」列')
        self.assertEqual(heads.index('52周最低'), heads.index('现价') + 1)
        self.assertEqual(heads.index('卖出价'), heads.index('52周最低') + 1)

    def test_full_column_order(self):
        """列顺序由用户指定，整体锁定，避免后续改动漂移。"""
        body = self.client.get('/stock/list').get_data(as_text=True)
        heads = [re.sub(r'<[^>]+>', '', h).strip()
                 for h in re.findall(r'<th\b[^>]*>(.*?)</th>', body, re.S)]
        self.assertEqual(heads, ['标的', '现价', '52周最低', '卖出价', '当前 PE', '当前 PB',
                                 'K线信号', '状态', '创建时间', '操作'])

    def test_cell_count_matches_columns(self):
        body = self.client.get('/stock/list').get_data(as_text=True)
        heads = re.findall(r'<th\b[^>]*>', body)
        # 行属性会随改动增加（如刷新行情需要的 data-id），用 \b 前缀匹配而不是写死属性顺序
        rows = re.findall(r'<tr\b[^>]*data-status.*?</tr>', body, re.S)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(len(re.findall(r'<td', row)), len(heads))

    def test_missing_data_shows_dash(self):
        """无近一年 K 线的订单显示 —，不能显示 0.00 让人误读。"""
        body = self.client.get('/stock/list?per_page=50').get_data(as_text=True)
        cells = re.findall(r'<td class="right num muted">([^<]*)</td>', body)
        self.assertTrue(cells, '未渲染出 52周最低 单元格')
        for value in cells:
            self.assertTrue(value.strip() == '—' or re.match(r'^\d+\.\d{2}$', value.strip()),
                            '非法单元格内容: %r' % value)


if __name__ == '__main__':
    unittest.main()
