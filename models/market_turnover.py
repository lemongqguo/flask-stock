# -*- coding: utf-8 -*-
"""
市场成交额数据模型（009 市场成交额）。

表 `market_daily_turnover`：沪深北三市每日成交额与合计，单位**亿元**（DECIMAL(18,4)，
与历史 CSV 四位小数一致），`trade_date` 唯一键 + `ON DUPLICATE KEY UPDATE` 幂等 upsert，
当日盘中快照允许被收盘终值覆盖。

三条写入路径共用 `upsert_rows`：
- `sync_from_source`：日常同步（东财主源 / 腾讯备源；2026-11-13 起库非空走增量、
  库空 / 超窗 / --full 走全量，全量 + 备源带 60 日写入保护，见 ADR-006 / ADR-008）；
- `import_csv`：历史 CSV 导入（example 口径，整体校验通过才写入）；
- 页面「同步数据」按钮与监控线程自动同步（默认 3h）都走 `sync_from_source`，页面本身只读库。

纯函数 `parse_csv_rows` / `dashboard_payload` 不碰数据库，便于单测。
"""
import csv
import datetime
import logging
import os

from models.base import BaseModel
from utils import turnover_source

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CSV_PATH = os.path.join(BASE_DIR, 'example', 'A股每日成交额_1990至今.csv')

# example 输出的固定表头（顺序敏感）
CSV_COLUMNS = ('日期', '沪市成交额(亿元)', '深市成交额(亿元)', '北证成交额(亿元)', '合计成交额(亿元)')
# 合计校验容差（亿元）：CSV 四位小数舍入，分量和与合计允许 0.0002 的差
TOTAL_TOLERANCE = 0.0002
SOURCE_CSV = 'CSV导入'

# 可更新字段（trade_date 是唯一键不参与 UPDATE；created_at 保留首次写入时间）
_UPSERT_FIELDS = ('sh_amount', 'sz_amount', 'bj_amount', 'total_amount', 'source')


def parse_csv_rows(path):
    """
    解析并校验 example 口径的成交额 CSV，返回入库行（单位亿元，缺失保留 None）。

    校验项：表头 / 日期格式与唯一 / 数值合法非负 / 合计=分量和（容差 TOTAL_TOLERANCE）。
    **任何一行不合法即整体拒绝**（抛 ValueError），不做部分导入——
    历史数据宁可不进，不可进一半。
    """
    if not os.path.isfile(path):
        raise ValueError('CSV 文件不存在：%s' % path)

    rows = []
    seen = set()
    with open(path, encoding='utf-8') as fp:
        reader = csv.DictReader(fp)
        if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
            raise ValueError('CSV 表头不符，期望：%s' % ','.join(CSV_COLUMNS))
        for lineno, raw in enumerate(reader, start=2):
            day = (raw.get('日期') or '').strip()
            try:
                datetime.datetime.strptime(day, '%Y-%m-%d')
            except ValueError:
                raise ValueError('第 %d 行日期非法：%r' % (lineno, day))
            if day in seen:
                raise ValueError('第 %d 行日期重复：%s' % (lineno, day))
            seen.add(day)

            amounts = []
            for col in CSV_COLUMNS[1:4]:
                text = (raw.get(col) or '').strip()
                if text == '':
                    amounts.append(None)  # 北证早期 / 深市开业前：留空不伪造 0
                    continue
                try:
                    value = float(text)
                except ValueError:
                    raise ValueError('第 %d 行「%s」非数值：%r' % (lineno, col, text))
                if value < 0:
                    raise ValueError('第 %d 行「%s」为负数：%s' % (lineno, col, text))
                amounts.append(value)

            total_text = (raw.get(CSV_COLUMNS[4]) or '').strip()
            try:
                total = float(total_text)
            except ValueError:
                raise ValueError('第 %d 行合计非数值：%r' % (lineno, total_text))
            if total < 0:
                raise ValueError('第 %d 行合计为负数：%s' % (lineno, total_text))
            if abs(total - sum(v or 0.0 for v in amounts)) > TOTAL_TOLERANCE:
                raise ValueError('第 %d 行合计与分量和不符（%s）：%s' % (lineno, day, total_text))

            rows.append({
                'trade_date': day,
                'sh_amount': amounts[0],
                'sz_amount': amounts[1],
                'bj_amount': amounts[2],
                'total_amount': total,
            })

    if not rows:
        raise ValueError('CSV 没有数据行：%s' % path)
    return rows


