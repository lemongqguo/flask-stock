"""
监控服务模型（后台轮询线程）。

本轮修复内容（详见 spec/PROGRESS.md）：
- D-02 收件人为空导致邮件必失败：改为读取环境变量并做发送前校验。
- D-03 阈值持续满足时重复告警：引入 AlarmThrottle 冷却机制。
- D-04 非交易时段仍高频轮询：非交易时段降频休眠。
- D-05 重启/reloader 下可能拉起多个线程：加锁 + 存活检查，重复启动直接拒绝。
- D-11 异常被 print 吞掉：统一 logger.exception，删除散落 print。
"""
import concurrent.futures
import logging
import os
import random
import threading
import time

import pysnowball as ball

from config import Config, XueqiuToken
from models.account_settings import (
    UserNotifyPref,
    notify_enabled,
    prefs_for_user,
    recipients_for_user,
    resolve_alarm_recipients,
    resolve_bench_code,
)
from models.stock_master import StockMaster
from models.stock_warehouse import StockWarehouse
from models.stock_pe import StockPe
from models.stock_pb import StockPb
from models.stock_alarm import StockAlarm
from models.stock_indicator import StockBenchKline, StockIndicator, StockIndicatorConfig
from models.stock_kline import StockKline
from utils.alarm_rules import (
    ALARM_TYPE_INDICATOR,
    ALARM_TYPE_PB,
    ALARM_TYPE_PE,
    ALARM_TYPE_PRICE,
    ALARM_TYPE_SELL,
    NOTIFY_FAILED,
    NOTIFY_SENT,
    NOTIFY_SKIPPED,
    alarm_key_prefix,
    build_daily_summary,
    build_gear_alarm,
    build_sell_alarm,
    check_sell,
    determine_lower_gear,
    make_alarm_key,
    threshold_of,
)
from utils.alarm_throttle import AlarmThrottle
from utils.indicator_rules import (
    DEFAULT_BENCH_CODE,
    DEFAULT_THRESHOLDS,
    SUBTYPE_COMBO,
    build_indicator_alarm,
    is_combo_hit,
    n_day_return,
)
from utils.mail_sender import send_mail
from utils.snowball_errors import describe as describe_xueqiu_error
from utils.snowball_errors import parse_xueqiu_error, should_backoff
from utils.trading_time import describe_session, is_trading_time

logger = logging.getLogger(__name__)


