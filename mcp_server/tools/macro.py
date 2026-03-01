"""
Tool 6: get_macro_indicators
글로벌 매크로 지표를 수집합니다.

환율 분석 철학 (뉴노멀 기반):
- 1,380~1,400원 = 중립 구간 (현 뉴노멀 인정)
- 레벨보다 속도(Velocity, ROC)가 더 중요한 신호
- 비선형 리스크: 1,450원 이상은 위험 가중치 5배 (Panic Zone)
- Safety Brake: 1,450원 이상 + 3일 ROC > 1% → 즉각 경보

데이터 소스:
- USD/KRW: Frankfurter API (ECB 기준, 무료/키 불필요)
- JPY/USD: Frankfurter API (원화 단독 약세 여부 판별)
- KOSPI/KOSDAQ: Naver 모바일 API
- 외국인 수급: Naver Finance 스크래핑
- S&P500 / NASDAQ / VIX: yfinance (Yahoo Finance, 무료/키 불필요)
"""
import logging
import re
from datetime import datetime, timedelta

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger("mcp.tools.macro")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── 환율 위험 구간 정의 ──────────────────────────────────────────────
# 레벨 기반 위험 가중치 (비선형)
FX_RISK_WEIGHTS = [
    (1450, 5.0, "Panic/MarginCall Zone"),   # 1,450원 이상: 5배 위험
    (1400, 2.5, "Stress Zone"),              # 1,400~1,449: 2.5배 위험
    (1380, 1.0, "New Normal Zone"),          # 1,380~1,399: 중립 (뉴노멀)
    (1300, 0.8, "Stable Zone"),              # 1,300~1,379: 안정
    (0,    0.5, "Strong KRW Zone"),          # 1,300 미만: 원화 강세
]

# ROC 경보 기준
ROC_3D_ALERT = 1.0    # 3일 내 1% 이상 상승 → 수급 경보
DAILY_VOL_ALERT = 10  # 하루 10원 이상 변동 → 변동성 경보
MA5_DIVERGE_PCT = 3.0 # 5일 MA 대비 3% 이상 이격 → 급등 경보


async def get_macro_indicators(days: int = 30) -> dict:
    """
    글로벌 매크로 지표를 수집하고 뉴노멀 기반 해석 신호를 반환합니다.

    Args:
        days: 환율 조회 기간 (기본 30일)

    Returns:
        dict: 환율 분석, 지수, 외국인 수급, 비선형 리스크 신호
    """
    try:
        import asyncio
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=_HEADERS, timeout=timeout) as session:
            usd_task     = _fetch_usd_krw_advanced(session, days)
            jpy_task     = _fetch_jpy_usd(session, days)
            kospi_task   = _fetch_kospi(session)
            foreign_task = _fetch_foreign_flow(session)
            us_task      = _fetch_us_markets()   # yfinance — thread executor 실행

            usd_krw, jpy_usd, kospi, foreign_flow, us_markets = await asyncio.gather(
                usd_task, jpy_task, kospi_task, foreign_task, us_task
            )

        # 원화 단독 약세 여부 판별
        krw_solo_weak = _check_krw_solo_weakness(usd_krw, jpy_usd)

        # 종합 신호 (VIX 포함)
        signals = _build_signals(usd_krw, foreign_flow, krw_solo_weak, us_markets)

        return {
            "usd_krw":       usd_krw,
            "jpy_usd":       jpy_usd,
            "kospi":         kospi,
            "foreign_flow":  foreign_flow,
            "krw_solo_weak": krw_solo_weak,
            "us_markets":    us_markets,
            "signals":       signals,
        }

    except Exception as e:
        logger.error(f"매크로 지표 조회 실패: {e}")
        return {"error": str(e)}


# ── USD/KRW 상세 분석 ────────────────────────────────────────────────

