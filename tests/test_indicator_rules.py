"""
指标判定规则测试（006 指标监控）。

覆盖：四条判定式与其相等边界、5 日倍数的两道护栏、NULL 不参与判定、
阈值解析、以及 config.py 默认值与 DEFAULT_THRESHOLDS 的一致性（防漂移）。
"""
import unittest

from config import Config
from utils.indicator_rules import (
    ALARM_SUBTYPES,
    DEFAULT_THRESHOLDS,
    SUBTYPE_COMBO,
    SUBTYPE_DRAWDOWN,
    SUBTYPE_LOW52W,
    SUBTYPE_RS20,
    SUBTYPE_RS5,
    SUBTYPES,
    build_indicator_alarm,
    check_drawdown,
    check_low52w,
    check_rs20,
    check_rs5,
    evaluate_indicators,
    hit_subtypes,
    is_combo_hit,
    n_day_return,
    pct_change,
    resolve_thresholds,
)


class PctChangeTest(unittest.TestCase):
    def test_normal(self):
        self.assertAlmostEqual(pct_change(110.0, 100.0), 10.0)

    def test_negative(self):
        self.assertAlmostEqual(pct_change(80.0, 100.0), -20.0)

    def test_missing_or_zero_base(self):
        self.assertIsNone(pct_change(None, 100.0))
        self.assertIsNone(pct_change(100.0, None))
        self.assertIsNone(pct_change(100.0, 0))

    def test_accepts_decimal_like_strings(self):
        self.assertAlmostEqual(pct_change('11', '10'), 10.0)


class NDayReturnTest(unittest.TestCase):
    """涨跌幅按「交易日条数」算：不足 N+1 条返回 None（新股保护）。"""

    def test_5_day_return(self):
        closes = [10.0] * 5 + [11.0]  # 第 6 条相对第 1 条
        self.assertAlmostEqual(n_day_return(closes, 5), 10.0)

    def test_20_day_return(self):
        closes = [10.0] * 20 + [8.0]
        self.assertAlmostEqual(n_day_return(closes, 20), -20.0)

    def test_insufficient_data_returns_none(self):
        """新股：只有 15 条时算不出 20 日收益，返回 None 而不是瞎算一个近似值。"""
        self.assertIsNone(n_day_return([10.0] * 15, 20))

    def test_empty_and_bad_params(self):
        self.assertIsNone(n_day_return([], 5))
        self.assertIsNone(n_day_return([1.0, 2.0], 0))
        self.assertIsNone(n_day_return([1.0, 2.0], None))
        self.assertIsNone(n_day_return([{'x': 1}], 5))


class Low52wTest(unittest.TestCase):
    def test_hit_at_exact_threshold(self):
        """边界取等号：距离恰好等于阈值即命中。"""
        self.assertTrue(check_low52w(105.0, 100.0, 5.0))

    def test_hit_below_threshold(self):
        self.assertTrue(check_low52w(102.0, 100.0, 5.0))

    def test_miss_above_threshold(self):
        self.assertFalse(check_low52w(106.0, 100.0, 5.0))

    def test_below_52w_low_still_hits(self):
        """盘中跌破 52 周低也算命中。"""
        self.assertTrue(check_low52w(98.0, 100.0, 5.0))

    def test_missing_data_returns_false(self):
        self.assertFalse(check_low52w(None, 100.0, 5.0))
        self.assertFalse(check_low52w(100.0, None, 5.0))
        self.assertFalse(check_low52w(100.0, 0, 5.0))
        self.assertFalse(check_low52w(100.0, 100.0, None))


class DrawdownTest(unittest.TestCase):
    def test_hit_at_exact_threshold(self):
        self.assertTrue(check_drawdown(65.0, 100.0, 35.0))

    def test_hit_deeper(self):
        self.assertTrue(check_drawdown(50.0, 100.0, 35.0))

    def test_miss_shallower(self):
        self.assertFalse(check_drawdown(66.0, 100.0, 35.0))

    def test_uptrend_not_drawdown(self):
        self.assertFalse(check_drawdown(120.0, 100.0, 35.0))

    def test_missing_data_returns_false(self):
        self.assertFalse(check_drawdown(None, 100.0, 35.0))
        self.assertFalse(check_drawdown(50.0, None, 35.0))
        self.assertFalse(check_drawdown(50.0, 0, 35.0))


