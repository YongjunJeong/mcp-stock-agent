# Implementation and operations guide

[Overview](../README.md) · [Korean reference](../README.ko.md)

This guide preserves the implementation and operational detail from the original
README. Model personas and numerical thresholds describe application policy,
not validated financial expertise or predictive performance.

## Data tools and analysis flow

| Tool | Implementation | Inputs and purpose |
|---|---|---|
| `get_price_data` | `mcp_server/tools/price.py` | Korean stock OHLCV from pykrx; ticker and period |
| `get_technical_indicators` | `tools/technical.py`, `indicators.py` | RSI, MACD, Bollinger bands and volume signals |
| `analyze_chart_pattern` | `tools/pattern.py` | Rule-based patterns over OHLCV; reported confidence is heuristic |
| `get_financial_statements` | `tools/fundamental.py` | Naver financial snapshot and pykrx market capitalization |
| `get_news_sentiment` | `tools/sentiment.py` | Naver headlines and dictionary sentiment features |
| `get_macro_indicators` | `tools/macro.py` | FX, Korean/US indices, VIX and foreign flows |

The specialist functions call these Python tools directly. External MCP clients
can use their typed schemas through the separate stdio server. Gemini receives a
text summary of the tool results; it does not select or execute arbitrary tools.

`run_full_analysis()` reads the latest history record **before** the current
analysis, runs four specialists, normalizes exceptions, calculates the weighted
score, applies macro rules, computes the delta, asks Gemini for synthesis and
attempts history storage. The weights are technical 0.30, fundamental 0.35,
macro 0.20 and sentiment 0.15. The buy threshold defaults to 70.

Missing macro alert data disables the buy flag. A safety-brake alert caps the
aggregate at 35; panic-zone data without that alert caps it at 49. Other specialist
failures become neutral score 50, so a report can remain incomplete even when an
aggregate is available. The initial history read can fail before orchestration;
it is not covered by the best-effort history-write policy.

## Why these components are separate

1. **Collection versus interpretation:** tools gather/compute data; specialists
   interpret a bounded domain. This permits external MCP reuse without adding
   protocol overhead to the internal workflow.
2. **Macro versus news sentiment:** prompts exclude macro topics from the news
   specialist to reduce double counting. This is an instruction, not a guarantee
   that the model follows the domain boundary.
3. **Async versus blocking I/O:** Gemini uses `client.aio`; synchronous provider
   work such as pykrx runs in `asyncio.to_thread`. Specialist calls use `gather`,
   helping keep Slack's event loop responsive without a distributed worker.
4. **Direct indicator implementation:** three needed indicators use pandas rather
   than an additional indicator package. Tests compare calculation conventions
   with independent implementations: Wilder RSI, SMA-seeded EMA for MACD and
   sample standard deviation for Bollinger bands.
5. **Shared macro result:** a process-local TTL cache defaults to 600 seconds and
   an async lock coalesces concurrent requests. Failed data collection is not
   cached. A configured positive TTL is not a cross-process cache or durable state.
6. **Readable output markers:** specialist `SCORE:` markers and PM
   `STRATEGY_START` / `STRATEGY_END` blocks are parsed for Slack rendering. This
   avoids requiring a whole narrative to be JSON but lacks typed response validation.
7. **Bounded output:** Gemini configuration uses `thinking_budget=0`, temperature
   0.3, specialist output budget 1024 and PM budget 2048 tokens. These are current
   code values; alternative models need compatibility checks.
8. **Best-effort persistence:** `save_analysis()` logs and suppresses write errors
   so a completed analysis can still return. That trades audit completeness for
   availability; no guarantee is made that every delivered report was stored.

## Macro policy detail

`FX_RISK_WEIGHTS` defines currency bands at 0, 1300, 1380, 1400 and 1450 KRW/USD
with weights 0.5, 0.8, 1.0, 2.5 and 5.0. The tool uses three-day ROC above 1%,
five-day MA divergence above 3% and daily absolute movement above 10 as alerts.
The safety brake combines USD/KRW at least 1450 with three-day ROC above 1%.

VIX values are mapped to descriptive bands in the tool and prompt. They do not
independently override PM's buy flag: the deterministic brake uses the currency
alerts. Prompt claims about correlations or expertise are not measured evidence.
These fixed policy values should not be treated as live market recommendations.