async def _fetch_usd_krw_advanced(session: aiohttp.ClientSession, days: int) -> dict:
    """
    Frankfurter API로 USD/KRW를 가져와 속도(Velocity)·비선형 리스크를 계산합니다.
    """
    end   = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y-%m-%d")
    url   = f"https://api.frankfurter.app/{start}..{end}?from=USD&to=KRW"

    try:
        async with session.get(url) as resp:
            data = await resp.json(content_type=None)
    except Exception as e:
        logger.warning(f"Frankfurter API 실패: {e}")
        return {"error": "환율 조회 실패"}

    rates = data.get("rates", {})
    if not rates:
        return {"error": "환율 데이터 없음"}

    sorted_dates = sorted(rates.keys())[-days:]
    values       = [rates[d]["KRW"] for d in sorted_dates]

    current   = values[-1]
    prev_30d  = values[0]

    # ── 속도 지표 (Velocity) ─────────────────────────────────────
    # 3일 ROC: 단기 패닉 셀링 감지
    roc_3d = (
        (current - values[-4]) / values[-4] * 100
        if len(values) >= 4 else 0.0
    )
    # 5일 이동평균과 이격도
    ma5       = sum(values[-5:]) / min(5, len(values))
    ma5_div   = (current - ma5) / ma5 * 100

    # 일일 최대 변동 (최근 5일)
    daily_max_vol = max(
        abs(values[i] - values[i-1]) for i in range(-5, 0) if len(values) >= 5
    ) if len(values) >= 5 else 0.0

    # ── 비선형 위험 가중치 ───────────────────────────────────────
    risk_weight, risk_zone = _get_risk_weight(current)

    # ── 경보 플래그 ──────────────────────────────────────────────
    velocity_alert   = roc_3d > ROC_3D_ALERT               # 3일 급등
    volatility_alert = daily_max_vol > DAILY_VOL_ALERT      # 일별 고변동
    diverge_alert    = abs(ma5_div) > MA5_DIVERGE_PCT       # MA5 과이격
    panic_zone       = current >= 1450                       # 패닉 구간

    # Safety Brake 발동 조건
    safety_brake = panic_zone and velocity_alert

    # ── 신호 ─────────────────────────────────────────────────────
    signal = _usd_krw_signal(current, roc_3d, risk_zone, velocity_alert, panic_zone)

    return {
        "current":           round(current, 2),
        "prev_30d":          round(prev_30d, 2),
        "change_1m_pct":     round((current - prev_30d) / prev_30d * 100, 2),
        "ma5":               round(ma5, 2),
        "ma5_divergence_pct": round(ma5_div, 2),
        "roc_3d_pct":        round(roc_3d, 3),
        "daily_max_vol_5d":  round(daily_max_vol, 2),
        "risk_zone":         risk_zone,
        "risk_weight":       risk_weight,
        "alerts": {
            "velocity":   velocity_alert,   # 3일 내 급등
            "volatility": volatility_alert, # 일별 고변동
            "divergence": diverge_alert,    # MA5 과이격
            "panic_zone": panic_zone,       # 1,450원 초과
            "safety_brake": safety_brake,   # 최고 수준 경보
        },
        "signal": signal,
        "history": {
            "dates":  sorted_dates,
            "values": [round(v, 2) for v in values],
        },
    }


def _get_risk_weight(rate: float) -> tuple[float, str]:
    """환율 레벨에 따른 비선형 위험 가중치 반환"""
    for threshold, weight, zone in FX_RISK_WEIGHTS:
        if rate >= threshold:
            return weight, zone
    return 0.5, "Strong KRW Zone"


def _usd_krw_signal(
    rate: float, roc_3d: float,
    risk_zone: str, velocity_alert: bool, panic_zone: bool
) -> str:
    """레벨 + 속도를 결합한 복합 신호"""
    if panic_zone and velocity_alert:
        return "⛔ Safety Brake — 패닉구간+급등(외국인이탈 최고경보)"
    if panic_zone:
        return "🚨 Panic Zone(1450↑) — 매수신호 무효화 수준"
    if "Stress" in risk_zone and velocity_alert:
        return "⚠️ Stress Zone+급등 — 수급경보 발령"
    if "Stress" in risk_zone:
        return "⚠️ Stress Zone(1400~1449) — 외국인이탈 주의"
    if "New Normal" in risk_zone:
        return "중립 — 뉴노멀 구간(1380~1400), 수출주 유리"
    if "Stable" in risk_zone and roc_3d < -1:
        return "긍정 — 원화강세 전환 감지(외국인 유입 기대)"
    return "안정 — 원화 안정 구간"


# ── JPY/USD (원화 단독 약세 체크) ─────────────────────────────────

async def _fetch_jpy_usd(session: aiohttp.ClientSession, days: int) -> dict:
    """
    USD/JPY 추세와 비교해 원화만 유독 약세인지 판별합니다.
    원화만 약세 = 한국 고유 내부 리스크 가능성.
    """
    end   = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    url   = f"https://api.frankfurter.app/{start}..{end}?from=USD&to=JPY"

    try:
        async with session.get(url) as resp:
            data = await resp.json(content_type=None)
        rates   = data.get("rates", {})
        if not rates:
            return {"error": "JPY 데이터 없음"}
        sorted_d = sorted(rates.keys())
        vals     = [rates[d]["JPY"] for d in sorted_d]
        roc_7d   = round((vals[-1] - vals[-8]) / vals[-8] * 100, 2) if len(vals) >= 8 else 0.0
        return {
            "current_usd_jpy": round(vals[-1], 2),
            "roc_7d_pct":      roc_7d,
            "trend":           "엔약세(달러강세)" if roc_7d > 1 else (
                               "엔강세(달러약세)" if roc_7d < -1 else "횡보"),
        }
    except Exception as e:
        return {"error": str(e)}