def dashboard_payload(rows, updated_at=None):
    """
    把库里的行（按日期升序）组装成页面数据，结构与 example 的 data.json 同构。

    展示值统一 round 2（亿元），缺失保留 None（前端渲染「—」）；
    统计口径与 example write_dashboard 一致：排名 / 峰值 / 近 20 日均值。
    纯函数，不碰数据库。
    """
    if not rows:
        return None

    def _f(value):
        return None if value is None else round(float(value), 2)

    def _day(value):
        return str(value)[:10]

    latest = rows[-1]
    latest_total = float(latest['total_amount'])
    rank = 1 + sum(1 for r in rows if float(r['total_amount']) > latest_total)
    peak = max(rows, key=lambda r: float(r['total_amount']))
    recent = rows[-20:]
    avg20 = sum(float(r['total_amount']) for r in recent) / len(recent)

    return {
        'updated_at': updated_at or '',
        'source': latest.get('source') or '',
        'latest': {
            'date': _day(latest['trade_date']),
            'sh': _f(latest['sh_amount']),
            'sz': _f(latest['sz_amount']),
            'bj': _f(latest['bj_amount']),
            'total': _f(latest['total_amount']),
        },
        'stats': {
            'rank': rank,
            'days': len(rows),
            'peak_date': _day(peak['trade_date']),
            'peak_total': _f(peak['total_amount']),
            'avg20': round(avg20, 2),
        },
        'history': [
            [_day(r['trade_date']), _f(r['sh_amount']), _f(r['sz_amount']),
             _f(r['bj_amount']), _f(r['total_amount'])]
            for r in rows
        ],
    }