## SQLite schema and memory

```sql
CREATE TABLE watchlist (
    ticker TEXT PRIMARY KEY,
    added_at TEXT NOT NULL
);
CREATE TABLE analysis_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    final_score REAL NOT NULL,
    buy_signal INTEGER NOT NULL,
    signal_text TEXT NOT NULL,
    score_tech INTEGER NOT NULL,
    score_fund INTEGER NOT NULL,
    score_macro INTEGER NOT NULL,
    score_sent INTEGER NOT NULL
);
CREATE INDEX idx_history_ticker_time
    ON analysis_history(ticker, analyzed_at DESC);
```

Timestamps are UTC ISO strings. History stores scores and signal text, not full
reports or raw data. `_compute_delta()` supplies score/signal changes and elapsed
time to the PM prompt and Slack view. This is structured previous-result comparison,
not semantic long-term memory or event replay.

`/app/data/stock_agent.db` is selected if `/app/data` exists; otherwise the database
is `./data/stock_agent.db`. `init_db()` seeds an **empty** watchlist from `WATCHLIST_KR`.
If all tickers are removed, the next initialization can seed it again. The scheduler
reads the current DB watchlist each scan; it does not use a frozen startup list.

## Configuration

Copy [`.env.example`](../.env.example) to `.env` and keep it private.

| Variable | Default or purpose |
|---|---|
| `GEMINI_API_KEY` | Required for live model calls |
| `GEMINI_MODEL` | `gemini-2.5-flash` |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | Socket Mode integration credentials |
| `SLACK_CHANNEL_ID` | Scheduled notification destination |
| `KRX_ID`, `KRX_PW` | Credentials used by pykrx |
| `WATCHLIST_KR` | `005930,000660,035420`; empty-watchlist seed |
| `SIGNAL_THRESHOLD_STRONG` | `70`; policy threshold |
| `MACRO_CACHE_TTL_SECONDS` | `600`; process-local macro cache |
| `DEFAULT_PERIOD` | Listed in the example; not read by application code |

Input periods are supplied by function parameters rather than `DEFAULT_PERIOD`.
Some configuration is read at import time; changing `.env` is not a runtime
configuration API. Data-provider access must be checked independently.

## Slack commands

Commands are Korean because the implemented parser uses Korean command tokens.
Examples are interactions, not measured outputs:

```text
@bot 005930                 Analyze a ticker
@bot 삼성전자               Analyze a mapped company name
@bot 워치리스트             List the watchlist
@bot 추가 005930            Add a ticker
@bot 제거 005930            Remove a ticker
@bot 삭제 035420            Removal synonym
@bot 히스토리 005930        Read the latest five records
@bot 도움                   Show help
```

The name parser covers an explicit mapping and six-digit ticker tokens; it is not
unrestricted natural-language entity resolution. There is no per-user permission
policy or quota. A mention may initiate paid/external model work and post a reply.

## Scheduling, Docker and diagnosis

APScheduler runs weekdays hourly from 09:00 to 15:00 Asia/Seoul. Tickers are analyzed
sequentially within that scan; specialists are concurrent within each analysis.
There is no exchange-holiday calendar. The scheduled notifier uses `buy_signal`,
not a second independent score comparison.

The Docker image installs dependencies in a builder stage and runs as a non-root
user. `docker-compose.yml` mounts `stock_agent_data` at `/app/data`. Ordinary
`docker compose down` retains the volume. Removing the volume destroys stored
watchlists/history and is not a normal shutdown instruction.

| Symptom | First check |
|---|---|
| Price data unavailable | KRX credential/access and provider errors; neutral fallback is not valid price evidence |
| Macro unavailable | Currency provider response and `macro_available`; buy flag should be withheld |
| Strategy section absent | Marker presence and output truncation; PM has a larger token budget |
| MCP startup parsing fails | stdout must contain JSON-RPC only; import diagnostics should go to stderr |
| History delta missing | First analysis versus SQLite write warning; history can be incomplete |
| Slack command has no response | App mention subscription, Socket Mode and local logs |

Tests are run without configuring live credentials. Existing CI checks imports,
MCP registration/stdio behavior and Docker. Local tests do not establish live
provider success, container operability or model calibration.
