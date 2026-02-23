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
        logger.info(f"🔌 {self.exchange_id.upper()} 거래소 연결 초기화 완료 (Dry Run: {self.is_dry_run})")

    def _init_exchange(self) -> Any:
        """거래소 객체 생성 및 설정."""
        if self.exchange_id not in ccxt.exchanges:
            raise ValueError(f"지원하지 않는 거래소입니다: {self.exchange_id}")
            
        exchange_class = getattr(ccxt, self.exchange_id)
        
        # 공통 옵션 설정
        options = {
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot', # 현물 거래 기본
            }
        }

        # 거래소별 특화 설정
        if self.exchange_id == 'upbit':
            # 업비트: 시장가 매수 시 가격 파라미터 필요 없음 설정
            options['options']['createMarketBuyOrderRequiresPrice'] = False
            
        elif self.exchange_id in ['htx', 'huobi']:
            # HTX (구 Huobi): 시장가 주문 시 수량 정밀도 조정 등 필요시 추가
            options['options']['createMarketBuyOrderRequiresPrice'] = False

        return exchange_class(options)

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
        """계좌 잔고 조회 (KRW 또는 USDT 기준)."""
        if self.is_dry_run:
            # 테스트 모드: 가상 자산 (업비트=KRW, 글로벌=USDT)
            currency = "KRW" if self.exchange_id == 'upbit' else "USDT"
            return {"free": {currency: 10000.0}, "total": {currency: 10000.0}}
            
        try:
            balance = await self.exchange.fetch_balance()
            return balance
        except Exception as e:
            logger.error(f"[{self.exchange_id}] 잔고 조회 에러: {e}")
            return {}

    async def create_order(self, symbol: str, side: str, amount: float, price: Optional[float] = None) -> Dict[str, Any]:
        """주문 실행 (시장가/지정가)."""
        if self.is_dry_run:
            logger.info(f"[DRY_RUN] 주문 시뮬레이션 ({self.exchange_id}): {side} {amount} {symbol}")
            return {"id": "dry_run_id", "status": "closed", "price": price or 1.0}

        try:
            if price:
                # 지정가 주문
                order = await self.exchange.create_limit_order(symbol, side, amount, price)
            else:
                # 시장가 주문
                # 주의: 업비트 매수(buy)는 amount가 '주문 총액(Cost)'이고, 
                #       HTX 매수(buy)는 amount가 '매수 수량(Quantity)'일 수 있음.
                #       ccxt가 대부분 처리해주지만, 거래소별 특성을 고려해야 함.
                if self.exchange_id == 'upbit' and side == 'buy':
                    # 업비트 시장가 매수는 cost(비용) 기준
                    order = await self.exchange.create_order(symbol, 'market', side, amount, price) # create_market_buy_order_with_cost 권장되나 ccxt 버전에 따라 다름
                else:
                    # 일반적인 시장가 주문 (수량 기준)
                    order = await self.exchange.create_market_order(symbol, side, amount)
            
            logger.info(f"주문 접수 성공: {order['id']}")
            return order
        except Exception as e:
            logger.error(f"[{self.exchange_id}] 주문 에러: {e}")
            return {}

    async def close(self):
        """연결 종료."""
        await self.exchange.close()
