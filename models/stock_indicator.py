"""
指标监控数据模型（006 指标监控）。

包含三块：
- `StockIndicator`：指标快照表 `stock_indicator`，按 `(stock_master_id, trade_date)` 幂等 upsert；
- `StockIndicatorConfig`：单标的阈值覆盖表 `stock_indicator_config`，字段留空表示继承全局 `IND_*`；
- `StockBenchKline`：基准指数日线表 `stock_bench_kline`，用于计算相对强弱。

**为何基准不复用 `stock_kline`**：该表靠 `stock_master_id` 关联订单，而基准指数不是订单，
无法复用；相对强弱又必须有基准的历史收盘价，故单独建表。

本模块刻意**不 import pandas**：Pandas 只在 K 线采集（`models/stock_kline.py`）里用到，
这里直接读 `pysnowball` 的原始 dict 即可，指标计算也能保持可单测。
"""
import datetime
import logging

import pysnowball as ball

from config import Config, XueqiuToken
from models.base import BaseModel
from utils.indicator_rules import (
    DEFAULT_THRESHOLDS,
    evaluate_indicators,
    resolve_thresholds,
)
from utils.snowball_errors import describe as describe_xueqiu_error
from utils.snowball_errors import parse_xueqiu_error

logger = logging.getLogger(__name__)

# stock_indicator 的可写字段（与 INSERT 保持一致，便于拼 UPDATE 子句）
_SNAPSHOT_FIELDS = (
    'price', 'high52w', 'low52w',
    'pct_from_low52w', 'drawdown_52w',
    'ret_5d', 'ret_20d',
    'bench_ret_5d', 'bench_ret_20d',
    'rs_20d', 'rs_5d_ratio',
    'flag_low52w', 'flag_drawdown', 'flag_rs20', 'flag_rs5',
)


def _flag(value):
    """BOOL → TINYINT（0/1）。"""
    return 1 if value else 0


