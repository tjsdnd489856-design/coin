"""
거래 데이터 모델 및 AI 전략 파라미터 스키마.
자가 적응형(Self-Adaptive) 파라미터 튜닝 지원.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class TradeParams(BaseModel):
    """AI가 제안하는 동적 전략 파라미터."""
    k: float = 0.5               # 변동성 돌파 계수
    rsi_buy_threshold: int = 30  # RSI 매수 기준
    stop_loss_pct: float = 0.02  # 손절 비율
    take_profit_pct: float = 0.04 # 익절 비율
    volume_multiplier: float = 1.5 # 거래량 급증 기준 (평소 대비 배수)


class TradeEvent(BaseModel):
    """실시간 거래 감시 이벤트."""
    trace_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    exchange: str
    symbol: str
    side: str
    price: float
    quantity: float
    order_type: str = "market"
    meta: Dict[str, Any] = Field(default_factory=dict)


class FeatureSet(BaseModel):
    """학습용 피처 세트."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    event_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    spread: float = 0.0
    vwap_1m: float = 0.0
    volume_1m: float = 0.0
    liquidity_score: float = 0.0
    volatility_5m: float = 0.0


class Prediction(BaseModel):
    """AI 모델의 예측 및 전략 제안."""
    model_version: str
    suggested_params: TradeParams # AI가 최적화한 파라미터
    estimated_slippage: float = 0.0
    confidence_score: float = 0.0
    meta: Dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """매매 결과 및 피드백 데이터."""
    order_id: str
    filled_price: float
    filled_quantity: float = 0.0
    status: str = "filled"
    actual_slippage: float = 0.0
    pnl_pct: float = 0.0 # 수익률 (중요: 학습 레이블)
    strategy_type: str = "unknown"
    meta: Dict[str, Any] = Field(default_factory=dict)
