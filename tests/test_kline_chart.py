"""
K 线图配色的回归用例。

对应变更：[2026-10-21 前端 UI 改版 · 用户反馈修正（第 4 轮）](../spec/changes/2026-10-21-frontend-redesign.md)

用户提供的参考图：收盘价青绿实线，MA5/MA10/MA30 为粉/蓝/黄**虚线**。
Chart.js 是运行时绘制的，无法在单测里断言像素，这里锁三件事：

1. 四条线都引用 `--kline-*` 变量（不许再借用 --up/--down 等语义色）；
2. 三条均线都有 `borderDash`（虚线）；
3. `theme.css` 两个主题都定义了这 4 个变量（缺一个，canvas 里就是透明线）。
"""
import os
import re
import sys
import unittest

sys.path.insert(0, '.')

from app import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VARS = ('--kline-price', '--kline-ma5', '--kline-ma10', '--kline-ma30')


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as fh:
        return fh.read()


class KlineColorTest(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'

    def test_datasets_use_kline_vars(self):
        body = self.client.get('/stock/edit/1').get_data(as_text=True)
        self.assertIn("cssVar('--kline-price')", body, '收盘价未使用 --kline-price')
        for name in VARS[1:]:
            self.assertIn("cssVar('%s')" % name, body, '%s 未被均线引用' % name)
        # 旧的语义色借用必须清除，否则两处配色会漂移
        self.assertNotIn("borderColor: cssVar('--up')", body)
        self.assertNotIn("borderColor: cssVar('--down')", body)
        self.assertNotIn("borderColor: cssVar('--info')", body)

    def test_ma_lines_are_dashed(self):
        """参考图里三条均线是虚线；收盘价保持实线。"""
        body = self.client.get('/stock/edit/1').get_data(as_text=True)
        self.assertEqual(body.count('borderDash'), 3, '应有且仅有 3 条虚线（MA5/MA10/MA30）')
        ma5 = re.search(r"label: 'MA5'.*?}", body, re.S)
        self.assertIsNotNone(ma5)
        self.assertIn('borderDash', ma5.group(0))

    def test_theme_css_defines_all_vars(self):
        css = read('static/css/theme.css')
        for name in VARS:
            found = len(re.findall(r'%s\s*:' % re.escape(name), css))
            self.assertGreaterEqual(found, 2, '%s 应在暗色与亮色主题各定义一次' % name)


if __name__ == '__main__':
    unittest.main()
