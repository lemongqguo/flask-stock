"""
订单表单渲染的回归用例。

覆盖两类容易静默出错的问题：

1. 字段为 NULL 时 Jinja 会渲染出字符串 `None`，一旦回填进表单再提交，
   就会把数据库里的 NULL 改成字面量 "None"（脏数据）。
2. 设计稿只保留一个备注框；PE / PB 备注若静默丢失字段名，保存时会被空值覆盖。
"""
import io
import os
import unittest

from flask import render_template_string

from app import app

TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'templates', 'stock_order_form.html'
)


class NoneSafeRenderTest(unittest.TestCase):
    """模板里统一用 `{{ (x.y or '') if x else '' }}`，NULL 必须渲染成空串。"""

    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_null_value_renders_empty(self):
        expr = "{{ (memo_holder.memo or '') if memo_holder else '' }}"

        class Holder(object):
            memo = None

        html = render_template_string('<input value="' + expr + '">', memo_holder=Holder())
        self.assertNotIn('None', html)
        self.assertIn('value=""', html)

    def test_value_preserved(self):
        expr = "{{ (memo_holder.memo or '') if memo_holder else '' }}"

        class Holder(object):
            memo = '第一档试仓 20%'

        html = render_template_string('<input value="' + expr + '">', memo_holder=Holder())
        self.assertIn('第一档试仓 20%', html)

    def test_no_holder_renders_empty(self):
        expr = "{{ (memo_holder.memo or '') if memo_holder else '' }}"
        html = render_template_string('<input value="' + expr + '">', memo_holder=None)
        self.assertIn('value=""', html)


class OrderFormMemoFieldTest(unittest.TestCase):
    """设计稿只保留第 4 段一个备注框；PE / PB 备注改为隐藏字段回传原值。"""

    @classmethod
    def setUpClass(cls):
        with io.open(TEMPLATE_PATH, encoding='utf-8') as f:
            cls.source = f.read()

    def test_pe_pb_memo_not_editable(self):
        self.assertNotIn('<textarea name="pe_memo"', self.source)
        self.assertNotIn('<textarea name="pb_memo"', self.source)

    def test_pe_pb_memo_still_submitted(self):
        """字段名必须还在，否则保存时后端按空串处理会把备注清空。"""
        self.assertIn('name="pe_memo"', self.source)
        self.assertIn('name="pb_memo"', self.source)

    def test_single_visible_memo(self):
        self.assertIn('<textarea name="memo"', self.source)


if __name__ == '__main__':
    unittest.main()
