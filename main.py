"""
메인 진입점 — Slack Bot + 스케줄러를 동시에 실행합니다.

실행:
  python main.py
"""
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


async def main():
    from slack.bot import start_bot
    from scheduler.cron import create_scheduler

    # 스케줄러 시작
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("스케줄러 시작 완료 (장중 09:00~15:00 KST, 매 정각)")

    # Slack Bot 시작 (블로킹)
    logger.info("Slack Bot 시작...")
    await start_bot()


if __name__ == "__main__":
    asyncio.run(main())
