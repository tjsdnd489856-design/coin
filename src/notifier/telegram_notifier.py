"""
텔레그램 통신 최적화 모듈.
세션을 유지하여 불필요한 로그를 줄이고 응답 속도를 향상함.
"""
import os
import asyncio
from telegram import Bot
from src.learner.utils import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    """텔레그램 알림 및 수신 최적화 클래스."""

    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.is_enabled = bool(self.token and self.chat_id)
        self.last_update_id = 0
        
        if self.is_enabled:
            # 세션을 유지하기 위해 Bot 객체를 한 번만 생성
            self.bot = Bot(token=self.token)
        else:
            logger.warning("텔레그램 설정이 없습니다.")

    async def send_message(self, text: str):
        """메시지 전송."""
        if not self.is_enabled:
            return

        try:
            # 헬스체크(getMe) 로그를 줄이기 위해 직접 호출
            await self.bot.send_message(chat_id=self.chat_id, text=text)
        except Exception as e:
            logger.error(f"텔레그램 전송 실패: {e}")

    async def get_recent_command(self) -> str:
        """명령어 수신."""
        if not self.is_enabled:
            return ""

        try:
            # 타임아웃을 짧게 주어 루프가 지연되지 않게 함
            updates = await self.bot.get_updates(offset=self.last_update_id + 1, timeout=0.5)
            for update in updates:
                self.last_update_id = update.update_id
                if update.message and str(update.message.chat_id) == str(self.chat_id) and update.message.text:
                    return update.message.text.strip()
        except Exception:
            # 통신 오류는 무시하고 다음 루프로 진행
            pass
        
        return ""
