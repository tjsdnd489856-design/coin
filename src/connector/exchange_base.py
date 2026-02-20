"""
거래소 API 연결을 담당하는 기본 모듈.
ccxt 라이브러리를 사용하여 범용성을 확보.
"""
import os
import ccxt.async_support as ccxt
from typing import Dict, Any, Optional, List
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ExchangeConnector:
    """거래소와의 직접적인 통신을 담당하는 클래스."""

    def __init__(self, exchange_id: str = None):
        self.exchange_id = exchange_id or os.getenv("EXCHANGE_ID", "binance")
        self.api_key = os.getenv("API_KEY")
        self.secret_key = os.getenv("SECRET_KEY")
        self.is_dry_run = os.getenv("DRY_RUN", "True").lower() == "true"
        
        self.exchange = self._init_exchange()

    def _init_exchange(self) -> Any:
        """거래소 객체 초기화."""
        if self.exchange_id not in ccxt.exchanges:
            raise ValueError(f"지원하지 않는 거래소입니다: {self.exchange_id}")
            
        exchange_class = getattr(ccxt, self.exchange_id)
        return exchange_class({
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """현재가 및 시세 정보 조회."""
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return ticker
        except Exception as e:
            logger.error(f"시세 조회 에러: {e}")
            return {}

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '1d', limit: int = 2) -> List[List[Any]]:
        """과거 캔들 데이터 조회."""
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            return ohlcv
        except Exception as e:
            logger.error(f"OHLCV 데이터 조회 에러: {e}")
            return []

    async def fetch_balance(self) -> Dict[str, Any]:
        """계좌 잔고 조회."""
        if self.is_dry_run:
            # 테스트 모드일 때는 가상의 10,000 USDT 반환
            return {"free": {"USDT": 10000.0}, "total": {"USDT": 10000.0}}
            
        try:
            balance = await self.exchange.fetch_balance()
            return balance
        except Exception as e:
            logger.error(f"잔고 조회 에러: {e}")
            return {}

    async def create_order(self, symbol: str, side: str, amount: float, price: Optional[float] = None) -> Dict[str, Any]:
        """주문 실행."""
        if self.is_dry_run:
            logger.info(f"[DRY_RUN] 주문 시뮬레이션: {side} {amount} {symbol}")
            return {"id": "dry_run_id", "status": "closed", "price": price or 1.0}

        try:
            if price:
                order = await self.exchange.create_limit_order(symbol, side, amount, price)
            else:
                order = await self.exchange.create_market_order(symbol, side, amount)
            
            logger.info(f"주문 성공: {order['id']}")
            return order
        except Exception as e:
            logger.error(f"주문 에러: {e}")
            return {}

    async def close(self):
        """연결 종료."""
        await self.exchange.close()
