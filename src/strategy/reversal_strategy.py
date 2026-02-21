"""
업비트 수수료 및 슬리피지를 고려한 1분 봉 역추세 매매 전략.
기술적 반등 폭 상향 및 투매 필터 강화.
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ReversalStrategy(BaseStrategy):
    """수수료 최적화 역추세 전략."""

    def __init__(self, rsi_threshold: int = 20, bb_std: float = 3.0, stop_loss_pct: float = 0.008, take_profit_pct: float = 0.015):
        # BB 표준편차를 3.0으로 높여 정말 극단적인 폭락만 잡음 (승률 상승)
        # 익절 1.5%, 손절 0.8%로 상향
        self.rsi_threshold = rsi_threshold
        self.bb_std = bb_std
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        self.bb_lower = None
        self.bb_middle = None
        self.rsi = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
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
        self.rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        if self.bb_lower is None or self.rsi is None:
            return False
        current_price = current_data['last']
        
        # 밴드 하단 이탈 + RSI 20 이하 (투매 상황)
        if current_price <= self.bb_lower and self.rsi <= self.rsi_threshold:
            # AI의 슬리피지 예측이 0.5% 넘으면 역추세는 위험함
            if ai_pred and ai_pred.get('estimated_slippage', 0) > 0.005:
                return False
            return True
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        pnl = (current_price - entry_price) / entry_price
        
        # 1. 고정 익절 1.5% 
        if pnl >= self.take_profit_pct:
            return "REVERSAL_TP"
        # 2. 고정 손절 0.8%
        if pnl <= -self.stop_loss_pct:
            return "REVERSAL_SL"
        # 3. 기술적 청산: BB 중심선(MA20) 도달 시 수익이 0.2% 이상이라면 확정 수익 청산
        if self.bb_middle and current_price >= self.bb_middle and pnl > 0.002:
            return "REVERSAL_BB_EXIT"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
