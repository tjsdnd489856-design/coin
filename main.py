"""
자동 매매 시스템의 메인 진입점.
모든 모듈을 초기화하고 매매 루프를 실행.
"""
import asyncio
import os
import signal
from dotenv import load_dotenv
from src.strategy_manager import StrategyManager
from src.learner.utils import get_logger

# 환경 변수 로드 (.env 파일이 있으면 읽어옴)
load_dotenv()

logger = get_logger("Main")


async def main():
    """시스템 초기화 및 실행."""
    logger.info("========================================")
    logger.info("   Coin Auto-Trading System 시작")
    logger.info("========================================")
    
    manager = StrategyManager()
    
    # 프로그램 종료 신호 처리 (Ctrl+C 등)
    loop = asyncio.get_running_loop()
    
    def stop_handler():
        logger.info("종료 신호를 수신했습니다. 안전하게 정지합니다...")
        manager.stop()
        
    # 윈도우 환경과 리눅스 환경의 신호 처리 차이 대응
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_handler)
    except NotImplementedError:
        # 윈도우에서는 signal handler가 제한적일 수 있음
        pass

    try:
        # 실제 매매 루프 시작
        await manager.start()
    except KeyboardInterrupt:
        logger.info("사용자에 의해 프로그램이 중단되었습니다.")
    except Exception as e:
        logger.error(f"시스템 실행 중 치명적 에러 발생: {e}")
    finally:
        manager.stop()
        logger.info("시스템이 완전히 종료되었습니다.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
