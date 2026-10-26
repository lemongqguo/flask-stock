"""
订单相关视图
"""
import logging
import math
import threading
import time

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from config import Config
from models.account_settings import resolve_bench_code
from models.stock_alarm import StockAlarm
from models.stock_indicator import StockIndicator, StockIndicatorConfig
from models.stock_kline import StockKline
from models.stock_master import StockMaster
from models.stock_pb import StockPb
from models.stock_pe import StockPe
from models.stock_warehouse import StockWarehouse
from utils.decorators import login_required
from utils.indicator_rules import (
    DEFAULT_THRESHOLDS,
    SUBTYPES,
    is_combo_hit,
)

logger = logging.getLogger(__name__)

# 创建订单蓝图
stock_bp = Blueprint('stock', __name__)

@stock_bp.route('/')
@login_required
def index():
    """
    订单主页，重定向到订单列表
    """
    return redirect(url_for('stock.stock_list'))

@stock_bp.route('/list', methods=['GET'])
@login_required
def stock_list():
    """
    订单列表页面（带分页功能）
    """
    # 获取分页参数
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search_query = request.args.get('search', '', type=str)
    
    # 验证每页显示数量的有效性
    valid_per_page_options = [5, 10, 20, 50]
    if per_page not in valid_per_page_options:
        per_page = 10
    
    # 获取订单数据
    stocks, total_count = StockMaster.get_all_with_details(
        page=page, 
        per_page=per_page, 
        search_query=search_query
    )

    # 52周最低价：一次批量取回本页订单，避免逐行查库
    lows_52w = StockKline.get_low_52w_batch([stock['id'] for stock in stocks])

    # 为每个股票添加K线信号信息
    for stock in stocks:
        signal_type = StockKline.get_latest_signal(stock['id'])
        stock['kline_signal'] = signal_type
        stock['low_52w'] = lows_52w.get(stock['id'])
    
    # 计算总页数
    total_pages = math.ceil(total_count / per_page) if per_page else 0

    # 获取订单统计信息
    from models.stock_monitor import monitor  # 导入监控实例
    stats = {
        'total': total_count,
        'active': StockMaster.count_by_status('active'),
        'inactive': StockMaster.count_by_status('inactive'),
        'alarm_active': StockMaster.count_alarm_active(),
        'thread_count': threading.active_count(),  # 获取当前活跃线程数
        'monitor_running': monitor.is_running  # 获取监控是否运行的状态
    }
    
    return render_template(
        'stock_order_list.html', 
        stocks=stocks, 
        search_query=search_query,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_count=total_count,
        stats=stats
    )

