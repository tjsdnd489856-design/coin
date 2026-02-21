"""
멀티 코인 및 멀티 전략 관리자 (하트비트 주기 조정 및 보고 기능 강화).
사용자 명령어 인식률을 높이고 로그 출력을 최적화함.
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
        self.last_daily_report_date = None # 일일 보고 추적용
        self.is_market_safe = True

    async def _check_market_sentiment(self):
        """시장 건전성 및 추세 체크 (EMA 정배열 및 변동성 확인)."""
        try:
            # BTC 1분봉 60개를 가져와서 단기/장기 추세 분석
            btc_ohlcv = await self.connector.fetch_ohlcv("BTC/KRW", timeframe='1m', limit=60)
            if btc_ohlcv and len(btc_ohlcv) >= 60:
                df = pd.DataFrame(btc_ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
                
                # 1. 가격 변화율
                change_pct = (df['c'].iloc[-1] - df['c'].iloc[-5]) / df['c'].iloc[-5]
                
                # 2. EMA 추세 (단기 10, 장기 30)
                ema10 = df['c'].ewm(span=10).mean().iloc[-1]
                ema30 = df['c'].ewm(span=30).mean().iloc[-1]
                is_uptrend = ema10 > ema30
                
                # 3. 변동성 (너무 낮으면 횡보장으로 판단하여 제외)
                std_dev = df['c'].iloc[-20:].std() / df['c'].iloc[-1]
                is_volatile = std_dev > 0.0005 # 0.05% 이상의 변동성 필요
                
                # 급락 중이 아니고, 추세가 살아있거나 변동성이 적정할 때만 안전으로 판단
                self.is_market_safe = change_pct > -0.003 and (is_uptrend or is_volatile)
                
                if not self.is_market_safe:
                    logger.warning(f"⚠️ 시장 주의 상태 (Change: {change_pct:.2%}, Uptrend: {is_uptrend}, Vol: {std_dev:.4f})")
        except Exception as e:
            logger.error(f"시장 감지 오류: {e}")
            self.is_market_safe = True # 에러 시 기본값은 True로 유지하되 로그 남김

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

                # 3. 매일 오전 10시(KST) 자동 종합 보고 (UTC 01:00)
                # 한국 시간 10시는 UTC 01시입니다.
                if now.hour == 1 and self.last_daily_report_date != now.date():
                    await self._send_status_report(is_daily_summary=True)
                    self.last_daily_report_date = now.date()

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

    async def _send_status_report(self, is_daily_summary: bool = False):
        """현재 시황 및 포지션 상세 보고."""
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            
            header = "📅 [일일 종합 보고]" if is_daily_summary else "📊 [시스템 실시간 보고]"
            msg = f"{header}\n"
            msg += f"💰 원화 잔고: {krw_free:,.0f}원\n"
            msg += f"🛡️ 시장 상태: {'안전' if self.is_market_safe else '위험(관망)'}\n"
            
            if is_daily_summary:
                # 최근 50회 평균 수익률 정보 추가
                avg_pnl = sum(self.learner.recent_pnl) / len(self.learner.recent_pnl) if self.learner.recent_pnl else 0
                msg += f"📈 최근 평균 수익률: {avg_pnl*100:.2f}%\n"
                msg += f"🔄 최근 거래 횟수: {len(self.learner.recent_pnl)}회\n"

            msg += "\n"
            for symbol in self.symbols:
                ticker = await self.connector.fetch_ticker(symbol)
                pos = self.coin_data[symbol]['position']
                status = f"보유중 (PnL: {(ticker['last']-pos['entry_price'])/pos['entry_price']*100:.2f}%)" if pos else "신호 감시 중"
                msg += f"- {symbol}: {ticker['last']:,.0f}원 | {status}\n"
                
            await self.notifier.send_message(msg)
            logger.info(f"✅ {'일일' if is_daily_summary else '실시간'} 보고서 전송 완료")
        except Exception as e:
            logger.error(f"보고 실패: {e}")

    async def _execute_buy(self, symbol: str, ticker: Dict[str, Any], strategy_type: str):
        try:
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            invest_krw = krw_free / (len(self.symbols) + 1)
            if invest_krw < 5000: return
            
            strategy = self.coin_data[symbol]['strategies'][strategy_type]
            # 업비트 시장가 매수는 수량이 아닌 '투자 금액'을 amount 자리에 넣어야 함
            order = await self.connector.create_order(symbol, "buy", invest_krw)
            
            if order:
                # 내부 포지션 관리를 위해 실제 체결 수량 계산 (또는 ticker 기준 계산)
                amount = strategy.calculate_amount(invest_krw, ticker['last'])
                self.coin_data[symbol]['position'] = {'entry_price': ticker['last'], 'amount': amount, 'strategy_type': strategy_type}
                await self.notifier.send_message(f"🚀 [매수 완료] {symbol}\n전략: {strategy_type}")
        except Exception as e:
            logger.error(f"[{symbol}] 매수 실패: {e}")

    def stop(self):
        self.is_running = False
