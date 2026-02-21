"""
거래소 API 연결을 담당하는 기본 모듈.
업비트(Upbit) 환경에 최적화.
"""
import os
import ccxt.async_support as ccxt
from typing import Dict, Any, Optional, List
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ExchangeConnector:
    """거래소와의 직접적인 통신을 담당하는 클래스 (업비트 대응)."""

    def __init__(self, exchange_id: str = None):
        self.exchange_id = exchange_id or os.getenv("EXCHANGE_ID", "upbit")
        self.api_key = os.getenv("API_KEY")
        self.secret_key = os.getenv("SECRET_KEY")
        self.is_dry_run = os.getenv("DRY_RUN", "True").lower() == "true"
        
        self.exchange = self._init_exchange()

    def _init_exchange(self) -> Any:
        """업비트 거래소 객체 초기화."""
        if self.exchange_id not in ccxt.exchanges:
            raise ValueError(f"지원하지 않는 거래소입니다: {self.exchange_id}")
            
        exchange_class = getattr(ccxt, self.exchange_id)
        return exchange_class({
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'enableRateLimit': True,
            'options': {
                'createMarketBuyOrderRequiresPrice': False,
            }
        })

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """현재가 및 시세 정보 조회."""
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return ticker
        except Exception as e:
            logger.error(f"[{self.exchange_id}] 시세 조회 에러: {e}")
            return {}

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '1d', limit: int = 2) -> List[List[Any]]:
        """과거 캔들 데이터 조회."""
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            return ohlcv
        except Exception as e:
            logger.error(f"[{self.exchange_id}] OHLCV 데이터 조회 에러: {e}")
            return []

    async def fetch_balance(self) -> Dict[str, Any]:
        """계좌 잔고 조회 (KRW/원화 기준)."""
        if self.is_dry_run:
            # 테스트 모드 가상 원화 100만원
            return {"free": {"KRW": 1000000.0}, "total": {"KRW": 1000000.0}}
            
        try:
            balance = await self.exchange.fetch_balance()
            return balance
        except Exception as e:
            logger.error(f"[{self.exchange_id}] 잔고 조회 에러: {e}")
            return {}

    async def create_order(self, symbol: str, side: str, amount: float, price: Optional[float] = None) -> Dict[str, Any]:
        """주문 실행 (업비트는 최소 주문 금액 5,000원 확인 필수)."""
        if self.is_dry_run:
            logger.info(f"[DRY_RUN] 업비트 주문 시뮬레이션: {side} {amount} {symbol}")
            return {"id": "dry_run_id", "status": "closed", "price": price or 1.0}

        try:
            if price:
                order = await self.exchange.create_limit_order(symbol, side, amount, price)
            else:
                # 업비트 시장가 매수는 수량이 아닌 '금액' 기준으로 주문해야 할 수도 있음 (ccxt에서 자동 처리)
                order = await self.exchange.create_market_order(symbol, side, amount)
            
            logger.info(f"주문 성공: {order['id']}")
            return order
        except Exception as e:
            logger.error(f"[{self.exchange_id}] 주문 에러: {e}")
            return {}

    async def close(self):
        await self.exchange.close()
