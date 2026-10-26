"""
AI 个股分析视图（007 AI 个股分析）。

路由（蓝图 `ai`，挂载前缀 `/stock/ai`）：

- `GET  /stock/ai/`           报告工作台：顶部搜索定标的 + 标的条 / 报告 / 参数 + 快照 + 历史
- `GET  /stock/ai/api/search` 标的搜索（名称 / 代码，服务端真查库），供顶部搜索框下拉
- `POST /stock/ai/analyze`    生成一次分析（写库留痕）
- `POST /stock/ai/ask`        基于最近一次分析追问（也留痕，verdict=问答）
- `POST /stock/ai/config`     保存非凭据参数（温度 / 上限 / 引用范围 / 开关）
- `POST /stock/ai/test`       连通测试（真实请求，会消耗少量 Token）

视图保持薄：校验 → 模型/客户端 → 渲染或重定向；提示词组装与解析在 `utils/ai_prompt.py`。
"""
import datetime
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from models.stock_ai import (
    DATA_SCOPES,
    DIMENSIONS,
    DIMENSION_DESCS,
    VERDICT_QA,
    StockAiConfig,
    StockAiReport,
    parse_dimensions,
)
from models.stock_indicator import StockIndicator
from models.stock_kline import StockKline
from models.stock_master import StockMaster
from models.stock_warehouse import StockWarehouse
from utils import ai_client
from utils.ai_prompt import (
    PROMPT_VERSION,
    build_context,
    build_followup_messages,
    build_messages,
    parse_report,
)
from utils.decorators import login_required

logger = logging.getLogger(__name__)

ai_bp = Blueprint('ai', __name__)

# 追问长度上限：既防误贴超长文本刷 Token，也避免把表单塞爆
QUESTION_MAX_LENGTH = 300
# 报告页保留的历史条数
HISTORY_LIMIT = 8
# 顶部搜索下拉一次最多给几条（服务端真查库，不是前端过滤已渲染行）
SEARCH_LIMIT = 12
# 搜索关键字长度上限：再长也匹配不到有意义的标的，截断防刷
SEARCH_MAX_LENGTH = 32
# 「最近分析」快捷入口条数（跨标的，只在未选标的时展示）
RECENT_LIMIT = 5

# 能力卡片图标：与 DIMENSIONS 一一对应，图标走 theme.js 注入的内联 sprite
DIM_ICONS = {
    'valuation': 'i-scale',
    'technical': 'i-candles',
    'relative': 'i-compare',
    'position': 'i-target',
    'risk': 'i-shield',
}


def _month_start(today=None):
    """本月第一天（含 00:00:00），用于月度调用计数。"""
    today = today or datetime.date.today()
    return datetime.datetime.combine(today.replace(day=1), datetime.time.min)


def _usage(limit):
    """
    本月调用情况。

    :return: dict(used, limit, remaining, unlimited)；计数查询失败时 used=None（不误拦）
    """
    used = StockAiReport.count_since(_month_start())
    if used is None:
        return {'used': None, 'limit': limit, 'remaining': None, 'unlimited': limit <= 0}
    return {
        'used': used,
        'limit': limit,
        'remaining': max(0, limit - used) if limit > 0 else None,
        'unlimited': limit <= 0,
    }


def _limit_reached(usage):
    """是否已达月度上限（limit<=0 视为不限）。"""
    if usage['unlimited'] or usage['used'] is None:
        return False
    return usage['used'] >= usage['limit']


def _load_context(stock_id, scope=None):
    """
    取该标的的输入数据（全部来自已有表，不抓外部数据）。

    :param scope: 「引用数据范围」白名单，不在范围内的字段由 `build_context` 置空
    :return: (stock, context)；stock 不存在时返回 (None, None)
    """
    stock = StockMaster.get_by_id(stock_id)
    if not stock:
        return None, None

    warehouse = StockWarehouse.get_by_stock_master_id(stock_id)
    indicator = StockIndicator.get_latest(stock_id)
    closes = StockKline.get_recent_closes(stock_id, limit=25)
    return stock, build_context(stock, warehouse, indicator, closes, scope=scope)


def _page_url(stock_id=None):
    """回跳本页：有标的就带上，避免保存参数后丢失上下文。"""
    if stock_id:
        return url_for('ai.page', stock_id=stock_id)
    return url_for('ai.page')


def _snapshot_map(stocks):
    """{stock_id: 最新指标快照}：一次 IN 查询喂搜索下拉的价格位，避免逐标 N+1。"""
    ids = [stock['id'] for stock in stocks]
    if not ids:
        return {}
    try:
        return StockIndicator.get_latest_batch(ids) or {}
    except Exception:
        logger.exception('加载指标快照失败，价格位按「—」渲染')
        return {}