class Rs20Test(unittest.TestCase):
    def test_hit_at_exact_threshold(self):
        self.assertTrue(check_rs20(-20.0, -5.0, 15.0))

    def test_hit_worse(self):
        self.assertTrue(check_rs20(-30.0, 0.0, 15.0))

    def test_miss_within_threshold(self):
        self.assertFalse(check_rs20(-14.9, 0.0, 15.0))

    def test_outperform_never_hits(self):
        self.assertFalse(check_rs20(10.0, -10.0, 15.0))

    def test_missing_either_side_returns_false(self):
        """基准没采集到，或个股不足交易日：都不参与判定（避免误报）。"""
        self.assertFalse(check_rs20(-20.0, None, 15.0))
        self.assertFalse(check_rs20(None, -5.0, 15.0))


class Rs5Test(unittest.TestCase):
    """5 日倍数 + 两道护栏（个股 ≥3%、基准 ≥0.5%）。"""

    def test_hit_at_exact_ratio(self):
        self.assertTrue(check_rs5(-7.5, -3.0, 2.5, 3.0, 0.5))

    def test_miss_below_ratio(self):
        self.assertFalse(check_rs5(-7.0, -3.0, 2.5, 3.0, 0.5))

    def test_guardrail_bench_drop_too_small(self):
        """横盘护栏：基准只跌 0.4%（< 0.5%）时即便倍数满足也不判定。"""
        self.assertFalse(check_rs5(-3.0, -0.4, 2.5, 3.0, 0.5))

    def test_guardrail_stock_drop_too_small(self):
        self.assertFalse(check_rs5(-2.9, -0.5, 2.5, 3.0, 0.5))

    def test_both_must_fall(self):
        self.assertFalse(check_rs5(5.0, -3.0, 2.5, 3.0, 0.5))
        self.assertFalse(check_rs5(-5.0, 3.0, 2.5, 3.0, 0.5))

    def test_missing_data_returns_false(self):
        self.assertFalse(check_rs5(None, -3.0, 2.5, 3.0, 0.5))
        self.assertFalse(check_rs5(-3.0, None, 2.5, 3.0, 0.5))

    def test_boundary_values_are_inclusive(self):
        self.assertTrue(check_rs5(-3.0, -1.2, 2.5, 3.0, 0.5))


class ComboHitTest(unittest.TestCase):
    """组合语义：四条之间是 AND，缺一条都不算（2026-10-23 起单条不再单独告警）。"""

    ALL_HIT = {
        SUBTYPE_LOW52W: True, SUBTYPE_DRAWDOWN: True,
        SUBTYPE_RS20: True, SUBTYPE_RS5: True,
    }

    def test_all_four_hits(self):
        self.assertTrue(is_combo_hit(self.ALL_HIT))

    def test_missing_one_is_not_combo(self):
        """AND 语义：任何一条不满足都不命中——这是本次变更的核心。"""
        for subtype in SUBTYPES:
            flags = dict(self.ALL_HIT)
            flags[subtype] = False
            self.assertFalse(is_combo_hit(flags), f'{subtype} 未命中却判为组合')

    def test_single_hit_is_not_combo(self):
        """只命中 52 周新低这种最宽松的一条，绝不能告警。"""
        for subtype in SUBTYPES:
            flags = {s: (s == subtype) for s in SUBTYPES}
            self.assertFalse(is_combo_hit(flags))

    def test_missing_data_is_not_combo(self):
        """缺数据的指标判 False → 基准未采集 / 新股都不会触发组合。"""
        flags = dict(self.ALL_HIT)
        flags[SUBTYPE_RS20] = None
        self.assertFalse(is_combo_hit(flags))

    def test_empty_flags_are_false(self):
        self.assertFalse(is_combo_hit(None))
        self.assertFalse(is_combo_hit({}))

    def test_combo_is_not_an_atomic_subtype(self):
        """combo 不是第五条判据：不能被 hit_subtypes / 逐项判定当成指标。"""
        self.assertNotIn(SUBTYPE_COMBO, SUBTYPES)
        self.assertIn(SUBTYPE_COMBO, ALARM_SUBTYPES)
        self.assertEqual(hit_subtypes({SUBTYPE_COMBO: True}), [])


