"""
텔레그램 메시지 전송 모듈.
"""
import os
import asyncio
from telegram import Bot
from src.learner.utils import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    """텔레그램 알림 발송 클래스."""

    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.is_enabled = bool(self.token and self.chat_id)
        
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
            # 텔레그램 API 호출 (비동기)
            async with self.bot:
                await self.bot.send_message(chat_id=self.chat_id, text=text)
            logger.debug("텔레그램 메시지 전송 완료.")
        except Exception as e:
            logger.error(f"텔레그램 메시지 전송 실패: {e}")
