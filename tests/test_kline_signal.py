"""
K 线均线信号判定测试（spec/current/005-kline-signal.md 验收条件）。

阈值：ma5 > ma30 * 1.03 → 金叉；ma5 < ma30 * 0.97 → 死叉；其余 → 震荡。
"""
import math
import unittest

from models.stock_kline import StockKline


class CheckSignalTest(unittest.TestCase):
    def test_golden_cross_above_3_percent(self):
        self.assertEqual(StockKline.check_signal(10.4, 9.0, 10.0), 'golden_cross')

    def test_golden_cross_boundary_is_exclusive(self):
        # ma5 == ma30 * 1.03 不构成"高于"，判为震荡
        self.assertEqual(StockKline.check_signal(10.3, 9.0, 10.0), 'normal')

    def test_just_above_boundary(self):
        self.assertEqual(StockKline.check_signal(10.31, 9.0, 10.0), 'golden_cross')

    def test_death_cross_below_3_percent(self):
        self.assertEqual(StockKline.check_signal(9.6, 9.0, 10.0), 'death_cross')

    def test_death_cross_boundary_is_exclusive(self):
        # ma5 == ma30 * 0.97 不构成"低于"
        self.assertEqual(StockKline.check_signal(9.7, 9.0, 10.0), 'normal')

    def test_just_below_boundary(self):
        self.assertEqual(StockKline.check_signal(9.69, 9.0, 10.0), 'death_cross')

    def test_normal_in_middle_band(self):
        self.assertEqual(StockKline.check_signal(10.1, 9.0, 10.0), 'normal')
        self.assertEqual(StockKline.check_signal(9.9, 9.0, 10.0), 'normal')

    def test_equal_mas_is_normal(self):
        self.assertEqual(StockKline.check_signal(10.0, 10.0, 10.0), 'normal')

    def test_ma10_not_used_for_decision(self):
        """MA10 只用于展示，改变它不应影响判定结果。"""
        self.assertEqual(StockKline.check_signal(10.4, 1.0, 10.0), 'golden_cross')
        self.assertEqual(StockKline.check_signal(10.4, 999.0, 10.0), 'golden_cross')

    def test_none_inputs_are_normal(self):
        self.assertEqual(StockKline.check_signal(None, 9.0, 10.0), 'normal')
        self.assertEqual(StockKline.check_signal(10.4, 9.0, None), 'normal')

    def test_nan_inputs_are_normal(self):
        """rolling 窗口不足时会产生 NaN，不能抛异常也不能误报信号。"""
        nan = float('nan')
        self.assertEqual(StockKline.check_signal(nan, 9.0, 10.0), 'normal')
        self.assertEqual(StockKline.check_signal(10.4, 9.0, nan), 'normal')
        self.assertEqual(StockKline.check_signal(nan, nan, nan), 'normal')

    def test_infinite_ma_is_handled(self):
        result = StockKline.check_signal(math.inf, 9.0, 10.0)
        self.assertEqual(result, 'golden_cross')


if __name__ == '__main__':
    unittest.main()
