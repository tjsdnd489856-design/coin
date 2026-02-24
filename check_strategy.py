import asyncio
import os
import pandas as pd
from src.connector.exchange_base import ExchangeConnector
from src.strategy.scalping_strategy import ScalpingStrategy

async def test_current_market():
    connector = ExchangeConnector()
    strategy = ScalpingStrategy()
    
    test_symbols = ["BTC/KRW", "ETH/KRW", "SOL/KRW"]
    
    print("--- Market Data & Indicator Test ---")
    
    for symbol in test_symbols:
        try:
            ohlcv = await connector.fetch_ohlcv(symbol, timeframe='1m', limit=50)
            ticker = await connector.fetch_ticker(symbol)
            
            if not ohlcv or not ticker:
                print(f"[{symbol}] Data Load Failed")
                continue
                
            await strategy.update_indicators(ohlcv)
            
            print(f"[{symbol}] Price: {ticker['last']}")
            print(f" - RSI: {strategy.rsi:.2f}")
            print(f" - Vol Ratio: {strategy.volume_ratio:.2f}")
            print(f" - Trend (MA5 > MA20): {strategy.ma_5 > strategy.ma_20}")
            
            is_buy = await strategy.check_signal(ticker, {"confidence_score": 0.5})
            print(f" - Signal: {'BUY' if is_buy else 'WAIT'}")
                
        except Exception as e:
            print(f"[{symbol}] Error: {e}")

    print("--- Test End ---")

if __name__ == "__main__":
    asyncio.run(test_current_market())
