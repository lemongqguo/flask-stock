"""
指标判定规则（纯函数，无数据库/网络依赖）。

对应 specs：[006 指标监控](../spec/current/006-stock-indicator.md)。

把四条判定式与护栏抽成纯函数的原因与 `utils/alarm_rules.py` 相同：
规则只有一份实现，且可以被单测完整覆盖（含边界与 NULL 语义）。

判定式（均在入参齐全时才可能命中，缺数据一律 False）：
- 52 周新低：`(price - low52w) / low52w * 100 <= low52w_near_pct`
- 52 周回撤：`(price - high52w) / high52w * 100 <= -drawdown_52w_pct`
- 20 日跑输：`ret_20d - bench_ret_20d <= -rs20_pct`
- 5 日倍数：个股与基准同时下跌，且 `|ret_5d| >= rs5_ratio * |bench_ret_5d|`，
           并满足两道护栏 `|ret_5d| >= rs5_min_drop_pct`、`|bench_ret_5d| >= rs5_min_bench_drop_pct`

**组合关系（2026-10-23 起）：四条之间是 AND，不是 OR。**
单条命中的标的太多（尤其 52 周回撤 >35% 是长期持续状态），单条件筛选不符合策略，
故只有**四项同时成立**才构成一次告警；缺任一项数据判 False，组合自然不触发。
见 [../spec/changes/2026-10-23-indicator-combo.md](../spec/changes/2026-10-23-indicator-combo.md)。
"""
import logging

logger = logging.getLogger(__name__)

# 默认基准指数（沪深300）。页面显示与 `config.IND_BENCH` 缺失时的兜底都用它。
DEFAULT_BENCH_CODE = 'SH000300'

# 指标子类型（同时作为 stock_alarm.alarm_subtype 与冷却 key 的一段）
SUBTYPE_LOW52W = 'low52w'
SUBTYPE_DRAWDOWN = 'drawdown'
SUBTYPE_RS20 = 'rs20'
SUBTYPE_RS5 = 'rs5'
SUBTYPES = (SUBTYPE_LOW52W, SUBTYPE_DRAWDOWN, SUBTYPE_RS20, SUBTYPE_RS5)

# 组合信号：四条同时命中才产生的一次告警（不是第五种判据，故不进 SUBTYPES，
# 否则 hit_subtypes / evaluate_indicators 的逐项语义会被污染）
SUBTYPE_COMBO = 'combo'
# 允许写进 stock_alarm.alarm_subtype 的取值：四条原子 + 组合
ALARM_SUBTYPES = SUBTYPES + (SUBTYPE_COMBO,)

SUBTYPE_LABELS = {
    SUBTYPE_LOW52W: '52 周新低',
    SUBTYPE_DRAWDOWN: '52 周回撤',
    SUBTYPE_RS20: '20 日跑输',
    SUBTYPE_RS5: '5 日倍数',
    SUBTYPE_COMBO: '组合信号',
}

# 阈值默认值。与 config.py 的 IND_* 保持一致，但此处不 import config，
# 以保证本模块是纯函数、可在无配置环境下被单测。
DEFAULT_THRESHOLDS = {
    'low52w_near_pct': 5.0,
    'drawdown_52w_pct': 35.0,
    'rs20_pct': 15.0,
    'rs5_ratio': 2.5,
    'rs5_min_drop_pct': 3.0,
    'rs5_min_bench_drop_pct': 0.5,
}

# stock_indicator_config 的可覆盖字段 -> 阈值 dict 的 key
_THRESHOLD_FIELDS = (
    'low52w_near_pct',
    'drawdown_52w_pct',
    'rs20_pct',
    'rs5_ratio',
    'rs5_min_drop_pct',
    'rs5_min_bench_drop_pct',
)


