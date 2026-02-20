"""
공통 유틸리티 및 로깅 설정 모듈.
최신 파이썬 시간 규격 반영.
"""
import logging
import os
import sys
from datetime import datetime, timezone

# 로깅 설정
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout
)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

def now_utc() -> datetime:
    """현재 UTC 시간 반환 (최신 방식)."""
    return datetime.now(timezone.utc)
