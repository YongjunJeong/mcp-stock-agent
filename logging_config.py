"""
로깅 설정 (엔트리포인트 공용).

main.py와 mcp_server/server.py 두 실행 경로가 같은 포맷을 쓰도록 한곳에 모읍니다.
모듈 import 시점이 아니라 엔트리포인트에서만 호출합니다.
"""
import logging

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT)
