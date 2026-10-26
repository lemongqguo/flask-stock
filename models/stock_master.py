"""
主订单表模型
"""
import logging

from models.base import BaseModel
from datetime import datetime
import pymysql

logger = logging.getLogger(__name__)

# 告警命中判定：价格三档 / 卖出价 / PE 三档 / PB 三档，任一满足即命中。
# 列表展示（CASE）与"触发告警"统计（WHERE）共用同一段条件，避免两处判定漂移。
ALARM_ACTIVE_CONDITION = """
                (sw.stock_valueone IS NOT NULL AND sw.current_price <= sw.stock_valueone)
                OR (sw.stock_valuetwo IS NOT NULL AND sw.current_price <= sw.stock_valuetwo)
                OR (sw.stock_valuethree IS NOT NULL AND sw.current_price <= sw.stock_valuethree)
                OR (sw.sell_rate IS NOT NULL AND sw.current_price >= sw.sell_rate)
                OR (sp.pe_valueone IS NOT NULL AND sm.current_pe <= sp.pe_valueone)
                OR (sp.pe_valuetwo IS NOT NULL AND sm.current_pe <= sp.pe_valuetwo)
                OR (sp.pe_valuethree IS NOT NULL AND sm.current_pe <= sp.pe_valuethree)
                OR (spb.pb_valueone IS NOT NULL AND sm.current_pb <= spb.pb_valueone)
                OR (spb.pb_valuetwo IS NOT NULL AND sm.current_pb <= spb.pb_valuetwo)
                OR (spb.pb_valuethree IS NOT NULL AND sm.current_pb <= spb.pb_valuethree)
                """

