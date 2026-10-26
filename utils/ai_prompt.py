"""
AI 分析的输入组装与输出解析（007 AI 个股分析）。

把「系统已有数据」压成一段确定性文本喂给模型，再把模型返回的 JSON 解析成页面可直接渲染的结构。
**不做任何外部取数**：输入只来自 `stock_master` / `stock_warehouse` / `stock_indicator` / `stock_kline`。

单独成文件的原因：提示词与解析是纯函数，能脱离网络与数据库单测（模型回答不确定，
但"给定回答能解析成什么"必须确定）。
"""
import json
import logging

from utils.indicator_rules import n_day_return

logger = logging.getLogger(__name__)

# 提示词版本：改动 SYSTEM_PROMPT 或解析结构时递增，报告里会留痕，便于事后追溯"当时用的哪版"
PROMPT_VERSION = 'ai-007-v1'

DISCLAIMER = '本报告由 AI 基于公开行情数据生成，不构成投资建议。'

# 允许的评级枚举：既是给模型的约束，也是解析时兜底映射的白名单
VERDICTS = ('买入', '增持', '持有', '减持', '回避')

_VERDICT_ALIASES = {
    'buy': '买入', 'strong_buy': '买入', '买入': '买入',
    'overweight': '增持', 'add': '增持', '增持': '增持',
    'hold': '持有', 'neutral': '持有', '持有': '持有', '中性': '持有',
    'underweight': '减持', 'reduce': '减持', '减持': '减持',
    'sell': '回避', 'avoid': '回避', '回避': '回避', '卖出': '回避',
}

SYSTEM_PROMPT = """你是一名严谨的 A 股研究助理。用户会给你一只股票的结构化行情与指标数据。

要求：
1. 只依据给定数据推理，缺失的数据要明确说"数据不足"，禁止编造财务数据、行业消息或政策预期；
2. 必须输出**单个 JSON 对象**，不要 Markdown 代码块、不要额外解释文字；
3. JSON 字段固定为：
   - verdict: 五档之一（买入 / 增持 / 持有 / 减持 / 回避）
   - confidence: 0-100 的整数，表示结论的置信度
   - summary: 一句话核心结论（不超过 80 字）
   - points: 字符串数组，3-5 条关键要点（每条不超过 60 字）
   - supports: 字符串数组，支撑结论的数据依据（引用给到的数字）
   - risks: 字符串数组，风险与反向可能
   - disclaimer: 固定输出「本报告由 AI 基于公开行情数据生成，不构成投资建议。」
4. 语气客观，不夸大，不使用"必涨""稳赚"等表述。"""


def _num(value, digits=2):
    """把 Decimal/str/None 统一成 float 或 None（不用 0 冒充缺失）。"""
    if value is None or value == '':
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _pct(value, digits=2):
    """百分比字段：缺失返回 None，保留时返回 float。"""
    return _num(value, digits)


