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
            rsi_buy_threshold=30,
            stop_loss_pct=0.005,
            take_profit_pct=0.015,
            volume_multiplier=1.3
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
        """최근 성과(승률, 손익비, 기대값)에 따라 전략 파라미터 동적 튜닝."""
        if not self.recent_pnl:
            return self.current_params

        profits = [p for p in self.recent_pnl if p > 0]
        losses = [p for p in self.recent_pnl if p <= 0]
        
        win_rate = len(profits) / len(self.recent_pnl)
        avg_profit = sum(profits) / len(profits) if profits else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.001
        
        profit_factor = (sum(profits) / abs(sum(losses))) if losses and sum(losses) != 0 else 2.0
        expected_value = (win_rate * avg_profit) - ((1 - win_rate) * avg_loss)
        
        new_params = self.current_params.model_copy()

        # [튜닝 로직 1] 기대값이 음수이거나 손익비가 1.0 미만 (손실 구간)
        if expected_value < 0 or profit_factor < 1.1:
            logger.debug(f"📉 성과 저조 (EV: {expected_value:.4f}, PF: {profit_factor:.2f}). 보수적 설정 적용.")
            new_params.k = min(0.85, new_params.k + 0.05)
            new_params.rsi_buy_threshold = max(20, new_params.rsi_buy_threshold - 2)
            new_params.volume_multiplier = min(1.8, new_params.volume_multiplier + 0.1)
            # 손절은 더 짧게, 익절은 더 길게 (손익비 개선 시도)
            new_params.stop_loss_pct = max(0.005, new_params.stop_loss_pct - 0.001)
            
        # [튜닝 로직 2] 성과 우수 (손익비 1.5 이상, 기대값 양수)
        elif profit_factor > 1.5 and expected_value > 0.002:
            logger.debug(f"📈 성과 우수 (PF: {profit_factor:.2f}). 기회 확대.")
            new_params.k = max(0.35, new_params.k - 0.03)
            new_params.rsi_buy_threshold = min(35, new_params.rsi_buy_threshold + 2)
            new_params.volume_multiplier = max(1.5, new_params.volume_multiplier - 0.2)

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