@stock_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_stock():
    """
    创建订单页面
    """
    if request.method == 'POST':
        # 获取表单数据
        stock_name = request.form['stock_name']
        stock_code = request.form['stock_code']
        target_pettm = request.form.get('target_pettm', type=float)
        target_pb = request.form.get('target_pb', type=float)
        
        # 验证必要字段
        if not stock_name or not stock_code:
            flash('订单名称和订单代码为必填项。', 'error')
            return render_template('stock_order_form.html', form_action='create')
        
        # 检查订单代码是否已存在
        existing_stock = StockMaster.get_by_stock_code(stock_code)
        if existing_stock:
            flash('订单代码已存在，请使用其他订单代码。', 'error')
            return render_template('stock_order_form.html', form_action='create')
        
        # 创建主订单记录
        new_stock = StockMaster.create(
            stock_name=stock_name,
            stock_code=stock_code,
            target_pettm=target_pettm,
            target_pb=target_pb
        )
        
        if new_stock:
            # 获取刚刚创建的订单ID
            stock_id = new_stock.id
            
            # 创建关联的仓库记录（如果提供了相关数据）
            dividend_yield = request.form.get('dividend_yield', type=float)
            sell_rate = request.form.get('sell_rate', type=float)
            stock_valueone = request.form.get('stock_valueone', type=float)
            stock_valuetwo = request.form.get('stock_valuetwo', type=float)
            stock_valuethree = request.form.get('stock_valuethree', type=float)
            memo = request.form.get('memo', '')
            
            if dividend_yield or sell_rate or stock_valueone or stock_valuetwo or stock_valuethree or memo:
                StockWarehouse.create(
                    stock_master_id=stock_id,
                    dividend_yield=dividend_yield,
                    sell_rate=sell_rate,
                    stock_valueone=stock_valueone,
                    stock_valuetwo=stock_valuetwo,
                    stock_valuethree=stock_valuethree,
                    memo=memo
                )
            
            # 创建PE记录（如果提供了相关数据）
            pe_valueone = request.form.get('pe_valueone', type=float)
            pe_valuetwo = request.form.get('pe_valuetwo', type=float)
            pe_valuethree = request.form.get('pe_valuethree', type=float)
            pe_memo = request.form.get('pe_memo', '')
            
            if pe_valueone or pe_valuetwo or pe_valuethree or pe_memo:
                StockPe.create(
                    stock_master_id=stock_id,
                    pe_valueone=pe_valueone,
                    pe_valuetwo=pe_valuetwo,
                    pe_valuethree=pe_valuethree,
                    memo=pe_memo
                )
            
            # 创建PB记录（如果提供了相关数据）
            pb_valueone = request.form.get('pb_valueone', type=float)
            pb_valuetwo = request.form.get('pb_valuetwo', type=float)
            pb_valuethree = request.form.get('pb_valuethree', type=float)
            pb_memo = request.form.get('pb_memo', '')
            
            if pb_valueone or pb_valuetwo or pb_valuethree or pb_memo:
                StockPb.create(
                    stock_master_id=stock_id,
                    pb_valueone=pb_valueone,
                    pb_valuetwo=pb_valuetwo,
                    pb_valuethree=pb_valuethree,
                    memo=pb_memo
                )
            
            flash('订单创建成功！', 'success')
            return redirect(url_for('stock.stock_list'))
        else:
            flash('订单创建失败，请重试。', 'error')
    
    return render_template('stock_order_form.html', form_action='create')

def _form_context(stock):
    """
    订单表单所需的完整上下文（stock + warehouse + pe + pb）。

    校验失败时也必须带全：模板里 pe_memo / pb_memo 是隐藏字段回传原值，
    缺了 pe_record / pb_record 会渲染成空串，用户改完再提交就把已有备注清空。
    """
    stock_id = stock.get('id') if isinstance(stock, dict) else None
    return {
        'stock': stock,
        'warehouse': StockWarehouse.get_by_stock_master_id(stock_id) if stock_id else None,
        'pe_record': StockPe.get_by_stock_master_id(stock_id) if stock_id else None,
        'pb_record': StockPb.get_by_stock_master_id(stock_id) if stock_id else None,
    }


