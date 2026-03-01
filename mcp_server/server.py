"""
MCP Server — 6개 Tool 스키마 등록 및 라우팅
"""
import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from mcp_server.tools.price import get_price_data
from mcp_server.tools.technical import get_technical_indicators
from mcp_server.tools.pattern import analyze_chart_pattern
from mcp_server.tools.fundamental import get_financial_statements
from mcp_server.tools.sentiment import get_news_sentiment
from mcp_server.tools.macro import get_macro_indicators

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp.server")

server = Server("stock-multi-agent")

# ── Tool 스키마 정의 ──────────────────────────────────────────────────

TOOLS: list[Tool] = [
    Tool(
        name="get_price_data",
        description=(
            "한국 주식 OHLCV 데이터를 pykrx로 조회합니다. "
            "종목 코드와 기간을 입력하면 최신 가격, 등락률, 거래량 히스토리를 반환합니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "KRX 종목 코드 (예: '005930' = 삼성전자)",
                },
                "period": {
                    "type": "string",
                    "enum": ["1mo", "3mo", "6mo", "1y"],
                    "description": "조회 기간. 기본값: '6mo'",
                },
            },
            "required": ["ticker"],
        },
    ),
    Tool(
        name="get_technical_indicators",
        description=(
            "RSI, MACD, 볼린저밴드, 거래량 비율을 계산합니다. "
            "pandas-ta를 사용하며 각 지표에 대한 신호 해석(과매도/골든크로스 등)을 포함합니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "KRX 종목 코드",
                },
                "period": {
                    "type": "string",
                    "enum": ["3mo", "6mo", "1y"],
                    "description": "조회 기간. 기본값: '6mo'",
                },
            },
            "required": ["ticker"],
        },
    ),
    Tool(
        name="analyze_chart_pattern",
        description=(
            "주요 차트 패턴(Double Bottom, 역 헤드앤숄더, 박스권 돌파, 삼각수렴)을 탐지합니다. "
            "패턴 신뢰도와 함께 최근 60봉 OHLCV 데이터를 반환합니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "KRX 종목 코드",
                },
                "period": {
                    "type": "string",
                    "enum": ["3mo", "6mo", "1y"],
                    "description": "조회 기간. 기본값: '6mo'",
                },
            },
            "required": ["ticker"],
        },
    ),
    Tool(
        name="get_financial_statements",
        description=(
            "pykrx로 PER, PBR, EPS, 배당수익률 등 Fundamental 지표를 조회합니다. "
            "EPS 추세 분석으로 실적 모멘텀을 평가합니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "KRX 종목 코드",
                },
            },
            "required": ["ticker"],
        },
    ),
    Tool(
        name="get_news_sentiment",
        description=(
            "Naver Finance에서 최근 종목 뉴스를 스크래핑하고 감성 점수를 계산합니다. "
            "긍정/부정 기사 수, 주요 헤드라인, 전체 기사 목록을 반환합니다. "
            "매크로(환율/금리/글로벌 증시) 내용은 get_macro_indicators를 사용하세요."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "KRX 종목 코드",
                },
                "days": {
                    "type": "integer",
                    "description": "조회할 과거 일수 (기본값: 7)",
                    "minimum": 1,
                    "maximum": 30,
                },
            },
            "required": ["ticker"],
        },
    ),
    Tool(
        name="get_macro_indicators",
        description=(
            "글로벌 매크로 지표를 수집합니다: USD/KRW 환율 추세, "
            "KOSPI/KOSDAQ 지수 현황, 외국인 수급 동향. "
            "지정학적 리스크와 글로벌 증시 흐름이 한국 주식에 미치는 영향 분석에 사용합니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "환율 조회 기간 일수 (기본값: 30)",
                    "minimum": 7,
                    "maximum": 90,
                },
            },
            "required": [],
        },
    ),
]


# ── 핸들러 ────────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    import json

    logger.info(f"Tool 호출: {name}({arguments})")

    try:
        if name == "get_price_data":
            result = await get_price_data(**arguments)
        elif name == "get_technical_indicators":
            result = await get_technical_indicators(**arguments)
        elif name == "analyze_chart_pattern":
            result = await analyze_chart_pattern(**arguments)
        elif name == "get_financial_statements":
            result = await get_financial_statements(**arguments)
        elif name == "get_news_sentiment":
            result = await get_news_sentiment(**arguments)
        elif name == "get_macro_indicators":
            result = await get_macro_indicators(**arguments)
        else:
            result = {"error": f"알 수 없는 툴: {name}"}
    except Exception as e:
        logger.error(f"Tool 실행 오류 [{name}]: {e}")
        result = {"error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


# ── 진입점 ────────────────────────────────────────────────────────────

async def main():
    logger.info("MCP Stock Multi-Agent Server 시작")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
