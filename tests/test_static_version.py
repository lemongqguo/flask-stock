"""
静态资源版本号（cache busting）的契约用例。

对应变更：[2026-10-22 静态资源加版本号](../spec/changes/2026-10-22-static-version.md)

背景（真实故障）：Flask 对 static 目录的响应不带明确 max-age，浏览器走启发式缓存。
改了 CSS/JS 后用户拿到的仍是旧文件——表现为"按钮渲染出来了（服务端渲染），点了没反应
（JS 是旧版，没有对应处理函数）"。

锁：
1. `static_url()` 生成的 URL 带版本参数，且随文件 mtime 变化；
2. 三个模板（base/auth/error）引用 CSS/JS 都走 `static_url`，**不得**裸用 `url_for('static', ...)`。
"""
import os
import re
import sys
import unittest

sys.path.insert(0, '.')

from app import app, static_url

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = ('base.html', 'auth.html', 'error.html')


class StaticUrlTest(unittest.TestCase):
    """static_url 内部用 url_for，必须在 app context 里调用。"""

    def setUp(self):
        self.ctx = app.test_request_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_has_version_param(self):
        url = static_url('js/theme.js')
        self.assertIn('/static/js/theme.js', url)
        self.assertRegex(url, r'[?&]v=\d+', '静态资源 URL 必须带版本号')

    def test_version_follows_mtime(self):
        """版本号跟着文件 mtime 走：文件一改，URL 就变。"""
        path = os.path.join(ROOT, 'static', 'js', 'theme.js')
        self.assertEqual(static_url('js/theme.js'),
                         static_url('js/theme.js'))  # 幂等
        self.assertIn(str(int(os.path.getmtime(path))), static_url('js/theme.js'))

    def test_missing_file_degrades(self):
        """文件不存在时不能抛异常（模板渲染不该因为缺文件挂掉）。"""
        self.assertIn('/static/js/nope.js', static_url('js/nope.js'))

    def test_templates_use_static_url(self):
        for name in TEMPLATES:
            with open(os.path.join(ROOT, 'templates', name), encoding='utf-8') as fh:
                body = fh.read()
            self.assertNotRegex(body, r"url_for\('static'",
                                '%s 必须改用 static_url（否则改了 JS/CSS 用户拿不到新文件）' % name)
            self.assertIn("static_url('js/theme.js')", body)
            self.assertIn("static_url('css/theme.css')", body)


class RenderedPageTest(unittest.TestCase):
    """真实渲染出来的页面里，脚本地址必须带版本号。"""

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'smoke'

    def test_script_tag_versioned(self):
        body = self.client.get('/stock/list').get_data(as_text=True)
        match = re.search(r'<script src="([^"]*theme\.js[^"]*)"', body)
        self.assertIsNotNone(match, '页面缺少 theme.js 引用')
        self.assertRegex(match.group(1), r'[?&]v=\d+')

    def test_css_link_versioned(self):
        body = self.client.get('/stock/list').get_data(as_text=True)
        match = re.search(r'<link href="([^"]*theme\.css[^"]*)"', body)
        self.assertIsNotNone(match, '页面缺少 theme.css 引用')
        self.assertRegex(match.group(1), r'[?&]v=\d+')


if __name__ == '__main__':
    unittest.main()
