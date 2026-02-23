"""
[하이퍼 스캘핑 전략]
목표: 높은 승률과 잦은 거래 빈도.
특징:
1. RSI 50 상향 돌파 시 매수 (상승 모멘텀 포착)
2. 볼린저 밴드 상단 터치 시 매도 (과열권 수익 실현)
3. 목표 수익률(TP) 0.4%, 손절(SL) 0.3%로 매우 짧게 설정
4. 거래량 급증 포착 (거래량 펌핑 시 진입)
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """초단타 하이퍼 스캘핑 전략."""

    def __init__(self):
        # [핵심 설정] 매우 짧은 목표와 손절
        self.take_profit_pct = 0.004  # 목표 수익률 0.4% (수수료 제외 순수익 약 0.3%)
        self.stop_loss_pct = 0.003    # 손절 0.3% (칼손절)
        self.fee_rate = 0.0005        # 업비트 수수료 0.05%
        
        # 지표 데이터
        self.rsi = None
        self.ma_5 = None
        self.ma_20 = None
        self.bb_upper = None
        self.bb_lower = None
        self.volume_ratio = 1.0       # 거래량 비율 (현재/평균)

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        """1분 봉 데이터를 받아 지표 계산."""
        if not ohlcv_list or len(ohlcv_list) < 30:
            return

        # 데이터프레임 변환
        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 1. 이동평균선 (단기 5분, 중기 20분)
        df['ma_5'] = df['close'].rolling(5).mean()
        df['ma_20'] = df['close'].rolling(20).mean()
        self.ma_5 = df['ma_5'].iloc[-1]
        self.ma_20 = df['ma_20'].iloc[-1]
        
        # 2. RSI (상대강도지수, 기간 14)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        self.rsi = df['rsi'].iloc[-1]
        
        # 3. 볼린저 밴드 (20일, 승수 2)
        std = df['close'].rolling(20).std()
        df['bb_upper'] = df['ma_20'] + (std * 2)
        df['bb_lower'] = df['ma_20'] - (std * 2)
        self.bb_upper = df['bb_upper'].iloc[-1]
        self.bb_lower = df['bb_lower'].iloc[-1]
        
        # 4. 거래량 급증 확인 (최근 5개 평균 대비 현재)
        avg_vol = df['volume'].iloc[-6:-1].mean()
        curr_vol = df['volume'].iloc[-1]
        self.volume_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """매수 신호 감지 (1분마다 호출)."""
        if self.rsi is None:
            return False
            
        current_price = current_data['last']
        
        # [매수 조건]
        # 1. 상승 추세: 5분 이평선이 20분 이평선보다 위에 있음 (정배열)
        cond_trend = self.ma_5 > self.ma_20
        
        # 2. RSI 모멘텀: RSI가 45 ~ 65 사이 (너무 과열되지도, 침체되지도 않은 상승 초입)
        cond_rsi = 45 < self.rsi < 65
        
        # 3. 거래량: 평소보다 거래량이 1.5배 이상 터짐 (수급 유입)
        cond_vol = self.volume_ratio > 1.2
        
        # 4. 가격 위치: 볼린저 밴드 상단을 아직 뚫지 않음 (상승 여력 있음)
        cond_room = current_price < self.bb_upper

        if cond_trend and cond_rsi and cond_vol and cond_room:
            # AI가 "매수하지 마라(confidence < 0.3)"고 하면 무시 (안전장치)
            confidence = ai_pred.get('confidence_score', 0.5) if ai_pred else 0.5
            if confidence < 0.3:
                return False

            logger.info(f"⚡ 초단타 포착! RSI:{self.rsi:.1f}, Vol:{self.volume_ratio:.1f}배")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        """매도 신호 확인 (실시간 가격 감시)."""
        raw_pnl = (current_price - entry_price) / entry_price
        net_pnl = raw_pnl - (self.fee_rate * 2) # 수수료 차감 후 순수익

        # 1. 익절 (Take Profit): 목표 수익 달성 시 바로 매도
        if net_pnl >= self.take_profit_pct:
            return "TP_익절"
            
        # 2. 손절 (Stop Loss): 손실이 커지기 전에 칼같이 자름
        if net_pnl <= -self.stop_loss_pct:
            return "SL_손절"
            
        # 3. 보조 매도 조건 (RSI 과열 시 조기 매도)
        if self.rsi is not None and self.rsi > 75:
             if net_pnl > 0.001: # 0.1%라도 수익이면 팜
                 return "RSI_과열매도"

        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        """매수 수량 계산 (전액 사용)."""
        return balance / price
