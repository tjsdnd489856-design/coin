"""
거래 관련 데이터 모델 및 스키마 정의 모듈.
Pydantic V2 규격에 맞게 수정.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class TradeEvent(BaseModel):
    """실시간 거래 이벤트 데이터 모델."""
    trace_id: str
    timestamp: Optional[datetime] = Field(default_factory=None)
    exchange: str
    symbol: str
    side: str
    price: float
    quantity: float
    order_type: str = "market"
    meta: Dict[str, Any] = Field(default_factory=dict)


class FeatureSet(BaseModel):
    """모델 입력용 피처 세트."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    event_id: str
    timestamp: datetime = Field(default_factory=datetime.now) # 기본값 설정으로 에러 방지
    spread: float
    vwap_1m: float
    volume_1m: float
    liquidity_score: float
    volatility_5m: float


class Prediction(BaseModel):
    """모델 예측 결과."""
    model_version: str
    recommended_split_count: int
    estimated_slippage: float
    confidence_score: float
    meta: Dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """실제 체결 결과."""
    order_id: str
    feature_set_id: str
    actual_slippage: float
    execution_time_ms: float
    partial_fill_ratio: float
    cost: float
