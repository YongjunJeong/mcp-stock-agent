# ── 빌드 스테이지: 의존성 설치 ──────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

# 모든 의존성이 x86_64·aarch64용 바이너리 휠을 제공하므로 컴파일러가 필요 없습니다.
# --prefer-binary: 최신 버전이 소스 배포판만 있으면 휠이 있는 직전 버전을 고릅니다.
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary --prefix=/install -r requirements.txt


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
