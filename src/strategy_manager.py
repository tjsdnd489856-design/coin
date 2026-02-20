"""
전략들을 관리하고 실제 거래소/학습 모듈과 연결하여 실행하는 관리자.
"""
import asyncio
from typing import Optional
from src.connector.exchange_base import ExchangeConnector
from src.learner.online_learner import OnlineLearner
from src.learner.schema import TradeEvent
from src.strategy.scalping_strategy import ScalpingStrategy
from src.learner.utils import get_logger

logger = get_logger(__name__)


class StrategyManager:
    """전략 실행 및 전체 루프 관리자."""

    def __init__(self):
        self.connector = ExchangeConnector()
        self.learner = OnlineLearner()
        self.strategy = ScalpingStrategy()
        self.symbol = "BTC/USDT"
        self.is_running = False

    async def start(self):
        """매매 루프 시작."""
        self.is_running = True
        logger.info(f"{self.symbol} 자동 매매를 시작합니다.")
        
        # 최초 목표가 설정 (실제로는 API로 전일 OHLCV 가져와야 함)
        await self.strategy.update_target_price({'high': 51000, 'low': 49000, 'close': 50000})

        while self.is_running:
            try:
                # 1. 시세 조회
                ticker = await self.connector.fetch_ticker(self.symbol)
                
                # 2. AI 학습 모듈에 조언 요청
                event = TradeEvent(
                    trace_id=f"tick_{int(asyncio.get_event_loop().time())}",
                    timestamp=None, # utils에서 처리 가능
                    exchange=self.connector.exchange_id,
                    symbol=self.symbol,
                    side="buy",
                    price=ticker['last'],
                    quantity=0.01
                )
                ai_pred = await self.learner.predict(event)
                
                # 3. 전략 신호 확인
                if await self.strategy.check_signal(ticker, ai_pred.dict()):
                    logger.info(">>> 매수 신호 발생! 주문을 실행합니다.")
                    # 4. 주문 실행
                    await self.connector.create_order(self.symbol, "buy", 0.001)
                    # 주문 후 루프 일시 정지 (과도한 주문 방지)
                    await asyncio.sleep(60)
                
                await asyncio.sleep(1) # 1초마다 반복
                
            except Exception as e:
                logger.error(f"루프 에러: {e}")
                await asyncio.sleep(5)

    def stop(self):
        """매매 루프 중단."""
        self.is_running = False
        logger.info("자동 매매를 중단합니다.")
