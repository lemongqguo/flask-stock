"""
告警冷却（D-03）测试：条件持续满足时不得重复产生告警。
"""
import unittest

from utils.alarm_throttle import AlarmThrottle


class FakeClock:
    """可手动推进的假时钟，避免测试真的 sleep。"""

    def __init__(self, start=1_000_000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class AlarmThrottleTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.throttle = AlarmThrottle(cooldown_seconds=3600, clock=self.clock)

    def test_first_call_allowed(self):
        self.assertTrue(self.throttle.should_fire('1:price:1'))

    def test_repeat_within_cooldown_blocked(self):
        self.assertTrue(self.throttle.should_fire('1:price:1'))
        for _ in range(10):
            self.assertFalse(self.throttle.should_fire('1:price:1'))

    def test_allowed_again_after_cooldown(self):
        self.assertTrue(self.throttle.should_fire('1:price:1'))
        self.clock.advance(3599)
        self.assertFalse(self.throttle.should_fire('1:price:1'))
        self.clock.advance(2)
        self.assertTrue(self.throttle.should_fire('1:price:1'))

    def test_different_gears_are_independent(self):
        self.assertTrue(self.throttle.should_fire('1:price:1'))
        self.assertTrue(self.throttle.should_fire('1:price:2'))
        self.assertTrue(self.throttle.should_fire('1:pe:1'))

    def test_different_stocks_are_independent(self):
        self.assertTrue(self.throttle.should_fire('1:price:1'))
        self.assertTrue(self.throttle.should_fire('2:price:1'))

    def test_clear_allows_immediate_refire(self):
        """条件消失后再满足，应立即重新告警，而不是继续被冷却挡住。"""
        self.assertTrue(self.throttle.should_fire('1:price:1'))
        self.throttle.clear('1:price:1')
        self.assertTrue(self.throttle.should_fire('1:price:1'))

    def test_clear_prefix_clears_all_gears_of_one_metric(self):
        self.assertTrue(self.throttle.should_fire('1:price:1'))
        self.assertTrue(self.throttle.should_fire('1:price:2'))
        self.assertTrue(self.throttle.should_fire('1:pe:1'))

        self.throttle.clear_prefix('1:price:')

        self.assertTrue(self.throttle.should_fire('1:price:1'))
        self.assertTrue(self.throttle.should_fire('1:price:2'))
        self.assertFalse(self.throttle.should_fire('1:pe:1'))

    def test_clear_prefix_does_not_touch_other_stock(self):
        self.assertTrue(self.throttle.should_fire('1:price:1'))
        self.throttle.clear_prefix('2:price:')
        self.assertFalse(self.throttle.should_fire('1:price:1'))

    def test_zero_cooldown_always_allows(self):
        throttle = AlarmThrottle(cooldown_seconds=0, clock=self.clock)
        for _ in range(5):
            self.assertTrue(throttle.should_fire('1:price:1'))

    def test_negative_cooldown_always_allows(self):
        throttle = AlarmThrottle(cooldown_seconds=-1, clock=self.clock)
        self.assertTrue(throttle.should_fire('1:price:1'))
        self.assertTrue(throttle.should_fire('1:price:1'))

    def test_reset_clears_everything(self):
        self.assertTrue(self.throttle.should_fire('1:price:1'))
        self.assertTrue(self.throttle.should_fire('2:pe:3'))
        self.throttle.reset()
        self.assertTrue(self.throttle.should_fire('1:price:1'))
        self.assertTrue(self.throttle.should_fire('2:pe:3'))

    def test_stats_reports_remaining_seconds(self):
        self.throttle.should_fire('1:price:1')
        self.clock.advance(600)
        stats = self.throttle.stats()
        self.assertIn('1:price:1', stats)
        self.assertAlmostEqual(stats['1:price:1'], 3000, delta=1)

    def test_stats_drops_expired_keys(self):
        self.throttle.should_fire('1:price:1')
        self.clock.advance(7200)
        self.assertEqual(self.throttle.stats(), {})


if __name__ == '__main__':
    unittest.main()
