"""
数据库初始化与连接管理。
"""
import logging

import pymysql

from config import get_pool
from utils.alarm_rules import NOTIFY_UNKNOWN, classify_alarm_text

logger = logging.getLogger(__name__)


def _create_tables(conn):
    """创建全部业务表（幂等）。"""
    with conn.cursor() as cursor:
        # 用户表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(80) UNIQUE NOT NULL,
                password_hash VARCHAR(120) NOT NULL,
                email VARCHAR(120),
                -- 个人资料扩展（2026-10-23 账户设置）：手机号 / 默认基准指数 / 最后登录
                phone VARCHAR(32) NULL,
                bench_code VARCHAR(16) NULL,
                last_login TIMESTAMP NULL DEFAULT NULL,
                -- 刻意不带 ON UPDATE：登录回写 last_login 不应把该账户顶成"最近保存的账户"
                -- （生效账户判定依赖 updated_at，见 models/account_settings.py）
                updated_at TIMESTAMP NULL DEFAULT NULL,
                -- 角色（2026-10-26 多用户数据隔离）：admin 看全部订单，user 只看自己名下
                role ENUM('user', 'admin') NOT NULL DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 告警通知偏好（2026-10-23 账户设置）：四类开关，默认"三类开、每日汇总关"
        # 每用户一行；无行的用户 = 用默认偏好
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_notify_pref (
                user_id INT PRIMARY KEY,
                notify_price TINYINT NOT NULL DEFAULT 1,
                notify_valuation TINYINT NOT NULL DEFAULT 1,
                notify_indicator TINYINT NOT NULL DEFAULT 1,
                notify_daily TINYINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 主订单表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_master (
                id INT AUTO_INCREMENT PRIMARY KEY,
                -- 归属用户（2026-10-26 多用户数据隔离）
                user_id INT NULL,
                stock_name VARCHAR(100) NOT NULL,
                stock_code VARCHAR(20) NOT NULL,
                target_pettm DECIMAL(10,2),
                current_pe DECIMAL(10,2),
                target_pb DECIMAL(10,2),
                current_pb DECIMAL(10,2),
                status ENUM('active', 'inactive') DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_stock_name (stock_name),
                INDEX idx_stock_code (stock_code),
                -- 同一股票代码可被多个用户各自持有，唯一性收敛到 (归属人, 代码)
                INDEX idx_stock_owner (user_id),
                UNIQUE KEY uk_user_code (user_id, stock_code),
                CONSTRAINT fk_stock_master_user FOREIGN KEY (user_id)
                    REFERENCES users(id) ON DELETE RESTRICT
            )
        """)

        # 仓库表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_warehouse (
                id INT AUTO_INCREMENT PRIMARY KEY,
                stock_master_id INT NOT NULL,
                dividend_yield DECIMAL(5,2),
                current_price DECIMAL(10,2),
                sell_rate DECIMAL(10,2),
                stock_valueone DECIMAL(10,2),
                stock_valuetwo DECIMAL(10,2),
                stock_valuethree DECIMAL(10,2),
                memo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (stock_master_id) REFERENCES stock_master(id) ON DELETE CASCADE
            )
        """)

        # PE 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_pe (
                id INT AUTO_INCREMENT PRIMARY KEY,
                stock_master_id INT NOT NULL,
                pe_valueone DECIMAL(10,2),
                pe_valuetwo DECIMAL(10,2),
                pe_valuethree DECIMAL(10,2),
                memo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (stock_master_id) REFERENCES stock_master(id) ON DELETE CASCADE
            )
        """)

        # PB 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_pb (
                id INT AUTO_INCREMENT PRIMARY KEY,
                stock_master_id INT NOT NULL,
                pb_valueone DECIMAL(10,2),
                pb_valuetwo DECIMAL(10,2),
                pb_valuethree DECIMAL(10,2),
                memo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (stock_master_id) REFERENCES stock_master(id) ON DELETE CASCADE
            )
        """)

        # 告警表：alarm_time 排序频繁，补索引（D-09）
        # alarm_type / alarm_subtype / alarm_level / notify_status 用于告警历史按类型与送达状态筛选
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_alarm (
                id INT AUTO_INCREMENT PRIMARY KEY,
                stock_master_id INT NOT NULL,
                alarm_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                alarm_text TEXT,
                alarm_type VARCHAR(16) DEFAULT 'unknown',
                alarm_subtype VARCHAR(16),
                alarm_level TINYINT,
                notify_status VARCHAR(16) DEFAULT 'unknown',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (stock_master_id) REFERENCES stock_master(id) ON DELETE CASCADE,
                INDEX idx_alarm_time (alarm_time),
                INDEX idx_stock_alarm (stock_master_id, alarm_time),
                INDEX idx_alarm_type (alarm_type, alarm_time)
            )
        """)

        # K 线数据表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_kline (
                id INT AUTO_INCREMENT PRIMARY KEY,
                stock_master_id INT NOT NULL,
                stock_code VARCHAR(20) NOT NULL,
                trade_date DATETIME NOT NULL,
                open_price DECIMAL(10,2),
                high_price DECIMAL(10,2),
                low_price DECIMAL(10,2),
                close_price DECIMAL(10,2),
                volume BIGINT,
                ma5 DECIMAL(10,2),
                ma10 DECIMAL(10,2),
                ma30 DECIMAL(10,2),
                signal_type ENUM('golden_cross', 'death_cross', 'normal') DEFAULT 'normal',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (stock_master_id) REFERENCES stock_master(id) ON DELETE CASCADE,
                INDEX idx_stock_master_trade_date (stock_master_id, trade_date),
                INDEX idx_signal_type (signal_type)
            )
        """)

        # 指标快照（006 指标监控）：按 (stock_master_id, trade_date) 幂等 upsert
        # 注：stock_master_id 用 INT 而非 BIGINT——外键列类型必须与 stock_master.id 完全一致，
        # 否则 MySQL 会报 errno 150 拒建外键。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_indicator (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                stock_master_id INT NOT NULL,
                trade_date DATE NOT NULL,
                price DECIMAL(12,4),
                high52w DECIMAL(12,4),
                low52w DECIMAL(12,4),
                pct_from_low52w DECIMAL(8,4),
                drawdown_52w DECIMAL(8,4),
                ret_5d DECIMAL(8,4),
                ret_20d DECIMAL(8,4),
                bench_code VARCHAR(16),
                bench_ret_5d DECIMAL(8,4),
                bench_ret_20d DECIMAL(8,4),
                rs_20d DECIMAL(8,4),
                rs_5d_ratio DECIMAL(8,4),
                flag_low52w TINYINT DEFAULT 0,
                flag_drawdown TINYINT DEFAULT 0,
                flag_rs20 TINYINT DEFAULT 0,
                flag_rs5 TINYINT DEFAULT 0,
                notified_at DATETIME NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_stock_indicator_date (stock_master_id, trade_date),
                FOREIGN KEY (stock_master_id) REFERENCES stock_master(id) ON DELETE CASCADE,
                INDEX idx_indicator_trade_date (trade_date)
            )
        """)

        # 单标的阈值覆盖；字段留空表示继承全局 IND_* 环境变量
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_indicator_config (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                stock_master_id INT NOT NULL UNIQUE,
                low52w_near_pct DECIMAL(8,4) NULL,
                drawdown_52w_pct DECIMAL(8,4) NULL,
                rs20_pct DECIMAL(8,4) NULL,
                rs5_ratio DECIMAL(8,4) NULL,
                rs5_min_drop_pct DECIMAL(8,4) NULL,
                rs5_min_bench_drop_pct DECIMAL(8,4) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (stock_master_id) REFERENCES stock_master(id) ON DELETE CASCADE
            )
        """)

        # 基准指数日线：stock_kline 靠 stock_master_id 关联订单，指数不是订单，故单独建表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_bench_kline (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                bench_code VARCHAR(16) NOT NULL,
                trade_date DATE NOT NULL,
                close_price DECIMAL(12,4),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_bench_date (bench_code, trade_date)
            )
        """)


        # AI 分析报告留痕（007 AI 个股分析）：一次调用一行，用于复盘、月度计数与成本核对。
        # content_json 存结构化结果（评级 / 要点 / 支撑 / 风险 / 免责声明），verdict=qa 时存追问的问答。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_ai_report (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                stock_master_id INT NOT NULL,
                model VARCHAR(64),
                prompt_version VARCHAR(16),
                verdict VARCHAR(16),
                confidence DECIMAL(5,2) NULL,
                content_json MEDIUMTEXT,
                tokens_used INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (stock_master_id) REFERENCES stock_master(id) ON DELETE CASCADE,
                INDEX idx_ai_report_stock (stock_master_id, created_at),
                INDEX idx_ai_report_created (created_at)
            )
        """)

        # AI 可调参数（仅非凭据项；单行表，固定 id=1）。密钥永远只在环境变量里。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_ai_config (
                id INT PRIMARY KEY,
                enabled TINYINT DEFAULT 1,
                temperature DECIMAL(3,2) DEFAULT 0.60,
                max_tokens INT DEFAULT 1200,
                monthly_limit INT DEFAULT 200,
                data_scope VARCHAR(64) DEFAULT 'quote,valuation,indicator,kline',
                model VARCHAR(64) DEFAULT NULL,
                dimensions VARCHAR(128) DEFAULT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)