def _price_map(stock_ids):
    """
    {stock_id: 现价}：一次批量取，避免搜索下拉逐标查询。

    现价以 `stock_warehouse.current_price` 为准（与订单列表 / 编辑页一致），
    该列缺失时回退指标快照里的 `price`；两个都没有才是真的没有（页面渲染「—」）。
    """
    if not stock_ids:
        return {}
    prices = {}
    try:
        for row in StockMaster.get_quotes_by_ids(stock_ids) or []:
            if row.get('current_price') is not None:
                prices[row['id']] = float(row['current_price'])
    except Exception:
        logger.exception('批量取现价失败')
    return prices


def _search_items(rows, snapshots, prices):
    """把标的行序列化成搜索下拉要的字段（价格缺失给 None，由前端渲染「—」）。"""
    items = []
    for row in rows:
        sid = row.get('id')
        price = prices.get(sid)
        if price is None:
            price = (snapshots.get(sid) or {}).get('price')
        items.append({
            'id': sid,
            'name': row.get('stock_name') or '',
            'code': row.get('stock_code') or '',
            'price': float(price) if price is not None else None,
            # 跳转地址由服务端生成，前端不自己拼 URL
            'url': url_for('ai.page', stock_id=sid),
        })
    return items


def _current_price(stock_id, snapshot):
    """
    该标的的现价：warehouse 优先，指标快照兜底，都没有返回 None（页面渲染「—」）。
    """
    try:
        warehouse = StockWarehouse.get_by_stock_master_id(stock_id)
    except Exception:
        logger.exception('读取现价失败 stock_id=%s', stock_id)
        warehouse = None
    value = getattr(warehouse, 'current_price', None)
    if value is None:
        value = (snapshot or {}).get('price')
    return float(value) if value is not None else None


def _stock_total():
    """标的总数，用于区分「还没有任何标的」；查询失败返回 None（不误报空）。"""
    try:
        _, total = StockMaster.get_all(page=1, per_page=1)
    except Exception:
        logger.exception('统计标的数量失败')
        return None
    return int(total or 0)


def _kline_signal(stock_id):
    """K 线信号：返回 (文案, 语义色)。取不到按「震荡」处理，不编造。"""
    try:
        signal = StockKline.get_latest_signal(stock_id)
    except Exception:
        logger.exception('读取 K 线信号失败 stock_id=%s', stock_id)
        return '震荡', 'flat'
    return {'golden_cross': ('金叉', 'up'), 'death_cross': ('死叉', 'down')}.get(
        signal, ('震荡', 'flat'))


def _effective_model(config):
    """
    实际会发出去的模型：参数面板里保存的那个，不在候选清单内就回退到默认模型。

    回退是必要的——`AI_MODEL` 曾经允许填「a,b,c」整串并存进库里，
    把这种串发给网关必然失败（见 changes/2026-10-22-ai-model-list.md）。

    :return: (model, stale)；stale=True 表示保存的值已失效、被回退了
    """
    fallback = ai_client.default_model()
    saved = (config.get('model') or '').strip()
    if saved and ai_client.is_allowed_model(saved):
        return saved, False
    return fallback, bool(saved) and saved != fallback


def _selection(config):
    """
    解析本次调用用哪个模型、哪些维度：表单优先，缺省回退参数面板里保存的默认值。

    :return: (model, dimension_keys, error)；error 非空表示不能发起调用
    """
    default_model, _ = _effective_model(config)
    model = (request.form.get('model') or '').strip() or default_model
    # 表单里塞了清单外的模型（伪造参数 / 页面过期）→ 拒绝。
    # 注意：**只有库里保存的旧值才回退**（见 _effective_model），表单提交要显式报错，
    # 否则用户改了环境变量却不知道自己提交的是什么模型。
    if not ai_client.is_allowed_model(model):
        return None, None, '模型不可用：请检查环境变量 AI_MODEL / AI_MODELS'

    default_dims = config.get('dimension_keys') or list(DIMENSIONS)
    raw = request.form.getlist('dimensions')
    dim_keys = parse_dimensions(raw, default=default_dims) if raw else default_dims
    return model, dim_keys, ''


