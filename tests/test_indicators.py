"""
보조지표 검증.

pandas의 ewm/rolling에 기대지 않고, 테스트 안에서 순수 파이썬 루프로
같은 정의를 독립 구현해 비교합니다. 구현을 그대로 베껴 쓰면
"자기 자신과 같다"는 무의미한 테스트가 되기 때문입니다.

참조 정의 (pandas-ta 0.4.71b0과 동일하게 맞춘 규약):
  - RMA  : alpha = 1/length, 첫 값에서 시작하는 재귀 평균
  - EMA  : span 기반 alpha = 2/(length+1), 앞 length개의 SMA를 시드로 사용
  - BB   : SMA(length) ± std * 표본표준편차(ddof=1)
"""
import math
import statistics

import pandas as pd
import pytest

from mcp_server import indicators as ind


# ── 독립 참조 구현 ───────────────────────────────────────────────────

def ref_rma(values, length):
    alpha = 1.0 / length
    out, prev = [], None
    for v in values:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out.append(float("nan"))
            continue
        prev = v if prev is None else alpha * v + (1 - alpha) * prev
        out.append(prev)
    return out


def ref_rsi(closes, length=14):
    gains = [float("nan")] + [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [float("nan")] + [min(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    ag, al = ref_rma(gains, length), ref_rma(losses, length)
    return [
        float("nan") if math.isnan(g) else min(100.0, max(0.0, 100 * g / (g + abs(l))))
        for g, l in zip(ag, al)
    ]


def ref_ema_presma(values, length):
    """앞 length개의 SMA를 시드로 쓰는 EMA (TA-Lib 관행)."""
    alpha = 2.0 / (length + 1)
    out = [float("nan")] * len(values)
    if len(values) < length:
        return out
    prev = sum(values[:length]) / length
    out[length - 1] = prev
    for i in range(length, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


# ── 픽스처 ───────────────────────────────────────────────────────────

@pytest.fixture
def closes():
    """결정적인 합성 종가 시계열 (난수 시드 고정 없이 재현 가능)."""
    vals, x = [], 70000.0
    for i in range(160):
        x += 900 * math.sin(i / 7.0) + 300 * math.cos(i / 3.0) - 12
        vals.append(round(x, 2))
    return vals


# ── RSI ──────────────────────────────────────────────────────────────

def test_rsi_matches_independent_reference(closes):
    got = ind.rsi(pd.Series(closes), 14).tolist()
    exp = ref_rsi(closes, 14)
    for i, (g, e) in enumerate(zip(got, exp)):
        if math.isnan(e):
            assert math.isnan(g), f"index {i}: NaN이어야 함"
        else:
            assert g == pytest.approx(e, abs=1e-9), f"index {i}"


def test_rsi_stays_in_range(closes):
    vals = ind.rsi(pd.Series(closes), 14).dropna()
    assert not vals.empty
    assert vals.between(0, 100).all()


def test_rsi_flat_series_is_nan():
    """가격이 전혀 안 움직이면 분모가 0이라 RSI는 정의되지 않습니다."""
    flat = pd.Series([50000.0] * 60)
    assert ind.rsi(flat, 14).iloc[-1] != ind.rsi(flat, 14).iloc[-1]  # NaN


def test_rsi_monotonic_rise_saturates_high():
    rising = pd.Series([1000.0 + i * 10 for i in range(60)])
    assert ind.rsi(rising, 14).iloc[-1] == pytest.approx(100.0)


# ── MACD ─────────────────────────────────────────────────────────────

def test_macd_matches_independent_reference(closes):
    df = ind.macd(pd.Series(closes), 12, 26, 9)

    fast = ref_ema_presma(closes, 12)
    slow = ref_ema_presma(closes, 26)
    macd_line = [
        float("nan") if (math.isnan(f) or math.isnan(s)) else f - s
        for f, s in zip(fast, slow)
    ]
    first_valid = next(i for i, v in enumerate(macd_line) if not math.isnan(v))
    sig_tail = ref_ema_presma(macd_line[first_valid:], 9)
    signal = [float("nan")] * first_valid + sig_tail

    for i in range(len(closes)):
        for col, exp in (("macd", macd_line[i]), ("signal", signal[i])):
            g = df[col].iloc[i]
            if math.isnan(exp):
                assert math.isnan(g), f"{col} index {i}: NaN이어야 함"
            else:
                assert g == pytest.approx(exp, abs=1e-9), f"{col} index {i}"


def test_macd_histogram_is_macd_minus_signal(closes):
    df = ind.macd(pd.Series(closes))
    diff = (df["macd"] - df["signal"] - df["histogram"]).abs().max()
    assert diff == pytest.approx(0.0, abs=1e-12)


def test_macd_leading_values_are_nan(closes):
    """slow=26 이전 구간은 값이 없어야 합니다(0으로 채우면 신호가 왜곡됨)."""
    df = ind.macd(pd.Series(closes), 12, 26, 9)
    assert df["macd"].iloc[:25].isna().all()
    assert not math.isnan(df["macd"].iloc[25])


# ── 볼린저밴드 ───────────────────────────────────────────────────────

def test_bbands_matches_independent_reference(closes):
    df = ind.bbands(pd.Series(closes), 20, 2.0)
    for i in range(19, len(closes)):
        window = closes[i - 19: i + 1]
        mid = statistics.fmean(window)
        dev = statistics.stdev(window)          # 표본표준편차 = ddof 1
        assert df["mid"].iloc[i] == pytest.approx(mid, rel=1e-12)
        assert df["upper"].iloc[i] == pytest.approx(mid + 2 * dev, rel=1e-12)
        assert df["lower"].iloc[i] == pytest.approx(mid - 2 * dev, rel=1e-12)


def test_bbands_pct_b_positions(closes):
    df = ind.bbands(pd.Series(closes), 20, 2.0)
    s = pd.Series(closes)
    # 종가가 상단이면 1, 하단이면 0
    i = 100
    upper, lower = df["upper"].iloc[i], df["lower"].iloc[i]
    got = (s.iloc[i] - lower) / (upper - lower)
    assert df["pct_b"].iloc[i] == pytest.approx(got, rel=1e-12)


def test_bbands_flat_series_pct_b_is_nan():
    """밴드 폭이 0이면 %B는 0으로 나누기 → NaN이어야 하고 예외는 안 납니다."""
    flat = pd.Series([50000.0] * 40)
    out = ind.bbands(flat, 20, 2.0)
    assert out["upper"].iloc[-1] == pytest.approx(out["lower"].iloc[-1])
    assert math.isnan(out["pct_b"].iloc[-1])


def test_bbands_int_series_does_not_raise():
    """정수 dtype 입력도 처리돼야 합니다(pykrx 종가가 정수로 올 수 있음)."""
    out = ind.bbands(pd.Series(range(50000, 50050)), 20, 2.0)
    assert not math.isnan(out["mid"].iloc[-1])
