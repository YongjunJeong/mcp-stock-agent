"""
Tool 4: get_financial_statements
Naver Finance coinfo 페이지에서 PER, PBR, EPS, 배당수익률을 스크래핑합니다.
pykrx로 시가총액 데이터를 보완합니다.
"""
import logging
import re
from datetime import datetime, timedelta

import aiohttp
from bs4 import BeautifulSoup
from pykrx import stock as krx

logger = logging.getLogger("mcp.tools.fundamental")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


async def get_financial_statements(ticker: str) -> dict:
    """
    Naver Finance로 Fundamental 지표를 조회합니다.

    Args:
        ticker: 종목 코드 (예: "005930")

    Returns:
        dict: PER, PBR, EPS, 배당수익률, 시가총액, 밸류에이션 신호
    """
    try:
        per, eps, pbr, bps, div_yield = await _scrape_naver_fundamental(ticker)

        # 시가총액 (pykrx)
        market_cap = _get_market_cap(ticker)

        valuation_signal = _valuation_signal(per, pbr)

        return {
            "ticker": ticker,
            "valuation": {
                "per":        per,
                "eps":        eps,
                "pbr":        pbr,
                "bps":        bps,
                "div_yield":  div_yield,
            },
            "market_cap_billion_krw": (
                round(market_cap / 1e8, 1) if market_cap else None
            ),
            "signals": {
                "valuation": valuation_signal,
            },
            "note": "PER/EPS: 최근 4분기 합산 기준 (Naver Finance)",
        }

    except Exception as e:
        logger.error(f"Fundamental 데이터 조회 실패 [{ticker}]: {e}")
        return {"error": str(e), "ticker": ticker}


# ── 스크래핑 ─────────────────────────────────────────────────────────

async def _scrape_naver_fundamental(ticker: str):
    """
    Naver Finance coinfo 페이지에서 PER, EPS, PBR, BPS, 배당수익률 추출.
    파이프 구분 텍스트에서 숫자 위치를 직접 탐색합니다.
    구조: PER|l|EPS|(날짜)|설명...|32.98|배|l|6,564|원
    """
    url = f"https://finance.naver.com/item/coinfo.nhn?code={ticker}"
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(headers=_HEADERS, timeout=timeout) as session:
        async with session.get(url) as resp:
            html = await resp.text(encoding="euc-kr", errors="replace")

    soup = BeautifulSoup(html, "html.parser")

    # PER/EPS 테이블 찾기
    parts = []
    for t in soup.select("table"):
        txt = t.get_text(separator="|", strip=True)
        if "PER" in txt and "EPS" in txt and "배당수익률" in txt:
            parts = txt.split("|")
            break

    def find_value_after(label: str, unit: str):
        """label 이후 unit 앞에 있는 숫자를 찾음"""
        try:
            idx = next(i for i, p in enumerate(parts) if p.strip() == label)
        except StopIteration:
            return None
        # idx 이후 50 토큰 내에서 unit 직전 숫자 탐색
        for j in range(idx + 1, min(idx + 50, len(parts) - 1)):
            if parts[j + 1].strip() == unit:
                val_str = parts[j].strip().replace(",", "")
                try:
                    return float(val_str)
                except ValueError:
                    return None
        return None

    # PER (단위: 배) — 첫 번째 PER 항목 (실적 PER)
    per = find_value_after("PER", "배")

    # EPS (단위: 원) — 첫 번째 EPS 항목
    eps = find_value_after("EPS", "원")

    # PBR (단위: 배 또는 N/A)
    pbr = find_value_after("PBR", "배")

    # BPS (단위: 원)
    bps = find_value_after("BPS", "원")

    # 배당수익률 (단위: %)
    div_yield = find_value_after("배당수익률", "%")

    return per, eps, pbr, bps, div_yield


def _get_market_cap(ticker: str):
    """pykrx로 최근 시가총액 조회"""
    try:
        end   = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
        df = krx.get_market_cap_by_date(start, end, ticker)
        if not df.empty:
            return int(df["시가총액"].iloc[-1])
    except Exception:
        pass
    return None


# ── 밸류에이션 신호 ──────────────────────────────────────────────────

def _valuation_signal(per, pbr) -> str:
    if per is None:
        return "PER없음(적자추정)"
    if per <= 0:
        return "적자기업"
    if per < 10 and (pbr is None or pbr < 1.0):
        return "심한저평가"
    if per < 15 and (pbr is None or pbr < 1.5):
        return "저평가"
    if per < 25 and (pbr is None or pbr < 3.0):
        return "적정가치"
    if per < 40:
        return "고평가"
    return "심한고평가"
