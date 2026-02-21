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
        self.volume_multiplier = 2.0 # 기본값
        
        # 지표
        self.target_price = None
        self.ma_20 = None
        self.rsi = None
        self.avg_volume = None
        self.bb_width = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        if not ohlcv_list or len(ohlcv_list) < 30: return
        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 목표가는 k값이 변동되므로 check_signal 시점에 계산하는 게 좋지만,
        # 여기선 기본값으로 계산해두고 signal 체크 때 덮어씌움
        prev_candle = df.iloc[-2]
        self.prev_range = prev_candle['high'] - prev_candle['low']
        self.current_open = df.iloc[-1]['open']
        
        self.ma_20 = df['close'].rolling(20).mean().iloc[-1]
        
        # RSI 등 보조지표 계산
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        self.rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
        
        ma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        upper = ma20 + (2*std20)
        lower = ma20 - (2*std20)
        self.bb_width = ((upper - lower) / ma20).iloc[-1]
        
        self.avg_volume = df['volume'].iloc[-21:-1].mean()

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """AI가 제안한 파라미터(params)를 우선 적용."""
        if self.ma_20 is None: return False
        
        # [핵심] AI가 제안한 파라미터 적용 (없으면 기본값)
        params = ai_pred.get('suggested_params', {}) if ai_pred else {}
        # Pydantic 모델이 dict로 변환되어 들어옴
        k = params.get('k', self.k)
        vol_mult = params.get('volume_multiplier', self.volume_multiplier)
        
        # 동적 목표가 재계산
        target_price = self.current_open + (self.prev_range * k)
        
        current_price = current_data['last']
        current_vol = current_data.get('baseVolume', 0)
        
        # 1. 가격 돌파
        cond_price = current_price >= target_price and current_price > self.ma_20
        # 2. 거래량 (AI가 정해준 배수)
        cond_vol = self.avg_volume and current_vol > (self.avg_volume * vol_mult)
        # 3. 응축 (선택)
        cond_squeeze = self.bb_width < 0.025
        
        if cond_price and cond_vol and cond_squeeze:
            logger.info(f"✨ AI 스캘핑 신호 (k={k:.2f}, vol_x={vol_mult:.1f})")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        pnl = (current_price - entry_price) / entry_price
        if pnl >= self.take_profit_pct: return "AI_TP"
        if pnl <= -self.stop_loss_pct: return "AI_SL"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
