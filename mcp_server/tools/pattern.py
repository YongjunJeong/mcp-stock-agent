"""
Tool 3: analyze_chart_pattern
Double Bottom, IH&S, 박스권 돌파, 삼각수렴 패턴을 근사 알고리즘으로 탐지합니다.
최종 해석은 Technical Agent(LLM)가 수행합니다.
"""
import logging
from datetime import datetime, timedelta

import numpy as np
from pykrx import stock as krx

logger = logging.getLogger("mcp.tools.pattern")


async def analyze_chart_pattern(ticker: str, period: str = "6mo") -> dict:
    """
    최근 가격 데이터에서 주요 차트 패턴을 탐지합니다.

    Args:
        ticker: 종목 코드
        period: 조회 기간

    Returns:
        dict: 탐지된 패턴 목록 + 패턴별 신뢰도 + 원시 OHLCV
    """
    period_days = {"3mo": 120, "6mo": 210, "1y": 400}
    days  = period_days.get(period, 210)
    end   = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    try:
        df = krx.get_market_ohlcv_by_date(start, end, ticker)
        if df.empty or len(df) < 40:
            return {"error": f"데이터 부족: {ticker} ({len(df)}봉)"}

        close  = df["종가"].astype(float).values
        high   = df["고가"].astype(float).values
        low    = df["저가"].astype(float).values
        volume = df["거래량"].astype(float).values
        dates  = [d.strftime("%Y-%m-%d") for d in df.index]

        patterns = []

        # ── 1. Double Bottom ────────────────────────────────────
        db = _detect_double_bottom(low, close)
        if db["detected"]:
            patterns.append(db)

        # ── 2. Inverse Head & Shoulders ────────────────────────
        ihs = _detect_ihs(low, close)
        if ihs["detected"]:
            patterns.append(ihs)

        # ── 3. 박스권 돌파 (Breakout) ───────────────────────────
        bo = _detect_breakout(close, high, volume)
        if bo["detected"]:
            patterns.append(bo)

        # ── 4. 삼각수렴 (Triangle Convergence) ─────────────────
        tri = _detect_triangle(high, low, close)
        if tri["detected"]:
            patterns.append(tri)

        # 최근 60봉 OHLCV (LLM이 직접 참고)
        n = min(60, len(close))
        return {
            "ticker":   ticker,
            "patterns": patterns,
            "pattern_count": len(patterns),
            "strongest_pattern": patterns[0]["name"] if patterns else "없음",
            "ohlcv_recent": {
                "dates":  dates[-n:],
                "high":   [int(v) for v in high[-n:]],
                "low":    [int(v) for v in low[-n:]],
                "close":  [int(v) for v in close[-n:]],
                "volume": [int(v) for v in volume[-n:]],
            },
        }

    except Exception as e:
        logger.error(f"패턴 분석 실패 [{ticker}]: {e}")
        return {"error": str(e), "ticker": ticker}


# ── 패턴 탐지 헬퍼 ──────────────────────────────────────────────────

def _detect_double_bottom(low: np.ndarray, close: np.ndarray) -> dict:
    """
    최근 60봉에서 Double Bottom 탐지.
    조건: 두 저점이 5% 이내 유사, 사이에 10% 이상 반등, 두 번째 저점 이후 회복
    """
    base = {"name": "Double Bottom", "detected": False}
    seg = low[-60:]
    if len(seg) < 20:
        return base

    # 국소 저점 탐지 (window=5)
    local_mins = []
    for i in range(5, len(seg) - 5):
        if seg[i] == min(seg[i-5:i+6]):
            local_mins.append(i)

    if len(local_mins) < 2:
        return base

    # 가장 최근 두 저점 비교
    p1, p2 = local_mins[-2], local_mins[-1]
    v1, v2 = seg[p1], seg[p2]

    gap = abs(p2 - p1)
    price_diff_pct = abs(v2 - v1) / v1
    peak_between   = max(seg[p1:p2+1])
    rebound_pct    = (peak_between - min(v1, v2)) / min(v1, v2)

    detected = (
        5 <= gap <= 40         # 저점 사이 간격
        and price_diff_pct <= 0.05  # 두 저점이 5% 이내
        and rebound_pct >= 0.08     # 사이에 8% 이상 반등
        and close[-1] > (v2 * 1.03) # 현재가가 두 번째 저점 대비 회복
    )

    confidence = 0.0
    if detected:
        # 저점 유사도가 높을수록, 반등 폭이 클수록 신뢰도 ↑
        confidence = min(1.0, 0.5 + (0.05 - price_diff_pct) * 5 + rebound_pct * 0.5)

    return {
        "name":       "Double Bottom",
        "detected":   detected,
        "confidence": round(confidence, 2),
        "detail": {
            "bottom1_idx":   int(p1),
            "bottom2_idx":   int(p2),
            "price_diff_pct": round(price_diff_pct * 100, 2),
            "rebound_pct":   round(rebound_pct * 100, 2),
        } if detected else {},
    }


