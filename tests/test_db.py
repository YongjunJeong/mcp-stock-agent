"""SQLite 레이어 — 워치리스트 CRUD와 분석 히스토리."""
import pytest

from db import database as db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "_db_path", lambda: path)
    monkeypatch.delenv("WATCHLIST_KR", raising=False)
    return path


async def test_init_seeds_from_env(temp_db, monkeypatch):
    monkeypatch.setenv("WATCHLIST_KR", "005930,000660")
    await db.init_db()
    assert await db.get_watchlist() == ["005930", "000660"]


async def test_init_is_idempotent(temp_db, monkeypatch):
    monkeypatch.setenv("WATCHLIST_KR", "005930")
    await db.init_db()
    await db.add_ticker("035420")
    await db.init_db()          # 두 번째 호출이 시드를 다시 밀어넣으면 안 됨
    assert await db.get_watchlist() == ["005930", "035420"]


async def test_add_and_remove_ticker(temp_db):
    await db.init_db()
    assert await db.add_ticker("068270") is True
    assert await db.add_ticker("068270") is False      # 중복
    assert "068270" in await db.get_watchlist()
    assert await db.remove_ticker("068270") is True
    assert await db.remove_ticker("068270") is False   # 이미 없음
    assert "068270" not in await db.get_watchlist()


def _result(ticker="005930", score=72.5, buy=True):
    return {
        "ticker": ticker, "final_score": score, "buy_signal": buy,
        "signal_text": "★ 매수 신호" if buy else "관망",
        "scores": {"tech": 80, "fund": 70, "macro": 60, "sent": 75},
    }


async def test_save_and_read_history(temp_db):
    await db.init_db()
    await db.save_analysis(_result())
    rows = await db.get_history("005930")
    assert len(rows) == 1
    assert rows[0]["final_score"] == pytest.approx(72.5)
    assert rows[0]["score_tech"] == 80
    assert rows[0]["buy_signal"] == 1


async def test_history_is_newest_first_and_limited(temp_db):
    await db.init_db()
    for s in (50.0, 60.0, 70.0):
        await db.save_analysis(_result(score=s))
    rows = await db.get_history("005930", limit=2)
    assert len(rows) == 2
    assert [r["final_score"] for r in rows] == [70.0, 60.0]


async def test_history_is_scoped_per_ticker(temp_db):
    await db.init_db()
    await db.save_analysis(_result(ticker="005930"))
    await db.save_analysis(_result(ticker="000660"))
    assert len(await db.get_history("005930")) == 1
    assert len(await db.get_history("035420")) == 0


async def test_save_analysis_never_raises(temp_db):
    """
    분석 히스토리 저장 실패가 분석 흐름 자체를 막으면 안 된다.
    (필수 키가 빠진 결과를 넣어도 예외가 밖으로 나가지 않아야 함)
    """
    await db.init_db()
    await db.save_analysis({"ticker": "005930"})       # 나머지 키 없음
    assert await db.get_history("005930") == []
