"""
告警类型字段测试（CHG-1）。

覆盖：存量文本归类、档位解析、带 subtype 的冷却 key、create/update 参数与异常路径、
存量回填函数。
"""
import unittest
from unittest import mock

from database import _backfill_alarm_types
from models.stock_alarm import StockAlarm
from utils.alarm_rules import (
    ALARM_TYPE_INDICATOR,
    ALARM_TYPE_PB,
    ALARM_TYPE_PE,
    ALARM_TYPE_PRICE,
    ALARM_TYPE_SELL,
    ALARM_TYPE_UNKNOWN,
    NOTIFY_FAILED,
    NOTIFY_PENDING,
    NOTIFY_SENT,
    NOTIFY_SKIPPED,
    NOTIFY_UNKNOWN,
    classify_alarm_text,
    make_alarm_key,
    parse_gear_from_text,
)
from utils.alarm_throttle import AlarmThrottle


class ParseGearTest(unittest.TestCase):
    """从历史文本中提取档位。"""

    def test_chinese_and_digits(self):
        self.assertEqual(parse_gear_from_text('达到第一档建仓阈值'), 1)
        self.assertEqual(parse_gear_from_text('达到第二档建仓阈值'), 2)
        self.assertEqual(parse_gear_from_text('达到第三档建仓阈值'), 3)
        self.assertEqual(parse_gear_from_text('PE到第3档关注点位啦'), 3)

    def test_missing_or_empty(self):
        self.assertIsNone(parse_gear_from_text('没有档位信息'))
        self.assertIsNone(parse_gear_from_text(''))
        self.assertIsNone(parse_gear_from_text(None))


class ClassifyAlarmTextTest(unittest.TestCase):
    """存量告警文本归类：可识别的归类，不可识别的落 unknown（不猜测）。"""

    def test_sell(self):
        self.assertEqual(
            classify_alarm_text('【贵州茅台】达到目标卖出价！当前价格: 1800，目标卖出价: 1750'),
            (ALARM_TYPE_SELL, None),
        )

    def test_pe_with_gear(self):
        text = '【宁德时代】PE达到第二档告警阈值！当前PE: 20.5，第二档阈值: 25'
        self.assertEqual(classify_alarm_text(text), (ALARM_TYPE_PE, 2))

    def test_pb_with_gear(self):
        text = '【招商银行】PB达到第一档告警阈值！当前PB: 0.8，第一档阈值: 1.0'
        self.assertEqual(classify_alarm_text(text), (ALARM_TYPE_PB, 1))

    def test_price_with_gear(self):
        text = '【隆基绿能】达到第三档建仓阈值！当前价格: 15.2，第三档阈值: 16'
        self.assertEqual(classify_alarm_text(text), (ALARM_TYPE_PRICE, 3))

    def test_unrecognizable_falls_back_to_unknown(self):
        """无法识别时必须是 unknown，不得猜测成 price。"""
        self.assertEqual(classify_alarm_text('行情刷新失败'), (ALARM_TYPE_UNKNOWN, None))
        self.assertEqual(classify_alarm_text(''), (ALARM_TYPE_UNKNOWN, None))
        self.assertEqual(classify_alarm_text(None), (ALARM_TYPE_UNKNOWN, None))

    def test_sell_takes_precedence_over_gear_text(self):
        """卖出文案里即便提到档位，也归类为 sell。"""
        text = '【平安银行】到卖出价格啦，第1档已达成'
        self.assertEqual(classify_alarm_text(text), (ALARM_TYPE_SELL, None))


class AlarmKeyWithSubtypeTest(unittest.TestCase):
    """指标类用 subtype 生成冷却 key，4 种指标互不遮挡。"""

    def test_subtype_key(self):
        self.assertEqual(
            make_alarm_key(12, ALARM_TYPE_INDICATOR, subtype='drawdown'),
            '12:indicator:drawdown',
        )

    def test_gear_key_unchanged(self):
        """价格/估值的既有 key 格式必须保持兼容。"""
        self.assertEqual(make_alarm_key(7, ALARM_TYPE_PRICE, 2), '7:price:2')
        self.assertEqual(make_alarm_key(7, ALARM_TYPE_SELL), '7:sell')

    def test_four_indicators_are_distinct(self):
        keys = {
            make_alarm_key(12, ALARM_TYPE_INDICATOR, subtype=name)
            for name in ('low52w', 'drawdown', 'rs20', 'rs5')
        }
        self.assertEqual(len(keys), 4)

    def test_indicators_do_not_block_each_other(self):
        """同一订单的 4 种指标应各自独立冷却。"""
        throttle = AlarmThrottle(cooldown_seconds=3600)
        self.assertTrue(throttle.should_fire(make_alarm_key(12, ALARM_TYPE_INDICATOR, subtype='rs20')))
        self.assertFalse(throttle.should_fire(make_alarm_key(12, ALARM_TYPE_INDICATOR, subtype='rs20')))
        self.assertTrue(throttle.should_fire(make_alarm_key(12, ALARM_TYPE_INDICATOR, subtype='rs5')))


