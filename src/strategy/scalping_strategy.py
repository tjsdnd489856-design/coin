"""
[하이퍼 스캘핑 전략]
목표: 높은 승률과 잦은 거래 빈도.
특징:
1. RSI 50 상향 돌파 시 매수 (상승 모멘텀 포착)
2. 트레일링 스탑(Trailing Stop) 적용: 수익 발생 시 매도를 지연하여 수익 극대화
3. 목표 수익률(TP) 0.4% 도달 시 추격 시작
4. 손절(SL) 0.3%로 리스크 관리
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """초단타 하이퍼 스캘핑 전략 (수익 추격 기능 포함)."""

    def __init__(self):
        # [핵심 설정]
        self.take_profit_pct = 0.004    # 추격 시작 수익률 (0.4%)
        self.trailing_callback = 0.0015 # 최고점 대비 하락 시 매도 (0.15%)
        self.stop_loss_pct = 0.003      # 손절 0.3%
        self.fee_rate = 0.0005          # 업비트 수수료 0.05%
        
        # 지표 데이터
        self.rsi = None
        self.ma_5 = None
        self.ma_20 = None
        self.bb_upper = None
        self.bb_lower = None
        self.volume_ratio = 1.0
        
        # 추격 매도 상태 관리
        self.max_price = 0
        self.is_trailing = False

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        """1분 봉 데이터를 받아 지표 계산."""
        if not ohlcv_list or len(ohlcv_list) < 30:
            return

        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 1. 이동평균선
        df['ma_5'] = df['close'].rolling(5).mean()
        df['ma_20'] = df['close'].rolling(20).mean()
        self.ma_5 = df['ma_5'].iloc[-1]
        self.ma_20 = df['ma_20'].iloc[-1]
        
        # 2. RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        self.rsi = df['rsi'].iloc[-1]
        
        # 3. 볼린저 밴드
        std = df['close'].rolling(20).std()
        df['bb_upper'] = df['ma_20'] + (std * 2)
        df['bb_lower'] = df['ma_20'] - (std * 2)
        self.bb_upper = df['bb_upper'].iloc[-1]
        self.bb_lower = df['bb_lower'].iloc[-1]
        
        # 4. 거래량 비율
        avg_vol = df['volume'].iloc[-6:-1].mean()
        curr_vol = df['volume'].iloc[-1]
        self.volume_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """매수 신호 감지."""
        if self.rsi is None:
            return False
            
        current_price = current_data['last']
        
        cond_trend = self.ma_5 > self.ma_20
        cond_rsi = 45 < self.rsi < 65
        cond_vol = self.volume_ratio > 1.2
        cond_room = current_price < self.bb_upper

        if cond_trend and cond_rsi and cond_vol and cond_room:
            confidence = ai_pred.get('confidence_score', 0.5) if ai_pred else 0.5
            if confidence < 0.3:
                return False

            # 매수 시 추격 상태 초기화
            self.max_price = current_price
            self.is_trailing = False
            
            logger.info(f"⚡ 초단타 포착! RSI:{self.rsi:.1f}, Vol:{self.volume_ratio:.1f}배")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        """지능형 매도 신호 확인 (추격 매도 로직)."""
        raw_pnl = (current_price - entry_price) / entry_price
        net_pnl = raw_pnl - (self.fee_rate * 2)

        # 최고가 갱신
        if current_price > self.max_price:
            self.max_price = current_price

        # 1. 손절 (Stop Loss): 추격 모드와 상관없이 즉시 작동
        if net_pnl <= -self.stop_loss_pct:
            return "SL_손절"

        # 2. 익절 판단 로직
        # 목표 수익률 0.4% 도달 시 추격 모드 활성화
        if not self.is_trailing and net_pnl >= self.take_profit_pct:
            self.is_trailing = True
            logger.info(f"📈 수익권 진입(0.4%↑)! 추격 매도 시작 (현재 수익: {net_pnl:.2%})")

        # 추격 모드일 때 매도 타이밍 잡기
        if self.is_trailing:
            # 현재가가 최고가 대비 일정 비율(0.15%) 이상 하락하면 매도
            drop_from_max = (self.max_price - current_price) / self.max_price
            if drop_from_max >= self.trailing_callback:
                return f"TS_추격익절({net_pnl:.2%})"
            
            # (옵션) 수익이 너무 많이 났을 때 RSI 과열 시 안전하게 탈출
            if self.rsi is not None and self.rsi > 85:
                return "TS_과열탈출"
        
        # 추격 모드가 아닐 때의 보조 매도 조건 (RSI 과열)
        elif self.rsi is not None and self.rsi > 75:
             if net_pnl > 0.001:
                 return "RSI_조기익절"

        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
