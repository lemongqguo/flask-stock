"""
仓库表模型
"""
import logging

from models.base import BaseModel
import pymysql

logger = logging.getLogger(__name__)

class StockWarehouse(BaseModel):
    table_name = 'stock_warehouse'
    
    def __init__(self, id=None, stock_master_id=None, dividend_yield=None, current_price=None, 
                 sell_rate=None, stock_valueone=None, stock_valuetwo=None, stock_valuethree=None, 
                 memo=None, created_at=None, updated_at=None):
        self.id = id
        self.stock_master_id = stock_master_id
        self.dividend_yield = dividend_yield
        self.current_price = current_price
        self.sell_rate = sell_rate
        self.stock_valueone = stock_valueone
        self.stock_valuetwo = stock_valuetwo
        self.stock_valuethree = stock_valuethree
        self.memo = memo
        self.created_at = created_at
        self.updated_at = updated_at
    
    @classmethod
    def create(cls, stock_master_id, dividend_yield=None, current_price=None, sell_rate=None, 
               stock_valueone=None, stock_valuetwo=None, stock_valuethree=None, memo=None):
        """
        创建新的仓库记录
        """
        query = """
        INSERT INTO stock_warehouse 
        (stock_master_id, dividend_yield, current_price, sell_rate, 
         stock_valueone, stock_valuetwo, stock_valuethree, memo) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (stock_master_id, dividend_yield, current_price, sell_rate, 
                  stock_valueone, stock_valuetwo, stock_valuethree, memo)
        
        try:
            result = cls.execute_update(query, params)
            if result > 0:
                # 返回新创建的记录
                new_record = cls.get_by_stock_master_id(stock_master_id)
                return new_record
            return None
        except Exception:
            logger.exception('创建仓库记录失败')
            return None
    
    @classmethod
    def get_by_stock_master_id(cls, stock_master_id):
        """
        根据主订单ID获取仓库记录
        """
        query = "SELECT * FROM stock_warehouse WHERE stock_master_id = %s"
        result = cls.execute_query(query, (stock_master_id,))
        if result:
            record_data = result[0]
            return cls(
                id=record_data['id'],
                stock_master_id=record_data['stock_master_id'],
                dividend_yield=record_data['dividend_yield'],
                current_price=record_data['current_price'],
                sell_rate=record_data['sell_rate'],
                stock_valueone=record_data['stock_valueone'],
                stock_valuetwo=record_data['stock_valuetwo'],
                stock_valuethree=record_data['stock_valuethree'],
                memo=record_data['memo'],
                created_at=record_data['created_at'],
                updated_at=record_data['updated_at']
            )
        return None
    
    @classmethod
    def get_by_stock_code(cls, stock_code):
        """
        根据股票代码获取仓库记录
        """
        query = """
        SELECT sw.* FROM stock_warehouse sw
        JOIN stock_master sm ON sw.stock_master_id = sm.id
        WHERE sm.stock_code = %s
        """
        result = cls.execute_query(query, (stock_code,))
        if result:
            record_data = result[0]
            return cls(
                id=record_data['id'],
                stock_master_id=record_data['stock_master_id'],
                dividend_yield=record_data['dividend_yield'],
                current_price=record_data['current_price'],
                sell_rate=record_data['sell_rate'],
                stock_valueone=record_data['stock_valueone'],
                stock_valuetwo=record_data['stock_valuetwo'],
                stock_valuethree=record_data['stock_valuethree'],
                memo=record_data['memo'],
                created_at=record_data['created_at'],
                updated_at=record_data['updated_at']
            )
        return None
    
    @classmethod
    def update_by_stock_master_id(cls, stock_master_id, **kwargs):
        """
        根据主订单ID更新仓库记录
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
        query = f"UPDATE stock_warehouse SET {', '.join(fields)} WHERE stock_master_id = %s"
        
        try:
            result = cls.execute_update(query, tuple(params))
            return result > 0
        except Exception:
            logger.exception('更新仓库记录失败')
            return False
    
    @classmethod
    def update_by_stock_code(cls, stock_code, **kwargs):
        """
        根据股票代码更新仓库记录
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
        
        params.append(stock_code)
        query = """
        UPDATE stock_warehouse sw
        JOIN stock_master sm ON sw.stock_master_id = sm.id
        SET {} WHERE sm.stock_code = %s
        """.format(', '.join(fields))
        
        try:
            result = cls.execute_update(query, tuple(params))
            return result > 0
        except Exception:
            logger.exception('更新仓库记录失败')
            return False
    
    @classmethod
    def delete_by_stock_master_id(cls, stock_master_id):
        """
        根据主订单ID删除仓库记录
        """
        query = "DELETE FROM stock_warehouse WHERE stock_master_id = %s"
        return cls.execute_update(query, (stock_master_id,)) > 0