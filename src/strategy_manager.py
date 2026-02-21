"""
멀티 코인 및 멀티 전략 관리자.
비트코인 시장 지수(BTC Filter)를 통한 고승률 매매 제어 로직 포함.
"""
import asyncio
import os
from datetime import datetime
from typing import Dict, Any, List
from src.connector.exchange_base import ExchangeConnector
from src.learner.online_learner import OnlineLearner
from src.learner.schema import TradeEvent, ExecutionResult
from src.strategy.scalping_strategy import ScalpingStrategy
from src.strategy.reversal_strategy import ReversalStrategy
from src.notifier.telegram_notifier import TelegramNotifier
from src.learner.utils import get_logger, now_utc

logger = get_logger(__name__)


class StrategyManager:
    """시장 전체 흐름을 고려하는 고승률 관리자."""

    def __init__(self):
        self.connector = ExchangeConnector()
        self.learner = OnlineLearner()
        self.notifier = TelegramNotifier()
        self.is_running = False
        
        symbols_str = os.getenv("SYMBOL_LIST", "BTC/KRW,ETH/KRW,XRP/KRW")
        self.symbols = [s.strip() for s in symbols_str.split(",")]
        
        self.coin_data = {}
        for symbol in self.symbols:
            self.coin_data[symbol] = {
                'strategies': {'trend': ScalpingStrategy(), 'reversal': ReversalStrategy()},
                'position': None,
            }
        
        self.last_indicator_update = None
        self.is_market_safe = True # 시장 안전 여부 (BTC 기준)

    async def _check_market_sentiment(self):
        """비트코인 상태를 체크하여 시장의 안전성 판단."""
        try:
            # BTC/KRW의 1분 봉 최근 5개를 가져옴
            btc_ohlcv = await self.connector.fetch_ohlcv("BTC/KRW", timeframe='1m', limit=5)
            if len(btc_ohlcv) < 5: return True
            
            start_price = btc_ohlcv[0][4] # 5분 전 종가
            current_price = btc_ohlcv[-1][4] # 현재가
            change_pct = (current_price - start_price) / start_price
            
            # 비트코인이 5분 만에 0.5% 이상 급락 중이라면 시장이 위험하다고 판단
            if change_pct <= -0.005:
                if self.is_market_safe:
                    logger.warning(f"⚠️ 시장 위험 감지: BTC 5분간 {change_pct*100:.2f}% 하락. 매수 중단.")
                    self.is_market_safe = False
            else:
                if not self.is_market_safe:
                    logger.info("✅ 시장 안정화 확인. 매수 감시 재개.")
                    self.is_market_safe = True
        except Exception as e:
            logger.error(f"시장 감정 체크 에러: {e}")
            self.is_market_safe = True

    async def _update_all_indicators(self):
        """1분 봉 지표 갱신."""
        for symbol in self.symbols:
            try:
                ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='1m', limit=100)
                if len(ohlcv) >= 30:
                    for strategy in self.coin_data[symbol]['strategies'].values():
                        await strategy.update_indicators(ohlcv)
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"[{symbol}] 지표 갱신 에러: {e}")
        self.last_indicator_update = now_utc()

    async def start(self):
        """메인 매매 루프."""
        self.is_running = True
        await self.notifier.send_message("🚀 고승률 시장 필터(BTC Filter) 가동 시작")
        await self._update_all_indicators()

        while self.is_running:
            try:
                now = now_utc()
                # 텔레그램 명령 및 시장 심리 체크
                await self.notifier.get_recent_command() # 명령 수신만 (보고 기능은 생략 가능)
                await self._check_market_sentiment()

                if self.last_indicator_update is None or (now - self.last_indicator_update).total_seconds() >= 60:
                    await self._update_all_indicators()

                for symbol in self.symbols:
                    data = self.coin_data[symbol]
                    ticker = await self.connector.fetch_ticker(symbol)
                    if not ticker: continue

                    if not data['position']:
                        # [핵심] 시장이 안전할 때만 신규 매수 신호 감시
                        if not self.is_market_safe: continue
                        
                        event = TradeEvent(trace_id=f"t_{int(now.timestamp())}", timestamp=now, 
                                           exchange=self.connector.exchange_id, symbol=symbol, side="buy", price=ticker['last'], quantity=0)
                        ai_pred = await self.learner.predict(event)
                        
                        if await data['strategies']['trend'].check_signal(ticker, ai_pred.dict()):
                            await self._execute_buy(symbol, ticker, "trend")
                        elif await data['strategies']['reversal'].check_signal(ticker, ai_pred.dict()):
                            await self._execute_buy(symbol, ticker, "reversal")
                    else:
                        # 매도(청산)는 시장 상황과 관계없이 전략에 따라 실행
                        pos = data['position']
                        strategy = data['strategies'][pos['strategy_type']]
                        exit_type = strategy.check_exit_signal(pos['entry_price'], ticker['last'])
                        
                        if exit_type:
                            order = await self.connector.create_order(symbol, "sell", pos['amount'])
                            if order:
                                pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                                await self.notifier.send_message(f"📢 [매도] {symbol} ({exit_type}) 수익률: {pnl:.2f}%")
                                await self.learner.feedback(ExecutionResult(order_id=order.get('id', 'unknown'), filled_price=ticker['last'], status="success"))
                                data['position'] = None
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"메인 루프 에러: {e}")
                await asyncio.sleep(1)
            await asyncio.sleep(0.5)

    async def _execute_buy(self, symbol: str, ticker: Dict[str, Any], strategy_type: str):
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            invest_krw = krw_free / (len(self.symbols) + 1)
            if invest_krw < 5000: return
            strategy = self.coin_data[symbol]['strategies'][strategy_type]
            amount = strategy.calculate_amount(invest_krw, ticker['last'])
            order = await self.connector.create_order(symbol, "buy", amount)
            if order:
                self.coin_data[symbol]['position'] = {'entry_price': ticker['last'], 'amount': amount, 'strategy_type': strategy_type}
                await self.notifier.send_message(f"🔔 [매수] {symbol} ({strategy_type})")
        except Exception as e:
            logger.error(f"[{symbol}] 매수 실패: {e}")

    def stop(self):
        self.is_running = False
