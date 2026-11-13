# -*- coding: utf-8 -*-
"""
成交额走势图契约（009 · 2026-11-13 分量线 + 轴下图例）。

运行：python -m unittest tests.test_market_turnover_chart -v

纯静态断言，不连库不起 app：锁死「沪深北三条分量线细于合计主线、
图例在 x 轴下方、缺失断线不连、双主题分量色」四个呈现约定不回归。
"""
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), '..')


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


class MarketChartContractTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = _read('templates', 'market_turnover.html')
        cls.css = _read('static', 'css', 'theme.css')

    def test_legend_below_x_axis(self):
        # 图例在 canvas 容器之后（x 轴日期标签绘于 canvas 底部），且在图表卡内
        wrap = self.html.index('id="mkChartWrap"')
        legend = self.html.index('class="mk-legend"')
        section_end = self.html.index('</section>', wrap)
        self.assertGreater(legend, wrap)
        self.assertLess(legend, section_end)

    def test_legend_four_items(self):
        # 四项齐全：合计 + 沪 / 深 / 北，色条类名与线色变量对应
        legend = self.html[self.html.index('class="mk-legend"'):]
        legend = legend[:legend.index('</div>')]
        for label, cls in (('沪深北合计', 'is-total'), ('沪市', 'is-sh'),
                           ('深市', 'is-sz'), ('北证', 'is-bj')):
            self.assertIn('mk-legend-line ' + cls, legend)
            self.assertIn(label, legend)

    def test_component_lines_thinner_than_total(self):
        # 分量线宽 < 合计主线宽；三条分量系列（history 行下标 1/2/3）齐全
        total = float(re.search(r'const TOTAL_WIDTH = ([\d.]+);', self.html).group(1))
        comp = float(re.search(r'const COMPONENT_WIDTH = ([\d.]+);', self.html).group(1))
        self.assertLess(comp, total)
        for index, color in ((1, 'sh'), (2, 'sz'), (3, 'bj')):
            self.assertIn("{ index: %d, color: '%s' }" % (index, color), self.html)
        # 先画分量（垫底）后画主线（最上层）
        self.assertLess(self.html.index('ctx.lineWidth = COMPONENT_WIDTH;'),
                        self.html.index('ctx.lineWidth = TOTAL_WIDTH;'))

    def test_null_gaps_break_line(self):
        # 分量路径遇 null 断笔重启（moveTo），绝不跨缺失连线、不伪造 0
        self.assertIn('if (v === null || v === undefined) { pen = false; continue; }', self.html)
        self.assertIn('path.moveTo(xAt(i), yAt(v));', self.html)

    def test_scale_includes_components(self):
        # Y 轴按 SERIES_INDEX 映射遍历四系列，跳过隐藏系列与 null（分量不会跌出绘图区）
        self.assertIn('const SERIES_INDEX = { sh: 1, sz: 2, bj: 3, total: 4 };', self.html)
        self.assertIn('if (hidden[key]) continue;', self.html)

    def test_theme_colors_both_modes(self):
        # 三个分量色变量在暗 / 亮两个主题块各定义一次；图例与 tooltip 圆点样式齐全
        for var in ('--mk-sh', '--mk-sz', '--mk-bj'):
            self.assertEqual(len(re.findall(re.escape(var) + r':\s*#', self.css)), 2)
        for cls in ('.mk-legend-line.is-total', '.mk-legend-line.is-sh',
                    '.mk-legend-line.is-sz', '.mk-legend-line.is-bj',
                    '.mk-tooltip .t-dot.is-total', '.mk-tooltip .t-dot.is-sh',
                    '.mk-tooltip .t-dot.is-sz', '.mk-tooltip .t-dot.is-bj'):
            self.assertIn(cls, self.css)


    def test_legend_toggle_buttons(self):
        # 图例为可点击 button（键盘可达）+ aria-pressed 初始 true + 容器 id
        self.assertIn('id="mkLegend"', self.html)
        for key in ('total', 'sh', 'sz', 'bj'):
            self.assertIn(
                f'<button type="button" class="mk-legend-item" data-series="{key}" aria-pressed="true"',
                self.html)

    def test_legend_click_handler(self):
        # 点击切换 hidden + is-off + aria-pressed 并立即重绘
        self.assertIn("legendBox.addEventListener('click'", self.html)
        self.assertIn('hidden[key] = !hidden[key];', self.html)
        self.assertIn("button.classList.toggle('is-off', hidden[key]);", self.html)
        self.assertIn("button.setAttribute('aria-pressed', String(!hidden[key]));", self.html)

    def test_hidden_series_skipped(self):
        # 绘制/单点/悬停/tooltip 均按 hidden 过滤；全隐藏有居中提示兜底
        self.assertIn('if (hidden[COMPONENTS[s].color]) continue;', self.html)
        self.assertIn('if (!hidden.total) {', self.html)
        self.assertIn('if (!hidden.sh) tipRows.push', self.html)
        self.assertIn('所有系列已隐藏 · 点击下方图例恢复', self.html)
        self.assertIn('const allHidden = minValue === Infinity;', self.html)

    def test_legend_off_styles(self):
        self.assertIn('.mk-legend-item.is-off {', self.css)
        self.assertIn('.mk-legend-item.is-off .mk-legend-line {', self.css)
        self.assertIn('.mk-legend-item:focus-visible {', self.css)
        self.assertIn('.mk-legend-item:hover {', self.css)


if __name__ == '__main__':
    unittest.main()