def _to_float(value):
    """把 Decimal / str / int 安全转成 float；不可用时返回 None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_num(value):
    return isinstance(value, (int, float)) and value == value  # 排除 float('nan')


# ----------------------------------------------------------------------
# 阈值解析
# ----------------------------------------------------------------------
def resolve_thresholds(overrides=None, defaults=None):
    """
    解析最终生效的阈值：以默认值为底，用非空的配置行逐字段覆盖。

    :param overrides: stock_indicator_config 的一行（dict）；None 或字段为 NULL 表示继承
    :param defaults: 全局阈值 dict，缺省用 DEFAULT_THRESHOLDS
    :return: 完整的阈值 dict（字段齐备）
    """
    base = dict(defaults or DEFAULT_THRESHOLDS)
    if not overrides:
        return base

    for field in _THRESHOLD_FIELDS:
        value = _to_float(overrides.get(field) if isinstance(overrides, dict) else None)
        if value is not None:
            base[field] = value
    return base


# ----------------------------------------------------------------------
# 涨跌幅
# ----------------------------------------------------------------------
def pct_change(new, old):
    """
    计算涨跌幅百分比：`(new - old) / old * 100`。

    :return: 任一入参缺失或 old 为 0 时返回 None（不参与判定）
    """
    new_val = _to_float(new)
    old_val = _to_float(old)
    if not _is_num(new_val) or not _is_num(old_val) or old_val == 0:
        return None
    return (new_val - old_val) / old_val * 100.0


def n_day_return(closes, days):
    """
    按「交易日条数」计算 N 日涨跌幅百分比。

    :param closes: 收盘价序列，**升序**（旧 → 新）
    :param days: 回溯的交易日数（5 / 20）
    :return: 数据不足 `days + 1` 条时返回 None
             ——对应「新股上市不足 20 个交易日，ret_20d 为 NULL，该指标不参与判定」
    """
    if days is None or days <= 0 or not closes:
        return None
    try:
        series = [float(x) for x in closes]
    except (TypeError, ValueError):
        return None
    if len(series) < days + 1:
        return None
    return pct_change(series[-1], series[-1 - days])


# ----------------------------------------------------------------------
# 四条判定
# ----------------------------------------------------------------------
def check_low52w(price, low52w, near_pct):
    """距 52 周最低不超过 `near_pct`%（含等号）。"""
    price_val = _to_float(price)
    low_val = _to_float(low52w)
    pct = _to_float(near_pct)
    if not _is_num(price_val) or not _is_num(pct):
        return False
    if not _is_num(low_val) or low_val <= 0:
        return False
    return pct_change(price_val, low_val) <= pct


def check_drawdown(price, high52w, drawdown_pct):
    """52 周回撤达到 `drawdown_pct`%（回撤为负值，故判 `<= -阈值`，含等号）。"""
    price_val = _to_float(price)
    high_val = _to_float(high52w)
    pct = _to_float(drawdown_pct)
    if not _is_num(price_val) or not _is_num(pct):
        return False
    if not _is_num(high_val) or high_val <= 0:
        return False
    return pct_change(price_val, high_val) <= -pct


def check_rs20(ret_20d, bench_ret_20d, rs20_pct):
    """20 日跑输基准 `rs20_pct` 个百分点（含等号）。缺任一侧数据返回 False。"""
    stock_ret = _to_float(ret_20d)
    bench_ret = _to_float(bench_ret_20d)
    pct = _to_float(rs20_pct)
    if not _is_num(stock_ret) or not _is_num(bench_ret) or not _is_num(pct):
        return False
    return (stock_ret - bench_ret) <= -pct


def check_rs5(ret_5d, bench_ret_5d, ratio, min_drop_pct, min_bench_drop_pct):
    """
    5 日跌幅倍数：两者均下跌，且 `|个股| >= ratio × |基准|`。

    护栏的必要性：倍数式在横盘市场会失真（基准跌 0.2%、个股跌 0.6% 就满足 2.5 倍），
    故额外要求个股跌幅 ≥ `min_drop_pct`、基准跌幅 ≥ `min_bench_drop_pct`。

    :return: True / False；缺任一侧数据返回 False
    """
    stock_ret = _to_float(ret_5d)
    bench_ret = _to_float(bench_ret_5d)
    ratio_val = _to_float(ratio)
    min_drop = _to_float(min_drop_pct)
    min_bench = _to_float(min_bench_drop_pct)
    if not _is_num(stock_ret) or not _is_num(bench_ret) or not _is_num(ratio_val):
        return False
    if not _is_num(min_drop) or not _is_num(min_bench):
        return False

    stock_drop = -stock_ret
    bench_drop = -bench_ret
    # 两者都必须下跌
    if stock_drop <= 0 or bench_drop <= 0:
        return False
    # 护栏：跌幅太小不判定（避免横盘失真）
    if stock_drop < min_drop or bench_drop < min_bench:
        return False
    return stock_drop >= ratio_val * bench_drop


# ----------------------------------------------------------------------
# 汇总
# ----------------------------------------------------------------------
def evaluate_indicators(snapshot, thresholds=None):
    """
    对一个标的的一组指标输入做完整判定。

    :param snapshot: dict(price, high52w, low52w, ret_5d, ret_20d, bench_ret_5d, bench_ret_20d)
    :param thresholds: 阈值 dict，缺省用 DEFAULT_THRESHOLDS
    :return: dict —— metrics（pct_from_low52w / drawdown_52w / rs_20d / rs_5d_ratio）、
             flags（四条原子指标各自的命中与否）、combo_hit（四条是否同时命中）
    """
    snapshot = snapshot or {}
    th = dict(thresholds or DEFAULT_THRESHOLDS)

    price = snapshot.get('price')
    high52w = snapshot.get('high52w')
    low52w = snapshot.get('low52w')
    ret_5d = snapshot.get('ret_5d')
    ret_20d = snapshot.get('ret_20d')
    bench_ret_5d = snapshot.get('bench_ret_5d')
    bench_ret_20d = snapshot.get('bench_ret_20d')

    pct_from_low = pct_change(price, low52w)
    drawdown = pct_change(price, high52w)
    rs_20d = None
    if _is_num(_to_float(ret_20d)) and _is_num(_to_float(bench_ret_20d)):
        rs_20d = _to_float(ret_20d) - _to_float(bench_ret_20d)

    rs_5d_ratio = None
    stock_drop = -_to_float(ret_5d) if _is_num(_to_float(ret_5d)) else None
    bench_drop = -_to_float(bench_ret_5d) if _is_num(_to_float(bench_ret_5d)) else None
    if stock_drop is not None and bench_drop is not None and bench_drop != 0:
        rs_5d_ratio = stock_drop / bench_drop

    flags = {
        SUBTYPE_LOW52W: check_low52w(price, low52w, th.get('low52w_near_pct')),
        SUBTYPE_DRAWDOWN: check_drawdown(price, high52w, th.get('drawdown_52w_pct')),
        SUBTYPE_RS20: check_rs20(ret_20d, bench_ret_20d, th.get('rs20_pct')),
        SUBTYPE_RS5: check_rs5(
            ret_5d, bench_ret_5d,
            th.get('rs5_ratio'),
            th.get('rs5_min_drop_pct'),
            th.get('rs5_min_bench_drop_pct'),
        ),
    }

    return {
        'pct_from_low52w': pct_from_low,
        'drawdown_52w': drawdown,
        'rs_20d': rs_20d,
        'rs_5d_ratio': rs_5d_ratio,
        'flags': flags,
        # 告警只看这一个值：四条同时成立才发（2026-10-23 组合语义）
        'combo_hit': is_combo_hit(flags),
    }


def hit_subtypes(flags):
    """从 flags dict 中取出命中的子类型列表（顺序固定为 SUBTYPES）。"""
    if not flags:
        return []
    return [subtype for subtype in SUBTYPES if flags.get(subtype)]


def is_combo_hit(flags):
    """
    组合是否命中：**四条全部命中**（AND）才算。

    之所以不再按单条发告警：单条件命中的标的太多（52 周回撤 >35% 是长期持续状态），
    筛出来的结果不符合策略。缺任一数据该条判 False → 组合不命中，
    因此新股（ret_20d 为 NULL）与基准未采集的标的天然不会触发（宁可不报，不可误报）。

    :param flags: evaluate_indicators 返回的 flags dict
    :return: True / False
    """
    if not flags:
        return False
    return all(flags.get(subtype) for subtype in SUBTYPES)


# ----------------------------------------------------------------------
# 告警文案
# ----------------------------------------------------------------------
def _fmt(value, suffix='%'):
    if value is None:
        return '—'
    try:
        return f'{float(value):.2f}{suffix}'
    except (TypeError, ValueError):
        return '—'


def build_indicator_alarm(stock_name, subtype, metrics, thresholds=None, bench_code=''):
    """
    构造指标告警文案。

    :param stock_name: 股票名称
    :param subtype: SUBTYPE_* 之一
    :param metrics: dict(price, low52w, high52w, pct_from_low52w, drawdown_52w,
                         ret_5d, ret_20d, bench_ret_5d, bench_ret_20d, rs_20d, rs_5d_ratio)
    :param thresholds: 阈值 dict，用于文案里回显当前阈值
    :param bench_code: 基准代码，相对强弱类文案会展示
    :return: (subject, body)；未知 subtype 抛 ValueError
    """
    if subtype not in ALARM_SUBTYPES:
        raise ValueError(f'未知的指标子类型: {subtype}')

    metrics = metrics or {}
    th = dict(thresholds or DEFAULT_THRESHOLDS)
    bench = bench_code or '基准'

    if subtype == SUBTYPE_COMBO:
        # 一条邮件交代四项：收到邮件不用再去页面核对为什么被筛出来
        return (
            f'【{stock_name}】四项指标同时触发啦',
            f'【{stock_name}】四项指标同时满足，基准 {bench}：\n'
            f'① 距 52 周低 {_fmt(metrics.get("pct_from_low52w"))}'
            f'（阈值 ≤ {_fmt(th.get("low52w_near_pct"))}），'
            f'现价 {_fmt(metrics.get("price"), "")} / 52 周低 {_fmt(metrics.get("low52w"), "")}；\n'
            f'② 52 周回撤 {_fmt(metrics.get("drawdown_52w"))}'
            f'（阈值 ≤ -{_fmt(th.get("drawdown_52w_pct"), "%")}），'
            f'52 周高 {_fmt(metrics.get("high52w"), "")}；\n'
            f'③ 20 日跑输 {_fmt(metrics.get("rs_20d"))}'
            f'（个股 {_fmt(metrics.get("ret_20d"))} / 基准 {_fmt(metrics.get("bench_ret_20d"))}，'
            f'阈值 ≤ -{_fmt(th.get("rs20_pct"), "%")}）；\n'
            f'④ 5 日倍数 {_fmt(metrics.get("rs_5d_ratio"), " 倍")}'
            f'（个股 {_fmt(metrics.get("ret_5d"))} / 基准 {_fmt(metrics.get("bench_ret_5d"))}，'
            f'阈值 ≥ {_fmt(th.get("rs5_ratio"), " 倍")}）。'
        )

    if subtype == SUBTYPE_LOW52W:
        subject = f'【{stock_name}】接近 52 周最低啦'
        body = (f'【{stock_name}】接近 52 周最低！'
                f'当前价格: {_fmt(metrics.get("price"), "")}，'
                f'52 周最低: {_fmt(metrics.get("low52w"), "")}'
                f'（高于低点 {_fmt(metrics.get("pct_from_low52w"))}，'
                f'阈值 ≤ {_fmt(th.get("low52w_near_pct"))}）')
    elif subtype == SUBTYPE_DRAWDOWN:
        subject = f'【{stock_name}】52 周回撤达到阈值啦'
        body = (f'【{stock_name}】52 周回撤达到阈值！'
                f'当前价格: {_fmt(metrics.get("price"), "")}，'
                f'52 周最高: {_fmt(metrics.get("high52w"), "")}'
                f'（回撤 {_fmt(metrics.get("drawdown_52w"))}，'
                f'阈值 ≤ -{_fmt(th.get("drawdown_52w_pct"), "%")}）')
    elif subtype == SUBTYPE_RS20:
        subject = f'【{stock_name}】20 日跑输基准啦'
        body = (f'【{stock_name}】20 日跑输基准阈值！'
                f'个股 20 日涨跌: {_fmt(metrics.get("ret_20d"))}，'
                f'{bench}: {_fmt(metrics.get("bench_ret_20d"))}'
                f'（差值 {_fmt(metrics.get("rs_20d"))}，'
                f'阈值 ≤ -{_fmt(th.get("rs20_pct"), "%")}）')
    else:
        subject = f'【{stock_name}】5 日跌幅达基准倍数啦'
        body = (f'【{stock_name}】5 日跌幅达到基准倍数！'
                f'个股 5 日: {_fmt(metrics.get("ret_5d"))}，'
                f'{bench}: {_fmt(metrics.get("bench_ret_5d"))}'
                f'（倍数 {_fmt(metrics.get("rs_5d_ratio"), " 倍")}，'
                f'阈值 ≥ {_fmt(th.get("rs5_ratio"), " 倍")}；'
                f'护栏：个股跌幅 ≥ {_fmt(th.get("rs5_min_drop_pct"))}、'
                f'基准跌幅 ≥ {_fmt(th.get("rs5_min_bench_drop_pct"))}）')

    return subject, body
