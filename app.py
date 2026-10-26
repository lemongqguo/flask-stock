"""
应用入口。

D-05 修复：
- debug 不再硬编码 True，改由环境变量 FLASK_DEBUG 控制，默认关闭；
- 使用 reloader 时只在子进程中启动监控线程，避免父/子进程各拉起一个监控线程；
- start_monitoring() 本身幂等，重复调用不会产生第二个线程。

D-11 修复：日志同时输出到控制台与文件（原来仅在非 debug 时挂文件 handler，
实际等于从不落盘）。
"""
import logging
import os

from flask import Flask, has_request_context, redirect, render_template, request, session, url_for

from config import Config, validate_runtime_settings
from database import init_database
from models.stock_monitor import monitor
from utils.logging_config import setup_logging
from views.ai_analysis import ai_bp
from views.auth import auth_bp
from views.stock_orders import stock_bp

# 启动即初始化日志，保证后续模块的 logger 生效
setup_logging(level=Config.DEBUG and 'DEBUG' or 'INFO')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# 注册蓝图
app.register_blueprint(auth_bp)
app.register_blueprint(stock_bp, url_prefix='/stock')
# AI 分析（007）：/stock/ai/...，与订单页同域便于共用侧栏与静态资源
app.register_blueprint(ai_bp, url_prefix='/stock/ai')


@app.template_global('static_url')
def static_url(filename):
    """
    静态资源 URL（**带版本号**）。

    Flask 对 static 目录的响应不带明确的 max-age，浏览器会用启发式缓存——
    改了 CSS/JS 之后用户拿到的仍是旧文件，表现为"按钮点了没反应"。
    这里按文件 mtime 拼 `?v=`：文件一改 URL 就变，强制拉新。

    模板里统一用 `{{ static_url('js/theme.js') }}`，**不要**直接 `url_for('static', ...)`。
    """
    path = os.path.join(app.static_folder or 'static', filename)
    try:
        version = int(os.path.getmtime(path))
    except OSError:
        version = 0
    return url_for('static', filename=filename, v=version)


@app.context_processor
def inject_system_status():
    """全局注入系统运行状态：侧栏底部与顶栏徽标**首屏就有值**（无空白闪烁）。

    文案与 /stock/api/system_status 共用 utils.system_status，保证首屏与轮询更新一致。

    另外注入侧栏导航徽标 `nav_badges`（「指标监控」条数）：只在已登录时查库
    （未登录不渲染侧栏，没必要查）；查询失败由模型降级为 0，模板据此隐藏徽标。
    """
    from utils.system_status import build_system_status

    nav_badges = {'indicator': 0}
    # `session` 依赖请求上下文：`render_template_string` 只在 app 上下文里跑时不能碰它
    if has_request_context() and session.get('user_id'):
        from models.stock_alarm import StockAlarm

        nav_badges['indicator'] = StockAlarm.count_recent_indicator(24)

    return {
        'system_status': build_system_status(monitor),
        'nav_badges': nav_badges,
    }


def bootstrap_database():
    """初始化数据库结构；失败时记录错误但不阻断应用启动（便于先看页面）。"""
    if init_database():
        logger.info('数据库结构检查完成')
    else:
        logger.error('数据库结构检查失败，相关页面将无法正常使用')


bootstrap_database()

# 白名单端点：不要求登录
PUBLIC_ENDPOINTS = frozenset({'auth.login', 'auth.register', 'static'})


@app.before_request
def require_login():
    """全局登录拦截，作为 @login_required 之外的第二道防线。"""
    if request.endpoint not in PUBLIC_ENDPOINTS and 'user_id' not in session:
        return redirect(url_for('auth.login'))


@app.route('/')
def index():
    """主页路由。"""
    return redirect(url_for('stock.stock_list'))


@app.errorhandler(403)
def forbidden_error(error):
    logger.warning('403 越权访问: %s', request.url)
    return render_template(
        'error.html',
        error_message='没有访问权限',
        error_description='您没有权限访问该页面',
    ), 403


@app.errorhandler(404)
def not_found_error(error):
    logger.warning('404 页面未找到: %s', request.url)
    return render_template(
        'error.html',
        error_message='页面未找到',
        error_description='您访问的页面不存在，请检查URL是否正确',
    ), 404


@app.errorhandler(500)
def internal_error(error):
    logger.exception('服务器内部错误: %s', request.url)
    return render_template(
        'error.html',
        error_message='服务器内部错误',
        error_description='服务器遇到了问题，请稍后重试或联系管理员',
    ), 500


def start_monitoring_on_startup():
    """
    启动监控服务。

    使用 Werkzeug reloader 时，父进程负责监视文件变化、子进程才真正提供服务，
    因此只在子进程中启动监控线程，避免出现两个监控线程。
    """
    if not Config.MONITOR_ENABLED:
        logger.info('监控服务已通过 MONITOR_ENABLED=0 禁用')
        return False

    if Config.DEBUG and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        logger.info('检测到 reloader 父进程，跳过监控启动（由子进程负责）')
        return False

    started = monitor.start_monitoring()
    if started:
        logger.info('订单监控服务已启动')
    else:
        logger.warning('订单监控服务未启动（线程可能已在运行）')
    return started


def install_shutdown_handlers():
    """
    注册优雅退出处理器（Ctrl+C / SIGTERM）。

    ThreadPoolExecutor 的工作线程是非 daemon 线程，解释器退出时会 join 它们；
    监控任务最长要休眠 300 秒，导致按下 Ctrl+C 后进程迟迟不退出。
    这里在收到信号时先停监控并取消排队任务，再起看门狗兜底强制退出。
    """
    try:
        from utils.shutdown import install_graceful_shutdown

        return install_graceful_shutdown(
            timeout=Config.SHUTDOWN_TIMEOUT,
            callbacks=[monitor.stop_monitoring],
        )
    except Exception:
        logger.exception('注册退出处理器失败，Ctrl+C 可能无法正常退出')
        return None


@app.cli.command('init-db')
def init_db_command():
    """flask init-db：手动执行数据库初始化。"""
    if init_database():
        print('数据库初始化成功')
    else:
        print('数据库初始化失败')


if __name__ == '__main__':
    # 生产环境严格校验配置（缺凭据直接拒绝启动）
    validate_runtime_settings(strict=not Config.DEBUG)

    # 网络调用兜底超时，避免线程挂死导致进程无法退出
    try:
        from utils.shutdown import set_socket_default_timeout

        set_socket_default_timeout(Config.SOCKET_TIMEOUT)
    except Exception:  # pragma: no cover - 兜底，不应阻断启动
        logger.exception('设置 socket 默认超时失败')

    install_shutdown_handlers()
    start_monitoring_on_startup()

    try:
        app.run(
            debug=Config.DEBUG,
            use_reloader=Config.DEBUG,
            host=Config.HOST,
            port=Config.PORT,
        )
    except KeyboardInterrupt:
        logger.info('已收到中断信号，应用退出')
    finally:
        monitor.stop_monitoring()
