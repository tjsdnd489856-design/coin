"""
멀티 코인 및 멀티 전략 관리자.
보유 코인 실시간 추적 및 초고속 매도 대응 기능이 강화되었습니다.
"""
import asyncio
import os
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List
from src.connector.exchange_base import ExchangeConnector
from src.learner.online_learner import OnlineLearner
from src.learner.schema import TradeEvent, ExecutionResult
from src.strategy.scalping_strategy import ScalpingStrategy
from src.notifier.telegram_notifier import TelegramNotifier
from src.learner.utils import get_logger, now_utc

logger = get_logger(__name__)


class StrategyManager:
    """매매 시스템의 중앙 제어 장치."""

    def __init__(self):
        """초기화 및 설정 로드."""
        self.connector = ExchangeConnector()
        self.learner = OnlineLearner()
        self.notifier = TelegramNotifier()
        self.is_running = False
        self.is_paused = False

        default_symbols = "BTC/KRW,ETH/KRW,XRP/KRW,SOL/KRW,DOGE/KRW,ADA/KRW,TRX/KRW,AVAX/KRW,DOT/KRW,LINK/KRW"
        symbols_str = os.getenv("SYMBOL_LIST", default_symbols)
        self.symbols = [s.strip() for s in symbols_str.split(",")]
        
        self.max_positions = 5

        self.coin_data = {}
        for symbol in self.symbols:
            self.coin_data[symbol] = {
                'strategies': {
                    'trend': ScalpingStrategy(),
                },
                'position': None,
                'last_sell_time': None, # 재진입 방지용
            }

        self.last_indicator_update = None
        self.last_heartbeat_time = None
        self.last_daily_report_date = None
        self.is_market_safe = True

    async def _check_market_sentiment(self):
        """시장 건전성 및 추세 체크 (BTC 기준)."""
        try:
            btc_ohlcv = await self.connector.fetch_ohlcv("BTC/KRW", timeframe='1m', limit=60)
            if btc_ohlcv and len(btc_ohlcv) >= 60:
                df = pd.DataFrame(btc_ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])

                change_pct = (df['c'].iloc[-1] - df['c'].iloc[-5]) / df['c'].iloc[-5]
                ema10 = df['c'].ewm(span=10).mean().iloc[-1]
                ema30 = df['c'].ewm(span=30).mean().iloc[-1]
                is_uptrend = ema10 > ema30
                
                std_dev = df['c'].iloc[-20:].std() / df['c'].iloc[-1]
                is_volatile = std_dev > 0.0005

                self.is_market_safe = change_pct > -0.003 and (is_uptrend or is_volatile)

                if not self.is_market_safe:
                    logger.warning(f"⚠️ 시장 주의 상태 (변동률: {change_pct:.2%}, 상승장: {is_uptrend})")
        except Exception as e:
            logger.error(f"시장 감지 오류: {e}")
            self.is_market_safe = True

    async def _update_all_indicators(self):
        """모든 코인의 기술적 지표 업데이트."""
        for symbol in self.symbols:
            try:
                ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='1m', limit=50)
                if ohlcv and len(ohlcv) >= 30:
                    for strategy in self.coin_data[symbol]['strategies'].values():
                        await strategy.update_indicators(ohlcv)
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.error(f"[{symbol}] 지표 업데이트 실패: {e}")
        self.last_indicator_update = now_utc()

    async def _process_commands(self):
        """텔레그램 명령어 처리 로직."""
        cmd = await self.notifier.get_recent_command()
        if not cmd: return

        if "종료" in cmd:
            self.is_paused = True
            await self.notifier.send_message("⏸️ 시스템을 **일시 정지**합니다.")
        elif "시작" in cmd:
            self.is_paused = False
            await self.notifier.send_message("▶️ 시스템을 **재개**합니다.")
        elif "보고" in cmd:
            await self._send_status_report()

    async def _monitor_positions_loop(self):
        """보유 중인 코인의 가격을 1초마다 실시간으로 추적하고 매도 신호에 반응합니다."""
        logger.info("👀 [실시간 감시] 포지션 추적 루프 가동")
        while self.is_running:
            try:
                if self.is_paused:
                    await asyncio.sleep(1)
                    continue

                for symbol in self.symbols:
                    pos = self.coin_data[symbol]['position']
                    if pos and pos.get('state') != 'selling':
                        await self._check_position_exit(symbol, pos)
                        await asyncio.sleep(0.2)

            except Exception as e:
                logger.error(f"실시간 감시 루프 오류: {e}")
            
            await asyncio.sleep(1)

    async def _check_position_exit(self, symbol: str, pos: Dict[str, Any]):
        """개별 포지션의 탈출 조건을 실시간으로 확인."""
        try:
            ticker = await self.connector.fetch_ticker(symbol)
            if not ticker: return

            strategy = self.coin_data[symbol]['strategies'][pos['strategy_type']]
            exit_type = strategy.check_exit_signal(pos['entry_price'], ticker['last'])
            
            if exit_type:
                pos['state'] = 'selling'
                await self._execute_sell(symbol, ticker, pos, exit_type)
        except Exception as e:
            logger.error(f"[{symbol}] 실시간 가격 체크 오류: {e}")

    async def start(self):
        """메인 실행 루프."""
        self.is_running = True
        symbols_list_str = ", ".join([s.split('/')[0] for s in self.symbols])
        await self.notifier.send_message(f"💎 AI 매매 시스템 가동 (실시간 추적 강화)\n대상: {symbols_list_str}")
        
        await self._update_all_indicators()

        asyncio.create_task(self._monitor_positions_loop())

        while self.is_running:
            try:
                now = now_utc()
                await self._process_commands()

                if self.is_paused:
                    await asyncio.sleep(1)
                    continue

                if self.last_heartbeat_time is None or (now - self.last_heartbeat_time).total_seconds() >= 3600:
                    logger.info(f"💓 [정상 가동] 시장: {'안전' if self.is_market_safe else '주의'}")
                    self.last_heartbeat_time = now

                if now.hour == 1 and self.last_daily_report_date != now.date():
                    await self._send_status_report(is_daily_summary=True)
                    self.last_daily_report_date = now.date()

                await self._check_market_sentiment()
                
                if self.last_indicator_update is None or (now - self.last_indicator_update).total_seconds() >= 60:
                    await self._update_all_indicators()

                for symbol in self.symbols:
                    await self._process_trading_logic(symbol, now)
                    await asyncio.sleep(0.2)

            except Exception as e:
                logger.error(f"메인 루프 오류: {e}")
                await asyncio.sleep(2)
            
            await asyncio.sleep(0.5)

    async def _process_trading_logic(self, symbol: str, now: datetime):
        """매수 신호를 탐색하는 로직."""
        try:
            data = self.coin_data[symbol]
            if data['position']: return

            if data['last_sell_time'] and (now - data['last_sell_time']).total_seconds() < 300:
                return

            if not self.is_market_safe: return

            ticker = await self.connector.fetch_ticker(symbol)
            if not ticker: return

            event = TradeEvent(
                trace_id=f"t_{int(now.timestamp())}", exchange=self.connector.exchange_id, 
                symbol=symbol, side="buy", price=ticker['last'], quantity=0
            )
            ai_pred = await self.learner.predict(event)
            
            if await data['strategies']['trend'].check_signal(ticker, ai_pred.model_dump()):
                await self._execute_buy(symbol, ticker, "trend")

        except Exception as e:
            logger.error(f"[{symbol}] 매수 탐색 오류: {e}")

    async def _execute_sell(self, symbol: str, ticker: Dict[str, Any], pos: Dict[str, Any], exit_type: str):
        """매도 실행 및 결과 처리."""
        try:
            balance = await self.connector.fetch_balance()
            coin_code = symbol.split('/')[0]
            
            # 가상 모드일 때는 항상 수량이 있다고 가정 (테스트 버그 수정)
            if self.connector.is_dry_run:
                actual_amount = 1.0 
            else:
                actual_amount = balance.get('free', {}).get(coin_code, 0)
            
            if actual_amount <= 0:
                self.coin_data[symbol]['position'] = None
                return

            if not self.connector.is_dry_run and actual_amount * ticker['last'] < 5050:
                self.coin_data[symbol]['position'] = None
                return

            order = await self.connector.create_order(symbol, "sell", actual_amount)
            if order:
                pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                await self.notifier.send_message(f"💰 [매도] {symbol} ({pnl:.2f}%, {exit_type})")
                
                self.coin_data[symbol]['strategies'][pos['strategy_type']].reset_trailing_state()
                self.coin_data[symbol]['last_sell_time'] = now_utc()
                self.coin_data[symbol]['position'] = None
                
                await self.learner.feedback(ExecutionResult(
                    order_id=order.get('id', 'unknown'), 
                    filled_price=ticker['last'], pnl_pct=pnl/100.0, strategy_type=pos['strategy_type']
                ))
        except Exception as e:
            logger.error(f"[{symbol}] 매도 실행 실패: {e}")
            if self.coin_data[symbol]['position']:
                self.coin_data[symbol]['position']['state'] = 'active'

    async def _execute_buy(self, symbol: str, ticker: Dict[str, Any], strategy_type: str):
        """매수 실행."""
        try:
            active_positions = sum(1 for s in self.symbols if self.coin_data[s]['position'] is not None)
            if active_positions >= self.max_positions: return
            
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            
            remaining_slots = self.max_positions - active_positions
            invest_krw = (krw_free / remaining_slots) * 0.98
            
            if invest_krw < 5050: return 
            
            order = await self.connector.create_order(symbol, "buy", invest_krw)
            if order:
                self.coin_data[symbol]['position'] = {
                    'entry_price': ticker['last'], 
                    'strategy_type': strategy_type,
                    'state': 'active'
                }
                await self.notifier.send_message(f"🚀 [매수] {symbol} (진입가: {ticker['last']:,.0f})")
        except Exception as e:
            logger.error(f"[{symbol}] 매수 실패: {e}")

    async def _send_status_report(self, is_daily_summary: bool = False):
        """상태 보고서 전송."""
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            header = "📅 [일일 보고]" if is_daily_summary else "📊 [상태 보고]"
            msg = f"{header}\n💰 잔고: {krw_free:,.0f}원\n🛡️ 시장: {'안전' if self.is_market_safe else '주의'}\n"
            
            msg += "\n[실시간 수익 현황]\n"
            active_count = 0
            for symbol in self.symbols:
                pos = self.coin_data[symbol]['position']
                if pos:
                    active_count += 1
                    ticker = await self.connector.fetch_ticker(symbol)
                    pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                    msg += f"- {symbol}: {pnl:+.2f}%\n"
            if active_count == 0: msg += "(보유 코인 없음)"
            await self.notifier.send_message(msg)
        except Exception as e:
            logger.error(f"보고 실패: {e}")

    def stop(self):
        self.is_running = False
