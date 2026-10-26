"""
AI 分析数据模型（007 AI 个股分析）。

两块：
- `StockAiReport`：报告留痕表 `stock_ai_report`，一次调用一行；追问也留痕（verdict='问答'）；
- `StockAiConfig`：可调参数表 `stock_ai_config`（单行，id=1），**只存非凭据项**。

安全约定：本模块**没有任何字段、任何方法**接触 API Key——密钥永远只在 `config.py` 从环境变量读取。
"""
import json
import logging

from config import Config
from models.base import BaseModel
from utils import ai_client

logger = logging.getLogger(__name__)

# 追问留痕用的 verdict 值：与五档评级区分开，避免污染"评级分布"统计
VERDICT_QA = '问答'

# `stock_ai_config` 的可写字段及默认值（与 database.py 建表默认值保持一致）
CONFIG_DEFAULTS = {
    'enabled': 1,
    'temperature': None,
    'max_tokens': None,
    'monthly_limit': None,
    'data_scope': 'quote,valuation,indicator,kline',
    'model': None,
    'dimensions': None,
}

# 引用数据范围的可选段：页面勾选，落库为逗号串
DATA_SCOPES = {
    'quote': '行情（现价 / 52 周高低）',
    'valuation': '估值（PE / PB）',
    'indicator': '指标（回撤 / 相对强弱）',
    'kline': 'K 线（5 / 20 日涨跌）',
}

# 分析维度白名单：**每个维度都必须有对应数据支撑**，否则模型只能编。
# 设计稿里的「基本面 / 消息面」没有数据源，故不提供（见变更记录 2026-10-22 AI 页改版 §3）。
DIMENSIONS = {
    'valuation': '估值',
    'technical': '技术面',
    'relative': '相对强弱',
    'position': '52 周位置',
    'risk': '风险',
}

# 每个维度的"依据数据"一句话说明：AI 页未选标的时的能力卡片用（必须与 §3.3 的数据依据一致）
DIMENSION_DESCS = {
    'valuation': 'PE / PB 与目标值的偏离',
    'technical': '近 5 / 20 日涨跌与 K 线信号',
    'relative': '对基准指数的超额收益',
    'position': '现价在 52 周区间中的位置',
    'risk': '告警命中与数据缺口',
}


def parse_scope(raw):
    """把 `data_scope` 字符串解析成有序去重的合法段列表（非法段忽略）。"""
    items = [part.strip() for part in str(raw or '').split(',')]
    seen = []
    for item in items:
        if item in DATA_SCOPES and item not in seen:
            seen.append(item)
    return seen


def parse_dimensions(raw, default=None):
    """
    把 `dimensions` 字符串（或列表）解析成有序去重的合法维度键。

    :param raw: `'valuation,risk'` / `['valuation']` / None
    :param default: 全部为空时的回退值（默认取全部维度）
    """
    if isinstance(raw, (list, tuple)):
        items = [str(item).strip() for item in raw]
    else:
        items = [part.strip() for part in str(raw or '').split(',')]
    seen = []
    for item in items:
        if item in DIMENSIONS and item not in seen:
            seen.append(item)
    if seen:
        return seen
    return list(default) if default else list(DIMENSIONS)


class StockAiReport(BaseModel):
    table_name = 'stock_ai_report'

    @classmethod
    def create(cls, stock_master_id, model, prompt_version, verdict,
               confidence=None, content=None, tokens_used=0):
        """
        写入一条报告。

        :param content: dict，会被序列化成 JSON 存进 `content_json`
        :return: 新记录 id；失败返回 None（已记日志）
        """
        query = ("INSERT INTO stock_ai_report "
                 "(stock_master_id, model, prompt_version, verdict, confidence, content_json, tokens_used) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s)")
        params = (stock_master_id, model, prompt_version, verdict, confidence,
                  json.dumps(content or {}, ensure_ascii=False), int(tokens_used or 0))
        try:
            return cls.execute_insert(query, params)
        except Exception:
            logger.exception('保存 AI 报告失败 stock_master_id=%s verdict=%s',
                             stock_master_id, verdict)
            return None

    @classmethod
    def _rows_to_dicts(cls, rows):
        """把 content_json 反序列化，坏数据降级为空 dict 而不是让页面 500。"""
        result = []
        for row in rows:
            item = dict(row)
            try:
                item['content'] = json.loads(item.get('content_json') or '{}')
            except (TypeError, ValueError):
                logger.warning('AI 报告内容不是合法 JSON，按空内容展示 id=%s', item.get('id'))
                item['content'] = {}
            result.append(item)
        return result

    @classmethod
    def list_by_stock(cls, stock_master_id, limit=10):
        """取某标的的报告，按时间倒序（含追问留痕）。失败返回空列表。"""
        query = ("SELECT * FROM stock_ai_report WHERE stock_master_id = %s "
                 "ORDER BY created_at DESC, id DESC LIMIT %s")
        try:
            rows = cls.execute_query(query, (stock_master_id, limit))
        except Exception:
            logger.exception('查询 AI 报告失败 stock_master_id=%s', stock_master_id)
            return []
        return cls._rows_to_dicts(rows)

    @classmethod
    def get_by_id(cls, report_id):
        """按主键取一条报告（含解析后的 content）。不存在返回 None。"""
        query = "SELECT * FROM stock_ai_report WHERE id = %s"
        try:
            rows = cls.execute_query(query, (report_id,))
        except Exception:
            logger.exception('查询 AI 报告详情失败 id=%s', report_id)
            return None
        return cls._rows_to_dicts(rows)[0] if rows else None

    @classmethod
    def latest(cls, stock_master_id):
        """该标的最近一条报告（含追问），无则 None。"""
        rows = cls.list_by_stock(stock_master_id, limit=1)
        return rows[0] if rows else None

    @classmethod
    def latest_analysis(cls, stock_master_id):
        """该标的最近一条**正式分析**（跳过追问留痕），用于追问时的上下文。"""
        query = ("SELECT * FROM stock_ai_report WHERE stock_master_id = %s AND verdict <> %s "
                 "ORDER BY created_at DESC, id DESC LIMIT 1")
        try:
            rows = cls.execute_query(query, (stock_master_id, VERDICT_QA))
        except Exception:
            logger.exception('查询最近分析失败 stock_master_id=%s', stock_master_id)
            return None
        return cls._rows_to_dicts(rows)[0] if rows else None

    @classmethod
    def list_recent(cls, limit=5):
        """
        跨标的最近 N 条记录（含标的名称 / 代码），用于 AI 页「最近分析」快捷入口。

        :return: [{'id', 'stock_master_id', 'verdict', 'created_at', 'stock_name', 'stock_code'}, ...]；
                 查询失败返回空列表
        """
        query = ("SELECT r.id, r.stock_master_id, r.verdict, r.confidence, r.created_at, "
                 "m.stock_name, m.stock_code "
                 "FROM stock_ai_report r "
                 "JOIN stock_master m ON m.id = r.stock_master_id "
                 "ORDER BY r.created_at DESC, r.id DESC LIMIT %s")
        try:
            rows = cls.execute_query(query, (max(1, int(limit or 1)),))
        except Exception:
            logger.exception('查询最近 AI 记录失败')
            return []
        return [dict(row) for row in rows]

    @classmethod
    def count_since(cls, since):
        """
        统计 `since` 之后的调用次数，用于月度上限。

        :param since: datetime
        :return: 次数；查询失败返回 None（调用方据此跳过上限判断而不是误拦）
        """
        query = "SELECT COUNT(*) AS total FROM stock_ai_report WHERE created_at >= %s"
        try:
            rows = cls.execute_query(query, (since,))
        except Exception:
            logger.exception('统计 AI 月度调用次数失败 since=%s', since)
            return None
        return int(rows[0]['total']) if rows else 0


