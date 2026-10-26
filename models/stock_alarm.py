"""
告警表模型
"""
import logging

from models.base import BaseModel
from utils.access import build_owner_where
from datetime import datetime
import pymysql

from utils.alarm_rules import NOTIFY_PENDING

logger = logging.getLogger(__name__)

class StockAlarm(BaseModel):
    table_name = 'stock_alarm'
    search_fields = ['alarm_text']
    
    def __init__(self, id=None, stock_master_id=None, alarm_time=None, alarm_text=None,
                 alarm_type=None, alarm_subtype=None, alarm_level=None, notify_status=None,
                 created_at=None):
        self.id = id
        self.stock_master_id = stock_master_id
        self.alarm_time = alarm_time
        self.alarm_text = alarm_text
        self.alarm_type = alarm_type
        self.alarm_subtype = alarm_subtype
        self.alarm_level = alarm_level
        self.notify_status = notify_status
        self.created_at = created_at

    @classmethod
    def create(cls, stock_master_id, alarm_text, alarm_type=None, alarm_subtype=None,
               alarm_level=None, notify_status=NOTIFY_PENDING):
        """
        创建新的告警记录。

        :param alarm_type: sell / price / pe / pb / indicator / unknown
        :param alarm_subtype: 指标类细分（low52w / drawdown / rs20 / rs5）
        :param alarm_level: 档位 1/2/3（价格与估值用）
        :param notify_status: 通知状态，默认 pending，发信后由调用方回写
        :return: 新记录 id；失败返回 None
        """
        query = """
        INSERT INTO stock_alarm
            (stock_master_id, alarm_text, alarm_type, alarm_subtype, alarm_level, notify_status)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        params = (stock_master_id, alarm_text, alarm_type, alarm_subtype, alarm_level, notify_status)

        try:
            return cls.execute_insert(query, params)
        except Exception:
            logger.exception('创建告警记录失败')
            return None

    @classmethod
    def update_notify_status(cls, alarm_id, status):
        """
        回写邮件通知状态（sent / failed / skipped）。

        :return: True 表示更新成功
        """
        if not alarm_id:
            return False
        query = "UPDATE stock_alarm SET notify_status = %s WHERE id = %s"
        try:
            return cls.execute_update(query, (status, alarm_id)) > 0
        except Exception:
            logger.exception('更新告警通知状态失败 id=%s', alarm_id)
            return False
    
    @classmethod
    def get_by_stock_master_id(cls, stock_master_id, limit=10):
        """
        根据主订单ID获取告警记录
        """
        query = "SELECT * FROM stock_alarm WHERE stock_master_id = %s ORDER BY alarm_time DESC LIMIT %s"
        params = (stock_master_id, limit)
        
        try:
            result = cls.execute_query(query, params)
            alarms = []
            for alarm_data in result:
                alarm = cls(
                    id=alarm_data['id'],
                    stock_master_id=alarm_data['stock_master_id'],
                    alarm_time=alarm_data['alarm_time'],
                    alarm_text=alarm_data['alarm_text'],
                    alarm_type=alarm_data.get('alarm_type'),
                    alarm_subtype=alarm_data.get('alarm_subtype'),
                    alarm_level=alarm_data.get('alarm_level'),
                    notify_status=alarm_data.get('notify_status'),
                    created_at=alarm_data['created_at']
                )
                alarms.append(alarm)
            return alarms
        except Exception:
            logger.exception('查询告警记录失败')
            return []
    
    @classmethod
    def get_recent_alarms(cls, limit=20):
        """
        获取最近的告警记录
        """
        query = "SELECT * FROM stock_alarm ORDER BY alarm_time DESC LIMIT %s"
        params = (limit,)
        
        try:
            result = cls.execute_query(query, params)
            alarms = []
            for alarm_data in result:
                alarm = cls(
                    id=alarm_data['id'],
                    stock_master_id=alarm_data['stock_master_id'],
                    alarm_time=alarm_data['alarm_time'],
                    alarm_text=alarm_data['alarm_text'],
                    alarm_type=alarm_data.get('alarm_type'),
                    alarm_subtype=alarm_data.get('alarm_subtype'),
                    alarm_level=alarm_data.get('alarm_level'),
                    notify_status=alarm_data.get('notify_status'),
                    created_at=alarm_data['created_at']
                )
                alarms.append(alarm)
            return alarms
        except Exception:
            logger.exception('查询告警记录失败')
            return []
    
    @classmethod
    def get_stats(cls, owner_user_id=None):
        """
        告警概览统计（供告警历史页 KPI 使用）。

        :param owner_user_id: 可见范围（多用户数据隔离），见 `utils.access.build_owner_where`
        :return: dict(total, today, last7, mail_sent, mail_failed, mail_skipped)；查询失败返回 None
        """
        owner_sql, owner_params = build_owner_where(owner_user_id, alias='sm')
        where = f" WHERE {owner_sql}" if owner_sql else ""
        query = f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN sa.alarm_time >= CURDATE() THEN 1 ELSE 0 END) AS today,
            SUM(CASE WHEN sa.alarm_time >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS last7,
            SUM(CASE WHEN sa.notify_status = 'sent' THEN 1 ELSE 0 END) AS mail_sent,
            SUM(CASE WHEN sa.notify_status = 'failed' THEN 1 ELSE 0 END) AS mail_failed,
            SUM(CASE WHEN sa.notify_status = 'skipped' THEN 1 ELSE 0 END) AS mail_skipped
        FROM stock_alarm sa
        JOIN stock_master sm ON sm.id = sa.stock_master_id{where}
        """
        try:
            result = cls.execute_query(query, tuple(owner_params) or None)
        except Exception:
            logger.exception('获取告警统计失败')
            return None
        if not result:
            return None
        row = result[0]
        # SUM 在无匹配行时返回 None，统一成 0 便于模板直接格式化
        return {key: (row.get(key) or 0) for key in
                ('total', 'today', 'last7', 'mail_sent', 'mail_failed', 'mail_skipped')}

    @classmethod
    def count_recent_indicator(cls, hours=24, owner_user_id=None):
        """
        近 N 小时的「指标」类告警条数（侧栏「指标监控」徽标用）。

        徽标必须显示真实数据：查询失败一律降级为 0（模板据此隐藏徽标），
        不许退回写死数字——0 条看起来是"没有告警"，写死数字则是假信息。

        :param hours: 统计窗口（小时），非法值按 24 处理
        :param owner_user_id: 可见范围（多用户数据隔离），徽标也只数自己名下的标的
        :return: int；异常返回 0
        """
        try:
            hours = max(int(hours), 1)
        except (TypeError, ValueError):
            hours = 24

        owner_sql, owner_params = build_owner_where(owner_user_id, alias='sm')
        where = f" AND {owner_sql}" if owner_sql else ""
        query = f"""
        SELECT COUNT(*) AS total FROM stock_alarm sa
        JOIN stock_master sm ON sm.id = sa.stock_master_id
        WHERE sa.alarm_type = 'indicator'
          AND sa.alarm_time >= DATE_SUB(NOW(), INTERVAL %s HOUR){where}
        """
        params = [hours] + list(owner_params)
        try:
            result = cls.execute_query(query, tuple(params))
        except Exception:
            logger.exception('统计近 %s 小时指标告警数失败', hours)
            return 0
        if not result:
            return 0
        try:
            return int(result[0].get('total') or 0)
        except (TypeError, ValueError):
            logger.exception('指标告警数无法转成整数：%r', result[0])
            return 0

    @classmethod
    def summarize_since(cls, hours=24):
        """
        近 N 小时告警汇总（每日汇总邮件用）。

        :param hours: 统计窗口（小时），非法值按 24 处理
        :return: dict(hours, total, by_type, samples)；查询失败返回 None
        """
        try:
            hours = max(int(hours), 1)
        except (TypeError, ValueError):
            hours = 24

        window = 'DATE_SUB(NOW(), INTERVAL %s HOUR)'
        try:
            total_rows = cls.execute_query(
                f"SELECT COUNT(*) AS total FROM stock_alarm WHERE alarm_time >= {window}",
                (hours,),
            )
            type_rows = cls.execute_query(
                f"SELECT alarm_type, COUNT(*) AS cnt FROM stock_alarm "
                f"WHERE alarm_time >= {window} GROUP BY alarm_type",
                (hours,),
            )
            sample_rows = cls.execute_query(
                f"SELECT sa.alarm_time, sa.alarm_type, sa.alarm_text, sm.stock_name "
                f"FROM stock_alarm sa "
                f"LEFT JOIN stock_master sm ON sm.id = sa.stock_master_id "
                f"WHERE sa.alarm_time >= {window} "
                f"ORDER BY sa.alarm_time DESC LIMIT 8",
                (hours,),
            )
        except Exception:
            logger.exception('汇总近 %s 小时告警失败', hours)
            return None

        return {
            'hours': hours,
            'total': int((total_rows[0].get('total') if total_rows else 0) or 0),
            'by_type': {
                (row.get('alarm_type') or 'unknown'): int(row.get('cnt') or 0)
                for row in type_rows
            },
            'samples': [dict(row) for row in sample_rows],
        }

    @classmethod
    def get_all_alarms(cls, page=1, per_page=10, search_query=None, start_date=None,
                       end_date=None, owner_user_id=None):
        """
        获取告警记录（支持分页、搜索、日期筛选与归属过滤）。

        :param owner_user_id: 可见范围（多用户数据隔离），见 `utils.access.build_owner_where`；
                              告警本身没有归属列，靠 JOIN `stock_master` 继承订单的归属
        """
        offset = (page - 1) * per_page

        select_part = ("SELECT sa.*, sm.stock_name, sm.stock_code "
                       "FROM stock_alarm sa "
                       "JOIN stock_master sm ON sa.stock_master_id = sm.id")
        count_part = ("SELECT COUNT(sa.id) as total "
                      "FROM stock_alarm sa "
                      "JOIN stock_master sm ON sa.stock_master_id = sm.id")

        # 条件只构造一次：数据查询与 COUNT 查询复用同一套，避免分页总数与列表不一致（D-07）
        where_conditions = []
        params = []

        owner_sql, owner_params = build_owner_where(owner_user_id, alias='sm')
        if owner_sql:
            where_conditions.append(owner_sql)
            params.extend(owner_params)

        if search_query:
            where_conditions.append(
                "(sa.alarm_text LIKE %s OR sm.stock_name LIKE %s OR sm.stock_code LIKE %s)"
            )
            search_param = f"%{search_query}%"
            params.extend([search_param, search_param, search_param])

        if start_date:
            where_conditions.append("sa.alarm_time >= %s")
            params.append(start_date)

        if end_date:
            where_conditions.append("sa.alarm_time <= %s")
            params.append(end_date)

        where_sql = (" WHERE " + " AND ".join(where_conditions)) if where_conditions else ""

        query = select_part + where_sql + " ORDER BY sa.alarm_time DESC LIMIT %s OFFSET %s"
        list_params = list(params) + [per_page, offset]

        try:
            result = cls.execute_query(query, tuple(list_params))
            count_result = cls.execute_query(count_part + where_sql, tuple(params))
            total_count = count_result[0]['total'] if count_result else 0

            return result, total_count
        except Exception:
            logger.exception('查询告警记录列表失败')
            return [], 0