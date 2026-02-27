"""
[울티메이트 하이브리드 전략 - 상태 메시지 로직 개선]
데이터 수집 성공 여부를 명확히 표시하도록 수정되었습니다.
"""
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """지능형 울티메이트 스캘핑 전략 (메시지 개선)."""

    def __init__(self):
        self.fee_rate = 0.0005
        self.max_holding_minutes = 10
        self.rsi = None
        self.ma_5 = None
        self.ma_20 = None
        self.volume_ratio = 1.0
        self.vwap = None
        self.atr = None
        self.is_15m_uptrend = False
        self.rsi_15m = None
        self.max_price = 0
        self.is_trailing = False
        self.entry_atr = 0
        # 초기 상태 메시지
        self.last_reason = "🚀 시스템 기동 중... (데이터 수집 시작)"

    def reset_trailing_state(self):
        self.max_price = 0
        self.is_trailing = False
        self.entry_atr = 0

    async def update_indicators(self, ohlcv_1m: List[List[Any]], ohlcv_15m: List[List[Any]] = None):
        """데이터 수집 성공 시 상태 메시지를 먼저 업데이트합니다."""
        if not ohlcv_1m or len(ohlcv_1m) < 30: 
            self.last_reason = f"⏳ 1분봉 수집 중 ({len(ohlcv_1m) if ohlcv_1m else 0}/30)"
            return
            
        if not ohlcv_15m or len(ohlcv_15m) < 20:
            self.last_reason = f"⏳ 15분봉 수집 중 ({len(ohlcv_15m) if ohlcv_15m else 0}/20)"
            return

        # 데이터를 성공적으로 받았을 때의 기본 메시지
        self.last_reason = "👀 시장 분석 완료 (조건 대기 중)"

        df = pd.DataFrame(ohlcv_1m, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        df['date'] = pd.to_datetime(df['datetime'], unit='ms').dt.date
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['cum_vol_price'] = df.groupby('date')['tp'].transform(lambda x: (x * df['volume']).cumsum())
        df['cum_vol'] = df.groupby('date')['volume'].transform('cumsum')
        self.vwap = (df['cum_vol_price'] / df['cum_vol']).iloc[-1]
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        self.rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
        self.ma_5 = df['close'].rolling(5).mean().iloc[-1]
        self.ma_20 = df['close'].rolling(20).mean().iloc[-1]
        
        df['tr'] = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
        self.atr = df['tr'].rolling(20).mean().iloc[-1]
        
        avg_vol = df['volume'].iloc[-6:-1].mean()
        self.volume_ratio = df['volume'].iloc[-1] / avg_vol if avg_vol > 0 else 1.0

        df15 = pd.DataFrame(ohlcv_15m, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        ema9_15 = df15['close'].ewm(span=9).mean().iloc[-1]
        ema21_15 = df15['close'].ewm(span=21).mean().iloc[-1]
        d15 = df15['close'].diff()
        g15 = (d15.where(d15 > 0, 0)).rolling(14).mean()
        l15 = (-d15.where(d15 < 0, 0)).rolling(14).mean()
        self.rsi_15m = (100 - (100 / (1 + (g15 / l15)))).iloc[-1]
        self.is_15m_uptrend = (ema9_15 > ema21_15) or (self.rsi_15m > 55)

    async def check_signal(self, current_data: Dict[str, Any]) -> bool:
        """주도주에 포함되었을 때 더 상세한 분석 사유를 제공합니다."""
        if self.rsi is None or self.vwap is None or self.rsi_15m is None:
            self.last_reason = "⚙️ 지표 계산 마무리 중..."
            return False
            
        current_price = current_data['last']
        
        if not self.is_15m_uptrend:
            self.last_reason = f"🔭 15분봉 추세 하락 (RSI: {self.rsi_15m:.1f})"
            return False
        if current_price <= self.vwap:
            self.last_reason = f"📉 VWAP({self.vwap:,.0f}) 아래 위치"
            return False
        if self.ma_5 <= self.ma_20:
            self.last_reason = "💤 단기 횡보 중 (이평선 역배열)"
            return False
        if self.rsi < 45 or self.rsi > 65:
            self.last_reason = f"📊 RSI 부적합 ({self.rsi:.1f})"
            return False
        if self.volume_ratio <= 1.3:
            self.last_reason = f"☁️ 거래량 미달 (평소 대비 {self.volume_ratio:.1f}배)"
            return False

        self.last_reason = f"✅ 진입 대기 (거래량 {self.volume_ratio:.1f}배 돌파)"
        return True

    def check_exit_signal(self, entry_price: float, current_price: float, entry_time: datetime = None) -> Optional[str]:
        if entry_time:
            now = datetime.now(timezone.utc)
            if (now - entry_time).total_seconds() / 60.0 >= self.max_holding_minutes:
                return "TL_시간제한"
        raw_pnl = (current_price - entry_price) / entry_price
        net_pnl = raw_pnl - (self.fee_rate * 2)
        atr_val = self.entry_atr if self.entry_atr > 0 else (entry_price * 0.002)
        dynamic_sl_pct = max(0.002, min(0.005, (atr_val / entry_price) * 1.5))
        dynamic_tp_pct = max(0.003, min(0.008, (atr_val / entry_price) * 2.5))
        if current_price > self.max_price: self.max_price = current_price
        if net_pnl <= -dynamic_sl_pct: return f"SL_가변손절({dynamic_sl_pct:.2%})"
        if self.max_price >= entry_price * (1 + dynamic_tp_pct * 0.5):
            if net_pnl < 0.0005: return "BE_본전보존"
        if not self.is_trailing and net_pnl >= dynamic_tp_pct: self.is_trailing = True
        if self.is_trailing:
            dynamic_callback = max(0.001, min(0.003, dynamic_tp_pct * 0.3))
            drop_from_max = (self.max_price - current_price) / self.max_price
            if drop_from_max >= dynamic_callback: return f"TS_가변익절({net_pnl:.2%})"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
