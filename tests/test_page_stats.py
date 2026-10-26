"""
页面 KPI 统计的回归用例。

覆盖两处新逻辑：
- 订单列表「触发告警」数必须与列表里高亮行的判定**完全一致**（共用同一段 SQL 条件）；
- 告警历史概览统计的取值与异常兜底。
"""
import unittest
from unittest import mock

from models.stock_alarm import StockAlarm
from models.stock_master import ALARM_ACTIVE_CONDITION, StockMaster


class AlarmActiveConditionTest(unittest.TestCase):
    """列表判定与统计判定共用条件，避免两处漂移导致「KPI 说 2 条、列表高亮 3 行」。"""

    def test_count_query_uses_shared_condition(self):
        captured = []

        def fake_query(query, params=None):
            captured.append(query)
            return [{'count': 0}]

        with mock.patch.object(StockMaster, 'execute_query', side_effect=fake_query):
            StockMaster.count_alarm_active()

        self.assertIn(ALARM_ACTIVE_CONDITION, captured[0])
        self.assertIn('COUNT(*)', captured[0])

    def test_detail_query_uses_shared_condition(self):
        captured = []

        def fake_query(query, params=None):
            captured.append(query)
            return []

        with mock.patch.object(StockMaster, 'execute_query', side_effect=fake_query):
            StockMaster.get_all_with_details()

        # 第一次调用是列表查询（含 is_alarm_active 判定），第二次是总数统计
        self.assertIn(ALARM_ACTIVE_CONDITION, captured[0])
        self.assertIn('is_alarm_active', captured[0])

    def test_condition_covers_price_pe_pb(self):
        """三类阈值（价格 / PE / PB）与卖出价都要出现在判定里。"""
        for token in ('sw.stock_valueone', 'sw.sell_rate', 'sp.pe_valueone', 'spb.pb_valueone'):
            self.assertIn(token, ALARM_ACTIVE_CONDITION)


class AlarmStatsTest(unittest.TestCase):

    def test_null_sum_normalized_to_zero(self):
        """无匹配行时 MySQL 的 SUM 返回 NULL，必须统一成 0，否则模板格式化会炸。"""
        row = {'total': 0, 'today': None, 'last7': None,
               'mail_sent': None, 'mail_failed': None, 'mail_skipped': None}
        with mock.patch.object(StockAlarm, 'execute_query', return_value=[row]):
            stats = StockAlarm.get_stats()
        self.assertEqual(stats['today'], 0)
        self.assertEqual(stats['mail_sent'], 0)
        self.assertEqual(stats['total'], 0)

    def test_values_passthrough(self):
        row = {'total': 100, 'today': 3, 'last7': 12,
               'mail_sent': 90, 'mail_failed': 2, 'mail_skipped': 6}
        with mock.patch.object(StockAlarm, 'execute_query', return_value=[row]):
            stats = StockAlarm.get_stats()
        self.assertEqual(stats['today'], 3)
        self.assertEqual(stats['last7'], 12)
        self.assertEqual(stats['mail_sent'], 90)
        self.assertEqual(stats['mail_failed'], 2)

    def test_empty_result_returns_none(self):
        with mock.patch.object(StockAlarm, 'execute_query', return_value=[]):
            self.assertIsNone(StockAlarm.get_stats())

    def test_query_error_returns_none(self):
        """统计失败不应让整个告警历史页 500。"""
        with mock.patch.object(StockAlarm, 'execute_query', side_effect=RuntimeError('db down')):
            self.assertIsNone(StockAlarm.get_stats())


class IndicatorNavBadgeTest(unittest.TestCase):
    """侧栏「指标监控」徽标的取数口径：近 24h 指标告警，失败降级为 0。"""

    def test_query_filters_type_and_window(self):
        captured = []

        def fake_query(query, params=None):
            captured.append((query, params))
            return [{'total': 2}]

        with mock.patch.object(StockAlarm, 'execute_query', side_effect=fake_query):
            self.assertEqual(StockAlarm.count_recent_indicator(24), 2)

        query, params = captured[0]
        self.assertIn("alarm_type = 'indicator'", query)
        self.assertIn('DATE_SUB(NOW(), INTERVAL %s HOUR)', query)
        self.assertEqual(params, (24,))

    def test_null_count_is_zero(self):
        with mock.patch.object(StockAlarm, 'execute_query', return_value=[{'total': None}]):
            self.assertEqual(StockAlarm.count_recent_indicator(), 0)

    def test_illegal_hours_falls_back_to_24(self):
        captured = []

        def fake_query(query, params=None):
            captured.append(params)
            return [{'total': 0}]

        with mock.patch.object(StockAlarm, 'execute_query', side_effect=fake_query):
            StockAlarm.count_recent_indicator('abc')
        self.assertEqual(captured[0], (24,))

    def test_query_error_degrades_to_zero(self):
        """查库失败不能让页面 500，也不能显示假数字。"""
        with mock.patch.object(StockAlarm, 'execute_query', side_effect=RuntimeError('db down')):
            self.assertEqual(StockAlarm.count_recent_indicator(24), 0)


if __name__ == '__main__':
    unittest.main()
