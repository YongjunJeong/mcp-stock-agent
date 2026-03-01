# MCP Stock Agent — Multi-Agent AI Stock Analysis System

> **Korean stock market analysis powered by a 5-agent AI pipeline, delivered via Slack.**
> Built as a portfolio project demonstrating multi-agent orchestration, MCP protocol integration, and event-driven automation.

---

## Demo

```
User:  @봇 삼성전자
Bot:   🔍 `005930` 분석 중... (5개 Agent 실행)

       ⚠️ 삼성전자 (005930) 멀티에이전트 분석
       현재가: 74,200 KRW  |  전일 대비: -0.93%
       S&P500: 소폭 하락 (-0.43%)  |  VIX: ✅ 안정 (VIX 19.9)
       ────────────────────────────────────
       📊 Final Score: 46.2/100 — 관망
       ████░░░░░░  46.2점

       📈 기술적(×30%)   📋 펀더멘털(×35%)
       ████████ 75점      ██░░░░░░ 15점

       🌐 매크로(×20%)   📰 감성(×15%)
       ████░░░░ 55점      ████░░░░ 50점
       ────────────────────────────────────
       🏦 PM 종합 의견
       기술적 분석상 박스권 돌파 시도 중이나, 펀더멘털
       고평가 우려와 Stress Zone 환율이 리스크 요인...

       💰 ⏳ 관망 중 — 진입 시나리오
       진입가: 70,000원 이하 조정 시   보유기간: 중기 3~6개월
       1차 목표가: 82,000원 (+17%)    2차 목표가: 92,000원 (+31%)
       🛑 손절기준: 67,000원 (-4%, 120일선 하방 이탈 시)
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Slack Bot                            │
│   (Socket Mode, Event-Driven, Block Kit UI)                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ @mention → trigger analysis
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      PM Agent                               │
│   Final_Score = Tech×0.30 + Fund×0.35 + Macro×0.20         │
│                                      + Sent×0.15            │
│   Safety Brake │ Buy Signal │ Strategy Block                │
└──────┬─────────┬────────────┬───────────────┬──────────────┘
       │         │            │               │
       ▼         ▼            ▼               ▼
  Technical  Fundamental   Macro         Sentiment
  Agent      Agent         Agent         Agent
  (chart +   (PER, EPS,    (FX, VIX,     (news
   pattern)   PBR, BPS)    KOSPI, flow)   sentiment)
       │         │            │               │
       └─────────┴────────────┴───────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   MCP Tool Layer                            │
│  price │ technical │ pattern │ fundamental │ sentiment      │
│                    │ macro                                  │
└───────────────────┬─────────────────────────────────────────┘
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
  Data Sources              AI (Gemini)
  ─────────────             ────────────
  pykrx (KRX OHLCV)        gemini-2.5-flash
  Naver Finance API         thinking_budget=0
  Frankfurter API           temperature=0.3
  yfinance (S&P500/VIX)     1 call per agent


┌─────────────────────────────────────────────────────────────┐
│               APScheduler (Automated Scanning)              │
│   Weekdays 09:00–15:00 KST, every hour                     │
│   Watchlist scan → Buy Signal → Slack notification          │
└─────────────────────────────────────────────────────────────┘
```

---

## Agent Design

### Why 5 Agents?

Each agent has a distinct **information domain** and **analysis persona**. Combining them into a single prompt would cause persona drift and reduce accuracy.

| Agent | Persona | Weight | Data Source |
|-------|---------|--------|-------------|
| Technical | 20-yr chart analyst | ×30% | RSI, MACD, Bollinger Bands, patterns |
| Fundamental | Conservative value investor | ×35% | PER, EPS, PBR, BPS, dividend yield |
| Macro | Global macro strategist | ×20% | USD/KRW, VIX, S&P500, KOSPI, foreign flow |
| Sentiment | Market psychology expert | ×15% | Naver Finance news (company-specific only) |
| **PM** | Hedge fund portfolio manager | synthesizer | All 4 agent reports |

