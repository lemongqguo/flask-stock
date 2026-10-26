"""
账户设置：默认基准指数、告警通知偏好、告警收件人。

对应设计稿 `design-preview/screens/account.html`，变更见
`spec/changes/2026-10-23-account-profile.md`。

**本模块是这三个"全局生效值"的唯一真值入口**——页面显示与后台发信必须调用同一份函数，
否则就会出现"页面写 A、邮件发到 B"这类最难排查的漂移：

- `resolve_bench_code()`：账户设置 > 环境变量 `IND_BENCH` > 沪深300
- `resolve_alarm_recipients()`：环境变量 `ALARM_RECIPIENTS` > 账户邮箱
- `notify_enabled(alarm_type)`：某类告警是否发邮件

多账户口径：本系统是单账户运维视角，全局设置以**最近保存过的账户**为准
（`ORDER BY updated_at DESC, id ASC`）。取数失败一律回退到既有默认值——
设置读取失败不能让页面 500，更不能让监控线程挂掉。
"""
import logging

from models.base import BaseModel
from utils.alarm_rules import (
    ALARM_TYPE_INDICATOR,
    ALARM_TYPE_PB,
    ALARM_TYPE_PE,
    ALARM_TYPE_PRICE,
    ALARM_TYPE_SELL,
)
from utils.indicator_rules import DEFAULT_BENCH_CODE

logger = logging.getLogger(__name__)

# 默认基准指数候选（设计稿要求四个；code 为雪球符号）
BENCHMARK_CHOICES = (
    {'code': 'SH000001', 'name': '上证指数'},
    {'code': 'SH000300', 'name': '沪深300'},
    {'code': 'SZ399006', 'name': '创业板指'},
    {'code': 'HKHSI', 'name': '恒生指数'},
)
BENCHMARK_CODES = tuple(item['code'] for item in BENCHMARK_CHOICES)
BENCHMARK_NAMES = {item['code']: item['name'] for item in BENCHMARK_CHOICES}

# 通知开关字段与设计稿四个开关一一对应
NOTIFY_FIELDS = ('notify_price', 'notify_valuation', 'notify_indicator', 'notify_daily')

# 默认偏好：三类告警开（与历史上"只要有收件人就发"一致），每日汇总关（避免莫名其妙多收邮件）
DEFAULT_NOTIFY_PREFS = {
    'notify_price': 1,
    'notify_valuation': 1,
    'notify_indicator': 1,
    'notify_daily': 0,
}

# 告警类型 -> 受哪个开关控制
ALARM_TYPE_TO_NOTIFY_FIELD = {
    ALARM_TYPE_PRICE: 'notify_price',
    ALARM_TYPE_SELL: 'notify_price',
    ALARM_TYPE_PE: 'notify_valuation',
    ALARM_TYPE_PB: 'notify_valuation',
    ALARM_TYPE_INDICATOR: 'notify_indicator',
}

# 生效账户查询：非 NULL 的 updated_at 按时间倒序在前，NULL（从未保存过）按 id 兜底
_LATEST_ACCOUNT_QUERY = (
    "SELECT id, username, email, phone, bench_code, updated_at "
    "FROM users ORDER BY updated_at DESC, id ASC LIMIT 1"
)


