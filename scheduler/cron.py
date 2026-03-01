"""
스케줄러 — 장중(09:00~15:30 KST) 매 1시간 자동 분석
Final_Score ≥ SIGNAL_THRESHOLD_STRONG → Slack 알림
"""
import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from slack_sdk.web.async_client import AsyncWebClient

load_dotenv()

logger = logging.getLogger("scheduler")

KST = ZoneInfo("Asia/Seoul")

THRESHOLD = int(os.getenv("SIGNAL_THRESHOLD_STRONG", "70"))


async def _notify_slack(result: dict) -> None:
    """매수 신호 발생 시 Slack 채널에 알림을 전송합니다."""
    from slack.bot import _to_slack_md, _score_emoji, _score_bar

    token      = os.getenv("SLACK_BOT_TOKEN")
    channel_id = os.getenv("SLACK_CHANNEL_ID")
    if not token or not channel_id:
        logger.warning("Slack 토큰 또는 채널 ID 없음 — 알림 스킵")
        return

    ticker  = result["ticker"]
    final   = result["final_score"]
    signal  = result["signal_text"]
    scores  = result["scores"]
    reports = result["reports"]
    emoji   = _score_emoji(final)

    # 가격 조회
    try:
        from mcp_server.tools.price import get_price_data
        price_data  = await get_price_data(ticker, "1mo")
        company     = price_data.get("company_name", ticker)
        latest      = price_data.get("latest", {})
        close_price = f"{latest.get('close', 'N/A'):,}" if isinstance(latest.get('close'), int) else "N/A"
        change_pct  = latest.get("change_pct", 0)
        change_text = f"{change_pct:+.2f}%"
    except Exception:
        company     = ticker
        close_price = "N/A"
        change_text = "N/A"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🚨 매수 신호: {company} ({ticker})",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*현재가:* {close_price} KRW"},
                {"type": "mrkdwn", "text": f"*전일 대비:* {change_text}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*📊 Final Score: {final}/100* — {signal}\n"
                    f"`{_score_bar(int(final))}`\n\n"
                    f"기술 {scores['tech']}점(×30%) · "
                    f"펀더 {scores['fund']}점(×35%) · "
                    f"매크로 {scores['macro']}점(×20%) · "
                    f"감성 {scores['sent']}점(×15%)"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🏦 PM 종합 의견*\n{_to_slack_md(reports['pm'])[:1500]}",
            },
        },
    ]

    sdk = AsyncWebClient(token=token)
    await sdk.chat_postMessage(
        channel=channel_id,
        text=f"🚨 매수 신호: {company} ({ticker}) — Final Score {final}/100",
        blocks=blocks,
    )
    logger.info(f"Slack 알림 전송 완료: {ticker} (score={final})")


async def _run_watchlist_scan() -> None:
    """워치리스트 전 종목 스캔 — 매수 신호 종목 알림."""
    from db.database import get_watchlist
    from agents.pm_agent import run_full_analysis

    watchlist = await get_watchlist()  # 매번 DB에서 읽어 런타임 변경 즉시 반영
    now_kst = datetime.now(KST)
    logger.info(
        f"[스케줄러] 워치리스트 스캔 시작: "
        f"{now_kst.strftime('%Y-%m-%d %H:%M KST')} "
        f"| 종목 {len(watchlist)}개"
    )

    for ticker in watchlist:
        try:
            logger.info(f"  분석 중: {ticker}")
            result = await run_full_analysis(ticker)
            logger.info(
                f"  {ticker} → Final={result['final_score']} | {result['signal_text']}"
            )

            if result["buy_signal"]:
                await _notify_slack(result)

        except Exception as e:
            logger.error(f"  {ticker} 분석 오류: {e}", exc_info=True)

        # 종목 간 1초 대기 (API 레이트 리밋 배려)
        await asyncio.sleep(1)

    logger.info("[스케줄러] 스캔 완료")


def create_scheduler() -> AsyncIOScheduler:
    """
    APScheduler 인스턴스를 생성하고 잡을 등록합니다.
    장중 09:00~15:30 KST, 매 시간 정각 실행.
    """
    scheduler = AsyncIOScheduler(timezone=KST)

    # 09:00, 10:00, 11:00, 12:00, 13:00, 14:00, 15:00 실행
    scheduler.add_job(
        _run_watchlist_scan,
        trigger=CronTrigger(
            hour="9-15",       # 09시~15시
            minute="0",        # 매 정각
            day_of_week="mon-fri",  # 평일만
            timezone=KST,
        ),
        id="watchlist_scan",
        name="워치리스트 자동 스캔",
        max_instances=1,       # 이전 실행 중에는 중복 실행 방지
        coalesce=True,
    )

    return scheduler
