"""
A 股交易时段判断。

用于监控服务在非交易时段降频轮询（D-04）。
仅覆盖 A 股常规交易时段，不含法定节假日日历；节假日按"非交易日"处理会退化为
低频轮询（不会漏告警），属于可接受的保守策略。
"""
from datetime import datetime, time as time_of_day

# 周一至周五为交易日
TRADING_WEEKDAYS = frozenset({0, 1, 2, 3, 4})

# 上午 9:30 - 11:30，下午 13:00 - 15:00（含边界）
MORNING_OPEN = time_of_day(9, 30)
MORNING_CLOSE = time_of_day(11, 30)
AFTERNOON_OPEN = time_of_day(13, 0)
AFTERNOON_CLOSE = time_of_day(15, 0)


def is_trading_day(moment=None):
    """是否为交易日（周一至周五）。"""
    moment = moment or datetime.now()
    return moment.weekday() in TRADING_WEEKDAYS


def is_trading_time(moment=None):
    """
    当前是否处于 A 股常规交易时段。

    :param moment: datetime 对象，缺省为当前时间
    :return: True 表示处于交易时段
    """
    moment = moment or datetime.now()
    if not is_trading_day(moment):
        return False

    current = moment.time()
    in_morning = MORNING_OPEN <= current <= MORNING_CLOSE
    in_afternoon = AFTERNOON_OPEN <= current <= AFTERNOON_CLOSE
    return in_morning or in_afternoon


def describe_session(moment=None):
    """
    返回当前时段的键名，用于日志与页面展示。

    :return: 'morning' / 'afternoon' / 'noon' / 'closed'
             - morning   早盘 9:30~11:30
             - afternoon 午盘 13:00~15:00
             - noon      午间休市 11:30~13:00（交易日）
             - closed    收盘后 / 盘前 / 非交易日（用 is_trading_day 再区分）
    """
    moment = moment or datetime.now()
    if not is_trading_day(moment):
        return 'closed'
    current = moment.time()
    if MORNING_OPEN <= current <= MORNING_CLOSE:
        return 'morning'
    if AFTERNOON_OPEN <= current <= AFTERNOON_CLOSE:
        return 'afternoon'
    if MORNING_CLOSE < current < AFTERNOON_OPEN:
        return 'noon'
    return 'closed'
