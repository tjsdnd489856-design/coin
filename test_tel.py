import asyncio
import os
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()

async def main():
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    print(f"토큰: {token}")
    print(f"아이디: {chat_id}")
    
    bot = Bot(token=token)
    try:
        async with bot:
            await bot.send_message(chat_id=chat_id, text="🚀 [테스트] 텔레그램 연결에 성공했습니다!")
        print("성공: 메시지를 보냈습니다. 텔레그램을 확인하세요.")
    except Exception as e:
        print(f"실패: 에러가 발생했습니다 -> {e}")

if __name__ == "__main__":
    asyncio.run(main())
