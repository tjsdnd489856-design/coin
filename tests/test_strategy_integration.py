import pytest
import pandas as pd
from src.strategy.scalping_strategy import ScalpingStrategy

@pytest.mark.asyncio
async def test_ai_parameter_adaptation():
    """AI 파라미터 제안이 전략에 반영되는지 테스트"""
    strategy = ScalpingStrategy()
    
    # 1. 가짜 차트 데이터 생성 (RSI 약 40, 거래량 증가 상황 연출)
    # 50개의 캔들 데이터 생성
    data = []
    base_price = 1000
    for i in range(50):
        # 완만한 하락 후 횡보 (RSI 낮게 유지)
        close = base_price - (i * 0.5)
        if i > 40: close = base_price - 20 + (i - 40) # 막판 소폭 반등
        
        data.append([
            pd.Timestamp.now(), 
            close, close+1, close-1, close, 
            100.0 # 평소 거래량
        ])
    
    # 마지막 캔들 거래량 살짝 증가 (110 -> 1.1배)
    data[-1][5] = 110.0
    
    # 지표 업데이트
    await strategy.update_indicators(data)
    
    # 강제로 지표 설정 (테스트 정확성을 위해)
    strategy.rsi = 40.0
    strategy.volume_ratio = 1.1
    strategy.ma_5 = 1000
    strategy.ma_20 = 990 # 정배열 조건 충족
    strategy.bb_upper = 1050 # 볼린저 밴드 여유 있음
    
    current_ticker = {'last': 1005}
    
    # ---------------------------------------------------------
    # Case A: 기본 설정 (RSI > 45, Vol > 1.2 필요)
    # 현상황: RSI 40, Vol 1.1 -> 매수 실패 예상
    # ---------------------------------------------------------
    signal_default = await strategy.check_signal(current_ticker, ai_pred=None)
    assert signal_default is False, "기본 조건에서는 매수되지 않아야 함"
    
    # ---------------------------------------------------------
    # Case B: AI가 파라미터 완화 제안 (RSI > 30, Vol > 1.0)
    # 현상황: RSI 40, Vol 1.1 -> 매수 성공 예상
    # ---------------------------------------------------------
    ai_pred = {
        'suggested_params': {
            'rsi_buy_threshold': 30,
            'volume_multiplier': 1.0,
            'stop_loss_pct': 0.02,
            'take_profit_pct': 0.05
        },
        'confidence_score': 0.8
    }
    
    signal_ai = await strategy.check_signal(current_ticker, ai_pred=ai_pred)
    assert signal_ai is True, "AI 파라미터 적용 시 매수되어야 함"
    
    # 내부 변수가 실제로 변경되었는지 확인
    assert strategy.rsi_lower_bound == 30
    assert strategy.volume_threshold == 1.0
