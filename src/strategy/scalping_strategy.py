"""
변동성 돌파 기반의 단타 전략 구현.
리스크 관리(손절/익절) 로직 추가.
"""
from typing import Dict, Any, Optional
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """변동성 돌파 + 리스크 관리 단타 전략."""

    def __init__(self, k: float = 0.5, stop_loss_pct: float = 0.02, take_profit_pct: float = 0.04):
        self.k = k
        self.stop_loss_pct = stop_loss_pct    # 2% 손절
        self.take_profit_pct = take_profit_pct # 4% 익절
        self.target_price = None

    async def update_target_price(self, ohlcv: Dict[str, Any]):
        """목표가 계산."""
        prev_range = ohlcv['high'] - ohlcv['low']
        self.target_price = ohlcv['close'] + (prev_range * self.k)
        logger.info(f"목표가 설정 완료: {self.target_price}")

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """매수 신호 확인."""
        if not self.target_price:
            return False
        current_price = current_data['last']
        price_signal = current_price >= self.target_price
        
        ai_signal = True
        if ai_pred and ai_pred.get('estimated_slippage', 0) > 0.005:
            ai_signal = False
            
        return price_signal and ai_signal

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        """손절/익절 신호 확인."""
        profit_loss_ratio = (current_price - entry_price) / entry_price
        
        if profit_loss_ratio <= -self.stop_loss_pct:
            return "STOP_LOSS"
        if profit_loss_ratio >= self.take_profit_pct:
            return "TAKE_PROFIT"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        """자산의 20%를 투입하도록 설정."""
        invest_ratio = 0.2
        return (balance * invest_ratio) / price
