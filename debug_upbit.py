import asyncio
import os
from dotenv import load_dotenv
from src.connector.exchange_base import ExchangeConnector

load_dotenv()

async def debug_connection():
    print("--- Start Connection Test ---")
    connector = ExchangeConnector()
    try:
        # 1. Balance Test
        print("1. Checking Balance...")
        balance = await connector.fetch_balance()
        krw = balance.get('free', {}).get('KRW', 'N/A')
        print(f"Success! KRW Balance: {krw}")
        
        # 2. Ticker Test
        print("2. Checking Market Price (BTC/KRW)...")
        ticker = await connector.fetch_ticker("BTC/KRW")
        price = ticker.get('last', 'N/A')
        print(f"Success! Current Price: {price}")
        
    except Exception as e:
        print("\n!!! ERROR DETECTED !!!")
        print(f"Error Type: {type(e).__name__}")
        print(f"Message: {str(e)}")
        print("\nCheck your API Key and IP whitelist on Upbit website.")
    finally:
        await connector.close()

if __name__ == "__main__":
    asyncio.run(debug_connection())
