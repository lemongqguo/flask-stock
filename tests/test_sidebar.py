"""
侧栏折叠控件的回归用例。

对应变更：[2026-10-21 侧栏导航可折叠](../spec/changes/2026-10-21-sidebar-collapse.md)

这里只能锁模板/静态资源契约（项目无 JS 自动化环境）：

1. 折叠按钮存在且位于 `nav-group-label` 内；
2. 每个导航项都有 `title`——折叠后只剩图标，悬停要能看到功能名；
3. sprite 与 CSS 里的折叠图标 / 折叠态规则不能缺（缺了图标会渲染成空白）；
4. 侧栏分组必须是「交易 / 监控 / 系统」，系统组收纳账户设置与退出登录
   （[2026-10-23 侧栏导航分组](../spec/archive/changes/2026-10-23-sidebar-groups.md)）；
5. 「指标监控」徽标只显示真实条数，为 0 时不得渲染。
"""
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, '.')

from app import app
from models.stock_alarm import StockAlarm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GROUP_LABEL_RE = r'<div class="nav-group-label">(.*?)</div>'


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as fh:
        return fh.read()


class SidebarToggleTest(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'

    def _body(self):
        return self.client.get('/stock/list').get_data(as_text=True)

    def _labels(self):
        return re.findall(GROUP_LABEL_RE, self._body(), re.S)

    def test_toggle_button_exists(self):
        body = self._body()
        self.assertIn('data-side-toggle', body)
        self.assertIn('class="side-toggle"', body)

    def test_button_inside_group_label(self):
        """按钮必须在组标题内——组标题折叠后整块隐藏会把按钮一起弄没。"""
        labels = self._labels()
        self.assertTrue(labels, '未找到 nav-group-label')
        holder = [label for label in labels if 'data-side-toggle' in label]
        self.assertEqual(len(holder), 1, '折叠按钮应只出现在一个组标题里')
        # 标题文字要包在 span 里，折叠时只隐藏文字
        self.assertIn('<span>监控</span>', holder[0])

    def test_nav_items_have_title(self):
        """折叠后只剩图标，title 是唯一的功能名来源。"""
        body = self._body()
        items = re.findall(r'<a class="nav-item[^>]*>', body)
        self.assertTrue(items)
        for item in items:
            self.assertIn('title="', item, '导航项缺少 title: %s' % item)

    def test_button_is_not_submit(self):
        """侧栏里也可能有表单，按钮必须是 type=button，避免误提交。"""
        body = self._body()
        btn = re.search(r'<button[^>]*data-side-toggle[^>]*>', body)
        self.assertIsNotNone(btn)
        self.assertIn('type="button"', btn.group(0))


class SidebarGroupsTest(unittest.TestCase):
    """分组结构：交易 / 监控 / 系统，系统组收纳账户设置与退出登录。"""

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'

    def _body(self):
        return self.client.get('/stock/list').get_data(as_text=True)

    def test_nav_groups_order(self):
        """组顺序是设计稿约定，调换会让"交易 / 监控 / 系统"的心智破裂。"""
        labels = re.findall(
            r'<div class="nav-group-label">\s*<span>([^<]+)</span>', self._body())
        self.assertEqual(labels, ['交易', '监控', '系统'])

    def test_system_group_entries(self):
        body = self._body()
        for name, href in (('账户设置', '/profile'), ('退出登录', '/logout')):
            self.assertIn('title="%s"' % name, body)
            self.assertRegex(
                body,
                r'<a class="nav-item[^"]*" href="[^"]*%s"[^>]*title="%s"' % (href, name))

    def test_nav_badge_hidden_when_zero(self):
        """0 条告警时不得渲染徽标（不显示假数字）。"""
        with mock.patch.object(StockAlarm, 'count_recent_indicator', return_value=0):
            body = self._body()
        self.assertNotIn('class="nav-badge', body)

    def test_nav_badge_renders_count(self):
        with mock.patch.object(StockAlarm, 'count_recent_indicator', return_value=3):
            body = self._body()
        self.assertIn('class="nav-badge num"', body)
        self.assertIn('>3</span>', body)
        self.assertIn('近 24 小时指标告警 3 条', body)

    def test_badge_count_not_queried_when_logged_out(self):
        """未登录不渲染侧栏，也就不该白查一次库。"""
        anon = app.test_client()
        with mock.patch.object(StockAlarm, 'count_recent_indicator') as counter:
            anon.get('/login')
        counter.assert_not_called()


class SidebarAssetTest(unittest.TestCase):
    """静态资源契约：图标与折叠态样式缺一不可。"""

    def test_sprite_has_chevron_icons(self):
        js = read('static/js/theme.js')
        self.assertIn('id="i-chevron-left"', js)
        self.assertIn('id="i-chevron-right"', js)

    def test_css_has_collapsed_rules(self):
        css = read('static/css/theme.css')
        self.assertIn('.shell.side-collapsed', css)
        # 折叠态必须隐藏导航文字，而不是整块组标题
        self.assertIn('.side-collapsed .nav-group-label span', css)
        self.assertIn('.side-collapsed .nav-item span', css)

    def test_collapse_key_declared(self):
        js = read('static/js/theme.js')
        self.assertIn('sidebar-collapsed', js, '缺少 localStorage 键')
        self.assertIn('initSideToggle()', js, '未在 DOMContentLoaded 注册')


if __name__ == '__main__':
    unittest.main()