@stock_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_stock(id):
    """
    编辑订单页面
    """
    stock = StockMaster.get_by_id(id)
    if not stock:
        flash('订单不存在。', 'error')
        return redirect(url_for('stock.stock_list'))
    
    if request.method == 'POST':
        # 获取表单数据
        stock_name = request.form['stock_name']
        stock_code = request.form['stock_code']
        target_pettm = request.form.get('target_pettm', type=float)
        target_pb = request.form.get('target_pb', type=float)
        status = request.form.get('status', 'active')
        
        # 验证必要字段
        if not stock_name or not stock_code:
            flash('订单名称和订单代码为必填项。', 'error')
            return render_template('stock_order_form.html', form_action='edit', **_form_context(stock))
        
        # 检查订单代码是否与其他记录冲突
        existing_stock = StockMaster.get_by_stock_code(stock_code)
        if existing_stock and existing_stock.id != id:
            flash('订单代码已存在，请使用其他订单代码。', 'error')
            return render_template('stock_order_form.html', form_action='edit', **_form_context(stock))
        
        # 更新主订单记录
        update_success = StockMaster.update(
            id=id,
            stock_name=stock_name,
            stock_code=stock_code,
            target_pettm=target_pettm,
            target_pb=target_pb,
            status=status
        )
        
        if update_success:
            # 更新或创建仓库记录
            dividend_yield = request.form.get('dividend_yield', type=float)
            sell_rate = request.form.get('sell_rate', type=float)
            stock_valueone = request.form.get('stock_valueone', type=float)
            stock_valuetwo = request.form.get('stock_valuetwo', type=float)
            stock_valuethree = request.form.get('stock_valuethree', type=float)
            memo = request.form.get('memo', '')
            
            warehouse = StockWarehouse.get_by_stock_master_id(id)
            if warehouse:
                # 更新现有记录
                StockWarehouse.update_by_stock_master_id(
                    stock_master_id=id,
                    dividend_yield=dividend_yield,
                    sell_rate=sell_rate,
                    stock_valueone=stock_valueone,
                    stock_valuetwo=stock_valuetwo,
                    stock_valuethree=stock_valuethree,
                    memo=memo
                )
            else:
                # 创建新记录
                StockWarehouse.create(
                    stock_master_id=id,
                    dividend_yield=dividend_yield,
                    sell_rate=sell_rate,
                    stock_valueone=stock_valueone,
                    stock_valuetwo=stock_valuetwo,
                    stock_valuethree=stock_valuethree,
                    memo=memo
                )
            
            # 更新或创建PE记录
            pe_valueone = request.form.get('pe_valueone', type=float)
            pe_valuetwo = request.form.get('pe_valuetwo', type=float)
            pe_valuethree = request.form.get('pe_valuethree', type=float)
            pe_memo = request.form.get('pe_memo', '')
            
            pe_record = StockPe.get_by_stock_master_id(id)
            if pe_record:
                # 更新现有记录
                StockPe.update_by_stock_master_id(
                    stock_master_id=id,
                    pe_valueone=pe_valueone,
                    pe_valuetwo=pe_valuetwo,
                    pe_valuethree=pe_valuethree,
                    memo=pe_memo
                )
            else:
                # 创建新记录
                StockPe.create(
                    stock_master_id=id,
                    pe_valueone=pe_valueone,
                    pe_valuetwo=pe_valuetwo,
                    pe_valuethree=pe_valuethree,
                    memo=pe_memo
                )
            
            # 更新或创建PB记录
            pb_valueone = request.form.get('pb_valueone', type=float)
            pb_valuetwo = request.form.get('pb_valuetwo', type=float)
            pb_valuethree = request.form.get('pb_valuethree', type=float)
            pb_memo = request.form.get('pb_memo', '')
            
            pb_record = StockPb.get_by_stock_master_id(id)
            if pb_record:
                # 更新现有记录
                StockPb.update_by_stock_master_id(
                    stock_master_id=id,
                    pb_valueone=pb_valueone,
                    pb_valuetwo=pb_valuetwo,
                    pb_valuethree=pb_valuethree,
                    memo=pb_memo
                )
            else:
                # 创建新记录
                StockPb.create(
                    stock_master_id=id,
                    pb_valueone=pb_valueone,
                    pb_valuetwo=pb_valuetwo,
                    pb_valuethree=pb_valuethree,
                    memo=pb_memo
                )
            
            flash('订单更新成功！', 'success')
            return redirect(url_for('stock.stock_list'))
        else:
            flash('订单更新失败，请重试。', 'error')
            # 重新渲染表单页面，让用户重新尝试（同样要带全上下文，否则备注隐藏字段会变空）
            return render_template('stock_order_form.html', form_action='edit', **_form_context(stock))
    
    return render_template(
        'stock_order_form.html', 
        form_action='edit', 
        **_form_context(stock)
    )

@stock_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete_stock(id):
    """
    删除订单
    """
    stock = StockMaster.get_by_id(id)
    if not stock:
        flash('订单不存在。', 'error')
        return redirect(url_for('stock.stock_list'))
    
    # 删除主订单记录（由于设置了外键约束ON DELETE CASCADE，关联记录也会被自动删除）
    if StockMaster.delete(id):
        flash('订单删除成功！', 'success')
    else:
        flash('订单删除失败。', 'error')
    
    return redirect(url_for('stock.stock_list'))

def _safe_list_url():
    """
    跳转回订单列表，并尽量保留分页 / 搜索参数。

    next 只允许本站内的相对路径，杜绝开放重定向（拒绝 //host、://、反斜杠变体）。
    """
    nxt = (request.form.get('next') or '').strip()
    if nxt.startswith('/') and not nxt.startswith('//') and '\\' not in nxt and '://' not in nxt:
        return nxt
    return url_for('stock.stock_list')


