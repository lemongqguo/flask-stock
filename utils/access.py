"""
多用户数据归属：可见性与写权限的**唯一判定入口**。

2026-10-26 多用户数据隔离，见 `spec/changes/2026-10-26-multi-user-ownership.md`。

为什么必须收敛到一处：`models/account_settings.py` 的头部注释已经把教训写明白了——
「页面显示的值」与「后台真正使用的值」分成两套实现，漂移最难排查。
归属判定是**安全边界**，比基准指数更不能有两份实现：

    **任何视图都不要自己拼 `WHERE user_id = `，一律走这里。**

对外只有三个口径：

- `owner_user_id = None`      —— 管理员，全量可见；
- `owner_user_id = <int>`     —— 普通用户，仅自己名下；
- `owner_user_id = NO_ACCESS`  —— 会话不完整（`@login_required` 之后理论上不会发生），
                                  查询返回空而不是全量，**失败关闭**。

管理员是否可改别人的订单由 `can_manage()` 一处决定（当前口径：可视即可管）。
"""
import logging

from flask import session

logger = logging.getLogger(__name__)

ROLE_USER = 'user'
ROLE_ADMIN = 'admin'

# 哨兵：会话缺失时不给任何数据。用字符串而非 None，避免与「管理员全量」混淆。
NO_ACCESS = '__no_access__'


def current_user_id():
    """当前登录用户 id；无请求上下文（监控线程等）返回 None。"""
    try:
        return session.get('user_id')
    except RuntimeError:  # 不在请求上下文中
        return None


def current_role():
    """当前登录用户的角色；未知一律按普通用户处理（失败关闭）。"""
    try:
        return session.get('role') or ROLE_USER
    except RuntimeError:
        return ROLE_USER


def is_admin():
    """是否管理员。会话不完整时返回 False，不给特权。"""
    return current_user_id() is not None and current_role() == ROLE_ADMIN


def owner_scope():
    """
    当前请求的数据可见范围（供所有模型查询使用）。

    :return: `None`（管理员全量）/ `int`（普通用户 id）/ `NO_ACCESS`（会话不完整）
    """
    user_id = current_user_id()
    if user_id is None:
        return NO_ACCESS
    return None if is_admin() else user_id


def build_owner_where(owner_user_id, alias='sm'):
    """
    把可见范围翻译成 SQL 片段。

    :param owner_user_id: `owner_scope()` 的返回值
    :param alias: 表别名（来自代码而非用户输入，仍做一次标识符校验）
    :return: (where_sql, params)；管理员返回 ('', [])
    """
    if owner_user_id is None:
        return '', []
    if owner_user_id == NO_ACCESS:
        return '1 = 0', []
    return f'`{_safe_alias(alias)}`.user_id = %s', [owner_user_id]


def and_where(*clauses):
    """
    合并多个 `(where_sql, params)` 片段成一个 `'a AND b'` 片段。

    含 OR 的子句保留自身括号（`build_search_where` 已返回 `(x OR y)`），
    避免合并后 `AND` 优先级把语义吃掉。

    :return: (where_sql, params)；全部为空时返回 ('', [])
    """
    parts, params = [], []
    for clause in clauses:
        sql, clause_params = clause
        if not sql:
            continue
        parts.append(sql if sql.startswith('(') else '(%s)' % sql)
        params.extend(clause_params or [])
    if not parts:
        return '', []
    return ' AND '.join(parts), params


def can_manage(stock_row):
    """
    当前用户能否对该订单做**写操作**（编辑 / 删除 / 切换状态 / 改阈值 / AI 分析）。

    当前口径：**管理员可视即可管**（为避免「看得见却点不动」的半残页面），
    普通用户仅限自己名下。要改成「管理员只读」只需把 `is_admin()` 分支删掉。

    **失败关闭**：行不存在、归属缺失、会话不完整一律返回 False。

    :param stock_row: `stock_master` 的一行 dict（也可能是带属性的模型对象）
    """
    if not stock_row:
        return False
    if is_admin():
        return True

    user_id = current_user_id()
    if user_id is None:
        return False

    owner = (stock_row.get('user_id') if isinstance(stock_row, dict)
             else getattr(stock_row, 'user_id', None))
    return owner is not None and owner == user_id


def _safe_alias(alias):
    """表别名白名单校验：只放行字母数字与下划线，其余回退到默认别名。"""
    alias = (alias or '').strip()
    if alias.replace('_', '').isalnum():
        return alias
    logger.warning('忽略非法的表别名: %r，回退到 sm', alias)
    return 'sm'
