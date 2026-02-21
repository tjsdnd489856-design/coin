"""
1분 봉 최적화 역추세 매매 전략.
극단적 과매도 구간(V자 반등)을 타겟으로 함.
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ReversalStrategy(BaseStrategy):
    """1분 봉 스캔용 역추세 전략."""

    def __init__(self, rsi_threshold: int = 20, bb_std: float = 2.5, stop_loss_pct: float = 0.005, take_profit_pct: float = 0.008):
        # 1분 봉 기준: RSI 20(극심한 투매), 익절 0.8%, 손절 0.5%
        self.rsi_threshold = rsi_threshold
        self.bb_std = bb_std
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        self.bb_lower = None
        self.bb_middle = None
        self.rsi = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        """지표 갱신."""
        if not ohlcv_list or len(ohlcv_list) < 30:
            return

        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        ma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        
        self.bb_middle = ma20.iloc[-1]
        self.bb_lower = self.bb_middle - (self.bb_std * std20.iloc[-1])
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        self.rsi = 100 - (100 / (1 + rs)).iloc[-1]

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """역추세 신호 확인."""
        if self.bb_lower is None or self.rsi is None:
            return False
            
        current_price = current_data['last']
        
        # 필터 1: 가격이 볼린저 밴드 하단을 확실히 뚫었을 때
        is_price_low = current_price <= self.bb_lower
        
        # 필터 2: RSI가 20 이하 (강력한 과매도)
        is_oversold = self.rsi <= self.rsi_threshold
            
        if is_price_low and is_oversold:
            logger.info(f"🆘 1분봉 투매 구간 포착! (RSI: {self.rsi:.2f})")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        """탈출 전략."""
        profit_loss_ratio = (current_price - entry_price) / entry_price
        
        if profit_loss_ratio <= -self.stop_loss_pct:
            return "1M_REVERSAL_SL"
        if profit_loss_ratio >= self.take_profit_pct:
            return "1M_REVERSAL_TP"
        if self.bb_middle and current_price >= self.bb_middle:
            return "1M_REVERSAL_BB_EXIT"
            
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
