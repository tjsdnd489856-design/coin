"""
[하이브리드 스캘핑 전략]
기존 초단타 스캘핑에 추세 필터(VWAP)와 시간/안전 장치를 결합한 전략.
특징:
1. VWAP(거래량 가중 평균가) 위에서만 진입하여 대세 하락장 매수 방지
2. 최대 10분 보유 제한으로 횡보장 자금 묶임 방지
3. 본전 보존(Break-even) 및 트레일링 스탑 유지
"""
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """안전성이 강화된 하이브리드 스캘핑 전략."""

    def __init__(self):
        # [수익/손실 설정]
        self.take_profit_pct = 0.004    # 추격 시작 수익률 (0.4%)
        self.trailing_callback = 0.0015 # 최고점 대비 하락 시 매도 (0.15%)
        self.stop_loss_pct = 0.003      # 기본 손절 0.3%
        self.fee_rate = 0.0005          # 업비트 수수료 0.05%
        
        # [진입 설정]
        self.rsi_lower_bound = 45       # RSI 매수 하한선
        self.volume_threshold = 1.2     # 거래량 급증 기준
        
        # [안전 장치 추가]
        self.max_holding_minutes = 10   # 최대 10분 보유
        
        # 지표 데이터
        self.rsi = None
        self.ma_5 = None
        self.ma_20 = None
        self.bb_upper = None
        self.bb_lower = None
        self.volume_ratio = 1.0
        self.vwap = None                # 새롭게 추가된 VWAP 지표
        
        # 추격 매도 상태 관리
        self.max_price = 0
        self.is_trailing = False

    def reset_trailing_state(self):
        """매도 후 또는 초기 상태로 추격 로직 초기화."""
        self.max_price = 0
        self.is_trailing = False

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        """1분 봉 데이터를 받아 지표 계산 (VWAP 포함)."""
        if not ohlcv_list or len(ohlcv_list) < 30:
            return

        # datetime 컬럼은 timestamp(ms) 형태로 들어온다고 가정
        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # [신규] 일간 VWAP 계산 로직
        # datetime 기반으로 오늘 날짜(UTC 기준) 파악
        df['date'] = pd.to_datetime(df['datetime'], unit='ms').dt.date
        # Typical Price 계산
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        # 날짜별(오늘 하루) 누적 거래대금 / 누적 거래량
        df['cum_vol_price'] = df.groupby('date')['tp'].transform(lambda x: (x * df['volume']).cumsum())
        df['cum_vol'] = df.groupby('date')['volume'].transform('cumsum')
        df['vwap'] = df['cum_vol_price'] / df['cum_vol']
        self.vwap = df['vwap'].iloc[-1]

        # 기존 지표 계산
        df['ma_5'] = df['close'].rolling(5).mean()
        df['ma_20'] = df['close'].rolling(20).mean()
        self.ma_5 = df['ma_5'].iloc[-1]
        self.ma_20 = df['ma_20'].iloc[-1]
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        self.rsi = df['rsi'].iloc[-1]
        
        std = df['close'].rolling(20).std()
        df['bb_upper'] = df['ma_20'] + (std * 2)
        df['bb_lower'] = df['ma_20'] - (std * 2)
        self.bb_upper = df['bb_upper'].iloc[-1]
        
        avg_vol = df['volume'].iloc[-6:-1].mean()
        curr_vol = df['volume'].iloc[-1]
        self.volume_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

    async def check_signal(self, current_data: Dict[str, Any]) -> bool:
        """매수 신호 감지 (VWAP 추세 필터 추가)."""
        if self.rsi is None or self.vwap is None:
            return False
            
        current_price = current_data['last']
        
        # [신규] VWAP 필터: 현재 가격이 당일 평균 단가(VWAP)보다 높아야만 강세장으로 판단
        cond_vwap = current_price > self.vwap
        
        cond_trend = self.ma_5 > self.ma_20
        cond_rsi = self.rsi_lower_bound < self.rsi < 65
        cond_vol = self.volume_ratio > self.volume_threshold
        cond_room = current_price < self.bb_upper

        if cond_vwap and cond_trend and cond_rsi and cond_vol and cond_room:
            # 매수 전 상태 초기화
            self.reset_trailing_state()
            self.max_price = current_price
            
            logger.info(f"⚡ [진입] VWAP 강세 확인 | RSI:{self.rsi:.1f}, Vol:{self.volume_ratio:.1f}배")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float, entry_time: datetime = None) -> Optional[str]:
        """지능형 매도 신호 확인 (시간 제한 기능 추가)."""
        
        # 1. [신규] 10분 초과 보유 시 무조건 청산 (시간 제한)
        if entry_time:
            now = datetime.now(timezone.utc)
            holding_minutes = (now - entry_time).total_seconds() / 60.0
            if holding_minutes >= self.max_holding_minutes:
                return f"TL_시간초과({holding_minutes:.1f}분)"

        # 2. 가격 기반 청산 (기존 로직)
        raw_pnl = (current_price - entry_price) / entry_price
        net_pnl = raw_pnl - (self.fee_rate * 2)

        if current_price > self.max_price:
            self.max_price = current_price

        # 강력 손절
        if net_pnl <= -self.stop_loss_pct:
            return "SL_고정손절"

        # 본전 보존
        if self.max_price >= entry_price * 1.002:
            if net_pnl < 0.0005:
                return "BE_본전보존"

        # 추격 매도
        if not self.is_trailing and net_pnl >= self.take_profit_pct:
            self.is_trailing = True
            logger.info(f"🔥 [수익권 진입] 추격 매도 시작 (수익률: {net_pnl:.2%})")

        if self.is_trailing:
            drop_from_max = (self.max_price - current_price) / self.max_price
            if drop_from_max >= self.trailing_callback:
                return f"TS_추격익절({net_pnl:.2%})"
            
            if self.rsi is not None and self.rsi > 85:
                return "TS_과열익절"
        
        elif self.rsi is not None and self.rsi > 75:
             if net_pnl > 0.001:
                 return "RSI_심리적익절"

        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