class StockAiConfig(BaseModel):
    table_name = 'stock_ai_config'

    CONFIG_ID = 1

    @classmethod
    def get(cls):
        """
        取参数行；未初始化时返回 None（调用方用 `effective()` 合并默认值）。
        """
        query = "SELECT * FROM stock_ai_config WHERE id = %s"
        try:
            rows = cls.execute_query(query, (cls.CONFIG_ID,))
        except Exception:
            logger.exception('读取 AI 参数失败')
            return None
        return rows[0] if rows else None

    @classmethod
    def upsert(cls, **fields):
        """
        写入参数（行不存在则建）。

        :param fields: enabled / temperature / max_tokens / monthly_limit / data_scope
        :return: True 表示执行成功
        """
        allowed = set(CONFIG_DEFAULTS)
        payload = {key: value for key, value in fields.items() if key in allowed}
        if not payload:
            return False

        columns = ['id'] + list(payload)
        placeholders = ', '.join(['%s'] * len(columns))
        updates = ', '.join(f'{key} = VALUES({key})' for key in payload)
        query = (f"INSERT INTO stock_ai_config ({', '.join(columns)}) "
                 f"VALUES ({placeholders}) "
                 f"ON DUPLICATE KEY UPDATE {updates}")
        params = tuple([cls.CONFIG_ID] + [payload[key] for key in payload])
        try:
            cls.execute_update(query, params)
            return True
        except Exception:
            logger.exception('保存 AI 参数失败')
            return False

    @classmethod
    def effective(cls):
        """
        最终生效的参数：`stock_ai_config` 的**非空**字段覆盖 `Config.AI_*` 默认值。

        :return: dict(enabled, temperature, max_tokens, monthly_limit, data_scope, scope_labels,
                      model, dimensions, dimension_labels)
        """
        env = {
            'enabled': 1 if getattr(Config, 'AI_ENABLED', False) else 0,
            'temperature': getattr(Config, 'AI_TEMPERATURE', 0.6),
            'max_tokens': getattr(Config, 'AI_MAX_TOKENS', 1200),
            'monthly_limit': getattr(Config, 'AI_MONTHLY_LIMIT', 200),
            'data_scope': 'quote,valuation,indicator,kline',
            # AI_MODEL 允许填逗号分隔的清单，默认模型取第一项（整串不能当 model 发出去）
            'model': ai_client.default_model(),
            'dimensions': ','.join(DIMENSIONS),
        }
        row = cls.get() or {}
        merged = dict(env)
        for key in ('temperature', 'max_tokens', 'monthly_limit'):
            value = row.get(key)
            if value is not None:
                merged[key] = float(value) if key == 'temperature' else int(value)
        if row.get('data_scope'):
            merged['data_scope'] = row['data_scope']
        if (row.get('model') or '').strip():
            merged['model'] = row['model'].strip()
        if row.get('dimensions'):
            merged['dimensions'] = row['dimensions']
        # enabled 以「环境开关 且 表内开关」为准：环境变量是总闸，表内只能在其之下关闭
        if 'enabled' in row and row.get('enabled') is not None:
            merged['enabled'] = 1 if (env['enabled'] and int(row['enabled'])) else 0
        merged['scope'] = parse_scope(merged['data_scope'])
        merged['scope_labels'] = [DATA_SCOPES[key] for key in merged['scope']]
        merged['dimension_keys'] = parse_dimensions(merged['dimensions'])
        merged['dimension_labels'] = [DIMENSIONS[key] for key in merged['dimension_keys']]
        return merged
