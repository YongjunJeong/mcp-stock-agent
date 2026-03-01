"""
PM Agent (Portfolio Manager)
4개 전문가 Agent의 리포트를 종합해 최종 투자 의견을 생성합니다.

Final_Score = (Tech × 0.30) + (Fund × 0.35) + (Macro × 0.20) + (Sent × 0.15)

가중치 근거:
- Fundamental 35%: 기업의 내재가치가 장기 수익의 핵심
- Technical 30%: 매수 타이밍과 단기 모멘텀 포착
- Macro 20%: 환율·외국인 수급이 한국 증시에 큰 영향
- Sentiment 15%: 기업 뉴스 심리 (노이즈 많아 가중치 낮춤)

매수 신호 임계값: Final_Score ≥ 70
"""
import logging
import os

from agents.gemini_client import call_gemini
from agents.technical_agent import run_technical_agent
from agents.fundamental_agent import run_fundamental_agent
from agents.macro_agent import run_macro_agent
from agents.sentiment_agent import run_sentiment_agent

logger = logging.getLogger("agents.pm")

# ── 가중치 ───────────────────────────────────────────────────────────
WEIGHT_TECH = 0.30
WEIGHT_FUND = 0.35
WEIGHT_MACRO = 0.20
WEIGHT_SENT = 0.15

def _buy_threshold() -> int:
    return int(os.getenv("SIGNAL_THRESHOLD_STRONG", "70"))

# ── System Prompt ────────────────────────────────────────────────────
_SYSTEM = """당신은 헤지펀드 포트폴리오 매니저입니다.
기술적 분석가, 펀더멘털 분석가, 매크로 전략가, 감성 분석가의 리포트를 종합해 최종 투자 의견을 작성합니다.

출력 형식 (반드시 준수):
[종합 투자 의견 - 3~5문장, 4개 관점의 합의점과 불일치 포인트 명시]
[매수 근거 (Final_Score ≥ 70인 경우) 또는 관망/매도 이유 (< 70인 경우)]
[핵심 리스크 요인 (매크로 리스크 / 기업 내부 리스크 구분해서 명시)]

리포트 마지막에 반드시 아래 블록을 정확히 출력하세요 (마커 포함, N/A 사용 금지):
- 매수 신호: 현재 매수 가능한 구체적 전략
- 관망: "진입 조건이 충족될 경우"의 가상 시나리오로 작성 (예: "~원 이하 조정 시 진입")
STRATEGY_START
진입가: [구체적 가격대 또는 조건. 예: 73,000~75,000원 (분할매수) / 조정 시 70,000원 이하]
목표가1: [1차 목표가 및 예상 수익률. 예: 82,000원 (+11%)]
목표가2: [2차 목표가 및 예상 수익률. 예: 92,000원 (+24%)]
손절기준: [구체적 손절 가격 및 최대 손실률. 예: 67,000원 (-9%, 60일선 하방 이탈 시)]
보유기간: [단기(1~2개월) / 중기(3~6개월) / 장기(6개월+) 중 택1 및 이유 1문장]
STRATEGY_END"""

# ── 메인 함수 ────────────────────────────────────────────────────────

