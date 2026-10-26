"""
交易时段判断测试（D-04）。
"""
import unittest
from datetime import datetime

from utils.trading_time import describe_session, is_trading_day, is_trading_time


def dt(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute)


class TradingDayTest(unittest.TestCase):
    def test_monday_is_trading_day(self):
        # 2026-10-19 是星期一
        self.assertTrue(is_trading_day(dt(2026, 10, 19, 10, 0)))

    def test_friday_is_trading_day(self):
        # 2026-10-23 是星期五
        self.assertTrue(is_trading_day(dt(2026, 10, 23, 10, 0)))

    def test_saturday_is_not_trading_day(self):
        # 2026-10-24 是星期六
        self.assertFalse(is_trading_day(dt(2026, 10, 24, 10, 0)))

    def test_sunday_is_not_trading_day(self):
        # 2026-10-25 是星期日
        self.assertFalse(is_trading_day(dt(2026, 10, 25, 10, 0)))


class TradingTimeTest(unittest.TestCase):
    # 2026-10-20 是星期二
    def test_before_open(self):
        self.assertFalse(is_trading_time(dt(2026, 10, 20, 9, 29)))

    def test_open_boundary(self):
        self.assertTrue(is_trading_time(dt(2026, 10, 20, 9, 30)))

    def test_mid_morning(self):
        self.assertTrue(is_trading_time(dt(2026, 10, 20, 10, 30)))

    def test_morning_close_boundary(self):
        self.assertTrue(is_trading_time(dt(2026, 10, 20, 11, 30)))

    def test_lunch_break(self):
        self.assertFalse(is_trading_time(dt(2026, 10, 20, 12, 0)))
        self.assertFalse(is_trading_time(dt(2026, 10, 20, 12, 59)))

    def test_afternoon_open_boundary(self):
        self.assertTrue(is_trading_time(dt(2026, 10, 20, 13, 0)))

    def test_afternoon_close_boundary(self):
        self.assertTrue(is_trading_time(dt(2026, 10, 20, 15, 0)))

    def test_after_close(self):
        self.assertFalse(is_trading_time(dt(2026, 10, 20, 15, 1)))

    def test_weekend_never_trading(self):
        self.assertFalse(is_trading_time(dt(2026, 10, 24, 10, 0)))


class DescribeSessionTest(unittest.TestCase):
    def test_morning(self):
        self.assertEqual(describe_session(dt(2026, 10, 20, 10, 0)), 'morning')

    def test_afternoon(self):
        self.assertEqual(describe_session(dt(2026, 10, 20, 14, 0)), 'afternoon')

    def test_noon_break(self):
        """11:30~13:00 为独立的「午间休市」档位（设计稿要单独显示），不再是 closed。

        变更见 spec/changes/2026-10-21-system-status-panels.md；
        describe_session 只用于展示，监控降频用的是 is_trading_time（未改动）。
        """
        self.assertEqual(describe_session(dt(2026, 10, 20, 12, 0)), 'noon')

    def test_closed_weekend(self):
        self.assertEqual(describe_session(dt(2026, 10, 24, 10, 0)), 'closed')


if __name__ == '__main__':
    unittest.main()