class ThresholdResolveTest(unittest.TestCase):
    def test_defaults_when_no_override(self):
        self.assertEqual(resolve_thresholds(None)['low52w_near_pct'], 5.0)

    def test_override_applied(self):
        resolved = resolve_thresholds({'low52w_near_pct': 8.0, 'rs20_pct': 20.0})
        self.assertEqual(resolved['low52w_near_pct'], 8.0)
        self.assertEqual(resolved['rs20_pct'], 20.0)
        self.assertEqual(resolved['drawdown_52w_pct'], 35.0)  # 未覆盖的继承

    def test_null_override_keeps_global(self):
        resolved = resolve_thresholds({'rs5_ratio': None})
        self.assertEqual(resolved['rs5_ratio'], DEFAULT_THRESHOLDS['rs5_ratio'])

    def test_custom_defaults(self):
        resolved = resolve_thresholds(None, defaults={'low52w_near_pct': 1.0})
        self.assertEqual(resolved['low52w_near_pct'], 1.0)


class EvaluateTest(unittest.TestCase):
    def test_metrics_and_flags(self):
        result = evaluate_indicators({
            'price': 70.0, 'high52w': 100.0, 'low52w': 68.0,
            'ret_5d': -8.0, 'ret_20d': -20.0,
            'bench_ret_5d': -2.0, 'bench_ret_20d': -2.0,
        })
        self.assertAlmostEqual(result['pct_from_low52w'], 2.94, places=2)
        self.assertAlmostEqual(result['drawdown_52w'], -30.0)
        self.assertAlmostEqual(result['rs_20d'], -18.0)
        self.assertAlmostEqual(result['rs_5d_ratio'], 4.0)
        self.assertTrue(result['flags'][SUBTYPE_LOW52W])
        self.assertTrue(result['flags'][SUBTYPE_RS20])
        self.assertTrue(result['flags'][SUBTYPE_RS5])
        self.assertFalse(result['flags'][SUBTYPE_DRAWDOWN])

    def test_combo_hit_only_when_all_four(self):
        """四项全中才 True；把回撤改回 30%（不达 35%）立刻变 False。"""
        snapshot = {
            'price': 61.0, 'high52w': 100.0, 'low52w': 60.0,
            'ret_5d': -8.0, 'ret_20d': -20.0,
            'bench_ret_5d': -2.0, 'bench_ret_20d': -2.0,
        }
        self.assertTrue(evaluate_indicators(snapshot)['combo_hit'])
        self.assertTrue(all(evaluate_indicators(snapshot)['flags'].values()))

        # 只把回撤改浅（-32.2%，未达 -35%）：其余三条仍命中，但组合必须 False
        partial = dict(snapshot, high52w=90.0)
        flags = evaluate_indicators(partial)['flags']
        self.assertTrue(flags[SUBTYPE_LOW52W] and flags[SUBTYPE_RS20] and flags[SUBTYPE_RS5])
        self.assertFalse(flags[SUBTYPE_DRAWDOWN])
        self.assertFalse(evaluate_indicators(partial)['combo_hit'])

    def test_combo_false_in_existing_metrics_case(self):
        """本用例的 drawdown 只有 -30%，单看 flags 有 3 条命中，但组合必须 False。"""
        result = evaluate_indicators({
            'price': 70.0, 'high52w': 100.0, 'low52w': 68.0,
            'ret_5d': -8.0, 'ret_20d': -20.0,
            'bench_ret_5d': -2.0, 'bench_ret_20d': -2.0,
        })
        self.assertEqual(len(hit_subtypes(result['flags'])), 3)
        self.assertFalse(result['combo_hit'])

    def test_new_stock_no_20d_flag(self):
        """ret_20d 为 None（上市不足 20 个交易日）→ 20 日指标必须不命中。"""
        result = evaluate_indicators({
            'price': 70.0, 'high52w': 100.0, 'low52w': 68.0,
            'ret_5d': -8.0, 'ret_20d': None,
            'bench_ret_5d': -2.0, 'bench_ret_20d': None,
        })
        self.assertFalse(result['flags'][SUBTYPE_RS20])
        self.assertIsNone(result['rs_20d'])

    def test_no_bench_data_disables_relative_metrics(self):
        result = evaluate_indicators({
            'price': 70.0, 'high52w': 100.0, 'low52w': 68.0,
            'ret_5d': -8.0, 'ret_20d': -20.0,
            'bench_ret_5d': None, 'bench_ret_20d': None,
        })
        self.assertFalse(result['flags'][SUBTYPE_RS20])
        self.assertFalse(result['flags'][SUBTYPE_RS5])
        self.assertTrue(result['flags'][SUBTYPE_LOW52W])

    def test_empty_snapshot_no_flags(self):
        self.assertEqual(hit_subtypes(evaluate_indicators(None)['flags']), [])

    def test_hit_subtypes_order(self):
        flags = {
            SUBTYPE_RS5: True, SUBTYPE_LOW52W: True,
            SUBTYPE_RS20: False, SUBTYPE_DRAWDOWN: True,
        }
        self.assertEqual(hit_subtypes(flags),
                         [SUBTYPE_LOW52W, SUBTYPE_DRAWDOWN, SUBTYPE_RS5])