# 针对已存在的存量库补索引（CREATE TABLE IF NOT EXISTS 不会改动已有表）
_INDEX_MIGRATIONS = [
    ('stock_alarm', 'idx_alarm_time', 'ALTER TABLE stock_alarm ADD INDEX idx_alarm_time (alarm_time)'),
    ('stock_alarm', 'idx_stock_alarm',
     'ALTER TABLE stock_alarm ADD INDEX idx_stock_alarm (stock_master_id, alarm_time)'),
    ('stock_alarm', 'idx_alarm_type',
     'ALTER TABLE stock_alarm ADD INDEX idx_alarm_type (alarm_type, alarm_time)'),
    # 多用户归属（2026-10-26）：列表 / 统计都按 user_id 过滤，必须走索引
    ('stock_master', 'idx_stock_owner',
     'ALTER TABLE stock_master ADD INDEX idx_stock_owner (user_id)'),
]

# 唯一键调整（2026-10-26 多用户数据隔离）：
# stock_code 由「全局唯一」改为「(归属人, 代码) 唯一」，同一只票可被多个用户各自持有。
# 顺序有意义——必须先 DROP 旧的全局唯一，再 ADD 新的复合唯一。
_UNIQUE_KEY_MIGRATIONS = [
    ('stock_master', 'stock_code', 'drop', 'ALTER TABLE stock_master DROP INDEX stock_code'),
    ('stock_master', 'uk_user_code', 'add',
     'ALTER TABLE stock_master ADD UNIQUE KEY uk_user_code (user_id, stock_code)'),
]

