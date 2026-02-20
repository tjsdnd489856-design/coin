"""
변동성 돌파 기반의 단타 전략 구현.
MA(이동평균선) 및 RSI 지표를 활용한 승률 개선 로직 추가.
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """변동성 돌파 + 리스크 관리 + 지표 필터링 전략."""

    def __init__(self, k: float = 0.5, stop_loss_pct: float = 0.02, take_profit_pct: float = 0.04):
        self.k = k
        self.stop_loss_pct = stop_loss_pct    # 2% 손절
        self.take_profit_pct = take_profit_pct # 4% 익절
        
        # 지표 데이터 저장소
        self.target_price = None
        self.ma_20 = None
        self.rsi = None

    async def update_indicators(self, ohlcv_list: List[List[Any]]):
        """OHLCV 데이터를 바탕으로 모든 지표 갱신."""
        if not ohlcv_list or len(ohlcv_list) < 20:
            logger.warning("지표 계산을 위한 데이터가 부족합니다.")
            return

        # 1. 데이터프레임 변환
        df = pd.DataFrame(ohlcv_list, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        
        # 2. 목표가 계산 (어제 데이터 기준)
        prev_day = df.iloc[-2]
        prev_range = prev_day['high'] - prev_day['low']
        self.target_price = prev_day['close'] + (prev_range * self.k)
        
        # 3. 20일 이동평균선 계산
        self.ma_20 = df['close'].rolling(window=20).mean().iloc[-1]
        
        # 4. RSI 계산 (14일 기준)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        self.rsi = 100 - (100 / (1 + rs)).iloc[-1]
        
        logger.info(f"지표 갱신 완료 | 목표가: {self.target_price:,.0f} | MA20: {self.ma_20:,.0f} | RSI: {self.rsi:.2f}")

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """강화된 매수 신호 확인."""
        if not self.target_price or self.ma_20 is None or self.rsi is None:
            return False
            
        current_price = current_data['last']
        
        # 필터 1: 변동성 돌파 조건
        price_breakout = current_price >= self.target_price
        
        # 필터 2: 상승 추세 조건 (현재가 > MA 20)
        is_uptrend = current_price > self.ma_20
        
        # 필터 3: 과매수 방지 조건 (RSI < 70)
        is_not_overbought = self.rsi < 70
        
        # 필터 4: AI 슬리피지 조건
        ai_signal = True
        if ai_pred and ai_pred.get('estimated_slippage', 0) > 0.005:
            ai_signal = False
            
        # 모든 조건 충족 시 매수
        if price_breakout and is_uptrend and is_not_overbought and ai_signal:
            logger.info("모든 매수 조건 충족!")
            return True
            
        return False

    def check_exit_signal(self, entry_price: float, current_price: float) -> Optional[str]:
        """손절/익절 신호 확인."""
        profit_loss_ratio = (current_price - entry_price) / entry_price
        
        if profit_loss_ratio <= -self.stop_loss_pct:
            return "STOP_LOSS"
        if profit_loss_ratio >= self.take_profit_pct:
            return "TAKE_PROFIT"
        return None

    def calculate_amount(self, balance: float, price: float) -> float:
        """가용 자산의 전체를 투입 (이미 Manager에서 N분할됨)."""
        # Manager에서 이미 invest_krw로 분할해서 주므로, 여기서는 해당 금액을 다 씀
        return balance / price
