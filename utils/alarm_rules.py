"""
告警判定规则（纯函数，无数据库/网络依赖）。

把原先内联在 StockMonitor.check_and_alert 中的档位判断抽出来，
便于单元测试覆盖（见 tests/test_alarm_rules.py），并保证规则只有一份实现。
"""
import re

# 告警类型（同时用于冷却 key 与前端识别）
ALARM_TYPE_SELL = 'sell'
ALARM_TYPE_PRICE = 'price'
ALARM_TYPE_PE = 'pe'
ALARM_TYPE_PB = 'pb'
ALARM_TYPE_INDICATOR = 'indicator'
ALARM_TYPE_UNKNOWN = 'unknown'

# 邮件通知状态
NOTIFY_PENDING = 'pending'
NOTIFY_SENT = 'sent'
NOTIFY_FAILED = 'failed'
NOTIFY_SKIPPED = 'skipped'
NOTIFY_UNKNOWN = 'unknown'

GEAR_LABELS = {1: '第一档', 2: '第二档', 3: '第三档'}

# 告警类型 -> 中文名（告警历史的 type_badge 与每日汇总邮件共用，避免两处各写一套）
TYPE_LABELS = {
    ALARM_TYPE_SELL: '卖出',
    ALARM_TYPE_PRICE: '价格',
    ALARM_TYPE_PE: 'PE',
    ALARM_TYPE_PB: 'PB',
    ALARM_TYPE_INDICATOR: '指标',
    ALARM_TYPE_UNKNOWN: '未知',
}


def determine_lower_gear(current, valueone, valuetwo, valuethree):
    """
    判断"当前值下探到第几档阈值"。

    判定顺序（与历史行为保持一致）：先看第一档，命中后再看第二档，
    再命中则看第三档。因此数值越小越先触发，返回档位越大。

    :param current: 当前值（价格 / PE / PB），为 None 时不告警
    :param valueone: 第一档阈值，None/0 视为未设置
    :param valuetwo: 第二档阈值
    :param valuethree: 第三档阈值
    :return: 1 / 2 / 3，未命中任何档位返回 None
    """
    if current is None or not valueone:
        return None
    if current > valueone:
        return None

    if valuetwo and current <= valuetwo:
        if valuethree and current <= valuethree:
            return 3
        return 2
    return 1


def check_sell(current, sell_rate):
    """是否达到卖出价。阈值未设置或当前值缺失时不告警。"""
    if current is None or not sell_rate:
        return False
    return current >= sell_rate


def build_sell_alarm(stock_name, current, sell_rate):
    """构造卖出告警文案。"""
    body = f"【{stock_name}】达到目标卖出价！当前价格: {current}，目标卖出价: {sell_rate}"
    subject = f"【{stock_name}】到卖出价格啦~"
    return subject, body


def build_gear_alarm(stock_name, alarm_type, gear, current, threshold):
    """
    构造档位告警文案。

    :param alarm_type: ALARM_TYPE_PRICE / ALARM_TYPE_PE / ALARM_TYPE_PB
    """
    label = GEAR_LABELS[gear]
    if alarm_type == ALARM_TYPE_PRICE:
        body = f"【{stock_name}】达到{label}建仓阈值！当前价格: {current}，{label}阈值: {threshold}"
        subject = f"【{stock_name}】到第{gear}档关注点位啦"
    elif alarm_type == ALARM_TYPE_PE:
        body = f"【{stock_name}】PE达到{label}告警阈值！当前PE: {current}，{label}阈值: {threshold}"
        subject = f"【{stock_name}】PE到第{gear}档关注点位啦"
    elif alarm_type == ALARM_TYPE_PB:
        body = f"【{stock_name}】PB达到{label}告警阈值！当前PB: {current}，{label}阈值: {threshold}"
        subject = f"【{stock_name}】PB到第{gear}档关注点位啦"
    else:
        raise ValueError(f'未知的告警类型: {alarm_type}')
    return subject, body


def threshold_of(gear, valueone, valuetwo, valuethree):
    """按档位取出对应阈值文本。"""
    return {1: valueone, 2: valuetwo, 3: valuethree}[gear]