# 外键（2026-10-26）：必须在回填 user_id 之后执行，否则存量行会因找不到父行而拒建。
# RESTRICT 而非 CASCADE：删用户连带清掉其订单 / 行情 / 告警代价太大，宁可禁止删用户。
_FOREIGN_KEY_MIGRATIONS = [
    ('stock_master', 'fk_stock_master_user',
     'ALTER TABLE stock_master ADD CONSTRAINT fk_stock_master_user '
     'FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT'),
]

# 首个用户默认成为管理员：保证改造后立刻有一个能看到全部订单的账号，不会把自己锁在外面
_FIRST_ADMIN_QUERY = "SELECT id FROM users ORDER BY id ASC LIMIT 1"

# 针对已存在的存量库补字段（CREATE TABLE IF NOT EXISTS 不会改动已有表）
# 注意：ALTER 刻意不带 DEFAULT，使存量行的新字段保持 NULL，
# 从而让 _backfill_alarm_types 能区分"未回填"，并保证重复执行安全。
_COLUMN_MIGRATIONS = [
    ('stock_alarm', 'alarm_type', 'ALTER TABLE stock_alarm ADD COLUMN alarm_type VARCHAR(16) NULL'),
    ('stock_alarm', 'alarm_subtype', 'ALTER TABLE stock_alarm ADD COLUMN alarm_subtype VARCHAR(16) NULL'),
    ('stock_alarm', 'alarm_level', 'ALTER TABLE stock_alarm ADD COLUMN alarm_level TINYINT NULL'),
    ('stock_alarm', 'notify_status', 'ALTER TABLE stock_alarm ADD COLUMN notify_status VARCHAR(16) NULL'),
    # AI 页改版（2026-10-22）：模型选择与分析维度，均只存非凭据项
    ('stock_ai_config', 'model',
     'ALTER TABLE stock_ai_config ADD COLUMN model VARCHAR(64) NULL DEFAULT NULL'),
    ('stock_ai_config', 'dimensions',
     'ALTER TABLE stock_ai_config ADD COLUMN dimensions VARCHAR(128) NULL DEFAULT NULL'),
    # 账户设置（2026-10-23）：个人资料扩展字段
    ('users', 'phone', 'ALTER TABLE users ADD COLUMN phone VARCHAR(32) NULL'),
    ('users', 'bench_code', 'ALTER TABLE users ADD COLUMN bench_code VARCHAR(16) NULL'),
    ('users', 'last_login', 'ALTER TABLE users ADD COLUMN last_login TIMESTAMP NULL DEFAULT NULL'),
    ('users', 'updated_at', 'ALTER TABLE users ADD COLUMN updated_at TIMESTAMP NULL DEFAULT NULL'),
    # 多用户数据隔离（2026-10-26）
    ('users', 'role',
     "ALTER TABLE users ADD COLUMN role ENUM('user', 'admin') NOT NULL DEFAULT 'user'"),
    ('stock_master', 'user_id', 'ALTER TABLE stock_master ADD COLUMN user_id INT NULL'),
]


