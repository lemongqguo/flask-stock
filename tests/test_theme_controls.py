"""
双主题下**原生表单控件**的契约用例（缺陷 D-15）。

真实故障：暗色主题里点开 AI 追问框的模型下拉，弹层是白底 + 浅灰字——
`<select>` 展开的 option 列表由浏览器/系统渲染，**不继承** select 的背景与文字色，
只靠 CSS 变量改不到它。修法两条并用：
1. 主题变量块里声明 `color-scheme: dark|light`（浏览器据此把弹层、滚动条等原生部件按暗/亮渲染）；
2. 给 `.select option` / `.ask-select option` 显式钉死背景与文字色（兜住仍走系统配色的平台）。

锁的就是这两条——删掉任意一条，弹层又会变回白底浅灰字。
"""
import os
import re
import sys
import unittest

sys.path.insert(0, '.')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as fh:
        return fh.read()


def theme_block(css, theme):
    """取出 `:root[data-theme="xxx"] { ... }` 的块内容（第一个闭合花括号为止）。"""
    match = re.search(r':root\[data-theme="%s"\]\s*\{(.*?)\}' % theme, css, re.S)
    return match.group(1) if match else ''


class ThemeColorSchemeTest(unittest.TestCase):
    """两套主题都要声明 color-scheme，且不能写反。"""

    @classmethod
    def setUpClass(cls):
        cls.css = read('static/css/theme.css')

    def test_dark_declares_dark_scheme(self):
        self.assertIn('color-scheme: dark', theme_block(self.css, 'dark'))

    def test_light_declares_light_scheme(self):
        self.assertIn('color-scheme: light', theme_block(self.css, 'light'))

    def test_no_cross_declaration(self):
        """写反了比不写更糟：暗色主题里声明 light 会让弹层固定成白底。"""
        self.assertNotIn('color-scheme: light', theme_block(self.css, 'dark'))
        self.assertNotIn('color-scheme: dark', theme_block(self.css, 'light'))


class SelectOptionStyleTest(unittest.TestCase):
    """select 的 option 必须显式配色（含 AI 追问框里那个透明底的 .ask-select）。"""

    @classmethod
    def setUpClass(cls):
        cls.css = read('static/css/theme.css')

    def _rule(self, selector):
        match = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', self.css)
        self.assertIsNotNone(match, '缺少样式规则 %s' % selector)
        return match.group(1)

    def test_option_has_theme_colors(self):
        rule = self._rule('.select option, .ask-select option')
        self.assertIn('background-color: var(--surface)', rule)
        self.assertIn('color: var(--text)', rule)

    def test_composer_select_keeps_pill_transparent(self):
        """pill 里的 select 本身要透明，否则会在胶囊里画出一块底色。"""
        rule = self._rule('.ask-select')
        self.assertIn('background: transparent', rule)


if __name__ == '__main__':
    unittest.main()