def build_context(stock, warehouse=None, indicator=None, closes=None, scope=None):
    """
    组装喂给模型的上下文（纯 dict，便于单测）。

    `scope` 是页面「引用数据范围」的落地：不在范围内的字段**一律置 None**，
    这样提示词里显示「数据不足」，模型不会拿用户已关掉的数据下结论。

    :param stock: `stock_master` 行（dict，含 stock_name/stock_code/current_pe/current_pb）
    :param warehouse: `stock_warehouse` 模型对象或 dict（取 current_price 等）
    :param indicator: `stock_indicator` 行（dict），None 表示尚未采集
    :param closes: 个股最近收盘价，升序；用于指标缺失时兜底计算 5 / 20 日涨跌
    :param scope: 引用范围列表（quote / valuation / indicator / kline），None 表示全用
    :return: dict
    """
    def pick(obj, key):
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    scope = tuple(scope) if scope else ('quote', 'valuation', 'indicator', 'kline')
    use_quote = 'quote' in scope
    use_valuation = 'valuation' in scope
    use_indicator = 'indicator' in scope
    use_kline = 'kline' in scope

    price = _num(pick(warehouse, 'current_price'))
    if price is None and indicator:
        price = _num(indicator.get('price'))

    ret_5d = _pct(indicator.get('ret_5d')) if (indicator and use_kline) else None
    ret_20d = _pct(indicator.get('ret_20d')) if (indicator and use_kline) else None
    if closes and use_kline:
        if ret_5d is None:
            ret_5d = _pct(n_day_return(closes, 5))
        if ret_20d is None:
            ret_20d = _pct(n_day_return(closes, 20))

    context = {
        'stock_name': pick(stock, 'stock_name'),
        'stock_code': pick(stock, 'stock_code'),
        'price': price if use_quote else None,
        'pe': _num(pick(stock, 'current_pe')) if use_valuation else None,
        'pe_target': _num(pick(stock, 'target_pettm')) if use_valuation else None,
        'pb': _num(pick(stock, 'current_pb')) if use_valuation else None,
        'pb_target': _num(pick(stock, 'target_pb')) if use_valuation else None,
        'high52w': _num(indicator.get('high52w')) if (indicator and use_indicator) else None,
        'low52w': _num(indicator.get('low52w')) if (indicator and use_indicator) else None,
        'pct_from_low52w': _pct(indicator.get('pct_from_low52w')) if (indicator and use_indicator) else None,
        'drawdown_52w': _pct(indicator.get('drawdown_52w')) if (indicator and use_indicator) else None,
        'ret_5d': ret_5d,
        'ret_20d': ret_20d,
        'rs_20d': _pct(indicator.get('rs_20d')) if (indicator and use_indicator) else None,
        'rs_5d_ratio': _num(indicator.get('rs_5d_ratio')) if (indicator and use_indicator) else None,
        'trade_date': str(indicator.get('trade_date')) if indicator and indicator.get('trade_date') else None,
        'has_indicator': indicator is not None and use_indicator,
        'scope': list(scope),
    }

    # 告警命中的指标：直接告诉模型"系统已判定命中"，避免它把明显风险读成正常
    hits = []
    if indicator and use_indicator:
        for sub, label in (('low52w', '52 周新低'), ('drawdown', '52 周回撤'),
                           ('rs20', '20 日跑输基准'), ('rs5', '5 日急跌')):
            if indicator.get('flag_' + sub):
                hits.append(label)
    context['indicator_hits'] = hits
    return context


def _fmt(value, suffix='', digits=2):
    """上下文文本里的数字格式化：缺失写「数据不足」，不写 0。"""
    if value is None:
        return '数据不足'
    if isinstance(value, (int, float)):
        return f'{value:.{digits}f}{suffix}'
    return f'{value}{suffix}'


def build_messages(context, dimensions=None):
    """
    组装一次「首次分析」的消息列表。

    :param context: `build_context()` 的返回值
    :param dimensions: 本次要求的分析维度（中文标签列表）；为空表示不限维度
    :return: [{'role': 'system'|'user', 'content': str}]
    """
    lines = [
        f"标的：{context.get('stock_name') or '—'}（{context.get('stock_code') or '—'}）",
        f"现价：{_fmt(context.get('price'))}",
        f"PE（TTM）：{_fmt(context.get('pe'))}｜PE 目标：{_fmt(context.get('pe_target'))}",
        f"PB：{_fmt(context.get('pb'))}｜PB 目标：{_fmt(context.get('pb_target'))}",
        f"52 周区间：{_fmt(context.get('low52w'))} ~ {_fmt(context.get('high52w'))}",
        f"距 52 周低：{_fmt(context.get('pct_from_low52w'), '%')}"
        f"｜52 周回撤：{_fmt(context.get('drawdown_52w'), '%')}",
        f"5 日涨跌：{_fmt(context.get('ret_5d'), '%')}"
        f"｜20 日涨跌：{_fmt(context.get('ret_20d'), '%')}",
        f"20 日相对基准：{_fmt(context.get('rs_20d'), '%')}"
        f"｜5 日跌幅倍数：{_fmt(context.get('rs_5d_ratio'), ' 倍')}",
        f"数据日期：{context.get('trade_date') or '数据不足'}",
    ]
    scope = context.get('scope') or []
    if scope and len(scope) < 4:
        lines.append('本次仅允许引用以下数据：' + '、'.join(scope)
                     + '；其余字段显示为「数据不足」，不要据此推断。')
    if not context.get('has_indicator'):
        lines.append('注意：该标的尚未采集指标快照，52 周区间与相对强弱等数据缺失，请据此降低置信度。')
    hits = context.get('indicator_hits') or []
    if hits:
        lines.append('系统已判定的指标命中：' + '、'.join(hits))

    dims = [str(dim).strip() for dim in (dimensions or []) if str(dim).strip()]
    if dims:
        lines.append('本次要求的分析维度：' + '、'.join(dims)
                     + '。请在 points 里每个维度至少给一条结论，'
                       '维度对应的数据缺失时直接写「数据不足」，不要从别的维度外推。')

    lines.append('请按要求输出 JSON。')
    return [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': '\n'.join(lines)},
    ]


