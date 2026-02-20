"""
거래 관련 데이터 모델 및 스키마 정의 모듈.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class TradeEvent(BaseModel):
    """실시간 거래 이벤트 데이터 모델."""
    trace_id: str
    timestamp: datetime
    exchange: str
    symbol: str
    side: str
    price: float
    quantity: float
    order_type: str = "market"
    meta: Dict[str, Any] = Field(default_factory=dict)


class FeatureSet(BaseModel):
    """모델 입력용 피처 세트."""
    event_id: str
    timestamp: datetime
    # 시장 상태 피처
    spread: float
    vwap_1m: float
    volume_1m: float
    # 거래소 메타
    liquidity_score: float
    # 파생 피처
    volatility_5m: float
    
    class Config:
        arbitrary_types_allowed = True


class Prediction(BaseModel):
    """모델 예측 결과."""
    model_version: str
    recommended_split_count: int
    estimated_slippage: float
    confidence_score: float
    meta: Dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """실제 체결 결과 (라벨링용)."""
    order_id: str
    feature_set_id: str
    actual_slippage: float
    execution_time_ms: float
    partial_fill_ratio: float
    cost: float
