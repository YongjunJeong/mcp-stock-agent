"""PM Agent 종합 로직 — 가중합, Safety Brake, Delta, 예외 격리."""
from datetime import datetime, timedelta, timezone

import pytest

from agents import pm_agent as pm


# ── 테스트용 에이전트 스텁 ───────────────────────────────────────────

def _agent_result(score, raw_data=None):
    return {"score": score, "report": f"리포트({score})", "raw_data": raw_data or {}}


def _macro_raw(safety_brake=False, panic=False):
    return {"usd_krw": {"alerts": {"safety_brake": safety_brake, "panic_zone": panic}}}


@pytest.fixture
def patched(monkeypatch):
    """4개 에이전트 · Gemini · DB를 모두 스텁으로 대체합니다."""
    state = {
        "tech": _agent_result(80),
        "fund": _agent_result(80),
        "macro": _agent_result(80, _macro_raw()),
        "sent": _agent_result(80),
        "prev": [],
        "saved": [],
    }

    async def fake_tech(ticker, period): return state["tech"]
    async def fake_fund(ticker): return state["fund"]
    async def fake_macro(): return state["macro"]
    async def fake_sent(ticker, days=7): return state["sent"]
    async def fake_gemini(system, user, **kw): return "종합 의견\nSCORE: 70"
    async def fake_get_history(ticker, limit=5): return state["prev"]
    async def fake_save(result): state["saved"].append(result)

    monkeypatch.setattr(pm, "run_technical_agent", fake_tech)
    monkeypatch.setattr(pm, "run_fundamental_agent", fake_fund)
    monkeypatch.setattr(pm, "run_macro_agent", fake_macro)
    monkeypatch.setattr(pm, "run_sentiment_agent", fake_sent)
    monkeypatch.setattr(pm, "call_gemini", fake_gemini)
    monkeypatch.setattr("db.database.get_history", fake_get_history)
    monkeypatch.setattr("db.database.save_analysis", fake_save)
    return state


# ── 가중합 ───────────────────────────────────────────────────────────

async def test_weighted_score(patched):
    patched["tech"] = _agent_result(100)
    patched["fund"] = _agent_result(0)
    patched["macro"] = _agent_result(0, _macro_raw())
    patched["sent"] = _agent_result(0)
    r = await pm.run_full_analysis("005930")
    assert r["final_score"] == pytest.approx(30.0)   # 100 * 0.30


async def test_weights_sum_to_one():
    total = pm.WEIGHT_TECH + pm.WEIGHT_FUND + pm.WEIGHT_MACRO + pm.WEIGHT_SENT
    assert total == pytest.approx(1.0)


async def test_buy_signal_above_threshold(patched, monkeypatch):
    monkeypatch.setenv("SIGNAL_THRESHOLD_STRONG", "70")
    r = await pm.run_full_analysis("005930")
    assert r["final_score"] == pytest.approx(80.0)
    assert r["buy_signal"] is True
    assert r["signal_text"] == "★ 매수 신호"


async def test_no_buy_signal_below_threshold(patched, monkeypatch):
    monkeypatch.setenv("SIGNAL_THRESHOLD_STRONG", "70")
    for k in ("tech", "fund", "sent"):
        patched[k] = _agent_result(50)
    patched["macro"] = _agent_result(50, _macro_raw())
    r = await pm.run_full_analysis("005930")
    assert r["buy_signal"] is False
    assert r["signal_text"] == "관망"


# ── Safety Brake ─────────────────────────────────────────────────────

async def test_safety_brake_blocks_buy(patched):
    patched["macro"] = _agent_result(80, _macro_raw(safety_brake=True))
    r = await pm.run_full_analysis("005930")
    assert r["safety_brake"] is True
    assert r["buy_signal"] is False
    assert r["final_score"] <= 35.0


async def test_panic_zone_caps_score(patched):
    patched["macro"] = _agent_result(80, _macro_raw(panic=True))
    r = await pm.run_full_analysis("005930")
    assert r["buy_signal"] is False
    assert r["final_score"] <= 49.0
    assert r["safety_brake"] is False


