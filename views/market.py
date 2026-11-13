# -*- coding: utf-8 -*-
"""
市场成交额视图（009 市场成交额）。

路由（蓝图 `market`，挂载前缀 `/stock/market`）：

- `GET  /stock/market/`             市场成交额页（**只读库**，加载/切换区间不打外部接口）
- `GET  /stock/market/api/turnover` 页面数据（全部历史 + 统计，供走势图）
- `POST /stock/market/api/sync`     手动同步（库非空增量 / 库空全量，东财主源失败自动切腾讯备源，
                                    冷却 TURNOVER_SYNC_COOLDOWN 秒）

视图保持薄：校验 → 模型 → 渲染或 JSON；取数与口径在 `utils/turnover_source.py`，
入库与统计在 `models/market_turnover.py`。
"""
import logging
import time

from flask import Blueprint, jsonify, render_template

from config import Config
from models.market_turnover import MarketDailyTurnover
from utils.decorators import login_required

logger = logging.getLogger(__name__)

market_bp = Blueprint('market', __name__)

# 同步冷却起点（进程内存，与告警冷却同类；项目强制单进程部署，见 ADR-006）
_last_sync_at = 0.0


@market_bp.route('/')
@login_required
def page():
    """市场成交额页：看板数据由前端经 /api/turnover 拉取（只读库）；这里只判空态。"""
    dashboard = MarketDailyTurnover.build_dashboard()
    return render_template('market_turnover.html', dashboard=dashboard)


@market_bp.route('/api/turnover')
@login_required
def api_turnover():
    """走势图数据：与 example data.json 同构；表为空时返回 empty 标记（不渲染假数据）。"""
    dashboard = MarketDailyTurnover.build_dashboard()
    return jsonify(dashboard or {'empty': True})


@market_bp.route('/api/sync', methods=['POST'])
@login_required
def api_sync():
    """
    手动同步（auto：东财优先失败切腾讯；库非空增量、库空全量，全量备源带 60 日写入保护）。

    冷却期内直接拒绝（429），防止重复点击打爆外部数据源；
    冷却起点在调用前置位——失败也计入冷却，避免失败重试风暴。
    """
    global _last_sync_at
    now = time.monotonic()
    wait = Config.TURNOVER_SYNC_COOLDOWN - (now - _last_sync_at)
    if _last_sync_at and wait > 0:
        return jsonify({'ok': False, 'error': '同步过于频繁，请 %d 秒后再试' % (int(wait) + 1)}), 429

    _last_sync_at = now
    try:
        summary = MarketDailyTurnover.sync_from_source('auto')
    except Exception:
        logger.exception('市场成交额同步失败')
        return jsonify({'ok': False, 'error': '同步失败：数据源不可用或数据校验未通过，详见日志'}), 502
    return jsonify({'ok': True, **summary})