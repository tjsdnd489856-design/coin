"""
AI 적응형 파라미터를 수용하는 고승률 역추세 매매 전략.
RSI Hook 및 동적 임계값을 통한 정교한 반등 타점 포착.
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ReversalStrategy(BaseStrategy):
    """AI가 주는 파라미터로 실시간 튜닝되는 역추세 전략."""

    def __init__(self, rsi_threshold: int = 25, bb_std: float = 2.5):
        self.rsi_threshold = rsi_threshold
        self.bb_std = bb_std
        self.stop_loss_pct = 0.007
        self.take_profit_pct = 0.015
        
        self.bb_lower = None
        self.bb_middle = None
        self.rsi = None
        self.prev_rsi = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        if not ohlcv_list or len(ohlcv_list) < 30: return
        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        ma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        self.bb_middle = ma20.iloc[-1]
        self.bb_lower = self.bb_middle - (self.bb_std * std20.iloc[-1])
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi_series = 100 - (100 / (1 + (gain / loss)))
        self.prev_rsi = rsi_series.iloc[-2]
        self.rsi = rsi_series.iloc[-1]

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """AI가 제안한 rsi_buy_threshold를 적용하여 반등 확인."""
        if self.bb_lower is None or self.rsi is None: return False
        
        # [핵심] AI 제안 파라미터 적용
        params = ai_pred.get('suggested_params', {}) if ai_pred else {}
        rsi_threshold = params.get('rsi_buy_threshold', self.rsi_threshold)
        
        current_price = current_data['last']
        
        # 1. 가격 조건 (밴드 하단 이탈)
        is_price_low = current_price <= self.bb_lower * 1.002
        # 2. RSI 반등 조건 (AI가 정해준 threshold 이하에서 상승 반전)
        is_rsi_hook = self.rsi <= rsi_threshold and self.rsi > self.prev_rsi
        
        if is_price_low and is_rsi_hook:
            logger.info(f"🆘 AI 역추세 신호 (RSI_Limit={rsi_threshold}, Current={self.rsi:.1f})")
            return True
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        pnl = (current_price - entry_price) / entry_price
        if pnl >= self.take_profit_pct: return "REV_TP"
        if pnl <= -self.stop_loss_pct: return "REV_SL"
        if pnl > 0.005 and pnl < 0.002: return "REV_BE" # 본절 방어
        if self.bb_middle and current_price >= self.bb_middle and pnl > 0.002:
            return "REV_BB_EXIT"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
