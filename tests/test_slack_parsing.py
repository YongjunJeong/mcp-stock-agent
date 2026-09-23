"""Slack 멘션 파싱 및 포맷 로직."""
import pytest

from slack_bot import bot


# ── 명령 라우팅 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["도움", "도움말", "help", "사용법"])
def test_help_commands(text):
    assert bot._parse_command(text) == ("help", None)


@pytest.mark.parametrize("text", [
    "카카오 사도 돼?",
    "005930 어때?",
    "삼성전자 지금 사도 될까?",
    "하이닉스 분석해줘",
])
def test_question_mark_does_not_hijack_analysis(text):
    """
    회귀 테스트: 예전에는 "?" 부분일치로 도움말 분기를 탔다.
    도움말에서 안내하던 `@봇 카카오 사도 돼?` 조차 동작하지 않았다.
    """
    assert bot._parse_command(text) is None


def test_watchlist_commands():
    assert bot._parse_command("워치리스트") == ("list", None)
    assert bot._parse_command("추가 005930") == ("add", "005930")
    assert bot._parse_command("제거 005930") == ("remove", "005930")
    assert bot._parse_command("삭제 카카오") == ("remove", "카카오")
    assert bot._parse_command("히스토리 005930") == ("history", "005930")


def test_unknown_command_returns_none():
    assert bot._parse_command("오늘 날씨 알려줘") is None


# ── 종목 파싱 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("<@U123> 삼성전자", "005930"),
    ("<@U123> 005930", "005930"),
    ("<@U123> 하이닉스 분석해줘", "000660"),
    ("<@U123> 카카오 사도 돼?", "035720"),
    ("<@U123> NAVER", "035420"),
])
def test_parse_ticker(text, expected):
    assert bot._parse_ticker(text) == expected


def test_parse_ticker_prefers_longest_company_name():
    """'삼성'과 '삼성전자'가 모두 등록돼 있으면 더 긴 쪽이 이겨야 한다."""
    assert bot._parse_ticker("삼성전자") == "005930"
    assert bot._parse_ticker("삼성바이오로직스") == "207940"


def test_parse_ticker_returns_none_when_no_match():
    assert bot._parse_ticker("<@U123> 안녕") is None


def test_resolve_ticker_from_arg():
    assert bot._resolve_ticker_from_arg("005930") == "005930"
    assert bot._resolve_ticker_from_arg("카카오") == "035720"
    assert bot._resolve_ticker_from_arg("없는회사") is None


# ── 전략 블록 파싱 ───────────────────────────────────────────────────

def test_parse_strategy_extracts_fields():
    report = """종합 의견입니다.
STRATEGY_START
진입가: 73,000~75,000원 (분할매수)
목표가1: 82,000원 (+11%)
목표가2: 92,000원 (+24%)
손절기준: 67,000원 (-9%)
보유기간: 중기(3~6개월)
STRATEGY_END"""
    s = bot._parse_strategy(report)
    assert s["진입가"] == "73,000~75,000원 (분할매수)"
    assert s["목표가1"] == "82,000원 (+11%)"
    assert s["손절기준"] == "67,000원 (-9%)"


def test_parse_strategy_returns_none_when_block_truncated():
    """출력 토큰이 모자라 STRATEGY_END가 잘리면 None이어야 한다."""
    assert bot._parse_strategy("의견\nSTRATEGY_START\n진입가: 70,000원") is None


def test_parse_strategy_returns_none_without_block():
    assert bot._parse_strategy("전략 블록이 없는 리포트") is None


# ── 마크다운 변환 ────────────────────────────────────────────────────

def test_to_slack_md_strips_strategy_block():
    text = "앞부분\nSTRATEGY_START\n진입가: 1원\nSTRATEGY_END\n뒷부분"
    out = bot._to_slack_md(text)
    assert "STRATEGY_START" not in out
    assert "진입가" not in out
    assert "앞부분" in out and "뒷부분" in out


def test_to_slack_md_converts_bold_and_headings():
    assert bot._to_slack_md("**강조**") == "*강조*"
    assert bot._to_slack_md("## 제목") == "*제목*"
    assert bot._to_slack_md("- 항목") == "• 항목"


# ── 점수 막대 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("score,filled", [(0, 0), (50, 5), (100, 10)])
def test_score_bar_length(score, filled):
    bar = bot._score_bar(score)
    assert len(bar) == 10
    assert bar.count("█") == filled


def test_score_emoji_thresholds():
    assert bot._score_emoji(75) == "🚨"
    assert bot._score_emoji(60) == "⚠️"
    assert bot._score_emoji(45) == "🟡"
    assert bot._score_emoji(20) == "⚪"


# ── 히스토리 포맷 ────────────────────────────────────────────────────

def test_build_history_block_renders_kst():
    rows = [{
        "analyzed_at": "2026-03-01T00:30:00+00:00",   # UTC
        "final_score": 72.5, "buy_signal": 1, "signal_text": "★ 매수 신호",
        "score_tech": 80, "score_fund": 70, "score_macro": 60, "score_sent": 75,
    }]
    out = bot._build_history_block("005930", rows)
    assert "005930" in out
    assert "72.5" in out
    # UTC 00:30 -> KST 09:30
    assert "03-01 09:30" in out
