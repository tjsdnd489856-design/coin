"""
[울티메이트 전략 관리자]
1. 실시간 주도주 스코어링 (상위 3개 집중 감시)
2. 15분봉+1분봉 데이터 다중 처리
3. 지능형 자금 배분 (Confidence Sizing)
"""
import asyncio
import os
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List
from src.connector.exchange_base import ExchangeConnector
from src.strategy.scalping_strategy import ScalpingStrategy
from src.notifier.telegram_notifier import TelegramNotifier
from src.learner.utils import get_logger, now_utc

logger = get_logger(__name__)


class StrategyManager:
    """울티메이트 트레이딩 시스템의 중앙 제어 장치."""

    def __init__(self):
        self.connector = ExchangeConnector()
        self.notifier = TelegramNotifier()
        self.is_running = False
        self.is_paused = False

        # 대상 코인 리스트
        default_symbols = "BTC/KRW,ETH/KRW,XRP/KRW,SOL/KRW,DOGE/KRW,ADA/KRW,TRX/KRW,AVAX/KRW,DOT/KRW,LINK/KRW"
        symbols_str = os.getenv("SYMBOL_LIST", default_symbols)
        self.symbols = [s.strip() for s in symbols_str.split(",")]
        
        self.max_positions = 3 # 주도주 집중을 위해 최대 포지션 수를 5->3으로 압축
        self.hot_symbols = []   # 현재 거래대금/상승률 상위 종목

        # 계좌 보호
        self.daily_max_loss_pct = 0.02
        self.max_consecutive_losses = 5
        self.start_of_day_balance = 0.0
        self.current_consecutive_losses = 0
        self.daily_pnl_pct = 0.0

        self.coin_data = {}
        for symbol in self.symbols:
            self.coin_data[symbol] = {
                'strategies': {'trend': ScalpingStrategy()},
                'position': None,
                'last_sell_time': None,
                'score': 0.0 # 주도주 점수
            }

        self.last_indicator_update = None
        self.last_heartbeat_time = None
        self.is_market_safe = True

    async def _update_hottest_symbols(self):
        """실시간 주도주(상승률+거래대금) 순위를 매깁니다."""
        scores = []
        for symbol in self.symbols:
            try:
                # 15분봉 기준 최근 1시간(4개 봉) 성과 측정
                ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='15m', limit=5)
                if len(ohlcv) < 5: continue
                
                df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
                change = (df['c'].iloc[-1] - df['c'].iloc[-4]) / df['c'].iloc[-4]
                vol_avg = df['v'].mean()
                
                # 점수 = 상승률(70%) + 거래량(30%) 가중치
                score = (change * 100 * 0.7) + (vol_avg / 1000000 * 0.3)
                self.coin_data[symbol]['score'] = score
                scores.append((symbol, score))
            except:
                continue
        
        # 점수 높은 순으로 정렬하여 상위 5개 추출
        scores.sort(key=lambda x: x[1], reverse=True)
        self.hot_symbols = [s[0] for s in scores[:5]]
        logger.info(f"🔥 실시간 주도주 선별: {', '.join([s.split('/')[0] for s in self.hot_symbols])}")

    async def _update_all_indicators(self):
        """모든 코인의 1분봉/15분봉 지표 업데이트."""
        for symbol in self.symbols:
            try:
                # 1분봉(RSI, MA용)과 15분봉(큰 추세 필터용) 동시 수집
                ohlcv_1m = await self.connector.fetch_ohlcv(symbol, timeframe='1m', limit=100)
                ohlcv_15m = await self.connector.fetch_ohlcv(symbol, timeframe='15m', limit=50)
                
                if ohlcv_1m and len(ohlcv_1m) >= 30:
                    strategy = self.coin_data[symbol]['strategies']['trend']
                    await strategy.update_indicators(ohlcv_1m, ohlcv_15m)
                
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"[{symbol}] 지표 업데이트 실패: {e}")
        
        self.last_indicator_update = now_utc()
        # 지표 업데이트 시 주도주 순위도 갱신
        await self._update_hottest_symbols()

    async def _process_trading_logic(self, symbol: str, now: datetime):
        """매수 신호 탐색 및 지능형 자금 배분."""
        try:
            # 주도주 리스트에 없는 코인은 매수 탐색 건너뜀 (선택과 집중)
            if symbol not in self.hot_symbols:
                return

            data = self.coin_data[symbol]
            if data['position']: return
            if data['last_sell_time'] and (now - data['last_sell_time']).total_seconds() < 300: return
            if not self.is_market_safe: return

            ticker = await self.connector.fetch_ticker(symbol)
            if not ticker: return
            
            strategy = data['strategies']['trend']
            if await strategy.check_signal(ticker):
                # 전략 엔진이 준 '자신감 점수'를 가져옴
                confidence = strategy.calculate_confidence()
                await self._execute_buy(symbol, ticker, "trend", confidence)

        except Exception as e:
            logger.error(f"[{symbol}] 매수 탐색 오류: {e}")

    async def _execute_buy(self, symbol: str, ticker: Dict[str, Any], strategy_type: str, confidence: float = 1.0):
        """지능형 자금 배분을 적용한 매수 실행."""
        try:
            active_positions = sum(1 for s in self.symbols if self.coin_data[s]['position'] is not None)
            if active_positions >= self.max_positions: return
            
            balance = await self.connector.fetch_balance()
            krw_free = balance.get('free', {}).get('KRW', 0)
            
            remaining_slots = self.max_positions - active_positions
            # 기본 투자금 계산
            base_invest = (krw_free / remaining_slots) * 0.95
            
            # [신규] 자신감 점수에 따라 투자금 조절 (0.5배 ~ 1.5배)
            final_invest = base_invest * confidence
            
            if final_invest < 5050: return 
            
            order = await self.connector.create_order(symbol, "buy", final_invest)
            if order:
                self.coin_data[symbol]['position'] = {
                    'entry_price': ticker['last'], 
                    'strategy_type': strategy_type,
                    'state': 'active',
                    'entry_time': now_utc(),
                    'confidence': confidence
                }
                await self.notifier.send_message(f"🚀 [울티메이트 매수] {symbol}\n신뢰도: {confidence:.1f}배 배팅\n진입가: {ticker['last']:,.0f}")
        except Exception as e:
            logger.error(f"[{symbol}] 매수 실패: {e}")

    # --- 기존 안전장치 및 루프 유지 ---
    async def _init_daily_balance(self):
        balance = await self.connector.fetch_balance()
        total_krw = balance.get('total', {}).get('KRW', 0)
        self.start_of_day_balance = total_krw
        self.current_consecutive_losses = 0
        self.daily_pnl_pct = 0.0
        logger.info(f"🏦 울티메이트 기준 잔고 초기화: {self.start_of_day_balance:,.0f}원")

    async def _check_account_safety(self) -> bool:
        if self.start_of_day_balance <= 0: return True
        if self.current_consecutive_losses >= self.max_consecutive_losses:
            if not self.is_paused:
                self.is_paused = True
                await self.notifier.send_message("🚨 5연패 발생! 안전을 위해 중단합니다.")
            return False
        
        balance = await self.connector.fetch_balance()
        curr_krw = balance.get('total', {}).get('KRW', 0)
        self.daily_pnl_pct = (curr_krw - self.start_of_day_balance) / self.start_of_day_balance
        if self.daily_pnl_pct <= -self.daily_max_loss_pct:
            if not self.is_paused:
                self.is_paused = True
                await self.notifier.send_message(f"🚨 일간 손실 2% 초과! 오늘 수익률: {self.daily_pnl_pct*100:.2f}%")
            return False
        return True

    async def _check_market_sentiment(self):
        try:
            btc = await self.connector.fetch_ohlcv("BTC/KRW", timeframe='1m', limit=60)
            df = pd.DataFrame(btc, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            ema10, ema30 = df['c'].ewm(span=10).mean().iloc[-1], df['c'].ewm(span=30).mean().iloc[-1]
            self.is_market_safe = (df['c'].iloc[-1] > df['c'].iloc[-5] * 0.997) and (ema10 > ema30)
        except: self.is_market_safe = True

    async def _monitor_positions_loop(self):
        while self.is_running:
            for symbol in self.symbols:
                pos = self.coin_data[symbol]['position']
                if pos and pos.get('state') != 'selling':
                    ticker = await self.connector.fetch_ticker(symbol)
                    if ticker:
                        exit_type = self.coin_data[symbol]['strategies'][pos['strategy_type']].check_exit_signal(
                            pos['entry_price'], ticker['last'], pos.get('entry_time')
                        )
                        if exit_type:
                            pos['state'] = 'selling'
                            await self._execute_sell(symbol, ticker, pos, exit_type)
            await asyncio.sleep(1)

    async def _execute_sell(self, symbol: str, ticker: Dict[str, Any], pos: Dict[str, Any], exit_type: str):
        try:
            balance = await self.connector.fetch_balance()
            coin = symbol.split('/')[0]
            amount = 1.0 if self.connector.is_dry_run else balance.get('free', {}).get(coin, 0)
            if amount <= 0: 
                self.coin_data[symbol]['position'] = None
                return

            order = await self.connector.create_order(symbol, "sell", amount)
            if order:
                pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                if pnl < -0.1: self.current_consecutive_losses += 1
                else: self.current_consecutive_losses = 0
                await self.notifier.send_message(f"💰 [매도] {symbol} ({pnl:.2f}%, {exit_type})")
                self.coin_data[symbol]['strategies'][pos['strategy_type']].reset_trailing_state()
                self.coin_data[symbol]['last_sell_time'] = now_utc()
                self.coin_data[symbol]['position'] = None
        except Exception as e:
            logger.error(f"[{symbol}] 매도 실패: {e}")

    async def _process_commands(self):
        cmd = await self.notifier.get_recent_command()
        if not cmd: return
        if "종료" in cmd: self.is_paused = True
        elif "시작" in cmd: 
            self.is_paused = False
            self.current_consecutive_losses = 0
        elif "보고" in cmd: await self._send_status_report()

    async def start(self):
        self.is_running = True
        await self._init_daily_balance()
        await self.notifier.send_message("🌌 울티메이트 트레이딩 시스템 가동\n(쌍안경 필터 + 주도주 선별 + 가변 배팅)")
        await self._update_all_indicators()
        asyncio.create_task(self._monitor_positions_loop())
        while self.is_running:
            try:
                now = now_utc()
                await self._process_commands()
                if now.hour == 0 and now.minute == 0 and now.second < 10: await self._init_daily_balance()
                safe = await self._check_account_safety()
                if self.is_paused or not safe:
                    await asyncio.sleep(1)
                    continue
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

    async def _send_status_report(self, is_daily_summary: bool = False):
        try:
            balance = await self.connector.fetch_balance()
            krw = balance.get('free', {}).get('KRW', 0)
            msg = f"{'📅 일일 보고' if is_daily_summary else '📊 상태 보고'}\n💰 잔고: {krw:,.0f}원\n📈 수익률: {self.daily_pnl_pct*100:.2f}%\n"
            msg += f"🔥 주도주: {', '.join([s.split('/')[0] for s in self.hot_symbols])}\n"
            active = [s for s in self.symbols if self.coin_data[s]['position']]
            if active:
                msg += "\n[포지션]\n"
                for s in active:
                    p = self.coin_data[s]['position']
                    ticker = await self.connector.fetch_ticker(s)
                    pnl = (ticker['last'] - p['entry_price']) / p['entry_price'] * 100
                    msg += f"- {s}: {pnl:+.2f}% (신뢰도 {p['confidence']}배)\n"
            else: msg += "\n(보유 포지션 없음)"
            await self.notifier.send_message(msg)
        except: pass

    def stop(self): self.is_running = False
