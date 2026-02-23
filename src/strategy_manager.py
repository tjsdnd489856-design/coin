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
from src.strategy.reversal_strategy import ReversalStrategy
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
        logger.info("📡 지표 및 AI 모델 데이터 동기화 중...")
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

    async def _process_commands(self):
        """텔레그램 명령어 처리 로직."""
        cmd = await self.notifier.get_recent_command()
        if not cmd:
            return

        if "종료" in cmd:
            self.is_paused = True
            await self.notifier.send_message("⏸️ 시스템을 **일시 정지**합니다.\n매매 신호를 감시하지 않습니다.")
            logger.info("사용자 명령에 의해 시스템 일시 정지")

        elif "시작" in cmd:
            self.is_paused = False
            await self.notifier.send_message("▶️ 시스템을 **재개**합니다.\n다시 매매를 시작합니다.")
            logger.info("사용자 명령에 의해 시스템 재개")

        elif "보고" in cmd:
            await self._send_status_report()

    async def start(self):
        """메인 실행 루프."""
        self.is_running = True
        await self.notifier.send_message("💎 AI 지능형 매매 시스템 가동\n(명령어: 시작, 종료, 보고)")
        await self._update_all_indicators()

        while self.is_running:
            try:
                now = now_utc()

                # 1. 텔레그램 명령 처리 (최우선)
                await self._process_commands()

                # 2. 일시 정지 상태라면 매매 로직 건너뛰기
                if self.is_paused:
                    # 정지 상태임을 알리는 로그는 너무 자주 찍지 않도록 함
                    if now.second % 60 == 0: 
                        logger.info("💤 시스템 일시 정지 대기 중...")
                    await asyncio.sleep(1)
                    continue

                # 3. 하트비트 (생존 신고) - 1시간 주기
                if self.last_heartbeat_time is None or (now - self.last_heartbeat_time).total_seconds() >= 3600:
                    logger.info(f"💓 [정상 가동] 상태: {'안전' if self.is_market_safe else '주의'}")
                    self.last_heartbeat_time = now

                # 4. 일일 보고 (오전 10시 KST = 01시 UTC)
                if now.hour == 1 and self.last_daily_report_date != now.date():
                    await self._send_status_report(is_daily_summary=True)
                    self.last_daily_report_date = now.date()

                # 5. 시장 감시 및 데이터 업데이트
                await self._check_market_sentiment()
                
                if self.last_indicator_update is None or (now - self.last_indicator_update).total_seconds() >= 60:
                    await self._update_all_indicators()

                # 6. 매매 로직 (매수/매도)
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
            if not ticker:
                return

            # 보유 포지션이 없을 때 (매수 검토)
            if not data['position']:
                # 시장이 위험하거나 건전하지 않으면 매수 금지
                if not self.is_market_safe:
                    return
                
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
                elif await data['strategies']['reversal'].check_signal(ticker, pred_dict):
                    await self._execute_buy(symbol, ticker, "reversal")

            # 보유 포지션이 있을 때 (매도 검토)
            else:
                pos = data['position']
                strategy = data['strategies'][pos['strategy_type']]
                exit_type = strategy.check_exit_signal(pos['entry_price'], ticker['last'])
                
                if exit_type:
                    await self._execute_sell(symbol, ticker, pos, exit_type)

        except Exception as e:
            logger.error(f"[{symbol}] 트레이딩 로직 처리 중 오류: {e}")

    async def _execute_sell(self, symbol: str, ticker: Dict[str, Any], pos: Dict[str, Any], exit_type: str):
        """매도 실행 및 결과 처리."""
        order = await self.connector.create_order(symbol, "sell", pos['amount'])
        if order:
            pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
            await self.notifier.send_message(f"💰 [매도 완료] {symbol}\n수익률: {pnl:.2f}% ({exit_type})")
            
            # AI 학습 피드백
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
            
            header = "📅 [일일 종합 보고]" if is_daily_summary else "📊 [시스템 상태 보고]"
            status_text = "일시 정지 ⏸️" if self.is_paused else "가동 중 ▶️"
            
            msg = f"{header}\n"
            msg += f"상태: {status_text}\n"
            msg += f"💰 원화 잔고: {krw_free:,.0f}원\n"
            msg += f"🛡️ 시장: {'안전' if self.is_market_safe else '위험(관망)'}\n"
            
            if is_daily_summary and self.learner.recent_pnl:
                avg_pnl = sum(self.learner.recent_pnl) / len(self.learner.recent_pnl)
                msg += f"📈 최근 평균 수익률: {avg_pnl*100:.2f}%\n"

            msg += "\n[보유 코인]\n"
            has_coin = False
            for symbol in self.symbols:
                pos = self.coin_data[symbol]['position']
                if pos:
                    has_coin = True
                    ticker = await self.connector.fetch_ticker(symbol)
                    pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                    msg += f"- {symbol}: {pnl:+.2f}%\n"
            
            if not has_coin:
                msg += "(보유 중인 코인 없음)"

            await self.notifier.send_message(msg)
            logger.info("보고서 전송 완료")
        except Exception as e:
            logger.error(f"보고 실패: {e}")

    async def _execute_buy(self, symbol: str, ticker: Dict[str, Any], strategy_type: str):
        """매수 실행."""
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            
            active_positions = sum(1 for s in self.symbols if self.coin_data[s]['position'] is not None)
            remaining_slots = len(self.symbols) - active_positions
            
            if remaining_slots <= 0:
                return
            
            invest_krw = (krw_free / remaining_slots) * 0.999
            
            if invest_krw < 5050:
                return 
            
            strategy = self.coin_data[symbol]['strategies'][strategy_type]
            order = await self.connector.create_order(symbol, "buy", invest_krw)
            
            if order:
                amount = strategy.calculate_amount(invest_krw, ticker['last'])
                self.coin_data[symbol]['position'] = {
                    'entry_price': ticker['last'], 
                    'amount': amount, 
                    'strategy_type': strategy_type
                }
                await self.notifier.send_message(f"🚀 [매수 완료] {symbol}\n전략: {strategy_type}")
        except Exception as e:
            logger.error(f"[{symbol}] 매수 실패: {e}")

    def stop(self):
        """시스템 완전 종료."""
        self.is_running = False