**Weight rationale:**
- Fundamental 35%: Intrinsic value is the foundation of long-term returns
- Technical 30%: Entry timing and short-term momentum
- Macro 20%: USD/KRW and foreign investor flows dominate KOSPI direction
- Sentiment 15%: High noise-to-signal ratio; deliberately underweighted

### Final Score Threshold

```
Final_Score ≥ 70  →  Buy Signal 🚨
Final_Score 55–69 →  Watchlist (close to trigger)
Final_Score < 55  →  Hold / Avoid
```

---

## Key Engineering Decisions

### 1. MCP Protocol as the Tool Layer

Rather than hardcoding data-fetching inside agents, each data domain is exposed as an **MCP tool** with a JSON schema. This decouples:
- **Data fetching logic** (how to get the data) from
- **Analysis logic** (how to interpret it)

Agents call tools directly (no network overhead) since they share the same Python runtime. The MCP server is registered for external client access.

### 2. Exchange Rate Risk Framework (Non-linear)

Simple "above X = bad" rules miss the critical insight: **velocity matters more than level**.

```python
FX_RISK_WEIGHTS = [
    (1450, 5.0, "Panic/MarginCall Zone"),   # ×5 risk multiplier
    (1400, 2.5, "Stress Zone"),             # ×2.5 risk multiplier
    (1380, 1.0, "New Normal Zone"),         # neutral (current normal)
    (1300, 0.8, "Stable Zone"),
]

# Safety Brake: absolute circuit breaker
safety_brake = (usd_krw >= 1450) AND (3-day ROC > 1%)
# → Forces buy_signal=False, caps score at 35
```

**KRW Solo Weakness Detection**: USD/KRW rising + JPY/USD falling simultaneously indicates Korea-specific internal risk (not global dollar strength).

### 3. Separated Macro & Sentiment Domains

A common mistake: mixing macro news (exchange rate, Fed policy) into sentiment analysis. This project explicitly separates them:

- **Sentiment Agent**: Company-specific news ONLY (`system_prompt` blocks macro content)
- **Macro Agent**: Covers FX, VIX, US market, foreign flows, geopolitical context

This prevents double-counting macro signals across agents.

### 4. Structured LLM Output Parsing

PM Agent outputs a machine-parseable `STRATEGY_START...STRATEGY_END` block:

```
STRATEGY_START
진입가: 73,000~75,000원 (분할매수 권장)
목표가1: 85,000원 (+15%)
목표가2: 95,000원 (+27%)
손절기준: 69,000원 (-8%, 60일선 하방 이탈 시)
보유기간: 중기 3~6개월
STRATEGY_END
```

Regex extraction is more robust than JSON for LLM output — models occasionally hallucinate JSON syntax errors under token pressure.

### 5. VIX as a Global Fear Circuit Breaker

```
VIX < 20   → ✅ Stable (risk-on environment)
VIX 20–25  → 🟡 Caution
VIX 25–30  → ⚠️ Elevated volatility
VIX ≥ 30   → 🚨 Fear zone (capital flight from EM)
VIX ≥ 35   → ⛔ Panic (all signals invalidated)
```

VIX ≥ 30 combined with Safety Brake triggers the highest severity composite alert.

### 6. Gemini `thinking_budget=0`

Gemini 2.5 Flash defaults to allocating thinking tokens before output. With a 1024-token output budget, thinking tokens consume the budget before the actual response. Setting `thinking_budget=0` eliminates this and ensures full response generation.

---

## Project Structure

