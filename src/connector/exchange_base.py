"""
거래소 API 연결을 담당하는 통합 모듈.
업비트(Upbit) 및 HTX(Huobi) 거래소를 지원합니다.
"""
import os
import ccxt.async_support as ccxt
from typing import Dict, Any, Optional, List
from src.learner.utils import get_logger

logger = get_logger(__name__)


class ExchangeConnector:
    """거래소와의 직접적인 통신을 담당하는 클래스."""

    def __init__(self, exchange_id: str = None):
        """환경 변수에 따라 거래소를 선택하여 초기화."""
        self.exchange_id = exchange_id or os.getenv("EXCHANGE_ID", "upbit").lower()
        self.api_key = os.getenv("API_KEY")
        self.secret_key = os.getenv("SECRET_KEY")
        self.is_dry_run = os.getenv("DRY_RUN", "True").lower() == "true"
        
        self.exchange = self._init_exchange()
        logger.info(f"🔌 {self.exchange_id.upper()} 연결 완료 (테스트모드: {self.is_dry_run})")

    def _init_exchange(self) -> Any:
        """거래소 객체 생성 및 설정."""
        if self.exchange_id not in ccxt.exchanges:
            raise ValueError(f"지원하지 않는 거래소입니다: {self.exchange_id}")
            
        exchange_class = getattr(ccxt, self.exchange_id)
        
        options = {
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        }

        if self.exchange_id == 'upbit':
            options['options']['createMarketBuyOrderRequiresPrice'] = False
            
        return exchange_class(options)

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """현재가 및 시세 정보 조회."""
        try:
            return await self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"시세 조회 에러 ({symbol}): {e}")
            return {}

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '1d', limit: int = 2) -> List[List[Any]]:
        """과거 캔들 데이터 조회."""
        try:
            return await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            logger.error(f"데이터 조회 에러 ({symbol}): {e}")
            return []

    async def fetch_balance(self) -> Dict[str, Any]:
        """계좌 잔고 조회."""
        if self.is_dry_run:
            currency = "KRW" if self.exchange_id == 'upbit' else "USDT"
            return {"free": {currency: 1000000.0}, "total": {currency: 1000000.0}}
            
        try:
            # 시장 데이터(마켓 정보)가 로드되어야 잔고 계산이 정확함
            if not self.exchange.markets:
                await self.exchange.load_markets()
            return await self.exchange.fetch_balance()
        except Exception as e:
            logger.error(f"잔고 조회 에러: {e}")
            return {}

    async def create_order(self, symbol: str, side: str, amount: float, price: Optional[float] = None) -> Dict[str, Any]:
        """주문 실행 (업비트 특화 로직 포함)."""
        if self.is_dry_run:
            logger.info(f"[시뮬레이션] {symbol} {side} {amount:,.2f}")
            return {"id": "dry_run", "status": "closed"}

        try:
            # 마켓 정보 로드 (정밀도 계산용)
            if not self.exchange.markets:
                await self.exchange.load_markets()

            if side == 'buy':
                if self.exchange_id == 'upbit':
                    # 업비트 시장가 매수는 '총 금액'을 입력해야 함
                    # amount 인자가 KRW 금액으로 들어온다고 가정
                    return await self.exchange.create_order(symbol, 'market', 'buy', amount)
                else:
                    return await self.exchange.create_market_buy_order(symbol, amount)
            else:
                # 매도는 '수량' 기준 (정밀도 조절 필수)
                amount = self.exchange.amount_to_precision(symbol, amount)
                return await self.exchange.create_market_sell_order(symbol, amount)
                
        except Exception as e:
            logger.error(f"주문 실행 에러 ({symbol} {side}): {e}")
            return {}

    async def close(self):
        """연결 종료 및 리소스 해제."""
        try:
            await self.exchange.close()
        except:
            pass
