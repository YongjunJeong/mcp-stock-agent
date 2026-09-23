"""
MCP Server — 6개 Tool을 MCP 프로토콜로 노출합니다.

입력 스키마는 각 Tool 함수의 타입 힌트에서 자동 생성됩니다.
(mcp 1.x의 `@server.list_tools()` / `@server.call_tool()` 데코레이터와
수기 JSON 스키마는 mcp 2.x에서 제거되어 MCPServer로 옮겼습니다.)

실행:
  python -m mcp_server.server
"""
import contextlib
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

# pykrx(>=1.2.5)는 import 시점에 KRX_ID/KRX_PW로 KRX에 로그인합니다.
# 그래서 .env는 도구 모듈보다 먼저 읽어야 합니다.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 로그인 결과를 print로 stdout에 찍는데, stdio 모드에서 stdout은 JSON-RPC
# 채널이라 이 한 줄 때문에 클라이언트가 첫 메시지부터 파싱에 실패합니다.
# import 동안만 stderr로 돌립니다. (서빙 중의 출력은 mcp가 stderr로 보냅니다.)
with contextlib.redirect_stdout(sys.stderr):
    from mcp_server.tools.fundamental import get_financial_statements
    from mcp_server.tools.macro import get_macro_indicators
    from mcp_server.tools.pattern import analyze_chart_pattern
    from mcp_server.tools.price import get_price_data
    from mcp_server.tools.sentiment import get_news_sentiment
    from mcp_server.tools.technical import get_technical_indicators

logger = logging.getLogger("mcp.server")

mcp = MCPServer(name="stock-multi-agent")

# ── Tool 등록 ─────────────────────────────────────────────────────────
# (함수, 설명) — 파라미터 스키마는 함수 시그니처에서 자동 추출됩니다.
_TOOLS = [
    (
        get_price_data,
        "한국 주식 OHLCV 데이터를 pykrx로 조회합니다. "
        "종목 코드와 기간을 입력하면 최신 가격, 등락률, 거래량 히스토리를 반환합니다.",
    ),
    (
        get_technical_indicators,
        "RSI, MACD, 볼린저밴드, 거래량 비율을 계산합니다. "
        "각 지표에 대한 신호 해석(과매도/골든크로스 등)을 포함합니다.",
    ),
    (
        analyze_chart_pattern,
        "주요 차트 패턴(Double Bottom, 역 헤드앤숄더, 박스권 돌파, 삼각수렴)을 탐지합니다. "
        "패턴 신뢰도와 함께 최근 60봉 OHLCV 데이터를 반환하며, 신뢰도 높은 순으로 정렬됩니다.",
    ),
    (
        get_financial_statements,
        "Naver Finance에서 PER, PBR, EPS, BPS, 배당수익률을 조회하고 "
        "pykrx 시가총액을 함께 반환합니다. 현재 시점 스냅샷이며 분기 시계열은 제공하지 않습니다.",
    ),
    (
        get_news_sentiment,
        "Naver Finance에서 최근 종목 뉴스를 스크래핑하고 사전 기반 감성 점수를 계산합니다. "
        "긍정/부정 기사 수, 주요 헤드라인, 전체 기사 목록을 반환합니다. "
        "매크로(환율/금리/글로벌 증시) 내용은 get_macro_indicators를 사용하세요.",
    ),
    (
        get_macro_indicators,
        "글로벌 매크로 지표를 수집합니다: USD/KRW 환율 추세와 속도, KOSPI/KOSDAQ 지수, "
        "외국인 수급, S&P500/NASDAQ/VIX. 지정학적 리스크와 글로벌 증시 흐름이 "
        "한국 주식에 미치는 영향 분석에 사용합니다.",
    ),
]

for _fn, _description in _TOOLS:
    mcp.add_tool(_fn, description=_description)


# ── 진입점 ────────────────────────────────────────────────────────────

def main() -> None:
    from logging_config import setup_logging

    setup_logging()
    logger.info("MCP Stock Multi-Agent Server 시작 (stdio)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
