"""
멀티 코인 및 멀티 전략 관리자.
일간 2% 최대 손실 제한 및 5연패 중지 등 계좌 보호 기능이 추가되었습니다.
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
    """매매 시스템의 중앙 제어 장치."""

    def __init__(self):
        """초기화 및 설정 로드."""
        self.connector = ExchangeConnector()
        self.notifier = TelegramNotifier()
        self.is_running = False
        self.is_paused = False

        default_symbols = "BTC/KRW,ETH/KRW,XRP/KRW,SOL/KRW,DOGE/KRW,ADA/KRW,TRX/KRW,AVAX/KRW,DOT/KRW,LINK/KRW"
        symbols_str = os.getenv("SYMBOL_LIST", default_symbols)
        self.symbols = [s.strip() for s in symbols_str.split(",")]
        
        self.max_positions = 5

        # [신규] 계좌 보호용 변수
        self.daily_max_loss_pct = 0.02   # 하루 최대 손실 허용치 (2%)
        self.max_consecutive_losses = 5  # 최대 연속 손실 횟수
        self.start_of_day_balance = 0.0  # 오늘 하루 시작 잔고 (0시 기준)
        self.current_consecutive_losses = 0 # 현재 연속 손실 횟수
        self.daily_pnl_pct = 0.0         # 오늘 하루 누적 수익률

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

    async def _init_daily_balance(self):
        """하루 시작 잔고를 기록 (일간 손실률 계산용)."""
        balance = await self.connector.fetch_balance()
        # 가용 잔고 + 묶인 잔고의 대략적인 합 (단순화를 위해 KRW 총액 사용)
        total_krw = balance.get('total', {}).get('KRW', 0)
        
        # 만약 시작 잔고가 0이면 초기화, 날짜가 바뀌었을 때도 갱신 필요
        if self.start_of_day_balance == 0 or total_krw > 0:
            self.start_of_day_balance = total_krw
            self.current_consecutive_losses = 0
            self.daily_pnl_pct = 0.0
            logger.info(f"🏦 일간 기준 잔고 초기화: {self.start_of_day_balance:,.0f}원")

    async def _check_account_safety(self) -> bool:
        """계좌가 터지는 것을 막는 일간 안전장치 확인."""
        if self.start_of_day_balance <= 0:
            return True

        # 1. 5연패 확인
        if self.current_consecutive_losses >= self.max_consecutive_losses:
            if not self.is_paused:
                self.is_paused = True
                msg = f"🚨 **[긴급] 5회 연속 손실 발생!**\n안전을 위해 시스템을 강제 정지합니다.\n수동으로 확인 후 '/시작' 명령어를 내려주세요."
                logger.error(msg)
                await self.notifier.send_message(msg)
            return False

        # 2. 일간 최대 손실 2% 초과 확인
        balance = await self.connector.fetch_balance()
        current_total_krw = balance.get('total', {}).get('KRW', 0)
        
        # 현재 수익률 계산
        if self.start_of_day_balance > 0:
            self.daily_pnl_pct = (current_total_krw - self.start_of_day_balance) / self.start_of_day_balance
            
            if self.daily_pnl_pct <= -self.daily_max_loss_pct:
                if not self.is_paused:
                    self.is_paused = True
                    msg = f"🚨 **[긴급] 일간 손실 한도(2%) 초과!**\n오늘 손실률: {self.daily_pnl_pct*100:.2f}%\n안전을 위해 시스템을 강제 정지합니다."
                    logger.error(msg)
                    await self.notifier.send_message(msg)
                return False

        return True

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
                # VWAP 등 계산을 위해 넉넉히 당일 치 데이터를 가져옵니다 (1m봉 1440개 = 24시간)
                # 업비트는 보통 최대 200개 제한이므로 여러 번 땡기거나 가능한 만큼 가져옴 (여기선 200개)
                ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe='1m', limit=200)
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
            # 정지 후 재시작 시 연패 기록 등 초기화
            self.current_consecutive_losses = 0
            await self.notifier.send_message("▶️ 시스템을 **재개**합니다. (연패 기록 초기화)")
        elif "보고" in cmd:
            await self._send_status_report()

    async def _monitor_positions_loop(self):
        """보유 중인 코인의 가격을 1초마다 실시간으로 추적하고 매도 신호에 반응합니다."""
        logger.info("👀 [실시간 감시] 포지션 추적 루프 가동")
        while self.is_running:
            try:
                # 포지션 추적은 시스템이 일시정지 상태여도(is_paused) 진행해야 물린 코인을 팔 수 있습니다.
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
            # [신규] 진입 시간을 넘겨주어 10분 시간 제한을 체크할 수 있게 함
            exit_type = strategy.check_exit_signal(pos['entry_price'], ticker['last'], pos.get('entry_time'))
            
            if exit_type:
                pos['state'] = 'selling'
                await self._execute_sell(symbol, ticker, pos, exit_type)
        except Exception as e:
            logger.error(f"[{symbol}] 실시간 가격 체크 오류: {e}")

    async def start(self):
        """메인 실행 루프."""
        self.is_running = True
        
        await self._init_daily_balance() # 시작 잔고 기록
        
        symbols_list_str = ", ".join([s.split('/')[0] for s in self.symbols])
        await self.notifier.send_message(f"🛡️ 안전강화 하이브리드 스캘핑 가동\n대상: {symbols_list_str}\n(안전장치: VWAP추세, 10분제한, 2%손실제한)")
        
        await self._update_all_indicators()

        asyncio.create_task(self._monitor_positions_loop())

        while self.is_running:
            try:
                now = now_utc()
                await self._process_commands()

                # 자정이 넘어가면 일간 기준 잔고 초기화 (새로운 하루 시작)
                if now.hour == 0 and now.minute == 0 and now.second < 10:
                    await self._init_daily_balance()

                # 일간 2% 손실, 5연패 체크 (매수 진입 차단용)
                is_account_safe = await self._check_account_safety()

                if self.is_paused or not is_account_safe:
                    await asyncio.sleep(1)
                    continue

                if self.last_heartbeat_time is None or (now - self.last_heartbeat_time).total_seconds() >= 3600:
                    logger.info(f"💓 [정상 가동] 시장: {'안전' if self.is_market_safe else '주의'} | 오늘수익률: {self.daily_pnl_pct*100:.2f}% | 연속손실: {self.current_consecutive_losses}회")
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
            
            if await data['strategies']['trend'].check_signal(ticker):
                await self._execute_buy(symbol, ticker, "trend")

        except Exception as e:
            logger.error(f"[{symbol}] 매수 탐색 오류: {e}")

    async def _execute_sell(self, symbol: str, ticker: Dict[str, Any], pos: Dict[str, Any], exit_type: str):
        """매도 실행 및 결과 처리."""
        try:
            balance = await self.connector.fetch_balance()
            coin_code = symbol.split('/')[0]
            
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
                
                # [신규] 연패 카운트 로직 적용 (수수료 포함 계산)
                net_pnl = pnl - 0.1 # 대략적인 매수/매도 수수료(0.05*2) 제외
                if net_pnl < 0:
                    self.current_consecutive_losses += 1
                else:
                    self.current_consecutive_losses = 0 # 수익 발생 시 연패 초기화
                    
                await self.notifier.send_message(f"💰 [매도] {symbol} ({pnl:.2f}%, {exit_type})\n(현재 {self.current_consecutive_losses}연패 중)")
                
                self.coin_data[symbol]['strategies'][pos['strategy_type']].reset_trailing_state()
                self.coin_data[symbol]['last_sell_time'] = now_utc()
                self.coin_data[symbol]['position'] = None
                
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
                    'state': 'active',
                    'entry_time': now_utc() # [신규] 진입 시간 기록 (10분 제한용)
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
            msg = f"{header}\n💰 가용 잔고: {krw_free:,.0f}원\n📉 오늘 수익률: {self.daily_pnl_pct*100:.2f}%\n"
            msg += f"🛡️ 현재 연패: {self.current_consecutive_losses}회 / 최대 {self.max_consecutive_losses}회\n"
            
            msg += "\n[실시간 수익 현황]\n"
            active_count = 0
            for symbol in self.symbols:
                pos = self.coin_data[symbol]['position']
                if pos:
                    active_count += 1
                    ticker = await self.connector.fetch_ticker(symbol)
                    pnl = (ticker['last'] - pos['entry_price']) / pos['entry_price'] * 100
                    
                    # 보유 시간 계산
                    holding_mins = (now_utc() - pos['entry_time']).total_seconds() / 60
                    msg += f"- {symbol}: {pnl:+.2f}% ({holding_mins:.1f}분 경과)\n"
            if active_count == 0: msg += "(보유 코인 없음)"
            await self.notifier.send_message(msg)
        except Exception as e:
            logger.error(f"보고 실패: {e}")

    def stop(self):
        self.is_running = False