@stock_bp.route('/toggle_status/<int:id>', methods=['POST'])
@login_required
def toggle_status(id):
    """
    切换订单的监控状态（active <-> inactive），供列表页内联开关使用。

    目标状态由服务端读取当前值后取反得出，不接受客户端传值，避免写入非法状态。
    """
    stock = StockMaster.get_by_id(id)
    if not stock:
        flash('订单不存在。', 'error')
        return redirect(_safe_list_url())

    # get_by_id 返回的是 dict 行（BaseModel.execute_query 结果），不是模型对象
    current_status = stock.get('status')
    new_status = 'inactive' if current_status == 'active' else 'active'
    try:
        updated = StockMaster.update(id, status=new_status)
    except Exception:
        logger.exception('切换订单状态失败: id=%s', id)
        updated = False

    if updated:
        logger.info('订单状态切换: id=%s, %s -> %s', id, current_status, new_status)
        flash('已切换为%s。' % ('监控中' if new_status == 'active' else '已暂停'), 'success')
    else:
        flash('状态切换失败，请稍后重试。', 'error')

    return redirect(_safe_list_url())


# 指标阈值表单：字段 -> (中文名, 下界, 上界)。顺序即表单顺序（长期在前、短期在后）
INDICATOR_THRESHOLD_FIELDS = (
    ('low52w_near_pct', '52 周新低阈值', 0.1, 100),
    ('drawdown_52w_pct', '52 周回撤阈值', 0.1, 100),
    ('rs20_pct', '20 日跑输阈值', 0.1, 100),
    ('rs5_ratio', '5 日倍数阈值', 0.1, 20),
    ('rs5_min_drop_pct', '个股最小跌幅', 0, 100),
    ('rs5_min_bench_drop_pct', '基准最小跌幅', 0, 100),
)


def _global_indicator_thresholds():
    """
    全局指标阈值：`config.IND_*`，缺失时用 `utils.indicator_rules.DEFAULT_THRESHOLDS` 兜底。

    做成函数而非常量：配置可能在测试里被替换，读一次性的常量会错过。
    """
    values = {}
    for key, _label, _low, _high in INDICATOR_THRESHOLD_FIELDS:
        values[key] = getattr(Config, 'IND_' + key.upper(), DEFAULT_THRESHOLDS[key])
    return values


def _parse_indicator_thresholds():
    """
    解析「指标告警」页签的表单。

    **留空 = 继承全局**（写 NULL），与 `stock_indicator_config` 的语义一致；
    越界或非法数值不落库，直接回错误提示。

    :return: (payload, errors)
    """
    payload, errors = {}, []
    for key, label, low, high in INDICATOR_THRESHOLD_FIELDS:
        raw = (request.form.get(key) or '').strip()
        if raw == '':
            payload[key] = None  # None → 数据库列写 NULL → 继承全局
            continue
        try:
            value = float(raw)
        except ValueError:
            errors.append(f'{label}必须是数字')
            continue
        if value < low or value > high:
            errors.append(f'{label}需在 {low} ~ {high} 之间')
            continue
        payload[key] = value
    return payload, errors


def _range_position(indicator):
    """
    现价在 52 周区间中的位置（0~100），供页面的区间条使用。

    :return: 数据缺失或区间退化（高 == 低）时返回 None，模板渲染成空条而不是 0%
    """
    try:
        low = float(indicator.get('low52w'))
        high = float(indicator.get('high52w'))
        price = float(indicator.get('price'))
    except (TypeError, ValueError):
        return None
    if high <= low:
        return None
    return max(0.0, min(100.0, (price - low) / (high - low) * 100))


