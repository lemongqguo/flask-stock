"""
告警冷却（去重）机制。

背景（D-03）：原实现中，只要阈值条件持续满足，每个监控循环都会重复写入
一条告警记录并重复发送邮件。本模块提供基于 key 的冷却窗口，保证
"同一订单 + 同一告警类型（+ 同一档位）在冷却期内只告警一次"。

约束：状态保存在进程内存中。应用为单进程 + 单监控线程的场景下有效；
若将来多进程部署，需把 last_fired 落到数据库或 Redis。
"""
import threading
import time


class AlarmThrottle:
    """线程安全的告警冷却器。"""

    def __init__(self, cooldown_seconds=14400, clock=time.time):
        """
        :param cooldown_seconds: 冷却窗口（秒）。<=0 表示不限制（每次都放行）。
        :param clock: 时间源，测试时可注入假时钟。
        """
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._last_fired = {}
        self._lock = threading.Lock()

    def should_fire(self, key):
        """
        判断是否允许触发告警；允许时同时记录触发时间。

        :param key: 由 alarm_rules.make_alarm_key 生成的唯一 key
        :return: True 表示本次应产生告警
        """
        if self.cooldown_seconds <= 0:
            return True

        now = self._clock()
        with self._lock:
            last = self._last_fired.get(key)
            if last is not None and (now - last) < self.cooldown_seconds:
                return False
            self._last_fired[key] = now
            return True

    def clear(self, key):
        """
        清除某个 key 的冷却记录。

        当告警条件消失时调用，使条件再次满足时能立即重新告警，
        而不是继续被冷却窗口挡住。
        """
        with self._lock:
            self._last_fired.pop(key, None)

    def clear_prefix(self, prefix):
        """清除某个订单下所有以 prefix 开头的 key（例如 stock_id 全部档位）。"""
        with self._lock:
            for key in [k for k in self._last_fired if k.startswith(prefix)]:
                del self._last_fired[key]

    def reset(self):
        """清空全部冷却记录。"""
        with self._lock:
            self._last_fired.clear()

    def stats(self):
        """返回当前处于冷却中的 key 与剩余秒数，便于页面展示与排障。"""
        now = self._clock()
        with self._lock:
            return {
                key: round(self.cooldown_seconds - (now - fired), 1)
                for key, fired in self._last_fired.items()
                if self.cooldown_seconds - (now - fired) > 0
            }
