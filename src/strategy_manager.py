"""
멀티 코인 및 멀티 전략 관리자.
1분 봉 대응 및 AI 피드백 루프(학습) 강화.
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
    """1분 봉 대응 및 학습 기능을 갖춘 통합 관리자."""

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
                'strategies': {
                    'trend': ScalpingStrategy(),
                    'reversal': ReversalStrategy()
                },
                'position': None,
            }
        
        self.last_indicator_update = None

    async def _handle_user_command(self):
        """텔레그램 명령 처리."""
        command = await self.notifier.get_recent_command()
        if command == "보고":
            await self._send_status_report()

    async def _send_status_report(self):
        """현재 시황 보고."""
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            msg = "📊 [1분 봉 스캔 중 - 시스템 보고]\n"
            msg += f"💰 가용 원화: {krw_free:,.0f}원\n\n"
            for symbol in self.symbols:
                ticker = await self.connector.fetch_ticker(symbol)
                pos = self.coin_data[symbol]['position']
                status = f"보유중 (수익: {(ticker['last']-pos['entry_price'])/pos['entry_price']*100:.2f}%)" if pos else "대기중"
                msg += f"- {symbol}: {ticker['last']:,.0f}원 | {status}\n"
            await self.notifier.send_message(msg)
        except Exception as e:
            logger.error(f"보고서 생성 에러: {e}")

    async def _update_all_indicators(self):
        """1분 봉 지표 갱신."""
        logger.info("1분 봉 지표 실시간 갱신 중...")
        for symbol in self.symbols:
            try:
                # 타임프레임을 1m으로 변경
                ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='1m', limit=100)
                if len(ohlcv) >= 30:
                    for strategy in self.coin_data[symbol]['strategies'].values():
                        await strategy.update_indicators(ohlcv)
                await asyncio.sleep(0.1) # 1분 봉은 더 빠른 처리가 필요함
            except Exception as e:
                logger.error(f"[{symbol}] 지표 갱신 에러: {e}")
        self.last_indicator_update = now_utc()

    async def start(self):
        """메인 매매 루프 (1분 단위 스캔)."""
        self.is_running = True
        await self.notifier.send_message("🚀 1분 봉 실시간 스캔 및 학습 모드 가동")
        await self._update_all_indicators()

        while self.is_running:
            try:
                now = now_utc()
                await self._handle_user_command()

                # 1. 매 분마다 지표 갱신
                if self.last_indicator_update is None or (now - self.last_indicator_update).total_seconds() >= 60:
                    await self._update_all_indicators()

                # 2. 실시간 매매 감시
                for symbol in self.symbols:
                    data = self.coin_data[symbol]
                    ticker = await self.connector.fetch_ticker(symbol)
                    if not ticker: continue

                    if not data['position']:
                        # 매수 감시
                        event = TradeEvent(
                            trace_id=f"t_{int(now.timestamp())}", timestamp=now, 
                            exchange=self.connector.exchange_id, symbol=symbol, side="buy", price=ticker['last'], quantity=0
                        )
                        ai_pred = await self.learner.predict(event)
                        
                        if await data['strategies']['trend'].check_signal(ticker, ai_pred.dict()):
                            await self._execute_buy(symbol, ticker, "trend")
                        elif await data['strategies']['reversal'].check_signal(ticker, ai_pred.dict()):
                            await self._execute_buy(symbol, ticker, "reversal")
                    else:
                        # 매도(청산) 감시 및 피드백(학습)
                        pos = data['position']
                        strategy = data['strategies'][pos['strategy_type']]
                        exit_type = strategy.check_exit_signal(pos['entry_price'], ticker['last'])
                        
                        if exit_type:
                            order = await self.connector.create_order(symbol, "sell", pos['amount'])
                            if order:
                                pnl_pct = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                                await self.notifier.send_message(f"📢 [매도] {symbol} ({exit_type})\n수익률: {pnl_pct:.2f}%")
                                
                                # [핵심] 경험 피드백: AI 모델에 거래 결과 전달
                                feedback_result = ExecutionResult(
                                    order_id=order.get('id', 'unknown'),
                                    actual_slippage=0.0, # 실제 슬리피지 계산 로직 추가 가능
                                    filled_quantity=pos['amount'],
                                    filled_price=ticker['last'],
                                    status="success",
                                    meta={"pnl": pnl_pct, "strategy": pos['strategy_type']}
                                )
                                await self.learner.feedback(feedback_result)
                                
                                data['position'] = None
                    await asyncio.sleep(0.05)

            except Exception as e:
                logger.error(f"메인 루프 에러: {e}")
                await asyncio.sleep(1)

            await asyncio.sleep(0.5)

    async def _execute_buy(self, symbol: str, ticker: Dict[str, Any], strategy_type: str):
        """매수 실행."""
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            invest_krw = krw_free / (len(self.symbols) + 1)
            
            if invest_krw < 5000: return
                
            strategy = self.coin_data[symbol]['strategies'][strategy_type]
            amount = strategy.calculate_amount(invest_krw, ticker['last'])
            
            order = await self.connector.create_order(symbol, "buy", amount)
            if order:
                self.coin_data[symbol]['position'] = {
                    'entry_price': ticker['last'], 'amount': amount, 'strategy_type': strategy_type
                }
                await self.notifier.send_message(f"🔔 [매수] {symbol} ({strategy_type})\n가격: {ticker['last']:,.0f}원")
        except Exception as e:
            logger.error(f"[{symbol}] 매수 실패: {e}")

    def stop(self):
        self.is_running = False