class MarketDailyTurnover(BaseModel):
    table_name = 'market_daily_turnover'

    @classmethod
    def count(cls):
        """库内交易日总数（备源保护判定要用）。"""
        result = cls.execute_query('SELECT COUNT(*) AS total FROM market_daily_turnover')
        return result[0]['total'] if result else 0

    @classmethod
    def get_history(cls, start_date=None, end_date=None):
        """按日期升序取历史（可选区间过滤），供页面与统计使用。"""
        query = ('SELECT trade_date, sh_amount, sz_amount, bj_amount, total_amount, source '
                 'FROM market_daily_turnover')
        conditions, params = [], []
        if start_date:
            conditions.append('trade_date >= %s')
            params.append(start_date)
        if end_date:
            conditions.append('trade_date <= %s')
            params.append(end_date)
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
        query += ' ORDER BY trade_date ASC'
        return cls.execute_query(query, tuple(params))

    @classmethod
    def get_latest(cls):
        """最新一个交易日（含数据源与更新时间）。"""
        rows = cls.execute_query(
            'SELECT trade_date, sh_amount, sz_amount, bj_amount, total_amount, source, updated_at '
            'FROM market_daily_turnover ORDER BY trade_date DESC LIMIT 1'
        )
        return rows[0] if rows else None

    @classmethod
    def upsert_rows(cls, rows, source):
        """
        批量幂等写入（ON DUPLICATE KEY UPDATE，trade_date 唯一键）。

        用 execute_many 单连接批量执行：8807 行逐条写会把连接占用放大几千倍（D-07 同类教训）。
        :return: 受影响行数（MySQL 语义：插入计 1、更新计 2，仅供日志参考）
        """
        if not rows:
            return 0
        columns = ('trade_date',) + _UPSERT_FIELDS
        placeholders = ', '.join(['%s'] * len(columns))
        updates = ', '.join('%s = VALUES(%s)' % (f, f) for f in _UPSERT_FIELDS)
        query = (
            'INSERT INTO market_daily_turnover (%s) VALUES (%s) '
            'ON DUPLICATE KEY UPDATE %s' % (', '.join(columns), placeholders, updates)
        )
        seq_params = [
            (r['trade_date'], r['sh_amount'], r['sz_amount'], r['bj_amount'], r['total_amount'], source)
            for r in rows
        ]
        return cls.execute_many(query, seq_params)

    @classmethod
    def sync_from_source(cls, source='auto', full=False):
        """
        从数据源同步每日成交额（日常更新入口，页面按钮 / CLI / 监控线程共用）。

        取数模式（2026-11-13 增量改造，ADR-008）：
        - 库非空且最新日期距今 ≤ INCREMENTAL_MAX_GAP_DAYS 自然日 → **增量**：
          只取最近约 60 个交易日（东财动态 beg / 腾讯单页 count），取数窗口本身即写入保护；
        - 库为空 / 超窗 / full=True → **全量**（原有逻辑）；
        - 全量 + 腾讯备源 + 库非空 → **60 日写入保护**（对齐 example write_csv 的 protect
          语义，ADR-006）：只 upsert 最近 60 个交易日，更早数据不动；库为空可全量写入。
        """
        since = None
        if not full:
            latest = cls.get_latest()
            if latest is not None:
                latest_day = str(latest['trade_date'])[:10]
                gap = (datetime.date.today()
                       - datetime.datetime.strptime(latest_day, '%Y-%m-%d').date()).days
                if gap <= turnover_source.INCREMENTAL_MAX_GAP_DAYS:
                    since = latest_day
                else:
                    logger.info('库内最新日期 %s 距今 %d 天，超出增量窗口，回退全量同步',
                                latest_day, gap)

        shanghai, shenzhen, beijing, label = turnover_source.fetch_all(source, since=since)
        rows = turnover_source.build_rows(shanghai, shenzhen, beijing)

        protected_before = None
        if (since is None and label == turnover_source.SOURCE_TENCENT
                and rows and cls.count() > 0):
            protected_before = rows[-turnover_source.BACKUP_PROTECT_DAYS:][0]['trade_date']
            rows = [r for r in rows if r['trade_date'] >= protected_before]

        affected = cls.upsert_rows(rows, label)
        summary = {
            'source': label,
            'mode': 'incremental' if since else 'full',
            'days': len(rows),
            'affected': affected,
            'protected_before': protected_before,
            'start_date': rows[0]['trade_date'] if rows else None,
            'end_date': rows[-1]['trade_date'] if rows else None,
        }
        logger.info('市场成交额同步完成：%s', summary)
        return summary

    @classmethod
    def import_csv(cls, path=None):
        """
        导入历史 CSV（默认 example 已拉好的全量文件），幂等可重复执行。

        先整体校验再写入：任何一行不合法即拒绝，不会出现「进了一半」的历史。
        """
        path = path or DEFAULT_CSV_PATH
        rows = parse_csv_rows(path)
        affected = cls.upsert_rows(rows, SOURCE_CSV)
        summary = {
            'source': SOURCE_CSV,
            'days': len(rows),
            'affected': affected,
            'start_date': rows[0]['trade_date'],
            'end_date': rows[-1]['trade_date'],
        }
        logger.info('市场成交额 CSV 导入完成：%s（%s）', summary, path)
        return summary

    @classmethod
    def build_dashboard(cls):
        """页面数据：全部历史 + 最新 / 排名 / 峰值 / 近 20 日均值；表为空返回 None。"""
        rows = cls.get_history()
        if not rows:
            return None
        result = cls.execute_query('SELECT MAX(updated_at) AS ts FROM market_daily_turnover')
        updated_at = result[0]['ts'] if result else None
        if isinstance(updated_at, datetime.datetime):
            updated_at = updated_at.strftime('%Y-%m-%d %H:%M:%S')
        return dashboard_payload(rows, updated_at=updated_at)