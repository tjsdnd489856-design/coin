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
        self.fee_rate = 0.0005 # 업비트 0.05%
        
        self.bb_lower = None
        self.bb_middle = None
        self.rsi = None
        self.prev_rsi = None
        self.atr = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        if not ohlcv_list or len(ohlcv_list) < 30: return
        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 볼린저 밴드
        ma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        self.bb_middle = ma20.iloc[-1]
        self.bb_lower = self.bb_middle - (self.bb_std * std20.iloc[-1])
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi_series = 100 - (100 / (1 + (gain / loss)))
        self.prev_rsi = rsi_series.iloc[-2]
        self.rsi = rsi_series.iloc[-1]

        # ATR (시장 변동성)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        self.atr = tr.rolling(14).mean().iloc[-1]

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """AI가 제안한 rsi_buy_threshold를 적용하여 반등 확인."""
        if self.bb_lower is None or self.rsi is None: return False
        
        params = ai_pred.get('suggested_params', {}) if ai_pred else {}
        rsi_threshold = params.get('rsi_buy_threshold', self.rsi_threshold)
        
        current_price = current_data['last']
        is_price_low = current_price <= self.bb_lower * 1.002
        is_rsi_hook = self.rsi <= rsi_threshold and self.rsi > self.prev_rsi
        
        if is_price_low and is_rsi_hook:
            # ATR 기반 동적 익절/손절 설정 (변동성의 1.5배/0.7배 등)
            if self.atr:
                self.take_profit_pct = max(0.012, (self.atr * 1.5) / current_price)
                self.stop_loss_pct = max(0.005, (self.atr * 0.8) / current_price)
            
            logger.info(f"🆘 AI 역추세 신호 (RSI={self.rsi:.1f}, TP={self.take_profit_pct:.2%})")
            return True
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        # 수수료를 고려한 순수익률 계산 (왕복 0.1%)
        raw_pnl = (current_price - entry_price) / entry_price
        net_pnl = raw_pnl - (self.fee_rate * 2)

        if net_pnl >= self.take_profit_pct: return "REV_TP"
        if net_pnl <= -self.stop_loss_pct: return "REV_SL"
        
        # 본절가 방어: 0.6% 이상 수익 후 0.3% 하락 시 탈출
        if net_pnl >= 0.006 and net_pnl <= 0.003:
            return "REV_BE"
            
        if self.bb_middle and current_price >= self.bb_middle and net_pnl > 0.002:
            return "REV_BB_EXIT"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
