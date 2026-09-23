"""MCP 서버: tool 등록과 stdio 프로토콜 채널 무결성."""
import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_TOOLS = {
    "get_price_data", "get_technical_indicators", "analyze_chart_pattern",
    "get_financial_statements", "get_news_sentiment", "get_macro_indicators",
}


def _schema_enum(prop: dict) -> list:
    return prop.get("enum") or [x["const"] for x in prop.get("anyOf", []) if "const" in x]


def test_all_tools_registered_with_schemas():
    from mcp_server.server import mcp

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert set(tools) == EXPECTED_TOOLS

    price = tools["get_price_data"].input_schema
    assert price["required"] == ["ticker"]
    assert _schema_enum(price["properties"]["period"]) == ["1mo", "3mo", "6mo", "1y"]

    tech = tools["get_technical_indicators"].input_schema
    assert _schema_enum(tech["properties"]["period"]) == ["3mo", "6mo", "1y"]

    assert tools["get_macro_indicators"].input_schema.get("required", []) == []


def test_stdio_channel_carries_only_json_rpc():
    """
    회귀 테스트: pykrx는 import 시점에 KRX 로그인 결과를 print로 stdout에 찍는다.
    stdio 모드에서 stdout은 JSON-RPC 채널이라, 이 한 줄이 섞이면 클라이언트가
    첫 메시지부터 파싱에 실패한다.
    """
    # 자격 증명이 없어야 pykrx가 "로그인 실패"를 출력하는 경로를 탄다.
    env = {k: v for k, v in os.environ.items() if k not in ("KRX_ID", "KRX_PW")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_server.server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=ROOT, env=env,
    )
    watchdog = threading.Timer(60, proc.kill)   # 서버가 멈추면 readline이 영원히 막힘
    watchdog.start()

    def send(msg):
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def read_response(msg_id):
        # 실제 클라이언트처럼 응답을 받을 때까지 연결을 유지한다.
        # (요청 직후 stdin을 닫으면 서버가 답하기 전에 EOF로 종료될 수 있다)
        while True:
            line = proc.stdout.readline()
            if not line:
                pytest.fail(f"응답 {msg_id} 전에 stdout이 닫혔습니다. stderr:\n{proc.stderr.read()}")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                pytest.fail(f"stdout에 JSON이 아닌 줄이 섞였습니다: {line!r}")
            if msg.get("id") == msg_id:
                return msg

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"}}})
        init = read_response(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = read_response(2)
    finally:
        # stdin은 communicate()가 닫습니다. 직접 닫으면 3.11에서는
        # communicate()가 닫힌 파일을 flush하려다 ValueError가 납니다.
        _, stderr = proc.communicate(timeout=30)
        watchdog.cancel()

    assert init["result"]["serverInfo"]["name"] == "stock-multi-agent"
    assert {t["name"] for t in listed["result"]["tools"]} == EXPECTED_TOOLS

    # pykrx 출력이 사라진 게 아니라 stderr로 옮겨졌는지도 확인
    assert "KRX" in stderr
