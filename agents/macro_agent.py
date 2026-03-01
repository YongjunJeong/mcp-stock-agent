"""
Macro Agent
페르소나: 글로벌 매크로 전략가. 환율·외국인 수급·지정학 리스크 전문.
사용 Tool: get_macro_indicators
출력: score(0-100) + report(str)

한국 증시 특성:
- 외국인 지분율 높아 외국인 수급이 지수 방향의 핵심 변수
- 달러 강세(원화 약세) = 외국인 이탈 → 지수 하방 압력
  단, 수출 비중 높은 종목(삼성전자, SK하이닉스 등)은 환율 상승이 매출 호재
"""
import logging

from agents.gemini_client import call_gemini, extract_score
from mcp_server.tools.macro import get_macro_indicators

logger = logging.getLogger("agents.macro")

# ── System Prompt ────────────────────────────────────────────────────
_SYSTEM = """당신은 15년 경력의 글로벌 매크로 전략가입니다.
환율·외국인 수급·원화 단독 약세 여부가 한국 개별 주식에 미치는 영향을 분석합니다.

[환율 뉴노멀 판단 기준]
1,380~1,400원을 '중립 구간(뉴노멀)'으로 인정합니다. 환율은 절대 레벨보다 속도(Velocity)가 더 중요합니다.

환율 구간별 위험 등급:
- 1,350 미만:     원화강세 → 외국인 유입 기대, 수출주 일부 불리
- 1,350~1,399:   안정/뉴노멀 → 중립
- 1,400~1,449:   Stress Zone (위험 가중치 2.5배) → 외국인 이탈 주의, 수출주 환율 호재 상충
- 1,450 이상:     Panic/MarginCall Zone (위험 가중치 5배) → 매수신호 무효화 수준

속도(Velocity) 경보:
- 3일 내 1% 이상 상승: 패닉 셀링 전조 → 수급 경보 즉시 발령
- 5일 MA 대비 3% 이상 이격: 단기 과열 급등

[원화 단독 약세 판별]
원/달러 상승 + 엔/달러 하락(엔 강세) 동시 발생 = 원화만 유독 약세.
이는 글로벌 달러 강세가 아닌 한국 고유 내부 리스크(Internal Risk)일 가능성을 강하게 시사합니다.

[핵심 분석 관점]
1. Safety Brake 여부 확인 (1,450원 + 3일 ROC > 1% 동시 발생 시)
2. Stress Zone 여부 + 속도 결합 해석
3. 외국인 순매수/순매도: KOSPI 방향의 가장 강력한 변수
4. 원화 단독 약세 여부: 한국 내부 리스크 판별
5. KOSPI 20일 추세: 시장 전반 방향성
6. VIX 공포 지수 + 미국 증시: 글로벌 리스크온/리스크오프 판단

[VIX(공포 지수) 분석 기준]
- VIX < 20: 시장 안정, 위험선호 정상 → 신흥국 자금 유입 우호적
- VIX 20~25: 경계 진입, 변동성 확대 초기
- VIX 25~30: 주의 구간, 기관 헤지 증가 → 신흥국 자금 일부 이탈
- VIX ≥ 30: 공포 구간 — 글로벌 리스크오프, 신흥국 급격한 자금 이탈
- VIX ≥ 35: 극도 공포(패닉) — 모든 매수 신호 무효화 수준

[미국 증시 ↔ 한국 증시 상관관계]
- KOSPI는 S&P500과 높은 상관관계(r≈0.7~0.8): 미국 증시 방향이 단기 가장 강한 변수
- 나스닥 급락 = 반도체·IT 수출주(삼성전자·SK하이닉스)에 직접 타격
- 미국 증시 강세 + 원화 약세: 수출주 이중 수혜(매출 환율 호재)
- 미국 증시 약세 + VIX 급등: 외국인 이탈 + 환율 상승 복합 충격

[지정학적 리스크 판단 기준]
- 미·중 무역분쟁 / 반도체 수출 규제: 한국 반도체·IT 수출주 밸류에이션 직격
- 러시아-우크라이나 / 중동 갈등: 원자재 가격 상승 → 에너지 비용 → 마진 압박
- 북한 도발 리스크: KRW 급격 약세 촉발, 외국인 이탈 트리거
- 미국 연준(Fed) 금리 결정: 신흥국 자금 흐름의 구조적 변수
지정학적 리스크는 현재 환율·VIX 수준에 반영되어 있음을 감안해 중복 패널티 주의.

[환율의 역설 주의]
환율이 높을 때가 오히려 국장 바닥인 경우도 있습니다.
환율 상승세가 '꺾이는 지점(반전)'을 포착하면 역발상 매수 기회입니다.

출력 형식 (반드시 준수):
[매크로 환경 요약 - 3~5문장: 환율·VIX·미국 증시·외국인·지정학 리스크 포함]
[한국 증시에 유리한 매크로 요인]
[한국 증시에 불리한 매크로 요인 (글로벌 리스크 / 한국 내부 리스크 구분)]
[수출주(반도체·전기전자) vs 내수주 영향 비교]
SCORE: [0-100 사이 정수]

0=Panic Zone+Safety Brake+VIX공포(매수 불가), 50=중립(뉴노멀), 100=원화강세+외국인대거유입+VIX안정.
숫자만, 소수점 없이."""

