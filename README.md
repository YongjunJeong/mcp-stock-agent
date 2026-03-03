# MCP Stock Agent — 멀티에이전트 AI 주식 분석 시스템

> **5개의 전문가 AI 에이전트가 한국 주식을 분석하고, 매수 신호를 Slack으로 전송하는 자동화 시스템입니다.**
>
> MCP(Model Context Protocol) 기반 Tool 레이어, Gemini 2.5 Flash LLM, Slack Socket Mode,
> SQLite 분석 히스토리 DB, 런타임 워치리스트 관리까지 갖춘 포트폴리오 프로젝트입니다.

---

## 데모

### 종목 분석

```
사용자: @봇 삼성전자

봇:     🔍 `005930` 분석 중... (5개 전문가 Agent 실행)

        ⚠️ 삼성전자 (005930) 멀티에이전트 분석
        ─────────────────────────────────────
        현재가: 74,200 KRW          전일 대비: -0.93%
        S&P500: 소폭 하락 (-0.43%)   VIX: ✅ 안정 (VIX 19.9)
        ─────────────────────────────────────
        📊 Final Score: 58.7/100 — 관망
        `█████░░░░░` 58.7점
        ↑ *전 분석(1일 전) 대비 +12.5점*  `관망 유지`

        📈 기술적 분석  (×30%)    📋 펀더멘털 분석 (×35%)
        `████████ ` 75점           `██░░░░░░` 25점

        🌐 매크로 분석  (×20%)    📰 감성 분석     (×15%)
        `████░░░░` 55점            `████░░░░` 60점
        ─────────────────────────────────────
        🏦 PM 종합 의견
        기술적 분석상 박스권 돌파를 시도하며 MACD 상승 모멘텀이
        긍정적이나, 펀더멘털 고평가(PER 15배 이상)와 Stress Zone
        환율(1,441원)이 외국인 이탈 리스크를 높이고 있습니다.
        전일 대비 기술적 점수가 +18점 상향된 주요 원인은 거래량
        급증과 함께 20일선 상향 돌파가 확인됐기 때문입니다...

        💰 ⏳ 관망 중 — 진입 시나리오
        진입가: 70,000원 이하       보유기간: 중기 3~6개월
        1차 목표가: 82,000원 (+17%)  2차 목표가: 92,000원 (+31%)
        🛑 손절기준: 67,000원 (-4%, 120일선 하방 이탈 시)
```

### 워치리스트 관리

```
사용자: @봇 워치리스트
봇:     📋 워치리스트 (3개)
        • `005930`
        • `000660`
        • `035420`

사용자: @봇 추가 035720
봇:     ✅ `035720` 워치리스트에 추가됐습니다.

사용자: @봇 히스토리 005930
봇:     [ 005930 분석 히스토리 ]
        ─────────────────────────────
        `03-01 21:00`  *58.7점*  관망     Tech:75 Fund:25 Macro:55 Sent:60
        `03-01 10:00`  *46.2점*  관망     Tech:57 Fund:15 Macro:55 Sent:50
        `02-28 15:00`  *71.5점*  ★매수   Tech:75 Fund:70 Macro:65 Sent:74

사용자: @봇 제거 035720
봇:     🗑️ `035720` 워치리스트에서 제거됐습니다.
```

---

## 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────────────┐
│                      Slack Bot (Socket Mode)                          │
│                                                                      │
│  @봇 삼성전자          → 종목 파싱    → 분석 트리거                         │
│  @봇 추가/제거/워치리스트 → 워치리스트  → DB CRUD                           │
│  @봇 히스토리 005930   → 히스토리    → DB 조회 후 포맷                      │
│  결과: Block Kit 카드 (↑↓ Memory 델타 배지 포함)                           │
└────────────────────────┬─────────────────────────────────────────────┘
                         │ 분석 요청
                         ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        PM Agent (종합 판단)                             │
