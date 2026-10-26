"""
系统状态聚合。

把监控服务的运行状态转成页面可直接展示的文案，供**侧栏底部**与**顶栏徽标**共用——
两处共用同一份数据，避免各写一套导致显示不一致。

文案与判定都在这里，模板只负责渲染。
"""
import time

from utils.trading_time import describe_session, is_trading_day

# 交易时段键 → 展示文案
SESSION_LABELS = {
    'morning': '早盘交易中',
    'afternoon': '午盘交易中',
    'noon': '午间休市',
    'closed': '已收盘',
}


def format_duration(seconds):
    """秒数 → 中文时长（用于告警冷却展示）。"""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return '—'
    if seconds <= 0:
        return '不限制'
    if seconds % 3600 == 0:
        return '%d 小时' % (seconds // 3600)
    if seconds >= 3600:
        return '%.1f 小时' % (seconds / 3600)
    if seconds % 60 == 0:
        return '%d 分钟' % (seconds // 60)
    return '%d 秒' % seconds


def _xueqiu_state(status):
    """
    雪球行情源状态：退避中 > 未配置 Token > 正常。

    除了 `ok` 还给出 `tone`（`ok` / `bad`）——**颜色语义由这里判定**，
    模板与 JS 只负责渲染：正常绿、异常红，避免"谁都能顺手解读一次状态"导致显示不一致。
    """
    backoff = int(status.get('xueqiu_backoff_remaining') or 0)
    if backoff > 0:
        return {
            'ok': False,
            'tone': 'bad',
            'text': '限流退避中',
            'reason': status.get('xueqiu_backoff_reason') or '',
        }

    try:
        from config import XueqiuToken

        if not (getattr(XueqiuToken, 'TOKEN', '') or '').strip():
            return {'ok': False, 'tone': 'bad', 'text': '未配置 Token',
                    'reason': '缺少 XUEQIU_TOKEN'}
    except Exception:  # pragma: no cover - 配置异常不应让页面挂掉
        return {'ok': False, 'tone': 'bad', 'text': '状态未知', 'reason': '读取配置失败'}

    return {'ok': True, 'tone': 'ok', 'text': '正常', 'reason': ''}


def build_system_status(monitor):
    """
    聚合成页面可直接渲染的系统状态。

    :param monitor: StockMonitor 实例（可为 None，例如监控被禁用）
    :return: dict；任何异常都降级为占位状态，不让页面 500
    """
    try:
        status = monitor.get_status() if monitor is not None else {}
    except Exception:  # pragma: no cover - 监控状态异常不应连累页面
        status = {}

    running = bool(status.get('running'))
    session_key = status.get('session') or describe_session()
    if session_key == 'closed' and not is_trading_day():
        session_text = '非交易日'
    else:
        session_text = SESSION_LABELS.get(session_key, '—')

    cooldown_seconds = status.get('cooldown_seconds')
    try:
        cooldown_seconds = int(cooldown_seconds or 0)
    except (TypeError, ValueError):
        cooldown_seconds = 0

    return {
        # 监控停止 = 异常（本该在跑），tone 决定颜色：ok 绿 / bad 红
        'monitor': {'running': running, 'tone': 'ok' if running else 'bad',
                    'text': '运行中' if running else '已停止'},
        'session': {'key': session_key, 'text': session_text},
        'cooldown': {'seconds': cooldown_seconds, 'text': format_duration(cooldown_seconds)},
        'xueqiu': _xueqiu_state(status),
        'updated_at': time.strftime('%H:%M:%S'),
    }
