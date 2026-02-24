"""
[하이퍼 스캘핑 전략]
목표: 높은 승률과 잦은 거래 빈도.
특징:
1. RSI 50 상향 돌파 시 매수 (상승 모멘텀 포착)
2. 본전 보존(Break-even): 수익 0.2% 도달 시 손절선을 매수가로 이동하여 리스크 제거
3. 트레일링 스탑(Trailing Stop): 수익 발생 시 매도를 지연하여 수익 극대화
4. 손절(SL) 0.3%로 리스크 관리
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """초단타 하이퍼 스캘핑 전략 (실시간 가격 추적 및 본전 보존 기능 포함)."""

    def __init__(self):
        # [핵심 설정] - 기본값 (AI가 동적으로 변경 가능)
        self.take_profit_pct = 0.004    # 추격 시작 수익률 (0.4%)
        self.trailing_callback = 0.0015 # 최고점 대비 하락 시 매도 (0.15%)
        self.stop_loss_pct = 0.003      # 손절 0.3%
        self.fee_rate = 0.0005          # 업비트 수수료 0.05%
        
        # [AI 제안 적용 대상]
        self.rsi_lower_bound = 45       # RSI 매수 하한선
        self.volume_threshold = 1.2     # 거래량 급증 기준
        
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

    def reset_trailing_state(self):
        """매도 후 또는 초기 상태로 추격 로직 초기화."""
        self.max_price = 0
        self.is_trailing = False

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        """1분 봉 데이터를 받아 지표 계산."""
        if not ohlcv_list or len(ohlcv_list) < 30:
            return

        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 지표 계산
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
        self.bb_lower = df['bb_lower'].iloc[-1]
        
        avg_vol = df['volume'].iloc[-6:-1].mean()
        curr_vol = df['volume'].iloc[-1]
        self.volume_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """매수 신호 감지 (AI 제안 파라미터 적용)."""
        if self.rsi is None:
            return False
            
        # AI 제안 파라미터 적용 로직
        if ai_pred and 'suggested_params' in ai_pred:
            params = ai_pred['suggested_params']
            # AI가 제안한 값으로 전략 변수 업데이트
            self.stop_loss_pct = params.get('stop_loss_pct', self.stop_loss_pct)
            self.take_profit_pct = params.get('take_profit_pct', self.take_profit_pct)
            self.rsi_lower_bound = params.get('rsi_buy_threshold', self.rsi_lower_bound)
            self.volume_threshold = params.get('volume_multiplier', self.volume_threshold)
            
        current_price = current_data['last']
        
        cond_trend = self.ma_5 > self.ma_20
        # AI가 조정한 RSI 기준 사용
        cond_rsi = self.rsi_lower_bound < self.rsi < 65
        # AI가 조정한 거래량 기준 사용
        cond_vol = self.volume_ratio > self.volume_threshold
        cond_room = current_price < self.bb_upper

        if cond_trend and cond_rsi and cond_vol and cond_room:
            confidence = ai_pred.get('confidence_score', 0.5) if ai_pred else 0.5
            if confidence < 0.3:
                return False

            # 매수 전 상태 초기화
            self.reset_trailing_state()
            self.max_price = current_price
            
            logger.info(f"⚡ [AI 진입] RSI:{self.rsi:.1f}(>{self.rsi_lower_bound}), Vol:{self.volume_ratio:.1f}배(>{self.volume_threshold})")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        """지능형 매도 신호 확인 (실시간 가격 반응 로직)."""
        raw_pnl = (current_price - entry_price) / entry_price
        net_pnl = raw_pnl - (self.fee_rate * 2)

        # 최고가 업데이트
        if current_price > self.max_price:
            self.max_price = current_price

        # 1. 강력 손절 (0.3% 하락 시 즉시 실행)
        if net_pnl <= -self.stop_loss_pct:
            return "SL_고정손절"

        # 2. 본전 보존 (수익 0.2% 도달 후 다시 매수가 근처로 오면 탈출)
        # 0.2% 수익 달성 후, 이익이 0.05% 미만으로 줄어들면 본전에서 정리
        if self.max_price >= entry_price * 1.002:
            if net_pnl < 0.0005:
                return "BE_본전보존"

        # 3. 추격 매도 로직
        if not self.is_trailing and net_pnl >= self.take_profit_pct:
            self.is_trailing = True
            logger.info(f"🔥 [수익권 진입] 추격 매도 시작 (수익률: {net_pnl:.2%})")

        if self.is_trailing:
            # 고점 대비 설정한 비율(0.15%)만큼 하락하면 매도
            drop_from_max = (self.max_price - current_price) / self.max_price
            if drop_from_max >= self.trailing_callback:
                return f"TS_추격익절({net_pnl:.2%})"
            
            # 과열권(RSI 85) 도달 시 즉시 익절
            if self.rsi is not None and self.rsi > 85:
                return "TS_과열익절"
        
        # 보조: RSI 75 이상에서 수익 중일 때 소폭 하락하면 조기 익절
        elif self.rsi is not None and self.rsi > 75:
             if net_pnl > 0.001:
                 return "RSI_심리적익절"

        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        return balance / price
