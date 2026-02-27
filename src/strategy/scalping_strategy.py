"""
[울티메이트 하이브리드 전략]
1. 15분봉 큰 추세 필터 (15m EMA & RSI)
2. ATR 기반 가변 익절/손절 (시장 변동성 대응)
3. 지표 신뢰도 기반 컨피던스 스코어링
"""
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """지능형 울티메이트 스캘핑 전략."""

    def __init__(self):
        # [기본 설정]
        self.fee_rate = 0.0005
        self.max_holding_minutes = 10
        
        # [지표 데이터 - 1분봉]
        self.rsi = None
        self.ma_5 = None
        self.ma_20 = None
        self.volume_ratio = 1.0
        self.vwap = None
        self.atr = None # 변동성 지표
        
        # [지표 데이터 - 15분봉 (쌍안경 필터)]
        self.is_15m_uptrend = False
        self.rsi_15m = 50
        
        # 상태 관리
        self.max_price = 0
        self.is_trailing = False
        self.entry_atr = 0 # 진입 시점의 변동성 기록

    def reset_trailing_state(self):
        self.max_price = 0
        self.is_trailing = False
        self.entry_atr = 0

    async def update_indicators(self, ohlcv_1m: List[List[Any]], ohlcv_15m: List[List[Any]] = None):
        """1분봉과 15분봉 지표를 동시에 업데이트."""
        if not ohlcv_1m or len(ohlcv_1m) < 30: return

        # --- 1분봉 지표 계산 ---
        df = pd.DataFrame(ohlcv_1m, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # VWAP 계산
        df['date'] = pd.to_datetime(df['datetime'], unit='ms').dt.date
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['cum_vol_price'] = df.groupby('date')['tp'].transform(lambda x: (x * df['volume']).cumsum())
        df['cum_vol'] = df.groupby('date')['volume'].transform('cumsum')
        self.vwap = (df['cum_vol_price'] / df['cum_vol']).iloc[-1]

        # RSI & MA
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        self.rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
        self.ma_5 = df['close'].rolling(5).mean().iloc[-1]
        self.ma_20 = df['close'].rolling(20).mean().iloc[-1]
        
        # ATR (변동성 계산)
        df['tr'] = np.maximum(df['high'] - df['low'], 
                             np.maximum(abs(df['high'] - df['close'].shift(1)), 
                                        abs(df['low'] - df['close'].shift(1))))
        self.atr = df['tr'].rolling(20).mean().iloc[-1]
        
        # 거래량 비율
        avg_vol = df['volume'].iloc[-6:-1].mean()
        self.volume_ratio = df['volume'].iloc[-1] / avg_vol if avg_vol > 0 else 1.0

        # --- 15분봉 큰 추세 필터 (쌍안경) ---
        if ohlcv_15m and len(ohlcv_15m) >= 20:
            df15 = pd.DataFrame(ohlcv_15m, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            ema9_15 = df15['close'].ewm(span=9).mean().iloc[-1]
            ema21_15 = df15['close'].ewm(span=21).mean().iloc[-1]
            
            # 15분봉 RSI
            d15 = df15['close'].diff()
            g15 = (d15.where(d15 > 0, 0)).rolling(14).mean()
            l15 = (-d15.where(d15 < 0, 0)).rolling(14).mean()
            self.rsi_15m = (100 - (100 / (1 + (g15 / l15)))).iloc[-1]
            
            # 조건: 15분봉이 정배열이거나 RSI가 강력할 때만 진입 허용
            self.is_15m_uptrend = (ema9_15 > ema21_15) or (self.rsi_15m > 55)

    def calculate_confidence(self) -> float:
        """현재 신호의 강도를 0.5 ~ 1.5 사이의 점수로 환산."""
        score = 1.0
        if self.rsi_15m > 60: score += 0.2    # 큰 추세가 아주 좋음
        if self.volume_ratio > 2.0: score += 0.2 # 거래량이 폭발적임
        if self.rsi < 40: score -= 0.2         # 너무 과매도권 (위험)
        return max(0.5, min(1.5, score))

    async def check_signal(self, current_data: Dict[str, Any]) -> bool:
        """울티메이트 진입 로직."""
        if self.rsi is None or self.vwap is None or not self.is_15m_uptrend:
            return False
            
        current_price = current_data['last']
        
        # 핵심 조건: 15분봉 상승 + VWAP 위 + 1분봉 정배열 + RSI 적정 + 거래량 급증
        cond_main = current_price > self.vwap and self.ma_5 > self.ma_20
        cond_rsi = 45 < self.rsi < 65
        cond_vol = self.volume_ratio > 1.3 # 1.2에서 1.3으로 소폭 상향

        if cond_main and cond_rsi and cond_vol:
            self.reset_trailing_state()
            self.max_price = current_price
            self.entry_atr = self.atr # 진입 시점 변동성 기록
            
            logger.info(f"🚀 [울티메이트 진입] 15m추세 확인 | Confidence: {self.calculate_confidence():.1f}")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float, entry_time: datetime = None) -> Optional[str]:
        """ATR 기반 가변 익절/손절 로직."""
        if entry_time:
            now = datetime.now(timezone.utc)
            if (now - entry_time).total_seconds() / 60.0 >= self.max_holding_minutes:
                return "TL_시간제한"

        raw_pnl = (current_price - entry_price) / entry_price
        net_pnl = raw_pnl - (self.fee_rate * 2)

        # [신규] ATR 기반 다이나믹 손절선 계산
        # 변동성이 크면 손절선을 깊게(0.5%까지), 작으면 좁게(0.2%까지) 자동 조절
        dynamic_sl_pct = max(0.002, min(0.005, (self.entry_atr / entry_price) * 1.5))
        
        # [신규] ATR 기반 다이나믹 익절 트리거
        dynamic_tp_pct = max(0.003, min(0.008, (self.entry_atr / entry_price) * 2.5))

        if current_price > self.max_price:
            self.max_price = current_price

        # 1. 가변 손절
        if net_pnl <= -dynamic_sl_pct:
            return f"SL_가변손절({dynamic_sl_pct:.2%})"

        # 2. 본전 보존
        if self.max_price >= entry_price * (1 + dynamic_tp_pct * 0.5):
            if net_pnl < 0.0005:
                return "BE_본전보존"

        # 3. 가변 추격 익절
        if not self.is_trailing and net_pnl >= dynamic_tp_pct:
            self.is_trailing = True
            
        if self.is_trailing:
            # 고점 대비 하락폭도 ATR에 비례하게 조절 (변동성 크면 여유있게)
            dynamic_callback = max(0.001, min(0.003, dynamic_tp_pct * 0.3))
            drop_from_max = (self.max_price - current_price) / self.max_price
            if drop_from_max >= dynamic_callback:
                return f"TS_가변익절({net_pnl:.2%})"

        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
