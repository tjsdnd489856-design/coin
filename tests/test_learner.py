"""
학습 모듈 단위 테스트.
pytest 기반 Mock 테스트.
"""
import pytest
import asyncio
from datetime import datetime
from src.learner.online_learner import OnlineLearner
from src.learner.schema import TradeEvent, ExecutionResult

# Mock 환경변수 설정
@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "True")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")


@pytest.mark.asyncio
async def test_online_learner_prediction():
    """온라인 학습기 예측 기능 테스트."""
    learner = OnlineLearner()
    
    event = TradeEvent(
        trace_id="test-trace-123",
        timestamp=datetime.utcnow(),
        exchange="binance",
        symbol="BTC/USDT",
        side="buy",
        price=50000.0,
        quantity=1.0
    )
    
    prediction = await learner.predict(event)
    
    assert prediction is not None
    assert prediction.model_version is not None
    # Mock 모델의 기본값 확인
    assert prediction.recommended_split_count == 3 


@pytest.mark.asyncio
async def test_online_learner_feedback():
    """피드백 루프 처리 테스트 (큐 동작 확인)."""
    learner = OnlineLearner()
    
    result = ExecutionResult(
        order_id="order-123",
        feature_set_id="feat-123",
        actual_slippage=0.002,
        execution_time_ms=120,
        partial_fill_ratio=0.0,
        cost=5.0
    )
    
    # 큐에 넣기
    await learner.feedback(result)
    
    # 비동기 처리 대기 (조금 기다림)
    await asyncio.sleep(0.1)
    
    # 큐가 비워졌는지 확인 (training loop가 처리했는지)
    assert learner.update_queue.empty()