```
mcp-stock-agent/
├── agents/
│   ├── gemini_client.py      # Shared Gemini 2.5 Flash client
│   ├── technical_agent.py    # RSI · MACD · BB · chart patterns
│   ├── fundamental_agent.py  # PER · EPS · PBR · BPS
│   ├── macro_agent.py        # FX · VIX · KOSPI · foreign flow
│   ├── sentiment_agent.py    # News sentiment (company-specific)
│   └── pm_agent.py           # Synthesizer · Safety Brake · Strategy
│
├── mcp_server/
│   ├── server.py             # MCP server (6 tools, stdio transport)
│   └── tools/
│       ├── price.py          # OHLCV via pykrx
│       ├── technical.py      # pandas-ta indicators
│       ├── pattern.py        # Chart pattern detection (numpy)
│       ├── fundamental.py    # Naver Finance scraping (pykrx broken)
│       ├── sentiment.py      # Naver mobile JSON API
│       └── macro.py          # Frankfurter + Naver + yfinance
│
├── slack/
│   └── bot.py                # Socket Mode · Block Kit · Strategy UI
│
├── scheduler/
│   └── cron.py               # APScheduler · watchlist scan
│
├── main.py                   # Entry point (bot + scheduler)
├── requirements.txt
└── .env                      # Secrets (not committed)
```

---

## Tech Stack

| Layer | Technology | Reason |
|-------|-----------|--------|
| AI / LLM | Gemini 2.5 Flash | Free tier, 1M context, fast |
| Agent Protocol | MCP (Anthropic) | Structured tool definitions |
| Slack Integration | slack-bolt (Socket Mode) | No public URL required |
| Scheduling | APScheduler | Async-native, cron syntax |
| FX Data | Frankfurter API | Free, ECB-sourced, no API key |
| US Market | yfinance | S&P500, NASDAQ, VIX (free) |
| KR Market | pykrx + Naver | OHLCV + fundamentals |
| HTTP | aiohttp | Async, all data fetching |
| Indicators | pandas-ta | RSI, MACD, Bollinger Bands |

---

## Setup

### Prerequisites

- Python 3.11+
- Slack App with Bot Token (`xoxb-`) and App Token (`xapp-`)
- Gemini API key (free tier sufficient)

### Installation

```bash
git clone https://github.com/your-id/mcp-stock-agent
cd mcp-stock-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables

```bash
# .env
GEMINI_API_KEY=AIza...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_CHANNEL_ID=C...          # channel for scheduler alerts

# Optional tuning
WATCHLIST_KR=005930,000660,035420
SIGNAL_THRESHOLD_STRONG=70
```

### Run

```bash
python main.py
```

### Slack Commands

```
@봇 삼성전자          # company name
@봇 005930            # ticker code
@봇 하이닉스 분석해줘  # natural language
@봇 도움              # help message
```

---

## Data Sources & Limitations

| Data | Source | Free | Limitation |
|------|--------|------|-----------|
| KR stock OHLCV | pykrx (KRX) | ✅ | T+1 delay |
| KR fundamentals | Naver Finance (scraping) | ✅ | pykrx fundamental API broken |
| News sentiment | Naver mobile API | ✅ | Korean news only |
| USD/KRW, JPY/USD | Frankfurter (ECB) | ✅ | 1-day lag (ECB publish time) |
| S&P500, NASDAQ, VIX | yfinance (Yahoo) | ✅ | Unofficial API, may throttle |
| KOSPI, KOSDAQ | Naver mobile API | ✅ | Real-time (15-min delay) |
| Foreign flow | Naver Finance (scraping) | ✅ | Daily summary only |

---

## Scoring Example

```
삼성전자 (005930) — 2026-03-01

Technical Agent:   75/100  ×0.30 = 22.5
Fundamental Agent: 15/100  ×0.35 =  5.3  ← high PER, low dividend
Macro Agent:       55/100  ×0.20 = 11.0  ← Stress Zone (1,441원)
Sentiment Agent:   50/100  ×0.15 =  7.5
                                  ──────
Final Score:                       46.2  → 관망 (threshold: 70)
```

---

## What I Would Add Next

- **Docker** — single `docker compose up` deployment
- **Oracle Cloud** — 24/7 production hosting
- **Backtesting** — historical signal accuracy validation
- **More tickers** — watchlist via Slack command (`@봇 추가 035420`)
- **Position sizing** — Kelly Criterion or fixed fractional
