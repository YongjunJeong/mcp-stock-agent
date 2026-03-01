"""
Technical Agent
페르소나: 20년 경력 차트 분석가. 보조지표 간 Divergence 탐지 전문.
사용 Tool: get_technical_indicators + analyze_chart_pattern
출력: score(0-100) + report(str)
"""
import json
import logging

from agents.gemini_client import call_gemini, extract_score
from mcp_server.tools.technical import get_technical_indicators
from mcp_server.tools.pattern import analyze_chart_pattern

logger = logging.getLogger("agents.technical")

# ── System Prompt ────────────────────────────────────────────────────
_SYSTEM = """당신은 20년 경력의 한국 주식 차트 분석 전문가입니다.
RSI, MACD, 볼린저밴드, 거래량 지표와 차트 패턴을 종합해 매수 적합도를 평가합니다.

핵심 분석 관점:
1. 보조지표 간 Divergence (가격↑ & RSI↓ = Bearish Divergence → 위험 신호)
2. MACD 히스토그램 0선 교차 및 모멘텀 방향
3. 볼린저밴드 %B 위치와 스퀴즈(밴드 수축) 여부
4. 거래량 확인 (가격 움직임에 거래량이 동반되어야 신뢰도↑)
5. 탐지된 차트 패턴의 신뢰도

출력 형식 (반드시 준수):
[기술적 분석 요약 - 3~5문장]
[주요 강점]
[주요 위험 요인]
SCORE: [0-100 사이 정수]

0=매우 약세, 50=중립, 100=매우 강세. 숫자만, 소수점 없이."""

# ── 메인 함수 ────────────────────────────────────────────────────────

async def run_technical_agent(ticker: str, period: str = "6mo") -> dict:
    """
    기술적 분석을 수행하고 점수와 리포트를 반환합니다.

    Returns:
        dict: {"score": int, "report": str, "raw_data": dict}
    """
    logger.info(f"[Technical Agent] 분석 시작: {ticker}")

    # ── Step 1: Tool 직접 호출 (MCP 오버헤드 없이) ─────────────────
    tech_data    = await get_technical_indicators(ticker, period)
    pattern_data = await analyze_chart_pattern(ticker, period)

    if "error" in tech_data:
        return {
            "score":  50,
            "report": f"기술적 데이터 조회 실패: {tech_data['error']}",
            "raw_data": {},
        }

    # ── Step 2: 데이터 → 텍스트 요약 (Gemini 토큰 절약) ──────────
    user_prompt = _build_prompt(ticker, tech_data, pattern_data)

    # ── Step 3: Gemini 1회 호출 ────────────────────────────────────
    response = await call_gemini(_SYSTEM, user_prompt)

    if not response:
        score = _fallback_score(tech_data)
        return {
            "score":    score,
            "report":  f"[LLM 호출 실패, 규칙 기반 점수] {_fallback_summary(tech_data)}",
            "raw_data": tech_data,
        }

    score = extract_score(response)
    logger.info(f"[Technical Agent] {ticker} → score={score}")

    return {
        "score":    score,
        "report":  response,
        "raw_data": tech_data,
    }


# ── 프롬프트 빌더 ────────────────────────────────────────────────────

def _build_prompt(ticker: str, tech: dict, patterns: dict) -> str:
    rsi   = tech.get("rsi", {})
    macd  = tech.get("macd", {})
    bb    = tech.get("bollinger", {})
    vol   = tech.get("volume", {})

    # 패턴 요약
    pat_list = patterns.get("patterns", [])
    pat_text = (
        ", ".join(f"{p['name']}(신뢰도 {p['confidence']})" for p in pat_list)
        if pat_list else "탐지된 패턴 없음"
    )

    # 최근 RSI 추세 (5봉)
    rsi_hist = tech.get("history", {}).get("rsi", [])
    rsi_trend = " → ".join(str(v) for v in rsi_hist[-5:]) if rsi_hist else "N/A"

    # 최근 MACD 히스토그램 추세 (5봉)
    macd_hist_vals = tech.get("history", {}).get("macd_hist", [])
    macd_trend = " → ".join(str(v) for v in macd_hist_vals[-5:]) if macd_hist_vals else "N/A"

    return f"""종목코드: {ticker}

[보조지표 현재값]
- RSI(14): {rsi.get('value', 'N/A')} → {rsi.get('signal', 'N/A')}
  최근 5봉 RSI 추세: {rsi_trend}
- MACD 히스토그램: {macd.get('histogram', 'N/A')} → {macd.get('signal_type', 'N/A')}
  최근 5봉 MACD 히스토그램 추세: {macd_trend}
- 볼린저밴드 %B: {bb.get('pct_b', 'N/A')} → {bb.get('signal', 'N/A')}
  상단: {bb.get('upper', 'N/A')} / 중단: {bb.get('middle', 'N/A')} / 하단: {bb.get('lower', 'N/A')}
- 거래량 비율(20MA 대비): {vol.get('ratio', 'N/A')}x → {vol.get('signal', 'N/A')}

[탐지된 차트 패턴]
{pat_text}

위 데이터를 종합해 기술적 관점에서 현재 매수 적합도를 평가하세요.
Divergence 여부를 반드시 언급하고, SCORE를 마지막 줄에 출력하세요."""


# ── 폴백 (Gemini 실패 시 규칙 기반) ─────────────────────────────────

def _fallback_score(tech: dict) -> int:
    """Gemini 호출 실패 시 규칙 기반으로 점수를 계산합니다."""
    score = 50
    rsi = tech.get("rsi", {}).get("value", 50)
    macd_sig = tech.get("macd", {}).get("signal_type", "")
    bb_pct = tech.get("bollinger", {}).get("pct_b", 0.5)
    vol_ratio = tech.get("volume", {}).get("ratio", 1.0)

    if rsi <= 30:
        score += 15
    elif rsi >= 70:
        score -= 10

    if "골든크로스" in macd_sig:
        score += 15
    elif "데드크로스" in macd_sig:
        score -= 15
    elif "상승모멘텀" in macd_sig:
        score += 8

    if bb_pct <= 0.1:
        score += 10
    elif bb_pct >= 0.9:
        score -= 10

    if vol_ratio >= 1.5:
        score += 5

    return max(0, min(100, score))


def _fallback_summary(tech: dict) -> str:
    rsi = tech.get("rsi", {})
    macd = tech.get("macd", {})
    return (
        f"RSI {rsi.get('value')} ({rsi.get('signal')}), "
        f"MACD {macd.get('signal_type')}"
    )
