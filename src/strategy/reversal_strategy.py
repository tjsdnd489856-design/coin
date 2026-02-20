"""
역추세 매매(Mean Reversion) 전략 구현.
볼린저 밴드와 RSI 과매도를 활용하여 반등 지점을 공략.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ReversalStrategy(BaseStrategy):
    """과매도 구간 반등을 노리는 역추세 전략."""

    def __init__(self, rsi_threshold: int = 30, bb_std: float = 2.0, stop_loss_pct: float = 0.03, take_profit_pct: float = 0.05):
        self.rsi_threshold = rsi_threshold   # RSI 30 이하일 때 주목
        self.bb_std = bb_std                 # 볼린저 밴드 표준편차
        self.stop_loss_pct = stop_loss_pct   # 3% 손절
        self.take_profit_pct = take_profit_pct # 5% 익절
        
        # 지표 데이터 저장소
        self.bb_lower = None
        self.bb_middle = None
        self.rsi = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        """볼린저 밴드 및 RSI 지표 갱신."""
        if not ohlcv_list or len(ohlcv_list) < 20:
            return

        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 1. 볼린저 밴드 계산 (20일 기준)
        ma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        
        self.bb_middle = ma20.iloc[-1]
        self.bb_lower = self.bb_middle - (self.bb_std * std20.iloc[-1])
        
        # 2. RSI 계산 (14일 기준)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        self.rsi = 100 - (100 / (1 + rs)).iloc[-1]
        
        logger.info(f"[역추세] 지표 갱신 | RSI: {self.rsi:.2f} | BB_Lower: {self.bb_lower:,.0f}")

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """역추세 매수 신호 확인 (과매도 + 밴드 하단 이탈)."""
        if self.bb_lower is None or self.rsi is None:
            return False
            
        current_price = current_data['last']
        
        # 필터 1: 가격이 볼린저 밴드 하단보다 낮거나 근접 (과매도 투매 상황)
        is_price_low = current_price <= self.bb_lower * 1.01 # 밴드 하단 1% 이내 근접 포함
        
        # 필터 2: RSI가 과매도 임계치 이하
        is_oversold = self.rsi <= self.rsi_threshold
        
        # 필터 3: AI 슬리피지 조건
        ai_signal = True
        if ai_pred and ai_pred.get('estimated_slippage', 0) > 0.007: # 역추세는 변동성이 크므로 조금 더 여유를 둠
            ai_signal = False
            
        if is_price_low and is_oversold and ai_signal:
            logger.info(f"🔥 역추세 매수 신호 포착! (RSI: {self.rsi:.2f}, 가격: {current_price:,.0f})")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        """손절/익절 신호 확인."""
        profit_loss_ratio = (current_price - entry_price) / entry_price
        
        # 역추세는 반등 시 짧게 먹고 나오는 것이 핵심
        if profit_loss_ratio <= -self.stop_loss_pct:
            return "STOP_LOSS_REVERSAL"
        if profit_loss_ratio >= self.take_profit_pct:
            return "TAKE_PROFIT_REVERSAL"
            
        # 추가: 가격이 볼린저 밴드 중심(MA20)에 도달하면 이익 실현 (강력 추천)
        if current_price >= self.bb_middle:
            return "TAKE_PROFIT_BB_MIDDLE"
            
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        """가용 자산 투입."""
        return balance / price
