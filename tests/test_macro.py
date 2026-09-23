"""매크로 지표 해석 로직 (환율 구간, 속도 경보, 종합 신호)."""
import pytest

from mcp_server.tools import macro as m


# ── 일별 변동폭 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [0, 1, 2, 5, 6, 10, 30])
def test_daily_max_vol_never_raises(n):
    """
    회귀 테스트: 예전 구현은 values가 정확히 5개일 때 values[-6]에 접근해
    IndexError를 냈다.
    """
    values = [1000.0 + i * 3 for i in range(n)]
    assert m._daily_max_vol(values) >= 0.0


def test_daily_max_vol_picks_largest_move():
    assert m._daily_max_vol([1000, 1002, 1020, 1021, 1022, 1023]) == pytest.approx(18)


def test_daily_max_vol_only_looks_at_recent_window():
    """창 밖의 큰 변동은 무시돼야 한다."""
    values = [1000.0, 9999.0, 1000.0, 1001.0, 1002.0, 1003.0, 1004.0, 1005.0]
    assert m._daily_max_vol(values) == pytest.approx(1.0)


def test_daily_max_vol_empty_is_zero():
    assert m._daily_max_vol([]) == 0.0


# ── 환율 위험 구간 ───────────────────────────────────────────────────

@pytest.mark.parametrize("rate,zone", [
    (1500, "Panic/MarginCall Zone"),
    (1450, "Panic/MarginCall Zone"),
    (1449, "Stress Zone"),
    (1400, "Stress Zone"),
    (1390, "New Normal Zone"),
    (1350, "Stable Zone"),
    (1250, "Strong KRW Zone"),
])
def test_risk_zone_boundaries(rate, zone):
    assert m._get_risk_weight(rate)[1] == zone


def test_risk_weight_is_monotonic_in_rate():
    rates = [1200, 1350, 1390, 1420, 1500]
    weights = [m._get_risk_weight(r)[0] for r in rates]
    assert weights == sorted(weights), weights


# ── 환율 신호 ────────────────────────────────────────────────────────

def test_safety_brake_signal_wins_over_panic():
    sig = m._usd_krw_signal(1460, 1.5, "Panic/MarginCall Zone", True, True)
    assert "Safety Brake" in sig


def test_panic_zone_without_velocity():
    sig = m._usd_krw_signal(1460, 0.2, "Panic/MarginCall Zone", False, True)
    assert "Panic Zone" in sig and "Safety Brake" not in sig


def test_new_normal_is_neutral():
    assert "중립" in m._usd_krw_signal(1390, 0.1, "New Normal Zone", False, False)


# ── 원화 단독 약세 ───────────────────────────────────────────────────

def test_krw_solo_weakness_detected():
    out = m._check_krw_solo_weakness({"roc_3d_pct": 1.2}, {"roc_7d_pct": -0.8})
    assert out["detected"] is True
    assert "단독" in out["interpretation"]


def test_krw_weak_together_with_yen_is_global_dollar_strength():
    out = m._check_krw_solo_weakness({"roc_3d_pct": 1.2}, {"roc_7d_pct": 1.5})
    assert out["detected"] is False
    assert "글로벌" in out["interpretation"]


# ── 종합 신호 ────────────────────────────────────────────────────────

def _usd(safety_brake=False, panic=False, velocity=False, zone="New Normal Zone"):
    return {
        "risk_zone": zone,
        "signal": "테스트",
        "alerts": {
            "safety_brake": safety_brake, "panic_zone": panic, "velocity": velocity,
        },
    }


def _us(vix):
    return {"vix": {"current": vix, "signal": f"VIX {vix}"},
            "sp500": {"signal": "보합"}, "nasdaq": {"signal": "보합"}}


def test_overall_escalates_with_safety_brake_and_fear():
    s = m._build_signals(_usd(safety_brake=True), {"signal": ""}, {}, _us(35))
    assert "최고경보" in s["overall"] and "글로벌 공포" in s["overall"]


def test_overall_safety_brake_alone():
    s = m._build_signals(_usd(safety_brake=True), {"signal": ""}, {}, _us(15))
    assert "최고경보" in s["overall"]


def test_overall_high_vix_alone_is_risk_off():
    s = m._build_signals(_usd(), {"signal": ""}, {}, _us(32))
    assert "리스크오프" in s["overall"]


def test_overall_favourable_when_stable_and_foreign_buying():
    s = m._build_signals(_usd(zone="Stable Zone"), {"signal": "외국인순매수"}, {}, _us(14))
    assert "우호적" in s["overall"]


def test_safety_brake_flag_is_propagated():
    s = m._build_signals(_usd(safety_brake=True), {"signal": ""}, {}, _us(14))
    assert s["safety_brake"] is True


def test_build_signals_tolerates_missing_us_markets():
    s = m._build_signals(_usd(), {"signal": ""}, {}, {})
    assert s["vix_signal"] == "N/A"
    assert s["overall"]


# ── 숫자 파싱 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("1,234.56", 1234.56), ("2500", 2500.0), ("", 0.0), (None, 0.0), ("N/A", 0.0),
])
def test_to_float(raw, expected):
    assert m._to_float(raw) == expected


# ── VIX 신호 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("vix,marker", [
    (40, "극도 공포"), (32, "공포 구간"), (27, "변동성 상승"), (22, "경계"), (14, "안정"),
])
def test_vix_signal_bands(vix, marker):
    assert marker in m._us_index_signal("vix", vix, 0.0)
