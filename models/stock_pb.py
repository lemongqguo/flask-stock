"""
PB表模型
"""
import logging

from models.base import BaseModel
import pymysql

logger = logging.getLogger(__name__)

class StockPb(BaseModel):
    table_name = 'stock_pb'
    
    def __init__(self, id=None, stock_master_id=None, pb_valueone=None, pb_valuetwo=None, 
                 pb_valuethree=None, memo=None, created_at=None, updated_at=None):
        self.id = id
        self.stock_master_id = stock_master_id
        self.pb_valueone = pb_valueone
        self.pb_valuetwo = pb_valuetwo
        self.pb_valuethree = pb_valuethree
        self.memo = memo
        self.created_at = created_at
        self.updated_at = updated_at
    
    @classmethod
    def create(cls, stock_master_id, pb_valueone=None, pb_valuetwo=None, pb_valuethree=None, memo=None):
        """
        创建新的PB记录
        """
        query = """
        INSERT INTO stock_pb 
        (stock_master_id, pb_valueone, pb_valuetwo, pb_valuethree, memo) 
        VALUES (%s, %s, %s, %s, %s)
        """
        params = (stock_master_id, pb_valueone, pb_valuetwo, pb_valuethree, memo)
        
        try:
            result = cls.execute_update(query, params)
            if result > 0:
                # 返回新创建的记录
                new_record = cls.get_by_stock_master_id(stock_master_id)
                return new_record
            return None
        except Exception:
            logger.exception('创建PB记录失败')
            return None
    
    @classmethod
    def get_by_stock_master_id(cls, stock_master_id):
        """
        根据主订单ID获取PB记录
        """
        query = "SELECT * FROM stock_pb WHERE stock_master_id = %s"
        result = cls.execute_query(query, (stock_master_id,))
        if result:
            record_data = result[0]
            return cls(
                id=record_data['id'],
                stock_master_id=record_data['stock_master_id'],
                pb_valueone=record_data['pb_valueone'],
                pb_valuetwo=record_data['pb_valuetwo'],
                pb_valuethree=record_data['pb_valuethree'],
                memo=record_data['memo'],
                created_at=record_data['created_at'],
                updated_at=record_data['updated_at']
            )
        return None
    
    @classmethod
    def get_by_stock_code(cls, stock_code):
        """
        根据股票代码获取PB记录
        """
        query = """
        SELECT spb.* FROM stock_pb spb
        JOIN stock_master sm ON spb.stock_master_id = sm.id
        WHERE sm.stock_code = %s
        """
        result = cls.execute_query(query, (stock_code,))
        if result:
            record_data = result[0]
            return cls(
                id=record_data['id'],
                stock_master_id=record_data['stock_master_id'],
                pb_valueone=record_data['pb_valueone'],
                pb_valuetwo=record_data['pb_valuetwo'],
                pb_valuethree=record_data['pb_valuethree'],
                memo=record_data['memo'],
                created_at=record_data['created_at'],
                updated_at=record_data['updated_at']
            )
        return None
    
    @classmethod
    def update_by_stock_master_id(cls, stock_master_id, **kwargs):
        """
        根据主订单ID更新PB记录
        """
        # 构建动态更新语句
        fields = []
        params = []
        for key, value in kwargs.items():
            if hasattr(cls(), key) and key != 'id' and key != 'stock_master_id':
                fields.append(f"{key} = %s")
                params.append(value)
        
        if not fields:
            return False
        
        params.append(stock_master_id)
        query = f"UPDATE stock_pb SET {', '.join(fields)} WHERE stock_master_id = %s"
        
        try:
            result = cls.execute_update(query, tuple(params))
            return result > 0
        except Exception:
            logger.exception('更新PB记录失败')
            return False
    
    @classmethod
    def delete_by_stock_master_id(cls, stock_master_id):
        """
        根据主订单ID删除PB记录
        """
        query = "DELETE FROM stock_pb WHERE stock_master_id = %s"
        return cls.execute_update(query, (stock_master_id,)) > 0