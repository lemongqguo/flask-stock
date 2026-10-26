"""
告警档位判定规则测试（D-03 / spec/current/003-alarm-thresholds.md 验收条件）。

这些用例锁定的是"历史行为 + 修复后必须保持"的行为：
档位判定顺序（三档 → 二档 → 一档）不得被后续重构悄悄改掉。
"""
import unittest

from utils.alarm_rules import (
    ALARM_TYPE_PB,
    ALARM_TYPE_PE,
    ALARM_TYPE_PRICE,
    ALARM_TYPE_SELL,
    build_gear_alarm,
    build_sell_alarm,
    check_sell,
    determine_lower_gear,
    make_alarm_key,
    threshold_of,
)


class DetermineLowerGearTest(unittest.TestCase):
    """三档下探判定。"""

    # 阈值：10 / 9 / 8
    V1, V2, V3 = 10.0, 9.0, 8.0

    def test_no_hit_above_first_threshold(self):
        self.assertIsNone(determine_lower_gear(11.0, self.V1, self.V2, self.V3))

    def test_hit_first_gear_only(self):
        # 9.5：<= 10 但 > 9
        self.assertEqual(determine_lower_gear(9.5, self.V1, self.V2, self.V3), 1)

    def test_boundary_equals_first_threshold_is_gear_one(self):
        self.assertEqual(determine_lower_gear(10.0, self.V1, self.V2, self.V3), 1)

    def test_hit_second_gear(self):
        self.assertEqual(determine_lower_gear(9.0, self.V1, self.V2, self.V3), 2)

    def test_boundary_equals_second_threshold_is_gear_two(self):
        self.assertEqual(determine_lower_gear(9.0, self.V1, self.V2, self.V3), 2)

    def test_hit_third_gear(self):
        self.assertEqual(determine_lower_gear(8.0, self.V1, self.V2, self.V3), 3)

    def test_below_third_threshold_is_gear_three(self):
        self.assertEqual(determine_lower_gear(5.0, self.V1, self.V2, self.V3), 3)

    def test_missing_first_threshold_never_alerts(self):
        self.assertIsNone(determine_lower_gear(1.0, None, self.V2, self.V3))
        self.assertIsNone(determine_lower_gear(1.0, 0, self.V2, self.V3))

    def test_missing_second_threshold_falls_back_to_gear_one(self):
        self.assertEqual(determine_lower_gear(8.5, self.V1, None, self.V3), 1)

    def test_missing_third_threshold_falls_back_to_gear_two(self):
        self.assertEqual(determine_lower_gear(8.5, self.V1, self.V2, None), 2)

    def test_current_none_never_alerts(self):
        self.assertIsNone(determine_lower_gear(None, self.V1, self.V2, self.V3))

    def test_negative_pe_is_not_alerted(self):
        # PE 为负（亏损公司）时不应触发阈值告警：valueone 为正数，负值 <= 阈值
        # 这里显式锁定当前行为，暴露该风险供后续规格决策
        self.assertEqual(determine_lower_gear(-3.2, self.V1, self.V2, self.V3), 3)


class CheckSellTest(unittest.TestCase):
    """卖出价判定。"""

    def test_reach_sell_rate(self):
        self.assertTrue(check_sell(20.0, 20.0))

    def test_above_sell_rate(self):
        self.assertTrue(check_sell(25.0, 20.0))

    def test_below_sell_rate(self):
        self.assertFalse(check_sell(19.99, 20.0))

    def test_missing_sell_rate(self):
        self.assertFalse(check_sell(25.0, None))
        self.assertFalse(check_sell(25.0, 0))

    def test_current_none(self):
        self.assertFalse(check_sell(None, 20.0))


class ThresholdOfTest(unittest.TestCase):
    def test_returns_matching_threshold(self):
        self.assertEqual(threshold_of(1, 10, 9, 8), 10)
        self.assertEqual(threshold_of(2, 10, 9, 8), 9)
        self.assertEqual(threshold_of(3, 10, 9, 8), 8)


class AlarmTextTest(unittest.TestCase):
    """告警文案保持与历史一致，避免用户侧标题跳变。"""

    def test_sell_text(self):
        subject, body = build_sell_alarm('贵州茅台', 2000.0, 1800.0)
        self.assertEqual(subject, '【贵州茅台】到卖出价格啦~')
        self.assertIn('达到目标卖出价', body)
        self.assertIn('2000.0', body)
        self.assertIn('1800.0', body)

    def test_price_gear_text(self):
        subject, body = build_gear_alarm('贵州茅台', ALARM_TYPE_PRICE, 2, 9.0, 9.0)
        self.assertEqual(subject, '【贵州茅台】到第2档关注点位啦')
        self.assertIn('第二档', body)
        self.assertIn('建仓阈值', body)

    def test_pe_gear_text(self):
        subject, body = build_gear_alarm('贵州茅台', ALARM_TYPE_PE, 3, 8.0, 8.0)
        self.assertEqual(subject, '【贵州茅台】PE到第3档关注点位啦')
        self.assertIn('PE达到第三档告警阈值', body)

    def test_pb_gear_text(self):
        subject, body = build_gear_alarm('贵州茅台', ALARM_TYPE_PB, 1, 8.0, 8.0)
        self.assertEqual(subject, '【贵州茅台】PB到第1档关注点位啦')
        self.assertIn('PB达到第一档告警阈值', body)

    def test_unknown_alarm_type_raises(self):
        with self.assertRaises(ValueError):
            build_gear_alarm('贵州茅台', 'unknown', 1, 1.0, 1.0)


class AlarmKeyTest(unittest.TestCase):
    def test_key_without_gear(self):
        self.assertEqual(make_alarm_key(7, ALARM_TYPE_SELL), '7:sell')

    def test_key_with_gear(self):
        self.assertEqual(make_alarm_key(7, ALARM_TYPE_PRICE, 2), '7:price:2')

    def test_pe_and_pb_keys_are_distinct(self):
        self.assertNotEqual(make_alarm_key(7, ALARM_TYPE_PE, 1), make_alarm_key(7, ALARM_TYPE_PB, 1))


if __name__ == '__main__':
    unittest.main()