def _check_krw_solo_weakness(usd_krw: dict, jpy_usd: dict) -> dict:
    """
    원화와 엔화 방향 비교.
    원/달러 상승 + 엔/달러 하락(엔 강세) → 원화만 유독 약세 → 한국 내부 리스크
    """
    krw_roc = usd_krw.get("roc_3d_pct", 0)
    jpy_roc = jpy_usd.get("roc_7d_pct", 0)   # 양수 = 엔 약세

    # 원화 약세 + 엔화 강세(달러 대비) = 원화 단독 약세
    solo_weak = krw_roc > 0.5 and jpy_roc < 0
    return {
        "detected": solo_weak,
        "krw_roc_3d":  krw_roc,
        "jpy_roc_7d":  jpy_roc,
        "interpretation": (
            "⚠️ 원화 단독 약세 — 한국 내부 리스크 가능성" if solo_weak
            else "글로벌 달러 강세(원화 약세, 정상 동조화)" if krw_roc > 0.5
            else "원화 안정 또는 강세"
        ),
    }


# ── KOSPI / KOSDAQ 지수 ─────────────────────────────────────────────

async def _fetch_kospi(session: aiohttp.ClientSession) -> dict:
    result = {}
    for idx_code in ["KOSPI", "KOSDAQ"]:
        basic_url = f"https://m.stock.naver.com/api/index/{idx_code}/basic"
        hist_url  = f"https://m.stock.naver.com/api/index/{idx_code}/price?pageSize=20&page=1"
        try:
            async with session.get(basic_url) as r:
                basic = await r.json(content_type=None)
            async with session.get(hist_url) as r:
                hist_list = await r.json(content_type=None)

            close = _to_float(basic.get("closePrice", "0"))
            chg   = _to_float(basic.get("compareToPreviousClosePrice", "0"))
            chg_pct = round(chg / (close - chg) * 100, 2) if (close - chg) != 0 else 0.0

            hist_list = list(reversed(hist_list)) if hist_list else []
            closes    = [_to_float(h["closePrice"]) for h in hist_list]
            dates     = [h["localTradedAt"] for h in hist_list]
            trend_20d = round((closes[-1] - closes[0]) / closes[0] * 100, 2) if len(closes) >= 2 else 0.0

            result[idx_code.lower()] = {
                "close":         close,
                "change_pct":    chg_pct,
                "trend_20d_pct": trend_20d,
                "signal":        "상승추세" if trend_20d > 2 else ("하락추세" if trend_20d < -2 else "횡보"),
                "history":       {"dates": dates, "closes": closes},
            }
        except Exception as e:
            result[idx_code.lower()] = {"error": str(e)}
    return result


# ── 외국인 수급 ──────────────────────────────────────────────────────

async def _fetch_foreign_flow(session: aiohttp.ClientSession) -> dict:
    url = "https://finance.naver.com/sise/sise_deposit.nhn"
    try:
        async with session.get(url) as resp:
            html = await resp.text(encoding="euc-kr", errors="replace")
    except Exception as e:
        return {"error": str(e)}

    soup = BeautifulSoup(html, "html.parser")
    try:
        rows = soup.select("table.type_1 tr")
        result = {}
        for row in rows:
            tds = row.select("td")
            if len(tds) >= 2:
                label = tds[0].get_text(strip=True)
                value = tds[1].get_text(strip=True).replace(",", "").replace("억", "")
                if "외국인" in label:
                    try:
                        result[label] = int(value)
                    except ValueError:
                        pass

        net = result.get("외국인순매수", result.get("외국인", None))
        signal = ("외국인순매수" if (net and net > 0)
                  else "외국인순매도" if (net and net < 0)
                  else "데이터없음")
        return {
            "net_buy_billion": round(net / 1e8, 1) if isinstance(net, (int, float)) else None,
            "signal":          signal,
        }
    except Exception as e:
        return {"error": str(e)}


# ── 종합 신호 ─────────────────────────────────────────────────────────

