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

    async def _update_all_indicators(self):
        """모든 코인의 기술적 지표(MA, RSI, 목표가) 갱신."""
        logger.info("모든 코인의 지표 갱신을 시작합니다...")
        for symbol in self.symbols:
            # MA20, RSI14 계산을 위해 넉넉하게 50개의 캔들을 가져옴
            ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='1d', limit=50)
            if len(ohlcv) >= 20:
                await self.coin_data[symbol]['strategy'].update_indicators(ohlcv)
                logger.info(f"[{symbol}] 지표 설정 완료")
            else:
                logger.warning(f"[{symbol}] 데이터 부족으로 지표 설정 실패 (데이터 수: {len(ohlcv)})")
            await asyncio.sleep(0.1) # 거래소 요청 제한 방지

    async def start(self):
        self.is_running = True
        await self.notifier.send_message(f"🚀 멀티 코인 매매 시스템 가동: {', '.join(self.symbols)}")
        
        # 시작 전 지표 초기화
        await self._update_all_indicators()

        while self.is_running:
            for symbol in self.symbols:
                try:
                    data = self.coin_data[symbol]
                    ticker = await self.connector.fetch_ticker(symbol)
                    if not ticker: continue

                    # A. 매수 탐색
                    if not data['position']:
                        # AI 예측을 위한 이벤트 생성
                        event = TradeEvent(
                            trace_id=f"t_{int(asyncio.get_event_loop().time())}",
                            timestamp=None, exchange=self.connector.exchange_id,
                            symbol=symbol, side="buy", price=ticker['last'], quantity=0.001
                        )
                        ai_pred = await self.learner.predict(event)
                        
                        # 지표 + AI 조건을 모두 체크
                        if await data['strategy'].check_signal(ticker, ai_pred.dict()):
                            balance = await self.connector.fetch_balance()
                            krw_free = balance.get('free', {}).get('KRW', 0)
                            
                            # 코인 수만큼 자산 분할 투자
                            invest_krw = krw_free / len(self.symbols)
                            amount = data['strategy'].calculate_amount(invest_krw, ticker['last'])
                            
                            # 업비트 최소 주문 금액 5,000원 확인
                            if (amount * ticker['last']) > 5000:
                                order = await self.connector.create_order(symbol, "buy", amount)
                                if order:
                                    data['position'] = {'entry_price': ticker['last'], 'amount': amount}
                                    await self.notifier.send_message(
                                        f"🔔 [매수] {symbol}\n"
                                        f"가격: {ticker['last']:,.0f}원\n"
                                        f"RSI: {data['strategy'].rsi:.2f}\n"
                                        f"상태: 정배열(상승추세)"
                                    )
                    
                    # B. 매도(손절/익절) 감시
                    else:
                        exit_type = data['strategy'].check_exit_signal(data['position']['entry_price'], ticker['last'])
                        if exit_type:
                            order = await self.connector.create_order(symbol, "sell", data['position']['amount'])
                            if order:
                                pnl = (ticker['last'] - data['position']['entry_price']) / data['position']['entry_price'] * 100
                                await self.notifier.send_message(
                                    f"📢 [{exit_type}] {symbol}\n"
                                    f"매도가: {ticker['last']:,.0f}원\n"
                                    f"수익률: {pnl:.2f}%"
                                )
                                data['position'] = None

                    await asyncio.sleep(0.2) # 코인 간 간격
                except Exception as e:
                    logger.error(f"[{symbol}] 루프 에러: {e}")

            # 매시간 정각마다 지표 갱신 (선택 사항, 여기서는 루프마다 혹은 특정 주기로 갱신 가능)
            # 여기서는 단순화를 위해 루프는 계속 돌고, 지표는 시작 시 갱신하도록 유지
            await asyncio.sleep(1) 

    def stop(self):
        self.is_running = False