class StockMonitor:
    def __init__(self, config=None):
        self.config = config or Config
        self.is_running = False
        self.monitor_thread = None
        self._stop_event = threading.Event()
        self._start_lock = threading.Lock()
        self._throttle = AlarmThrottle(cooldown_seconds=self.config.ALARM_COOLDOWN_SECONDS)
        # 同一雪球错误码的提示节流：避免 Token 失效时每只股票打一条日志
        self._notice_throttle = AlarmThrottle(
            cooldown_seconds=self.config.XUEQIU_NOTICE_INTERVAL
        )
        # 指标类独立冷却（默认 24h）：52 周回撤 >35% 是持续状态，用价格告警的 4h 会连发数日
        # （测试用的最小配置对象可能不含指标项，故走 getattr 兜底）
        indicator_hours = getattr(self.config, 'IND_COOLDOWN_HOURS', 24)
        self._indicator_throttle = AlarmThrottle(cooldown_seconds=max(0, int(indicator_hours)) * 3600)
        # 雪球退避：Token 失效/限流期间不再请求，避免无谓消耗与日志刷屏
        self._xueqiu_backoff_until = 0.0
        self._xueqiu_backoff_reason = ''

        # 线程池复用并在停止时 shutdown(wait=False, cancel_futures=True)：
        # 非 daemon 工作线程会让进程在 Ctrl+C 后卡在 join 上（见 utils/shutdown.py）
        self._executor = None
        self._executor_lock = threading.Lock()
        # 基准指数日线每交易日只需同步一次，这里记住上次同步日期
        self._bench_synced_date = None
        # 生效基准指数（账户设置 > IND_BENCH > 沪深300）：_check_indicators 每只股票都会问一次，
        # 直接打库会放大成 N 次查询，故缓存 60 秒（改设置后一分钟内生效）
        self._bench_code_cache = None
        self._bench_code_cached_at = 0.0
        # 每日汇总邮件：每个自然日只发一次
        self._daily_summary_date = None
        # 同一轮内按股票代码共享外部结果（2026-10-26 方案 A）：
        # 同一只票被多个用户各持有一条时，不应对雪球重复请求
        self._round_lock = threading.Lock()
        self._round_cache = {'quote': {}, 'kline': {}}
        self._round_pending = {}
        self.stats = {
            'rounds': 0,
            'checks': 0,
            'alarms': 0,
            'errors': 0,
            'last_round_at': None,
            'daily_summary': None,
        }

    # ------------------------------------------------------------------
    # 雪球退避
    # ------------------------------------------------------------------
    def _xueqiu_backoff_remaining(self):
        """退避剩余秒数，0 表示未退避。"""
        return max(0.0, self._xueqiu_backoff_until - time.time())

    @property
    def xueqiu_backoff_remaining(self):
        return self._xueqiu_backoff_remaining()

    def _enter_xueqiu_backoff(self, reason):
        seconds = max(0, self.config.XUEQIU_BACKOFF_SECONDS)
        if seconds <= 0 or self._xueqiu_backoff_remaining() > 0:
            return
        self._xueqiu_backoff_until = time.time() + seconds
        self._xueqiu_backoff_reason = reason
        logger.warning('%s；已暂停请求雪球 %s 秒（可用 XUEQIU_BACKOFF_SECONDS 调整）', reason, seconds)

    def _handle_xueqiu_error(self, stock_code, exc):
        """
        处理雪球接口错误：业务错误只提示，不打堆栈；未知错误才记 exception。

        :return: True 表示已识别为业务错误（调用方无需额外处理）
        """
        code, description = parse_xueqiu_error(exc)
        if code is None:
            logger.exception('获取行情失败（未知异常）stock=%s', stock_code)
            return False

        if should_backoff(code):
            self._enter_xueqiu_backoff(describe_xueqiu_error(code, description))
            return True

        # 非退避类业务错误（如代码不存在）：按错误码节流提示
        if self._notice_throttle.should_fire(f'xueqiu:{code}'):
            logger.warning(
                '%s stock=%s', describe_xueqiu_error(code, description), stock_code
            )
        return True

    # ------------------------------------------------------------------
    # 线程生命周期
    # ------------------------------------------------------------------
    def start_monitoring(self):
        """
        启动监控线程。已运行时直接返回 False，保证全局只有一个监控线程（D-05）。
        """
        with self._start_lock:
            if self.monitor_thread and self.monitor_thread.is_alive():
                logger.warning('监控线程已在运行（pid=%s），忽略重复启动请求', os.getpid())
                return False

            self._stop_event.clear()
            self.is_running = True
            self.monitor_thread = threading.Thread(
                target=self.monitor_loop, name='stock-monitor', daemon=True
            )
            self.monitor_thread.start()
            logger.info('股票监控已启动 pid=%s thread=%s', os.getpid(), self.monitor_thread.name)
            return True

    def stop_monitoring(self, join_timeout=5):
        """
        停止监控线程并释放线程池。

        :param join_timeout: 等待监控线程退出的秒数；超时不阻塞调用方
        """
        with self._start_lock:
            if not self.is_running:
                self.shutdown_executor()
                return False
            self.is_running = False
            self._stop_event.set()

        # 先取消尚未开始的任务，让工作线程尽快退出
        self.shutdown_executor()

        thread = self.monitor_thread
        if thread and thread.is_alive():
            thread.join(timeout=join_timeout)
            if thread.is_alive():
                logger.warning('监控线程 %s 秒内未退出，将由退出看门狗处理', join_timeout)
        logger.info('股票监控已停止')
        return True

    # ------------------------------------------------------------------
    # 线程池
    # ------------------------------------------------------------------
    def _get_executor(self):
        """懒创建线程池（重启监控后可复用新的池）。"""
        with self._executor_lock:
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=self.config.MONITOR_MAX_WORKERS,
                    thread_name_prefix='monitor-worker',
                )
            return self._executor

    def shutdown_executor(self, wait=False):
        """
        关闭线程池并取消排队任务。

        ``cancel_futures=True`` 只丢弃**尚未开始**的任务；已经在跑的任务仍要自己返回，
        所以非 daemon 工作线程未必立刻消失（这也是为什么还需要 ``utils/shutdown`` 的看门狗）。
        真正让运行中任务快速返回的是两件事：
        - 休眠走 ``_stop_event.wait()``，收到停止信号立即返回；
        - 网络调用受 ``SOCKET_TIMEOUT`` 兜底，不会永久挂起。
        """
        with self._executor_lock:
            executor, self._executor = self._executor, None

        if executor is None:
            return False
        try:
            executor.shutdown(wait=wait, cancel_futures=True)
        except TypeError:  # Python < 3.9 不支持 cancel_futures
            executor.shutdown(wait=wait)
        return True

    def get_status(self):
        """返回监控运行状态，供页面展示与排障。"""
        return {
            'running': self.is_running,
            'thread_alive': bool(self.monitor_thread and self.monitor_thread.is_alive()),
            'in_trading_hours': is_trading_time(),
            'session': describe_session(),
            'cooldown_seconds': self.config.ALARM_COOLDOWN_SECONDS,
            'indicator_cooldown_seconds': self._indicator_throttle.cooldown_seconds,
            # 与发信同源：页面/接口看到的收件人数就是真正会收到邮件的人数
            'recipients': len(resolve_alarm_recipients()['recipients']),
            'xueqiu_backoff_remaining': int(self._xueqiu_backoff_remaining()),
            'xueqiu_backoff_reason': self._xueqiu_backoff_reason,
            'stats': dict(self.stats),
        }

    def _sleep(self, seconds):
        """可被停止信号打断的休眠。返回 True 表示收到了停止信号。"""
        if seconds <= 0:
            return self._stop_event.is_set()
        return self._stop_event.wait(seconds)

    # ------------------------------------------------------------------
    # 数据获取
    # ------------------------------------------------------------------
    def _fetch_delay_range(self):
        """
        本轮每只标的拉取前的节流区间（秒）。

        交易时段用 `FETCH_MIN_DELAY~FETCH_MAX_DELAY`（默认 30~300s）；
        非交易时段用 `MONITOR_OFF_HOURS_FETCH_MIN_DELAY~MAX`（默认 60~300s）——
        收盘后价格不变，拉慢一点即可，但**照旧要拉**（当天收盘价 / 当日 K 线靠它补上）。
        """
        if is_trading_time():
            return self.config.FETCH_MIN_DELAY, self.config.FETCH_MAX_DELAY
        return (self.config.MONITOR_OFF_HOURS_FETCH_MIN_DELAY,
                self.config.MONITOR_OFF_HOURS_FETCH_MAX_DELAY)

    def _reset_round_cache(self):
        """
        每轮开始时清空共享结果。

        **必须每轮清**：缓存的是实时行情与当日 K 线，跨轮复用会让我们拿昨天的价格去判告警。
        """
        with self._round_lock:
            self._round_cache = {'quote': {}, 'kline': {}}
            self._round_pending = {}

    def _shared_result(self, kind, stock_code, producer):
        """
        本轮内按股票代码共享外部结果：同一代码的并发任务只有第一个真正去请求，
        其余等待并复用。

        为什么必须有：2026-10-26 起同一代码可被多个用户各持有一条，
        不共享就会对同一个代码打出 N 次雪球请求，外部请求量随用户数线性增长。

        :param kind: 'quote'（行情快照）或 'kline'（日线）
        :param producer: 真正发起外部请求的 Callable
        :return: 结果；失败返回 None。**失败不缓存**——否则一次超时会连坐同代码的其他订单
        """
        key = (kind, stock_code)

        with self._round_lock:
            cached = self._round_cache.get(kind) or {}
            if stock_code in cached:
                return cached[stock_code]
            waiter = self._round_pending.get(key)
            if waiter is None:
                self._round_pending[key] = waiter = threading.Event()
                owner = True
            else:
                owner = False

        if not owner:
            # 首个请求者还在节流/网络等待里，等它拿回来复用即可（比重复请求省一次调用）
            waiter.wait()
            with self._round_lock:
                return (self._round_cache.get(kind) or {}).get(stock_code)

        try:
            value = producer()
        finally:
            # 无论成败都要放行等待者，否则一次异常会把同伴永久挂住
            with self._round_lock:
                self._round_pending.pop(key, None)
            waiter.set()

        if value is None:
            return None
        with self._round_lock:
            self._round_cache.setdefault(kind, {})[stock_code] = value
        return value

    def get_stock_data(self, stock_code):
        """
        从雪球获取单只股票的行情快照。

        注意：stock_code 需带交易所前缀，例如 SZ002027、SH600000。

        :return: 包含 current/pe_ttm/pb/dividend_yield/name 的 dict，失败返回 None
        """
        token = XueqiuToken.TOKEN
        if not token:
            if self._notice_throttle.should_fire('xueqiu:no-token'):
                logger.warning('未配置雪球 Token（环境变量 XUEQIU_TOKEN），跳过行情获取')
            return None

        # Token 失效/限流退避期内不再请求，避免无效调用刷屏
        if self._xueqiu_backoff_remaining() > 0:
            return None

        try:
            # 节流：规避雪球限流。收盘后区间更长（不再停采，见 2026-10-23 变更）
            low, high = self._fetch_delay_range()
            delay = random.uniform(low, high)
            if self._sleep(delay):
                return None

            ball.set_token(token)
            data = ball.quote_detail(stock_code)

            if not isinstance(data, dict) or 'data' not in data or 'quote' not in data['data']:
                logger.warning('雪球返回数据格式异常 stock=%s', stock_code)
                return None

            quote = data['data']['quote']
            return {
                'current': quote.get('current'),
                'pe_ttm': quote.get('pe_ttm'),
                'pb': quote.get('pb'),
                'dividend_yield': quote.get('dividend_yield'),
                'name': quote.get('name'),
                # 52 周高低：雪球直接提供，不自行计算 52 周窗口（006 指标监控）
                'high52w': quote.get('high52w', quote.get('high52_week')),
                'low52w': quote.get('low52w', quote.get('low52_week')),
            }
        except Exception as exc:
            self._handle_xueqiu_error(stock_code, exc)
            return None

    # ------------------------------------------------------------------
    # 告警
    # ------------------------------------------------------------------
    def _send_alert_mail_status(self, subject, body, alarm_type=None, owner_user_id=None):
        """
        发送告警邮件并返回通知状态。

        跳过（skipped）的三种情形，都明确记日志而非静默失败：
        - 该类告警的通知开关被关掉（账户设置 → 告警通知；告警**仍然落库**，只是不发信）；
        - 邮件总开关 `ALARM_MAIL_ENABLED=0`；
        - 解析不到收件人（归属人邮箱为空且环境变量也未设置）。
        发送抛异常时记日志并返回 failed，不向上抛，避免打断监控主循环。

        :param alarm_type: 告警类型（ALARM_TYPE_*）；为 None 表示不受分类开关约束（如每日汇总）
        :param owner_user_id: **订单归属人** id（2026-10-26 多用户数据隔离）：
                              谁的票告警就按谁的开关与邮箱发。为 None（如每日汇总、
                              老数据无归属）时沿用旧的全局口径
        :return: NOTIFY_SENT / NOTIFY_FAILED / NOTIFY_SKIPPED
        """
        if alarm_type is not None and not notify_enabled(alarm_type, prefs_for_user(owner_user_id)):
            logger.info('通知偏好已关闭该类告警邮件（%s），跳过: %s', alarm_type, subject)
            return NOTIFY_SKIPPED

        if not self.config.ALARM_MAIL_ENABLED:
            logger.info('邮件告警已关闭（ALARM_MAIL_ENABLED=0），跳过: %s', subject)
            return NOTIFY_SKIPPED

        recipients = recipients_for_user(owner_user_id)['recipients']
        if not recipients:
            logger.warning('未解析到告警收件人（ALARM_RECIPIENTS 为空且账户邮箱未设置），'
                           '跳过邮件发送: %s', subject)
            return NOTIFY_SKIPPED

        try:
            sent = send_mail(subject=subject, body=body, recipients=recipients)
        except Exception:
            logger.exception('告警邮件发送异常: %s', subject)
            return NOTIFY_FAILED
        return NOTIFY_SENT if sent else NOTIFY_FAILED

    def _send_alert_mail(self, subject, body):
        """发送告警邮件；True 表示已发出（保留布尔语义）。"""
        return self._send_alert_mail_status(subject, body) == NOTIFY_SENT

    def _emit_alarm(self, stock, alarm_key, subject, body,
                    alarm_type=None, alarm_subtype=None, alarm_level=None,
                    throttle=None):
        """
        产生一条告警：冷却检查 -> 落库 -> 发邮件 -> 回写通知状态。

        :param alarm_key: 由 alarm_rules.make_alarm_key 生成的冷却 key
        :param alarm_type: 告警类型（sell/price/pe/pb/indicator），供告警历史按类型筛选
        :param alarm_subtype: 指标类子类型
        :param alarm_level: 档位 1/2/3
        :param throttle: 冷却器，缺省用 `self._throttle`（4h）。
                         指标类传入 `self._indicator_throttle`（24h），与价格/估值互不干扰
        :return: True 表示本次真正产生了告警
        """
        key = alarm_key
        throttle = throttle or self._throttle
        if not throttle.should_fire(key):
            logger.debug('告警处于冷却期，跳过 stock=%s key=%s', stock.stock_code, key)
            return False

        self.stats['alarms'] += 1
        logger.info('触发告警 [%s] %s', key, body)
        alarm_id = StockAlarm.create(
            stock.id, body,
            alarm_type=alarm_type,
            alarm_subtype=alarm_subtype,
            alarm_level=alarm_level,
        )
        # 告警邮件按**订单归属人**发（多用户数据隔离）；
        # 归属缺失（存量数据）时 getattr 返回 None，自动回退到旧的全局口径
        status = self._send_alert_mail_status(
            subject, body, alarm_type=alarm_type,
            owner_user_id=getattr(stock, 'user_id', None),
        )
        StockAlarm.update_notify_status(alarm_id, status)
        return True

    def _check_price_alarms(self, stock, warehouse, current):
        """价格类告警：卖出价 + 三档建仓价。"""
        stock_name = stock.stock_name

        # 卖出告警
        if check_sell(current, getattr(warehouse, 'sell_rate', None)):
            subject, body = build_sell_alarm(stock_name, current, warehouse.sell_rate)
            self._emit_alarm(
                stock, alarm_key_prefix(stock.id, ALARM_TYPE_SELL), subject, body,
                alarm_type=ALARM_TYPE_SELL,
            )
        else:
            self._throttle.clear(alarm_key_prefix(stock.id, ALARM_TYPE_SELL))

        # 三档建仓价
        gear = determine_lower_gear(
            current,
            getattr(warehouse, 'stock_valueone', None),
            getattr(warehouse, 'stock_valuetwo', None),
            getattr(warehouse, 'stock_valuethree', None),
        )
        if gear is None:
            self._throttle.clear_prefix(alarm_key_prefix(stock.id, ALARM_TYPE_PRICE) + ':')
            return

        threshold = threshold_of(
            gear,
            warehouse.stock_valueone,
            warehouse.stock_valuetwo,
            warehouse.stock_valuethree,
        )
        subject, body = build_gear_alarm(
            stock_name, ALARM_TYPE_PRICE, gear, current, threshold
        )
        self._emit_alarm(
            stock, make_alarm_key(stock.id, ALARM_TYPE_PRICE, gear), subject, body,
            alarm_type=ALARM_TYPE_PRICE, alarm_level=gear,
        )

    # ------------------------------------------------------------------
    # 指标监控（006）
    # ------------------------------------------------------------------
    def _indicator_defaults(self):
        """
        把配置里的全局 `IND_*` 阈值取出来；缺少某项时用 `DEFAULT_THRESHOLDS` 兜底。

        刻意不用 `self.config.X` 直取：测试与其他调用方可能传入最小配置对象。
        """
        return {
            'low52w_near_pct': getattr(self.config, 'IND_LOW52W_NEAR_PCT',
                                       DEFAULT_THRESHOLDS['low52w_near_pct']),
            'drawdown_52w_pct': getattr(self.config, 'IND_DRAWDOWN_52W_PCT',
                                        DEFAULT_THRESHOLDS['drawdown_52w_pct']),
            'rs20_pct': getattr(self.config, 'IND_RS20_PCT', DEFAULT_THRESHOLDS['rs20_pct']),
            'rs5_ratio': getattr(self.config, 'IND_RS5_RATIO', DEFAULT_THRESHOLDS['rs5_ratio']),
            'rs5_min_drop_pct': getattr(self.config, 'IND_RS5_MIN_DROP_PCT',
                                        DEFAULT_THRESHOLDS['rs5_min_drop_pct']),
            'rs5_min_bench_drop_pct': getattr(self.config, 'IND_RS5_MIN_BENCH_DROP_PCT',
                                              DEFAULT_THRESHOLDS['rs5_min_bench_drop_pct']),
        }

    def _current_bench_code(self):
        """
        生效基准指数：账户设置 > 环境变量 IND_BENCH > 沪深300。

        缓存 60 秒：`_check_indicators` 是每只股票调用一次，不缓存会把一次账户查询放大成 N 次。
        解析失败（库不可达等）一律回退到环境变量值，绝不让指标判定因为没有基准而停摆。
        """
        now = time.time()
        if self._bench_code_cache and now - self._bench_code_cached_at < 60:
            return self._bench_code_cache

        code = resolve_bench_code(getattr(self.config, 'IND_BENCH', DEFAULT_BENCH_CODE))
        self._bench_code_cache = code
        self._bench_code_cached_at = now
        return code

    def _maybe_send_daily_summary(self):
        """
        每日汇总邮件：开关打开 + 已到发送时间 + 近 24 小时有告警，才发，且**每天只发一次**。

        设计要点：
        - 无告警不发空邮件（空邮件比不发更烦人），且不把当天标记为已发——收盘前出现告警仍会补发；
        - 成败都记当天：发送失败不重试，否则 SMTP 一挂就是每轮一封；
        - 汇总窗口固定 24 小时，时间点由 `DAILY_SUMMARY_TIME` 控制（默认 08:30）。
        """
        prefs = UserNotifyPref.effective()
        if not prefs.get('notify_daily'):
            return False

        send_at = getattr(self.config, 'DAILY_SUMMARY_TIME', '08:30') or '08:30'
        if time.strftime('%H:%M') < send_at:
            return False

        today = time.strftime('%Y-%m-%d')
        if self._daily_summary_date == today:
            return False

        summary = StockAlarm.summarize_since(24)
        if not summary or not summary.get('total'):
            logger.info('近 24 小时无告警，跳过每日汇总邮件')
            return False

        try:
            subject, body = build_daily_summary(summary)
        except Exception:
            self.stats['errors'] += 1
            logger.exception('构造每日汇总邮件失败')
            return False

        status = self._send_alert_mail_status(subject, body)
        self._daily_summary_date = today
        self.stats['daily_summary'] = status
        logger.info('每日汇总邮件状态=%s（近 24h 共 %s 条告警）',
                    status, summary.get('total'))
        return status == NOTIFY_SENT

    def _maybe_sync_bench(self):
        """
        同步基准指数日线：**每个交易日一次**（缺数据时立即同步一次）。

        相对强弱必须有基准的历史收盘价；同步失败不抛异常，
        只会导致本轮 rs20 / rs5 因缺少基准数据而不参与判定（006 已知限制）。
        """
        if not getattr(self.config, 'IND_ENABLED', True):
            return False
        if self._xueqiu_backoff_remaining() > 0:
            return False
        bench_code = self._current_bench_code()

        today = time.strftime('%Y-%m-%d')
        if self._bench_synced_date == today:
            return False

        try:
            has_data = StockBenchKline.get_latest_trade_date(bench_code) is not None
        except Exception:
            self.stats['errors'] += 1
            logger.exception('查询基准日线最新交易日失败 bench=%s', bench_code)
            return False
        if has_data:
            self._bench_synced_date = today
            return False

        try:
            saved = StockBenchKline.sync_from_snowball(bench_code)
        except Exception:
            self.stats['errors'] += 1
            logger.exception('同步基准日线失败 bench=%s', bench_code)
            return False
        if saved > 0:
            self._bench_synced_date = today
        return saved > 0

    def _check_indicators(self, stock, stock_data):
        """
        采集指标 → 幂等落库 → 命中告警。

        约定：
        - 取数失败（K 线不足 / 基准未采集）时对应指标 **不参与判定**，不报错不误报；
        - 新股不足 20 个交易日时 `ret_20d` 为 None → 20 日 / 5 日相关均线指标自动跳过；
        - **只有四条同时成立才告警**（`is_combo_hit`），且一次只产生一条 `combo` 告警；
          单条命中不告警——四条各自命中率都很高，单条件筛选不符合策略；
        - 单只标的异常不影响整轮循环。
        """
        if not getattr(self.config, 'IND_ENABLED', True):
            return

        price = stock_data.get('current')
        high52w = stock_data.get('high52w')
        low52w = stock_data.get('low52w')
        if price is None and high52w is None and low52w is None:
            return

        bench_code = self._current_bench_code()
        try:
            closes = StockKline.get_recent_closes(stock.id, limit=30)
            ret_5d = n_day_return(closes, 5)
            ret_20d = n_day_return(closes, 20)

            bench_closes = StockBenchKline.get_recent_closes(bench_code, limit=30)
            bench_ret_5d = n_day_return(bench_closes, 5)
            bench_ret_20d = n_day_return(bench_closes, 20)

            thresholds = StockIndicatorConfig.resolve_for(stock.id, self._indicator_defaults())
            trade_date = time.strftime('%Y-%m-%d')
            saved = StockIndicator.compute_and_save(
                stock.id, trade_date, bench_code,
                {
                    'price': price, 'high52w': high52w, 'low52w': low52w,
                    'ret_5d': ret_5d, 'ret_20d': ret_20d,
                    'bench_ret_5d': bench_ret_5d, 'bench_ret_20d': bench_ret_20d,
                },
                thresholds,
            )
            if not saved:
                return
            # 组合语义：四条同时成立才产生一条 combo 告警（单条命中率太高，不符合策略）
            self._emit_indicator_alarm(
                stock, SUBTYPE_COMBO, saved, bench_code, trade_date,
                hit=is_combo_hit(saved.get('flags')),
            )
        except Exception:
            self.stats['errors'] += 1
            logger.exception('指标采集/判定失败 stock=%s', stock.stock_code)

    def _emit_indicator_alarm(self, stock, subtype, saved, bench_code, trade_date, hit):
        """
        单条指标告警：命中才走冷却+落库+发信；**未命中时清除该指标的冷却**。

        清除的原因与价格告警一致（D-03）：条件消失后再出现应能重新告警。
        """
        key = make_alarm_key(stock.id, ALARM_TYPE_INDICATOR, subtype=subtype)
        if not hit:
            self._indicator_throttle.clear(key)
            return False

        try:
            subject, body = build_indicator_alarm(
                stock.stock_name, subtype, saved['metrics'], saved['thresholds'], bench_code
            )
        except Exception:
            self.stats['errors'] += 1
            logger.exception('构造指标告警文案失败 stock=%s subtype=%s',
                             stock.stock_code, subtype)
            return False

        fired = self._emit_alarm(
            stock, key, subject, body,
            alarm_type=ALARM_TYPE_INDICATOR, alarm_subtype=subtype,
            throttle=self._indicator_throttle,
        )
        if fired:
            StockIndicator.mark_notified(stock.id, trade_date)
        return fired

    def _check_ratio_alarm(self, stock, info, current, alarm_type, metric_name):
        """PE / PB 类告警（三档阈值，判定规则一致）。"""
        if not info or current is None:
            return

        valueone = getattr(info, f'{metric_name}_valueone', None)
        valuetwo = getattr(info, f'{metric_name}_valuetwo', None)
        valuethree = getattr(info, f'{metric_name}_valuethree', None)

        gear = determine_lower_gear(current, valueone, valuetwo, valuethree)
        if gear is None:
            self._throttle.clear_prefix(alarm_key_prefix(stock.id, alarm_type) + ':')
            return

        threshold = threshold_of(gear, valueone, valuetwo, valuethree)
        subject, body = build_gear_alarm(
            stock.stock_name, alarm_type, gear, current, threshold
        )
        self._emit_alarm(
            stock, make_alarm_key(stock.id, alarm_type, gear), subject, body,
            alarm_type=alarm_type, alarm_level=gear,
        )

    # ------------------------------------------------------------------
    # 单只股票检查
    # ------------------------------------------------------------------
    def _persist_quote(self, stock, stock_data):
        """
        把行情快照回写数据库：PE/PB → ``stock_master``，现价 → ``stock_warehouse``。

        :return: 现价回写成功时返回 warehouse 对象（告警判定要用它读阈值），
                 否则返回 None——沿用 check_and_alert 原有的"无 warehouse 就不判价格告警"语义。
        """
        try:
            StockMaster.update(
                id=stock.id,
                current_pe=stock_data.get('pe_ttm'),
                current_pb=stock_data.get('pb'),
            )
        except Exception:
            self.stats['errors'] += 1
            logger.exception('回写 PE/PB 失败 stock=%s', stock.stock_code)

        try:
            warehouse = StockWarehouse.get_by_stock_master_id(stock.id)
            if warehouse:
                StockWarehouse.update_by_stock_master_id(
                    stock_master_id=stock.id, current_price=stock_data.get('current')
                )
                return warehouse
        except Exception:
            self.stats['errors'] += 1
            logger.exception('回写当前价格失败 stock=%s', stock.stock_code)
        return None

    def check_and_alert(self, stock):
        """检查单只股票：刷新行情 → 落库 → 判定告警。异常不外抛。"""
        # 收到停止信号时不再发起新的网络请求，避免工作线程迟迟退不掉
        if self._stop_event.is_set():
            return

        self.stats['checks'] += 1

        try:
            # 同一代码被多人持有时会产出多行订单，本轮只真正取一次行情
            stock_data = self._shared_result(
                'quote', stock.stock_code,
                lambda: self.get_stock_data(stock.stock_code),
            )
        except Exception:
            self.stats['errors'] += 1
            logger.exception('获取行情时发生未预期错误 stock=%s', stock.stock_code)
            return
        if not stock_data:
            return

        current = stock_data.get('current')
        logger.debug('行情快照 stock=%s current=%s pe=%s pb=%s',
                     stock.stock_code, current, stock_data.get('pe_ttm'), stock_data.get('pb'))

        # 1) + 2) 回写 PE/PB 与现价
        warehouse = self._persist_quote(stock, stock_data)

        # 3) 采集并保存 K 线（失败不影响告警判定）
        self._sync_kline(stock)

        # 4) 指标采集与判定（006 指标监控）
        self._check_indicators(stock, stock_data)

        # 5) 告警判定
        try:
            if warehouse:
                self._check_price_alarms(stock, warehouse, current)
            self._check_ratio_alarm(
                stock, StockPe.get_by_stock_master_id(stock.id),
                stock_data.get('pe_ttm'), ALARM_TYPE_PE, 'pe',
            )
            self._check_ratio_alarm(
                stock, StockPb.get_by_stock_master_id(stock.id),
                stock_data.get('pb'), ALARM_TYPE_PB, 'pb',
            )
        except Exception:
            self.stats['errors'] += 1
            logger.exception('告警判定失败 stock=%s', stock.stock_code)

    def _sync_kline(self, stock):
        """拉取并落库 K 线，异常仅记录不中断。"""
        if self._xueqiu_backoff_remaining() > 0:
            return
        try:
            # 与行情同理：同一代码的 K 线本轮只拉一次
            kline_df = self._shared_result(
                'kline', stock.stock_code,
                lambda: StockKline.get_kline_data_from_snowball(stock.stock_code, days=40),
            )
            if kline_df is None or len(kline_df) == 0:
                logger.warning('未获取到 K 线数据 stock=%s', stock.stock_code)
                return
            saved_count = StockKline.save_kline_data(stock.id, stock.stock_code, kline_df)
            logger.debug('K 线数据已保存 stock=%s count=%s', stock.stock_code, saved_count)
        except Exception:
            self.stats['errors'] += 1
            logger.exception('处理 K 线数据出错 stock=%s', stock.stock_code)

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def _process_stocks(self, stocks):
        """
        并发处理一批活跃订单。

        使用常驻线程池（而非每轮新建），停止时可被 ``shutdown_executor`` 取消排队任务。
        """
        if self._stop_event.is_set():
            return

        executor = self._get_executor()
        futures = []
        for row in stocks:
            if not self.is_running or self._stop_event.is_set():
                break
            stock = self._to_stock_object(row)
            try:
                futures.append(executor.submit(self.check_and_alert, stock))
            except RuntimeError:
                # 线程池已关闭（正在退出），停止派发新任务
                logger.debug('线程池已关闭，停止派发本轮剩余任务')
                break

        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except concurrent.futures.CancelledError:
                pass
            except Exception:
                self.stats['errors'] += 1
                logger.exception('监控子任务出现未捕获异常')

    @staticmethod
    def _to_stock_object(row):
        """把查询结果字典转换为 StockMaster 对象。"""
        return StockMaster(
            id=row['id'],
            stock_name=row['stock_name'],
            stock_code=row['stock_code'],
            target_pettm=row.get('target_pettm'),
            current_pe=row.get('current_pe'),
            target_pb=row.get('target_pb'),
            current_pb=row.get('current_pb'),
            status=row.get('status'),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at'),
            # 归属人：告警邮件要发给谁、按谁的开关决定
            user_id=row.get('user_id'),
        )

    def monitor_loop(self):
        """
        监控主循环。异常不中断循环，退避后继续。

        **非交易时段照常采集**（2026-10-23，见 spec/changes/2026-10-23-offhours-collection.md）：
        收盘后 / 午休 / 周末不再跳过整轮，行情、K 线、指标、告警判定全部照跑，
        只是两处放慢——每只标的的拉取节流更长、每轮之间多睡一段。
        """
        logger.info('监控循环启动 pid=%s', os.getpid())

        while self.is_running:
            # 每日汇总邮件：与交易时段无关（默认 08:30 在非交易时段），故放在时段判断之前
            try:
                self._maybe_send_daily_summary()
            except Exception:
                self.stats['errors'] += 1
                logger.exception('每日汇总邮件处理失败')

            # 雪球退避期（Token 失效/限流）：整轮跳过，等退避结束再试
            backoff = self._xueqiu_backoff_remaining()
            if backoff > 0:
                if self._sleep(min(backoff, self.config.MONITOR_OFF_HOURS_SLEEP)):
                    break
                continue

            self.stats['rounds'] += 1
            self.stats['last_round_at'] = time.strftime('%Y-%m-%d %H:%M:%S')

            # 基准指数日线：每交易日同步一次（异常只记日志，不影响主循环）
            self._maybe_sync_bench()

            try:
                stocks = StockMaster.get_active_stocks(limit=self.config.MONITOR_MAX_STOCKS)
                # 每轮清空共享缓存：跨轮复用会拿昨天的行情去判今天的告警
                self._reset_round_cache()
                if not stocks:
                    logger.debug('没有活跃订单，休眠 %ss', self.config.MONITOR_ERROR_SLEEP)
                    if self._sleep(self.config.MONITOR_ERROR_SLEEP):
                        break
                    continue
                logger.debug('本轮待处理订单数=%s', len(stocks))
                self._process_stocks(stocks)

                # 轮间隔：交易时段默认 0（一轮结束立即下一轮，靠 per-stock 节流控频）；
                # 非交易时段按 OFF_HOURS_ROUND_INTERVAL 放慢。**不停采**，只是拉得稀。
                interval = (self.config.MONITOR_ROUND_INTERVAL if is_trading_time()
                            else self.config.MONITOR_OFF_HOURS_ROUND_INTERVAL)
                if self._sleep(interval):
                    break
            except Exception:
                self.stats['errors'] += 1
                logger.exception('监控循环发生错误，退避后继续')
                if self._sleep(self.config.MONITOR_ERROR_SLEEP):
                    break

        logger.info('监控循环退出')


# 全局监控实例
monitor = StockMonitor()