def alarm_key_prefix(stock_master_id, alarm_type):
    """告警 key 前缀，形如 `12:price`，用于批量清理某订单某类型的冷却记录。"""
    return f'{stock_master_id}:{alarm_type}'


def make_alarm_key(stock_master_id, alarm_type, gear=None, subtype=None):
    """
    生成告警冷却 key。

    同一订单 + 同一告警类型（+ 同一档位 / 同一指标子类型）在冷却期内只允许产生一次告警，
    解决"阈值持续满足导致每轮重复告警、重复发邮件"的问题（D-03）。

    :param gear: 价格 / PE / PB 的档位（1/2/3）
    :param subtype: 指标类子类型（low52w / drawdown / rs20 / rs5），
                    与 gear 互斥，用于让 4 种指标各自独立冷却
    """
    prefix = alarm_key_prefix(stock_master_id, alarm_type)
    segment = subtype if subtype else gear
    return prefix if segment is None else f'{prefix}:{segment}'


# ----------------------------------------------------------------------
# 存量告警文本归类（用于历史数据回填）
# ----------------------------------------------------------------------

# 文本中的档位描述，例如"达到第二档建仓阈值"、"PE到第3档关注点位啦"
_GEAR_PATTERN = re.compile(r'第\s*([一二三1-3])\s*档')
_GEAR_CHARS = {'一': 1, '二': 2, '三': 3, '1': 1, '2': 2, '3': 3}


def build_daily_summary(summary):
    """
    构造「每日汇总」邮件文案（纯函数，便于单测）。

    :param summary: dict(hours, total, by_type, samples)，由 `StockAlarm.summarize_since` 提供
    :return: (subject, body)
    """
    summary = summary or {}
    hours = summary.get('hours') or 24
    total = int(summary.get('total') or 0)
    by_type = summary.get('by_type') or {}
    samples = summary.get('samples') or []

    subject = f'【股池监控台】近 {hours} 小时告警汇总（{total} 条）'
    lines = [f'近 {hours} 小时共触发 {total} 条告警：']

    if by_type:
        parts = [
            f'{TYPE_LABELS.get(alarm_type, alarm_type)} {count} 条'
            for alarm_type, count in sorted(by_type.items(), key=lambda kv: -kv[1])
        ]
        lines.append(' · '.join(parts))
    else:
        lines.append('（无类型分布）')

    if samples:
        lines.append('')
        lines.append('最近告警：')
        for item in samples:
            alarm_type = item.get('alarm_type') or ALARM_TYPE_UNKNOWN
            lines.append(
                f"- {item.get('alarm_time')}　{item.get('stock_name') or '未知标的'}　"
                f"{TYPE_LABELS.get(alarm_type, alarm_type)}：{item.get('alarm_text')}"
            )

    lines.append('')
    lines.append('完整记录见「告警历史」页面。')
    return subject, '\n'.join(lines)


def parse_gear_from_text(text):
    """从告警文本中提取档位（1/2/3）；提取不到返回 None。"""
    if not text:
        return None
    match = _GEAR_PATTERN.search(text)
    if not match:
        return None
    return _GEAR_CHARS.get(match.group(1))


def classify_alarm_text(alarm_text):
    """
    从历史告警文本推断告警类型与档位。

    仅用于**存量数据回填**：`stock_alarm` 早期没有类型字段，只能靠文本反推。
    无法识别时返回 `('unknown', None)`——宁可留白也不猜测（历史文本格式并不统一）。

    :param alarm_text: 告警正文
    :return: (alarm_type, alarm_level)
    """
    if not alarm_text:
        return ALARM_TYPE_UNKNOWN, None

    text = str(alarm_text)
    gear = parse_gear_from_text(text)

    if '卖出' in text:
        return ALARM_TYPE_SELL, None
    if 'PE' in text.upper():
        return ALARM_TYPE_PE, gear
    if 'PB' in text.upper():
        return ALARM_TYPE_PB, gear
    if '建仓' in text or '买入' in text:
        return ALARM_TYPE_PRICE, gear
    return ALARM_TYPE_UNKNOWN, None
