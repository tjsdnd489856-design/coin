"""
업비트 수수료 및 슬리피지를 고려한 1분 봉 스캘핑 전략.
익절 폭 상향 및 본절가 방어 로직 포함.
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """수수료 최적화 스캘핑 전략."""

    def __init__(self, k: float = 0.6, stop_loss_pct: float = 0.005, take_profit_pct: float = 0.012):
        # k값을 0.6으로 올려 더 확실한 돌파만 잡음
        # 익절을 1.2%로 상향 (수수료 0.2% 제외 시 1.0% 실질 수익)
        # 손절을 0.5%로 상향
        self.k = k
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        self.target_price = None
        self.ma_20 = None
        self.rsi = None
        self.avg_volume = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        if not ohlcv_list or len(ohlcv_list) < 30:
            return
        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        prev_candle = df.iloc[-2]
        prev_range = prev_candle['high'] - prev_candle['low']
        self.target_price = df.iloc[-1]['open'] + (prev_range * self.k)
        self.ma_20 = df['close'].rolling(window=20).mean().iloc[-1]
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        self.rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
        self.avg_volume = df['volume'].iloc[-21:-1].mean()

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        if self.target_price is None or self.ma_20 is None:
            return False
        current_price = current_data['last']
        current_volume = current_data.get('baseVolume', 0)
        
        # 1. 가격 돌파 + 2. 상승 추세 + 3. 거래량 2.5배 폭발 (더 엄격하게)
        if current_price >= self.target_price and current_price > self.ma_20:
            if self.avg_volume and current_volume > (self.avg_volume * 2.5):
                # AI 슬리피지 예측이 너무 크면(0.3% 이상) 진입 포기
                if ai_pred and ai_pred.get('estimated_slippage', 0) > 0.003:
                    return False
                return True
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        pnl = (current_price - entry_price) / entry_price
        
        # 본절가 방어: 수익이 0.5% 이상 났다가 0.2%로 내려오면 수수료만 건지고 탈출
        if pnl >= self.take_profit_pct:
            return "SCALPING_TP"
        if pnl <= -self.stop_loss_pct:
            return "SCALPING_SL"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
