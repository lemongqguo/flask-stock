"""
全局配置。

安全约定（见 spec/rules/development-standards.md 第 1 节）：
- 本文件 **不得包含任何明文凭据**（数据库密码 / SECRET_KEY / 邮箱授权码 / 第三方 Token）。
- 所有敏感项一律从环境变量读取；本地开发可放在项目根目录的 `.env`（该文件已被 .gitignore 排除）。
- 缺失必填项时启动即报错，而不是带着空值继续跑。
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, '.env')


def load_dotenv(path=ENV_FILE, override=False):
    """
    极简 .env 加载器，避免为配置引入额外依赖。

    支持 `KEY=VALUE` 与 `#` 注释；已存在的环境变量默认不被覆盖。
    """
    if not os.path.isfile(path):
        return {}
    loaded = {}
    try:
        with open(path, 'r', encoding='utf-8') as fp:
            for raw_line in fp:
                line = raw_line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if not key:
                    continue
                loaded[key] = value
                if override or key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        logger.warning('读取 .env 失败（已忽略）: %s', exc)
    return loaded


load_dotenv()


def _get_str(key, default=''):
    value = os.environ.get(key)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _get_int(key, default):
    raw = _get_str(key, '')
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning('环境变量 %s=%r 不是合法整数，回退默认值 %s', key, raw, default)
        return default


def _get_float(key, default):
    raw = _get_str(key, '')
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning('环境变量 %s=%r 不是合法数字，回退默认值 %s', key, raw, default)
        return default


def _get_bool(key, default=False):
    raw = _get_str(key, '')
    if not raw:
        return default
    return raw.lower() in ('1', 'true', 'yes', 'on')


def _get_list(key, default=None):
    """从逗号/分号分隔的环境变量解析列表，并去除空项。"""
    raw = _get_str(key, '')
    if not raw:
        return list(default or [])
    items = [item.strip() for item in raw.replace(';', ',').split(',')]
    return [item for item in items if item]


def _normalize_hhmm(value, default):
    """
    校验 `HH:MM`（24 小时制，零填充）。

    每日汇总邮件靠字符串比较判断是否到点（`'07:59' < '08:30'`），
    格式不合法会让比较结果失去意义，故非法值直接回退默认并记日志。
    """
    if value and re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value):
        return value
    if value:
        logger.warning('时间配置 %r 不是合法的 HH:MM，回退默认值 %s', value, default)
    return default


def missing_required_settings():
    """返回缺失的必填配置项名称列表，供启动自检与测试使用。"""
    required = {
        'MYSQL_PASSWORD': '数据库密码',
        'SECRET_KEY': 'Flask 会话密钥',
        'XUEQIU_TOKEN': '雪球 Token',
        'MAIL_USERNAME': '发件邮箱',
        'MAIL_PASSWORD': '邮箱授权码',
        'ALARM_RECIPIENTS': '告警收件人',
    }
    return [f'{key}({label})' for key, label in required.items() if not _get_str(key)]


def validate_runtime_settings(strict=False):
    """
    启动自检：返回 (是否通过, 问题列表)。

    strict=True 时缺少必填项直接抛 RuntimeError，用于生产启动；
    strict=False 时仅记录警告，供本地/测试使用。
    """
    problems = []
    missing = missing_required_settings()
    if missing:
        problems.append('缺少必填配置项：' + '、'.join(missing))

    recipients = get_alarm_recipients()
    if not recipients:
        problems.append('告警收件人为空，邮件告警将无法送达（请配置 ALARM_RECIPIENTS）')

    if problems:
        for problem in problems:
            logger.error('配置自检失败：%s', problem)
        if strict:
            raise RuntimeError('；'.join(problems))
    return (not problems), problems


# ---------------------------------------------------------------------------
# 数据库连接池（惰性创建，避免 import config 时就要求数据库可用）
# ---------------------------------------------------------------------------
_POOL = None


def get_pool():
    """返回全局唯一的 MySQL 连接池，首次调用时才真正建立连接。"""
    global _POOL
    if _POOL is None:
        from dbutils.pooled_db import PooledDB
        import pymysql

        _POOL = PooledDB(
            creator=pymysql,          # 使用连接数据库的模块
            maxconnections=_get_int('MYSQL_MAX_CONNECTIONS', 5),   # 连接池允许的最大连接数
            mincached=_get_int('MYSQL_MIN_CACHED', 2),             # 初始化时至少创建的空闲连接数
            maxcached=_get_int('MYSQL_MAX_CACHED', 3),             # 连接池中最多闲置的连接数
            blocking=True,             # 无可用连接时阻塞等待
            setsession=[],              # 开始会话前执行的命令列表
            ping=1,                     # 从连接池取连接时 ping 一次，避免拿到已失效的死连接
            host=_get_str('MYSQL_HOST', '127.0.0.1'),
            port=_get_int('MYSQL_PORT', 3306),
            user=_get_str('MYSQL_USER', 'root'),
            password=_get_str('MYSQL_PASSWORD'),
            database=_get_str('MYSQL_DATABASE', 'stockdb'),
            charset=_get_str('MYSQL_CHARSET', 'utf8mb4'),
        )
        logger.info('MySQL 连接池已创建: %s:%s/%s',
                    _get_str('MYSQL_HOST', '127.0.0.1'),
                    _get_int('MYSQL_PORT', 3306),
                    _get_str('MYSQL_DATABASE', 'stockdb'))
    return _POOL


def reset_pool():
    """释放连接池（主要用于测试与热重载）。"""
    global _POOL
    _POOL = None


class Config:
    """Flask 应用配置。"""

    # --- Flask ---
    SECRET_KEY = _get_str('SECRET_KEY') or 'dev-insecure-secret-key-please-override'
    DEBUG = _get_bool('FLASK_DEBUG', False)
    HOST = _get_str('FLASK_HOST', '0.0.0.0')
    PORT = _get_int('FLASK_PORT', 5000)
    JSON_AS_ASCII = False

    # --- 邮件 ---
    MAIL_SERVER = _get_str('MAIL_SERVER', 'smtp.qq.com')
    MAIL_PORT = _get_int('MAIL_PORT', 465)
    MAIL_USE_TLS = _get_bool('MAIL_USE_TLS', False)
    MAIL_USE_SSL = _get_bool('MAIL_USE_SSL', True)
    MAIL_USERNAME = _get_str('MAIL_USERNAME')
    MAIL_PASSWORD = _get_str('MAIL_PASSWORD')
    MAIL_TIMEOUT = _get_int('MAIL_TIMEOUT', 10)

    # --- 监控服务 ---
    MONITOR_ENABLED = _get_bool('MONITOR_ENABLED', True)          # 是否随应用启动监控线程
    MONITOR_MAX_WORKERS = _get_int('MONITOR_MAX_WORKERS', 6)      # 线程池并发度
    MONITOR_MAX_STOCKS = _get_int('MONITOR_MAX_STOCKS', 100)       # 单轮最多处理的活跃订单数
    MONITOR_ERROR_SLEEP = _get_int('MONITOR_ERROR_SLEEP', 5)      # 空轮询/异常时的休眠秒数
    # 雪球退避期的休眠上限（退避期整轮跳过，睡 min(剩余退避, 本值) 后重试）
    MONITOR_OFF_HOURS_SLEEP = _get_int('MONITOR_OFF_HOURS_SLEEP', 300)
    # 每轮之间的休眠秒数：交易时段默认 0（一轮结束立即下一轮，靠下面的 per-stock 节流控频），
    # 非交易时段默认 1800s——收盘后照常采集，只是放慢（2026-10-23，见 spec/changes/2026-10-23-offhours-collection.md）
    MONITOR_ROUND_INTERVAL = _get_int('MONITOR_ROUND_INTERVAL', 0)
    MONITOR_OFF_HOURS_ROUND_INTERVAL = _get_int('MONITOR_OFF_HOURS_ROUND_INTERVAL', 1800)

    # 行情拉取节流区间（秒），用于规避雪球限流
    FETCH_MIN_DELAY = _get_float('FETCH_MIN_DELAY', 30.0)
    FETCH_MAX_DELAY = _get_float('FETCH_MAX_DELAY', 300.0)
    # 非交易时段每只标的的节流区间（秒）：收盘后价格不变，放慢即可，不再整轮停采
    MONITOR_OFF_HOURS_FETCH_MIN_DELAY = _get_float('MONITOR_OFF_HOURS_FETCH_MIN_DELAY', 60.0)
    MONITOR_OFF_HOURS_FETCH_MAX_DELAY = _get_float('MONITOR_OFF_HOURS_FETCH_MAX_DELAY', 300.0)

    # 雪球 Token 失效 / 限流后的退避秒数，期间不再请求雪球，只提示一次
    XUEQIU_BACKOFF_SECONDS = _get_int('XUEQIU_BACKOFF_SECONDS', 600)
    # 同一雪球错误码的重复提示间隔，避免刷屏
    XUEQIU_NOTICE_INTERVAL = _get_int('XUEQIU_NOTICE_INTERVAL', 300)

    # 退出看门狗：收到 Ctrl+C/SIGTERM 后超过该秒数仍未退出则强制结束进程
    SHUTDOWN_TIMEOUT = _get_float('SHUTDOWN_TIMEOUT', 5.0)
    # 全局 socket 默认超时（秒）。pysnowball 未传 timeout，长时间挂起会导致线程无法退出
    SOCKET_TIMEOUT = _get_float('SOCKET_TIMEOUT', 30.0)

    # 告警冷却：同一订单同一告警类型在该秒数内不重复记录与重复发信
    ALARM_COOLDOWN_SECONDS = _get_int('ALARM_COOLDOWN_SECONDS', 14400)
    ALARM_MAIL_ENABLED = _get_bool('ALARM_MAIL_ENABLED', True)
    # 每日汇总邮件的发送时间点（本地时间 HH:MM）；开关在「账户设置 → 告警通知」
    DAILY_SUMMARY_TIME = _normalize_hhmm(_get_str('DAILY_SUMMARY_TIME', '08:30'), '08:30')

    # --- 指标监控（006 指标监控）---
    # 全部可在 stock_indicator_config 里按个股覆盖；该表字段留空时继承这里的全局值
    IND_ENABLED = _get_bool('IND_ENABLED', True)
    IND_BENCH = _get_str('IND_BENCH', 'SH000300')          # 基准指数，默认沪深300
    IND_LOW52W_NEAR_PCT = _get_float('IND_LOW52W_NEAR_PCT', 5.0)     # 距 52 周低 ≤ 该百分比即命中
    IND_DRAWDOWN_52W_PCT = _get_float('IND_DRAWDOWN_52W_PCT', 35.0)  # 52 周回撤达该百分比即命中
    IND_RS20_PCT = _get_float('IND_RS20_PCT', 15.0)                  # 20 日跑输基准百分点
    IND_RS5_RATIO = _get_float('IND_RS5_RATIO', 2.5)                 # 5 日跌幅达基准的倍数
    IND_RS5_MIN_DROP_PCT = _get_float('IND_RS5_MIN_DROP_PCT', 3.0)   # 护栏：个股 5 日最小跌幅
    IND_RS5_MIN_BENCH_DROP_PCT = _get_float('IND_RS5_MIN_BENCH_DROP_PCT', 0.5)  # 护栏：基准最小跌幅
    # 指标类冷却小时数。52 周回撤 >35% 是持续状态，用价格告警的 4h 会连发数日
    IND_COOLDOWN_HOURS = _get_int('IND_COOLDOWN_HOURS', 24)
    IND_BENCH_WINDOW_DAYS = _get_int('IND_BENCH_WINDOW_DAYS', 40)    # 基准日线采集窗口（自然日）

    # --- AI 个股分析（007）---
    # AI_API_KEY 只从环境变量读取，**不入库、不回显、不写日志**；
    # 其余默认值可被 stock_ai_config 表覆盖（该表不存任何凭据）
    AI_ENABLED = _get_bool('AI_ENABLED', False)          # 总开关；默认关闭，页面显示「未启用」
    AI_API_BASE = _get_str('AI_API_BASE')                # 如 https://api.openai.com/v1（末尾不带斜杠）
    AI_MODEL = _get_str('AI_MODEL')                      # 默认模型 ID，如 gpt-4o-mini
    # 可选模型清单（逗号分隔），供页面下拉选择；AI_MODEL 始终入选并排第一
    AI_MODELS = _get_str('AI_MODELS')
    AI_API_KEY = _get_str('AI_API_KEY')
    AI_API_STYLE = _get_str('AI_API_STYLE', 'responses')  # responses | chat，兼容两类 OpenAI 风格
    AI_TEMPERATURE = _get_float('AI_TEMPERATURE', 0.6)
    AI_MAX_TOKENS = _get_int('AI_MAX_TOKENS', 1200)
    AI_MONTHLY_LIMIT = _get_int('AI_MONTHLY_LIMIT', 200)   # 月度调用上限，达限拒绝而不是静默失败
    AI_TIMEOUT = _get_int('AI_TIMEOUT', 60)                # 外部调用超时（秒），必传


class XueqiuToken:
    """雪球行情 Token（从环境变量读取，禁止硬编码）。"""

    TOKEN = _get_str('XUEQIU_TOKEN')


def get_alarm_recipients():
    """返回合法的告警收件人列表（已过滤空串与不含 @ 的非法项）。"""
    return [addr for addr in _get_list('ALARM_RECIPIENTS') if '@' in addr]
