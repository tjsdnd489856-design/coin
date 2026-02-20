"""
공통 유틸리티 및 로깅 설정 모듈.
"""
import logging
import os
import sys
from datetime import datetime

# 로깅 설정
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] [trace_id=%(trace_id)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout
)

def get_logger(name: str) -> logging.Logger:
    """모듈별 로거 반환."""
    return logging.getLogger(name)


class ContextFilter(logging.Filter):
    """Trace ID를 로그 레코드에 주입하는 필터."""
    def filter(self, record):
        if not hasattr(record, 'trace_id'):
            record.trace_id = 'N/A'
        return True


def setup_logger(logger_name: str, trace_id: str = None) -> logging.Logger:
    """Trace ID 컨텍스트가 포함된 로거 설정."""
    logger = logging.getLogger(logger_name)
    # 이미 필터가 있다면 추가하지 않음
    if not any(isinstance(f, ContextFilter) for f in logger.filters):
        logger.addFilter(ContextFilter())
    return logger


def now_utc() -> datetime:
    """현재 UTC 시간 반환."""
    return datetime.utcnow()