def _build_signals(
    usd_krw: dict, foreign_flow: dict,
    krw_solo: dict, us_markets: dict
) -> dict:
    alerts    = usd_krw.get("alerts", {})
    risk_zone = usd_krw.get("risk_zone", "")
    f_sig     = foreign_flow.get("signal", "")

    # VIX 공포 지수 추출
    vix_val    = 0.0
    vix_signal = "N/A"
    if isinstance(us_markets, dict) and "vix" in us_markets:
        vix_val    = us_markets["vix"].get("current", 0.0) or 0.0
        vix_signal = us_markets["vix"].get("signal", "N/A")

    global_fear = vix_val >= 30  # VIX 30+ = 글로벌 공포 구간

    signals = {
        "exchange_rate":  usd_krw.get("signal", "N/A"),
        "foreign_flow":   f_sig,
        "krw_solo_weak":  krw_solo.get("interpretation", "N/A"),
        "safety_brake":   alerts.get("safety_brake", False),
        "vix_signal":     vix_signal,
        "sp500_signal":   us_markets.get("sp500", {}).get("signal", "N/A") if isinstance(us_markets, dict) else "N/A",
        "nasdaq_signal":  us_markets.get("nasdaq", {}).get("signal", "N/A") if isinstance(us_markets, dict) else "N/A",
    }

    # 종합 환경 판단 (Safety Brake + VIX 복합 고려)
    if alerts.get("safety_brake") and global_fear:
        signals["overall"] = "⛔ 최고경보 — Safety Brake 발동 + 글로벌 공포(VIX≥30)"
    elif alerts.get("safety_brake"):
        signals["overall"] = "⛔ 최고경보 — Safety Brake 발동(매수 불가)"
    elif alerts.get("panic_zone") or global_fear:
        signals["overall"] = "🚨 Panic/글로벌리스크오프 — 매수 극도 자제"
    elif alerts.get("velocity") and "Stress" in risk_zone:
        signals["overall"] = "⚠️ Stress+급등 — 수급 경보"
    elif "순매수" in f_sig and "Stable" in risk_zone:
        signals["overall"] = "✅ 우호적 — 환율안정+외국인유입"
    elif "순매도" in f_sig:
        signals["overall"] = "❌ 불리 — 외국인 이탈 중"
    elif "Stress" in risk_zone:
        signals["overall"] = "⚠️ Stress Zone — 수급 주의"
    else:
        signals["overall"] = "중립"

    return signals


def _to_float(s) -> float:
    try:
        return float(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


# ── 미국 시장 지수 (S&P500, NASDAQ, VIX) ─────────────────────────────
# yfinance는 동기 라이브러리 → asyncio.run_in_executor로 스레드풀 실행
# aiohttp 이벤트루프 차단 없이 다른 비동기 작업과 병렬 실행 가능

async def _fetch_us_markets() -> dict:
    """
    S&P500, NASDAQ, VIX를 yfinance로 수집합니다.
    동기 함수(_fetch_us_markets_sync)를 thread executor에서 실행합니다.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_us_markets_sync)


def _fetch_us_markets_sync() -> dict:
    """yfinance 동기 호출 — executor 전용. 직접 호출 시 이벤트루프 차단."""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance 미설치 — pip install yfinance")
        return {"error": "yfinance 미설치"}

    symbols = {
        "sp500":  "^GSPC",   # S&P 500 (미국 대형주 종합)
        "nasdaq": "^IXIC",   # NASDAQ Composite (기술주 중심)
        "vix":    "^VIX",    # CBOE VIX (공포 지수)
    }
    result = {}

    for name, sym in symbols.items():
        try:
            data = yf.download(
                sym, period="5d", interval="1d",
                progress=False, auto_adjust=True,
            )
            if data.empty:
                result[name] = {"error": "데이터 없음"}
                continue

            # yfinance 1.x: MultiIndex DataFrame → squeeze()로 Series 변환
            closes = data["Close"].squeeze().dropna().values.tolist()
            current    = round(float(closes[-1]), 2)
            change_pct = (
                round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
                if len(closes) >= 2 else 0.0
            )
            result[name] = {
                "current":    current,
                "change_pct": change_pct,
                "signal":     _us_index_signal(name, current, change_pct),
            }
        except Exception as e:
            logger.warning(f"US 시장 데이터 오류 [{sym}]: {e}")
            result[name] = {"error": str(e)}

    return result


def _us_index_signal(name: str, value: float, chg_pct: float) -> str:
    """VIX 공포 구간 및 미국 지수 방향 신호 텍스트"""
    if name == "vix":
        if value >= 35: return f"⛔ 극도 공포 (VIX {value:.1f}) — 전면 리스크오프"
        if value >= 30: return f"🚨 공포 구간 (VIX {value:.1f}) — 신흥국 자금 이탈"
        if value >= 25: return f"⚠️ 변동성 상승 (VIX {value:.1f}) — 주의"
        if value >= 20: return f"🟡 경계 구간 (VIX {value:.1f})"
        return               f"✅ 안정 (VIX {value:.1f})"
    # S&P500 / NASDAQ
    if chg_pct >=  1.5: return f"강세 (+{chg_pct:.2f}%)"
    if chg_pct >=  0.0: return f"소폭 상승 (+{chg_pct:.2f}%)"
    if chg_pct >= -1.5: return f"소폭 하락 ({chg_pct:.2f}%)"
    return                   f"약세 ({chg_pct:.2f}%)"