async def test_macro_failure_blocks_buy_signal(patched):
    """
    회귀 테스트: 매크로 조회가 실패하면 alerts가 없다.
    예전 코드는 .get("alerts", {})가 빈 dict를 돌려주며 브레이크를 풀어,
    환율 안전장치를 확인하지 못한 채 매수 신호를 낼 수 있었다.
    """
    patched["macro"] = _agent_result(80, {})     # raw_data 비어 있음
    r = await pm.run_full_analysis("005930")
    assert r["macro_available"] is False
    assert r["buy_signal"] is False
    assert "매크로" in r["signal_text"]


async def test_macro_available_true_on_normal_path(patched):
    r = await pm.run_full_analysis("005930")
    assert r["macro_available"] is True


# ── 에이전트 예외 격리 ───────────────────────────────────────────────

async def test_one_agent_exception_does_not_kill_analysis(patched, monkeypatch):
    async def boom(ticker, days=7):
        raise RuntimeError("뉴스 API 다운")
    monkeypatch.setattr(pm, "run_sentiment_agent", boom)

    r = await pm.run_full_analysis("005930")
    assert r["scores"]["sent"] == 50          # 중립 처리
    assert r["scores"]["tech"] == 80          # 나머지는 살아있음
    assert "오류" in r["reports"]["sent"]


def test_neutral_on_error_passes_through_normal_result():
    ok = {"score": 77, "report": "정상"}
    assert pm._neutral_on_error(ok, "기술적") is ok


def test_neutral_on_error_converts_exception():
    out = pm._neutral_on_error(ValueError("터짐"), "매크로")
    assert out["score"] == 50
    assert out["raw_data"] == {}


# ── Delta ────────────────────────────────────────────────────────────

def _prev_row(score, signal, hours_ago=3):
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "analyzed_at": ts.isoformat(), "final_score": score, "signal_text": signal,
        "score_tech": 50, "score_fund": 50, "score_macro": 50, "score_sent": 50,
    }


def test_delta_without_previous_record():
    assert pm._compute_delta(70.0, "관망", {}, None) == {"has_prev": False}


def test_delta_computes_change_and_transition():
    scores = {"tech": 60, "fund": 55, "macro": 45, "sent": 70}
    d = pm._compute_delta(72.0, "★ 매수 신호", scores, _prev_row(65.0, "관망"))
    assert d["has_prev"] is True
    assert d["score_change"] == pytest.approx(7.0)
    assert d["signal_changed"] is True
    assert d["score_tech_change"] == 10
    assert d["score_macro_change"] == -5
    assert "시간 전" in d["analyzed_ago"]


def test_delta_no_signal_change():
    d = pm._compute_delta(66.0, "관망", {"tech": 50, "fund": 50, "macro": 50, "sent": 50},
                          _prev_row(65.0, "관망"))
    assert d["signal_changed"] is False


@pytest.mark.parametrize("hours,marker", [(0.5, "분 전"), (5, "시간 전"), (50, "일 전")])
def test_delta_relative_time_wording(hours, marker):
    d = pm._compute_delta(70.0, "관망", {"tech": 50, "fund": 50, "macro": 50, "sent": 50},
                          _prev_row(65.0, "관망", hours_ago=hours))
    assert marker in d["analyzed_ago"]


# ── 결과 구조 ────────────────────────────────────────────────────────

async def test_result_shape_and_persistence(patched):
    r = await pm.run_full_analysis("005930")
    for key in ("ticker", "final_score", "buy_signal", "signal_text",
                "safety_brake", "macro_available", "delta", "scores", "reports", "raw_data"):
        assert key in r
    assert set(r["scores"]) == {"tech", "fund", "macro", "sent"}
    assert set(r["reports"]) == {"tech", "fund", "macro", "sent", "pm"}
    assert len(patched["saved"]) == 1        # DB 저장이 한 번 호출됨


async def test_falls_back_to_rule_based_report_when_llm_empty(patched, monkeypatch):
    async def empty(system, user, **kw): return ""
    monkeypatch.setattr(pm, "call_gemini", empty)
    r = await pm.run_full_analysis("005930")
    assert "LLM 호출 실패" in r["reports"]["pm"]
