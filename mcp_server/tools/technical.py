"""
Tool 2: get_technical_indicators
RSI, MACD, Bollinger Bands, Volume Ratio를 pykrx + pandas-ta로 계산합니다.
"""
import logging
from datetime import datetime, timedelta

import pandas as pd
import pandas_ta as ta
from pykrx import stock as krx

logger = logging.getLogger("mcp.tools.technical")

# 보조지표 계산에 필요한 최소 데이터 포인트 (MACD slow=26 + signal=9 + buffer)
_MIN_BARS = 60


async def get_technical_indicators(ticker: str, period: str = "6mo") -> dict:
    """
    RSI, MACD, Bollinger Bands, Volume Ratio를 계산합니다.

    Args:
        ticker: 종목 코드 (예: "005930")
        period: 조회 기간 ("3mo" / "6mo" / "1y")

    Returns:
        dict: 각 지표의 현재값, 신호 해석, 과거 시계열
    """
    period_days = {"3mo": 120, "6mo": 210, "1y": 400}
    # 계산 버퍼(60봉) 포함해 넉넉하게 조회
    days = max(period_days.get(period, 210), _MIN_BARS + 30)
    end   = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    try:
        df = krx.get_market_ohlcv_by_date(start, end, ticker)
        if df.empty or len(df) < _MIN_BARS:
            return {"error": f"데이터 부족: {ticker} ({len(df)}봉)"}

        # 컬럼 영문 변환
        df = df.rename(columns={
            "시가": "open", "고가": "high", "저가": "low",
            "종가": "close", "거래량": "volume",
        })
        close  = df["close"].astype(float)
        high   = df["high"].astype(float)
        low    = df["low"].astype(float)
        volume = df["volume"].astype(float)

        # ── RSI(14) ──────────────────────────────────────────
        rsi_series = ta.rsi(close, length=14)
        rsi_val    = float(rsi_series.iloc[-1])

        # ── MACD(12, 26, 9) ───────────────────────────────────
        macd_df   = ta.macd(close, fast=12, slow=26, signal=9)
        macd_val  = float(macd_df["MACD_12_26_9"].iloc[-1])
        macd_sig  = float(macd_df["MACDs_12_26_9"].iloc[-1])
        macd_hist = float(macd_df["MACDh_12_26_9"].iloc[-1])
        prev_hist = float(macd_df["MACDh_12_26_9"].iloc[-2])

        # ── Bollinger Bands(20, 2σ) ───────────────────────────
        bb_df = ta.bbands(close, length=20, std=2)
        # pandas-ta 버전에 따라 컬럼명이 다를 수 있어 동적으로 탐색
        bb_upper_col = next((c for c in bb_df.columns if c.startswith("BBU")), None)
        bb_mid_col   = next((c for c in bb_df.columns if c.startswith("BBM")), None)
        bb_lower_col = next((c for c in bb_df.columns if c.startswith("BBL")), None)
        if not all([bb_upper_col, bb_mid_col, bb_lower_col]):
            raise ValueError(f"BB 컬럼 탐색 실패: {bb_df.columns.tolist()}")
        bb_upper = float(bb_df[bb_upper_col].iloc[-1])
        bb_mid   = float(bb_df[bb_mid_col].iloc[-1])
        bb_lower = float(bb_df[bb_lower_col].iloc[-1])
        bb_pct   = (close.iloc[-1] - bb_lower) / (bb_upper - bb_lower)  # 0~1

        # ── Volume Ratio (최근 거래량 / 20일 평균) ────────────
        vol_ma20    = volume.rolling(20).mean().iloc[-1]
        vol_ratio   = float(volume.iloc[-1] / vol_ma20) if vol_ma20 > 0 else 1.0

        # ── 신호 해석 ─────────────────────────────────────────
        rsi_signal = _rsi_signal(rsi_val)
        macd_signal = _macd_signal(macd_hist, prev_hist)
        bb_signal  = _bb_signal(bb_pct)

        return {
            "ticker": ticker,
            "rsi": {
                "value":  round(rsi_val, 2),
                "signal": rsi_signal,
            },
            "macd": {
                "macd":      round(macd_val, 2),
                "signal":    round(macd_sig, 2),
                "histogram": round(macd_hist, 2),
                "signal_type": macd_signal,
            },
            "bollinger": {
                "upper":   int(bb_upper),
                "middle":  int(bb_mid),
                "lower":   int(bb_lower),
                "pct_b":   round(float(bb_pct), 3),
                "signal":  bb_signal,
            },
            "volume": {
                "ratio":  round(vol_ratio, 2),
                "signal": "고거래량" if vol_ratio >= 1.5 else "평균",
            },
            # Technical Agent가 참고할 요약 시계열 (최근 20봉)
            "history": {
                "dates":  [d.strftime("%Y-%m-%d") for d in df.index[-20:]],
                "close":  [int(v) for v in close[-20:]],
                "rsi":    [round(float(v), 1) for v in rsi_series[-20:]],
                "macd_hist": [round(float(v), 1)
                              for v in macd_df["MACDh_12_26_9"][-20:]],
            },
        }

    except Exception as e:
        logger.error(f"기술적 지표 계산 실패 [{ticker}]: {e}")
        return {"error": str(e), "ticker": ticker}


# ── 신호 해석 헬퍼 ─────────────────────────────────────────────────

def _rsi_signal(rsi: float) -> str:
    if rsi <= 30:
        return "과매도"
    if rsi >= 70:
        return "과매수"
    if rsi < 45:
        return "약세"
    if rsi > 55:
        return "강세"
    return "중립"


def _macd_signal(hist: float, prev_hist: float) -> str:
    """히스토그램 0선 교차 및 방향으로 신호 판단"""
    if prev_hist < 0 < hist:
        return "골든크로스"
    if prev_hist > 0 > hist:
        return "데드크로스"
    if hist > 0:
        return "상승모멘텀" if hist > prev_hist else "모멘텀약화(강세)"
    return "하락모멘텀" if hist < prev_hist else "모멘텀약화(약세)"


def _bb_signal(pct_b: float) -> str:
    if pct_b <= 0.05:
        return "하단밴드접촉(과매도)"
    if pct_b >= 0.95:
        return "상단밴드접촉(과매수)"
    if pct_b < 0.4:
        return "하단권"
    if pct_b > 0.6:
        return "상단권"
    return "중간권"
