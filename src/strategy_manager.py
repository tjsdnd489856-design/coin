"""
전략들을 관리하고 실제 거래소/학습 모듈과 연결하여 실행하는 관리자.
"""
import asyncio
from typing import Optional
from src.connector.exchange_base import ExchangeConnector
from src.learner.online_learner import OnlineLearner
from src.learner.schema import TradeEvent
from src.strategy.scalping_strategy import ScalpingStrategy
from src.notifier.telegram_notifier import TelegramNotifier
from src.learner.utils import get_logger

logger = get_logger(__name__)


class StrategyManager:
    """전략 실행 및 전체 루프 관리자."""

    def __init__(self):
        self.connector = ExchangeConnector()
        self.learner = OnlineLearner()
        self.strategy = ScalpingStrategy()
        self.notifier = TelegramNotifier() # 알림 기능 추가
        self.symbol = "BTC/USDT"
        self.is_running = False

    async def _update_strategy_target(self):
        """거래소에서 실제 데이터를 가져와 전략 목표가 갱신."""
        ohlcv = await self.connector.fetch_ohlcv(self.symbol, timeframe='1d', limit=2)
        if len(ohlcv) >= 2:
            prev_day = {
                'high': ohlcv[0][2],
                'low': ohlcv[0][3],
                'close': ohlcv[0][4]
            }
            await self.strategy.update_target_price(prev_day)
            msg = f"✅ [{self.symbol}] 전략 목표가 갱신 완료: {self.strategy.target_price}"
            await self.notifier.send_message(msg)
        else:
            logger.error("데이터 부족으로 목표가를 설정할 수 없습니다.")

    async def start(self):
        """매매 루프 시작."""
        self.is_running = True
        await self.notifier.send_message(f"🚀 {self.symbol} 자동 매매 시스템 가동 시작")
        
        await self._update_strategy_target()

    # ... (기존 루프 로직 유지하되 주문 시 알림 추가)
        while self.is_running:
            try:
                ticker = await self.connector.fetch_ticker(self.symbol)
                if not ticker:
                    await asyncio.sleep(1)
                    continue

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
                
                if await self.strategy.check_signal(ticker, ai_pred.dict()):
                    logger.info(">>> 매수 신호 발생!")
                    
                    # 주문 실행
                    order = await self.connector.create_order(self.symbol, "buy", 0.001)
                    
                    if order:
                        # 텔레그램 알림 전송
                        await self.notifier.send_message(
                            f"🔔 [매수 주문 발생]\n심볼: {self.symbol}\n가격: {ticker['last']}\n결과: {order.get('status')}"
                        )
                    
                    await asyncio.sleep(600)
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"루프 에러: {e}")
                await self.notifier.send_message(f"⚠️ 시스템 루프 에러 발생: {e}")
                await asyncio.sleep(5)

    def stop(self):
        self.is_running = False
        logger.info("자동 매매를 중단합니다.")