class StockIndicator(BaseModel):
    table_name = 'stock_indicator'

    @classmethod
    def compute_and_save(cls, stock_master_id, trade_date, bench_code, snapshot,
                         thresholds=None):
        """
        计算指标并幂等落库。

        :param stock_master_id: 订单主表 ID
        :param trade_date: 归属交易日（date 或 YYYY-MM-DD 字符串）
        :param bench_code: 基准代码，如 SH000300
        :param snapshot: dict(price, high52w, low52w, ret_5d, ret_20d, bench_ret_5d, bench_ret_20d)
        :param thresholds: 阈值 dict，缺省用 DEFAULT_THRESHOLDS
        :return: dict(metrics, flags, hits, thresholds)；失败返回 None
        """
        th = dict(thresholds or DEFAULT_THRESHOLDS)
        try:
            result = evaluate_indicators(snapshot, th)
        except Exception:
            logger.exception('指标计算失败 stock_master_id=%s', stock_master_id)
            return None

        metrics = {
            'price': snapshot.get('price'),
            'high52w': snapshot.get('high52w'),
            'low52w': snapshot.get('low52w'),
            'ret_5d': snapshot.get('ret_5d'),
            'ret_20d': snapshot.get('ret_20d'),
            'bench_ret_5d': snapshot.get('bench_ret_5d'),
            'bench_ret_20d': snapshot.get('bench_ret_20d'),
            'pct_from_low52w': result['pct_from_low52w'],
            'drawdown_52w': result['drawdown_52w'],
            'rs_20d': result['rs_20d'],
            'rs_5d_ratio': result['rs_5d_ratio'],
        }
        flags = result['flags']

        row = {
            'stock_master_id': stock_master_id,
            'trade_date': trade_date,
            'price': metrics['price'],
            'high52w': metrics['high52w'],
            'low52w': metrics['low52w'],
            'pct_from_low52w': metrics['pct_from_low52w'],
            'drawdown_52w': metrics['drawdown_52w'],
            'ret_5d': metrics['ret_5d'],
            'ret_20d': metrics['ret_20d'],
            'bench_code': bench_code,
            'bench_ret_5d': metrics['bench_ret_5d'],
            'bench_ret_20d': metrics['bench_ret_20d'],
            'rs_20d': metrics['rs_20d'],
            'rs_5d_ratio': metrics['rs_5d_ratio'],
            'flag_low52w': _flag(flags.get('low52w')),
            'flag_drawdown': _flag(flags.get('drawdown')),
            'flag_rs20': _flag(flags.get('rs20')),
            'flag_rs5': _flag(flags.get('rs5')),
        }

        # MySQL 的 NO_AUTO_VALUE_ON_ZERO / 严格模式不属于我的控制范围，这里只做常规 upsert；
        # notified_at 刻意不进 UPDATE 子句——已通知状态不应被后续刷新覆盖掉。
        columns = ['stock_master_id', 'trade_date', 'bench_code'] + list(_SNAPSHOT_FIELDS)
        placeholders = ', '.join(['%s'] * len(columns))
        updates = ', '.join(f'{field} = VALUES({field})' for field in _SNAPSHOT_FIELDS)
        query = (
            f"INSERT INTO stock_indicator ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {updates}"
        )
        params = tuple(row[column] for column in columns)

        try:
            cls.execute_update(query, params)
        except Exception:
            logger.exception('保存指标快照失败 stock_master_id=%s trade_date=%s',
                             stock_master_id, trade_date)
            return None

        return {
            'metrics': metrics,
            'flags': flags,
            'hits': [sub for sub in ('low52w', 'drawdown', 'rs20', 'rs5') if flags.get(sub)],
            'thresholds': th,
        }

    @classmethod
    def get_latest(cls, stock_master_id):
        """取该标的最新一条指标快照（dict 行，无数据返回 None）。"""
        query = ("SELECT * FROM stock_indicator WHERE stock_master_id = %s "
                 "ORDER BY trade_date DESC LIMIT 1")
        try:
            rows = cls.execute_query(query, (stock_master_id,))
        except Exception:
            logger.exception('查询指标快照失败 stock_master_id=%s', stock_master_id)
            return None
        return rows[0] if rows else None

    @classmethod
    def list_recent(cls, stock_master_id, limit=30):
        """按交易日倒序取该标的的指标历史。失败返回空列表。"""
        query = ("SELECT * FROM stock_indicator WHERE stock_master_id = %s "
                 "ORDER BY trade_date DESC LIMIT %s")
        try:
            return cls.execute_query(query, (stock_master_id, limit))
        except Exception:
            logger.exception('查询指标历史失败 stock_master_id=%s', stock_master_id)
            return []

    @classmethod
    def get_latest_batch(cls, stock_master_ids):
        """
        批量取每个标的**最新交易日**的指标快照（一次查询，避免页面的 N+1）。

        :param stock_master_ids: 订单主表 ID 列表
        :return: {stock_master_id: 快照行}；无快照的不出现在结果里；查询失败返回空 dict
        """
        if not stock_master_ids:
            return {}

        # 占位符只由元素个数生成，值一律参数化传入
        placeholders = ', '.join(['%s'] * len(stock_master_ids))
        query = f"""
        SELECT si.*
        FROM stock_indicator si
        JOIN (
            SELECT stock_master_id, MAX(trade_date) AS latest_date
            FROM stock_indicator
            WHERE stock_master_id IN ({placeholders})
            GROUP BY stock_master_id
        ) latest ON si.stock_master_id = latest.stock_master_id
              AND si.trade_date = latest.latest_date
        """
        try:
            rows = cls.execute_query(query, tuple(stock_master_ids))
        except Exception:
            logger.exception('查询最新指标快照失败 ids=%s', stock_master_ids)
            return {}
        return {row['stock_master_id']: row for row in rows}

    @classmethod
    def mark_notified(cls, stock_master_id, trade_date):
        """回写邮件通知时间。True 表示更新到行。"""
        query = ("UPDATE stock_indicator SET notified_at = NOW() "
                 "WHERE stock_master_id = %s AND trade_date = %s")
        try:
            return cls.execute_update(query, (stock_master_id, trade_date)) > 0
        except Exception:
            logger.exception('回写指标通知时间失败 stock_master_id=%s', stock_master_id)
            return False


