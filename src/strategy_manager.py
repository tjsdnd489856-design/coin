"""
멀티 코인 및 멀티 전략 관리자.
텔레그램 명령어를 통해 시스템 일시 정지(종료) 및 재개(시작) 기능을 지원합니다.
"""
import asyncio
import os
import pandas as pd
from datetime import datetime
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
        self.is_paused = False  # 일시 정지 상태 플래그

        # 감시 코인은 10개를 유지하되, 투자는 최대 5개 코인에 집중 (5분할)
        default_symbols = "BTC/KRW,ETH/KRW,XRP/KRW,SOL/KRW,DOGE/KRW,ADA/KRW,TRX/KRW,AVAX/KRW,DOT/KRW,LINK/KRW"
        symbols_str = os.getenv("SYMBOL_LIST", default_symbols)
        self.symbols = [s.strip() for s in symbols_str.split(",")]
        
        # 투자 비중 설정 (5등분)
        self.max_positions = 5

        self.coin_data = {}
        for symbol in self.symbols:
            self.coin_data[symbol] = {
                'strategies': {
                    'trend': ScalpingStrategy(),
                },
                'position': None,
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
        logger.info(f"📡 {len(self.symbols)}개 코인 지표 동기화 중...")
        for symbol in self.symbols:
            try:
                ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='1m', limit=50)
                if ohlcv and len(ohlcv) >= 30:
                    for strategy in self.coin_data[symbol]['strategies'].values():
                        await strategy.update_indicators(ohlcv)
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"[{symbol}] 지표 업데이트 실패: {e}")
        self.last_indicator_update = now_utc()

    async def _process_commands(self):
        """텔레그램 명령어 처리 로직."""
        cmd = await self.notifier.get_recent_command()
        if not cmd:
            return

        if "종료" in cmd:
            self.is_paused = True
            await self.notifier.send_message("⏸️ 시스템을 **일시 정지**합니다.")
            logger.info("사용자 명령에 의해 시스템 일시 정지")

        elif "시작" in cmd:
            self.is_paused = False
            await self.notifier.send_message("▶️ 시스템을 **재개**합니다.")
            logger.info("사용자 명령에 의해 시스템 재개")

        elif "보고" in cmd:
            await self._send_status_report()

    async def start(self):
        """메인 실행 루프."""
        self.is_running = True
        symbols_list_str = ", ".join([s.split('/')[0] for s in self.symbols])
        await self.notifier.send_message(f"💎 AI 매매 시스템 가동 (5분할 집중 투자)\n대상: {symbols_list_str}")
        await self._update_all_indicators()

        while self.is_running:
            try:
                now = now_utc()
                await self._process_commands()

                if self.is_paused:
                    if now.second % 60 == 0: logger.info("💤 일시 정지 중...")
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
                    await asyncio.sleep(0.05)

            except Exception as e:
                logger.error(f"메인 루프 오류: {e}")
                await asyncio.sleep(2)
            
            await asyncio.sleep(0.5)

    async def _process_trading_logic(self, symbol: str, now: datetime):
        """개별 코인에 대한 매수/매도 판단 로직."""
        try:
            data = self.coin_data[symbol]
            ticker = await self.connector.fetch_ticker(symbol)
            if not ticker: return

            # 보유 포지션이 없을 때 (매수 검토)
            if not data['position']:
                if not self.is_market_safe: return
                
                event = TradeEvent(
                    trace_id=f"t_{int(now.timestamp())}", 
                    exchange=self.connector.exchange_id, 
                    symbol=symbol, 
                    side="buy", 
                    price=ticker['last'], 
                    quantity=0
                )
                ai_pred = await self.learner.predict(event)
                pred_dict = ai_pred.model_dump()

                if await data['strategies']['trend'].check_signal(ticker, pred_dict):
                    await self._execute_buy(symbol, ticker, "trend")

            # 보유 포지션이 있을 때 (매도 검토)
            else:
                pos = data['position']
                strategy = data['strategies'][pos['strategy_type']]
                exit_type = strategy.check_exit_signal(pos['entry_price'], ticker['last'])
                
                if exit_type:
                    await self._execute_sell(symbol, ticker, pos, exit_type)

        except Exception as e:
            logger.error(f"[{symbol}] 트레이딩 로직 오류: {e}")

    async def _execute_sell(self, symbol: str, ticker: Dict[str, Any], pos: Dict[str, Any], exit_type: str):
        """매도 실행 및 결과 처리."""
        order = await self.connector.create_order(symbol, "sell", pos['amount'])
        if order:
            pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
            await self.notifier.send_message(f"💰 [매도] {symbol} ({pnl:.2f}%, {exit_type})")
            
            await self.learner.feedback(ExecutionResult(
                order_id=order.get('id', 'unknown'), 
                filled_price=ticker['last'], 
                pnl_pct=pnl/100.0, 
                strategy_type=pos['strategy_type']
            ))
            self.coin_data[symbol]['position'] = None

    async def _send_status_report(self, is_daily_summary: bool = False):
        """상태 보고서 전송."""
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            
            header = "📅 [일일 보고]" if is_daily_summary else "📊 [상태 보고]"
            status_text = "일시 정지 ⏸️" if self.is_paused else "가동 중 ▶️"
            
            msg = f"{header}\n상태: {status_text}\n💰 잔고: {krw_free:,.0f}원\n🛡️ 시장: {'안전' if self.is_market_safe else '주의'}\n"
            
            msg += "\n[보유 코인]\n"
            active_count = 0
            for symbol in self.symbols:
                pos = self.coin_data[symbol]['position']
                if pos:
                    active_count += 1
                    ticker = await self.connector.fetch_ticker(symbol)
                    pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                    msg += f"- {symbol}: {pnl:+.2f}%\n"
            
            if active_count == 0: msg += "(없음)"
            msg += f"\n(슬롯: {active_count}/{self.max_positions})"

            await self.notifier.send_message(msg)
        except Exception as e:
            logger.error(f"보고 실패: {e}")

    async def _execute_buy(self, symbol: str, ticker: Dict[str, Any], strategy_type: str):
        """매수 실행 (5분할 투자)."""
        try:
            # 현재 몇 개의 코인을 가지고 있는지 확인
            active_positions = sum(1 for s in self.symbols if self.coin_data[s]['position'] is not None)
            
            # 이미 5개 코인을 보유 중이면 더 이상 사지 않음
            if active_positions >= self.max_positions:
                return
            
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            
            # 한 번 투자할 때 가용한 전체 원금의 1/5 수준으로 투자
            # (남은 현금 / 남은 슬롯) 방식으로 계산하여 자금을 효율적으로 배분
            remaining_slots = self.max_positions - active_positions
            invest_krw = (krw_free / remaining_slots) * 0.99
            
            if invest_krw < 5050: return 
            
            strategy = self.coin_data[symbol]['strategies'][strategy_type]
            order = await self.connector.create_order(symbol, "buy", invest_krw)
            
            if order:
                amount = strategy.calculate_amount(invest_krw, ticker['last'])
                self.coin_data[symbol]['position'] = {
                    'entry_price': ticker['last'], 
                    'amount': amount, 
                    'strategy_type': strategy_type
                }
                await self.notifier.send_message(f"🚀 [매수] {symbol} (비중 1/{self.max_positions})")
        except Exception as e:
            logger.error(f"[{symbol}] 매수 실패: {e}")

    def stop(self):
        self.is_running = False
