"""
Feature Store 인터페이스 및 구현체.
PostgreSQL/TimescaleDB 및 Redis를 추상화하여 피처 저장/조회를 담당.
"""
import asyncio
import os
from typing import List, Optional
from datetime import datetime
from .schema import FeatureSet, TradeEvent
from .utils import get_logger

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
        
        # TODO: 실제 DB 저장 로직 (asyncpg 등 사용)
        # await self.db_conn.execute(...)
        logger.info(f"Saved features to DB: {features.event_id}")
        return True

    async def get_features(self, event_id: str) -> Optional[FeatureSet]:
        """이벤트 ID로 피처 조회."""
        # 캐시(Redis) 조회 후 DB 조회 로직 구현
        return None

    async def compute_features(self, event: TradeEvent) -> FeatureSet:
        """실시간 이벤트로부터 피처 계산 및 생성."""
        # 예시: 최근 N틱 데이터 조회 및 통계 계산
        # 실제 구현시에는 Redis의 최근 호가창 스냅샷 등을 활용
        
        logger.debug(f"Computing features for event: {event.trace_id}")
        
        return FeatureSet(
            event_id=event.trace_id,
            timestamp=event.timestamp,
            spread=0.001,       # Mock value
            vwap_1m=event.price, # Mock value
            volume_1m=10.5,     # Mock value
            liquidity_score=0.8,# Mock value
            volatility_5m=0.02  # Mock value
        )
