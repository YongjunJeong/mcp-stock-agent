# ── 빌드 스테이지: 의존성 설치 ──────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

# C 확장 빌드에 필요한 시스템 패키지 (aiohttp, numpy 등)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# pandas-ta는 pandas 버전을 과도하게 제한하므로 --no-deps로 별도 설치
# (pandas-ta 자체 코드만 필요, numba 등 선택적 의존성 불필요)
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt && \
    pip install --no-cache-dir --prefix=/install --no-deps pandas-ta


# ── 런타임 스테이지: 최소 이미지 ──────────────────────────────────────
FROM python:3.13-slim

WORKDIR /app

# 빌드 스테이지에서 설치된 패키지만 복사 (gcc 등 빌드 도구 제외)
COPY --from=builder /install /usr/local

# 소스 코드 복사 (.dockerignore로 .env, .venv 등 제외됨)
COPY . .

# 보안: root가 아닌 전용 유저로 실행
RUN useradd -m -u 1001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

# 로그를 stdout으로 출력 (Docker 로그 드라이버가 수집)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["python", "main.py"]
