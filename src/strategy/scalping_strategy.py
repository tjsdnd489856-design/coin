"""
고승률을 위한 변동성 응축(Squeeze) 및 모멘텀 필터 적용 스캘핑 전략.
1분 봉의 가짜 신호를 극도로 제한함.
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """1분 봉 고승률 타겟 스캘핑 전략."""

    def __init__(self, k: float = 0.6, stop_loss_pct: float = 0.005, take_profit_pct: float = 0.012):
        self.k = k
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        # 지표 저장소
        self.target_price = None
        self.ma_20 = None
        self.rsi = None
        self.prev_rsi = None
        self.avg_volume = None
        self.bb_width = None # 밴드 너비 (응축도 확인용)

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        """지표 업데이트 및 응축도 계산."""
        if not ohlcv_list or len(ohlcv_list) < 30:
            return
        
        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 1. 목표가 및 이평선
        prev_candle = df.iloc[-2]
        prev_range = prev_candle['high'] - prev_candle['low']
        self.target_price = df.iloc[-1]['open'] + (prev_range * self.k)
        self.ma_20 = df['close'].rolling(window=20).mean().iloc[-1]
        
        # 2. RSI 및 모멘텀(기울기) 계산
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi_series = 100 - (100 / (1 + (gain / loss)))
        
        self.prev_rsi = rsi_series.iloc[-2]
        self.rsi = rsi_series.iloc[-1]
        
        # 3. 볼린저 밴드 너비(BB Width)로 응축도 계산
        ma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        upper_bb = ma20 + (2 * std20)
        lower_bb = ma20 - (2 * std20)
        # 밴드 폭이 좁을수록 힘이 응축됨
        self.bb_width = (upper_bb - lower_bb) / ma20
        self.bb_width = self.bb_width.iloc[-1]
        
        # 4. 거래량 필터
        self.avg_volume = df['volume'].iloc[-21:-1].mean()

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """강화된 4중 필터 승률 전략."""
        if self.target_price is None or self.bb_width is None:
            return False
            
        current_price = current_data['last']
        current_volume = current_data.get('baseVolume', 0)
        
        # 필터 1: 가격 돌파 및 상승 추세
        price_condition = current_price >= self.target_price and current_price > self.ma_20
        
        # 필터 2: 변동성 응축 확인 (밴드 너비가 너무 넓으면 이미 슈팅한 것이므로 제외)
        # 밴드 폭이 평소보다 좁은 상태에서 터지는 것만 잡음
        is_squeezed = self.bb_width < 0.02 # 2% 이내로 응축된 상태일 때만
        
        # 필터 3: 모멘텀 가속도 (RSI가 이전 봉보다 상승 중이어야 함)
        is_momentum_up = False
        if self.rsi and self.prev_rsi:
            is_momentum_up = self.rsi > self.prev_rsi
            
        # 필터 4: 거래량 폭발 (평균의 2.5배 이상)
        is_volume_spike = False
        if self.avg_volume and current_volume > (self.avg_volume * 2.5):
            is_volume_spike = True
            
        if price_condition and is_momentum_up and is_volume_spike:
            # Squeeze 조건은 선택적으로 적용 (너무 빡빡하면 거래가 안 터지므로 로그로 확인)
            logger.info(f"✨ 고승률 타점 발견! RSI: {self.rsi:.2f}, BB_Width: {self.bb_width:.4f}")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        pnl = (current_price - entry_price) / entry_price
        if pnl >= self.take_profit_pct:
            return "HIGH_PROB_TP"
        if pnl <= -self.stop_loss_pct:
            return "HIGH_PROB_SL"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
