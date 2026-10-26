"""
表格行状态底色的契约用例。

对应变更：[2026-10-22 告警行/暂停行专属背景](../spec/changes/2026-10-22-row-state-bg.md)

原则：**底色用来表达状态，不是装饰**。普通行保持卡片原色——
曾给所有行加过淡色底（用户反馈效果不好，已回退，见
[2026-10-22 表格行淡色底](../changes/2026-10-22-table-row-bg.md)）。

锁：
1. 普通行**没有**底色（防止淡色底被重新加回来），hover 仍走 `--surface-2`；
2. 告警行 / 暂停行有各自的底色，告警行呼吸；
3. sticky 操作列必须与行状态同源、动画参数一致（否则右侧出现不呼吸的色块）；
4. 尊重 `prefers-reduced-motion`。
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_PATH = os.path.join(ROOT, 'static', 'css', 'theme.css')


def read_css():
    with open(CSS_PATH, encoding='utf-8') as fh:
        return fh.read()


def theme_block(css, theme):
    match = re.search(r':root\[data-theme="%s"\]\s*\{(.*?)\}' % theme, css, re.S)
    assert match, '缺少 %s 主题变量块' % theme
    return match.group(1)


class PlainRowTest(unittest.TestCase):
    """普通行：不带底色（淡色底已回退）。"""

    def test_plain_row_has_no_background(self):
        css = read_css()
        rule = re.search(r'^tbody tr\s*\{(.*?)\}', css, re.S | re.M)
        self.assertIsNotNone(rule)
        # 注意：transition 里也有 "background" 字样，只能按 `background:` 声明判断
        self.assertNotRegex(rule.group(1), r'background\s*:',
                            '普通行不设底色——底色只用于表达告警/暂停状态')

    def test_row_bg_variables_removed(self):
        """--row-bg / --row-bg-hover 已随淡色底一起回退，不应再出现。"""
        css = read_css()
        self.assertNotIn('--row-bg', css)

    def test_hover_uses_surface2(self):
        css = read_css()
        rule = re.search(r'^tbody tr:hover\s*\{(.*?)\}', css, re.S | re.M)
        self.assertIsNotNone(rule, '缺少普通行 hover 规则')
        self.assertIn('var(--surface-2)', rule.group(1))


class AlarmRowTest(unittest.TestCase):

    def test_alarm_row_uses_gradient(self):
        css = read_css()
        rule = re.search(r'^tbody tr\[data-alarm="alarm"\]\s*\{(.*?)\}', css, re.S | re.M)
        self.assertIsNotNone(rule)
        self.assertIn('var(--alarm-grad)', rule.group(1))

    def test_gradient_is_slidable(self):
        """渐变要能滑动：background-size 必须大于 100%，否则没有位移余量。"""
        css = read_css()
        rule = re.search(r'^tbody tr\[data-alarm="alarm"\]\s*\{(.*?)\}', css, re.S | re.M)
        size = re.search(r'background-size:\s*(\d+)%', rule.group(1))
        self.assertIsNotNone(size, '缺少 background-size')
        self.assertGreater(int(size.group(1)), 100)

    def test_alarm_row_flows(self):
        css = read_css()
        rule = re.search(r'^tbody tr\[data-alarm="alarm"\]\s*\{(.*?)\}', css, re.S | re.M)
        self.assertIn('alarm-flow', rule.group(1))
        self.assertIn('infinite', rule.group(1))

    def test_alarm_row_breathes(self):
        css = read_css()
        rule = re.search(r'^tbody tr\[data-alarm="alarm"\]\s*\{(.*?)\}', css, re.S | re.M)
        self.assertIn('alarm-breathe', rule.group(1))

    def test_flow_keyframes_move_position(self):
        css = read_css()
        block = re.search(r'@keyframes alarm-flow\s*\{(.*?)\n\}', css, re.S)
        self.assertIsNotNone(block, '缺少 alarm-flow 动画定义')
        self.assertIn('background-position', block.group(1))

    def test_breathe_uses_opacity_not_background(self):
        """呼吸只能改 opacity——渐变占了 background，改它会把渐变冲掉。"""
        css = read_css()
        block = re.search(r'@keyframes alarm-breathe\s*\{(.*?)\n\}', css, re.S)
        self.assertIsNotNone(block)
        self.assertIn('opacity', block.group(1))
        self.assertNotIn('background', block.group(1))

    def test_hover_stops_flow_but_keeps_breathing(self):
        """hover 停流动、留呼吸，并换成更浓的渐变（渐变无法叠加半透明层）。"""
        css = read_css()
        rule = re.search(r'^tbody tr\[data-alarm="alarm"\]:hover\s*\{(.*?)\}', css, re.S | re.M)
        self.assertIsNotNone(rule)
        self.assertIn('animation: none,', rule.group(1), 'hover 必须停掉流动动画')
        self.assertIn('alarm-breathe', rule.group(1), '呼吸应保留')
        self.assertIn('var(--alarm-grad-hover)', rule.group(1))


class StickyColumnSyncTest(unittest.TestCase):
    """sticky 操作列自带不透明背景，必须跟着行状态走。"""

    def test_base_background_is_surface(self):
        css = read_css()
        rule = re.search(r'th\.col-actions,\s*td\.col-actions\s*\{(.*?)\}', css, re.S)
        self.assertIsNotNone(rule)
        self.assertIn('background: var(--surface)', rule.group(1))

    def test_alarm_column_opaque(self):
        """操作列必须不透明：渐变在右缘已渐隐到透明，这里要用等效实色顶上，
           否则横向滚动时会透视下层列的内容。"""
        css = read_css()
        rule = re.search(r'tbody tr\[data-alarm="alarm"\] td\.col-actions\s*\{(.*?)\}', css, re.S)
        self.assertIsNotNone(rule, '告警行的操作列必须自带底色')
        self.assertIn('var(--alarm-bg-1)', rule.group(1))

    def test_column_does_not_run_its_own_animation(self):
        """操作列不能再跑一套自己的动画——呼吸由 tr 的 opacity 统一作用整行，
           操作列若各自为政必然不同步。"""
        css = read_css()
        rule = re.search(r'tbody tr\[data-alarm="alarm"\] td\.col-actions\s*\{(.*?)\}', css, re.S)
        self.assertNotIn('animation', rule.group(1))

    def test_inactive_column_follows(self):
        css = read_css()
        self.assertRegex(css, r'tbody tr\[data-status="inactive"\] td\.col-actions\s*\{[^}]*var\(--surface-2\)')


class InactiveRowTest(unittest.TestCase):

    def test_inactive_row_dimmed(self):
        css = read_css()
        rule = re.search(r'^tbody tr\[data-status="inactive"\]\s*\{(.*?)\}', css, re.S | re.M)
        self.assertIsNotNone(rule)
        self.assertIn('var(--idle-grad)', rule.group(1))
        self.assertIn('opacity', rule.group(1), '暂停行要整体淡出，一眼看出不在监控')

    def test_inactive_hover_restores(self):
        """hover 时恢复清晰，否则按钮也跟着变淡不好点。"""
        css = read_css()
        self.assertRegex(css, r'tbody tr\[data-status="inactive"\]:hover\s*\{[^}]*opacity:\s*1')


class AlarmTokensTest(unittest.TestCase):

    def test_both_themes_define_gradients(self):
        css = read_css()
        for theme in ('dark', 'light'):
            block = theme_block(css, theme)
            for var in ('--alarm-grad', '--alarm-grad-hover', '--idle-grad', '--alarm-bg-1'):
                self.assertIn(var, block, '%s 主题缺少 %s' % (theme, var))

    def test_gradients_are_multicolor(self):
        """告警渐变要多色叠加，且终点透明（从左侧淡入、到右侧边缘收尾）。"""
        css = read_css()
        for theme in ('dark', 'light'):
            block = theme_block(css, theme)
            grad = re.search(r'--alarm-grad:\s*linear-gradient\((.*?)\);', block, re.S)
            self.assertIsNotNone(grad, '%s 主题的告警渐变缺失' % theme)
            stops = re.findall(r'rgba\(', grad.group(1))
            self.assertGreaterEqual(len(stops), 3, '至少三色叠加：%s' % theme)
            self.assertIn('rgba(255, 77, 79, 0)', grad.group(1), '终点必须透明，渐变才会在右缘收尾')

    def test_respects_reduced_motion(self):
        css = read_css()
        self.assertIn('prefers-reduced-motion', css)


if __name__ == '__main__':
    unittest.main()
