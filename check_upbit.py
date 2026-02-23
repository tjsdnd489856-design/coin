import asyncio
import os
import sys

# 인코딩 문제 해결
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
from src.connector.exchange_base import ExchangeConnector

load_dotenv()

async def main():
    print("----------------------------------------")
    print(" [UPBIT 연결 테스트]")
    print("----------------------------------------")

    os.environ["EXCHANGE_ID"] = "upbit"
    
    try:
        connector = ExchangeConnector()
        print(f"✅ 커넥터: {connector.exchange_id}")
        
        balance = await connector.fetch_balance()
        if balance:
            # 테스트 모드라면 100만원이 보여야 함
            krw = balance.get('total', {}).get('KRW', 0)
            print(f"💰 원화 잔고: {krw:,.0f}원")
        else:
            print("❌ 잔고 조회 실패")
            
        ticker = await connector.fetch_ticker("BTC/KRW")
        if ticker:
            print(f"📈 비트코인: {ticker['last']:,.0f}원")
            
        await connector.close()
        
    except Exception as e:
        print(f"🚨 에러: {e}")

if __name__ == "__main__":
    asyncio.run(main())
