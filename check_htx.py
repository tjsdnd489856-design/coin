"""
HTX 거래소 연결 및 잔고 조회 테스트.
"""
import asyncio
import os
import sys

# Windows에서 UTF-8 출력 강제 설정
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
from src.connector.exchange_base import ExchangeConnector

# 환경 변수 로드
load_dotenv()

async def main():
    print("----------------------------------------")
    print(" [HTX 연결 테스트 시작]")
    print("----------------------------------------")
    
    # 1. 환경 변수 강제 설정 (테스트용)
    os.environ["EXCHANGE_ID"] = "htx"
    os.environ["DRY_RUN"] = "False"
    
    try:
        # 2. 커넥터 생성
        connector = ExchangeConnector()
        print(f"✅ 커넥터 초기화 완료: {connector.exchange_id}")
        
        # 3. 잔고 조회 (API 키 정상 작동 확인)
        print("🔍 잔고 조회 중...")
        balance = await connector.fetch_balance()
        
        if balance:
            print("\n💰 [잔고 조회 성공]")
            total_usdt = balance.get('total', {}).get('USDT', 0)
            free_usdt = balance.get('free', {}).get('USDT', 0)
            print(f"- USDT (총액): {total_usdt}")
            print(f"- USDT (가용): {free_usdt}")
            
            # 보유 중인 다른 코인 출력
            count = 0
            for coin, amount in balance.get('total', {}).items():
                if amount > 0 and coin != 'USDT':
                    print(f"- {coin}: {amount}")
                    count += 1
            if count == 0:
                print("(USDT 외 보유 코인 없음)")
        else:
            print("\n❌ 잔고 조회 실패 (응답이 비어있음)")
            
        # 4. 시세 조회 (BTC/USDT)
        print("\n📈 [시세 조회 테스트]")
        ticker = await connector.fetch_ticker("BTC/USDT")
        if ticker:
            btc_price = ticker['last']
            print(f"- BTC/USDT 현재가: {btc_price}")
        else:
            print("❌ 시세 조회 실패")
            
        # 5. 연결 종료
        await connector.close()
        print("\n✅ 테스트 완료 (모두 정상입니다)")
        
    except Exception as e:
        print(f"\n🚨 [에러 발생] {e}")
        print("팁: API 키나 IP 제한 설정을 다시 확인해 보세요.")

if __name__ == "__main__":
    asyncio.run(main())
