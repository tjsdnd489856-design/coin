"""
멀티 코인 및 멀티 전략 관리자.
추세 추종(Scalping) 및 역추세(Reversal) 전략을 통합 관리.
"""
import asyncio
import os
from typing import Dict, Any, List
from src.connector.exchange_base import ExchangeConnector
from src.learner.online_learner import OnlineLearner
from src.learner.schema import TradeEvent
from src.strategy.scalping_strategy import ScalpingStrategy
from src.strategy.reversal_strategy import ReversalStrategy
from src.notifier.telegram_notifier import TelegramNotifier
from src.learner.utils import get_logger

logger = get_logger(__name__)


class StrategyManager:
    """여러 코인과 전략을 동시에 운용하는 통합 관리자."""

    def __init__(self):
        self.connector = ExchangeConnector()
        self.learner = OnlineLearner()
        self.notifier = TelegramNotifier()
        self.is_running = False
        
        symbols_str = os.getenv("SYMBOL_LIST", "BTC/KRW")
        self.symbols = [s.strip() for s in symbols_str.split(",")]
        
        # 코인별 데이터 구조 확장 (전략 리스트화)
        self.coin_data = {}
        for symbol in self.symbols:
            self.coin_data[symbol] = {
                'strategies': {
                    'trend': ScalpingStrategy(),
                    'reversal': ReversalStrategy()
                },
                'position': None, # { 'entry_price', 'amount', 'strategy_type' }
            }

    async def _update_all_indicators(self):
        """모든 전략의 지표 갱신."""
        logger.info("모든 전략의 지표 갱신 시작...")
        for symbol in self.symbols:
            ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='1d', limit=50)
            if len(ohlcv) >= 20:
                # 해당 코인의 모든 전략 지표 갱신
                for s_name, strategy in self.coin_data[symbol]['strategies'].items():
                    await strategy.update_indicators(ohlcv)
                logger.info(f"[{symbol}] 모든 전략 지표 설정 완료")
            await asyncio.sleep(0.1)

    async def start(self):
        self.is_running = True
        await self.notifier.send_message(f"🚀 듀얼 전략 시스템 가동: {', '.join(self.symbols)}\n(추세 추종 + 역추세)")
        await self._update_all_indicators()

        while self.is_running:
            for symbol in self.symbols:
                try:
                    data = self.coin_data[symbol]
                    ticker = await self.connector.fetch_ticker(symbol)
                    if not ticker: continue

                    # A. 매수 탐색 (포지션이 없을 때)
                    if not data['position']:
                        event = TradeEvent(
                            trace_id=f"t_{int(asyncio.get_event_loop().time())}",
                            timestamp=None, exchange=self.connector.exchange_id,
                            symbol=symbol, side="buy", price=ticker['last'], quantity=0.001
                        )
                        ai_pred = await self.learner.predict(event)
                        
                        # 1. 추세 추종 전략 체크
                        if await data['strategies']['trend'].check_signal(ticker, ai_pred.dict()):
                            await self._execute_buy(symbol, ticker, "trend")
                            
                        # 2. 역추세 전략 체크 (추세 신호가 없을 때만 혹은 별개로 수행 가능)
                        elif await data['strategies']['reversal'].check_signal(ticker, ai_pred.dict()):
                            await self._execute_buy(symbol, ticker, "reversal")
                    
                    # B. 매도 감시 (포지션이 있을 때)
                    else:
                        pos = data['position']
                        strategy = data['strategies'][pos['strategy_type']]
                        exit_type = strategy.check_exit_signal(pos['entry_price'], ticker['last'])
                        
                        if exit_type:
                            order = await self.connector.create_order(symbol, "sell", pos['amount'])
                            if order:
                                pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                                await self.notifier.send_message(
                                    f"📢 [{exit_type}] {symbol}\n"
                                    f"전략: {pos['strategy_type']}\n"
                                    f"수익률: {pnl:.2f}%"
                                )
                                data['position'] = None

                    await asyncio.sleep(0.2)
                except Exception as e:
                    logger.error(f"[{symbol}] 루프 에러: {e}")

            await asyncio.sleep(1)

    async def _execute_buy(self, symbol: str, ticker: Dict[str, Any], strategy_type: str):
        """매수 실행 공통 로직."""
        data = self.coin_data[symbol]
        balance = await self.connector.fetch_balance()
        krw_free = balance.get('free', {}).get('KRW', 0)
        
        invest_krw = krw_free / len(self.symbols)
        strategy = data['strategies'][strategy_type]
        amount = strategy.calculate_amount(invest_krw, ticker['last'])
        
        if (amount * ticker['last']) > 5000:
            order = await self.connector.create_order(symbol, "buy", amount)
            if order:
                data['position'] = {
                    'entry_price': ticker['last'], 
                    'amount': amount,
                    'strategy_type': strategy_type
                }
                await self.notifier.send_message(
                    f"🔔 [매수] {symbol} ({strategy_type})\n"
                    f"가격: {ticker['last']:,.0f}원\n"
                    f"RSI: {strategy.rsi:.2f}"
                )

    def stop(self):
        self.is_running = False