│                                                                      │
│  ① 분석 시작 전  →  이전 기록 조회 (Memory Layer)                          │
│  ② 4개 에이전트 실행 후  →  Delta 계산 (점수 변화량·신호 전환)                 │
│  ③ Gemini 프롬프트에 Delta 컨텍스트 주입                                   │
│  ④ 분석 완료 후  →  결과를 analysis_history에 자동 저장                     │
│                                                                      │
│  Final_Score = Tech×0.30 + Fund×0.35 + Macro×0.20 + Sent×0.15        │
│                                                                      │
│  Safety Brake: USD/KRW ≥ 1,450 AND 3일 ROC > 1%                      │
│  → buy_signal 강제 False, Final Score 상한 35점                         │
└──────┬───────────┬──────────────┬──────────────┬────────────────────┘
       │           │              │              │
       ▼           ▼              ▼              ▼
  Technical    Fundamental      Macro        Sentiment
  Agent        Agent            Agent        Agent
  ───────────  ───────────      ──────────   ──────────
  RSI·MACD     PER·EPS·PBR     USD/KRW      기업 뉴스
  볼린저밴드   BPS·배당         VIX·S&P500   감성 분석
  차트 패턴    Naver스크래핑    외국인수급    (매크로 제외)
       │           │              │              │
       └───────────┴──────────────┴──────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │           MCP Tool 레이어 (6개 도구)            │
        │  price │ technical │ pattern │ fundamental  │
        │  sentiment │ macro                          │
        └──────────────────┬──────────────────────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
       데이터 소스                 Gemini 2.5 Flash
       ──────────────             ──────────────────
       pykrx (KRX OHLCV)         에이전트당 1회 호출
       Naver Finance API         thinking_budget=0
       Frankfurter (환율)         temperature=0.3
       yfinance (미국 시장)        max_output_tokens=1024


┌──────────────────────────────────────────────────────────────────────┐
│                     SQLite DB (aiosqlite)                             │
│                                                                      │
│  watchlist          analysis_history                                 │
│  ───────────────    ────────────────────────────────────             │
│  ticker (PK)        id, ticker, analyzed_at (UTC ISO)                │
│  added_at           final_score, buy_signal, signal_text             │
│                     score_tech/fund/macro/sent                       │
│                                                                      │
│  ← Slack Bot 읽기/쓰기 (워치리스트 CRUD)                                  │
│  ← APScheduler 읽기 (매 스캔마다 최신 목록 조회)                            │
│  ← PM Agent 읽기/쓰기 (Memory Layer + 분석 결과 저장)                     │
│  Docker named volume (stock_agent_data) → 재시작 후에도 보존             │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                  APScheduler (장중 자동 스캔)                            │
│  평일 09:00 ~ 15:00 KST, 매 시간 정각                                    │
│  DB에서 워치리스트 실시간 조회 → 전 종목 분석                                 │
│  Final Score ≥ 70 → Slack 채널 자동 알림 (매수 신호)                       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 에이전트 설계

### 왜 5개 에이전트로 분리했나?

하나의 프롬프트에 모든 분석을 넣으면 **페르소나 충돌**이 발생합니다.
"매수 타이밍을 잡는 차트 분석가"와 "현금흐름 보수주의 가치 투자자"는 같은 종목에 대해 상충된 의견을 가집니다.
에이전트를 분리하면 각자의 영역에서 독립적으로 판단하고, PM Agent가 합의점과 불일치를 명시적으로 종합합니다.

| 에이전트 | 페르소나 | 가중치 | 주요 지표 |
|---------|---------|--------|----------|
| Technical | 20년 경력 차트 분석가 | ×30% | RSI(14), MACD(12/26/9), 볼린저밴드(20,2σ), 거래량비율, 이중바닥·역헤드앤숄더 패턴 |
| Fundamental | 보수적 가치 투자자 | ×35% | PER, EPS, PBR, BPS, 배당수익률 (Naver Finance 스크래핑) |
| Macro | 글로벌 매크로 전략가 | ×20% | USD/KRW 속도, VIX, S&P500, NASDAQ, KOSPI, 외국인 수급 |
| Sentiment | 시장 심리 전문가 | ×15% | 기업 뉴스 감성 (매크로 뉴스 제외, 기업 이슈만 집중) |
| **PM** | 헤지펀드 포트폴리오 매니저 | 종합 | 4개 리포트 종합 → 최종 의견 + 구체적 투자 전략 |