# ── 메인 함수 ────────────────────────────────────────────────────────

async def run_macro_agent() -> dict:
    """
    매크로 분석을 수행하고 점수와 리포트를 반환합니다.
    ticker 파라미터 없음 — 전체 시장 지표를 분석합니다.

    Returns:
        dict: {"score": int, "report": str, "raw_data": dict}
    """
    logger.info("[Macro Agent] 분석 시작")

    # ── Step 1: Tool 직접 호출 ─────────────────────────────────────
    macro_data = await get_macro_indicators(days=30)

    if "error" in macro_data:
        return {
            "score":   50,
            "report":  f"매크로 데이터 조회 실패: {macro_data['error']}",
            "raw_data": {},
        }

    # ── Step 2: 텍스트 요약 → Gemini 1회 호출 ─────────────────────
    user_prompt = _build_prompt(macro_data)
    response    = await call_gemini(_SYSTEM, user_prompt)

    if not response:
        score = _fallback_score(macro_data)
        return {
            "score":   score,
            "report":  f"[LLM 호출 실패, 규칙 기반 점수] {_fallback_summary(macro_data)}",
            "raw_data": macro_data,
        }

    score = extract_score(response)
    logger.info(f"[Macro Agent] score={score}")

    return {
        "score":   score,
        "report":  response,
        "raw_data": macro_data,
    }


# ── 프롬프트 빌더 ────────────────────────────────────────────────────

def _build_prompt(macro: dict) -> str:
    usd    = macro.get("usd_krw", {})
    jpy    = macro.get("jpy_usd", {})
    kospi  = macro.get("kospi", {}).get("kospi", {})
    kosdq  = macro.get("kospi", {}).get("kosdaq", {})
    flow   = macro.get("foreign_flow", {})
    solo   = macro.get("krw_solo_weak", {})
    sig    = macro.get("signals", {})
    alerts = usd.get("alerts", {})

    # 환율 핵심 지표
    fx_cur     = usd.get("current", "N/A")
    fx_1m_chg  = usd.get("change_1m_pct", 0)
    fx_roc_3d  = usd.get("roc_3d_pct", 0)
    fx_ma5     = usd.get("ma5", "N/A")
    fx_ma5_div = usd.get("ma5_divergence_pct", 0)
    fx_vol     = usd.get("daily_max_vol_5d", 0)
    risk_zone  = usd.get("risk_zone", "N/A")
    risk_wt    = usd.get("risk_weight", 1.0)
    fx_sig     = usd.get("signal", "N/A")

    # 환율 히스토리 (최근 10일)
    fx_vals = usd.get("history", {}).get("values", [])[-10:]
    fx_trend_text = " → ".join(str(v) for v in fx_vals) if fx_vals else "N/A"

    # 경보 현황
    alert_flags = []
    if alerts.get("safety_brake"):  alert_flags.append("⛔ Safety Brake 발동")
    if alerts.get("panic_zone"):    alert_flags.append("🚨 Panic Zone(1450↑)")
    if alerts.get("velocity"):      alert_flags.append("⚡ 3일 급등 경보")
    if alerts.get("volatility"):    alert_flags.append("📊 일변동 10원↑")
    if alerts.get("divergence"):    alert_flags.append("📐 MA5 과이격")
    alert_text = " | ".join(alert_flags) if alert_flags else "없음"

    # KOSPI
    k_close = kospi.get("close", "N/A")
    k_chg   = kospi.get("change_pct", 0)
    k_trend = kospi.get("trend_20d_pct", 0)
    k_sig   = kospi.get("signal", "N/A")

    # 외국인
    net_buy = flow.get("net_buy_billion")
    f_sig   = flow.get("signal", "N/A")
    net_text = f"{net_buy:+,.1f}억원" if isinstance(net_buy, float) else "N/A"

    # 엔화 비교 (원화 단독 약세 판별)
    jpy_trend = jpy.get("trend", "N/A")
    jpy_roc   = jpy.get("roc_7d_pct", 0)

    # 미국 시장
    us = macro.get("us_markets", {})
    sp500  = us.get("sp500",  {})
    nasdaq = us.get("nasdaq", {})
    vix    = us.get("vix",    {})

    return f"""[글로벌 매크로 현황]

▶ USD/KRW 환율 — 레벨 + 속도(Velocity) 분석
- 현재: {fx_cur}원  |  위험 구간: {risk_zone}  |  위험 가중치: {risk_wt}배
- 30일 변화: {fx_1m_chg:+.2f}%  |  3일 ROC: {fx_roc_3d:+.3f}%
- 5일 MA: {fx_ma5}원  |  MA5 이격도: {fx_ma5_div:+.2f}%
- 최근 5일 최대 일변동: {fx_vol:.1f}원
- 최근 10일 추이: {fx_trend_text}
- 신호: {fx_sig}
- 경보: {alert_text}

▶ 원화 vs 엔화 (단독 약세 판별)
- USD/JPY 7일 추세: {jpy_trend} ({jpy_roc:+.2f}%)
- 판별: {solo.get('interpretation', 'N/A')}

▶ 국내 증시
- KOSPI: {k_close} ({k_chg:+.2f}%)  |  20일 추세: {k_trend:+.2f}% ({k_sig})
- KOSDAQ: {kosdq.get('close', 'N/A')} ({kosdq.get('change_pct', 0):+.2f}%)

▶ 외국인 수급 (KOSPI)
- 순매수: {net_text}  |  신호: {f_sig}

▶ 미국 증시 및 VIX 공포 지수
- S&P500:  {sp500.get('current', 'N/A')} ({sp500.get('change_pct', 0):+.2f}%) → {sp500.get('signal', 'N/A')}
- NASDAQ:  {nasdaq.get('current', 'N/A')} ({nasdaq.get('change_pct', 0):+.2f}%) → {nasdaq.get('signal', 'N/A')}
- VIX:     {vix.get('current', 'N/A')} → {vix.get('signal', 'N/A')}

▶ 종합 환경 판단
- {sig.get('overall', 'N/A')}

위 데이터를 바탕으로 현재 매크로 환경을 평가하세요.
Safety Brake 발동 여부, 원화 단독 약세 여부, 환율 속도와 방향을 반드시 언급하고,
VIX 공포 지수와 미국 증시가 한국 수출주/내수주에 미치는 영향도 분석하세요.
현재 진행 중인 지정학적 리스크(미·중 무역갈등, 연준 정책 방향 등)가 있다면 반영하세요.
SCORE를 마지막 줄에 출력하세요."""


