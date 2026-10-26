"""
K线数据模型
用于存储和管理股票的K线数据及均线信息
"""
from models.base import BaseModel
import pysnowball as ball
import pandas as pd
from config import XueqiuToken
from utils.snowball_errors import describe as describe_xueqiu_error
from utils.snowball_errors import parse_xueqiu_error
import logging

logger = logging.getLogger(__name__)

class StockKline(BaseModel):
    table_name = 'stock_kline'
    
    def __init__(self, id=None, stock_master_id=None, stock_code=None, trade_date=None,
                 open_price=None, high_price=None, low_price=None, close_price=None,
                 volume=None, ma5=None, ma10=None, ma30=None, signal_type=None,
                 created_at=None):
        self.id = id
        self.stock_master_id = stock_master_id
        self.stock_code = stock_code
        self.trade_date = trade_date
        self.open_price = open_price
        self.high_price = high_price
        self.low_price = low_price
        self.close_price = close_price
        self.volume = volume
        self.ma5 = ma5
        self.ma10 = ma10
        self.ma30 = ma30
        self.signal_type = signal_type  # 'golden_cross', 'death_cross', 'normal'
        self.created_at = created_at
    
    @classmethod
    def get_kline_data_from_snowball(cls, stock_code, days=40):
        """
        从雪球获取K线数据
        
        参数:
            stock_code: 股票代码，如 'SZ002027'
            days: 获取的天数，建议至少40天以计算30日均线
        
        返回:
            DataFrame包含K线数据和均线
        """
        token = XueqiuToken.TOKEN
        if not token:
            logger.error('未配置雪球 Token（环境变量 XUEQIU_TOKEN），无法获取K线 %s', stock_code)
            return None
        try:
            ball.set_token(token)
            kline_data = ball.kline(stock_code, 'day', days)
            
            # 提取数据
            data = kline_data['data']
            columns = data['column']
            items = data['item']
            
            # 转换为DataFrame
            df = pd.DataFrame(items, columns=columns)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # 计算均线（基于收盘价close）
            df['ma5'] = df['close'].rolling(window=5).mean()
            df['ma10'] = df['close'].rolling(window=10).mean()
            df['ma30'] = df['close'].rolling(window=30).mean()
            
            return df
        except Exception as exc:
            # 雪球业务错误（Token 失效/限流/代码不存在）只提示，不打堆栈
            code, description = parse_xueqiu_error(exc)
            if code is None:
                logger.exception('从雪球获取K线数据失败 %s', stock_code)
            else:
                logger.warning('%s stock=%s', describe_xueqiu_error(code, description), stock_code)
            return None
    
    @classmethod
    def check_signal(cls, ma5, ma10, ma30):
        """
        判断金叉死叉信号
        
        参数:
            ma5: 5日均线
            ma10: 10日均线
            ma30: 30日均线
        
        返回:
            'golden_cross': 金叉 (MA5上穿MA30)
            'death_cross': 死叉 (MA5下穿MA30)
            'normal': 震荡
        """
        if ma5 is None or ma30 is None or pd.isna(ma5) or pd.isna(ma30):
            return 'normal'
        
        # 金叉：MA5 > MA30 * 1.03 (MA5明显高于MA30)
        if ma5 > ma30 * 1.03:
            return 'golden_cross'
        # 死叉：MA5 < MA30 * 0.97 (MA5明显低于MA30)
        elif ma5 < ma30 * 0.97:
            return 'death_cross'
        else:
            return 'normal'
    
    @classmethod
    def save_kline_data(cls, stock_master_id, stock_code, kline_df):
        """
        保存K线数据到数据库
        
        参数:
            stock_master_id: 股票主表ID
            stock_code: 股票代码
            kline_df: K线数据DataFrame
        
        返回:
            成功保存的记录数
        """
        if kline_df is None or len(kline_df) == 0:
            return 0
        
        saved_count = 0
        try:
            for _, row in kline_df.iterrows():
                # 检查是否已存在该日期的数据
                exist_query = """
                SELECT id FROM stock_kline 
                WHERE stock_master_id = %s AND trade_date = %s
                """
                exist_result = cls.execute_query(exist_query, (stock_master_id, row['timestamp']))
                
                # 判断信号类型
                signal_type = cls.check_signal(row['ma5'], row['ma10'], row['ma30'])
                
                if exist_result:
                    # 更新已有记录
                    update_query = """
                    UPDATE stock_kline 
                    SET open_price = %s, high_price = %s, low_price = %s, 
                        close_price = %s, volume = %s, ma5 = %s, ma10 = %s, 
                        ma30 = %s, signal_type = %s
                    WHERE stock_master_id = %s AND trade_date = %s
                    """
                    params = (
                        float(row['open']) if pd.notna(row['open']) else None,
                        float(row['high']) if pd.notna(row['high']) else None,
                        float(row['low']) if pd.notna(row['low']) else None,
                        float(row['close']) if pd.notna(row['close']) else None,
                        float(row['volume']) if pd.notna(row['volume']) else None,
                        float(row['ma5']) if pd.notna(row['ma5']) else None,
                        float(row['ma10']) if pd.notna(row['ma10']) else None,
                        float(row['ma30']) if pd.notna(row['ma30']) else None,
                        signal_type,
                        stock_master_id,
                        row['timestamp']
                    )
                    cls.execute_update(update_query, params)
                else:
                    # 插入新记录
                    insert_query = """
                    INSERT INTO stock_kline 
                    (stock_master_id, stock_code, trade_date, open_price, high_price, 
                     low_price, close_price, volume, ma5, ma10, ma30, signal_type)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    params = (
                        stock_master_id,
                        stock_code,
                        row['timestamp'],
                        float(row['open']) if pd.notna(row['open']) else None,
                        float(row['high']) if pd.notna(row['high']) else None,
                        float(row['low']) if pd.notna(row['low']) else None,
                        float(row['close']) if pd.notna(row['close']) else None,
                        float(row['volume']) if pd.notna(row['volume']) else None,
                        float(row['ma5']) if pd.notna(row['ma5']) else None,
                        float(row['ma10']) if pd.notna(row['ma10']) else None,
                        float(row['ma30']) if pd.notna(row['ma30']) else None,
                        signal_type
                    )
                    cls.execute_update(insert_query, params)
                
                saved_count += 1
            
            logger.info(f"成功保存 {saved_count} 条K线数据，股票代码: {stock_code}")
            return saved_count
        except Exception:
            logger.exception('保存K线数据失败 %s', stock_code)
            return 0
    
    @classmethod
    def get_latest_kline(cls, stock_master_id):
        """
        获取最新的K线数据（包含信号类型）
        
        参数:
            stock_master_id: 股票主表ID
        
        返回:
            最新一条K线记录字典
        """
        query = """
        SELECT * FROM stock_kline 
        WHERE stock_master_id = %s 
        ORDER BY trade_date DESC 
        LIMIT 1
        """
        result = cls.execute_query(query, (stock_master_id,))
        return result[0] if result else None
    
    @classmethod
    def get_low_52w_batch(cls, stock_master_ids):
        """
        批量获取多个订单近 52 周（按自然日 365 天近似）的最低价。

        一次查询取回本页全部订单，避免逐行查库（列表已有逐行取信号的 N+1，不再叠加）。

        参数:
            stock_master_ids: 订单主表 ID 列表

        返回:
            {stock_master_id: 最低价}；无 K 线数据的订单不在结果中；查询失败返回空 dict
        """
        if not stock_master_ids:
            return {}

        # 占位符只由元素个数生成，值一律参数化传入
        placeholders = ', '.join(['%s'] * len(stock_master_ids))
        query = f"""
        SELECT stock_master_id, MIN(low_price) AS low_52w
        FROM stock_kline
        WHERE stock_master_id IN ({placeholders})
          AND trade_date >= DATE_SUB(CURDATE(), INTERVAL 365 DAY)
          AND low_price IS NOT NULL
        GROUP BY stock_master_id
        """
        try:
            rows = cls.execute_query(query, tuple(stock_master_ids))
        except Exception:
            logger.exception('查询52周最低价失败: ids=%s', stock_master_ids)
            return {}
        return {row['stock_master_id']: row['low_52w'] for row in rows}

    @classmethod
    def get_recent_closes(cls, stock_master_id, limit=40):
        """
        取个股最近若干交易日的收盘价，**升序**（旧 → 新）。

        给 006 指标监控算 5 / 20 日涨跌幅用；刻意返回 Python 列表而不是 DataFrame，
        让 `utils/indicator_rules.n_day_return` 保持纯函数、可脱离 pandas 单测。

        :return: list[float]；无数据或查询失败返回 []
        """
        query = """
        SELECT close_price FROM stock_kline
        WHERE stock_master_id = %s AND close_price IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT %s
        """
        try:
            rows = cls.execute_query(query, (stock_master_id, limit))
        except Exception:
            logger.exception('查询收盘价序列失败 id=%s', stock_master_id)
            return []

        closes = []
        for row in rows:
            try:
                closes.append(float(row['close_price']))
            except (TypeError, ValueError):
                continue
        closes.reverse()
        return closes

    @classmethod
    def get_latest_signal(cls, stock_master_id):
        """
        获取最新的信号类型
        
        参数:
            stock_master_id: 股票主表ID
        
        返回:
            信号类型字符串: 'golden_cross', 'death_cross', 'normal'
        """
        latest = cls.get_latest_kline(stock_master_id)
        if latest:
            return latest.get('signal_type', 'normal')
        return 'normal'
    
    @classmethod
    def delete_by_stock_master_id(cls, stock_master_id):
        """
        删除指定股票的所有K线数据
        
        参数:
            stock_master_id: 股票主表ID
        
        返回:
            删除的记录数
        """
        query = "DELETE FROM stock_kline WHERE stock_master_id = %s"
        return cls.execute_update(query, (stock_master_id,))
