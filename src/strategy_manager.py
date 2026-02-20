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

    async def _update_strategy_target(self):
        """거래소에서 실제 데이터를 가져와 전략 목표가 갱신."""
        ohlcv = await self.connector.fetch_ohlcv(self.symbol, timeframe='1d', limit=2)
        if len(ohlcv) >= 2:
            # ohlcv[0]은 전일 데이터: [timestamp, open, high, low, close, volume]
            prev_day = {
                'high': ohlcv[0][2],
                'low': ohlcv[0][3],
                'close': ohlcv[0][4]
            }
            await self.strategy.update_target_price(prev_day)
            logger.info(f"실제 시장 데이터 기반 목표가 설정 완료.")
        else:
            logger.error("데이터 부족으로 목표가를 설정할 수 없습니다.")

    async def start(self):
        """매매 루프 시작."""
        self.is_running = True
        logger.info(f"{self.symbol} 자동 매매를 시작합니다.")
        
        # 1. 실제 데이터 기반으로 첫 목표가 설정
        await self._update_strategy_target()

        while self.is_running:
            try:
                # 2. 실시간 시세 조회
                ticker = await self.connector.fetch_ticker(self.symbol)
                if not ticker:
                    await asyncio.sleep(1)
                    continue

                # 3. AI 학습 모듈에 조언 요청
                event = TradeEvent(
                    trace_id=f"tick_{int(asyncio.get_event_loop().time())}",
                    timestamp=None,
                    exchange=self.connector.exchange_id,
                    symbol=self.symbol,
                    side="buy",
                    price=ticker['last'],
                    quantity=0.01
                )
                ai_pred = await self.learner.predict(event)
                
                # 4. 전략 신호 확인
                if await self.strategy.check_signal(ticker, ai_pred.dict()):
                    logger.info(f">>> 매수 신호 발생! 현재가({ticker['last']})가 목표가({self.strategy.target_price})를 돌파했습니다.")
                    
                    # 5. 주문 실행
                    await self.connector.create_order(self.symbol, "buy", 0.001)
                    
                    # 주문 후 한동안 대기 (중복 주문 방지)
                    await asyncio.sleep(600) # 10분 대기
                
                # 매일 자정쯤(또는 주기적으로) 목표가 재계산 필요 (여기서는 매 루프마다 체크는 생략)
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"루프 에러: {e}")
                await asyncio.sleep(5)

    def stop(self):
        """매매 루프 중단."""
        self.is_running = False
        logger.info("자동 매매를 중단합니다.")
