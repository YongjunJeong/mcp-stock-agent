"""
로깅 설정 (엔트리포인트 공용).

main.py와 mcp_server/server.py 두 실행 경로가 같은 포맷을 쓰도록 한곳에 모읍니다.
모듈 import 시점이 아니라 엔트리포인트에서만 호출합니다.
"""
import logging

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    # force=True: 라이브러리가 먼저 basicConfig를 호출해도 엔트리포인트 설정이 이깁니다.
    # (mcp의 MCPServer는 생성자에서 format="%(message)s"로 설정해버립니다.)
    # 출력은 기본값인 stderr로 갑니다. MCP stdio 모드에서 stdout은 프로토콜 채널입니다.
    logging.basicConfig(level=level, format=LOG_FORMAT, force=True)