async def run_full_analysis(ticker: str, period: str = "6mo") -> dict:
    """
    4개 Agent를 순차 실행하고 PM Agent가 종합합니다.

    Returns:
        dict: {
            "ticker": str,
            "final_score": float,
            "buy_signal": bool,
            "scores": {"tech": int, "fund": int, "macro": int, "sent": int},
            "reports": {"tech": str, "fund": str, "macro": str, "sent": str, "pm": str},
            "raw_data": dict,
        }
    """
    logger.info(f"[PM Agent] 전체 분석 시작: {ticker}")

    # ── Step 1: 4개 전문가 Agent 순차 실행 ────────────────────────
    tech_result  = await run_technical_agent(ticker, period)
    fund_result  = await run_fundamental_agent(ticker)
    macro_result = await run_macro_agent()          # ticker 무관, 시장 전체 지표
    sent_result  = await run_sentiment_agent(ticker, days=7)

    tech_score  = tech_result["score"]
    fund_score  = fund_result["score"]
    macro_score = macro_result["score"]
    sent_score  = sent_result["score"]

    # ── Step 2: Final_Score 계산 (Python에서 수행) ─────────────────
    final_score = round(
        tech_score  * WEIGHT_TECH
        + fund_score  * WEIGHT_FUND
        + macro_score * WEIGHT_MACRO
        + sent_score  * WEIGHT_SENT,
        1,
    )

    # ── Safety Brake: 1,450원 이상 + 3일 급등 시 매수 강제 차단 ───
    safety_brake = False
    usd_data = macro_result.get("raw_data", {}).get("usd_krw", {})
    if usd_data.get("alerts", {}).get("safety_brake", False):
        safety_brake = True
        final_score  = min(final_score, 35.0)   # 점수 강제 상한 35
        buy_signal   = False
        signal_text  = "⛔ 매수 차단 (Safety Brake 발동)"
    elif usd_data.get("alerts", {}).get("panic_zone", False):
        # Panic Zone만 (급등은 아님): 점수 상한 49
        final_score  = min(final_score, 49.0)
        buy_signal   = False
        signal_text  = "🚨 매수 자제 (Panic Zone)"
    else:
        buy_signal  = final_score >= _buy_threshold()
        signal_text = "★ 매수 신호" if buy_signal else "관망"

    logger.info(
        f"[PM Agent] {ticker} → "
        f"Tech:{tech_score}×0.30 + Fund:{fund_score}×0.35 + "
        f"Macro:{macro_score}×0.20 + Sent:{sent_score}×0.15 "
        f"= Final:{final_score} → {signal_text}"
    )

    # ── Step 3: PM Agent Gemini 호출 ───────────────────────────────
    pm_prompt   = _build_pm_prompt(
        ticker, final_score, buy_signal,
        tech_score, tech_result["report"],
        fund_score, fund_result["report"],
        macro_score, macro_result["report"],
        sent_score, sent_result["report"],
    )
    pm_response = await call_gemini(_SYSTEM, pm_prompt)

    if not pm_response:
        pm_response = _fallback_pm_report(
            ticker, final_score, buy_signal,
            tech_score, fund_score, macro_score, sent_score,
        )

    return {
        "ticker":        ticker,
        "final_score":   final_score,
        "buy_signal":    buy_signal,
        "signal_text":   signal_text,
        "safety_brake":  safety_brake,
        "scores": {
            "tech":  tech_score,
            "fund":  fund_score,
            "macro": macro_score,
            "sent":  sent_score,
        },
        "reports": {
            "tech":  tech_result["report"],
            "fund":  fund_result["report"],
            "macro": macro_result["report"],
            "sent":  sent_result["report"],
            "pm":    pm_response,
        },
        "raw_data": {
            "tech":  tech_result.get("raw_data", {}),
            "fund":  fund_result.get("raw_data", {}),
            "macro": macro_result.get("raw_data", {}),
            "sent":  sent_result.get("raw_data", {}),
        },
    }


# ── 프롬프트 빌더 ────────────────────────────────────────────────────

def _build_pm_prompt(
    ticker: str, final_score: float, buy_signal: bool,
    tech_score: int, tech_report: str,
    fund_score: int, fund_report: str,
    macro_score: int, macro_report: str,
    sent_score: int, sent_report: str,
) -> str:
    signal_text = "★ 매수 신호" if buy_signal else "관망"
    threshold   = _buy_threshold()

    def trim(text: str, n: int = 450) -> str:
        return text[:n] + "..." if len(text) > n else text

    return f"""종목코드: {ticker}

[전문가 점수 요약]
- 기술적 분석:    {tech_score}/100  × 30% = {tech_score * 0.30:.1f}점
- 펀더멘털 분석:  {fund_score}/100  × 35% = {fund_score * 0.35:.1f}점
- 매크로 분석:    {macro_score}/100 × 20% = {macro_score * 0.20:.1f}점
- 감성 분석:      {sent_score}/100  × 15% = {sent_score * 0.15:.1f}점
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Final Score:    {final_score}/100 → {signal_text} (임계값: {threshold})

[기술적 분석 리포트]
{trim(tech_report)}

[펀더멘털 분석 리포트]
{trim(fund_report)}

[매크로 분석 리포트]
{trim(macro_report)}

[감성 분석 리포트]
{trim(sent_report)}

4개 전문가의 분석을 종합해 최종 투자 의견을 작성하세요.
매크로 리스크(환율·외국인 수급)와 기업 내부 리스크를 구분해서 언급하고,
구체적인 투자 전략을 제시하세요."""


def _fallback_pm_report(
    ticker: str, final_score: float, buy_signal: bool,
    tech: int, fund: int, macro: int, sent: int,
) -> str:
    signal = "매수 신호" if buy_signal else "관망"
    return (
        f"[{ticker}] 종합 분석 결과\n"
        f"Final Score: {final_score}/100 → {signal}\n"
        f"기술: {tech}점(×30%) | 펀더: {fund}점(×35%) | "
        f"매크로: {macro}점(×20%) | 감성: {sent}점(×15%)\n"
        f"(PM Agent LLM 호출 실패 — 규칙 기반 요약)"
    )
