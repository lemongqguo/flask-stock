"""
订单列表「AI 分析」快捷入口的回归用例。

对应变更：[2026-10-22 订单列表 AI 分析快捷入口](../spec/changes/2026-10-22-list-ai-shortcut.md)

锁定三件事：

1. **不串标的**：每行的入口必须指向**本行**的 `stock_id`（复制粘贴最易出的错）；
2. **不新增列**：入口复用「标的」列吸收的剩余宽度，表头仍是 10 列、每行仍是 10 个 `<td>`；
3. **位置**：入口落在第一个 `<td>`（标的列）内，而不是被挤到别的单元格里。
"""
import os
import re
import sys
import unittest

sys.path.insert(0, '.')

from app import app

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME_CSS = os.path.join(BASE_DIR, 'static', 'css', 'theme.css')

# 标的列内容区的最低需求：avatar 34 + gap 11 + 4 字名称 56 + gap 12 + 按钮 75 + td 左右 padding 28
STOCK_COL_MIN = 216


class ListAiShortcutTest(unittest.TestCase):
    """页面层：真实渲染订单列表（依赖库内已有订单）。"""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        with cls.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'
        cls.body = cls.client.get('/stock/list?per_page=50').get_data(as_text=True)

    def _rows(self):
        """[(stock_id, 整行 HTML)]"""
        return re.findall(r'<tr\b[^>]*data-id="(\d+)"[^>]*>(.*?)</tr>', self.body, re.S)

    def test_every_row_has_entry_to_its_own_stock(self):
        rows = self._rows()
        self.assertTrue(rows, '没有渲染出任何订单行，无法验证入口')
        for stock_id, row in rows:
            targets = set(re.findall(r'/stock/ai/\?stock_id=(\d+)', row))
            self.assertEqual(targets, {stock_id},
                             '第 %s 行的 AI 入口指向了 %r' % (stock_id, targets))
            self.assertEqual(row.count('row-ai'), 1, '第 %s 行应恰好一个 AI 入口' % stock_id)

    def test_entry_sits_in_stock_cell_without_new_column(self):
        heads = re.findall(r'<th\b[^>]*>', self.body)
        self.assertEqual(len(heads), 10, '列数变了：入口应复用标的列的空档，不新增列')
        rows = self._rows()
        self.assertTrue(rows)
        for stock_id, row in rows:
            cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S)
            self.assertEqual(len(cells), len(heads))
            self.assertIn('row-ai', cells[0], '第 %s 行的入口不在「标的」单元格内' % stock_id)

    def test_entry_is_a_plain_link_not_a_form(self):
        """快捷入口只做跳转：GET 链接，不要在列表里塞表单（避免误提交）。"""
        rows = self._rows()
        self.assertTrue(rows)
        for _, row in rows:
            anchor = re.search(r'<a[^>]*row-ai[^>]*>', row)
            self.assertIsNotNone(anchor)
            self.assertIn('/stock/ai/?stock_id=', anchor.group(0))


class StockColumnWidthTest(unittest.TestCase):
    """
    小屏 / 缩窗重叠的回归（D-13）。

    真实出现过的三种坏法，对应三条互不替代的约束：
    1. **列宽被压缩**：9 个定宽列吃掉 992px，第一列（唯一不定宽）在 1160 表宽下只剩 168px，
       窄窗更强压缩——压到 0 时名称整块消失（省略号在 0 宽上不渲染）。
       → 十列全定宽 + `min-width` = 定宽之和，宽度不够只横向滚动，**永不反压**；
    2. **flex 子项不肯收缩**：`.cell-primary` 的 `min-width: auto` 让它拒绝缩到内容以下，
       名称溢出盖住按钮。→ 三层 `min-width: 0` + 名称 `nowrap + ellipsis`；
    3. **列宽要够**：标的列得放下 头像 + 名称 + 按钮。→ 300px ≥ 216px（用例锁死）。
    """

    def setUp(self):
        with open(THEME_CSS, encoding='utf-8') as fh:
            self.css = fh.read()
        with open(os.path.join(BASE_DIR, 'templates', 'stock_order_list.html'),
                  encoding='utf-8') as fh:
            self.tpl = fh.read()

    def test_all_columns_fixed_width(self):
        """十列全定宽 + min-width 等于定宽之和：窄窗只滚动，不反压列宽（压到 0 名称就消失）。"""
        widths = [int(w) for w in re.findall(r'<col style="width:(\d+)px">', self.tpl)]
        self.assertEqual(len(widths), 10, '十列必须全定宽，留一个 auto 列就会被压成 0')
        self.assertIn('class="table-orders"', self.tpl, '订单表格需要独立类名，避免影响其他页')
        rule = re.search(r'table\.table-orders\s*\{\s*min-width:\s*(\d+)px', self.css)
        self.assertIsNotNone(rule, '缺少 table.table-orders 的 min-width')
        self.assertEqual(int(rule.group(1)), sum(widths),
                         'min-width 必须等于定宽之和 %d，否则窄窗下浏览器会反向压缩列宽'
                         % sum(widths))
        self.assertGreaterEqual(widths[0], STOCK_COL_MIN,
                                '标的列只有 %dpx，装不下名称 + AI 入口（需 ≥ %dpx）'
                                % (widths[0], STOCK_COL_MIN))

    def test_cell_allowed_to_shrink(self):
        """三层 min-width:0 + 省略号：只设一层的话名称仍会溢出压住按钮。"""
        self.assertIn('.cell-with-action > .cell-primary { flex: 1 1 auto; min-width: 0; }', self.css)
        self.assertIn('.cell-with-action .cell-primary > span { min-width: 0; }', self.css)
        block = re.search(r'\.cell-with-action \.cell-name,\s*\.cell-with-action \.cell-code\s*\{([^}]*)\}',
                          self.css)
        self.assertIsNotNone(block, '缺少名称 / 代码的省略号规则')
        self.assertIn('text-overflow: ellipsis', block.group(1))
        self.assertIn('white-space: nowrap', block.group(1))


if __name__ == '__main__':
    unittest.main()
