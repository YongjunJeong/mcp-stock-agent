"""
Sentiment Agent
페르소나: 시장 심리 전문가. 뉴스와 공시의 뉘앙스 파악.
사용 Tool: get_news_sentiment
출력: score(0-100) + report(str)
"""
import logging

from agents.gemini_client import call_gemini, extract_score
from mcp_server.tools.sentiment import get_news_sentiment

logger = logging.getLogger("agents.sentiment")

# ── System Prompt ────────────────────────────────────────────────────
_SYSTEM = """당신은 종목 뉴스 심리 분석 전문가입니다.
개별 기업에 관한 뉴스 헤드라인의 뉘앙스와 감성을 평가합니다.

[분석 범위 제한]
- 환율, 금리, 글로벌 증시, 지정학적 리스크 등 매크로 이슈는 분석하지 마세요.
  (해당 내용은 별도 매크로 에이전트가 담당합니다)
- 오직 해당 종목·기업에 직접 관련된 뉴스만 평가합니다.

핵심 분석 관점:
1. 감성 점수(-1~1): 수치와 실제 헤드라인 내용의 일치 여부 확인
2. 기사량: 많은 기사 = 높은 관심도 (호재든 악재든 변동성↑)
3. 뉘앙스 파악: 표면적 긍정이지만 실질적으로 부정인 경우 탐지
   예: "목표가 하향 조정에도 매수 의견 유지" → 약한 부정
4. 기업 이벤트: 실적 발표, 신제품, M&A, 규제·소송, 경영진 변동
5. 애널리스트 의견: 목표주가 변경, 투자의견 변경

출력 형식 (반드시 준수):
[종목 뉴스 감성 요약 - 3~5문장, 기업 이슈에 집중]
[주요 호재 (기업 관련)]
[주요 악재 또는 리스크 신호 (기업 관련)]
SCORE: [0-100 사이 정수]

0=극단적 부정 심리, 50=중립, 100=극단적 긍정 심리.
숫자만, 소수점 없이."""

# ── 메인 함수 ────────────────────────────────────────────────────────

async def run_sentiment_agent(ticker: str, days: int = 7) -> dict:
    """
    뉴스 감성 분석을 수행하고 점수와 리포트를 반환합니다.

    Returns:
        dict: {"score": int, "report": str, "raw_data": dict}
    """
    logger.info(f"[Sentiment Agent] 분석 시작: {ticker}")

    # ── Step 1: Tool 직접 호출 ─────────────────────────────────────
    sent_data = await get_news_sentiment(ticker, days)

    if "error" in sent_data:
        return {
            "score":   50,
            "report":  f"감성 데이터 조회 실패: {sent_data['error']}",
            "raw_data": {},
        }

    # 기사가 너무 적으면 중립 반환 (LLM 호출 불필요)
    article_count = sent_data.get("article_count", 0)
    if article_count < 3:
        return {
            "score":   50,
            "report":  f"최근 {days}일 내 기사가 {article_count}건으로 부족해 분석 불가. 중립 처리.",
            "raw_data": sent_data,
        }

    # ── Step 2: 텍스트 요약 → Gemini 1회 호출 ─────────────────────
    user_prompt = _build_prompt(ticker, sent_data, days)
    response    = await call_gemini(_SYSTEM, user_prompt)

    if not response:
        # Gemini 실패 시 사전 기반 점수 사용
        score = _fallback_score(sent_data)
        return {
            "score":   score,
            "report":  f"[LLM 호출 실패, 규칙 기반 점수] {_fallback_summary(sent_data)}",
            "raw_data": sent_data,
        }

    score = extract_score(response)
    logger.info(f"[Sentiment Agent] {ticker} → score={score}")

    return {
        "score":   score,
        "report":  response,
        "raw_data": sent_data,
    }


# ── 프롬프트 빌더 ────────────────────────────────────────────────────

def _build_prompt(ticker: str, sent: dict, days: int) -> str:
    total   = sent.get("article_count", 0)
    pos     = sent.get("pos_count", 0)
    neg     = sent.get("neg_count", 0)
    neutral = sent.get("neutral_count", 0)
    score   = sent.get("sentiment_score", 0)
    signal  = sent.get("signal", "N/A")

    # 헤드라인 (최대 10개)
    headlines = sent.get("headlines", [])[:10]
    headline_text = "\n".join(f"  {i+1}. {h}" for i, h in enumerate(headlines))
    if not headline_text:
        headline_text = "  (헤드라인 없음)"

    # 전체 기사 제목 (최대 15개, LLM 직접 분석용)
    articles = sent.get("articles", [])[:15]
    article_text = "\n".join(
        f"  [{a.get('date_str', '')}] ({a.get('source', '')}) {a.get('title', '')}"
        for a in articles
    )

    return f"""종목코드: {ticker} | 분석 기간: 최근 {days}일

[감성 통계]
- 총 기사 수: {total}건
- 긍정: {pos}건 / 부정: {neg}건 / 중립: {neutral}건
- 사전 기반 감성 점수: {score:.3f} ({signal})

[주요 헤드라인 (최신 순)]
{headline_text}

[전체 기사 목록 (LLM 분석용)]
{article_text}

위 뉴스를 종합해 현재 시장 심리를 평가하세요.
표면적 수치와 실제 뉘앙스 차이를 반드시 검토하고, SCORE를 마지막 줄에 출력하세요."""


# ── 폴백 ─────────────────────────────────────────────────────────────

def _fallback_score(sent: dict) -> int:
    """Gemini 실패 시 사전 기반 감성 점수로 환산"""
    raw_score = sent.get("sentiment_score", 0)  # -1 ~ 1
    # -1→0, 0→50, 1→100 선형 변환
    return max(0, min(100, int((raw_score + 1) / 2 * 100)))


def _fallback_summary(sent: dict) -> str:
    return (
        f"기사 {sent.get('article_count')}건 | "
        f"감성점수 {sent.get('sentiment_score')} ({sent.get('signal')})"
    )