class AlarmTextTest(unittest.TestCase):
    METRICS = {
        'price': 70.0, 'high52w': 100.0, 'low52w': 68.0,
        'pct_from_low52w': 2.94, 'drawdown_52w': -30.0,
        'ret_5d': -8.0, 'ret_20d': -20.0,
        'bench_ret_5d': -2.0, 'bench_ret_20d': -2.0,
        'rs_20d': -18.0, 'rs_5d_ratio': 4.0,
    }

    def test_all_subtypes_produce_text(self):
        for subtype in SUBTYPES:
            subject, body = build_indicator_alarm('测试股', subtype, self.METRICS)
            self.assertIn('测试股', subject)
            self.assertIn('测试股', body)
            self.assertTrue(subject.startswith('【测试股】'))

    def test_subtype_in_body(self):
        _, body = build_indicator_alarm('测试股', SUBTYPE_LOW52W, self.METRICS)
        self.assertIn('52 周最低', body)
        _, body = build_indicator_alarm('测试股', SUBTYPE_DRAWDOWN, self.METRICS)
        self.assertIn('回撤', body)
        _, body = build_indicator_alarm('测试股', SUBTYPE_RS20, self.METRICS)
        self.assertIn('基准', body)
        _, body = build_indicator_alarm('测试股', SUBTYPE_RS5, self.METRICS)
        self.assertIn('倍数', body)

    def test_combo_text_lists_all_four(self):
        """一条邮件必须交代四项：收到邮件不用再去页面核对为什么被筛出来。"""
        subject, body = build_indicator_alarm('测试股', SUBTYPE_COMBO, self.METRICS,
                                              bench_code='SH000300')
        self.assertIn('同时', subject)
        self.assertIn('SH000300', body)
        for token in ('距 52 周低', '52 周回撤', '20 日跑输', '5 日倍数'):
            self.assertIn(token, body)
        for threshold in ('5.00%', '-35.00%', '-15.00%', '2.50 倍'):
            self.assertIn(threshold, body)

    def test_combo_metrics_missing_does_not_raise(self):
        subject, body = build_indicator_alarm('测试股', SUBTYPE_COMBO, {})
        self.assertIn('测试股', subject)
        self.assertIn('—', body)

    def test_bench_code_shown(self):
        _, body = build_indicator_alarm('测试股', SUBTYPE_RS20, self.METRICS,
                                        bench_code='SH000300')
        self.assertIn('SH000300', body)

    def test_empty_metrics_does_not_raise(self):
        subject, body = build_indicator_alarm('测试股', SUBTYPE_LOW52W, {})
        self.assertIn('测试股', subject)
        self.assertIn('—', body)

    def test_unknown_subtype_raises(self):
        with self.assertRaises(ValueError):
            build_indicator_alarm('测试股', 'BAD', self.METRICS)


class ConfigDefaultConsistencyTest(unittest.TestCase):
    """config.py 的默认值必须与判定模块一致，否则单例 Ment 与降级行为会漂移。"""

    def test_config_matches_default_thresholds(self):
        for key, value in (
            ('low52w_near_pct', Config.IND_LOW52W_NEAR_PCT),
            ('drawdown_52w_pct', Config.IND_DRAWDOWN_52W_PCT),
            ('rs20_pct', Config.IND_RS20_PCT),
            ('rs5_ratio', Config.IND_RS5_RATIO),
            ('rs5_min_drop_pct', Config.IND_RS5_MIN_DROP_PCT),
            ('rs5_min_bench_drop_pct', Config.IND_RS5_MIN_BENCH_DROP_PCT),
        ):
            self.assertEqual(DEFAULT_THRESHOLDS[key], value, f'不一致的配置项: {key}')

    def test_bench_and_cooldown_defaults(self):
        self.assertEqual(Config.IND_BENCH, 'SH000300')
        self.assertEqual(Config.IND_COOLDOWN_HOURS, 24)


if __name__ == '__main__':
    unittest.main()
