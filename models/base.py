"""
基础模型类，提供通用的数据库操作方法。
"""
import logging

import pymysql

from database import get_connection
from utils.access import and_where, build_owner_where

logger = logging.getLogger(__name__)


class BaseModel:
    table_name = None
    search_fields = None  # 子类可覆盖，声明支持搜索的字段

    @classmethod
    def execute_query(cls, query, params=None):
        """
        执行查询操作。

        :param query: SQL 语句，必须使用 %s 参数化占位
        :param params: 参数元组
        :return: 结果字典列表
        """
        conn = get_connection()
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(query, params or ())
                return cursor.fetchall()
        except Exception:
            logger.exception('查询执行失败: %s', ' '.join(str(query).split())[:200])
            raise
        finally:
            conn.close()

    @classmethod
    def execute_update(cls, query, params=None):
        """
        执行写操作（INSERT / UPDATE / DELETE）。

        :return: 受影响行数
        """
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params or ())
                affected_rows = cursor.rowcount
            conn.commit()
            return affected_rows
        except Exception:
            logger.exception('更新执行失败: %s', ' '.join(str(query).split())[:200])
            conn.rollback()
            raise
        finally:
            conn.close()

    @classmethod
    def execute_insert(cls, query, params=None):
        """
        执行 INSERT 并返回新记录的自增主键。

        与 execute_update 的区别：后者只返回受影响行数，拿不到自增 id，
        而告警需要在落库后回写邮件发送状态（notify_status），必须知道主键。

        :return: 新记录 id；执行失败时抛异常（由调用方捕获处理）
        """
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params or ())
                new_id = cursor.lastrowid
            conn.commit()
            return new_id
        except Exception:
            logger.exception('插入执行失败: %s', ' '.join(str(query).split())[:200])
            conn.rollback()
            raise
        finally:
            conn.close()

    @classmethod
    def build_search_where(cls, search_query, keyword='search'):
        """
        根据 search_query 构造 WHERE 子句。

        D-07 修复要点：
        1. 只有在确实存在可搜索字段时才追加 WHERE，杜绝拼出裸 `WHERE `；
        2. 字段名来自类定义而非用户输入，并用标识符包裹，避免注入；
        3. 返回 (where_sql, params)，便于复用同一条件做 COUNT 查询。

        :param search_query: 关键字
        :return: (where_sql, params)；无可搜索字段时返回 ('', [])
        """
        keyword = (search_query or '').strip()
        fields = getattr(cls, 'search_fields', None)
        if not keyword or not fields:
            return '', []

        conditions = []
        params = []
        for field in fields:
            # field 来自代码而非用户输入；此处再做一次白名单校验以防子类误配
            if not isinstance(field, str) or not field.replace('_', '').isalnum():
                logger.warning('忽略非法的搜索字段配置: %r', field)
                continue
            conditions.append(f'`{field}` LIKE %s')
            params.append(f'%{keyword}%')

        if not conditions:
            return '', []
        return '(' + ' OR '.join(conditions) + ')', params

    @classmethod
    def get_by_id(cls, id):
        """根据主键获取单条记录。"""
        query = f"SELECT * FROM {cls.table_name} WHERE id = %s"
        result = cls.execute_query(query, (id,))
        return result[0] if result else None

    @classmethod
    def get_all(cls, page=1, per_page=10, search_query=None, owner_user_id=None):
        """
        分页查询记录列表，支持关键字搜索与归属过滤。

        :param owner_user_id: 多用户数据隔离（2026-10-26）的可见范围，
                              取值语义见 `utils.access.build_owner_where`：
                              `None` = 全量（管理员），`int` = 仅该用户，`NO_ACCESS` = 空集。
        :return: (当前页记录列表, 总记录数)
        """
        page = max(1, int(page or 1))
        per_page = max(1, int(per_page or 10))
        offset = (page - 1) * per_page

        where_sql, where_params = and_where(
            build_owner_where(owner_user_id, alias=cls.table_name),
            cls.build_search_where(search_query),
        )

        query = f"SELECT * FROM {cls.table_name}"
        count_query = f"SELECT COUNT(*) as total FROM {cls.table_name}"
        if where_sql:
            query += f" WHERE {where_sql}"
            count_query += f" WHERE {where_sql}"

        params = list(where_params)
        query += " ORDER BY id DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        try:
            result = cls.execute_query(query, tuple(params))
            # 数据查询与 COUNT 查询必须复用同一套条件，否则分页总数会与列表对不上（D-07）
            count_result = cls.execute_query(count_query, tuple(where_params))
            total_count = count_result[0]['total'] if count_result else 0
            return result, total_count
        except Exception:
            logger.exception('获取记录列表失败 table=%s', cls.table_name)
            raise

    @classmethod
    def delete_by_id(cls, id):
        """根据主键删除记录。"""
        query = f"DELETE FROM {cls.table_name} WHERE id = %s"
        return cls.execute_update(query, (id,))
