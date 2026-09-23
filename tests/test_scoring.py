"""점수 추출과 규칙 기반 폴백 점수."""
import pytest

from agents import fundamental_agent as fa
from agents import sentiment_agent as sa
from agents import technical_agent as ta
from agents.gemini_client import NEUTRAL_SCORE, extract_score
from mcp_server.tools.fundamental import _valuation_signal

# ── SCORE 추출 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("분석 내용\nSCORE: 73", 73),
    ("SCORE:8", 8),
    ("SCORE：65", 65),            # 전각 콜론
    ("score: 42", 42),            # 대소문자 무시
    ("SCORE: 250", 100),          # 상한 클램프
    ("SCORE: 40\n재평가\nSCORE: 55", 55),   # 마지막 값 채택
])
def test_extract_score(text, expected):
    assert extract_score(text) == expected


@pytest.mark.parametrize("text", [
    "",
    "점수를 못 냈습니다.",
    "손절기준 67,000원 (-9%), 목표가 82,000원",   # 숫자는 많지만 SCORE 없음
])
def test_extract_score_falls_back_to_neutral(text):
    """
    회귀 테스트: 예전에는 '본문의 마지막 세 자리 이하 숫자'를 점수로 썼다.
    목표가나 등락률을 점수로 오인하는 문제가 있었다.
    """
    assert extract_score(text) == NEUTRAL_SCORE


# ── 펀더멘털 폴백 ────────────────────────────────────────────────────

def test_valuation_delta_covers_every_signal():
    """_valuation_signal이 낼 수 있는 값은 모두 델타 표에 있어야 한다."""
    produced = {
        _valuation_signal(per, pbr)
        for per in (None, -1, 0, 5, 12, 20, 30, 50, 100)
        for pbr in (None, 0.5, 1.0, 1.2, 2.0, 5.0)
    }
    assert produced <= set(fa._VALUATION_DELTA), produced - set(fa._VALUATION_DELTA)


def _fund(signal, div=None):
    return {"signals": {"valuation": signal}, "valuation": {"div_yield": div}}


def test_severe_overvaluation_scores_below_plain_overvaluation():
    """
    회귀 테스트: '고평가' in '심한고평가' 라서 예전에는 심한고평가가
    -25가 아니라 -15 분기에 먼저 걸렸다.
    """
    plain = fa._fallback_score(_fund("고평가"))
    severe = fa._fallback_score(_fund("심한고평가"))
    assert severe < plain
    assert severe == 25 and plain == 35


def test_severe_undervaluation_scores_above_plain():
    assert fa._fallback_score(_fund("심한저평가")) > fa._fallback_score(_fund("저평가"))


def test_dividend_bonus():
    assert fa._fallback_score(_fund("적정가치", div=3.5)) == 60
    assert fa._fallback_score(_fund("적정가치", div=2.0)) == 55
    assert fa._fallback_score(_fund("적정가치", div=0.5)) == 50


def test_fundamental_fallback_is_clamped():
    assert 0 <= fa._fallback_score(_fund("심한저평가", div=9.0)) <= 100
    assert 0 <= fa._fallback_score(_fund("심한고평가")) <= 100


def test_unknown_signal_is_neutral():
    assert fa._fallback_score(_fund("처음 보는 신호")) == 50


# ── 기술적 폴백 ──────────────────────────────────────────────────────

def _tech(rsi=50, macd="", bb=0.5, vol=1.0):
    return {
        "rsi": {"value": rsi},
        "macd": {"signal_type": macd},
        "bollinger": {"pct_b": bb},
        "volume": {"ratio": vol},
    }


def test_technical_fallback_direction():
    assert ta._fallback_score(_tech(rsi=25)) > 50        # 과매도 가점
    assert ta._fallback_score(_tech(rsi=80)) < 50        # 과매수 감점
    assert ta._fallback_score(_tech(macd="골든크로스")) > 50
    assert ta._fallback_score(_tech(macd="데드크로스")) < 50


def test_technical_fallback_is_clamped():
    best = _tech(rsi=10, macd="골든크로스", bb=0.02, vol=3.0)
    worst = _tech(rsi=95, macd="데드크로스", bb=0.99, vol=0.1)
    assert 0 <= ta._fallback_score(best) <= 100
    assert 0 <= ta._fallback_score(worst) <= 100


# ── 감성 폴백 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [(-1.0, 0), (0.0, 50), (1.0, 100)])
def test_sentiment_fallback_maps_to_0_100(raw, expected):
    assert sa._fallback_score({"sentiment_score": raw}) == expected


def test_sentiment_fallback_handles_missing_key():
    assert sa._fallback_score({}) == 50
