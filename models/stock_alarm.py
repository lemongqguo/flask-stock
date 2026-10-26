"""
告警表模型
"""
import logging

from models.base import BaseModel
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
    def get_stats(cls):
        """
        告警概览统计（供告警历史页 KPI 使用）。

        :return: dict(total, today, last7, mail_sent, mail_failed, mail_skipped)；查询失败返回 None
        """
        query = """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN alarm_time >= CURDATE() THEN 1 ELSE 0 END) AS today,
            SUM(CASE WHEN alarm_time >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS last7,
            SUM(CASE WHEN notify_status = 'sent' THEN 1 ELSE 0 END) AS mail_sent,
            SUM(CASE WHEN notify_status = 'failed' THEN 1 ELSE 0 END) AS mail_failed,
            SUM(CASE WHEN notify_status = 'skipped' THEN 1 ELSE 0 END) AS mail_skipped
        FROM stock_alarm
        """
        try:
            result = cls.execute_query(query)
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
    def count_recent_indicator(cls, hours=24):
        """
        近 N 小时的「指标」类告警条数（侧栏「指标监控」徽标用）。

        徽标必须显示真实数据：查询失败一律降级为 0（模板据此隐藏徽标），
        不许退回写死数字——0 条看起来是"没有告警"，写死数字则是假信息。

        :param hours: 统计窗口（小时），非法值按 24 处理
        :return: int；异常返回 0
        """
        try:
            hours = max(int(hours), 1)
        except (TypeError, ValueError):
            hours = 24

        query = """
        SELECT COUNT(*) AS total FROM stock_alarm
        WHERE alarm_type = 'indicator' AND alarm_time >= DATE_SUB(NOW(), INTERVAL %s HOUR)
        """
        try:
            result = cls.execute_query(query, (hours,))
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
    def get_all_alarms(cls, page=1, per_page=10, search_query=None, start_date=None, end_date=None):
        """
        获取所有告警记录（支持分页、搜索和日期筛选）
        """
        offset = (page - 1) * per_page
        
        # 构建查询语句
        query = "SELECT sa.*, sm.stock_name, sm.stock_code FROM stock_alarm sa JOIN stock_master sm ON sa.stock_master_id = sm.id"
        params = []
        
        # 添加WHERE条件
        where_conditions = []
        
        if search_query:
            where_conditions.append("(sa.alarm_text LIKE %s OR sm.stock_name LIKE %s OR sm.stock_code LIKE %s)")
            search_param = f"%{search_query}%"
            params.extend([search_param, search_param, search_param])
        
        if start_date:
            where_conditions.append("sa.alarm_time >= %s")
            params.append(start_date)
        
        if end_date:
            where_conditions.append("sa.alarm_time <= %s")
            params.append(end_date)
        
        if where_conditions:
            query += " WHERE " + " AND ".join(where_conditions)
        
        query += " ORDER BY sa.alarm_time DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])
        
        try:
            result = cls.execute_query(query, tuple(params))
            
            # 获取总数用于分页
            count_query = "SELECT COUNT(sa.id) as total FROM stock_alarm sa JOIN stock_master sm ON sa.stock_master_id = sm.id"
            count_params = []
            count_where_conditions = []
            
            if search_query:
                count_where_conditions.append("(sa.alarm_text LIKE %s OR sm.stock_name LIKE %s OR sm.stock_code LIKE %s)")
                search_param = f"%{search_query}%"
                count_params.extend([search_param, search_param, search_param])
            
            if start_date:
                count_where_conditions.append("sa.alarm_time >= %s")
                count_params.append(start_date)
            
            if end_date:
                count_where_conditions.append("sa.alarm_time <= %s")
                count_params.append(end_date)
            
            if count_where_conditions:
                count_query += " WHERE " + " AND ".join(count_where_conditions)
            
            count_result = cls.execute_query(count_query, tuple(count_params))
            total_count = count_result[0]['total'] if count_result else 0
            
            return result, total_count
        except Exception:
            logger.exception('查询告警记录列表失败')
            return [], 0