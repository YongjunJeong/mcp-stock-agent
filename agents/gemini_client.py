"""
Gemini API 공통 클라이언트.
모든 Agent가 이 모듈을 통해 Gemini를 호출합니다.
- thinking_budget=0 (thinking 토큰이 output 예산을 잠식하는 문제 방지)
- temperature=0.3 (일관된 분석 결과)
- 자동 재시도 1회
"""
import logging
import os
import re

from dotenv import load_dotenv
from google import genai
from google.genai import types as gtypes

load_dotenv()

logger = logging.getLogger("agents.gemini")

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


async def call_gemini(system_prompt: str, user_prompt: str) -> str:
    """
    Gemini에 system + user 프롬프트를 전달하고 텍스트 응답을 반환합니다.

    Args:
        system_prompt: Agent 페르소나 및 출력 형식 지시
        user_prompt:   분석할 데이터 및 질문

    Returns:
        str: Gemini 응답 텍스트 (빈 문자열이면 오류)
    """
    client = _get_client()
    model  = get_model()

    config = gtypes.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.3,
        max_output_tokens=1024,
        thinking_config=gtypes.ThinkingConfig(thinking_budget=0),
    )

    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=config,
            )
            text = response.text or ""
            if not text:
                logger.warning(f"Gemini 빈 응답 (attempt {attempt+1})")
                continue
            return text.strip()
        except Exception as e:
            logger.error(f"Gemini 호출 실패 (attempt {attempt+1}): {e}")
            if attempt == 1:
                return ""

    return ""


def extract_score(text: str) -> int:
    """
    응답 텍스트에서 'SCORE: 숫자' 형식의 점수를 추출합니다.
    0~100 범위를 벗어나면 클램핑합니다.
    """
    m = re.search(r"SCORE\s*[:：]\s*(\d+)", text, re.IGNORECASE)
    if m:
        return max(0, min(100, int(m.group(1))))
    # 대안: 마지막으로 나오는 두 자리 숫자
    nums = re.findall(r"\b(\d{1,3})\b", text)
    if nums:
        candidate = int(nums[-1])
        if 0 <= candidate <= 100:
            return candidate
    return 50  # 파싱 실패 시 중립값
