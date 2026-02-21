"""
멀티 코인 및 멀티 전략 관리자.
15분 봉 기반 실시간 지표 갱신 및 매매 로직 통합.
"""
import asyncio
import os
from datetime import datetime, timedelta
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
    """15분 타임프레임 대응 통합 관리자."""

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
        
        self.last_indicator_update = None # 마지막 지표 갱신 시간

    async def _update_all_indicators(self):
        """모든 전략의 지표를 15분 봉 기준으로 갱신."""
        logger.info("모든 전략의 15분 봉 지표 갱신 시작...")
        for symbol in self.symbols:
            try:
                # 15분(15m) 데이터 수집
                ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='15m', limit=100)
                if len(ohlcv) >= 30:
                    for s_name, strategy in self.coin_data[symbol]['strategies'].items():
                        await strategy.update_indicators(ohlcv)
                
                # 거래소 API 부하 방지를 위한 짧은 대기
                await asyncio.sleep(0.3) 
            except Exception as e:
                logger.error(f"[{symbol}] 지표 갱신 에러: {e}")
        
        self.last_indicator_update = now_utc()
        logger.info("모든 지표 갱신 완료.")

    async def start(self):
        """메인 매매 루프 시작."""
        self.is_running = True
        await self.notifier.send_message(f"🚀 15분 봉 고빈도 매매 시스템 가동\n대상: {', '.join(self.symbols)}")
        
        # 시작 시 즉시 한 번 갱신
        await self._update_all_indicators()

        while self.is_running:
            try:
                now = now_utc()
                
                # 1. 15분 주기로 지표 자동 갱신 (정각, 15분, 30분, 45분)
                if (now.minute % 15 == 0 and now.second < 5) or self.last_indicator_update is None:
                    # 중복 실행 방지 (이미 최근 1분 내에 갱신했다면 패스)
                    if self.last_indicator_update is None or (now - self.last_indicator_update).total_seconds() > 60:
                        await self._update_all_indicators()

                # 2. 매 6시간마다 생존 신고 및 자산 보고
                if now.minute == 0 and now.hour % 6 == 0 and now.second < 5:
                    balance = await self.connector.fetch_balance()
                    krw_free = balance.get('free', {}).get('KRW', 0)
                    await self.notifier.send_message(f"✅ 시스템 정상 가동 중\n💰 현재 가용 원화: {krw_free:,.0f}원")

                # 3. 실시간 매매 신호 감시
                for symbol in self.symbols:
                    data = self.coin_data[symbol]
                    ticker = await self.connector.fetch_ticker(symbol)
                    if not ticker:
                        continue

                    # 포지션이 없는 경우: 매수 신호 확인
                    if not data['position']:
                        # AI 예측 데이터 생성 (트레이스 ID 포함)
                        event = TradeEvent(
                            trace_id=f"t_{int(now.timestamp())}",
                            timestamp=now, 
                            exchange=self.connector.exchange_id,
                            symbol=symbol, side="buy", price=ticker['last'], quantity=0
                        )
                        ai_pred = await self.learner.predict(event)
                        
                        # 각 전략별 매수 조건 체크
                        if await data['strategies']['trend'].check_signal(ticker, ai_pred.dict()):
                            await self._execute_buy(symbol, ticker, "trend")
                        elif await data['strategies']['reversal'].check_signal(ticker, ai_pred.dict()):
                            await self._execute_buy(symbol, ticker, "reversal")
                    
                    # 포지션이 있는 경우: 매도(청산) 신호 확인
                    else:
                        pos = data['position']
                        strategy = data['strategies'][pos['strategy_type']]
                        exit_type = strategy.check_exit_signal(pos['entry_price'], ticker['last'])
                        
                        if exit_type:
                            order = await self.connector.create_order(symbol, "sell", pos['amount'])
                            if order:
                                pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                                await self.notifier.send_message(
                                    f"📢 [{exit_type}] {symbol} 매도 완료\n익청구분: {pos['strategy_type']}\n수익률: {pnl:.2f}%"
                                )
                                data['position'] = None
                    
                    await asyncio.sleep(0.1) # 코인 간 간격

            except Exception as e:
                logger.error(f"메인 루프 에러: {e}")
                await asyncio.sleep(5)

            await asyncio.sleep(1) # 기본 루프 주기

    async def _execute_buy(self, symbol: str, ticker: Dict[str, Any], strategy_type: str):
        """실제 매수 주문 실행 및 알림."""
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            
            # 총 자산의 일부를 코인별로 분할 투자
            invest_krw = krw_free / (len(self.symbols) + 1) # 여유 자금 확보
            if invest_krw < 5000:
                return # 최소 주문 금액 미달
                
            strategy = self.coin_data[symbol]['strategies'][strategy_type]
            amount = strategy.calculate_amount(invest_krw, ticker['last'])
            
            order = await self.connector.create_order(symbol, "buy", amount)
            if order:
                self.coin_data[symbol]['position'] = {
                    'entry_price': ticker['last'],
                    'amount': amount,
                    'strategy_type': strategy_type
                }
                await self.notifier.send_message(
                    f"🔔 [매수] {symbol} 진입\n전략: {strategy_type}\n가격: {ticker['last']:,.0f}원"
                )
        except Exception as e:
            logger.error(f"[{symbol}] 매수 주문 실패: {e}")

    def stop(self):
        self.is_running = False
