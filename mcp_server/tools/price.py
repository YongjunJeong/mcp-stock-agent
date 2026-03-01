"""
Tool 1: get_price_data
한국 주식 OHLCV 데이터를 pykrx로 조회합니다.
"""
import logging
from datetime import datetime, timedelta

import pandas as pd
from pykrx import stock as krx

logger = logging.getLogger("mcp.tools.price")


async def get_price_data(ticker: str, period: str = "6mo") -> dict:
    """
    pykrx로 한국 주식 OHLCV 데이터를 조회합니다.

    Args:
        ticker: 종목 코드 (예: "005930")
        period: 조회 기간 ("1mo" / "3mo" / "6mo" / "1y")

    Returns:
        dict: 회사명, 최신 가격, OHLCV 히스토리
    """
    period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}
    days = period_days.get(period, 180)
    end   = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    try:
        df = krx.get_market_ohlcv_by_date(start, end, ticker)
        if df.empty:
            return {"error": f"데이터 없음: {ticker}"}

        # 종목명 조회
        try:
            name = krx.get_market_ticker_name(ticker)
        except Exception:
            name = ticker

        latest = df.iloc[-1]
        prev   = df.iloc[-2] if len(df) > 1 else latest

        # 전일 대비 등락률 계산
        change_pct = (
            (float(latest["종가"]) - float(prev["종가"])) / float(prev["종가"]) * 100
        )

        return {
            "ticker":       ticker,
            "company_name": name,
            "currency":     "KRW",
            "latest": {
                "date":       df.index[-1].strftime("%Y-%m-%d"),
                "open":       int(latest["시가"]),
                "high":       int(latest["고가"]),
                "low":        int(latest["저가"]),
                "close":      int(latest["종가"]),
                "volume":     int(latest["거래량"]),
                "change_pct": round(change_pct, 2),
            },
            "history": {
                "dates":  [d.strftime("%Y-%m-%d") for d in df.index],
                "open":   [int(v) for v in df["시가"]],
                "high":   [int(v) for v in df["고가"]],
                "low":    [int(v) for v in df["저가"]],
                "close":  [int(v) for v in df["종가"]],
                "volume": [int(v) for v in df["거래량"]],
            },
            "period":      period,
            "data_points": len(df),
        }

    except Exception as e:
        logger.error(f"가격 데이터 조회 실패 [{ticker}]: {e}")
        return {"error": str(e), "ticker": ticker}