def _ensure_columns(conn):
    """幂等地为存量表补齐缺失字段。"""
    with conn.cursor() as cursor:
        for table, column, ddl in _COLUMN_MIGRATIONS:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
                (table, column),
            )
            row = cursor.fetchone()
            if row and row[0] > 0:
                continue
            try:
                cursor.execute(ddl)
                logger.info('已为 %s 表补充字段 %s', table, column)
            except Exception as exc:  # noqa: BLE001 - 迁移失败不应阻断启动
                logger.warning('为 %s 表补充字段 %s 失败: %s', table, column, exc)


def _backfill_alarm_types(conn):
    """
    为存量告警回填 alarm_type / alarm_level / notify_status。

    早期 stock_alarm 只有文本没有类型字段，这里按文本尽力反推；
    **无法识别的一律落 unknown**——宁可留白也不猜测。
    只处理 alarm_type 为 NULL 的行，因此可重复执行。
    """
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT id, alarm_text FROM stock_alarm WHERE alarm_type IS NULL")
            rows = cursor.fetchall()

        if not rows:
            return 0

        updated = 0
        with conn.cursor() as cursor:
            for row in rows:
                alarm_type, alarm_level = classify_alarm_text(row['alarm_text'])
                cursor.execute(
                    "UPDATE stock_alarm SET alarm_type = %s, alarm_level = %s, "
                    "notify_status = IFNULL(notify_status, %s) WHERE id = %s",
                    (alarm_type, alarm_level, NOTIFY_UNKNOWN, row['id']),
                )
                updated += 1
        logger.info('已回填 %s 条存量告警的类型字段', updated)
        return updated
    except Exception as exc:  # noqa: BLE001 - 回填失败不应阻断启动
        logger.warning('回填存量告警类型失败: %s', exc)
        return 0


def _ensure_indexes(conn):
    """幂等地为存量表补齐缺失索引。"""
    with conn.cursor() as cursor:
        for table, index_name, ddl in _INDEX_MIGRATIONS:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.STATISTICS "
                "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
                (table, index_name),
            )
            row = cursor.fetchone()
            if row and row[0] > 0:
                continue
            try:
                cursor.execute(ddl)
                logger.info('已为 %s 表补充索引 %s', table, index_name)
            except Exception as exc:  # noqa: BLE001 - 迁移失败不应阻断启动
                logger.warning('为 %s 表补充索引 %s 失败: %s', table, index_name, exc)


def _ensure_first_admin(conn):
    """
    保证至少有一个管理员：把 id 最小的用户提升为 admin。

    为什么必须有这一步：普通用户只看自己名下的订单，**没有任何 admin 时，
    user_id 为空的存量订单将谁也看不见**（同时也无法回收）。
    只处理"全库还没有 admin"的情况，既有的管理员不会被覆盖。

    :return: 提升的用户数（0 或 1）
    """
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            row = cursor.fetchone()
            if row and row[0] > 0:
                return 0

            cursor.execute(_FIRST_ADMIN_QUERY)
            target = cursor.fetchone()
            if not target:
                return 0
            cursor.execute("UPDATE users SET role = 'admin' WHERE id = %s", (target[0],))
            logger.info('已将首个用户 id=%s 设为管理员', target[0])
            return 1
    except Exception as exc:  # noqa: BLE001 - 迁移失败不应阻断启动
        logger.warning('设置首个管理员失败: %s', exc)
        return 0