### 가중치 설계 근거

```
Fundamental 35%  — 기업 내재가치가 장기 수익의 핵심
Technical   30%  — 매수 타이밍과 단기 모멘텀
Macro       20%  — 환율·외국인 수급이 한국 증시 방향의 핵심 변수
Sentiment   15%  — 노이즈가 많아 의도적으로 낮은 비중
```

### 매수 신호 임계값

```
Final Score ≥ 70  →  🚨 매수 신호 (Slack 알림 발송)
Final Score 55–69 →  ⚠️ 관망 (진입 조건 시나리오 제공)
Final Score < 55  →  ⚪ 관망/회피
```

---

## Memory Layer — 시계열 분석 추적

매 분석 결과를 SQLite에 저장하고, **다음 분석 시 이전 결과와 비교해 변화 맥락을 AI에 제공**합니다.

### 동작 흐름

```
run_full_analysis("005930") 호출
        │
        ▼
① get_history("005930", limit=1)   ← 분석 시작 전 이전 기록 조회
        │
        ▼
② 4개 서브에이전트 실행 → Final Score 계산
        │
        ▼
③ _compute_delta(current, previous)
   {
     "has_prev": True,
     "prev_score": 46.2,
     "score_change": +12.5,          ← 점수 변화
     "signal_changed": False,         ← 신호 전환 여부
     "score_tech_change": +18,        ← 기술적 점수 변화
     "analyzed_ago": "1일 전",
   }
        │
        ▼
④ Gemini 프롬프트에 Delta 컨텍스트 주입
   [이전 분석 대비 변화] ← 1일 전 (2026-02-28)
   - Final Score: 46.2점 → 58.7점 (+12.5점)
   - 신호 변화: 관망 유지
   - 세부 변화: 기술적 +18점 / 펀더멘털 +10점 / ...
   위 변화를 고려해 점수 상승의 주요 원인을 한 문장으로 언급하세요.
        │
        ▼
⑤ save_analysis(result)             ← 현재 분석 DB 저장
```

### Slack 표시

**첫 분석 (이전 기록 없음)**:
```
📊 Final Score: 46.2/100 — 관망
`████░░░░░░` 46.2점
```

**재분석 (신호 전환)**:
```
📊 Final Score: 72.0/100 — ★ 매수 신호
`███████░░░` 72.0점
↑ *전 분석(1일 전) 대비 +25.8점*  `관망 → ★ 매수 신호`
```

---

## DB 레이어 (SQLite + aiosqlite)

### 스키마

```sql
-- 워치리스트: 런타임에 Slack으로 추가/제거 가능
CREATE TABLE watchlist (
    ticker   TEXT PRIMARY KEY,
    added_at TEXT NOT NULL        -- ISO-8601 UTC
);

-- 모든 분석 결과 히스토리
CREATE TABLE analysis_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,    -- ISO-8601 UTC
    final_score REAL NOT NULL,
    buy_signal  INTEGER NOT NULL, -- 0 / 1
    signal_text TEXT NOT NULL,
    score_tech  INTEGER NOT NULL,
    score_fund  INTEGER NOT NULL,
    score_macro INTEGER NOT NULL,
    score_sent  INTEGER NOT NULL
);

CREATE INDEX idx_history_ticker_time ON analysis_history(ticker, analyzed_at DESC);
```

### DB 경로 자동 판단

```python
def _db_path() -> str:
    if Path("/app/data").exists():      # Docker 환경
        return "/app/data/stock_agent.db"
    Path("./data").mkdir(exist_ok=True) # 로컬 개발
    return "./data/stock_agent.db"
```

### 첫 실행 자동 시드

앱 시작 시 `init_db()` 호출 → `watchlist` 테이블이 비어있으면 `WATCHLIST_KR` 환경변수를 파싱해 자동 삽입합니다. 이후 Slack 명령으로 추가/제거해도 재시작 시 초기화되지 않습니다.

### Docker 데이터 영속성

```yaml
# docker-compose.yml
volumes:
  - stock_agent_data:/app/data   # named volume

volumes:
  stock_agent_data:
    driver: local
```

