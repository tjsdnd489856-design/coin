"""
15분 봉 기반의 변동성 돌파 스캘핑 전략.
거래량 필터와 타이트한 익절/손절을 통해 승률을 높임.
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """15분 봉 최적화 변동성 돌파 전략."""

    def __init__(self, k: float = 0.4, stop_loss_pct: float = 0.008, take_profit_pct: float = 0.015):
        # 15분 봉은 노이즈가 많으므로 k값을 약간 낮추고(0.4), 익절(1.5%)과 손절(0.8%)을 타이트하게 잡음
        self.k = k
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        # 지표 데이터 저장소
        self.target_price = None
        self.ma_20 = None
        self.rsi = None
        self.avg_volume = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        """15분 봉 데이터를 바탕으로 지표 갱신."""
        if not ohlcv_list or len(ohlcv_list) < 30:
            logger.warning("지표 계산을 위한 데이터가 부족합니다. (최소 30개 필요)")
            return

        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 1. 목표가 계산 (직전 봉 기준 변동성 적용)
        prev_candle = df.iloc[-2]
        prev_range = prev_candle['high'] - prev_candle['low']
        self.target_price = df.iloc[-1]['open'] + (prev_range * self.k)
        
        # 2. 이동평균선 및 RSI (15분 봉 추세 확인용)
        self.ma_20 = df['close'].rolling(window=20).mean().iloc[-1]
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        self.rsi = 100 - (100 / (1 + rs)).iloc[-1]
        
        # 3. 평균 거래량 계산 (거래량 필터용)
        self.avg_volume = df['volume'].iloc[-21:-1].mean()
        
        logger.info(f"[스캘핑] 지표 갱신 | 목표가: {self.target_price:,.0f} | RSI: {self.rsi:.2f} | 평균거래량: {self.avg_volume:.2f}")

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """15분 봉 기반 매수 신호 확인."""
        if self.target_price is None or self.ma_20 is None or self.rsi is None:
            return False
            
        current_price = current_data['last']
        current_volume = current_data.get('baseVolume', 0) # 현재 거래량
        
        # 필터 1: 가격 돌파
        price_breakout = current_price >= self.target_price
        
        # 필터 2: 상승 추세 (MA 20 위)
        is_uptrend = current_price > self.ma_20
        
        # 필터 3: 거래량 동반 (평균 거래량의 1.5배 이상일 때 진입하여 가짜 돌파 방지)
        is_volume_spike = True
        if self.avg_volume and self.avg_volume > 0:
            is_volume_spike = current_volume > (self.avg_volume * 1.5)
        
        # 필터 4: 과매수 방지 (RSI 65 미만에서만 진입)
        is_not_overbought = self.rsi < 65
            
        if price_breakout and is_uptrend and is_volume_spike and is_not_overbought:
            logger.info(f"✨ 스캘핑 진입 신호! 가격: {current_price:,.0f}, 거래량: {current_volume:.2f}")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        """타이트한 손절/익절 체크."""
        profit_loss_ratio = (current_price - entry_price) / entry_price
        
        if profit_loss_ratio <= -self.stop_loss_pct:
            return "SCALPING_STOP_LOSS"
        if profit_loss_ratio >= self.take_profit_pct:
            return "SCALPING_TAKE_PROFIT"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        """가용 자산 투입."""
        return balance / price