class StockIndicatorConfig(BaseModel):
    table_name = 'stock_indicator_config'

    @classmethod
    def get_by_stock_master_id(cls, stock_master_id):
        """取单标的阈值覆盖行（dict 行，未配置返回 None）。"""
        query = "SELECT * FROM stock_indicator_config WHERE stock_master_id = %s LIMIT 1"
        try:
            rows = cls.execute_query(query, (stock_master_id,))
        except Exception:
            logger.exception('查询指标阈值覆盖失败 stock_master_id=%s', stock_master_id)
            return None
        return rows[0] if rows else None

    @classmethod
    def get_map(cls, stock_master_ids):
        """
        批量取多个标的的阈值覆盖（页面一次取回，避免 N+1）。

        :return: {stock_master_id: 配置行}；未配置的不出现在结果里；查询失败返回空 dict
        """
        if not stock_master_ids:
            return {}
        placeholders = ', '.join(['%s'] * len(stock_master_ids))
        query = (f"SELECT * FROM stock_indicator_config "
                 f"WHERE stock_master_id IN ({placeholders})")
        try:
            rows = cls.execute_query(query, tuple(stock_master_ids))
        except Exception:
            logger.exception('批量查询指标阈值覆盖失败 ids=%s', stock_master_ids)
            return {}
        return {row['stock_master_id']: row for row in rows}

    @classmethod
    def upsert(cls, stock_master_id, **fields):
        """
        写入/更新单标的阈值覆盖。只接受 `*_pct` / `rs5_ratio` 等已知字段，未知字段忽略。

        :return: True 表示执行成功
        """
        allowed = {
            'low52w_near_pct', 'drawdown_52w_pct', 'rs20_pct',
            'rs5_ratio', 'rs5_min_drop_pct', 'rs5_min_bench_drop_pct',
        }
        payload = {key: value for key, value in fields.items() if key in allowed}
        if not payload:
            return False

        columns = ['stock_master_id'] + list(payload)
        placeholders = ', '.join(['%s'] * len(columns))
        updates = ', '.join(f'{key} = VALUES({key})' for key in payload)
        query = (
            f"INSERT INTO stock_indicator_config ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {updates}"
        )
        params = tuple([stock_master_id] + [payload[key] for key in payload])
        try:
            cls.execute_update(query, params)
            return True
        except Exception:
            logger.exception('保存指标阈值覆盖失败 stock_master_id=%s', stock_master_id)
            return False

    @classmethod
    def resolve_for(cls, stock_master_id, defaults=None):
        """
        取该标的最终生效的阈值：全局默认 + 个股非空覆盖。

        :param defaults: 全局阈值 dict，缺省用 DEFAULT_THRESHOLDS（实际 globals 来自 config 的 IND_*）
        """
        row = cls.get_by_stock_master_id(stock_master_id)
        return resolve_thresholds(row, defaults)


