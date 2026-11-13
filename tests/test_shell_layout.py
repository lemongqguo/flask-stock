# -*- coding: utf-8 -*-
"""
壳层布局契约（008 侧栏四组折叠控件 + 009 看板平铺自适应，2026-11-12 用户反馈）。

运行：python -m unittest tests.test_shell_layout -v

纯静态断言，不连库不起 app：锁死「四组都有折叠控件且状态同步」与
「看板不设宽度上限、图表撑满剩余高度」两个布局约定不回归。
"""
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), '..')


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


class ShellLayoutContractTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.base = _read('templates', 'base.html')
        cls.js = _read('static', 'js', 'theme.js')
        cls.css = _read('static', 'css', 'theme.css')

    def test_four_side_toggles(self):
        # 交易 / 行情 / 监控 / 系统 四个组标题行右侧各一个折叠控件
        # （按按钮特征计数，注释里的提及不算）
        self.assertEqual(self.base.count('class="side-toggle" data-side-toggle'), 4)

    def test_side_toggle_binds_all(self):
        # theme.js 绑定全部控件并同步状态（不再只认第一个按钮）
        self.assertIn("querySelectorAll('[data-side-toggle]')", self.js)
        self.assertIn('btns.forEach', self.js)

    def test_market_full_bleed_width(self):
        # 看板随 .content 全宽铺开：1400px 上限不得复发
        self.assertNotIn('max-width: 1400px', self.css)
        self.assertIn('width: 100%; flex: 1 1 auto; min-height: 0;', self.css)

    def test_market_chart_fills_height(self):
        # 图表卡纵向撑满剩余高度（flex 链），宽屏指标单行平铺
        self.assertIn('.mk-chart-card { flex: 1 1 auto;', self.css)
        self.assertIn('.mk-chart-wrap { position: relative; flex: 1 1 auto;', self.css)
        self.assertIn('@media (min-width: 1500px)', self.css)


if __name__ == '__main__':
    unittest.main()