class UserNotifyPref(BaseModel):
    """告警通知偏好（`user_notify_pref`，每用户一行；无行即用默认偏好）。"""

    table_name = 'user_notify_pref'

    @classmethod
    def get(cls, user_id):
        """取某用户的偏好行（dict）；无行返回 None，查询失败返回 None。"""
        query = "SELECT * FROM user_notify_pref WHERE user_id = %s LIMIT 1"
        try:
            rows = cls.execute_query(query, (user_id,))
        except Exception:
            logger.exception('查询通知偏好失败 user_id=%s', user_id)
            return None
        return rows[0] if rows else None

    @classmethod
    def save(cls, user_id, **flags):
        """
        写入/更新某用户的通知偏好（只接受 NOTIFY_FIELDS 里的字段）。

        显式写 updated_at = NOW()：即使开关值没变，也要让该账户成为"最近保存的账户"，
        否则用户点了保存但全局生效值没变，会被当成"改了没生效"。

        :return: True 表示执行成功
        """
        payload = {key: 1 if flags.get(key) else 0 for key in NOTIFY_FIELDS if key in flags}
        if not payload:
            return False

        columns = ['user_id'] + list(payload)
        placeholders = ', '.join(['%s'] * len(columns))
        updates = ', '.join(f'{key} = VALUES({key})' for key in payload)
        query = (
            f"INSERT INTO user_notify_pref ({', '.join(columns)}, updated_at) "
            f"VALUES ({placeholders}, NOW()) "
            f"ON DUPLICATE KEY UPDATE {updates}, updated_at = NOW()"
        )
        params = tuple([user_id] + [payload[key] for key in payload])
        try:
            cls.execute_update(query, params)
            return True
        except Exception:
            logger.exception('保存通知偏好失败 user_id=%s', user_id)
            return False

    @classmethod
    def effective(cls):
        """
        取**全局生效**的偏好：最近保存过的那一行；无行 / 查询失败用默认偏好。

        :return: dict，含 NOTIFY_FIELDS 四个键 + `user_id`（无行时为 None）
        """
        query = ("SELECT * FROM user_notify_pref "
                 "ORDER BY updated_at DESC, user_id ASC LIMIT 1")
        try:
            rows = cls.execute_query(query)
        except Exception:
            logger.exception('查询生效通知偏好失败，回退默认偏好')
            rows = None

        prefs = dict(DEFAULT_NOTIFY_PREFS)
        prefs['user_id'] = None
        if rows:
            row = rows[0]
            prefs['user_id'] = row.get('user_id')
            for field in NOTIFY_FIELDS:
                prefs[field] = 1 if row.get(field) else 0
        return prefs


def latest_account():
    """最近保存过设置的账户（dict）；无用户 / 查询失败返回 None。"""
    try:
        rows = UserNotifyPref.execute_query(_LATEST_ACCOUNT_QUERY)
    except Exception:
        logger.exception('查询生效账户失败')
        return None
    return rows[0] if rows else None


def resolve_bench_code(default=None):
    """
    生效的基准指数代码：账户设置 > 环境变量 `IND_BENCH` > 沪深300。

    :param default: 环境变量缺失时的兜底，缺省依次取 Config.IND_BENCH / DEFAULT_BENCH_CODE
    :return: 基准代码字符串（一定是 BENCHMARK_CODES 之一或传入的 default）
    """
    from config import Config

    fallback = default or getattr(Config, 'IND_BENCH', '') or DEFAULT_BENCH_CODE
    row = latest_account() or {}
    code = (row.get('bench_code') or '').strip()
    # 只认白名单里的代码：库里被写进非法值时回退，不让指标采集拿着坏代码去打雪球
    return code if code in BENCHMARK_CODES else fallback


def resolve_alarm_recipients():
    """
    生效的告警收件人：环境变量 `ALARM_RECIPIENTS` **优先**，为空时回退到账户邮箱。

    环境变量优先的理由：它可能是多人共享的告警邮箱；不因为账户改了邮箱就把环境变量
    里的收件人悄悄换掉。反过来，环境变量为空时以账户邮箱兜底，保证"页面有邮箱就能收到"。

    :return: dict(recipients=[...], source='env' | 'account' | '', email=账户邮箱)
    """
    from config import get_alarm_recipients

    try:
        account = latest_account() or {}
    except Exception:  # pragma: no cover - 账户读不到也要能按环境变量发信
        logger.exception('解析账户邮箱失败，仅按环境变量解析收件人')
        account = {}
    email = (account.get('email') or '').strip()

    env_recipients = get_alarm_recipients()
    if env_recipients:
        return {'recipients': env_recipients, 'source': 'env', 'email': email}
    if '@' in email:
        return {'recipients': [email], 'source': 'account', 'email': email}
    return {'recipients': [], 'source': '', 'email': email}


def notify_enabled(alarm_type, prefs=None):
    """
    某类告警是否允许发邮件。

    未知类型一律放行——宁可多发一封，也不能因为新类型没登记就静默吞掉告警。

    :param alarm_type: utils.alarm_rules 的 ALARM_TYPE_*
    :param prefs: `UserNotifyPref.effective()` 的结果；缺省临时查一次
    :return: bool
    """
    prefs = prefs if prefs is not None else UserNotifyPref.effective()
    field = ALARM_TYPE_TO_NOTIFY_FIELD.get(alarm_type)
    if not field:
        return True
    return bool(prefs.get(field, 1))


def daily_summary_enabled(prefs=None):
    """每日汇总邮件是否开启。"""
    prefs = prefs if prefs is not None else UserNotifyPref.effective()
    return bool(prefs.get('notify_daily'))