class StockAlarmCreateTest(unittest.TestCase):
    """create 需把类型字段写入，并返回自增 id。"""

    def test_create_passes_type_fields(self):
        with mock.patch.object(StockAlarm, 'execute_insert', return_value=42) as ins:
            alarm_id = StockAlarm.create(
                1, '正文',
                alarm_type=ALARM_TYPE_INDICATOR,
                alarm_subtype='drawdown',
                alarm_level=None,
            )
        self.assertEqual(alarm_id, 42)
        sql, params = ins.call_args[0][0], ins.call_args[0][1]
        self.assertIn('alarm_type', sql)
        self.assertIn('notify_status', sql)
        self.assertEqual(params[0], 1)
        self.assertEqual(params[1], '正文')
        self.assertEqual(params[2], ALARM_TYPE_INDICATOR)
        self.assertEqual(params[3], 'drawdown')
        self.assertEqual(params[5], NOTIFY_PENDING)

    def test_create_defaults_to_pending(self):
        with mock.patch.object(StockAlarm, 'execute_insert', return_value=1) as ins:
            StockAlarm.create(1, '正文')
        self.assertEqual(ins.call_args[0][1][5], NOTIFY_PENDING)

    def test_create_returns_none_on_error(self):
        with mock.patch.object(StockAlarm, 'execute_insert', side_effect=RuntimeError('boom')):
            self.assertIsNone(StockAlarm.create(1, '正文'))


class UpdateNotifyStatusTest(unittest.TestCase):
    """邮件结果回写。"""

    def test_empty_id_short_circuits(self):
        with mock.patch.object(StockAlarm, 'execute_update') as upd:
            self.assertFalse(StockAlarm.update_notify_status(None, NOTIFY_SENT))
        upd.assert_not_called()

    def test_updates_with_status(self):
        with mock.patch.object(StockAlarm, 'execute_update', return_value=1) as upd:
            self.assertTrue(StockAlarm.update_notify_status(9, NOTIFY_FAILED))
        params = upd.call_args[0][1]
        self.assertEqual(params, (NOTIFY_FAILED, 9))

    def test_returns_false_on_error(self):
        with mock.patch.object(StockAlarm, 'execute_update', side_effect=RuntimeError('boom')):
            self.assertFalse(StockAlarm.update_notify_status(9, NOTIFY_SENT))


class BackfillAlarmTypesTest(unittest.TestCase):
    """存量回填：按文本归类，不可识别落 unknown，且可重复执行。"""

    def _fake_conn(self, rows):
        conn = mock.MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = rows
        return conn

    def test_backfills_recognizable_rows(self):
        conn = self._fake_conn([{'id': 1, 'alarm_text': '【A】达到第二档建仓阈值！当前价格: 1'}])
        updated = _backfill_alarm_types(conn)
        self.assertEqual(updated, 1)
        cursor = conn.cursor.return_value.__enter__.return_value
        sql, params = cursor.execute.call_args_list[-1][0]
        self.assertIn('UPDATE stock_alarm', sql)
        self.assertEqual(params[0], ALARM_TYPE_PRICE)
        self.assertEqual(params[1], 2)
        self.assertEqual(params[2], NOTIFY_UNKNOWN)

    def test_backfills_unrecognizable_as_unknown(self):
        conn = self._fake_conn([{'id': 2, 'alarm_text': '未知格式的旧记录'}])
        _backfill_alarm_types(conn)
        cursor = conn.cursor.return_value.__enter__.return_value
        self.assertEqual(cursor.execute.call_args_list[-1][0][1][0], ALARM_TYPE_UNKNOWN)

    def test_no_pending_rows_is_noop(self):
        conn = self._fake_conn([])
        self.assertEqual(_backfill_alarm_types(conn), 0)

    def test_failure_does_not_raise(self):
        """回填失败不应阻断启动。"""
        conn = mock.MagicMock()
        conn.cursor.side_effect = RuntimeError('db down')
        self.assertEqual(_backfill_alarm_types(conn), 0)


class NotifyStatusConstantTest(unittest.TestCase):
    """状态常量与 skipped 语义（邮件关闭/无收件人不得误记为 failed）。"""

    def test_status_values(self):
        self.assertEqual(
            {NOTIFY_PENDING, NOTIFY_SENT, NOTIFY_FAILED, NOTIFY_SKIPPED, NOTIFY_UNKNOWN},
            {'pending', 'sent', 'failed', 'skipped', 'unknown'},
        )


if __name__ == '__main__':
    unittest.main()
