"""
Gemini API 공통 클라이언트.
모든 Agent가 이 모듈을 통해 Gemini를 호출합니다.
- client.aio 사용 (동기 호출은 이벤트 루프를 막아 Slack 소켓까지 멈춤)
- thinking_budget=0 (thinking 토큰이 output 예산을 잠식하는 문제 방지)
- temperature=0.3 (일관된 분석 결과)
- 자동 재시도 1회 (지수 백오프)
"""
import asyncio
import logging
import os
import re

from google import genai
from google.genai import types as gtypes

logger = logging.getLogger("agents.gemini")

# 점수만 내는 전문가 에이전트의 기본 출력 예산.
# PM 에이전트는 종합의견 + 근거 + 리스크 + STRATEGY 블록까지 써야 해서
# 같은 예산을 쓰면 STRATEGY_END가 잘려 전략 섹션이 통째로 사라집니다.
DEFAULT_MAX_OUTPUT_TOKENS = 1024
PM_MAX_OUTPUT_TOKENS = 2048

_MAX_ATTEMPTS = 2
_RETRY_BASE_DELAY = 1.0

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY 환경변수가 없습니다.")
        _client = genai.Client(api_key=api_key)
    return _client


def get_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


async def call_gemini(
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> str:
    """
    Gemini에 system + user 프롬프트를 전달하고 텍스트 응답을 반환합니다.

    Args:
        system_prompt:     Agent 페르소나 및 출력 형식 지시
        user_prompt:       분석할 데이터 및 질문
        max_output_tokens: 출력 토큰 상한

    Returns:
        str: Gemini 응답 텍스트 (빈 문자열이면 오류)
    """
    client = _get_client()
    model = get_model()

    config = gtypes.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.3,
        max_output_tokens=max_output_tokens,
        thinking_config=gtypes.ThinkingConfig(thinking_budget=0),
    )

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=user_prompt,
                config=config,
            )
            text = (response.text or "").strip()
            if text:
                return text
            logger.warning(f"Gemini 빈 응답 (attempt {attempt}/{_MAX_ATTEMPTS})")
        except Exception as e:
            logger.error(f"Gemini 호출 실패 (attempt {attempt}/{_MAX_ATTEMPTS}): {e}")

        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(_RETRY_BASE_DELAY * attempt)

    return ""


_SCORE_RE = re.compile(r"SCORE\s*[:：]\s*(\d{1,3})", re.IGNORECASE)

NEUTRAL_SCORE = 50


def extract_score(text: str) -> int:
    """
    응답 텍스트에서 'SCORE: 숫자' 형식의 점수를 추출합니다.
    0~100 범위를 벗어나면 클램핑합니다.

    마커를 못 찾으면 중립값(50)을 돌려줍니다.
    예전에는 '본문의 마지막 세 자리 이하 숫자'를 점수로 썼는데,
    리포트 끝의 목표가나 등락률(-9% 등)을 점수로 오인하는 문제가 있었습니다.
    """
    matches = _SCORE_RE.findall(text or "")
    if not matches:
        return NEUTRAL_SCORE
    # 여러 번 등장하면 마지막 것이 최종 점수입니다.
    return max(0, min(100, int(matches[-1])))