def _backfill_stock_owner(conn):
    """
    给存量订单补归属人：统一归到 id 最小的用户（即 `_ensure_first_admin` 认定的管理员）。

    改造前 `stock_master` 没有 `user_id`，存量行补 NULL；这里把它们交给最早注册的用户，
    由他按需要在页面上重新分配。只处理 `user_id IS NULL` 的行，故幂等可重复执行。

    :return: 回填行数；没有用户时返回 0（等注册后下一次启动再补）
    """
    try:
        with conn.cursor() as cursor:
            cursor.execute(_FIRST_ADMIN_QUERY)
            owner = cursor.fetchone()
            if not owner:
                return 0
            owner_id = owner[0]
            cursor.execute(
                "UPDATE stock_master SET user_id = %s WHERE user_id IS NULL", (owner_id,)
            )
            updated = cursor.rowcount
        if updated:
            logger.info('已将 %s 条存量订单归入用户 id=%s', updated, owner_id)
        return updated
    except Exception as exc:  # noqa: BLE001 - 回填失败不应阻断启动
        logger.warning('回填订单归属失败: %s', exc)
        return 0


def _index_exists(cursor, table, index_name):
    """判断某表上的某个索引是否存在。"""
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
        (table, index_name),
    )
    row = cursor.fetchone()
    return bool(row and row[0] > 0)


def _ensure_unique_keys(conn):
    """
    幂等地调整唯一键：`stock_code` 全局唯一 → `UNIQUE(user_id, stock_code)` 每人唯一。

    必须先 DROP 旧的全局唯一再 ADD 新的复合唯一，两者不可颠倒
    （否则同一时刻会同时存在两个约束，新库建表路径也会与迁移路径漂移）。
    """
    with conn.cursor() as cursor:
        for table, index_name, action, ddl in _UNIQUE_KEY_MIGRATIONS:
            try:
                exists = _index_exists(cursor, table, index_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning('检查唯一键失败 %s.%s: %s', table, index_name, exc)
                continue

            if action == 'drop' and not exists:
                continue
            if action == 'add' and exists:
                continue

            try:
                cursor.execute(ddl)
                logger.info('已调整唯一键 %s.%s (%s)', table, index_name, action)
            except Exception as exc:  # noqa: BLE001
                logger.warning('调整唯一键失败 %s.%s: %s', table, index_name, exc)


def _ensure_foreign_keys(conn):
    """
    幂等地补外键：`stock_master.user_id` → `users(id) ON DELETE RESTRICT`。

    **必须在 `_backfill_stock_owner` 之后执行**：存量行 `user_id` 为 NULL 时无法建外键，
    先在 `_ensure_columns` 里补列、再回填、最后约束，顺序不能乱。
    """
    with conn.cursor() as cursor:
        for table, constraint, ddl in _FOREIGN_KEY_MIGRATIONS:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
                "WHERE constraint_schema = DATABASE() AND table_name = %s "
                "AND constraint_name = %s AND constraint_type = 'FOREIGN KEY'",
                (table, constraint),
            )
            row = cursor.fetchone()
            if row and row[0] > 0:
                continue
            try:
                cursor.execute(ddl)
                logger.info('已为 %s 补充外键 %s', table, constraint)
            except Exception as exc:  # noqa: BLE001
                logger.warning('为 %s 补充外键 %s 失败: %s', table, constraint, exc)


def init_database():
    """
    初始化数据库：建表 + 补字段 + 补索引 + 归属迁移 + 回填。

    顺序是刻意的：**建/补列 → 回填归属 → 收唯一键 → 收外键**。
    唯一键与外键都依赖"所有行已有归属"，提前执行会因 NULL / 孤儿行失败。

    :return: True 表示成功
    """
    try:
        conn = get_pool().connection()
    except Exception:
        logger.exception('无法获取数据库连接，请检查 MYSQL_* 环境变量配置')
        return False

    try:
        _create_tables(conn)
        conn.commit()
        _ensure_columns(conn)
        conn.commit()
        _ensure_indexes(conn)
        conn.commit()
        # 多用户数据隔离（2026-10-26）
        _ensure_first_admin(conn)
        _backfill_stock_owner(conn)
        conn.commit()
        _ensure_unique_keys(conn)
        conn.commit()
        _ensure_foreign_keys(conn)
        conn.commit()
        _backfill_alarm_types(conn)
        conn.commit()
        logger.info('数据库表结构检查完成')
        return True
    except pymysql.err.OperationalError as exc:
        logger.error('数据库初始化失败(连接问题): %s', exc)
        conn.rollback()
        return False
    except Exception:
        logger.exception('数据库初始化失败')
        conn.rollback()
        return False
    finally:
        conn.close()


def get_connection():
    """获取一个数据库连接（由连接池管理，调用方负责 close）。"""
    return get_pool().connection()


if __name__ == '__main__':
    from utils.logging_config import setup_logging

    setup_logging()
    if init_database():
        logger.info('数据库初始化流程结束')
    else:
        raise SystemExit(1)
