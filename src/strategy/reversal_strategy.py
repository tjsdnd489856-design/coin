"""
고승률을 위한 반등 확인형 역추세 매매 전략.
투매 이후 거래량 실린 반등 타점을 정교하게 포착함.
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ReversalStrategy(BaseStrategy):
    """1분 봉 고승률 타겟 역추세 전략."""

    def __init__(self, rsi_threshold: int = 25, bb_std: float = 2.5):
        # 파라미터 최적화
        self.rsi_threshold = rsi_threshold
        self.bb_std = bb_std
        self.stop_loss_pct = 0.007  # 손절 0.7%
        self.take_profit_pct = 0.015 # 익절 1.5%
        
        self.bb_lower = None
        self.bb_middle = None
        self.rsi = None
        self.prev_rsi = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        if not ohlcv_list or len(ohlcv_list) < 30:
            return
        
        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 1. 볼린저 밴드
        ma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        self.bb_middle = ma20.iloc[-1]
        self.bb_lower = self.bb_middle - (self.bb_std * std20.iloc[-1])
        
        # 2. RSI 및 이전 값 (반등 확인용)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi_series = 100 - (100 / (1 + (gain / loss)))
        
        self.prev_rsi = rsi_series.iloc[-2]
        self.rsi = rsi_series.iloc[-1]

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """반등 확인형 매수 신호."""
        if self.bb_lower is None or self.rsi is None:
            return False
            
        current_price = current_data['last']
        
        # 필터 1: 가격이 밴드 하단 부근 (투매 발생)
        is_price_low = current_price <= self.bb_lower * 1.002
        
        # 필터 2: [핵심] RSI 훅(Hook)
        # RSI가 임계값보다 낮으면서, 동시에 '직전 봉보다 상승'하기 시작할 때 (반등 조짐)
        is_rsi_reversing = self.rsi <= self.rsi_threshold and self.rsi > self.prev_rsi
        
        if is_price_low and is_rsi_reversing:
            logger.info(f"🆘 역추세 반등 신호! RSI: {self.prev_rsi:.1f} -> {self.rsi:.1f}")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        pnl = (current_price - entry_price) / entry_price
        
        # 1. 고정 익절/손절
        if pnl >= self.take_profit_pct: return "REV_TP"
        if pnl <= -self.stop_loss_pct: return "REV_SL"
        
        # 2. 본절 방어: 0.5% 수익 도달 후 0.2%까지 내려오면 익절
        if pnl > 0.005 and pnl < 0.002: return "REV_BREAKEVEN"
        
        # 3. 기술적 청산: BB 중심선
        if self.bb_middle and current_price >= self.bb_middle and pnl > 0.002:
            return "REV_BB_EXIT"
            
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