@stock_bp.route('/indicator')
@login_required
def indicator_list():
    """
    指标监控总览（006）：每个标的最新一条快照 + **组合信号**结论。

    只读的最新快照，不触发任何行情请求；缺数据的标的显示为「未采集」而不是 0%，
    避免把「没数据」渲染成「健康」。

    页面只回答一个问题：**四项是否同时满足**（AND）。四条 flag 仍逐项落库（便于排查），
    但不再单独展示其命中角标——单条件命中率太高，展示出来会让用户误以为是告警依据。

    分页与订单列表同口径（`?page=` / `?per_page=`，默认每页 10 条）。
    KPI 里只有「监控标的」是全量（`get_all` 返回的 total），命中 / 未采集是**本页**口径。
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    if per_page not in (5, 10, 20, 50):
        per_page = 10

    try:
        stocks, total_count = StockMaster.get_all(page=page, per_page=per_page,
                                                 search_query=None)
    except Exception:
        logger.exception('加载指标监控列表失败')
        flash('加载订单列表失败，请稍后重试。', 'error')
        stocks, total_count = [], 0

    total_pages = math.ceil(total_count / per_page) if per_page else 0

    stock_ids = [stock['id'] for stock in stocks]
    latest_rows = StockIndicator.get_latest_batch(stock_ids)

    rows = []
    summary = {'total': total_count, 'collected': 0, 'combo_hits': 0,
               'latest_date': None}
    for stock in stocks:
        indicator = latest_rows.get(stock['id'])
        if not indicator:
            rows.append({'stock': stock, 'indicator': None, 'combo': False})
            continue

        flags = {sub: indicator.get(f'flag_{sub}') for sub in SUBTYPES}
        combo = is_combo_hit(flags)
        summary['collected'] += 1
        summary['combo_hits'] += 1 if combo else 0

        trade_date = indicator.get('trade_date')
        trade_date_text = trade_date.strftime('%Y-%m-%d') if hasattr(trade_date, 'strftime') \
            else str(trade_date or '')
        if trade_date_text and trade_date_text > (summary['latest_date'] or ''):
            summary['latest_date'] = trade_date_text

        rows.append({'stock': stock, 'indicator': indicator, 'combo': combo,
                     'trade_date_text': trade_date_text,
                     'range_pos': _range_position(indicator)})

    return render_template(
        'indicator_list.html',
        rows=rows,
        summary=summary,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_count=total_count,
        global_thresholds=_global_indicator_thresholds(),
        ind_enabled=getattr(Config, 'IND_ENABLED', True),
        # 与监控发信/采集同源：账户设置 > IND_BENCH > 沪深300
        bench_code=resolve_bench_code(),
        cooldown_hours=getattr(Config, 'IND_COOLDOWN_HOURS', 24),
    )


@stock_bp.route('/alarm_settings', methods=['GET', 'POST'])
@login_required
def alarm_settings():
    """
    告警设置页面
    """
    if request.method == 'POST':
        stock_id = request.form.get('stock_id', type=int)
        alarm_type = request.form.get('alarm_type')  # 'warehouse', 'pe', 'pb', 'indicator'
        
        if alarm_type == 'warehouse':
            dividend_yield = request.form.get('dividend_yield', type=float)
            sell_rate = request.form.get('sell_rate', type=float)
            stock_valueone = request.form.get('stock_valueone', type=float)
            stock_valuetwo = request.form.get('stock_valuetwo', type=float)
            stock_valuethree = request.form.get('stock_valuethree', type=float)
            memo = request.form.get('memo', '')
            
            # 检查是否存在仓库记录
            warehouse = StockWarehouse.get_by_stock_master_id(stock_id)
            if warehouse:
                # 更新现有记录
                StockWarehouse.update_by_stock_master_id(
                    stock_master_id=stock_id,
                    dividend_yield=dividend_yield,
                    sell_rate=sell_rate,
                    stock_valueone=stock_valueone,
                    stock_valuetwo=stock_valuetwo,
                    stock_valuethree=stock_valuethree,
                    memo=memo
                )
            else:
                # 创建新记录
                StockWarehouse.create(
                    stock_master_id=stock_id,
                    dividend_yield=dividend_yield,
                    sell_rate=sell_rate,
                    stock_valueone=stock_valueone,
                    stock_valuetwo=stock_valuetwo,
                    stock_valuethree=stock_valuethree,
                    memo=memo
                )
        elif alarm_type == 'pe':
            pe_valueone = request.form.get('pe_valueone', type=float)
            pe_valuetwo = request.form.get('pe_valuetwo', type=float)
            pe_valuethree = request.form.get('pe_valuethree', type=float)
            pe_memo = request.form.get('pe_memo', '')
            
            # 检查是否存在PE记录
            pe_record = StockPe.get_by_stock_master_id(stock_id)
            if pe_record:
                # 更新现有记录
                StockPe.update_by_stock_master_id(
                    stock_master_id=stock_id,
                    pe_valueone=pe_valueone,
                    pe_valuetwo=pe_valuetwo,
                    pe_valuethree=pe_valuethree,
                    memo=pe_memo
                )
            else:
                # 创建新记录
                StockPe.create(
                    stock_master_id=stock_id,
                    pe_valueone=pe_valueone,
                    pe_valuetwo=pe_valuetwo,
                    pe_valuethree=pe_valuethree,
                    memo=pe_memo
                )
        elif alarm_type == 'pb':
            pb_valueone = request.form.get('pb_valueone', type=float)
            pb_valuetwo = request.form.get('pb_valuetwo', type=float)
            pb_valuethree = request.form.get('pb_valuethree', type=float)
            pb_memo = request.form.get('pb_memo', '')
            
            # 检查是否存在PB记录
            pb_record = StockPb.get_by_stock_master_id(stock_id)
            if pb_record:
                # 更新现有记录
                StockPb.update_by_stock_master_id(
                    stock_master_id=stock_id,
                    pb_valueone=pb_valueone,
                    pb_valuetwo=pb_valuetwo,
                    pb_valuethree=pb_valuethree,
                    memo=pb_memo
                )
            else:
                # 创建新记录
                StockPb.create(
                    stock_master_id=stock_id,
                    pb_valueone=pb_valueone,
                    pb_valuetwo=pb_valuetwo,
                    pb_valuethree=pb_valuethree,
                    memo=pb_memo
                )
        elif alarm_type == 'indicator':
            # 指标阈值：留空 = 继承全局；非法值不落库，直接回 error 提示
            payload, errors = _parse_indicator_thresholds()
            if not stock_id:
                errors.insert(0, '缺少标的，无法保存指标阈值')
            if errors:
                flash('指标告警阈值未保存：' + '；'.join(errors), 'error')
            elif StockIndicatorConfig.upsert(stock_id, **payload):
                flash('指标告警阈值保存成功！留空项继承全局默认。', 'success')
            else:
                flash('指标告警阈值保存失败，请稍后重试。', 'error')
            # 回到「指标告警」页签本身，保存后不要跳回价格页签
            if stock_id:
                return redirect(url_for('stock.alarm_settings', stock_id=stock_id, tab='indicator'))
            return redirect(url_for('stock.alarm_settings', tab='indicator'))
        
        flash('告警设置保存成功！', 'success')
        # 如果有指定的股票ID，重定向回该股票的告警设置页面
        if stock_id:
            return redirect(url_for('stock.alarm_settings', stock_id=stock_id))
        else:
            return redirect(url_for('stock.alarm_settings'))
    
    # 检查是否指定了特定的股票ID
    stock_id = request.args.get('stock_id', type=int)
    
    if stock_id:
        # 获取指定的股票信息
        stock = StockMaster.get_by_id(stock_id)
        if stock:
            # 获取指定股票的关联设置
            warehouse = StockWarehouse.get_by_stock_master_id(stock_id)
            pe_record = StockPe.get_by_stock_master_id(stock_id)
            pb_record = StockPb.get_by_stock_master_id(stock_id)
            indicator_config = StockIndicatorConfig.get_by_stock_master_id(stock_id)
            
            stocks_with_settings = [{
                'stock': stock,
                'warehouse': warehouse,
                'pe_record': pe_record,
                'pb_record': pb_record,
                'indicator_config': indicator_config
            }]
        else:
            # 如果指定的股票不存在，显示空列表
            stocks_with_settings = []
    else:
        # 获取所有订单
        try:
            stocks, _ = StockMaster.get_all(page=1, per_page=100, search_query=None)
        except Exception:
            logger.exception('加载订单列表失败')
            flash('加载订单列表失败，请稍后重试。', 'error')
            stocks = []

        # 每个标的的「指标告警」阈值覆盖：先批量取回，避免逐个查库
        stock_ids = [stock['id'] for stock in stocks]
        indicator_configs = StockIndicatorConfig.get_map(stock_ids)

        # 为每个订单获取关联的设置
        stocks_with_settings = []
        for stock in stocks:
            warehouse = StockWarehouse.get_by_stock_master_id(stock['id'])
            pe_record = StockPe.get_by_stock_master_id(stock['id'])
            pb_record = StockPb.get_by_stock_master_id(stock['id'])
            
            stock_with_settings = {
                'stock': stock,
                'warehouse': warehouse,
                'pe_record': pe_record,
                'pb_record': pb_record,
                'indicator_config': indicator_configs.get(stock['id'])
            }
            stocks_with_settings.append(stock_with_settings)
    
    return render_template('alarm_settings.html',
                           stocks_with_settings=stocks_with_settings,
                           global_thresholds=_global_indicator_thresholds(),
                           indicator_cooldown_hours=getattr(Config, 'IND_COOLDOWN_HOURS', 24))

@stock_bp.route('/recent_alarms')
@login_required
def recent_alarms():
    """
    查看最近的告警记录（带搜索、筛选和分页功能）
    """
    # 获取分页和筛选参数
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search_query = request.args.get('search', '', type=str)
    start_date = request.args.get('start_date', '', type=str)
    end_date = request.args.get('end_date', '', type=str)
    
    # 验证每页显示数量的有效性
    valid_per_page_options = [5, 10, 20, 50]
    if per_page not in valid_per_page_options:
        per_page = 10
    
    # 获取告警数据
    alarms, total_count = StockAlarm.get_all_alarms(
        page=page,
        per_page=per_page,
        search_query=search_query,
        start_date=start_date,
        end_date=end_date
    )
    
    # 计算总页数
    total_pages = math.ceil(total_count / per_page) if per_page else 0

    return render_template(
        'recent_alarms.html',
        alarms=alarms,
        total_count=total_count,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        search_query=search_query,
        start_date=start_date,
        end_date=end_date,
        alarm_stats=StockAlarm.get_stats()
    )

@stock_bp.route('/refresh_quotes', methods=['POST'])
@login_required
def refresh_quotes():
    """
    刷新**当前页**订单的行情（列表页「刷新行情」按钮）。

    只查库：监控线程在后台持续采集并落库，这里重新读取即可，**不请求雪球**——
    一次点击打几十次外部请求既慢又容易触发限流，而且库里本来就是最新的。

    入参：JSON {'ids': [...]}（前端传当前页可见行的 ID）
    """
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get('ids') or []
    # 只接受正整数，并限制规模（防止构造超大请求把整表拉出来）
    ids = [int(i) for i in raw_ids if str(i).isdigit()][:200]

    quotes = StockMaster.get_quotes_by_ids(ids)
    return jsonify({
        'quotes': quotes,
        'updated_at': time.strftime('%H:%M:%S'),
    })


@stock_bp.route('/api/system_status')
@login_required
def api_system_status():
    """
    API接口：系统运行状态（监控 / 交易时段 / 告警冷却 / 雪球行情源）。

    供侧栏底部与顶栏徽标定时刷新：这些状态会随时间变化（例如进入午间休市），
    不刷新整页也要跟着变。文案与首屏渲染共用 utils.system_status。
    """
    from models.stock_monitor import monitor  # 延迟导入，避免与 models 层的循环依赖
    from utils.system_status import build_system_status

    return jsonify(build_system_status(monitor))


@stock_bp.route('/api/kline/<int:stock_id>')
@login_required
def api_kline_data(stock_id):
    """
    API接口：获取股票的K线数据
    """
    try:
        from models.stock_kline import StockKline
        
        # 从数据库获取最近30天的K线数据
        query = """
        SELECT trade_date, close_price, ma5, ma10, ma30, signal_type
        FROM stock_kline
        WHERE stock_master_id = %s
        ORDER BY trade_date DESC
        LIMIT 60
        """
        
        from database import get_connection
        import pymysql
        
        conn = get_connection()
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(query, (stock_id,))
                klines = cursor.fetchall()
                
                # 反转列表，使日期从早到晚
                klines.reverse()
                
                # 格式化日期
                for kline in klines:
                    if kline['trade_date']:
                        kline['trade_date'] = kline['trade_date'].strftime('%Y-%m-%d')
        finally:
            conn.close()
        
        return jsonify({
            'success': True,
            'klines': klines
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500