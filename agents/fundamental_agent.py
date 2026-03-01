"""
Fundamental Agent
페르소나: 보수적 가치 투자자. 분기 실적 연속성과 현금흐름 질 최우선.
사용 Tool: get_financial_statements
출력: score(0-100) + report(str)
"""
import logging

from agents.gemini_client import call_gemini, extract_score
from mcp_server.tools.fundamental import get_financial_statements

logger = logging.getLogger("agents.fundamental")

# ── System Prompt ────────────────────────────────────────────────────
_SYSTEM = """당신은 20년 경력의 보수적 가치 투자자입니다.
분기 실적 연속성, PER/PBR 밸류에이션, 배당 안정성을 최우선으로 평가합니다.

핵심 분석 관점:
1. PER: 업종 평균 대비 저평가 여부 (한국 코스피 평균 PER ≈ 10~14배)
2. PBR: 1.0 미만이면 자산 가치 대비 저평가 (특히 금융/제조업)
3. EPS: 양(+)이어야 기본 조건, 성장세가 있으면 가점
4. 배당수익률: 시중금리(한국 기준금리 약 2.5~3%) 대비 매력도
5. 시가총액: 규모에 따른 리스크 프리미엄 고려

출력 형식 (반드시 준수):
[펀더멘털 분석 요약 - 3~5문장]
[투자 매력 포인트]
[위험 및 우려 사항]
SCORE: [0-100 사이 정수]

0=매우 고평가/실적 악화, 50=중립, 100=심각한 저평가+실적 성장.
숫자만, 소수점 없이."""

# ── 메인 함수 ────────────────────────────────────────────────────────

async def run_fundamental_agent(ticker: str) -> dict:
    """
    펀더멘털 분석을 수행하고 점수와 리포트를 반환합니다.

    Returns:
        dict: {"score": int, "report": str, "raw_data": dict}
    """
    logger.info(f"[Fundamental Agent] 분석 시작: {ticker}")

    # ── Step 1: Tool 직접 호출 ─────────────────────────────────────
    fund_data = await get_financial_statements(ticker)

    if "error" in fund_data:
        return {
            "score":   50,
            "report":  f"펀더멘털 데이터 조회 실패: {fund_data['error']}",
            "raw_data": {},
        }

    # ── Step 2: 텍스트 요약 → Gemini 1회 호출 ─────────────────────
    user_prompt = _build_prompt(ticker, fund_data)
    response    = await call_gemini(_SYSTEM, user_prompt)

    if not response:
        score = _fallback_score(fund_data)
        return {
            "score":   score,
            "report":  f"[LLM 호출 실패, 규칙 기반 점수] {_fallback_summary(fund_data)}",
            "raw_data": fund_data,
        }

    score = extract_score(response)
    logger.info(f"[Fundamental Agent] {ticker} → score={score}")

    return {
        "score":   score,
        "report":  response,
        "raw_data": fund_data,
    }


# ── 프롬프트 빌더 ────────────────────────────────────────────────────

def _build_prompt(ticker: str, fund: dict) -> str:
    val = fund.get("valuation", {})
    sig = fund.get("signals", {})
    cap = fund.get("market_cap_billion_krw")
    cap_text = f"{cap:,.0f}억원" if cap else "N/A"

    per = val.get("per")
    pbr = val.get("pbr")
    eps = val.get("eps")
    div = val.get("div_yield")

    per_text = f"{per:.2f}배" if per else "N/A (적자 또는 데이터없음)"
    pbr_text = f"{pbr:.2f}배" if pbr else "N/A"
    eps_text = f"{eps:,.0f}원" if eps else "N/A"
    div_text = f"{div:.2f}%" if div else "N/A"

    return f"""종목코드: {ticker}

[밸류에이션 지표]
- PER: {per_text}
- PBR: {pbr_text}
- EPS: {eps_text}
- 배당수익률: {div_text}
- 시가총액: {cap_text}

[자동 평가 신호]
- 밸류에이션: {sig.get('valuation', 'N/A')}

[참고 기준]
- 코스피 평균 PER: 10~14배
- 한국 기준금리: 약 2.5~3% (배당수익률 비교 기준)
- PBR 1.0 미만: 자산 대비 저평가 구간

위 데이터를 종합해 보수적 가치 투자자 관점에서 현재 투자 매력도를 평가하세요.
SCORE를 마지막 줄에 출력하세요."""


# ── 폴백 ─────────────────────────────────────────────────────────────

def _fallback_score(fund: dict) -> int:
    score = 50
    sig = fund.get("signals", {}).get("valuation", "")
    val = fund.get("valuation", {})

    if "심한저평가" in sig:
        score += 30
    elif "저평가" in sig:
        score += 15
    elif "고평가" in sig:
        score -= 15
    elif "심한고평가" in sig:
        score -= 25
    elif "적자" in sig:
        score -= 20

    div = val.get("div_yield") or 0
    if div >= 3.0:
        score += 10
    elif div >= 1.5:
        score += 5

    return max(0, min(100, score))


def _fallback_summary(fund: dict) -> str:
    val = fund.get("valuation", {})
    sig = fund.get("signals", {})
    return (
        f"PER {val.get('per')}배 / PBR {val.get('pbr')}배 / "
        f"EPS {val.get('eps')}원 / 밸류에이션: {sig.get('valuation')}"
    )
