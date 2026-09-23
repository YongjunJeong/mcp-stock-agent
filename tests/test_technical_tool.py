"""기술적 지표 Tool — 신호 해석과 파이프라인 동작."""
import math

import numpy as np
import pandas as pd
import pytest

from mcp_server.tools import technical as t

# ── 신호 해석 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("rsi,expected", [
    (10, "과매도"), (30, "과매도"), (31, "약세"), (44, "약세"),
    (50, "중립"), (56, "강세"), (70, "과매수"), (95, "과매수"),
])
def test_rsi_signal(rsi, expected):
    assert t._rsi_signal(rsi) == expected


def test_macd_signal_crossovers():
    assert t._macd_signal(1.0, -1.0) == "골든크로스"
    assert t._macd_signal(-1.0, 1.0) == "데드크로스"


def test_macd_signal_momentum():
    assert t._macd_signal(2.0, 1.0) == "상승모멘텀"
    assert t._macd_signal(1.0, 2.0) == "모멘텀약화(강세)"
    assert t._macd_signal(-2.0, -1.0) == "하락모멘텀"
    assert t._macd_signal(-1.0, -2.0) == "모멘텀약화(약세)"


@pytest.mark.parametrize("pct,expected", [
    (0.0, "하단밴드접촉(과매도)"), (0.05, "하단밴드접촉(과매도)"),
    (0.2, "하단권"), (0.5, "중간권"), (0.8, "상단권"),
    (0.95, "상단밴드접촉(과매수)"), (1.0, "상단밴드접촉(과매수)"),
])
def test_bb_signal(pct, expected):
    assert t._bb_signal(pct) == expected


# ── 파이프라인 ───────────────────────────────────────────────────────

def _ohlcv(n=200, flat=False, seed=5):
    idx = pd.bdate_range("2025-01-01", periods=n)
    if flat:
        close = np.full(n, 50000.0)
    else:
        close = np.cumsum(np.random.default_rng(seed).normal(0, 700, n)) + 70000
    return pd.DataFrame(
        {"시가": close, "고가": close * 1.01, "저가": close * 0.99,
         "종가": close, "거래량": np.full(n, 1_000_000.0)},
        index=idx,
    )


@pytest.fixture
def fake_krx(monkeypatch):
    def _install(df):
        monkeypatch.setattr(t.krx, "get_market_ohlcv_by_date", lambda s, e, tk: df)
    return _install


async def test_returns_full_indicator_set(fake_krx):
    fake_krx(_ohlcv())
    r = await t.get_technical_indicators("005930", "6mo")
    assert "error" not in r
    assert set(r) == {"ticker", "rsi", "macd", "bollinger", "volume", "history"}
    assert 0 <= r["rsi"]["value"] <= 100
    assert r["bollinger"]["lower"] <= r["bollinger"]["middle"] <= r["bollinger"]["upper"]
    assert len(r["history"]["rsi"]) == 20
    assert len(r["history"]["dates"]) == 20


async def test_rejects_insufficient_data(fake_krx):
    fake_krx(_ohlcv(n=30))
    r = await t.get_technical_indicators("005930")
    assert "데이터 부족" in r["error"]


async def test_rejects_empty_frame(fake_krx):
    fake_krx(pd.DataFrame())
    r = await t.get_technical_indicators("005930")
    assert "error" in r


async def test_flat_series_is_rejected_not_silently_wrong(fake_krx):
    """
    완전 횡보하면 RSI와 %B가 NaN이 된다.
    그대로 신호 해석에 넘기면 모든 비교가 False가 되어
    조용히 엉뚱한 신호가 나오므로 error로 걸러야 한다.
    """
    fake_krx(_ohlcv(flat=True))
    r = await t.get_technical_indicators("005930")
    assert "NaN" in r.get("error", "")


async def test_exception_is_caught_and_reported(fake_krx, monkeypatch):
    def boom(s, e, tk):
        raise ConnectionError("KRX 접속 실패")
    monkeypatch.setattr(t.krx, "get_market_ohlcv_by_date", boom)
    r = await t.get_technical_indicators("005930")
    assert "KRX 접속 실패" in r["error"]


async def test_history_values_are_finite(fake_krx):
    fake_krx(_ohlcv())
    r = await t.get_technical_indicators("005930")
    for key in ("rsi", "macd_hist", "close"):
        assert all(not math.isnan(float(v)) for v in r["history"][key])