`docker compose down --volumes` 를 명시적으로 실행하지 않는 한 컨테이너 재시작·재빌드에도 DB 보존됩니다.

---

## Slack 워치리스트 관리

### 명령어 전체 목록

```
@봇 삼성전자               회사명으로 종목 분석
@봇 005930                종목코드로 분석
@봇 하이닉스 분석해줘       자연어 입력 가능
@봇 카카오 사도 돼?         자연어 입력 가능

@봇 워치리스트              현재 워치리스트 목록 조회
@봇 추가 005930            종목 추가
@봇 추가 카카오             회사명으로도 추가 가능
@봇 제거 005930            종목 제거 (삭제도 동의어)
@봇 삭제 035420            동의어 지원
@봇 히스토리 005930        최근 5회 분석 기록 조회

@봇 도움                   전체 사용법 안내
```

### 런타임 반영 방식

APScheduler는 매 스캔 실행 시마다 DB에서 워치리스트를 새로 조회합니다. 따라서 **Slack으로 종목을 추가·제거하면 다음 정각 스캔에 즉시 반영**되며 앱 재시작이 필요 없습니다.

```python
# scheduler/cron.py — 모듈 레벨 상수 대신 매번 DB 조회
async def _run_watchlist_scan() -> None:
    watchlist = await get_watchlist()   # 실시간 반영
    for ticker in watchlist:
        result = await run_full_analysis(ticker)
        ...
```

---

## 핵심 설계 결정

### 1. MCP(Model Context Protocol)를 Tool 레이어로

```
데이터 수집 책임 (MCP Tools)  ≠  분석·판단 책임 (Agents)
```

에이전트 내부에 데이터 수집 코드를 넣는 대신 모든 데이터 도메인을 MCP Tool로 분리했습니다.
데이터 소스 교체(예: pykrx → 다른 API)가 에이전트 코드를 건드리지 않고 가능합니다.
같은 Python 런타임을 공유하므로 네트워크 오버헤드 없이 직접 호출합니다.

### 2. 환율 속도(Velocity) 우선 분석

단순히 "1,400원 이상 = 위험"이 아닌, **속도와 레벨을 결합한 비선형 리스크 모델**을 적용했습니다.

```
[환율 위험 구간]
1,380 ~ 1,399원  →  New Normal Zone  (위험 가중치 ×1.0)
1,400 ~ 1,449원  →  Stress Zone      (위험 가중치 ×2.5)
1,450원 이상     →  Panic Zone       (위험 가중치 ×5.0)

[속도 경보 — Velocity Alert]
3일 ROC > 1%                 →  패닉 셀링 전조 경보
5일 MA 대비 3% 이상 이격     →  단기 급등 경보

[Safety Brake — 매수 강제 차단]
USD/KRW ≥ 1,450 AND 3일 ROC > 1%
→ buy_signal = False 강제
→ Final Score 상한 35점
```

**원화 단독 약세 판별**: USD/KRW 상승 + JPY/USD 하락(엔화 강세)이 동시 발생하면
글로벌 달러 강세가 아닌 **한국 고유 내부 리스크**로 판단합니다.

### 3. 매크로 vs 감성 도메인 분리

흔한 실수: 뉴스 감성 분석에 환율·연준 뉴스를 포함하면 매크로 신호가 이중으로 집계됩니다.

```python
# Sentiment Agent 시스템 프롬프트
"환율, 금리, 글로벌 증시, 지정학적 리스크 등 매크로 이슈는
 분석하지 마세요. 기업 고유의 사건·제품·실적에만 집중하세요."
```

### 4. 구조화된 LLM 출력 파싱

PM Agent는 자유형식 리포트 끝에 **파싱 가능한 전략 블록**을 출력합니다.

```
STRATEGY_START
진입가: 73,000~75,000원 (분할매수 권장)
목표가1: 85,000원 (+15%)
목표가2: 95,000원 (+27%)
손절기준: 69,000원 (-8%, 60일선 하방 이탈 시)
보유기간: 중기 3~6개월
STRATEGY_END
```

