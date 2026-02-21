"""
멀티 코인 및 멀티 전략 관리자.
AI 자가 학습 피드백(ExecutionResult) 루프 연동.
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
    """AI 자가 학습 기반의 지능형 관리자."""

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
        self.is_market_safe = True

    async def _check_market_sentiment(self):
        """비트코인 상태 체크 (시장 지수)."""
        try:
            btc_ohlcv = await self.connector.fetch_ohlcv("BTC/KRW", timeframe='1m', limit=5)
            if len(btc_ohlcv) < 5: return
            change_pct = (btc_ohlcv[-1][4] - btc_ohlcv[0][4]) / btc_ohlcv[0][4]
            self.is_market_safe = change_pct > -0.005 # 5분간 -0.5% 이상 하락 시 위험
        except Exception as e:
            logger.error(f"Market sentiment error: {e}")

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
                logger.error(f"[{symbol}] Indicator update error: {e}")
        self.last_indicator_update = now_utc()

    async def start(self):
        """메인 매매 루프 시작."""
        self.is_running = True
        await self.notifier.send_message("🚀 AI 자가 학습 및 적응형 매매 엔진 가동")
        await self._update_all_indicators()

        while self.is_running:
            try:
                now = now_utc()
                await self.notifier.get_recent_command()
                await self._check_market_sentiment()

                if self.last_indicator_update is None or (now - self.last_indicator_update).total_seconds() >= 60:
                    await self._update_all_indicators()

                for symbol in self.symbols:
                    data = self.coin_data[symbol]
                    ticker = await self.connector.fetch_ticker(symbol)
                    if not ticker: continue

                    # [핵심] 매수 신호 감시
                    if not data['position']:
                        if not self.is_market_safe: continue
                        
                        # AI에게 현재 상황에 맞는 최적 파라미터 예측 요청
                        event = TradeEvent(trace_id=f"t_{int(now.timestamp())}", symbol=symbol, side="buy", price=ticker['last'], quantity=0)
                        ai_pred = await self.learner.predict(event)
                        
                        # AI가 준 파라미터(ai_pred.dict())로 전략 체크
                        if await data['strategies']['trend'].check_signal(ticker, ai_pred.model_dump()):
                            await self._execute_buy(symbol, ticker, "trend")
                        elif await data['strategies']['reversal'].check_signal(ticker, ai_pred.model_dump()):
                            await self._execute_buy(symbol, ticker, "reversal")
                    
                    # [핵심] 매도 신호 감시 및 피드백 학습
                    else:
                        pos = data['position']
                        strategy = data['strategies'][pos['strategy_type']]
                        exit_type = strategy.check_exit_signal(pos['entry_price'], ticker['last'])
                        
                        if exit_type:
                            order = await self.connector.create_order(symbol, "sell", pos['amount'])
                            if order:
                                pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                                await self.notifier.send_message(f"📢 [매도] {symbol} ({exit_type}) 수익: {pnl:.2f}%")
                                
                                # AI에게 매매 결과 피드백 (PnL 포함)
                                result = ExecutionResult(
                                    order_id=order.get('id', 'unknown'),
                                    filled_price=ticker['last'],
                                    filled_quantity=pos['amount'],
                                    pnl_pct=pnl / 100.0, # 학습용 수익률
                                    strategy_type=pos['strategy_type']
                                )
                                await self.learner.feedback(result)
                                
                                data['position'] = None
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Loop error: {e}")
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
