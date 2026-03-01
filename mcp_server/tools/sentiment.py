"""
Tool 5: get_news_sentiment
Naver Finance에서 최근 뉴스를 스크래핑하고 사전 기반 감성 점수를 계산합니다.
최종 감성 해석은 Sentiment Agent(Gemini)가 뉴스 원문을 바탕으로 수행합니다.
"""
import logging
import re
from datetime import datetime, timedelta

import aiohttp

logger = logging.getLogger("mcp.tools.sentiment")

# ── 감성 사전 (한국어) ───────────────────────────────────────────────
_POS_KEYWORDS = [
    "급등", "상승", "호실적", "흑자", "수주", "수출 증가", "신고가",
    "매수", "목표가 상향", "어닝서프라이즈", "성장", "호재", "긍정",
    "증가", "개선", "확대", "최대", "돌파", "신제품", "투자 유치",
    "계약 체결", "실적 개선", "배당 확대", "자사주 매입",
]
_NEG_KEYWORDS = [
    "급락", "하락", "적자", "손실", "소송", "리콜", "파업", "감소",
    "매도", "목표가 하향", "어닝쇼크", "부진", "악재", "부정",
    "축소", "최저", "위기", "제재", "과징금", "분식", "횡령",
    "실적 악화", "대규모 손실", "신용 강등",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


async def get_news_sentiment(ticker: str, days: int = 7) -> dict:
    """
    Naver Finance 뉴스를 조회하고 감성 분석 결과를 반환합니다.

    Args:
        ticker: 종목 코드 (예: "005930")
        days:   조회 기간 (일, 기본 7일)

    Returns:
        dict: 뉴스 목록, 긍정/부정 기사 수, 감성 점수(-1~1), 주요 헤드라인
    """
    try:
        articles = await _fetch_naver_news(ticker, max_pages=3)

        # days 필터링
        cutoff = datetime.now() - timedelta(days=days)
        recent = [a for a in articles if a["date"] >= cutoff]

        if not recent:
            return {
                "ticker":          ticker,
                "article_count":   0,
                "pos_count":       0,
                "neg_count":       0,
                "neutral_count":   0,
                "sentiment_score": 0.0,
                "signal":          "데이터없음",
                "headlines":       [],
                "articles":        [],
            }

        # 감성 점수 계산
        pos_count = 0
        neg_count = 0
        scored    = []

        for art in recent:
            text   = art["title"] + " " + art.get("summary", "")
            score  = _keyword_score(text)
            art["sentiment"] = score
            scored.append(art)
            if score > 0:
                pos_count += 1
            elif score < 0:
                neg_count += 1

        total  = len(recent)
        net_score = (pos_count - neg_count) / total  # -1 ~ 1

        # 주요 헤드라인 (최신 5개)
        headlines = [a["title"] for a in scored[:5]]

        return {
            "ticker":          ticker,
            "article_count":   total,
            "pos_count":       pos_count,
            "neg_count":       neg_count,
            "neutral_count":   total - pos_count - neg_count,
            "sentiment_score": round(net_score, 3),
            "signal":          _sentiment_signal(net_score, total),
            "headlines":       headlines,
            # 전체 기사 목록 (Sentiment Agent LLM이 직접 읽음)
            "articles":        scored[:20],
        }

    except Exception as e:
        logger.error(f"뉴스 감성 분석 실패 [{ticker}]: {e}")
        return {"error": str(e), "ticker": ticker}


# ── 스크래핑 ─────────────────────────────────────────────────────────

async def _fetch_naver_news(ticker: str, max_pages: int = 3) -> list[dict]:
    """
    Naver 모바일 주식 뉴스 API로 종목 뉴스를 가져옵니다.
    응답 형식: [{"tit": 제목, "ohnm": 언론사, "dt": "20260301115508", ...}]
    """
    articles = []
    page_size = 20
    url_tmpl = (
        "https://m.stock.naver.com/api/news/list"
        "?itemCode={ticker}&page={page}&pageSize={size}"
    )

    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(headers=_HEADERS, timeout=timeout) as session:
        for page in range(1, max_pages + 1):
            url = url_tmpl.format(ticker=ticker, page=page, size=page_size)
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json(content_type=None)
            except Exception as e:
                logger.warning(f"뉴스 페이지 {page} 요청 실패: {e}")
                break

            if not data:
                break

            for item in data:
                title  = item.get("tit", "")
                source = item.get("ohnm", "")
                dt_raw = item.get("dt", "")  # "20260301115508"
                summary = item.get("subcontent", "")

                try:
                    date_obj = datetime.strptime(dt_raw[:14], "%Y%m%d%H%M%S")
                except ValueError:
                    date_obj = datetime.now()

                articles.append({
                    "title":    title,
                    "source":   source,
                    "summary":  summary,
                    "date":     date_obj,
                    "date_str": date_obj.strftime("%Y-%m-%d %H:%M"),
                })

    return articles


# ── 감성 분석 헬퍼 ────────────────────────────────────────────────────

def _keyword_score(text: str) -> int:
    """키워드 매칭으로 +1(긍정) / -1(부정) / 0(중립) 반환"""
    text_lower = text.lower()
    pos = sum(1 for kw in _POS_KEYWORDS if kw in text)
    neg = sum(1 for kw in _NEG_KEYWORDS if kw in text)
    if pos > neg:
        return 1
    if neg > pos:
        return -1
    return 0


def _sentiment_signal(score: float, total: int) -> str:
    """감성 점수와 기사량으로 시장 심리 신호 반환"""
    if total < 3:
        return "데이터부족"
    if score >= 0.4:
        return "강한긍정"
    if score >= 0.1:
        return "긍정"
    if score <= -0.4:
        return "강한부정"
    if score <= -0.1:
        return "부정"
    return "중립"