@ai_bp.route('/')
@login_required
def page():
    """
    AI 分析工作台：顶部搜索定标的 → 标的条 / 报告 / 参数 + 快照 + 历史。

    页面**不加载全量标的列表**：标的由 `?stock_id=`（订单列表行内「AI 分析」按钮直达）
    或顶部搜索框（走 `/stock/ai/api/search`）确定。
    """
    config = StockAiConfig.effective()
    ai_info = ai_client.describe_settings()
    usage = _usage(config['monthly_limit'])

    # ?stock_id= 是唯一入口；取不到就进"未选标的"空态，不再默认选中第一只
    raw_stock_id = request.args.get('stock_id', type=int)
    stock = None
    if raw_stock_id:
        try:
            stock = StockMaster.get_by_id(raw_stock_id)
        except Exception:
            logger.exception('加载 AI 页标的失败 stock_id=%s', raw_stock_id)
            flash('加载标的失败，请稍后重试。', 'error')
            stock = None
    stock_id = stock['id'] if stock else None

    reports = []
    latest = None
    snapshot = None
    price = None
    signal_text, signal_tone = '—', 'flat'
    if stock_id:
        reports = StockAiReport.list_by_stock(stock_id, limit=HISTORY_LIMIT)
        latest = reports[0] if reports else None
        try:
            snapshot = StockIndicator.get_latest(stock_id)
        except Exception:
            logger.exception('加载指标快照失败 stock_id=%s', stock_id)
            snapshot = None
        signal_text, signal_tone = _kline_signal(stock_id)
        price = _current_price(stock_id, snapshot)
        # 刚从分析/追问跳回来时定位到那一条（校验归属，避免串标的）
        report_id = request.args.get('report_id', type=int)
        if report_id and latest and report_id != latest.get('id'):
            picked = StockAiReport.get_by_id(report_id)
            if picked and picked.get('stock_master_id') == stock_id:
                latest = picked

    # 未启用 / 未配置的原因由客户端给出：页面只展示，不自己拼一套判断
    ready, ready_reason = ai_client.is_ready()
    if ready and not config['enabled']:
        ready, ready_reason = False, 'AI 分析已在参数里关闭（stock_ai_config.enabled=0）'

    dim_cards = [{'key': key, 'label': DIMENSIONS[key],
                  'desc': DIMENSION_DESCS.get(key, ''),
                  'icon': DIM_ICONS.get(key, 'i-sparkles')}
                 for key in DIMENSIONS]

    # 页面显示"实际会发出去的那个模型"：库里没存 → 默认；存了但已不在候选清单 → 已回退
    model, model_stale = _effective_model(config)
    if model_stale:
        model_badge = '已回退'
    elif model and model == ai_client.default_model():
        model_badge = '默认'
    else:
        model_badge = ''

    return render_template(
        'ai_analysis.html',
        stock=stock,
        stock_id=stock_id,
        stock_total=_stock_total(),
        reports=reports,
        recent=[] if stock_id else StockAiReport.list_recent(limit=RECENT_LIMIT),
        latest=latest,
        snapshot=snapshot,
        price=price,
        signal_text=signal_text,
        signal_tone=signal_tone,
        config=config,
        ai_info=ai_info,
        model=model,
        model_badge=model_badge,
        model_stale=model_stale,
        models=ai_client.available_models(),
        dims=DIMENSIONS,
        dim_cards=dim_cards,
        usage=usage,
        ready=ready,
        ready_reason=ready_reason,
        scopes=DATA_SCOPES,
        prompt_version=PROMPT_VERSION,
        qa_verdict=VERDICT_QA,
        question_max=QUESTION_MAX_LENGTH,
        search_min=1,
    )


@ai_bp.route('/api/search')
@login_required
def search():
    """
    标的搜索（顶部搜索框下拉用）：按名称或代码**服务端真查库**。

    `q` 为空直接返回空列表——绝不退化成"返回全部"，否则又变回铺全量名单。
    """
    keyword = (request.args.get('q') or '').strip()
    if not keyword:
        return jsonify({'items': [], 'total': 0, 'truncated': False})
    keyword = keyword[:SEARCH_MAX_LENGTH]

    try:
        rows, total = StockMaster.get_all(page=1, per_page=SEARCH_LIMIT,
                                          search_query=keyword)
    except Exception:
        logger.exception('搜索标的失败 keyword=%s', keyword)
        return jsonify({'items': [], 'total': 0, 'truncated': False,
                        'error': '搜索失败，请稍后重试'}), 500

    rows = rows or []
    total = int(total or 0)
    return jsonify({
        'items': _search_items(rows, _snapshot_map(rows), _price_map([r['id'] for r in rows])),
        'total': total,
        'truncated': total > len(rows),
    })


