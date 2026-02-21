"""
1분 봉 최적화 변동성 돌파 스캘핑 전략.
고빈도 노이즈 필터링 및 극단적 손익비 설정.
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """1분 봉 스캔용 변동성 돌파 전략."""

    def __init__(self, k: float = 0.5, stop_loss_pct: float = 0.003, take_profit_pct: float = 0.005):
        # 1분 봉 기준: 익절 0.5%, 손절 0.3% (수수료를 감안한 초단타 설정)
        self.k = k
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        self.target_price = None
        self.ma_20 = None
        self.rsi = None
        self.avg_volume = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        """1분 봉 데이터로 지표 갱신."""
        if not ohlcv_list or len(ohlcv_list) < 30:
            return

        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 1. 목표가: 이전 1분 봉 변동성 기준
        prev_candle = df.iloc[-2]
        prev_range = prev_candle['high'] - prev_candle['low']
        self.target_price = df.iloc[-1]['open'] + (prev_range * self.k)
        
        # 2. 추세 필터
        self.ma_20 = df['close'].rolling(window=20).mean().iloc[-1]
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        self.rsi = 100 - (100 / (1 + rs)).iloc[-1]
        
        # 3. 거래량 필터 (최근 20분 평균 대비)
        self.avg_volume = df['volume'].iloc[-21:-1].mean()

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """1분 봉 기반 매수 신호 확인."""
        if self.target_price is None or self.ma_20 is None or self.rsi is None:
            return False
            
        current_price = current_data['last']
        current_volume = current_data.get('baseVolume', 0)
        
        # 필터 1: 가격 돌파
        price_breakout = current_price >= self.target_price
        
        # 필터 2: 상승 추세
        is_uptrend = current_price > self.ma_20
        
        # 필터 3: 거래량 폭발 (평균의 2.0배 이상 터져야 진입 - 1분 봉 노이즈 방어)
        is_volume_spike = False
        if self.avg_volume and self.avg_volume > 0:
            is_volume_spike = current_volume > (self.avg_volume * 2.0)
        
        # 필터 4: RSI 과매수 직전 제외 (60 미만)
        is_not_overbought = self.rsi < 60
            
        if price_breakout and is_uptrend and is_volume_spike and is_not_overbought:
            logger.info(f"⚡ 1분봉 스캘핑 신호 포착! 가격: {current_price:,.0f}")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        """초단타 익절/손절 체크."""
        profit_loss_ratio = (current_price - entry_price) / entry_price
        
        if profit_loss_ratio <= -self.stop_loss_pct:
            return "1M_SCALPING_SL"
        if profit_loss_ratio >= self.take_profit_pct:
            return "1M_SCALPING_TP"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
