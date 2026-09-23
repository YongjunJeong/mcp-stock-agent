"""
보조지표 계산 (RSI / MACD / 볼린저밴드)

pandas-ta 의존성을 제거하고 pandas만으로 계산합니다.
pandas-ta는 0.4 계열부터 import 시점에 numba를 요구해서
`--no-deps` 설치와 맞지 않고, ARM 휠 문제도 반복적으로 발생했습니다.
여기서 쓰는 지표는 3개뿐이라 직접 계산하는 편이 의존성·재현성 면에서 낫습니다.

계산 규약은 pandas-ta(0.4.71b0)와 동일하게 맞췄습니다:
  - RSI    : Wilder RMA (alpha = 1/length, adjust=False)
  - MACD   : EMA(span=length, adjust=False)의 차이, signal은 MACD선의 EMA
  - BBands : SMA(length) ± std × 표본표준편차(ddof=1)

pandas-ta와의 수치 일치는 무작위 시계열로 비교해 확인했습니다.
tests/test_indicators.py는 순수 파이썬으로 쓴 독립 참조 구현과 대조합니다.
"""
import pandas as pd

__all__ = ["ema", "rma", "rsi", "macd", "bbands"]


def ema(series: pd.Series, length: int, presma: bool = True) -> pd.Series:
    """
    지수이동평균.

    presma=True면 TA-Lib 방식으로 앞 length개의 SMA를 시드로 쓰고
    그 앞 구간은 NaN으로 둡니다. pandas-ta의 기본 동작과 같습니다.
    """
    series = series.astype(float)
    if presma:
        series = series.copy()
        seed = series.iloc[:length].mean()
        series.iloc[: length - 1] = float("nan")
        series.iloc[length - 1] = seed
    return series.ewm(span=length, adjust=False).mean()


def rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder 평활이동평균. alpha = 1/length인 EMA와 동일합니다."""
    return series.ewm(alpha=1.0 / length, adjust=False).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """
    RSI(Relative Strength Index).

    상승분/하락분을 각각 Wilder 평활한 뒤 비율로 환산합니다.
    가격이 완전히 횡보해 분모가 0이면 NaN이 나옵니다(pandas-ta와 동일).

    계산 결과는 [0, 100]으로 클램프합니다. 하락분이 0에 수렴하는 구간에서
    나눗셈 반올림으로 100.00000000000001 같은 값이 나올 수 있는데,
    RSI의 정의역을 벗어난 값이 밖으로 새면 경계 비교에서 사고가 납니다.
    (편차는 1e-14 수준이라 신호 해석에는 영향이 없습니다.)
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = delta.clip(upper=0)

    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)

    return (100 * avg_gain / (avg_gain + avg_loss.abs())).clip(0, 100)


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """
    MACD.

    Returns:
        DataFrame[macd, signal, histogram]
    """
    macd_line = ema(close, fast) - ema(close, slow)
    # signal은 MACD선의 유효값이 시작되는 지점부터 계산합니다(선행 NaN 제외).
    macd_valid = macd_line.loc[macd_line.first_valid_index():]
    signal_line = ema(macd_valid, signal)

    return pd.DataFrame(
        {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": macd_line - signal_line,
        }
    )


def bbands(
    close: pd.Series,
    length: int = 20,
    std: float = 2.0,
) -> pd.DataFrame:
    """
    볼린저밴드.

    Returns:
        DataFrame[lower, mid, upper, pct_b]

    pct_b는 밴드 내 상대 위치(0=하단, 1=상단)입니다.
    밴드 폭이 0이면(가격 완전 횡보) NaN이 나옵니다.
    """
    mid = close.rolling(length).mean()
    dev = close.rolling(length).std(ddof=1)

    upper = mid + std * dev
    lower = mid - std * dev
    width = upper - lower

    return pd.DataFrame(
        {
            "lower": lower,
            "mid": mid,
            "upper": upper,
            "pct_b": (close - lower) / width.where(width != 0),
        }
    )