class StockMaster(BaseModel):
    table_name = 'stock_master'
    search_fields = ['stock_name', 'stock_code']
    
    def __init__(self, id=None, stock_name=None, stock_code=None, target_pettm=None, 
                 current_pe=None, target_pb=None, current_pb=None, status='active', 
                 created_at=None, updated_at=None):
        self.id = id
        self.stock_name = stock_name
        self.stock_code = stock_code
        self.target_pettm = target_pettm
        self.current_pe = current_pe
        self.target_pb = target_pb
        self.current_pb = current_pb
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
    
    @classmethod
    def create(cls, stock_name, stock_code, target_pettm=None, target_pb=None):
        """
        创建新的订单记录
        """
        query = """
        INSERT INTO stock_master (stock_name, stock_code, target_pettm, target_pb) 
        VALUES (%s, %s, %s, %s)
        """
        params = (stock_name, stock_code, target_pettm, target_pb)
        
        try:
            result = cls.execute_update(query, params)
            if result > 0:
                # 返回新创建的记录
                new_stock = cls.get_by_stock_code(stock_code)
                return new_stock
            return None
        except Exception:
            logger.exception('创建订单记录失败')
            return None
    
    @classmethod
    def get_by_stock_code(cls, stock_code):
        """
        根据股票代码获取订单记录
        """
        query = "SELECT * FROM stock_master WHERE stock_code = %s"
        result = cls.execute_query(query, (stock_code,))
        if result:
            stock_data = result[0]
            return cls(
                id=stock_data['id'],
                stock_name=stock_data['stock_name'],
                stock_code=stock_data['stock_code'],
                target_pettm=stock_data['target_pettm'],
                current_pe=stock_data['current_pe'],
                target_pb=stock_data['target_pb'],
                current_pb=stock_data['current_pb'],
                status=stock_data['status'],
                created_at=stock_data['created_at'],
                updated_at=stock_data['updated_at']
            )
        return None
    
    @classmethod
    def update(cls, id, **kwargs):
        """
        更新订单记录
        """
        # 构建动态更新语句
        fields = []
        params = []
        for key, value in kwargs.items():
            if hasattr(cls(), key):
                fields.append(f"{key} = %s")
                params.append(value)
        
        if not fields:
            return True
        
        params.append(id)
        query = f"UPDATE stock_master SET {', '.join(fields)} WHERE id = %s"
        
        try:
            result = cls.execute_update(query, tuple(params))
            # 更新成功执行，不管是否实际改变了数据
            return True
        except Exception:
            logger.exception('更新订单记录失败')
            return False
    
    @classmethod
    def delete(cls, id):
        """
        删除订单记录
        """
        return cls.delete_by_id(id)
    
    @classmethod
    def get_all_with_details(cls, page=1, per_page=10, search_query=None):
        """
        获取所有订单记录（包含关联表信息）
        """
        offset = (page - 1) * per_page
        
        # 构建查询语句，关联仓库表获取当前价格
        # 使用 CAST 将 ENUM 类型的 status 转为字符串，避免 PyMySQL 返回数字索引
        # 实时判断是否满足告警条件（价格/PE/PB任一达到阈值）
        query = """
        SELECT 
            sm.*, 
            CAST(sm.status AS CHAR) as status,
            sw.current_price,
            sw.sell_rate,
            sw.stock_valueone,
            sw.stock_valuetwo,
            sw.stock_valuethree,
            sp.pe_valueone,
            sp.pe_valuetwo,
            sp.pe_valuethree,
            spb.pb_valueone,
            spb.pb_valuetwo,
            spb.pb_valuethree,
            CASE
                WHEN""" + ALARM_ACTIVE_CONDITION + """                THEN 1 ELSE 0 END as is_alarm_active
        FROM stock_master sm
        LEFT JOIN stock_warehouse sw ON sm.id = sw.stock_master_id
        LEFT JOIN stock_pe sp ON sm.id = sp.stock_master_id
        LEFT JOIN stock_pb spb ON sm.id = spb.stock_master_id
        """
        
        count_query = "SELECT COUNT(*) as total FROM stock_master sm"
        
        params = []
        
        if search_query:
            query += " WHERE sm.stock_name LIKE %s OR sm.stock_code LIKE %s"
            count_query += " WHERE stock_name LIKE %s OR stock_code LIKE %s"
            search_param = f"%{search_query}%"
            params.extend([search_param, search_param])
        
        query += " ORDER BY sm.id DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])
        
        try:
            result = cls.execute_query(query, tuple(params))
            
            # 获取总数用于分页
            count_params = []
            if search_query:
                search_param = f"%{search_query}%"
                count_params.extend([search_param, search_param])
            count_result = cls.execute_query(count_query, tuple(count_params) if search_query else None)
            total_count = count_result[0]['total'] if count_result else 0
            
            return result, total_count
        except Exception:
            logger.exception('获取订单记录列表失败')
            return [], 0
    
    @classmethod
    def get_quotes_by_ids(cls, stock_master_ids):
        """
        批量取回指定订单的**最新行情**（只查库，不请求行情源）。

        列表页「刷新行情」按钮用：监控线程在后台持续采集并落库，页面刷新只是重新读取，
        **不触发任何外部请求**——否则一次点击会打出几十次雪球请求（既慢又容易触发限流）。

        参数:
            stock_master_ids: 订单 ID 列表（由前端传当前页可见行）

        返回:
            [{'id': .., 'current_price': .., 'current_pe': .., 'current_pb': ..}, ...]；
            查询失败返回空列表
        """
        if not stock_master_ids:
            return []

        # 占位符只由元素个数生成，值一律参数化传入
        placeholders = ', '.join(['%s'] * len(stock_master_ids))
        query = f"""
        SELECT sm.id,
               sw.current_price,
               sm.current_pe,
               sm.current_pb
        FROM stock_master sm
        LEFT JOIN stock_warehouse sw ON sw.stock_master_id = sm.id
        WHERE sm.id IN ({placeholders})
        """
        try:
            rows = cls.execute_query(query, tuple(stock_master_ids))
        except Exception:
            logger.exception('查询行情失败: ids=%s', stock_master_ids)
            return []
        def _num(value):
            # DECIMAL 直接进 jsonify 会被序列化成字符串，这里显式转 float，前端拿到的是数字
            return float(value) if value is not None else None

        return [
            {
                'id': row['id'],
                'current_price': _num(row.get('current_price')),
                'current_pe': _num(row.get('current_pe')),
                'current_pb': _num(row.get('current_pb')),
            }
            for row in rows
        ]

    @classmethod
    def count_by_status(cls, status):
        """
        根据状态统计订单数量
        """
        query = "SELECT COUNT(*) as count FROM stock_master WHERE status = %s"
        result = cls.execute_query(query, (status,))
        if result:
            return result[0]['count']
        return 0

    @classmethod
    def count_alarm_active(cls):
        """
        统计当前满足告警条件的订单数。

        判定条件与 get_all_with_details 的 is_alarm_active 共用 ALARM_ACTIVE_CONDITION，
        保证"列表高亮的行数"与"KPI 触发告警数"永远一致。
        """
        query = """
        SELECT COUNT(*) as count
        FROM stock_master sm
        LEFT JOIN stock_warehouse sw ON sm.id = sw.stock_master_id
        LEFT JOIN stock_pe sp ON sm.id = sp.stock_master_id
        LEFT JOIN stock_pb spb ON sm.id = spb.stock_master_id
        WHERE""" + ALARM_ACTIVE_CONDITION
        result = cls.execute_query(query)
        if result:
            return result[0]['count']
        return 0

    @classmethod
    def get_active_stocks(cls, limit=100):
        """
        获取所有活跃状态的股票（用于监控）
        """
        # 使用 CAST 将 ENUM 类型的 status 转为字符串
        query = """
        SELECT *, CAST(status AS CHAR) as status
        FROM stock_master 
        WHERE CAST(status AS CHAR) = 'active'
        ORDER BY id DESC
        LIMIT %s
        """
        try:
            result = cls.execute_query(query, (limit,))
            return result
        except Exception:
            logger.exception('获取活跃股票失败')
            return []