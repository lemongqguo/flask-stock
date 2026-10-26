"""
装饰器工具。

D-10 修复：移除依赖 User 表中不存在的 role / permissions 字段的死代码
（admin_required、permission_required），避免误导后续维护者以为权限体系已存在。
当前项目为单角色内网工具，只需 login_required；如需权限体系，
应先在 users 表增加对应字段并另立规格。
"""
from functools import wraps

from flask import redirect, session, url_for


def login_required(f):
    """
    登录验证装饰器：未登录时重定向到登录页。
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function
