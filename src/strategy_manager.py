"""
멀티 코인 및 멀티 전략 관리자 (하트비트 주기 조정 및 보고 기능 강화).
사용자 명령어 인식률을 높이고 로그 출력을 최적화함.
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
    """1시간 주기 하트비트 및 강화된 보고 기능을 갖춘 관리자."""

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
        self.last_heartbeat_time = None
        self.is_market_safe = True

    async def _check_market_sentiment(self):
        """시장 건전성 체크."""
        try:
            btc_ohlcv = await self.connector.fetch_ohlcv("BTC/KRW", timeframe='1m', limit=5)
            if btc_ohlcv and len(btc_ohlcv) >= 5:
                change_pct = (btc_ohlcv[-1][4] - btc_ohlcv[0][4]) / btc_ohlcv[0][4]
                self.is_market_safe = change_pct > -0.005
        except Exception:
            pass

    async def _update_all_indicators(self):
        """지표 최신화."""
        logger.info("📡 1분 봉 지표 및 AI 모델 동기화 중...")
        for symbol in self.symbols:
            try:
                ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='1m', limit=50)
                if ohlcv and len(ohlcv) >= 30:
                    for strategy in self.coin_data[symbol]['strategies'].values():
                        await strategy.update_indicators(ohlcv)
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"[{symbol}] 지표 업데이트 실패: {e}")
        self.last_indicator_update = now_utc()

    async def start(self):
        """메인 매매 루프."""
        self.is_running = True
        await self.notifier.send_message("💎 AI 지능형 매매 시스템 가동 (명령어 인식 강화)")
        await self._update_all_indicators()

        while self.is_running:
            try:
                now = now_utc()
                
                # 1. 텔레그램 명령 처리 (강화된 인식)
                cmd = await self.notifier.get_recent_command()
                if cmd and "보고" in cmd:
                    await self._send_status_report()

                # 2. 1시간(3600초)마다 하트비트 로그 출력
                if self.last_heartbeat_time is None or (now - self.last_heartbeat_time).total_seconds() >= 3600:
                    logger.info(f"💓 [정상 가동 중] 시장안전: {self.is_market_safe} | 코인: {', '.join(self.symbols)}")
                    self.last_heartbeat_time = now

                await self._check_market_sentiment()
                if self.last_indicator_update is None or (now - self.last_indicator_update).total_seconds() >= 60:
                    await self._update_all_indicators()

                for symbol in self.symbols:
                    try:
                        data = self.coin_data[symbol]
                        ticker = await self.connector.fetch_ticker(symbol)
                        if not ticker: continue

                        if not data['position']:
                            if not self.is_market_safe: continue
                            
                            event = TradeEvent(trace_id=f"t_{int(now.timestamp())}", exchange=self.connector.exchange_id, symbol=symbol, side="buy", price=ticker['last'], quantity=0)
                            ai_pred = await self.learner.predict(event)
                            
                            pred_dict = ai_pred.model_dump()
                            if await data['strategies']['trend'].check_signal(ticker, pred_dict):
                                await self._execute_buy(symbol, ticker, "trend")
                            elif await data['strategies']['reversal'].check_signal(ticker, pred_dict):
                                await self._execute_buy(symbol, ticker, "reversal")
                        else:
                            pos = data['position']
                            strategy = data['strategies'][pos['strategy_type']]
                            exit_type = strategy.check_exit_signal(pos['entry_price'], ticker['last'])
                            
                            if exit_type:
                                order = await self.connector.create_order(symbol, "sell", pos['amount'])
                                if order:
                                    pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                                    await self.notifier.send_message(f"💰 [매도 완료] {symbol}\n수익률: {pnl:.2f}% ({exit_type})")
                                    await self.learner.feedback(ExecutionResult(order_id=order.get('id', 'unknown'), filled_price=ticker['last'], pnl_pct=pnl/100.0, strategy_type=pos['strategy_type']))
                                    data['position'] = None
                    except Exception:
                        pass
                    await asyncio.sleep(0.05)

            except Exception as e:
                logger.error(f"메인 루프 오류: {e}")
                await asyncio.sleep(2)
            await asyncio.sleep(0.5)

    async def _send_status_report(self):
        """현재 시황 및 포지션 상세 보고."""
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            msg = "📊 [시스템 실시간 보고]\n"
            msg += f"💰 원화 잔고: {krw_free:,.0f}원\n"
            msg += f"🛡️ 시장 상태: {'안전' if self.is_market_safe else '위험(관망)'}\n\n"
            for symbol in self.symbols:
                ticker = await self.connector.fetch_ticker(symbol)
                pos = self.coin_data[symbol]['position']
                status = f"보유중 (PnL: {(ticker['last']-pos['entry_price'])/pos['entry_price']*100:.2f}%)" if pos else "신호 감시 중"
                msg += f"- {symbol}: {ticker['last']:,.0f}원 | {status}\n"
            await self.notifier.send_message(msg)
            logger.info("✅ 텔레그램 보고서 전송 완료")
        except Exception as e:
            logger.error(f"보고 실패: {e}")

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
                await self.notifier.send_message(f"🚀 [매수 완료] {symbol}\n전략: {strategy_type}")
        except Exception as e:
            logger.error(f"[{symbol}] 매수 실패: {e}")

    def stop(self):
        self.is_running = False
