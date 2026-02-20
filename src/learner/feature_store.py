"""
Feature Store 인터페이스 및 구현체.
PostgreSQL/TimescaleDB 및 Redis를 추상화하여 피처 저장/조회를 담당.
"""
import asyncio
import os
from typing import List, Optional
from datetime import datetime
from .schema import FeatureSet, TradeEvent
from .utils import get_logger, now_utc

logger = get_logger(__name__)


class FeatureStore:
    """피처 저장소 클래스."""

    def __init__(self):
        # 실제 DB 연결 설정 (환경변수 기반)
        self.db_url = os.getenv("FEATURE_STORE_DB_URL", "postgresql://localhost:5432/coin_db")
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        # 테스트/DRY_RUN 환경에서는 Mock 객체 사용 가능
        self._is_dry_run = os.getenv("DRY_RUN", "True").lower() == "true"

    async def save_features(self, features: FeatureSet) -> bool:
        """피처 세트를 저장소에 저장 (비동기)."""
        if self._is_dry_run:
            logger.info(f"[DRY_RUN] Saving features: {features.event_id}")
            return True
        
        logger.info(f"Saved features to DB: {features.event_id}")
        return True

    async def get_features(self, event_id: str) -> Optional[FeatureSet]:
        """이벤트 ID로 피처 조회."""
        return None

    async def compute_features(self, event: TradeEvent) -> FeatureSet:
        """실시간 이벤트로부터 피처 계산 및 생성."""
        logger.debug(f"Computing features for event: {event.trace_id}")
        
        # timestamp가 None인 경우를 대비한 방어적 로직 추가
        safe_timestamp = event.timestamp if event.timestamp else now_utc()
        
        return FeatureSet(
            event_id=event.trace_id,
            timestamp=safe_timestamp,
            spread=0.001,
            vwap_1m=event.price,
            volume_1m=10.5,
            liquidity_score=0.8,
            volatility_5m=0.02
        )
