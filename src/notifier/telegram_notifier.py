"""
텔레그램 메시지 전송 및 수신 모듈.
"""
import os
import asyncio
from telegram import Bot
from src.learner.utils import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    """텔레그램 알림 발송 및 사용자 명령 수신 클래스."""

    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.is_enabled = bool(self.token and self.chat_id)
        self.last_update_id = 0 # 읽어온 마지막 메시지 ID
        
        if self.is_enabled:
            self.bot = Bot(token=self.token)
        else:
            logger.warning("텔레그램 설정이 없습니다. 알림 기능이 비활성화됩니다.")

    async def send_message(self, text: str):
        """메시지 전송 (비동기)."""
        if not self.is_enabled:
            logger.info(f"[NOTIFIER SKIP] {text}")
            return

        try:
            async with self.bot:
                await self.bot.send_message(chat_id=self.chat_id, text=text)
            logger.debug("텔레그램 메시지 전송 완료.")
        except Exception as e:
            logger.error(f"텔레그램 메시지 전송 실패: {e}")

    async def get_recent_command(self) -> str:
        """사용자가 보낸 최근 명령어를 읽어옴."""
        if not self.is_enabled:
            return ""

        try:
            async with self.bot:
                updates = await self.bot.get_updates(offset=self.last_update_id + 1, timeout=1)
                for update in updates:
                    self.last_update_id = update.update_id
                    # 지정된 chat_id를 가진 사용자가 보낸 텍스트 메시지만 처리
                    if update.message and str(update.message.chat_id) == str(self.chat_id) and update.message.text:
                        return update.message.text.strip()
        except Exception as e:
            logger.error(f"텔레그램 메시지 수신 에러: {e}")
        
        return ""
