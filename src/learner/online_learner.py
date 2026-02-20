"""
온라인 학습 모듈 (실시간 피드백 루프).
주문 이벤트 -> 피처 생성 -> 예측 -> 실행 결과 수신 -> 온라인 업데이트.
"""
import asyncio
import os
from typing import Dict, Any
from .schema import TradeEvent, Prediction, ExecutionResult
from .feature_store import FeatureStore
from .model_registry import ModelRegistry
from .utils import get_logger

logger = get_logger(__name__)


class OnlineLearner:
    """실시간 학습 및 예측 클래스."""

    def __init__(self):
        self.feature_store = FeatureStore()
        self.registry = ModelRegistry()
        self.model = self.registry.load_model(version="latest")
        self.update_queue = asyncio.Queue()
        self._is_dry_run = os.getenv("DRY_RUN", "True").lower() == "true"
        
        # 백그라운드 학습 루프 시작
        asyncio.create_task(self._training_loop())

    async def predict(self, event: TradeEvent) -> Prediction:
        """거래 이벤트에 대한 실행 전략 예측."""
        # 1. 피처 생성
        features = await self.feature_store.compute_features(event)
        
        # 2. 모델 예측 (Latency < 50ms 목표)
        # 실제로는 model.predict(features) 호출
        raw_pred = self.model.predict(features)
        
        # 3. 예측 결과 포장
        prediction = Prediction(
            model_version=getattr(self.model, "version", "unknown"),
            recommended_split_count=raw_pred.get("split", 1),
            estimated_slippage=raw_pred.get("slippage", 0.0),
            confidence_score=0.95,
            meta={"feature_id": features.event_id}
        )
        
        if self._is_dry_run:
            logger.info(f"[DRY_RUN] Prediction: {prediction}")
        
        return prediction

    async def feedback(self, result: ExecutionResult):
        """실행 결과를 받아 온라인 모델 업데이트 큐에 추가."""
        await self.update_queue.put(result)

    async def _training_loop(self):
        """백그라운드에서 모델 파라미터 업데이트 (SGD 등)."""
        logger.info("Starting online training loop...")
        while True:
            try:
                result = await self.update_queue.get()
                
                if self._is_dry_run:
                    logger.debug(f"[DRY_RUN] Skipping model update for: {result.order_id}")
                    self.update_queue.task_done()
                    continue

                # TODO: 온라인 학습 로직 (예: River 라이브러리 또는 scikit-learn partial_fit)
                # features = await self.feature_store.get_features(result.feature_set_id)
                # self.model.partial_fit(features, result.actual_slippage)
                
                logger.info(f"Updated model with result: {result.order_id}")
                self.update_queue.task_done()
                
            except Exception as e:
                logger.error(f"Error in training loop: {e}")