@ai_bp.route('/analyze', methods=['POST'])
@login_required
def analyze():
    """生成一次分析并落库。失败一律回页面提示，不向浏览器抛异常。"""
    stock_id = request.form.get('stock_id', type=int)
    if not stock_id:
        flash('请先选择标的', 'error')
        return redirect(url_for('ai.page'))

    config = StockAiConfig.effective()
    ready, reason = ai_client.is_ready()
    if not ready:
        flash(reason, 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))
    if not config['enabled']:
        flash('AI 分析已在参数里关闭，请先在下方开启。', 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))

    usage = _usage(config['monthly_limit'])
    if _limit_reached(usage):
        flash(f"本月调用已达上限（{usage['limit']} 次），请调整月度上限或下月再试。", 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))

    model, dim_keys, selection_error = _selection(config)
    if selection_error:
        flash(selection_error, 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))
    dim_labels = [DIMENSIONS[key] for key in dim_keys]

    stock, context = _load_context(stock_id, config['scope'])
    if not stock:
        flash('标的不存在或已被删除', 'error')
        return redirect(url_for('ai.page'))

    result = ai_client.call_ai(
        build_messages(context, dim_labels),
        temperature=config['temperature'],
        max_tokens=config['max_tokens'],
        model=model,
    )
    if not result['ok']:
        flash(f"分析失败：{result['error']}", 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))

    report = parse_report(result['text'])
    content = {
        'summary': report['summary'],
        'points': report['points'],
        'supports': report['supports'],
        'risks': report['risks'],
        'disclaimer': report['disclaimer'],
        'raw': report['raw'],
        'parsed': report['parsed'],
        'context': context,
        'scope': config['scope'],
        'dimensions': dim_labels,
        'dimension_keys': dim_keys,
    }
    new_id = StockAiReport.create(
        stock_master_id=stock_id,
        model=result['model'],
        prompt_version=PROMPT_VERSION,
        verdict=report['verdict'],
        confidence=report['confidence'],
        content=content,
        tokens_used=result['tokens'],
    )
    if new_id is None:
        flash('分析已完成但保存失败，请稍后重试。', 'error')
    elif not report['parsed']:
        flash('分析已保存，但模型未按约定格式返回，已按纯文本摘要展示。', 'warning')
    else:
        flash(f"分析完成：{report['verdict']}"
              f"（置信度 {int(report['confidence']) if report['confidence'] is not None else '—'}），"
              f"模型 {result['model']}，消耗 {result['tokens']} tokens。", 'success')
    return redirect(url_for('ai.page', stock_id=stock_id, report_id=new_id or ''))


@ai_bp.route('/ask', methods=['POST'])
@login_required
def ask():
    """基于最近一次正式分析追问；问答同样留痕，便于复盘。"""
    stock_id = request.form.get('stock_id', type=int)
    question = (request.form.get('question') or '').strip()
    if not stock_id:
        flash('请先选择标的', 'error')
        return redirect(url_for('ai.page'))
    if not question:
        flash('追问内容不能为空', 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))
    if len(question) > QUESTION_MAX_LENGTH:
        flash(f'追问内容过长（上限 {QUESTION_MAX_LENGTH} 字）', 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))

    config = StockAiConfig.effective()
    ready, reason = ai_client.is_ready()
    if not ready:
        flash(reason, 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))
    if not config['enabled']:
        flash('AI 分析已在参数里关闭，请先在下方开启。', 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))

    previous = StockAiReport.latest_analysis(stock_id)
    if not previous:
        flash('请先生成一次分析，再进行追问', 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))

    usage = _usage(config['monthly_limit'])
    if _limit_reached(usage):
        flash(f"本月调用已达上限（{usage['limit']} 次），请调整月度上限或下月再试。", 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))

    model, _, selection_error = _selection(config)
    if selection_error:
        flash(selection_error, 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))

    stock, context = _load_context(stock_id, config['scope'])
    if not stock:
        flash('标的不存在或已被删除', 'error')
        return redirect(url_for('ai.page'))

    result = ai_client.call_ai(
        build_followup_messages(context, question, previous.get('content')),
        temperature=config['temperature'],
        max_tokens=config['max_tokens'],
        model=model,
    )
    if not result['ok']:
        flash(f"追问失败：{result['error']}", 'error')
        return redirect(url_for('ai.page', stock_id=stock_id))

    new_id = StockAiReport.create(
        stock_master_id=stock_id,
        model=result['model'],
        prompt_version=PROMPT_VERSION,
        verdict=VERDICT_QA,
        confidence=None,
        content={'question': question, 'answer': result['text'], 'parsed': True},
        tokens_used=result['tokens'],
    )
    if new_id is None:
        flash('追问已得到回答，但保存失败，请重试。', 'error')
    else:
        flash(f"追问完成，消耗 {result['tokens']} tokens。", 'success')
    return redirect(url_for('ai.page', stock_id=stock_id, report_id=new_id or ''))


