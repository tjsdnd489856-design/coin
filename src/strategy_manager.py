"""
멀티 코인 대응 전략 관리자.
여러 코인의 시세 감시 및 포지션을 통합 관리.
"""
import asyncio
import os
from typing import Dict, Any, List
from src.connector.exchange_base import ExchangeConnector
from src.learner.online_learner import OnlineLearner
from src.learner.schema import TradeEvent
from src.strategy.scalping_strategy import ScalpingStrategy
from src.notifier.telegram_notifier import TelegramNotifier
from src.learner.utils import get_logger

logger = get_logger(__name__)


class StrategyManager:
    """여러 코인을 동시에 매매하는 통합 관리자."""

    def __init__(self):
        self.connector = ExchangeConnector()
        self.learner = OnlineLearner()
        self.notifier = TelegramNotifier()
        self.is_running = False
        
        # 설정에서 코인 목록 읽기
        symbols_str = os.getenv("SYMBOL_LIST", "BTC/KRW")
        self.symbols = [s.strip() for s in symbols_str.split(",")]
        
        # 코인별 개별 정보 저장소 (전략, 포지션)
        self.coin_data = {
            symbol: {
                'strategy': ScalpingStrategy(),
                'position': None
            } for symbol in self.symbols
        }

    async def _update_all_targets(self):
        """모든 코인의 목표가 갱신."""
        for symbol in self.symbols:
            ohlcv = await self.connector.fetch_ohlcv(symbol, limit=2)
            if len(ohlcv) >= 2:
                prev_day = {'high': ohlcv[0][2], 'low': ohlcv[0][3], 'close': ohlcv[0][4]}
                await self.coin_data[symbol]['strategy'].update_target_price(prev_day)
                logger.info(f"[{symbol}] 목표가 설정 완료")
            await asyncio.sleep(0.1) # 거래소 요청 제한 방지

    async def start(self):
        self.is_running = True
        await self.notifier.send_message(f"🚀 멀티 코인 매매 시스템 가동: {', '.join(self.symbols)}")
        await self._update_all_targets()

        while self.is_running:
            for symbol in self.symbols:
                try:
                    data = self.coin_data[symbol]
                    ticker = await self.connector.fetch_ticker(symbol)
                    if not ticker: continue

                    # A. 매수 탐색
                    if not data['position']:
                        event = TradeEvent(
                            trace_id=f"t_{int(asyncio.get_event_loop().time())}",
                            timestamp=None, exchange=self.connector.exchange_id,
                            symbol=symbol, side="buy", price=ticker['last'], quantity=0.001
                        )
                        ai_pred = await self.learner.predict(event)
                        
                        if await data['strategy'].check_signal(ticker, ai_pred.dict()):
                            balance = await self.connector.fetch_balance()
                            krw_free = balance.get('free', {}).get('KRW', 0)
                            # 코인 수만큼 자산 분할 투자 (예: 1/N)
                            invest_krw = krw_free / len(self.symbols)
                            amount = data['strategy'].calculate_amount(invest_krw, ticker['last'])
                            
                            if (amount * ticker['last']) > 5000:
                                order = await self.connector.create_order(symbol, "buy", amount)
                                if order:
                                    data['position'] = {'entry_price': ticker['last'], 'amount': amount}
                                    await self.notifier.send_message(f"🔔 [매수] {symbol}\n가격: {ticker['last']:,.0f}원")
                    
                    # B. 매도(손절/익절) 감시
                    else:
                        exit_type = data['strategy'].check_exit_signal(data['position']['entry_price'], ticker['last'])
                        if exit_type:
                            order = await self.connector.create_order(symbol, "sell", data['position']['amount'])
                            if order:
                                pnl = (ticker['last'] - data['position']['entry_price']) / data['position']['entry_price'] * 100
                                await self.notifier.send_message(f"📢 [{exit_type}] {symbol}\n수익률: {pnl:.2f}%")
                                data['position'] = None

                    await asyncio.sleep(0.2) # 코인 간 간격
                except Exception as e:
                    logger.error(f"[{symbol}] 루프 에러: {e}")

            await asyncio.sleep(1) # 한 바퀴 돌고 1초 휴식

    def stop(self):
        self.is_running = False
