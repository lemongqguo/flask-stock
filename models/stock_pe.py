"""
PE表模型
"""
import logging

from models.base import BaseModel
import pymysql

logger = logging.getLogger(__name__)

class StockPe(BaseModel):
    table_name = 'stock_pe'
    
    def __init__(self, id=None, stock_master_id=None, pe_valueone=None, pe_valuetwo=None, 
                 pe_valuethree=None, memo=None, created_at=None, updated_at=None):
        self.id = id
        self.stock_master_id = stock_master_id
        self.pe_valueone = pe_valueone
        self.pe_valuetwo = pe_valuetwo
        self.pe_valuethree = pe_valuethree
        self.memo = memo
        self.created_at = created_at
        self.updated_at = updated_at
    
    @classmethod
    def create(cls, stock_master_id, pe_valueone=None, pe_valuetwo=None, pe_valuethree=None, memo=None):
        """
        创建新的PE记录
        """
        query = """
        INSERT INTO stock_pe 
        (stock_master_id, pe_valueone, pe_valuetwo, pe_valuethree, memo) 
        VALUES (%s, %s, %s, %s, %s)
        """
        params = (stock_master_id, pe_valueone, pe_valuetwo, pe_valuethree, memo)
        
        try:
            result = cls.execute_update(query, params)
            if result > 0:
                # 返回新创建的记录
                new_record = cls.get_by_stock_master_id(stock_master_id)
                return new_record
            return None
        except Exception:
            logger.exception('创建PE记录失败')
            return None
    
    @classmethod
    def get_by_stock_master_id(cls, stock_master_id):
        """
        根据主订单ID获取PE记录
        """
        query = "SELECT * FROM stock_pe WHERE stock_master_id = %s"
        result = cls.execute_query(query, (stock_master_id,))
        if result:
            record_data = result[0]
            return cls(
                id=record_data['id'],
                stock_master_id=record_data['stock_master_id'],
                pe_valueone=record_data['pe_valueone'],
                pe_valuetwo=record_data['pe_valuetwo'],
                pe_valuethree=record_data['pe_valuethree'],
                memo=record_data['memo'],
                created_at=record_data['created_at'],
                updated_at=record_data['updated_at']
            )
        return None
    
    @classmethod
    def get_by_stock_code(cls, stock_code):
        """
        根据股票代码获取PE记录
        """
        query = """
        SELECT sp.* FROM stock_pe sp
        JOIN stock_master sm ON sp.stock_master_id = sm.id
        WHERE sm.stock_code = %s
        """
        result = cls.execute_query(query, (stock_code,))
        if result:
            record_data = result[0]
            return cls(
                id=record_data['id'],
                stock_master_id=record_data['stock_master_id'],
                pe_valueone=record_data['pe_valueone'],
                pe_valuetwo=record_data['pe_valuetwo'],
                pe_valuethree=record_data['pe_valuethree'],
                memo=record_data['memo'],
                created_at=record_data['created_at'],
                updated_at=record_data['updated_at']
            )
        return None
    
    @classmethod
    def update_by_stock_master_id(cls, stock_master_id, **kwargs):
        """
        根据主订单ID更新PE记录
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
        query = f"UPDATE stock_pe SET {', '.join(fields)} WHERE stock_master_id = %s"
        
        try:
            result = cls.execute_update(query, tuple(params))
            return result > 0
        except Exception:
            logger.exception('更新PE记录失败')
            return False
    
    @classmethod
    def delete_by_stock_master_id(cls, stock_master_id):
        """
        根据主订单ID删除PE记录
        """
        query = "DELETE FROM stock_pe WHERE stock_master_id = %s"
        return cls.execute_update(query, (stock_master_id,)) > 0