def _parse_config_form():
    """
    解析参数表单。

    :return: (payload, errors)；非法值不落库
    """
    payload, errors = {}, []

    payload['enabled'] = 1 if request.form.get('enabled') else 0

    raw_temp = (request.form.get('temperature') or '').strip()
    if raw_temp == '':
        payload['temperature'] = None
    else:
        try:
            temperature = float(raw_temp)
        except ValueError:
            errors.append('温度必须是数字')
        else:
            if not 0 <= temperature <= 2:
                errors.append('温度需在 0 ~ 2 之间')
            else:
                payload['temperature'] = temperature

    for field, label, low, high in (
        ('max_tokens', '单次最大 Token', 100, 32000),
        ('monthly_limit', '月度调用上限', 0, 100000),
    ):
        raw = (request.form.get(field) or '').strip()
        if raw == '':
            payload[field] = None
            continue
        try:
            value = int(raw)
        except ValueError:
            errors.append(f'{label}必须是整数')
            continue
        if value < low or value > high:
            errors.append(f'{label}需在 {low} ~ {high} 之间')
            continue
        payload[field] = value

    scopes = [key for key in request.form.getlist('data_scope') if key in DATA_SCOPES]
    if not scopes:
        errors.append('至少选择一项引用数据范围')
    else:
        payload['data_scope'] = ','.join(scopes)

    # 模型：只能从候选清单里选（清单来自 AI_MODELS + AI_MODEL），留空表示跟随环境变量
    model = (request.form.get('model') or '').strip()
    if model and not ai_client.is_allowed_model(model):
        errors.append('所选模型不在可选清单内')
    else:
        payload['model'] = model or None

    dim_keys = [key for key in request.form.getlist('dimensions') if key in DIMENSIONS]
    if not dim_keys:
        errors.append('至少选择一个分析维度')
    else:
        payload['dimensions'] = ','.join(dim_keys)

    return payload, errors


@ai_bp.route('/config', methods=['POST'])
@login_required
def save_config():
    """保存非凭据参数。密钥不在此处、也不在数据库里。"""
    payload, errors = _parse_config_form()
    if errors:
        flash('参数未保存：' + '；'.join(errors), 'error')
    elif StockAiConfig.upsert(**payload):
        flash('AI 参数已保存', 'success')
    else:
        flash('AI 参数保存失败，请稍后重试。', 'error')
    return redirect(_page_url(request.form.get('stock_id', type=int)))


@ai_bp.route('/test', methods=['POST'])
@login_required
def test():
    """
    连通测试（Composer 里与「密钥」同一处）：发一次真实请求，页面已提示会消耗少量 Token。

    三个可选参数：
    - `api_key`：本次录入的密钥，写入**进程内存**后立即用于测试（不落库、不回显、不写日志）；
    - `model`：测试哪个模型（Composer 下拉选的那个），必须在候选清单内；
    - `clear_key`：清掉运行时密钥，恢复使用环境变量 `AI_API_KEY`。
    """
    page_url = _page_url(request.form.get('stock_id', type=int))

    if request.form.get('clear_key'):
        ai_client.clear_runtime_key()
        flash('已清除本次运行录入的密钥，恢复使用环境变量 AI_API_KEY。', 'success')
        return redirect(page_url)

    key = (request.form.get('api_key') or '').strip()
    if key:
        ai_client.set_runtime_key(key)
        logger.info('已录入运行时 AI 密钥（不落库，仅本进程有效，脱敏=%s）',
                    ai_client.mask_key(key))

    model = (request.form.get('model') or '').strip()
    if model and not ai_client.is_allowed_model(model):
        flash('连通测试未执行：所选模型不在可选清单内', 'error')
        return redirect(page_url)

    result = ai_client.test_connection(model=model or None)
    prefix = '已保存密钥到本次运行（重启后失效）。' if key else ''
    if result['ok']:
        flash(f"{prefix}连通正常：模型 {result['model']}，{result['latency_ms']} ms，"
              f"消耗 {result['tokens']} tokens。", 'success')
    else:
        flash(f"{prefix}连通失败（{result['status']}）：{result['error']}", 'error')
    return redirect(page_url)
