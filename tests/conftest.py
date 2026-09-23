"""pytest 공통 설정 — 리포지토리 루트를 import 경로에 올립니다."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
