"""
SQLite DB 레이어 (aiosqlite)

책임:
  - DB 초기화 + 스키마 생성 (init_db)
  - 첫 실행 시 WATCHLIST_KR 환경변수로 시드
  - 워치리스트 CRUD: get_watchlist / add_ticker / remove_ticker
  - 분석 히스토리: save_analysis / get_history
"""
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger("db")


def _db_path() -> str:
    """Docker(/app/data) 또는 로컬(./data) 경로를 자동 판단."""
    docker_dir = Path("/app/data")
    if docker_dir.exists():
        return str(docker_dir / "stock_agent.db")
    local_dir = Path("./data")
    local_dir.mkdir(parents=True, exist_ok=True)
    return str(local_dir / "stock_agent.db")


async def init_db() -> None:
    """DB 초기화 및 스키마 생성. 첫 실행 시 환경변수로 워치리스트 시드."""
    db_path = _db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker   TEXT PRIMARY KEY,
                added_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS analysis_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                final_score REAL NOT NULL,
                buy_signal  INTEGER NOT NULL,
                signal_text TEXT NOT NULL,
                score_tech  INTEGER NOT NULL,
                score_fund  INTEGER NOT NULL,
                score_macro INTEGER NOT NULL,
                score_sent  INTEGER NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_ticker_time
                ON analysis_history(ticker, analyzed_at DESC)
        """)
        await db.commit()

        # 첫 실행 시만 환경변수로 시드
        cursor = await db.execute("SELECT COUNT(*) FROM watchlist")
        (count,) = await cursor.fetchone()
        if count == 0:
            env_val = os.getenv("WATCHLIST_KR", "005930,000660,035420")
            now_utc = datetime.now(timezone.utc).isoformat()
            tickers = [t.strip() for t in env_val.split(",") if t.strip()]
            await db.executemany(
                "INSERT OR IGNORE INTO watchlist (ticker, added_at) VALUES (?, ?)",
                [(t, now_utc) for t in tickers],
            )
            await db.commit()
            logger.info(f"워치리스트 시드 완료: {tickers}")

    logger.info(f"DB 초기화 완료: {db_path}")


async def get_watchlist() -> list[str]:
    """워치리스트 종목 코드 목록을 추가 순으로 반환."""
    async with aiosqlite.connect(_db_path()) as db:
        cursor = await db.execute(
            "SELECT ticker FROM watchlist ORDER BY added_at"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def add_ticker(ticker: str) -> bool:
    """종목 추가. 이미 있으면 False 반환."""
    async with aiosqlite.connect(_db_path()) as db:
        cursor = await db.execute(
            "SELECT ticker FROM watchlist WHERE ticker = ?", (ticker,)
        )
        if await cursor.fetchone():
            return False
        now_utc = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO watchlist (ticker, added_at) VALUES (?, ?)",
            (ticker, now_utc),
        )
        await db.commit()
        return True


async def remove_ticker(ticker: str) -> bool:
    """종목 제거. 없으면 False 반환."""
    async with aiosqlite.connect(_db_path()) as db:
        cursor = await db.execute(
            "DELETE FROM watchlist WHERE ticker = ?", (ticker,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def save_analysis(result: dict) -> None:
    """분석 결과 저장. 예외는 절대 전파하지 않음 — 분석 흐름을 방해해선 안 됨."""
    try:
        scores = result.get("scores", {})
        now_utc = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                """
                INSERT INTO analysis_history
                    (ticker, analyzed_at, final_score, buy_signal, signal_text,
                     score_tech, score_fund, score_macro, score_sent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["ticker"],
                    now_utc,
                    result["final_score"],
                    int(result["buy_signal"]),
                    result["signal_text"],
                    scores.get("tech", 0),
                    scores.get("fund", 0),
                    scores.get("macro", 0),
                    scores.get("sent", 0),
                ),
            )
            await db.commit()
    except Exception as e:
        logger.warning(f"분석 히스토리 저장 실패 (무시됨): {e}")


async def get_history(ticker: str, limit: int = 5) -> list[dict]:
    """종목 분석 히스토리를 최신순으로 반환."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT analyzed_at, final_score, buy_signal, signal_text,
                   score_tech, score_fund, score_macro, score_sent
            FROM analysis_history
            WHERE ticker = ?
            ORDER BY analyzed_at DESC
            LIMIT ?
            """,
            (ticker, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
