"""
멀티 코인 및 멀티 전략 관리자.
15분 봉 대응 및 텔레그램 명령(보고) 처리 기능 포함.
"""
import asyncio
import os
from datetime import datetime
from typing import Dict, Any, List
from src.connector.exchange_base import ExchangeConnector
from src.learner.online_learner import OnlineLearner
from src.learner.schema import TradeEvent
from src.strategy.scalping_strategy import ScalpingStrategy
from src.strategy.reversal_strategy import ReversalStrategy
from src.notifier.telegram_notifier import TelegramNotifier
from src.learner.utils import get_logger, now_utc

logger = get_logger(__name__)


class StrategyManager:
    """사용자 명령 처리가 가능한 통합 관리자."""

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
        """텔레그램을 통한 사용자 명령 처리."""
        command = await self.notifier.get_recent_command()
        if not command:
            return

        if command == "보고":
            logger.info("사용자로부터 '보고' 명령 수신")
            await self._send_status_report()

    async def _send_status_report(self):
        """현재 시황 및 시스템 상태 상세 보고."""
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            
            msg = "📊 [현재 시스템 상태 보고]\n"
            msg += f"💰 가용 원화: {krw_free:,.0f}원\n\n"
            msg += "🔍 코인별 상태:\n"
            
            for symbol in self.symbols:
                ticker = await self.connector.fetch_ticker(symbol)
                pos = self.coin_data[symbol]['position']
                
                if pos:
                    pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                    status = f"보유중 (수익률: {pnl:.2f}%)"
                else:
                    status = "대기중 (신호 감시)"
                
                msg += f"- {symbol}: {ticker['last']:,.0f}원 | {status}\n"
            
            await self.notifier.send_message(msg)
        except Exception as e:
            logger.error(f"상태 보고 중 에러: {e}")

    async def _update_all_indicators(self):
        """15분 봉 지표 갱신."""
        logger.info("15분 봉 지표 갱신 진행...")
        for symbol in self.symbols:
            try:
                ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='15m', limit=100)
                if len(ohlcv) >= 30:
                    for s_name, strategy in self.coin_data[symbol]['strategies'].items():
                        await strategy.update_indicators(ohlcv)
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"[{symbol}] 지표 갱신 에러: {e}")
        
        self.last_indicator_update = now_utc()

    async def start(self):
        """메인 매매 루프."""
        self.is_running = True
        await self.notifier.send_message(f"🚀 시스템 시작 (대상: {', '.join(self.symbols)})\n'보고'를 입력하면 현재 상태를 알려드립니다.")
        await self._update_all_indicators()

        while self.is_running:
            try:
                now = now_utc()
                
                # 1. 사용자 명령 체크 (매 루프마다)
                await self._handle_user_command()

                # 2. 15분 주기 지표 갱신
                if (now.minute % 15 == 0 and now.second < 5) or self.last_indicator_update is None:
                    if self.last_indicator_update is None or (now - self.last_indicator_update).total_seconds() > 60:
                        await self._update_all_indicators()

                # 3. 실시간 매매 감시
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
                        # 매도(청산) 감시
                        pos = data['position']
                        strategy = data['strategies'][pos['strategy_type']]
                        exit_type = strategy.check_exit_signal(pos['entry_price'], ticker['last'])
                        
                        if exit_type:
                            order = await self.connector.create_order(symbol, "sell", pos['amount'])
                            if order:
                                pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                                # 거래 완료 즉시 보고 (기능 확인)
                                await self.notifier.send_message(
                                    f"📢 [매도 완료] {symbol}\n사유: {exit_type}\n수익률: {pnl:.2f}%"
                                )
                                data['position'] = None
                    await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"메인 루프 에러: {e}")
                await asyncio.sleep(5)

            await asyncio.sleep(1)

    async def _execute_buy(self, symbol: str, ticker: Dict[str, Any], strategy_type: str):
        """매수 실행 및 보고."""
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
                # 거래 완료 즉시 보고 (기능 확인)
                await self.notifier.send_message(
                    f"🔔 [매수 완료] {symbol}\n전략: {strategy_type}\n가격: {ticker['last']:,.0f}원"
                )
        except Exception as e:
            logger.error(f"[{symbol}] 매수 실패: {e}")

    def stop(self):
        self.is_running = False