JSON보다 Regex 파싱을 선택한 이유: LLM이 토큰 압박 상황에서 JSON 문법 오류를 만드는 경우가 잦기 때문입니다.

### 5. VIX 공포 지수 연동

```
VIX < 20   →  ✅ 안정 (위험선호 정상, 신흥국 자금 유입 우호)
VIX 20–25  →  🟡 경계 (변동성 확대 초기)
VIX 25–30  →  ⚠️ 주의 (기관 헤지 증가)
VIX ≥ 30   →  🚨 공포 (글로벌 리스크오프)
VIX ≥ 35   →  ⛔ 극도 공포 (Safety Brake 복합 → 최고경보)
```

### 6. Gemini `thinking_budget=0` 설정

Gemini 2.5 Flash는 기본적으로 출력 전 "thinking 토큰"을 소비합니다.
`max_output_tokens=1024` 제한 하에서 thinking 토큰이 실제 분석 리포트를 잘리게 합니다.

```python
response = client.models.generate_content(
    model="gemini-2.5-flash",
    config=GenerateContentConfig(
        thinking_config=ThinkingConfig(thinking_budget=0),  # 핵심
        temperature=0.3,
        max_output_tokens=1024,
    ),
)
```

### 7. save_analysis의 절대 예외 방지

```python
async def save_analysis(result: dict) -> None:
    try:
        ...  # DB 저장
    except Exception as e:
        logger.warning(f"히스토리 저장 실패 (무시됨): {e}")
        # 절대 예외 전파 안 함 — DB 오류가 분석 응답을 막아선 안 됨
```

DB 레이어 장애가 메인 분석 파이프라인에 영향을 주지 않도록 격리합니다.

---

## 프로젝트 구조

```
mcp-stock-agent/
│
├── agents/                         # AI 에이전트 레이어
│   ├── gemini_client.py            # Gemini 2.5 Flash 공유 클라이언트
│   ├── technical_agent.py          # RSI · MACD · BB · 차트 패턴 분석
│   ├── fundamental_agent.py        # PER · EPS · PBR · BPS 가치 분석
│   ├── macro_agent.py              # 환율 · VIX · KOSPI · 외국인 수급 분석
│   ├── sentiment_agent.py          # 기업 뉴스 감성 분석 (매크로 제외)
│   └── pm_agent.py                 # 종합 판단 · Safety Brake · Memory Layer · 투자 전략
│
├── db/                             # DB 레이어 (SQLite + aiosqlite)
│   ├── __init__.py
│   └── database.py                 # init_db · watchlist CRUD · 분석 히스토리 저장/조회
│
├── mcp_server/                     # MCP Tool 레이어
│   ├── server.py                   # MCP 서버 (6개 도구, stdio transport)
│   └── tools/
│       ├── price.py                # OHLCV 데이터 (pykrx)
│       ├── technical.py            # 기술적 지표 (pandas-ta)
│       ├── pattern.py              # 차트 패턴 감지 (numpy 선형회귀)
│       ├── fundamental.py          # 재무 지표 (Naver Finance 스크래핑)
│       ├── sentiment.py            # 뉴스 감성 (Naver 모바일 JSON API)
│       └── macro.py                # 매크로 지표 (Frankfurter · Naver · yfinance)
│
├── slack/
│   └── bot.py                      # Socket Mode 봇 · Block Kit UI · 워치리스트 명령 · Memory 델타 표시
│
├── scheduler/
│   └── cron.py                     # APScheduler · 워치리스트 DB 조회 · 매수 신호 알림
│
├── data/                           # 런타임 DB (gitignore, Docker named volume 사용)
│   └── stock_agent.db              # 자동 생성 — 커밋하지 않음
│
├── main.py                         # 진입점 (init_db → 스케줄러 → Slack Bot)
├── requirements.txt
├── Dockerfile                      # 멀티스테이지 빌드 (builder + runtime)
├── docker-compose.yml              # named volume · 환경변수 주입 · 로그 순환
├── .env.example                    # 환경변수 템플릿
└── .gitignore
```

---

## 기술 스택

