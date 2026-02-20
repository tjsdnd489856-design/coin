"""
변동성 돌파 기반의 단타 전략 구현.
AI 학습 모듈의 예측 데이터를 필터로 사용.
"""
from typing import Dict, Any
from .base_strategy import BaseStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ScalpingStrategy(BaseStrategy):
    """변동성 돌파 + AI 필터 단타 전략."""

    def __init__(self, k: float = 0.5):
        self.k = k  # 변동성 계수 (통상 0.5 사용)
        self.target_price = None

    async def update_target_price(self, ohlcv: Dict[str, Any]):
        """전일 데이터를 기반으로 당일 목표가 계산."""
        # target = 당일시가 + (전일고가 - 전일저가) * k
        prev_range = ohlcv['high'] - ohlcv['low']
        self.target_price = ohlcv['close'] + (prev_range * self.k)
        logger.info(f"새로운 목표가 설정: {self.target_price}")

    async def check_signal(self, current_data: Dict[str, Any], ai_pred: Dict[str, Any] = None) -> bool:
        """매수 신호 확인."""
        if not self.target_price:
            return False
            
        current_price = current_data['last']
        
        # 1. 가격 조건 확인: 목표가 돌파 여부
        price_signal = current_price >= self.target_price
        
        # 2. AI 필터 조건 확인: 예상 슬리피지가 낮을 때만 진입 (승률 보정)
        ai_signal = True
        if ai_pred and ai_pred.get('estimated_slippage', 0) > 0.005: # 0.5% 이상의 오차 예상시 패스
            logger.info("AI 필터: 예상 슬리피지가 너무 높아 진입을 취소합니다.")
            ai_signal = False
            
        return price_signal and ai_signal

    def calculate_amount(self, balance: float, price: float) -> float:
        """자산의 일부(예: 10%)를 투입하는 수량 계산."""
        risk_per_trade = 0.1 # 10% 투입
        return (balance * risk_per_trade) / price