def _detect_ihs(low: np.ndarray, close: np.ndarray) -> dict:
    """역 헤드앤숄더: 세 저점 중 가운데가 가장 낮아야 함"""
    base = {"name": "Inverse H&S", "detected": False}
    seg = low[-80:]
    if len(seg) < 30:
        return base

    local_mins = []
    for i in range(5, len(seg) - 5):
        if seg[i] == min(seg[i-5:i+6]):
            local_mins.append(i)

    if len(local_mins) < 3:
        return base

    ls, head, rs = local_mins[-3], local_mins[-2], local_mins[-1]
    vls, vh, vrs = seg[ls], seg[head], seg[rs]

    # 헤드가 양 어깨보다 낮고, 양 어깨가 서로 비슷
    shoulder_diff = abs(vls - vrs) / max(vls, vrs)
    head_lower    = vh < min(vls, vrs) * 0.97

    detected = head_lower and shoulder_diff <= 0.07 and close[-1] > vrs * 1.02

    return {
        "name":       "Inverse H&S",
        "detected":   detected,
        "confidence": 0.75 if detected else 0.0,
        "detail": {
            "left_shoulder_idx":  int(ls),
            "head_idx":           int(head),
            "right_shoulder_idx": int(rs),
            "shoulder_diff_pct":  round(shoulder_diff * 100, 2),
        } if detected else {},
    }


def _detect_breakout(close: np.ndarray, high: np.ndarray,
                     volume: np.ndarray) -> dict:
    """박스권 돌파: 최근 20봉 박스 상단을 거래량 증가와 함께 돌파"""
    base = {"name": "박스권 돌파", "detected": False}
    if len(close) < 25:
        return base

    box_high = max(high[-25:-5])   # 최근 박스권 상단 (최근 5봉 제외)
    box_low  = min(close[-25:-5])  # 박스권 하단

    # 박스권이 너무 넓으면(30% 초과) 박스 아님
    if (box_high - box_low) / box_low > 0.30:
        return base

    vol_ma20  = np.mean(volume[-25:-5])
    curr_vol  = volume[-1]
    curr_close = close[-1]

    detected = (
        curr_close > box_high * 1.01    # 박스 상단 1% 이상 돌파
        and curr_vol > vol_ma20 * 1.4   # 거래량 40% 이상 증가
    )

    return {
        "name":       "박스권 돌파",
        "detected":   detected,
        "confidence": 0.80 if detected else 0.0,
        "detail": {
            "box_high":      int(box_high),
            "box_low":       int(box_low),
            "current_close": int(curr_close),
            "volume_ratio":  round(float(curr_vol / vol_ma20), 2),
        } if detected else {},
    }


def _detect_triangle(high: np.ndarray, low: np.ndarray,
                     close: np.ndarray) -> dict:
    """
    삼각수렴: 최근 30봉에서 고가 추세선은 하락, 저가 추세선은 상승
    → 변동폭이 점점 줄어드는 패턴
    """
    base = {"name": "삼각수렴", "detected": False}
    seg_h = high[-30:]
    seg_l = low[-30:]
    if len(seg_h) < 15:
        return base

    x = np.arange(len(seg_h), dtype=float)

    # 선형 회귀
    slope_h = float(np.polyfit(x, seg_h, 1)[0])
    slope_l = float(np.polyfit(x, seg_l, 1)[0])

    # 고가 추세↓, 저가 추세↑ = 수렴
    detected = slope_h < 0 and slope_l > 0

    # 수렴도: 범위 축소 비율
    range_start = seg_h[0] - seg_l[0]
    range_end   = seg_h[-1] - seg_l[-1]
    converge_pct = (range_start - range_end) / range_start if range_start > 0 else 0

    detected = detected and converge_pct > 0.20  # 20% 이상 수렴

    return {
        "name":       "삼각수렴",
        "detected":   detected,
        "confidence": round(min(1.0, 0.5 + converge_pct), 2) if detected else 0.0,
        "detail": {
            "high_slope":    round(slope_h, 1),
            "low_slope":     round(slope_l, 1),
            "converge_pct":  round(converge_pct * 100, 1),
        } if detected else {},
    }
