"""
用户模型
"""
import logging

from werkzeug.security import check_password_hash, generate_password_hash

from models.base import BaseModel

logger = logging.getLogger(__name__)

# 密码最短长度（服务端校验，避免只靠前端约束）
MIN_PASSWORD_LENGTH = 6


class User(BaseModel):
    table_name = 'users'
    search_fields = ['username', 'email']

    def __init__(self, id=None, username=None, password_hash=None, email=None, created_at=None,
                 phone=None, bench_code=None, last_login=None, updated_at=None):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.email = email
        self.created_at = created_at
        # 个人资料扩展（2026-10-23 账户设置）
        self.phone = phone
        self.bench_code = bench_code
        self.last_login = last_login
        self.updated_at = updated_at

    def set_password(self, password):
        """
        设置密码哈希
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """
        检查密码是否正确
        """
        if not self.password_hash or not password:
            return False
        return check_password_hash(self.password_hash, password)

    @classmethod
    def create(cls, username, password, email=None):
        """
        创建新用户。

        :return: 创建成功返回 User 实例，用户名已存在或失败返回 None
        """
        if not username or not password:
            logger.warning('创建用户失败：用户名或密码为空')
            return None
        if len(password) < MIN_PASSWORD_LENGTH:
            logger.warning('创建用户失败：密码长度不足 %s 位', MIN_PASSWORD_LENGTH)
            return None
        if cls.get_by_username(username):
            logger.warning('创建用户失败：用户名已存在')
            return None

        user = cls()
        user.set_password(password)

        query = "INSERT INTO users (username, password_hash, email) VALUES (%s, %s, %s)"
        params = (username, user.password_hash, email)

        try:
            result = cls.execute_update(query, params)
            if result > 0:
                user.id = cls.get_user_id_by_username(username)
                return user
            return None
        except Exception:
            logger.exception('创建用户失败 username=%s', username)
            return None

    @classmethod
    def update_password(cls, user_id, new_password):
        """
        修改密码（由模型层负责写库，视图层不再直接执行 SQL）。

        :return: True 表示更新成功
        """
        if not new_password or len(new_password) < MIN_PASSWORD_LENGTH:
            logger.warning('修改密码失败：新密码长度不足 %s 位', MIN_PASSWORD_LENGTH)
            return False

        query = "UPDATE users SET password_hash = %s WHERE id = %s"
        params = (generate_password_hash(new_password), user_id)
        try:
            return cls.execute_update(query, params) > 0
        except Exception:
            logger.exception('修改密码失败 user_id=%s', user_id)
            return False

    @classmethod
    def _from_row(cls, row):
        """把 users 的一行转成 User 实例（统一缺失列处理，避免各处字段漂移）。"""
        return cls(
            id=row.get('id'),
            username=row.get('username'),
            password_hash=row.get('password_hash'),
            email=row.get('email'),
            created_at=row.get('created_at'),
            phone=row.get('phone'),
            bench_code=row.get('bench_code'),
            last_login=row.get('last_login'),
            updated_at=row.get('updated_at'),
        )

    @classmethod
    def update_profile(cls, user_id, username=None, email=None, phone=None, bench_code=None):
        """
        更新个人资料（只更新显式传入的字段）。

        `updated_at` 显式写 NOW()：生效账户（基准 / 通知偏好的归属）按它排序，
        而该列刻意不带 ON UPDATE，避免登录回写 last_login 时误判为"最近保存"。

        :return: True 表示更新到行；用户名冲突或异常返回 False
        """
        payload = {}
        if username is not None:
            payload['username'] = username
        if email is not None:
            payload['email'] = email
        if phone is not None:
            payload['phone'] = phone
        if bench_code is not None:
            # 空串视为"不指定基准"（回退到环境变量），存 NULL 而不是空字符串
            payload['bench_code'] = bench_code or None
        if not payload:
            return False

        # 列名来自上面的白名单（不允许外部传入拼接），值一律参数化
        assignments = ', '.join(f'{column} = %s' for column in payload) + ', updated_at = NOW()'
        query = f"UPDATE users SET {assignments} WHERE id = %s"
        params = tuple(payload.values()) + (user_id,)
        try:
            return cls.execute_update(query, params) > 0
        except Exception:
            logger.exception('更新个人资料失败 user_id=%s', user_id)
            return False

    @classmethod
    def touch_login(cls, user_id):
        """回写最后登录时间（失败不影响登录流程）。"""
        try:
            return cls.execute_update(
                "UPDATE users SET last_login = NOW() WHERE id = %s", (user_id,)
            ) > 0
        except Exception:
            logger.exception('回写最后登录时间失败 user_id=%s', user_id)
            return False

    @classmethod
    def get_user_id_by_username(cls, username):
        """
        根据用户名获取用户ID
        """
        query = "SELECT id FROM users WHERE username = %s"
        result = cls.execute_query(query, (username,))
        return result[0]['id'] if result else None

    @classmethod
    def get_by_username(cls, username):
        """
        根据用户名获取用户
        """
        query = "SELECT * FROM users WHERE username = %s"
        result = cls.execute_query(query, (username,))
        if result:
            return cls._from_row(result[0])
        return None

    @classmethod
    def authenticate(cls, username, password):
        """
        用户认证
        """
        user = cls.get_by_username(username)
        if user and user.check_password(password):
            return user
        return None

    @classmethod
    def get_by_id(cls, user_id):
        """
        根据用户ID获取用户
        """
        query = "SELECT * FROM users WHERE id = %s"
        result = cls.execute_query(query, (user_id,))
        if result:
            return cls._from_row(result[0])
        return None
