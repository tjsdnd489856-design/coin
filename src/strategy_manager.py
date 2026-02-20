"""
멀티 코인 및 멀티 전략 관리자.
추세 추종 및 역추세 전략 통합 관리 및 정기 보고 기능 추가.
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
    """여러 코인과 전략을 동시에 운용하는 통합 관리자."""

    def __init__(self):
        self.connector = ExchangeConnector()
        self.learner = OnlineLearner()
        self.notifier = TelegramNotifier()
        self.is_running = False
        
        symbols_str = os.getenv("SYMBOL_LIST", "BTC/KRW,ETH/KRW,XRP/KRW")
        self.symbols = [s.strip() for s in symbols_str.split(",")]
        
        # 코인별 데이터 구조
        self.coin_data = {}
        for symbol in self.symbols:
            self.coin_data[symbol] = {
                'strategies': {
                    'trend': ScalpingStrategy(),
                    'reversal': ReversalStrategy()
                },
                'position': None,
            }
        
        # 정기 보고용 변수
        self.last_report_date = "" # 마지막으로 보고서를 보낸 날짜 (YYYY-MM-DD)

    async def _update_all_indicators(self):
        """모든 전략의 지표 갱신."""
        logger.info("모든 전략의 지표 갱신 시작...")
        for symbol in self.symbols:
            ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='1d', limit=50)
            if len(ohlcv) >= 20:
                for s_name, strategy in self.coin_data[symbol]['strategies'].items():
                    await strategy.update_indicators(ohlcv)
            await asyncio.sleep(0.1)

    async def _send_daily_report(self):
        """매일 오전 정기 자산 및 시장 상태 보고."""
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            total_equity = balance.get('total', {}).get('KRW', krw_free) # 단순화된 계산
            
            report_msg = "📊 [정기 보고서] 현재 시스템 상태\n\n"
            report_msg += f"💰 가용 원화: {krw_free:,.0f}원\n"
            
            report_msg += "\n🔍 코인별 지표 상태:\n"
            for symbol in self.symbols:
                strat = self.coin_data[symbol]['strategies']['trend']
                pos = self.coin_data[symbol]['position']
                
                status = "대기중"
                if pos:
                    ticker = await self.connector.fetch_ticker(symbol)
                    pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                    status = f"보유중 ({pnl:.2f}%)"
                
                report_msg += f"- {symbol}: {status} | RSI: {strat.rsi:.1f}\n"
            
            await self.notifier.send_message(report_msg)
            logger.info("정기 보고서 전송 완료")
        except Exception as e:
            logger.error(f"보고서 전송 중 에러: {e}")

    async def start(self):
        self.is_running = True
        await self.notifier.send_message(f"🚀 듀얼 전략 시스템 가동: {', '.join(self.symbols)}\n(정기 보고: 매일 오전 10시)")
        await self._update_all_indicators()

        while self.is_running:
            now = now_utc()
            
            # [추가] 매일 오전 10시 정기 보고 체크
            # 한국 시간 기준 (GCP 서버는 UTC일 수 있으므로 시간 계산 주의)
            # 여기서는 9시간 차이를 고려하거나, 단순하게 로컬 시간 기준 10시 체크
            current_date = now.strftime("%Y-%m-%d")
            if now.hour == 10 and self.last_report_date != current_date:
                await self._send_daily_report()
                self.last_report_date = current_date
                # 지표도 하루 한 번 이때 갱신
                await self._update_all_indicators()

            for symbol in self.symbols:
                try:
                    data = self.coin_data[symbol]
                    ticker = await self.connector.fetch_ticker(symbol)
                    if not ticker: continue

                    if not data['position']:
                        event = TradeEvent(
                            trace_id=f"t_{int(asyncio.get_event_loop().time())}",
                            timestamp=now, 
                            exchange=self.connector.exchange_id,
                            symbol=symbol, side="buy", price=ticker['last'], quantity=0.001
                        )
                        ai_pred = await self.learner.predict(event)
                        
                        if await data['strategies']['trend'].check_signal(ticker, ai_pred.dict()):
                            await self._execute_buy(symbol, ticker, "trend")
                        elif await data['strategies']['reversal'].check_signal(ticker, ai_pred.dict()):
                            await self._execute_buy(symbol, ticker, "reversal")
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
