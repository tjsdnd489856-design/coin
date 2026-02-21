"""
AI 적응형 파라미터(TradeParams)를 수용하는 스캘핑 전략.
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.schema import TradeParams
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """AI가 주는 파라미터로 실시간 튜닝되는 스캘핑 전략."""

    def __init__(self, k: float = 0.6):
        self.k = k
        self.stop_loss_pct = 0.005
        self.take_profit_pct = 0.012
        self.volume_multiplier = 2.0 
        self.fee_rate = 0.0005
        
        # 지표
        self.target_price = None
        self.ma_20 = None
        self.rsi = None
        self.avg_volume = None
        self.bb_width = None
        self.atr = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        if not ohlcv_list or len(ohlcv_list) < 30: return
        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        prev_candle = df.iloc[-2]
        self.prev_range = prev_candle['high'] - prev_candle['low']
        self.current_open = df.iloc[-1]['open']
        self.ma_20 = df['close'].rolling(20).mean().iloc[-1]
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        self.rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
        
        # 볼린저 밴드 너비
        ma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        self.bb_width = (((ma20 + 2*std20) - (ma20 - 2*std20)) / ma20).iloc[-1]
        
        self.avg_volume = df['volume'].iloc[-21:-1].mean()

        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        self.atr = tr.rolling(14).mean().iloc[-1]

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """AI가 제안한 파라미터(params)를 우선 적용."""
        if self.ma_20 is None: return False
        
        params = ai_pred.get('suggested_params', {}) if ai_pred else {}
        k = params.get('k', self.k)
        vol_mult = params.get('volume_multiplier', self.volume_multiplier)
        
        target_price = self.current_open + (self.prev_range * k)
        current_price = current_data['last']
        current_vol = current_data.get('baseVolume', 0)
        
        cond_price = current_price >= target_price and current_price > self.ma_20
        cond_vol = self.avg_volume and current_vol > (self.avg_volume * vol_mult)
        cond_squeeze = self.bb_width < 0.03 # 3% 미만 응축 시
        
        if cond_price and cond_vol and cond_squeeze:
            if self.atr:
                # 스캘핑은 짧게 먹으므로 ATR의 1.0배/0.5배 수준 설정
                self.take_profit_pct = max(0.01, self.atr / current_price)
                self.stop_loss_pct = max(0.005, (self.atr * 0.5) / current_price)
            
            logger.info(f"✨ AI 스캘핑 신호 (k={k:.2f}, TP={self.take_profit_pct:.2%})")
            return True
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        raw_pnl = (current_price - entry_price) / entry_price
        net_pnl = raw_pnl - (self.fee_rate * 2)

        if net_pnl >= self.take_profit_pct: return "AI_TP"
        if net_pnl <= -self.stop_loss_pct: return "AI_SL"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