def build_followup_messages(context, question, previous_report=None):
    """
    组装「追问」的消息：把已生成的报告作为上下文，避免模型忘掉前文。

    :param question: 用户的追问（已校验非空）
    :param previous_report: 上一次报告的结构化 dict（可为 None）
    """
    # 末尾那条才是「标的 + 数据」的用户消息；早先误取 lines[-2]（system 全文），
    # 导致追问时数据上下文根本没进提示词，只剩上一轮报告的 JSON。
    data_block = [m['content'] for m in build_messages(context)][-1]
    blocks = [
        '以下是上一轮分析结果（JSON），请在此基础上回答用户的追问：',
        json.dumps(previous_report or {}, ensure_ascii=False),
        '',
        '用户的追问：' + question,
        '请直接回答，不要重复整份报告；如涉及新数字，只能使用上面给到的数据。',
    ]
    return [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': data_block + '\n\n' + '\n'.join(blocks)},
    ]


def _strip_code_fence(text):
    """去掉 ```json ... ``` 包裹。"""
    body = (text or '').strip()
    if not body.startswith('```'):
        return body
    body = body.split('\n', 1)[-1]
    if body.rstrip().endswith('```'):
        body = body.rstrip()[:-3]
    return body.strip()


def _normalize_verdict(raw):
    """评级归一化：大小写/英文别名都映射到五档中文，无法识别返回「未知」。"""
    key = str(raw or '').strip().lower()
    return _VERDICT_ALIASES.get(key, '未知')


def _as_list(value, limit=8):
    """把模型可能给出的字符串/数组统一成字符串数组，去掉空项。"""
    if value is None:
        return []
    if isinstance(value, str):
        items = [line.strip(' -•\t') for line in value.splitlines()]
    elif isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value]
    else:
        return []
    return [item for item in items if item][:limit]


def parse_report(text):
    """
    把模型返回解析成结构化报告。

    **解析失败不抛异常**：退化成「未知评级 + 原文摘要」，页面照样能显示，
    同时在结果里标 `parsed=False`，视图据此提示"模型未按格式返回"。

    :param text: 模型返回的正文
    :return: dict(verdict, confidence, summary, points, supports, risks, disclaimer, raw, parsed)
    """
    raw = (text or '').strip()
    body = _strip_code_fence(raw)

    payload = None
    try:
        payload = json.loads(body)
    except ValueError:
        # 模型偶尔会在 JSON 前后加话术：截取第一个 { 到最后一个 } 再试一次
        start, end = body.find('{'), body.rfind('}')
        if 0 <= start < end:
            try:
                payload = json.loads(body[start:end + 1])
            except ValueError:
                payload = None

    if not isinstance(payload, dict):
        if raw:
            logger.warning('AI 返回不是合法 JSON，退化为纯文本摘要（长度 %s）', len(raw))
        return {
            'verdict': '未知',
            'confidence': None,
            'summary': raw[:500],
            'points': [],
            'supports': [],
            'risks': [],
            'disclaimer': DISCLAIMER,
            'raw': raw,
            'parsed': False,
        }

    confidence = _num(payload.get('confidence'), 0)
    if confidence is not None:
        confidence = max(0.0, min(100.0, confidence))

    return {
        'verdict': _normalize_verdict(payload.get('verdict')),
        'confidence': confidence,
        'summary': str(payload.get('summary') or '').strip()[:500],
        'points': _as_list(payload.get('points')),
        'supports': _as_list(payload.get('supports')),
        'risks': _as_list(payload.get('risks')),
        # 免责声明以本地常量为准：模型漏写或改写都不能影响合规要求
        'disclaimer': DISCLAIMER,
        'raw': raw,
        'parsed': True,
    }
