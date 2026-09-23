"""
메인 진입점 — Slack Bot + 스케줄러를 동시에 실행합니다.

실행:
  python main.py
"""
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from logging_config import setup_logging

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
setup_logging()
logger = logging.getLogger("main")


async def main():
    from db.database import init_db
    await init_db()
    logger.info("DB 초기화 완료")

    from scheduler.cron import create_scheduler
    from slack_bot.bot import start_bot

    # 스케줄러 시작
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("스케줄러 시작 완료 (장중 09:00~15:00 KST, 매 정각)")

    # Slack Bot 시작 (블로킹)
    logger.info("Slack Bot 시작...")
    await start_bot()


if __name__ == "__main__":
    asyncio.run(main())
