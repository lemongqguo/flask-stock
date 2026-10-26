"""
BaseModel 查询构造测试（D-07）。

原缺陷：传入 search_query 但类未定义 search_fields 时会拼出裸 `WHERE `，
导致 SQL 语法错误；count 查询里还有"三元表达式当语句"的无效写法。
这里通过替换 execute_query 捕获最终 SQL，不触碰真实数据库。
"""
import unittest

from models.base import BaseModel


class _Dummy(BaseModel):
    table_name = 'dummy_with_search'
    search_fields = ['name', 'code']


class _DummyNoSearch(BaseModel):
    """未声明 search_fields 的模型。"""
    table_name = 'dummy_without_search'


class _DummyBadField(BaseModel):
    """子类误配了非法字段名，应被白名单过滤掉。"""
    table_name = 'dummy_bad_field'
    search_fields = ['name', 'name; DROP TABLE users']


class SQLCaptureMixin:
    """把 execute_query 替换为记录调用的假实现。"""

    def setUp(self):
        self.captured = []
        self._original = BaseModel.__dict__['execute_query']

        def fake_execute_query(cls, query, params=None):
            self.captured.append((query, params))
            return []

        BaseModel.execute_query = classmethod(fake_execute_query)

    def tearDown(self):
        BaseModel.execute_query = self._original

    @property
    def data_query(self):
        return self.captured[0]

    @property
    def count_query(self):
        return self.captured[1]


class BuildSearchWhereTest(unittest.TestCase):
    def test_returns_empty_for_blank_keyword(self):
        self.assertEqual(_Dummy.build_search_where(''), ('', []))
        self.assertEqual(_Dummy.build_search_where(None), ('', []))
        self.assertEqual(_Dummy.build_search_where('   '), ('', []))

    def test_returns_empty_without_search_fields(self):
        """D-07 核心：无 search_fields 时不能产生 WHERE 子句。"""
        where, params = _DummyNoSearch.build_search_where('abc')
        self.assertEqual(where, '')
        self.assertEqual(params, [])

    def test_illegal_field_is_filtered(self):
        where, params = _DummyBadField.build_search_where('abc')
        self.assertNotIn('DROP', where)
        self.assertEqual(where, '(`name` LIKE %s)')
        self.assertEqual(params, ['%abc%'])

    def test_two_fields_produce_or_condition(self):
        where, params = _Dummy.build_search_where('abc')
        self.assertEqual(where, '(`name` LIKE %s OR `code` LIKE %s)')
        self.assertEqual(params, ['%abc%', '%abc%'])

    def test_keyword_wrapped_with_percent(self):
        # _Dummy 有两个搜索字段，因此参数会出现两次
        _, params = _Dummy.build_search_where('茅台')
        self.assertEqual(params, ['%茅台%', '%茅台%'])


class GetAllQueryTest(SQLCaptureMixin, unittest.TestCase):
    def test_no_search_produces_no_where_clause(self):
        _Dummy.get_all(page=1, per_page=10, search_query=None)
        data_sql, data_params = self.data_query
        count_sql, count_params = self.count_query

        self.assertNotIn('WHERE', data_sql)
        self.assertNotIn('WHERE', count_sql)
        self.assertEqual(data_params, (10, 0))
        self.assertEqual(count_params, ())

    def test_search_on_model_without_search_fields_has_no_bare_where(self):
        """回归用例：修复前这里会生成 `... WHERE  ORDER BY ...` 而报错。"""
        _DummyNoSearch.get_all(page=2, per_page=20, search_query='abc')
        data_sql, data_params = self.data_query
        count_sql, count_params = self.count_query

        self.assertNotIn('WHERE', data_sql)
        self.assertNotIn('WHERE', count_sql)
        self.assertNotIn('LIKE', data_sql)
        # 关键字被忽略，因此不进入参数列表
        self.assertEqual(data_params, (20, 20))
        self.assertEqual(count_params, ())

    def test_search_adds_where_and_matching_params(self):
        _Dummy.get_all(page=1, per_page=10, search_query='abc')
        data_sql, data_params = self.data_query
        count_sql, count_params = self.count_query

        self.assertIn('WHERE', data_sql)
        self.assertIn('WHERE', count_sql)
        self.assertEqual(data_params, ('%abc%', '%abc%', 10, 0))
        self.assertEqual(count_params, ('%abc%', '%abc%'))

    def test_data_and_count_share_identical_where(self):
        _Dummy.get_all(page=3, per_page=5, search_query='x')
        data_sql, _ = self.data_query
        count_sql, _ = self.count_query

        expected_where = '(`name` LIKE %s OR `code` LIKE %s)'
        self.assertIn(f'WHERE {expected_where}', data_sql)
        self.assertIn(f'WHERE {expected_where}', count_sql)

    def test_invalid_page_is_normalised(self):
        _Dummy.get_all(page=0, per_page=0, search_query=None)
        _, data_params = self.data_query
        # page 兜底为 1（offset=0），per_page 兜底为 10，都不会产生负数偏移
        self.assertEqual(data_params, (10, 0))

    def test_negative_page_does_not_produce_negative_offset(self):
        _Dummy.get_all(page=-5, per_page=10, search_query=None)
        _, data_params = self.data_query
        self.assertEqual(data_params, (10, 0))

    def test_page_offset_calculation(self):
        _Dummy.get_all(page=3, per_page=20, search_query=None)
        _, data_params = self.data_query
        self.assertEqual(data_params, (20, 40))


if __name__ == '__main__':
    unittest.main()
