"""
온라인 적응형 학습(Adaptive Learning) 모델.
실시간 성과(P&L)를 분석하여 최적의 전략 파라미터를 동적으로 제안.
"""
import asyncio
import os
import random
from typing import Dict, Any, List, Deque
from collections import deque
from .schema import TradeEvent, Prediction, ExecutionResult, TradeParams
from .feature_store import FeatureStore
from .model_registry import ModelRegistry
from .utils import get_logger

logger = get_logger(__name__)


class OnlineLearner:
    """자가 학습 및 파라미터 튜닝 엔진."""

    def __init__(self):
        self.feature_store = FeatureStore()
        self.registry = ModelRegistry()
        self.update_queue = asyncio.Queue()
        self._is_dry_run = os.getenv("DRY_RUN", "False").lower() == "true"
        
        # [핵심] 최근 50회 거래 성과 메모리 (단기 기억)
        self.recent_pnl: Deque[float] = deque(maxlen=50)
        
        # 현재 적용 중인 기본 파라미터 (초기값)
        self.current_params = TradeParams(
            k=0.5, 
            rsi_buy_threshold=25,
            stop_loss_pct=0.005,
            take_profit_pct=0.012,
            volume_multiplier=2.0
        )
        
        # 백그라운드 학습 루프 시작
        asyncio.create_task(self._training_loop())

    async def predict(self, event: TradeEvent) -> Prediction:
        """현재 시장 상황과 과거 성과를 반영한 최적 파라미터 제안."""
        # 1. 피처 계산 (생략 가능하나 확장성 위해 유지)
        # features = await self.feature_store.compute_features(event)
        
        # 2. 적응형 파라미터 계산 (Adaptive Logic)
        adjusted_params = self._adjust_params_based_on_performance()
        
        return Prediction(
            model_version="adaptive_v1",
            suggested_params=adjusted_params,
            estimated_slippage=0.001, # 고정값 또는 예측값
            confidence_score=self._calculate_confidence()
        )

    def _adjust_params_based_on_performance(self) -> TradeParams:
        """최근 성과에 따라 전략 파라미터 동적 튜닝."""
        if not self.recent_pnl:
            return self.current_params # 데이터 없으면 초기값 유지

        avg_pnl = sum(self.recent_pnl) / len(self.recent_pnl)
        win_rate = len([p for p in self.recent_pnl if p > 0]) / len(self.recent_pnl)
        
        # 기본 파라미터 복사
        new_params = self.current_params.model_copy()

        # [튜닝 로직 1] 성과가 저조할 때 (승률 40% 미만 or 평균 손실) -> 보수적 대응
        if win_rate < 0.4 or avg_pnl < 0:
            logger.info(f"📉 성과 저조 (승률: {win_rate:.2%}). 진입 장벽 강화.")
            new_params.k = min(0.9, new_params.k + 0.05)           # K값 상향 (더 확실한 돌파만)
            new_params.rsi_buy_threshold = max(15, new_params.rsi_buy_threshold - 2) # RSI 하향 (더 심한 과매도만)
            new_params.volume_multiplier = min(4.0, new_params.volume_multiplier + 0.2) # 거래량 조건 강화
            
        # [튜닝 로직 2] 성과가 우수할 때 (승률 60% 이상) -> 적극적 대응
        elif win_rate > 0.6 and avg_pnl > 0.005: # 평균 0.5% 이상 수익
            logger.info(f"📈 성과 우수 (승률: {win_rate:.2%}). 기회 확대.")
            new_params.k = max(0.3, new_params.k - 0.02)           # K값 하향 (진입 쉽게)
            new_params.rsi_buy_threshold = min(35, new_params.rsi_buy_threshold + 1) # RSI 상향
            new_params.volume_multiplier = max(1.2, new_params.volume_multiplier - 0.1) # 거래량 조건 완화

        return new_params

    def _calculate_confidence(self) -> float:
        """현재 모델의 신뢰도 (최근 승률 기반)."""
        if not self.recent_pnl: return 0.5
        win_rate = len([p for p in self.recent_pnl if p > 0]) / len(self.recent_pnl)
        return win_rate

    async def feedback(self, result: ExecutionResult):
        """거래 결과 수신 및 학습 큐 추가."""
        await self.update_queue.put(result)

    async def _training_loop(self):
        """백그라운드에서 성과 데이터 학습."""
        logger.info("Adaptive Learning Loop Started.")
        while True:
            try:
                result = await self.update_queue.get()
                
                # 결과 기록 (학습)
                pnl = result.pnl_pct
                self.recent_pnl.append(pnl)
                
                logger.info(f"📝 학습 완료: PnL {pnl*100:.2f}% (최근 {len(self.recent_pnl)}회 평균: {sum(self.recent_pnl)/len(self.recent_pnl)*100:.2f}%)")
                
                self.update_queue.task_done()
            except Exception as e:
                logger.error(f"Learning loop error: {e}")
