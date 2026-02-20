"""
전략 관리자: 자산 관리 및 포지션 감시 로직 통합.
"""
import asyncio
from src.connector.exchange_base import ExchangeConnector
from src.learner.online_learner import OnlineLearner
from src.learner.schema import TradeEvent
from src.strategy.scalping_strategy import ScalpingStrategy
from src.notifier.telegram_notifier import TelegramNotifier
from src.learner.utils import get_logger

logger = get_logger(__name__)


class StrategyManager:
    """전략 실행 및 리스크 관리자."""

    def __init__(self):
        self.connector = ExchangeConnector()
        self.learner = OnlineLearner()
        self.strategy = ScalpingStrategy()
        self.notifier = TelegramNotifier()
        self.symbol = "BTC/USDT"
        self.is_running = False
        self.position = None # 현재 보유 포지션 정보

    async def _update_strategy_target(self):
        ohlcv = await self.connector.fetch_ohlcv(self.symbol, limit=2)
        if len(ohlcv) >= 2:
            prev_day = {'high': ohlcv[0][2], 'low': ohlcv[0][3], 'close': ohlcv[0][4]}
            await self.strategy.update_target_price(prev_day)

    async def start(self):
        self.is_running = True
        await self.notifier.send_message(f"🚀 {self.symbol} 자동 매매 및 리스크 관리 시스템 가동")
        await self._update_strategy_target()

        while self.is_running:
            try:
                ticker = await self.connector.fetch_ticker(self.symbol)
                if not ticker:
                    await asyncio.sleep(1)
                    continue

                # A. 포지션이 없을 때: 매수 기회 탐색
                if not self.position:
                    event = TradeEvent(
                        trace_id=f"t_{int(asyncio.get_event_loop().time())}",
                        timestamp=None, exchange=self.connector.exchange_id,
                        symbol=self.symbol, side="buy", price=ticker['last'], quantity=0.01
                    )
                    ai_pred = await self.learner.predict(event)
                    
                    if await self.strategy.check_signal(ticker, ai_pred.dict()):
                        # 1. 잔고 확인
                        balance = await self.connector.fetch_balance()
                        usdt_free = balance.get('free', {}).get('USDT', 0)
                        
                        # 2. 수량 계산
                        amount = self.strategy.calculate_amount(usdt_free, ticker['last'])
                        
                        if amount > 0:
                            order = await self.connector.create_order(self.symbol, "buy", amount)
                            if order:
                                self.position = {'entry_price': ticker['last'], 'amount': amount}
                                await self.notifier.send_message(f"🔔 [매수 체결]\n가격: {ticker['last']}\n수량: {amount:.4f}")
                
                # B. 포지션이 있을 때: 손절/익절 감시
                else:
                    exit_type = self.strategy.check_exit_signal(self.position['entry_price'], ticker['last'])
                    if exit_type:
                        logger.info(f">>> {exit_type} 신호 발생! 전량 매도합니다.")
                        order = await self.connector.create_order(self.symbol, "sell", self.position['amount'])
                        if order:
                            pnl = (ticker['last'] - self.position['entry_price']) / self.position['entry_price'] * 100
                            await self.notifier.send_message(f"📢 [{exit_type} 매도 완료]\n가격: {ticker['last']}\n수익률: {pnl:.2f}%")
                            self.position = None # 포지션 초기화
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"루프 에러: {e}")
                await asyncio.sleep(5)

    def stop(self):
        self.is_running = False
