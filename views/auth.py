"""
认证相关视图。
"""
import logging
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from models.account_settings import (
    BENCHMARK_CHOICES,
    BENCHMARK_CODES,
    BENCHMARK_NAMES,
    NOTIFY_FIELDS,
    UserNotifyPref,
    resolve_alarm_recipients,
    resolve_bench_code,
)
from models.stock_indicator import StockBenchKline
from models.user import User
from utils.decorators import login_required

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)


def _is_safe_redirect(target):
    """
    判断 next 参数是否为站内相对地址，防止开放重定向。

    D-12：原先使用 werkzeug.urls.url_parse，该 API 在 Werkzeug 3.x 已被移除，
    改用标准库 urllib.parse，无框架版本耦合。
    """
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """用户注册页面。"""
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        email = (request.form.get('email') or '').strip()

        if not username or not password:
            flash('用户名和密码不能为空。', 'error')
            return render_template('auth.html', active_tab='register')

        # 用户名查重（模型层也会再查一次，双保险避免并发重复注册）
        if User.get_by_username(username):
            flash('用户名已存在，请选择其他用户名。', 'error')
            return render_template('auth.html', active_tab='register')

        new_user = User.create(username=username, password=password, email=email)
        if new_user:
            flash('注册成功！请登录。', 'success')
            return redirect(url_for('auth.login'))

        flash('注册失败：密码至少 6 位，或用户名已被占用。', 'error')

    return render_template('auth.html', active_tab='register')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """用户登录页面。"""
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        next_page = request.args.get('next')

        user = User.authenticate(username, password)
        if user:
            session['user_id'] = user.id
            session['username'] = user.username
            # 角色写进 session（2026-10-26 多用户数据隔离）：后续请求不必再查 users 表。
            # 代价：管理员被降/升时需要重新登录才生效，已写入 001 规格。
            session['role'] = user.role
            # 最后登录时间：失败不影响登录（账户页只会显示"未知"）
            User.touch_login(user.id)

            if not _is_safe_redirect(next_page):
                next_page = url_for('index')
            return redirect(next_page)

        flash('用户名或密码错误。', 'error')

    return render_template('auth.html', active_tab='login')


@auth_bp.route('/logout')
@login_required
def logout():
    """用户登出。"""
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('role', None)
    flash('您已成功登出。', 'info')
    return redirect(url_for('auth.login'))


def _render_account(active_tab='profile', user=None):
    """
    渲染账户设置页：一律带上**真实**的个人资料、通知偏好与收件人信息。

    收件人与基准指数走 `models.account_settings` 的解析函数，与监控发信同源——
    页面上看到的地址就是真正会收到邮件的地址。
    """
    user = user or User.get_by_id(session['user_id'])
    prefs = UserNotifyPref.effective()
    bench_code = resolve_bench_code()
    recipients = resolve_alarm_recipients()

    # 基准采集状态显式化：没采到就显示"尚未采集"，不伪装成正常（恒生指数尤其需要）
    try:
        bench_latest = StockBenchKline.get_latest_trade_date(bench_code)
    except Exception:
        logger.exception('查询基准最新交易日失败 bench=%s', bench_code)
        bench_latest = None

    # 生效偏好可能属于别的账户（单账户运维视角下的多账户提示）
    pref_owner = None
    if prefs.get('user_id') and prefs['user_id'] != session.get('user_id'):
        owner = User.get_by_id(prefs['user_id'])
        pref_owner = owner.username if owner else '#%s' % prefs['user_id']

    return render_template(
        'account.html',
        user=user,
        active_tab=active_tab,
        notify_prefs=prefs,
        pref_owner=pref_owner,
        bench_choices=BENCHMARK_CHOICES,
        bench_code=bench_code,
        bench_name=BENCHMARK_NAMES.get(bench_code, bench_code),
        bench_latest=bench_latest,
        recipients=recipients,
    )


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """
    个人资料页（可写）。

    一次提交同时保存：用户名 / 邮箱 / 手机号 / 默认基准指数 + 四个告警通知开关。
    校验失败一律不落库并回显错误（用户名重名、邮箱不含 @、基准不在白名单）。
    """
    user_id = session['user_id']

    if request.method == 'POST':
        user = User.get_by_id(user_id)
        if not user:
            flash('用户不存在，请重新登录。', 'error')
            return redirect(url_for('auth.login'))

        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        bench_code = (request.form.get('bench_code') or '').strip()
        error = None

        if not username:
            error = '用户名不能为空。'
        else:
            exists = User.get_by_username(username)
            if exists and exists.id != user_id:
                error = f'用户名「{username}」已被占用。'

        if not error and email and '@' not in email:
            error = '邮箱格式不正确（需包含 @）。'

        if not error and bench_code and bench_code not in BENCHMARK_CODES:
            error = '默认基准指数不在可选范围内。'

        if error:
            flash(error, 'error')
            return _render_account('profile', user=user)

        # 通知开关：form 里没带就是关（checkbox 语义）
        flags = {field: bool(request.form.get(field)) for field in NOTIFY_FIELDS}
        profile_ok = User.update_profile(
            user_id, username=username, email=email, phone=phone,
            bench_code=bench_code,
        )
        UserNotifyPref.save(user_id, **flags)

        if not profile_ok:
            flash('资料保存失败，请稍后重试。', 'error')
            return _render_account('profile', user=user)

        session['username'] = username
        flash('资料已保存，通知偏好立即生效。', 'success')
        return redirect(url_for('auth.profile'))

    return _render_account('profile')


@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    """修改密码（与个人资料同页，失败回到同页并保留资料内容）。"""
    if request.method == 'POST':
        user_id = session['user_id']
        user = User.get_by_id(user_id)

        if not user:
            flash('用户不存在，请重新登录。', 'error')
            return redirect(url_for('auth.login'))

        old_password = request.form.get('old_password') or ''
        new_password = request.form.get('new_password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not user.check_password(old_password):
            flash('旧密码错误。', 'error')
            return _render_account('password', user=user)

        if new_password != confirm_password:
            flash('新密码与确认密码不匹配。', 'error')
            return _render_account('password', user=user)

        # 写库交给模型层，视图层不再直接执行 SQL
        if User.update_password(user_id, new_password):
            flash('密码修改成功。', 'success')
            return redirect(url_for('auth.profile'))

        flash('密码修改失败，请稍后重试。', 'error')
        return _render_account('password', user=user)

    return _render_account('password')
