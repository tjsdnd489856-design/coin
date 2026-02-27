import pytest
import pandas as pd
from src.strategy.scalping_strategy import ScalpingStrategy

@pytest.mark.asyncio
async def test_fixed_parameter_strategy():
    """고정 파라미터 기반 매수 신호 테스트"""
    strategy = ScalpingStrategy()
    
    data = []
    base_price = 1000
    for i in range(50):
        close = base_price - (i * 0.5)
        if i > 40: close = base_price - 20 + (i - 40)
        
        data.append([
            pd.Timestamp.now(), 
            close, close+1, close-1, close, 
            100.0
        ])
    
    data[-1][5] = 130.0 # 볼륨 급증 처리 (100 -> 130: 1.3배)
    
    await strategy.update_indicators(data)
    
    # 지표 강제 조작 (매수 조건 충족 여부 테스트)
    strategy.rsi = 50.0 # 하한선(45) 초과
    strategy.volume_ratio = 1.3 # 볼륨 하한선(1.2) 초과
    strategy.ma_5 = 1000
    strategy.ma_20 = 990 
    strategy.bb_upper = 1050 
    
    current_ticker = {'last': 1005}
    
    signal = await strategy.check_signal(current_ticker)
    assert signal is True, "모든 조건 만족 시 매수되어야 함"

    # 하나라도 조건 미충족 시 매수 안됨 테스트
    strategy.rsi = 40.0 # 미충족
    signal_fail = await strategy.check_signal(current_ticker)
    assert signal_fail is False, "조건 미충족 시 매수되지 않아야 함"
