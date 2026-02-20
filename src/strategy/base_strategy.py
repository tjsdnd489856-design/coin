"""
매매 전략의 기본 인터페이스 정의.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any
from src.learner.schema import TradeEvent

class BaseStrategy(ABC):
    """모든 전략의 부모 클래스."""

    @abstractmethod
    async def check_signal(self, market_data: Dict[str, Any]) -> bool:
        """진입/청산 신호를 확인."""
        pass

    @abstractmethod
    def calculate_amount(self, balance: float, price: float) -> float:
        """매수/매도 수량을 계산."""
        pass
