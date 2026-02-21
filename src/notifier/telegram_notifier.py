"""
텔레그램 통신 최적화 및 수신 강화 모듈.
명령어 인식률을 높이고 에러 로깅을 강화함.
"""
import os
import asyncio
from telegram import Bot
from src.learner.utils import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    """텔레그램 알림 및 명령어 수신 클래스."""

    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.is_enabled = bool(self.token and self.chat_id)
        self.last_update_id = 0
        
        if self.is_enabled:
            self.bot = Bot(token=self.token)
        else:
            logger.warning("텔레그램 설정이 누락되었습니다. (.env 확인 필요)")

    async def send_message(self, text: str):
        """메시지 전송."""
        if not self.is_enabled:
            return

        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text)
        except Exception as e:
            logger.error(f"텔레그램 메시지 전송 실패: {e}")

    async def get_recent_command(self) -> str:
        """사용자가 보낸 최근 명령어를 안전하게 읽어옴."""
        if not self.is_enabled:
            return ""

        try:
            # 1. 최신 업데이트 가져오기
            updates = await self.bot.get_updates(offset=self.last_update_id + 1, timeout=1)
            
            for update in updates:
                # 다음 번 호출을 위해 마지막 update_id 업데이트
                self.last_update_id = update.update_id
                
                # 2. 메시지 확인
                if update.message and update.message.text:
                    user_chat_id = str(update.message.chat_id)
                    text = update.message.text.strip()
                    
                    # 보안: 설정된 CHAT_ID와 일치하는지 확인
                    if user_chat_id == str(self.chat_id):
                        logger.info(f"📥 텔레그램 명령어 수신: {text}")
                        return text
                    else:
                        logger.warning(f"⚠️ 알 수 없는 사용자({user_chat_id})의 접근 시도: {text}")
        except Exception as e:
            # 타임아웃 에러 등은 무시하되, 치명적 에러는 기록
            if "Conflict" in str(e):
                logger.error("텔레그램 봇 중복 실행 감지. 하나만 켜져 있는지 확인하세요.")
            return ""
        
        return ""