| 영역 | 기술 | 선택 이유 |
|------|-----|----------|
| AI / LLM | Gemini 2.5 Flash | 무료 티어, 100만 토큰 컨텍스트, 빠른 속도 |
| 에이전트 프로토콜 | MCP (Anthropic) | Tool 스키마 표준화, 에이전트-도구 분리 |
| Slack 연동 | slack-bolt (Socket Mode) | 공개 URL 불필요, WebSocket 기반 |
| 스케줄러 | APScheduler | asyncio 네이티브, cron 문법 지원 |
| DB | SQLite + aiosqlite | 서버리스, asyncio 비블로킹 I/O, 외부 의존성 없음 |
| 환율 데이터 | Frankfurter API | 무료, ECB 기준, API 키 불필요 |
| 미국 시장 | yfinance | S&P500·NASDAQ·VIX 무료 수집 |
| 한국 시장 | pykrx + Naver Finance | OHLCV + 재무지표 (pykrx 재무 API 불안정 → Naver 스크래핑으로 대체) |
| 비동기 HTTP | aiohttp | asyncio.gather로 병렬 데이터 수집 |
| 기술적 지표 | pandas-ta | RSI, MACD, 볼린저밴드 |
| 패턴 감지 | numpy | 이중바닥, 역헤드앤숄더, 삼각수렴 (선형회귀 기반) |
| 컨테이너 | Docker + docker-compose | ARM/AMD64 멀티스테이지 빌드 |

---

## 데이터 소스 및 한계

| 데이터 | 소스 | 무료 | 한계 |
|-------|------|------|------|
| 한국 주식 OHLCV | pykrx (KRX) | ✅ | T+1 딜레이 |
| 한국 재무 지표 | Naver Finance (스크래핑) | ✅ | pykrx 재무 API 서버 장애로 대체 |
| 뉴스 감성 | Naver 모바일 JSON API | ✅ | 한국어 뉴스만 |
| USD/KRW, JPY/USD | Frankfurter (ECB) | ✅ | ECB 공시 기준, 하루 딜레이 |
| S&P500, NASDAQ, VIX | yfinance (Yahoo Finance) | ✅ | 비공식 API, 간헐적 제한 가능 |
| KOSPI, KOSDAQ | Naver 모바일 API | ✅ | 실시간 (15분 지연) |
| 외국인 수급 | Naver Finance (스크래핑) | ✅ | 일별 집계만 제공 |

---

## 설치 및 실행

### 환경변수 설정 (공통)

```bash
cp .env.example .env
# .env 파일을 열어 실제 키 입력
```

```env
GEMINI_API_KEY=AIza...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_CHANNEL_ID=C...
WATCHLIST_KR=005930,000660,035420   # 첫 실행 시 DB 시드로 사용
SIGNAL_THRESHOLD_STRONG=70
```

### 방법 1 — Docker (권장)

```bash
git clone https://github.com/YongjunJeong/mcp-stock-agent.git
cd mcp-stock-agent
cp .env.example .env   # 실제 키 입력

docker compose up -d           # 백그라운드 실행
docker compose logs -f         # 실시간 로그
docker compose down            # 종료 (DB 데이터 보존)
docker compose down --volumes  # 종료 + DB 완전 삭제
```

### 방법 2 — Python 직접 실행 (로컬 개발용)

```bash
git clone https://github.com/YongjunJeong/mcp-stock-agent.git
cd mcp-stock-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 실제 키 입력

python main.py
# → data/stock_agent.db 자동 생성
# → Slack Bot (Socket Mode) + APScheduler 동시 시작
```

---

## 점수 계산 예시

```
삼성전자 (005930) — 2026-03-01 기준

기술적 분석:    75/100 × 0.30 = 22.5점   (MACD 상승, 박스권 돌파 시도)
펀더멘털:       15/100 × 0.35 =  5.3점   (PER 15배↑, 배당수익률 낮음)
매크로:         55/100 × 0.20 = 11.0점   (Stress Zone 환율 1,441원, VIX 안정)
감성:           50/100 × 0.15 =  7.5점   (중립적 뉴스 흐름)
                                ──────
Final Score:                    46.2점  →  관망 (임계값: 70점)
```

