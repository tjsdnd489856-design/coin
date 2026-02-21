"""
15분 봉 기반의 역추세 매매(Mean Reversion) 전략.
과매도 투매 구간에서의 짧은 반등을 타겟으로 함.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ReversalStrategy(BaseStrategy):
    """15분 봉 최적화 역추세 전략."""

    def __init__(self, rsi_threshold: int = 25, bb_std: float = 2.5, stop_loss_pct: float = 0.012, take_profit_pct: float = 0.02):
        # 15분 봉 기준: RSI 25 이하(강력 과매도), BB 표준편차 2.5(하단 이탈 엄격화)
        self.rsi_threshold = rsi_threshold
        self.bb_std = bb_std
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        # 지표 데이터 저장소
        self.bb_lower = None
        self.bb_middle = None
        self.rsi = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        """볼린저 밴드 및 RSI 지표 갱신."""
        if not ohlcv_list or len(ohlcv_list) < 30:
            return

        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 1. 볼린저 밴드 (20기간)
        ma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        
        self.bb_middle = ma20.iloc[-1]
        self.bb_lower = self.bb_middle - (self.bb_std * std20.iloc[-1])
        
        # 2. RSI (14기간)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        self.rsi = 100 - (100 / (1 + rs)).iloc[-1]
        
        logger.info(f"[역추세] 지표 갱신 | RSI: {self.rsi:.2f} | BB_Lower: {self.bb_lower:,.0f}")

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """강화된 역추세 매수 신호 확인."""
        if self.bb_lower is None or self.rsi is None:
            return False
            
        current_price = current_data['last']
        
        # 필터 1: 가격이 볼린저 밴드 하단 이탈 또는 강력 근접
        is_price_low = current_price <= self.bb_lower * 1.002 # 0.2% 근접까지 인정
        
        # 필터 2: RSI가 25 이하 (극심한 과매도)
        is_oversold = self.rsi <= self.rsi_threshold
        
        # 필터 3: AI 슬리피지 및 필터 (생략 가능하나 구조 유지)
        ai_signal = True
        if ai_pred and ai_pred.get('estimated_slippage', 0) > 0.005:
            ai_signal = False
            
        if is_price_low and is_oversold and ai_signal:
            logger.info(f"🔥 역추세 매수 기회 포착! (RSI: {self.rsi:.2f}, 현재가: {current_price:,.0f})")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        """역추세 탈출 전략 (익절/손절/중심선 도달)."""
        profit_loss_ratio = (current_price - entry_price) / entry_price
        
        # 1. 고정 손절 (1.2%)
        if profit_loss_ratio <= -self.stop_loss_pct:
            return "REVERSAL_STOP_LOSS"
            
        # 2. 고정 익절 (2.0%)
        if profit_loss_ratio >= self.take_profit_pct:
            return "REVERSAL_TAKE_PROFIT"
            
        # 3. 기술적 익절: 가격이 볼린저 밴드 중심(20평균선)에 도달하면 즉시 수익 실현
        if self.bb_middle and current_price >= self.bb_middle:
            return "REVERSAL_BB_MIDDLE_EXIT"
            
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        """가용 자산 투입."""
        return balance / price