# ── 폴백 ─────────────────────────────────────────────────────────────

def _fallback_score(macro: dict) -> int:
    """
    비선형 리스크 가중치를 반영한 규칙 기반 매크로 점수.
    Safety Brake → 즉시 25점 이하
    """
    score  = 50
    usd    = macro.get("usd_krw", {})
    flow   = macro.get("foreign_flow", {})
    alerts = usd.get("alerts", {})
    solo   = macro.get("krw_solo_weak", {})

    fx_cur    = usd.get("current", 1390)
    roc_3d    = usd.get("roc_3d_pct", 0)
    risk_wt   = usd.get("risk_weight", 1.0)
    f_sig     = flow.get("signal", "")

    # Safety Brake 발동 → 즉시 최하위
    if alerts.get("safety_brake"):
        return 10

    # 비선형 환율 레벨 패널티 (위험 가중치 적용)
    if fx_cur >= 1450:
        score -= int(25 * risk_wt / 5.0)  # 최대 25점 감점
    elif fx_cur >= 1400:
        score -= int(15 * risk_wt / 2.5)  # 최대 15점 감점
    elif fx_cur < 1350:
        score += 10

    # 속도(Velocity) 패널티 — 비선형 적용
    if alerts.get("velocity"):
        score -= int(10 * risk_wt)         # Panic Zone에서 최대 50점
    elif roc_3d > 0.5:
        score -= 5

    # 원화 단독 약세 추가 패널티
    if solo.get("detected"):
        score -= 10

    # 외국인 수급
    if "순매수" in f_sig:
        score += 15
    elif "순매도" in f_sig:
        score -= 15

    return max(0, min(100, score))


def _fallback_summary(macro: dict) -> str:
    usd  = macro.get("usd_krw", {})
    flow = macro.get("foreign_flow", {})
    sig  = macro.get("signals", {})
    alerts = usd.get("alerts", {})
    brake  = "⛔ Safety Brake 발동 | " if alerts.get("safety_brake") else ""
    return (
        f"{brake}USD/KRW {usd.get('current')}원 "
        f"(3일ROC {usd.get('roc_3d_pct', 0):+.2f}%) | "
        f"외국인 {flow.get('signal')} | {sig.get('overall')}"
    )