class StockBenchKline(BaseModel):
    table_name = 'stock_bench_kline'

    @staticmethod
    def _split_snowball_kline(payload):
        """
        把 pysnowball 的 kline 返回值拆成 [(trade_date, close)]，**不用 pandas**。

        :return: 解析失败返回 []
        """
        if not isinstance(payload, dict) or 'data' not in payload:
            return []
        data = payload['data']
        columns = data.get('column') or []
        items = data.get('item') or []
        if not columns or not items:
            return []

        try:
            idx_ts = columns.index('timestamp')
            idx_close = columns.index('close')
        except ValueError:
            logger.warning('雪球 K 线缺少 timestamp/close 列返回: %s', columns)
            return []

        rows = []
        for item in items:
            try:
                ts = int(item[idx_ts])
                close = float(item[idx_close])
            except (TypeError, ValueError):
                continue
            # 雪球时间戳单位为毫秒
            trade_date = datetime.date.fromtimestamp(ts / 1000)
            rows.append((trade_date, close))
        return rows

    @classmethod
    def save_closes(cls, bench_code, rows):
        """
        幂等写入基准日线。

        :param rows: [(trade_date, close)]
        :return: 写入行数；失败返回 0
        """
        if not rows:
            return 0
        query = ("INSERT INTO stock_bench_kline (bench_code, trade_date, close_price) "
                 "VALUES (%s, %s, %s) "
                 "ON DUPLICATE KEY UPDATE close_price = VALUES(close_price)")
        saved = 0
        for trade_date, close in rows:
            try:
                cls.execute_update(query, (bench_code, trade_date, close))
                saved += 1
            except Exception:
                logger.exception('保存基准日线失败 %s %s', bench_code, trade_date)
        return saved

    @classmethod
    def get_recent_closes(cls, bench_code, limit=40):
        """
        取基准最近若干交易日的收盘价，**升序**（旧 → 新），供 `n_day_return` 使用。

        :return: list[float]；无数据或查询失败返回 []
        """
        query = ("SELECT close_price FROM stock_bench_kline WHERE bench_code = %s "
                 "ORDER BY trade_date DESC LIMIT %s")
        try:
            rows = cls.execute_query(query, (bench_code, limit))
        except Exception:
            logger.exception('查询基准日线失败 %s', bench_code)
            return []

        closes = []
        for row in rows:
            try:
                closes.append(float(row['close_price']))
            except (TypeError, ValueError):
                continue
        closes.reverse()  # 查询是 DESC，这里转升序
        return closes

    @classmethod
    def get_latest_trade_date(cls, bench_code):
        """基准最新交易日（date 或字符串，无数据返回 None）。"""
        query = ("SELECT trade_date FROM stock_bench_kline WHERE bench_code = %s "
                 "ORDER BY trade_date DESC LIMIT 1")
        try:
            rows = cls.execute_query(query, (bench_code,))
        except Exception:
            logger.exception('查询基准最新交易日失败 %s', bench_code)
            return None
        return rows[0]['trade_date'] if rows else None

    @classmethod
    def sync_from_snowball(cls, bench_code, days=None):
        """
        从雪球拉取基准指数日线并幂等落库。

        交易时段每日同步一次即可；Token 失效等雪球业务错误只告警不打堆栈（对齐 StockKline 的处理）。

        :param days: 采集窗口（自然日），缺省取 Config.IND_BENCH_WINDOW_DAYS
        :return: 写入行数；失败返回 0
        """
        days = days or Config.IND_BENCH_WINDOW_DAYS
        token = XueqiuToken.TOKEN
        if not token:
            logger.warning('未配置雪球 Token（环境变量 XUEQIU_TOKEN），跳过基准日线采集 %s', bench_code)
            return 0

        try:
            ball.set_token(token)
            rows = cls._split_snowball_kline(ball.kline(bench_code, 'day', days))
        except Exception as exc:
            code, description = parse_xueqiu_error(exc)
            if code is None:
                logger.exception('获取基准日线失败（未知异常）bench=%s', bench_code)
            else:
                logger.warning('%s bench=%s', describe_xueqiu_error(code, description), bench_code)
            return 0

        if not rows:
            logger.warning('未获取到基准日线数据 bench=%s', bench_code)
            return 0

        saved = cls.save_closes(bench_code, rows)
        logger.debug('基准日线已保存 bench=%s count=%s', bench_code, saved)
        return saved
