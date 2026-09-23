"""매크로 에이전트 결과 캐시."""
import asyncio

import pytest

from agents import macro_agent as ma


@pytest.fixture
def stub(monkeypatch):
    """지표 수집과 Gemini 호출을 스텁으로 바꾸고 호출 횟수를 셉니다."""
    ma.clear_cache()
    state = {"fetches": 0, "fail": False, "clock": 1000.0}

    async def fake_indicators(days=30):
        state["fetches"] += 1
        await asyncio.sleep(0.01)           # 동시 호출이 겹치도록 약간 대기
        if state["fail"]:
            return {"error": "네트워크 오류"}
        return {"usd_krw": {"current": 1390.0, "alerts": {}}, "signals": {}}

    async def fake_gemini(system, user, **kw):
        return "매크로 요약\nSCORE: 61"

    monkeypatch.setattr(ma, "get_macro_indicators", fake_indicators)
    monkeypatch.setattr(ma, "call_gemini", fake_gemini)
    monkeypatch.setattr(ma, "_now", lambda: state["clock"])
    monkeypatch.setenv("MACRO_CACHE_TTL_SECONDS", "600")
    yield state
    ma.clear_cache()


async def test_sequential_calls_share_one_fetch(stub):
    first = await ma.run_macro_agent()
    second = await ma.run_macro_agent()
    assert stub["fetches"] == 1
    assert first is second
    assert first["score"] == 61


async def test_concurrent_calls_share_one_fetch(stub):
    """Slack 요청과 스케줄러 스캔이 동시에 들어와도 수집은 한 번이어야 한다."""
    results = await asyncio.gather(*(ma.run_macro_agent() for _ in range(5)))
    assert stub["fetches"] == 1
    assert all(r is results[0] for r in results)


async def test_cache_expires_after_ttl(stub):
    await ma.run_macro_agent()
    stub["clock"] += 599
    await ma.run_macro_agent()
    assert stub["fetches"] == 1
    stub["clock"] += 2                       # 601초 경과
    await ma.run_macro_agent()
    assert stub["fetches"] == 2


async def test_failed_fetch_is_not_cached(stub):
    """조회 실패를 캐시하면 TTL 동안 매수 신호가 계속 보류된다."""
    stub["fail"] = True
    failed = await ma.run_macro_agent()
    assert failed["raw_data"] == {}
    stub["fail"] = False
    ok = await ma.run_macro_agent()
    assert stub["fetches"] == 2
    assert ok["raw_data"]


async def test_ttl_zero_disables_cache(stub, monkeypatch):
    monkeypatch.setenv("MACRO_CACHE_TTL_SECONDS", "0")
    await ma.run_macro_agent()
    await ma.run_macro_agent()
    assert stub["fetches"] == 2
