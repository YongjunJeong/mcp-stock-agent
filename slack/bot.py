"""
Slack Bot (Socket Mode, 채널 멘션 방식)
Multi-Agent 분석 결과를 Slack Block Kit으로 표시합니다.

사용 방법:
  채널에서 @봇을 멘션하고 종목 코드 또는 회사명을 입력합니다.
  @봇 삼성전자
  @봇 005930
  @봇 하이닉스 분석해줘
  @봇 도움
"""

import asyncio
import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("slack-bot")

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

app = AsyncApp(token=SLACK_BOT_TOKEN)

# ── 회사명 → ticker 매핑 (한국 주식만, 이 프로젝트는 KR 전용) ──────
COMPANY_MAP: dict[str, str] = {
    "삼성전자":        "005930",
    "삼성":           "005930",
    "sk하이닉스":      "000660",
    "하이닉스":        "000660",
    "hynix":          "000660",
    "네이버":          "035420",
    "naver":          "035420",
    "카카오":          "035720",
    "kakao":          "035720",
    "lg에너지솔루션":  "373220",
    "lg엔솔":         "373220",
    "현대차":          "005380",
    "현대자동차":      "005380",
    "기아":           "000270",
    "기아차":         "000270",
    "포스코":          "005490",
    "posco":          "005490",
    "셀트리온":        "068270",
    "삼성바이오로직스": "207940",
    "삼바":           "207940",
    "카카오뱅크":      "323410",
    "크래프톤":        "259960",
    "krafton":        "259960",
    "엘지화학":        "051910",
    "lg화학":         "051910",
    "삼성sdi":        "006400",
    "한국전력":        "015760",
    "kepco":          "015760",
    "kb금융":         "105560",
    "신한지주":        "055550",
    "하나금융지주":    "086790",
}

_SKIP_WORDS = {
    "US", "KR", "IS", "IN", "AT", "TO", "AN", "AI",
    "IT", "OR", "BE", "BY", "ON", "NO", "SO", "DO",
    "GO", "UP", "OK", "HI", "BUY", "THE", "FOR", "AND",
}


# ── 마크다운 변환 ─────────────────────────────────────────────────────
def _to_slack_md(text: str) -> str:
    """Gemini 마크다운 → Slack mrkdwn 변환. STRATEGY 블록은 제거."""
    text = re.sub(r"STRATEGY_START.*?STRATEGY_END", "", text, flags=re.DOTALL)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"^#{1,3}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*---+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\*\-]\s+", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── 투자 전략 파서 ────────────────────────────────────────────────────
def _parse_strategy(pm_report: str) -> dict | None:
    """
    PM 리포트의 STRATEGY_START...STRATEGY_END 블록을 파싱합니다.
    Returns dict with keys: 진입가, 목표가1, 목표가2, 손절기준, 보유기간
    """
    m = re.search(r"STRATEGY_START\s*(.*?)\s*STRATEGY_END", pm_report, re.DOTALL)
    if not m:
        return None
    result = {}
    for line in m.group(1).strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result if len(result) >= 3 else None


# ── 종목 파싱 ─────────────────────────────────────────────────────────
def _parse_ticker(raw_text: str) -> str | None:
    """
    멘션 텍스트에서 KR 종목 코드를 추출합니다.

    우선순위:
      1. 회사명/브랜드명 매핑
      2. 6자리 숫자 → KR 코드
    """
    text = re.sub(r"<@[A-Z0-9]+>", "", raw_text).strip()
    text_lower = text.lower()

    # 1) 회사명 (가장 긴 키 우선)
    for key in sorted(COMPANY_MAP.keys(), key=len, reverse=True):
        if key in text_lower:
            return COMPANY_MAP[key]

    # 2) 6자리 숫자
    m = re.search(r"\b([0-9]{6})\b", text)
    if m:
        return m.group(1)

    return None


# ── 스코어 → 이모지 ──────────────────────────────────────────────────
def _score_emoji(score: float) -> str:
    if score >= 70:
        return "🚨"
    if score >= 55:
        return "⚠️"
    if score >= 40:
        return "🟡"
    return "⚪"


def _score_bar(score: int, length: int = 10) -> str:
    """점수를 텍스트 막대그래프로 표현 (0~100)"""
    filled = round(score / 100 * length)
    return "█" * filled + "░" * (length - filled)


# ── 분석 실행 + Slack 답장 ───────────────────────────────────────────
async def _analyze_and_reply(ticker: str, say, thread_ts: str | None = None) -> None:
    """Multi-Agent 분석을 실행하고 Slack에 결과를 전송합니다."""
    from agents.pm_agent import run_full_analysis

    kwargs = {"thread_ts": thread_ts} if thread_ts else {}

    # 로딩 메시지 먼저 전송
    loading = await say(
        text=f"🔍 `{ticker}` 분석 중... (4개 전문가 Agent 실행)",
        **kwargs,
    )

    try:
        result = await run_full_analysis(ticker)

        final  = result["final_score"]
        signal = result["signal_text"]
        scores = result["scores"]
        reports = result["reports"]

        # 매크로 raw_data에서 US 시장 추출
        macro_raw = result.get("raw_data", {}).get("macro", {})
        us_markets = macro_raw.get("us_markets", {})
        vix_info   = us_markets.get("vix", {})
        sp500_info = us_markets.get("sp500", {})

        # 종목명 & 최신가
        from mcp_server.tools.price import get_price_data
        price_data  = await get_price_data(ticker, "1mo")
        company     = price_data.get("company_name", ticker)
        latest      = price_data.get("latest", {})
        close_price = f"{latest.get('close', 'N/A'):,}" if isinstance(latest.get('close'), int) else "N/A"
        change_pct  = latest.get("change_pct", 0)
        change_text = f"{change_pct:+.2f}%" if change_pct else "N/A"

        emoji = _score_emoji(final)

        # ── Slack Block Kit 구성 ─────────────────────────────
        blocks = [
            # 헤더
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {company} ({ticker}) 멀티에이전트 분석",
                },
            },
            # 가격 + 글로벌 컨텍스트
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*현재가:* {close_price} KRW"},
                    {"type": "mrkdwn", "text": f"*전일 대비:* {change_text}"},
                    {"type": "mrkdwn", "text": f"*S&P500:* {sp500_info.get('signal', 'N/A')}"},
                    {"type": "mrkdwn", "text": f"*VIX:* {vix_info.get('signal', 'N/A')}"},
                ],
            },
            {"type": "divider"},
            # Final Score
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*📊 Final Score: {final}/100* — {signal}\n"
                        f"`{_score_bar(int(final))}` {final}점"
                    ),
                },
            },
            # 4개 에이전트 점수
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*📈 기술적 분석* (×30%)\n"
                            f"`{_score_bar(scores['tech'], 8)}` {scores['tech']}점"
                        ),
                    },
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*📋 펀더멘털 분석* (×35%)\n"
                            f"`{_score_bar(scores['fund'], 8)}` {scores['fund']}점"
                        ),
                    },
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*🌐 매크로 분석* (×20%)\n"
                            f"`{_score_bar(scores['macro'], 8)}` {scores['macro']}점"
                        ),
                    },
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*📰 감성 분석* (×15%)\n"
                            f"`{_score_bar(scores['sent'], 8)}` {scores['sent']}점"
                        ),
                    },
                ],
            },
            {"type": "divider"},
            # PM 종합 의견 (STRATEGY 블록은 _to_slack_md에서 제거됨)
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🏦 PM 종합 의견*\n{_to_slack_md(reports['pm'])[:2800]}",
                },
            },
        ]

        # ── 투자 전략 섹션 (항상 표시) ─────────────────────────
        strategy = _parse_strategy(reports["pm"])
        if strategy:
            is_buy   = result["buy_signal"]
            hdr_icon = "🚨 매수 전략" if is_buy else "⏳ 관망 중 — 진입 시나리오"
            blocks += [
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*💰 {hdr_icon}*"},
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*진입가*\n`{strategy.get('진입가', 'N/A')}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*보유기간*\n`{strategy.get('보유기간', 'N/A')}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*1차 목표가*\n`{strategy.get('목표가1', 'N/A')}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*2차 목표가*\n`{strategy.get('목표가2', 'N/A')}`",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*🛑 손절기준*  `{strategy.get('손절기준', 'N/A')}`",
                    },
                },
            ]

        # Safety Brake / 매수 신호 강조 섹션 추가
        if result.get("safety_brake"):
            blocks.insert(3, {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "⛔ *Safety Brake 발동* — USD/KRW 1,450원↑ + 급등 동시 감지. 매수 차단.",
                },
            })
        elif result["buy_signal"]:
            blocks.insert(3, {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "🚨 *매수 신호 감지!* Final Score ≥ 70 달성",
                },
            })

        # 로딩 메시지 → 결과로 교체
        sdk = AsyncWebClient(token=SLACK_BOT_TOKEN)
        await sdk.chat_update(
            channel=loading["channel"],
            ts=loading["ts"],
            text=f"{emoji} {company} 분석 완료 (Final: {final}/100 | {signal})",
            blocks=blocks,
        )

    except Exception as e:
        logger.error(f"분석 오류 [{ticker}]: {e}", exc_info=True)
        await say(text=f"❌ 분석 중 오류 발생: `{str(e)[:200]}`", **kwargs)


# ── 이벤트 핸들러 ─────────────────────────────────────────────────────
@app.event("app_mention")
async def handle_mention(event, say):
    text       = event.get("text", "")
    thread     = event.get("thread_ts") or event.get("ts")
    text_clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip().lower()

    # 도움말
    if any(k in text_clean for k in ("도움", "help", "사용법", "?")):
        await say(
            thread_ts=thread,
            text="사용법",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "*📈 멀티에이전트 주식 분석 봇 사용법*\n\n"
                            "*종목 조회 (한국 주식):*\n"
                            "• `@봇 삼성전자`\n"
                            "• `@봇 005930`\n"
                            "• `@봇 하이닉스 분석해줘`\n"
                            "• `@봇 카카오 사도 돼?`\n\n"
                            "*분석 구성:*\n"
                            "• 📈 기술적 에이전트 (RSI, MACD, 패턴) × 40%\n"
                            "• 📋 펀더멘털 에이전트 (PER, EPS) × 40%\n"
                            "• 📰 감성 에이전트 (뉴스 심리) × 20%\n"
                            "• 🏦 PM 에이전트 (종합 의견)\n\n"
                            "• `@봇 도움` → 이 메시지"
                        ),
                    },
                }
            ],
        )
        return

    # 종목 분석
    ticker = _parse_ticker(text)
    if ticker is None:
        await say(
            thread_ts=thread,
            text=(
                "종목을 인식하지 못했어요. 이렇게 입력해 보세요:\n"
                "• `@봇 삼성전자`\n"
                "• `@봇 005930`\n"
                "• `@봇 도움` 으로 전체 사용법 확인"
            ),
        )
        return

    await _analyze_and_reply(ticker, say, thread_ts=thread)


@app.event("message")
async def handle_message(event, logger):
    pass


# ── Bot 시작 ──────────────────────────────────────────────────────────
async def start_bot():
    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    logger.info("Slack Multi-Agent Bot 시작 (Socket Mode)")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(start_bot())
