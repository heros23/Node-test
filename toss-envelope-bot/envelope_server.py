"""
엔벨로프 전략 통합 대시보드 서버
- S&P500 / 코스피200 / 코스닥150
- 스캐너 + 차트 + 백테스트 + 실시간 워치리스트
"""

from flask import Flask, jsonify, request, send_from_directory
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import threading
import os
import json
import sys
import re

# Add project root to sys.path so src.* imports work when running from this folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.config_store import apply_config_to_environment, load_config
from src.broker_client import BrokerClient

app = Flask(__name__, static_folder='.', static_url_path='')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def no_cache(resp):
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp

# ─── 종목 DB ──────────────────────────────────────────────────────────────

MARKETS = {
    "US": {
        "name": "S&P500",
        "currency": "USD",
        "suffix": "",
        "index": "^GSPC",
        "index_name": "S&P 500",
        "sectors": {
            "Technology":    ["AAPL","MSFT","NVDA","META","GOOGL","AVGO","CRM","ORCL","AMD","INTC","QCOM","TXN","NOW","ADBE","INTU","AMAT","MU","LRCX"],
            "Healthcare":    ["LLY","UNH","JNJ","ABBV","MRK","TMO","ABT","DHR","BMY","AMGN","GILD","VRTX","REGN","ISRG","SYK","MDT"],
            "Financials":    ["BRK-B","JPM","V","MA","BAC","WFC","GS","MS","BLK","SCHW","AXP","CB","PGR","MMC","COF"],
            "Consumer Disc": ["AMZN","TSLA","HD","MCD","NKE","LOW","SBUX","TJX","BKNG","CMG","ORLY","AZO","DHI","GM","F"],
            "Industrials":   ["UNP","HON","CAT","GE","RTX","DE","BA","MMM","LMT","FDX","UPS","CSX","WM","ETN","EMR"],
            "Energy":        ["XOM","CVX","COP","SLB","EOG","MPC","VLO","PSX","OXY","BKR","HAL","DVN","HES","APA","MRO"],
            "Comm Svc":      ["NFLX","DIS","CMCSA","VZ","T","TMUS","EA","WBD","OMC"],
            "Cons Staples":  ["PG","KO","PEP","COST","WMT","CL","KMB","MO","GIS","K"],
            "Utilities":     ["NEE","DUK","SO","D","AEP","EXC","XEL","ED","SRE","WEC"],
            "Materials":     ["LIN","APD","SHW","ECL","NEM","FCX","NUE","VMC","DOW"],
            "Real Estate":   ["AMT","PLD","CCI","EQIX","PSA","DLR","O","WELL","SPG"],
        }
    },
    "KOSPI": {
        "name": "코스피200",
        "currency": "KRW",
        "suffix": ".KS",
        "index": "^KS200",
        "index_name": "KOSPI 200",
        "sectors": {
            "반도체":   ["005930","000660","042700","066570","009150","058470","036540"],
            "IT·전기":  ["005380","012330","007070","011200","009540","018260","036460"],
            "금융":     ["105560","055550","086790","316140","138040","175330","024110"],
            "바이오":   ["207940","068270","128940","032640","000100","326030","011070"],
            "소비재":   ["051900","097950","033780","004990","006400","008770","030200"],
            "에너지·화학":["010950","011170","010130","011790","006650","002790","004020"],
            "건설·중공업":["000720","047050","009830","010140","012450","064350","267250"],
            "통신·미디어":["017670","030200","032640","035420","251270","035720","259960"],
            "유통·서비스":["139480","004170","069960","282330","071840","007310","005070"],
        }
    },
    "KOSDAQ": {
        "name": "코스닥150",
        "currency": "KRW",
        "suffix": ".KQ",
        "index": "^KQ150",
        "index_name": "KOSDAQ 150",
        "sectors": {
            "IT·소프트웨어": ["293490","035900","041510","048410","357780","145020","036930"],
            "바이오·헬스":   ["091990","145720","263750","214450","950130","226950","086520"],
            "반도체·장비":   ["058470","036540","054450","036830","095340","240810","039030"],
            "엔터·콘텐츠":   ["041510","035900","093320","035080","112040","950190","122870"],
            "2차전지·소재":  ["247540","357780","096530","006740","298040","298050","064760"],
            "게임":          ["263750","036830","112040","194480","078340","225570","263020"],
            "기타":          ["058970","041830","108790","089030","053300","060150","900110"],
        }
    }
}

def get_all_tickers(market_key: str) -> list:
    m = MARKETS.get(market_key, {})
    suffix = m.get("suffix", "")
    tickers = []
    for stocks in m.get("sectors", {}).values():
        for s in stocks:
            tickers.append(s + suffix if suffix and not s.endswith(suffix) else s)
    return list(dict.fromkeys(tickers))

def get_sector(market_key: str, ticker: str) -> str:
    m = MARKETS.get(market_key, {})
    suffix = m.get("suffix", "")
    base = ticker.replace(suffix, "") if suffix else ticker
    for sec, stocks in m.get("sectors", {}).items():
        if base in stocks or ticker in stocks:
            return sec
    return "기타"


# ─── 티커 변환/해석 ─────────────────────────────────────────────────────────

# 간단한 종목명 매핑 (한국 종목 코드/명칭 → 티커)
_KOREAN_NAME_MAP = {
    "삼성전자": "005930", "SK하이닉스": "000660", "LG에너지솔루션": "373220",
    "삼성바이오로직스": "207940", "현대차": "005380", "셀트리온": "068270",
    "기아": "000270", "POSCO홀딩스": "005490", "삼성SDI": "006400",
    "NAVER": "035420", "카카오": "035720", "한국전력": "015760",
    "현대모비스": "012330", "LG화학": "051910", "삼성전자우": "005935",
    "SK이노베이션": "096770", "KB금융": "105560", "신한지주": "055550",
    "하나금융지주": "086790", "삼성생명": "032830", "삼성화재": "000810",
    "CJ제일제당": "097950", "아모레퍼시픽": "090430", "LG생활건강": "051900",
    "카카오뱅크": "323410", "크래프톤": "259960", "현대중공업": "329180",
    "두산에너빌리티": "034020", "SK텔레콤": "017670", "LG전자": "066570",
    "SK": "034730", "한화에어로스페이스": "012450", "삼성중공업": "010140",
    "현대제철": "004020", "S-Oil": "010950", "GS칼텍스": "007070",
    "SK바이오팜": "326030", "삼성엔지니어링": "028050", "대한항공": "003490",
    "HMM": "011200", "LG": "003550", "KT": "030200", "삼성SDS": "018260",
    "현대건설": "000720", "메리츠금융지주": "138040", "키움증권": "039490",
    "신세계": "004170", "현대로템": "064350",
}

# 영문 종목명 매핑 (S&P500 일부)
_ENGLISH_NAME_MAP = {
    "APPLE": "AAPL", "MICROSOFT": "MSFT", "NVIDIA": "NVDA", "ALPHABET": "GOOGL",
    "GOOGLE": "GOOGL", "AMAZON": "AMZN", "TESLA": "TSLA", "META": "META",
    "BERKSHIRE": "BRK-B", "UNITEDHEALTH": "UNH", "JOHNSON": "JNJ", "JPMORGAN": "JPM",
    "VISA": "V", "MASTERCARD": "MA", "EXXON": "XOM", "CHEVRON": "CVX",
    "LILLY": "LLY", "PROCTER": "PG", "COCA-COLA": "KO", "PEPSICO": "PEP",
    "WALMART": "WMT", "MCDONALD": "MCD", "DISNEY": "DIS", "NETFLIX": "NFLX",
    "BOEING": "BA", "INTEL": "INTC", "AMD": "AMD", "QUALCOMM": "QCOM",
    "CISCO": "CSCO", "VERIZON": "VZ", "AT&T": "T", "HOME-DEPOT": "HD",
    "BANK-OF-AMERICA": "BAC", "WELLS-FARGO": "WFC", "GOLDMAN-SACHS": "GS",
    "MORGAN-STANLEY": "MS", "CITIGROUP": "C", "PAYPAL": "PYPL", "ADOBE": "ADBE",
    "SALESFORCE": "CRM", "ORACLE": "ORCL", "IBM": "IBM", "SHELL": "SHEL",
    "TOYOTA": "TM", "UNILEVER": "UL", "NESTLE": "NESN", "TSMC": "TSM",
}

# 코드/티커 → 종목명 역매핑
_KOREAN_NAME_MAP_REV = {v: k for k, v in _KOREAN_NAME_MAP.items()}
_KOREAN_NAME_MAP_LOOKUP = {re.sub(r"\s+", "", k).upper(): v for k, v in _KOREAN_NAME_MAP.items()}
_ENGLISH_NAME_MAP_REV = {v: k for k, v in _ENGLISH_NAME_MAP.items()}
_DISPLAY_NAME_CACHE: dict[str, str] = {}
_display_name_lock = threading.Lock()


def _fallback_stock_name(market_key: str, base: str) -> str:
    """하드코딩 매핑 기반 최후 fallback 이름."""
    if market_key in ("KOSPI", "KOSDAQ"):
        return _KOREAN_NAME_MAP_REV.get(base) or _ENGLISH_NAME_MAP_REV.get(base) or base
    return _ENGLISH_NAME_MAP_REV.get(base) or _KOREAN_NAME_MAP_REV.get(base) or base


def _extract_company_name(payload: dict) -> str | None:
    """yfinance 메타데이터에서 종목명을 우선순위대로 추출."""
    for key in ("longName", "shortName", "displayName", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _lookup_korean_code(query: str) -> str | None:
    """공백/영문 대소문자를 무시하고 한국 종목명을 코드로 조회."""
    normalized = re.sub(r"\s+", "", query).upper()
    return _KOREAN_NAME_MAP_LOOKUP.get(normalized)


def get_stock_name(market_key: str, ticker: str) -> str:
    """풀 티커/코드를 종목명으로 변환. 가능하면 실제 회사명을 조회하고, 실패 시 fallback 사용."""
    suffix = MARKETS.get(market_key, {}).get("suffix", "")
    base = ticker.replace(suffix, "") if suffix else ticker

    # 한국 종목은 하드코딩된 한글명이 있으면 우선 사용
    mapped_korean_name = _KOREAN_NAME_MAP_REV.get(base)
    if mapped_korean_name:
        return mapped_korean_name

    cache_key = f"{market_key}:{base}"
    with _display_name_lock:
        cached_name = _DISPLAY_NAME_CACHE.get(cache_key)
    if cached_name:
        return cached_name

    resolved_name = None
    full_ticker = ticker if suffix and ticker.endswith(suffix) else (base + suffix if suffix else base)
    try:
        resolved_name = _extract_company_name(yf.Ticker(full_ticker).get_history_metadata() or {})
    except Exception:
        resolved_name = None

    if not resolved_name:
        try:
            resolved_name = _extract_company_name(yf.Ticker(full_ticker).info or {})
        except Exception:
            resolved_name = None

    if not resolved_name:
        resolved_name = _fallback_stock_name(market_key, base)

    with _display_name_lock:
        _DISPLAY_NAME_CACHE[cache_key] = resolved_name
    return resolved_name


def normalize_ticker_input(market_key: str, query: str) -> str | None:
    """
    사용자 입력(query)을 yfinance용 풀 티커로 변환.
    - 입력이 없으면 None
    - 6자리 숫자 코드(KOSPI/KOSDAQ) → suffix(.KS/.KQ) 추가
    - 종목명(한글/영문) → 코드 매핑 → 풀 티커
    - 이미 풀 티커면 그대로 반환
    - US 티커는 대문자로 반환
    """
    query = query.strip().upper()
    if not query:
        return None

    m = MARKETS.get(market_key, {})
    suffix = m.get("suffix", "")

    # 1. US: 영문 종목명 매핑을 먼저 시도, 그 후 티커 그대로 반환
    if market_key == "US":
        mapped = _ENGLISH_NAME_MAP.get(query)
        if mapped:
            return mapped
        if query.isalpha():
            return query
        return _ENGLISH_NAME_MAP.get(query, query)

    # 2. 6자리 숫자면 종목코드 → suffix 추가
    if re.fullmatch(r"\d{6}", query):
        return query + suffix

    # 3. 한글/영문 종목명 → 종목코드 변환
    code = _lookup_korean_code(query)
    if code:
        return code + suffix

    # 4. 영문명 매핑 시도
    code = _ENGLISH_NAME_MAP.get(query)
    if code:
        return code + suffix

    # 5. 이미 .KS/.KQ 붙은 풀 티커인지 확인
    if query.endswith((".KS", ".KQ")):
        return query

    # 6. 그 외는 입력을 그대로 suffix 붙여 시도
    return query + suffix


def resolve_ticker(market_key: str, query: str) -> str | None:
    """백테스트용: 종목명/코드/티커를 풀 티커로 해석."""
    return normalize_ticker_input(market_key, query)


# ─── 엔벨로프 계산 ────────────────────────────────────────────────────────

def calc_envelope(df: pd.DataFrame, period: int = 20, pct: float = 5.0) -> pd.DataFrame:
    df = df.copy()
    df['MA']    = df['Close'].rolling(period).mean()
    df['Upper'] = df['MA'] * (1 + pct / 100)
    df['Lower'] = df['MA'] * (1 - pct / 100)
    return df

def get_signal(df: pd.DataFrame, pct: float = 5.0) -> dict:
    if df is None or len(df) < 3:
        return {"signal": "N/A", "strength": 0}
    last = df.iloc[-1]
    close, ma, upper, lower = last['Close'], last['MA'], last['Upper'], last['Lower']
    if pd.isna(ma):
        return {"signal": "N/A", "strength": 0}

    pct_from_lower = (close - lower) / lower * 100
    pct_from_upper = (close - upper) / upper * 100
    pct_from_ma    = (close - ma)    / ma    * 100

    if   close <= lower:           signal, strength = "STRONG_BUY",  min(100, int(abs(pct_from_lower)*20))
    elif close <= lower * 1.01:    signal, strength = "BUY",         80
    elif close >= upper:           signal, strength = "STRONG_SELL", min(100, int(abs(pct_from_upper)*20))
    elif close >= upper * 0.99:    signal, strength = "SELL",        80
    elif pct_from_ma < -pct*0.5:   signal, strength = "WATCH_BUY",  40
    elif pct_from_ma >  pct*0.5:   signal, strength = "WATCH_SELL", 40
    else:                          signal, strength = "NEUTRAL",     0

    return {
        "signal": signal, "strength": strength,
        "close":  round(float(close), 2),
        "ma":     round(float(ma),    2),
        "upper":  round(float(upper), 2),
        "lower":  round(float(lower), 2),
        "pct_from_ma":    round(float(pct_from_ma),    2),
        "pct_from_lower": round(float(pct_from_lower), 2),
        "pct_from_upper": round(float(pct_from_upper), 2),
    }


# ─── 백테스트 ────────────────────────────────────────────────────────────

def backtest_envelope(df, period=20, pct=5.0, stop_loss=3.0, take_profit=5.0):
    df = calc_envelope(df, period, pct).dropna()
    capital = 10_000_000
    cash, shares, position = capital, 0, None
    trades = []

    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i-1]
        price = float(row['Close'])

        if position is None:
            if prev['Close'] > prev['Lower'] and row['Close'] <= row['Lower']:
                shares = int(cash * 0.9 / price)
                if shares > 0:
                    cash -= shares * price
                    position = {"entry": price, "shares": shares, "date": str(row.name)[:10]}
        else:
            pnl_pct = (price - position["entry"]) / position["entry"] * 100
            reason = None
            if   price >= row['Upper']:        reason = "상단밴드 도달"
            elif pnl_pct >= take_profit:       reason = "목표수익 달성"
            elif pnl_pct <= -stop_loss:        reason = "손절"
            if reason:
                cash += shares * price
                trades.append({
                    "entry_date": position["date"], "exit_date": str(row.name)[:10],
                    "entry": round(position["entry"],2), "exit": round(price,2),
                    "shares": position["shares"],
                    "pnl": round(shares*price - position["shares"]*position["entry"], 2),
                    "pnl_pct": round(pnl_pct, 2), "reason": reason,
                })
                position, shares = None, 0

    if position:
        price = float(df.iloc[-1]['Close'])
        cash += shares * price
        pnl_pct = (price - position["entry"]) / position["entry"] * 100
        trades.append({
            "entry_date": position["date"], "exit_date": str(df.index[-1])[:10],
            "entry": round(position["entry"],2), "exit": round(price,2),
            "shares": position["shares"],
            "pnl": round(shares*price - position["shares"]*position["entry"], 2),
            "pnl_pct": round(pnl_pct, 2), "reason": "기간 종료(보유중)",
        })

    wins   = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_return = (cash - capital) / capital * 100
    win_rate     = len(wins)/len(trades)*100 if trades else 0

    # MDD
    pv = []
    c2, pos2, sh2 = capital, None, 0
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i-1]
        p = float(row['Close'])
        if pos2 is None:
            if prev['Close'] > prev['Lower'] and row['Close'] <= row['Lower']:
                sh2 = int(c2*0.9/p)
                if sh2 > 0: c2 -= sh2*p; pos2 = p
        else:
            pp = (p-pos2)/pos2*100
            if p >= row['Upper'] or pp >= take_profit or pp <= -stop_loss:
                c2 += sh2*p; pos2, sh2 = None, 0
        pv.append(c2 + sh2*p)
    ps = pd.Series(pv) if pv else pd.Series([capital])
    mdd = float(((ps - ps.cummax()) / ps.cummax() * 100).min())

    return {
        "total_return": round(total_return, 2),
        "total_pnl":    round(cash - capital, 0),
        "final_value":  round(cash, 0),
        "win_rate":     round(win_rate, 1),
        "trade_count":  len(trades),
        "win_count":    len(wins),
        "loss_count":   len(losses),
        "avg_profit_pct": round(float(np.mean([t['pnl_pct'] for t in wins]))   if wins   else 0, 2),
        "avg_loss_pct":   round(float(np.mean([t['pnl_pct'] for t in losses])) if losses else 0, 2),
        "mdd":            round(mdd, 2),
        "trades":         trades[-20:],
    }


# ─── 워치리스트 (메모리) ─────────────────────────────────────────────────

wl_lock = threading.Lock()
watchlist: dict = {}   # key = "market:ticker"

def fetch_snapshot(ticker: str, period: int, pct: float) -> dict:
    try:
        end   = datetime.now()
        start = end - timedelta(days=max(90, period*3))
        df    = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        if df.empty or len(df) < period+2:
            return None
        df = df[['Close']].copy()
        df = calc_envelope(df, period, pct).dropna()
        if df.empty:
            return None
        sig = get_signal(df, pct)
        change_1d = 0.0
        if len(df) >= 2:
            prev = float(df['Close'].iloc[-2])
            curr = float(df['Close'].iloc[-1])
            change_1d = round((curr-prev)/prev*100, 2)
        sig['change_1d']  = change_1d
        sig['updated_at'] = datetime.now().strftime('%H:%M:%S')
        return sig
    except Exception:
        return None


def run_market_scan(market: str, period: int = 20, pct: float = 5.0, universe_limit: int = 60) -> dict:
    m = MARKETS.get(market)
    if not m:
        raise ValueError('unknown market')

    tickers = get_all_tickers(market)[:max(1, int(universe_limit or 60))]
    end = datetime.now()
    start = end - timedelta(days=120)
    results = []

    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    close_df = raw['Close'] if isinstance(raw.columns, pd.MultiIndex) else raw

    for ticker in tickers:
        try:
            col = ticker if ticker in close_df.columns else None
            if col is None:
                continue
            s = close_df[col].dropna()
            if len(s) < period + 5:
                continue
            df = pd.DataFrame({'Close': s})
            df = calc_envelope(df, period, pct)
            sig = get_signal(df, pct)
            if sig['signal'] == 'N/A':
                continue

            w52_high = float(s.tail(252).max())
            w52_low = float(s.tail(252).min())
            from_52h = (sig['close'] - w52_high) / w52_high * 100

            change_1d = 0.0
            if len(s) >= 2:
                change_1d = (float(s.iloc[-1]) - float(s.iloc[-2])) / float(s.iloc[-2]) * 100

            results.append({
                'ticker': ticker,
                'market': market,
                'display_ticker': ticker.replace(m['suffix'], '') if m['suffix'] else ticker,
                'display_name': get_stock_name(market, ticker),
                'sector': get_sector(market, ticker),
                'signal': sig['signal'],
                'strength': sig['strength'],
                'close': sig['close'],
                'ma': sig['ma'],
                'upper': sig['upper'],
                'lower': sig['lower'],
                'pct_from_ma': sig['pct_from_ma'],
                'pct_from_lower': sig['pct_from_lower'],
                'pct_from_upper': sig['pct_from_upper'],
                'week52_high': round(w52_high, 2),
                'week52_low': round(w52_low, 2),
                'from_52w_high': round(from_52h, 2),
                'change_1d': round(change_1d, 2),
                'currency': m['currency'],
            })
        except Exception:
            continue

    return {'stocks': results, 'scanned': len(tickers), 'market': market}


def filter_scan_results(results: list[dict], sig_filter: str = 'ALL') -> list[dict]:
    sig_filter = (sig_filter or 'ALL').upper()
    if sig_filter == 'BUY':
        return [r for r in results if 'BUY' in r['signal']]
    if sig_filter == 'SELL':
        return [r for r in results if 'SELL' in r['signal']]
    return results


_SIGNAL_PRESET_MAP = {
    'ALL': [],
    'STRONG_BUY': ['STRONG_BUY'],
    'BUY_SETUP': ['STRONG_BUY', 'BUY'],
    'BUY_WATCH': ['WATCH_BUY'],
    'BUY_ALL': ['STRONG_BUY', 'BUY', 'WATCH_BUY'],
    'SELL_WATCH': ['WATCH_SELL'],
    'SELL_ALERT': ['WATCH_SELL', 'SELL', 'STRONG_SELL'],
    'STRONG_SELL': ['STRONG_SELL'],
    'SELL_ALL': ['WATCH_SELL', 'SELL', 'STRONG_SELL'],
    'NEUTRAL': ['NEUTRAL'],
}


def _to_float_or_none(value):
    if value in (None, '', 'null'):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stock_matches_group(stock: dict, group: dict) -> bool:
    signals = group.get('signals') or _SIGNAL_PRESET_MAP.get((group.get('signal_mode') or 'ALL').upper(), [])
    if signals and stock.get('signal') not in signals:
        return False

    min_strength = int(group.get('min_strength', 0) or 0)
    if stock.get('strength', 0) < min_strength:
        return False

    max_pct_from_lower = _to_float_or_none(group.get('max_pct_from_lower'))
    if max_pct_from_lower is not None and float(stock.get('pct_from_lower', 0)) > max_pct_from_lower:
        return False

    min_pct_from_lower = _to_float_or_none(group.get('min_pct_from_lower'))
    if min_pct_from_lower is not None and float(stock.get('pct_from_lower', 0)) < min_pct_from_lower:
        return False

    max_pct_from_ma = _to_float_or_none(group.get('max_pct_from_ma'))
    if max_pct_from_ma is not None and float(stock.get('pct_from_ma', 0)) > max_pct_from_ma:
        return False

    min_pct_from_ma = _to_float_or_none(group.get('min_pct_from_ma'))
    if min_pct_from_ma is not None and float(stock.get('pct_from_ma', 0)) < min_pct_from_ma:
        return False

    min_pct_from_upper = _to_float_or_none(group.get('min_pct_from_upper'))
    if min_pct_from_upper is not None and float(stock.get('pct_from_upper', 0)) < min_pct_from_upper:
        return False

    max_from_52w_high = _to_float_or_none(group.get('max_from_52w_high'))
    if max_from_52w_high is not None and float(stock.get('from_52w_high', 0)) > max_from_52w_high:
        return False

    min_from_52w_high = _to_float_or_none(group.get('min_from_52w_high'))
    if min_from_52w_high is not None and float(stock.get('from_52w_high', 0)) < min_from_52w_high:
        return False

    return True


def _sort_group_results(results: list[dict], sort_by: str = 'pct_from_lower', sort_order: str = 'asc') -> list[dict]:
    key_name = sort_by or 'pct_from_lower'
    reverse = (sort_order or 'asc').lower() == 'desc'
    return sorted(results, key=lambda item: float(item.get(key_name, 0) or 0), reverse=reverse)


# ─── API 라우트 ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'envelope_dashboard.html')

# 시장 목록
@app.route('/api/markets')
def markets():
    return jsonify({k: {"name": v["name"], "currency": v["currency"],
                        "index_name": v["index_name"]} for k, v in MARKETS.items()})

# 지수 현황
@app.route('/api/index/<market>')
def index_summary(market: str):
    m = MARKETS.get(market)
    if not m:
        return jsonify({"error": "unknown market"}), 404
    period = int(request.args.get('period', 20))
    pct    = float(request.args.get('pct', 5.0))
    try:
        end   = datetime.now()
        start = end - timedelta(days=120)
        raw = yf.download(m['index'], start=start, end=end, auto_adjust=True, progress=False)
        df  = pd.DataFrame({'Close': raw['Close'].squeeze()})
        df  = calc_envelope(df, period, pct)
        sig = get_signal(df, pct)

        raw1y = yf.download(m['index'], start=end-timedelta(days=365), end=end,
                            auto_adjust=True, progress=False)
        ret1y = 0.0
        if not raw1y.empty:
            c = raw1y['Close'].squeeze()
            ret1y = float((c.iloc[-1]-c.iloc[0])/c.iloc[0]*100)

        return jsonify({"market": market, "name": m['index_name'],
                        "signal": sig, "return_1y": round(ret1y,2)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 스캐너
@app.route('/api/scan/<market>')
def scan(market: str):
    period = int(request.args.get('period', 20))
    pct = float(request.args.get('pct', 5.0))
    sig_filter = request.args.get('signal', 'ALL')
    limit = int(request.args.get('limit', 50))

    try:
        payload = run_market_scan(market, period, pct)
    except ValueError:
        return jsonify({"error": "unknown market"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    results = filter_scan_results(payload['stocks'], sig_filter)
    results.sort(key=lambda x: x['pct_from_lower'])
    return jsonify({"stocks": results[:limit], "total": len(results), "scanned": payload['scanned'], "market": market})


@app.route('/api/watchlist/group_scan', methods=['POST'])
def watchlist_group_scan():
    data = request.get_json(force=True) or {}
    market = data.get('market', 'US')
    period = int(data.get('period', 20))
    pct = float(data.get('pct', 5.0))
    limit = int(data.get('limit', 8))

    try:
        payload = run_market_scan(market, period, pct)
    except ValueError:
        return jsonify({'error': 'unknown market'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    matched = [stock for stock in payload['stocks'] if _stock_matches_group(stock, data)]
    sort_by = data.get('sort_by', 'pct_from_lower')
    sort_order = data.get('sort_order', 'asc')
    matched = _sort_group_results(matched, sort_by, sort_order)
    limited = matched[:limit]

    return jsonify({
        'group': {
            'id': data.get('id'),
            'name': data.get('name', ''),
            'market': market,
            'period': period,
            'pct': pct,
            'signal_mode': data.get('signal_mode', 'ALL'),
        },
        'stocks': limited,
        'matched': len(matched),
        'scanned': payload['scanned'],
        'updated_at': datetime.now().strftime('%H:%M:%S'),
        'summary': {
            'buy': sum(1 for item in limited if 'BUY' in item['signal']),
            'sell': sum(1 for item in limited if 'SELL' in item['signal']),
            'strong': sum(1 for item in limited if 'STRONG' in item['signal']),
        },
    })

# 차트 데이터
@app.route('/api/chart/<market>/<ticker>')
def chart_data(market: str, ticker: str):
    m = MARKETS.get(market)
    if not m:
        return jsonify({"error":"unknown market"}), 404
    days   = int(request.args.get('days', 180))
    period = int(request.args.get('period', 20))
    pct    = float(request.args.get('pct', 5.0))

    # 종목명/코드/티커를 yfinance용 풀 티커로 변환
    full_ticker = resolve_ticker(market, ticker)
    if not full_ticker:
        return jsonify({"error":"티커를 해석할 수 없습니다"}), 400

    end   = datetime.now()
    start = end - timedelta(days=days + period*2)
    try:
        df = yf.Ticker(full_ticker).history(start=start, end=end, auto_adjust=True)
        if df.empty:
            return jsonify({"error":"No data"}), 404
        df = df[['Open','High','Low','Close','Volume']].copy()
        df = calc_envelope(df, period, pct).dropna()
        df = df.tail(days)
        sig = get_signal(df, pct)

        ohlc = [{"date": str(dt)[:10],
                 "open":   round(float(r['Open']),  2),
                 "high":   round(float(r['High']),  2),
                 "low":    round(float(r['Low']),   2),
                 "close":  round(float(r['Close']), 2),
                 "volume": int(r['Volume']),
                 "ma":     round(float(r['MA']),    2),
                 "upper":  round(float(r['Upper']), 2),
                 "lower":  round(float(r['Lower']), 2),
                 } for dt, r in df.iterrows()]
        return jsonify({"ticker": full_ticker, "market": market,
                        "currency": m['currency'], "ohlc": ohlc, "signal": sig})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 백테스트
@app.route('/api/backtest/<market>/<ticker>')
@app.route('/api/backtest/<market>/', defaults={"ticker": ""})
@app.route('/api/backtest/<market>', defaults={"ticker": ""})
def backtest_route(market: str, ticker: str):
    m = MARKETS.get(market)
    if not m:
        return jsonify({"error":"unknown market"}), 404
    days       = int(request.args.get('days', 365))
    period     = int(request.args.get('period', 20))
    pct        = float(request.args.get('pct', 5.0))
    stop_loss  = float(request.args.get('stop_loss', 3.0))
    take_profit= float(request.args.get('take_profit', 5.0))

    end   = datetime.now()
    start = end - timedelta(days=days + period*2)

    # 1) 티커가 없으면 전체 종목 백테스트
    if not ticker or not ticker.strip():
        return _backtest_all(market, m, start, end, days, period, pct, stop_loss, take_profit)

    # 2) 종목명/코드/티커 해석
    full_ticker = resolve_ticker(market, ticker)
    if not full_ticker:
        return jsonify({"error":"티커를 해석할 수 없습니다"}), 400

    try:
        df = yf.Ticker(full_ticker).history(start=start, end=end, auto_adjust=True)
        if df.empty:
            return jsonify({"error":"No data"}), 404
        result = backtest_envelope(df[['Close']].copy(), period, pct, stop_loss, take_profit)
        result.update({"ticker": full_ticker, "market": market, "currency": m['currency'],
                       "display_ticker": full_ticker.replace(m['suffix'],'') if m['suffix'] else full_ticker,
                       "display_name": get_stock_name(market, full_ticker),
                       "params": {"period":period,"pct":pct,"stop_loss":stop_loss,
                                  "take_profit":take_profit,"days":days}})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _backtest_all(market, m, start, end, days, period, pct, stop_loss, take_profit):
    """선택한 시장의 전체 종목에 대해 백테스트하고 집계 결과 반환."""
    tickers = get_all_tickers(market)
    results = []
    errors  = []
    try:
        raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
        close_df = raw['Close'] if isinstance(raw.columns, pd.MultiIndex) else raw
    except Exception as e:
        return jsonify({"error": f"데이터 수집 실패: {e}"}), 500

    for ticker in tickers:
        try:
            col = ticker if ticker in close_df.columns else None
            if col is None:
                continue
            s = close_df[col].dropna()
            if len(s) < period + 5:
                continue
            df = pd.DataFrame({'Close': s})
            res = backtest_envelope(df, period, pct, stop_loss, take_profit)
            if res['trade_count'] == 0:
                continue
            res['ticker'] = ticker
            res['display_ticker'] = ticker.replace(m['suffix'], '') if m['suffix'] else ticker
            res['display_name'] = get_stock_name(market, ticker)
            res['sector'] = get_sector(market, ticker)
            results.append(res)
        except Exception as e:
            errors.append({"ticker": ticker, "error": str(e)})

    if not results:
        return jsonify({"error": "백테스트 가능한 거래 내역이 없습니다", "errors": errors}), 404

    total_trades = sum(r['trade_count'] for r in results)
    total_wins   = sum(r['win_count']   for r in results)
    avg_return   = float(np.mean([r['total_return'] for r in results]))
    avg_mdd      = float(np.mean([r['mdd']          for r in results]))
    avg_win_rate = float(np.mean([r['win_rate']     for r in results]))
    avg_profit   = float(np.mean([r['avg_profit_pct'] for r in results if r['win_count'] > 0]) or 0)
    avg_loss     = float(np.mean([r['avg_loss_pct']   for r in results if r['loss_count'] > 0]) or 0)

    # 개별 종목 중 상위/하위 수익률
    sorted_by_return = sorted(results, key=lambda x: x['total_return'], reverse=True)
    top5 = sorted_by_return[:5]
    bottom5 = sorted_by_return[-5:]

    aggregated = {
        "market": market,
        "currency": m['currency'],
        "mode": "all",
        "ticker_count": len(results),
        "total_trades": total_trades,
        "total_wins": total_wins,
        "total_losses": total_trades - total_wins,
        "avg_return": round(avg_return, 2),
        "avg_win_rate": round(avg_win_rate, 1),
        "avg_mdd": round(avg_mdd, 2),
        "avg_profit_pct": round(avg_profit, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "params": {"period": period, "pct": pct, "stop_loss": stop_loss,
                   "take_profit": take_profit, "days": days},
        "top5": [{"ticker": r['ticker'], "display_ticker": r['display_ticker'],
                  "display_name": r['display_name'], "sector": r['sector'],
                  "total_return": r['total_return'], "trade_count": r['trade_count'],
                  "win_rate": r['win_rate']} for r in top5],
        "bottom5": [{"ticker": r['ticker'], "display_ticker": r['display_ticker'],
                     "display_name": r['display_name'], "sector": r['sector'],
                     "total_return": r['total_return'], "trade_count": r['trade_count'],
                     "win_rate": r['win_rate']} for r in bottom5],
        "all": [{"ticker": r['ticker'], "display_ticker": r['display_ticker'],
                 "display_name": r['display_name'], "sector": r['sector'],
                 "total_return": r['total_return'], "trade_count": r['trade_count'],
                 "win_rate": r['win_rate'], "mdd": r['mdd']} for r in sorted_by_return],
        "errors": errors[:10],
    }
    return jsonify(aggregated)

# ── 워치리스트 API ────────────────────────────────────────────────────────

@app.route('/api/watchlist', methods=['GET'])
def wl_get():
    with wl_lock:
        return jsonify(list(watchlist.values()))

@app.route('/api/watchlist/add', methods=['POST'])
def wl_add():
    data    = request.get_json(force=True)
    market  = data.get('market','US')
    ticker  = data.get('ticker','').upper().strip()
    period  = int(data.get('period', 20))
    pct     = float(data.get('pct', 5.0))
    if not ticker:
        return jsonify({'error':'티커 없음'}), 400

    m = MARKETS.get(market, {})
    suffix = m.get('suffix','')
    full_ticker = ticker + suffix if suffix and not ticker.endswith(suffix) else ticker

    snap = fetch_snapshot(full_ticker, period, pct)
    if snap is None:
        return jsonify({'error': f'{ticker} 데이터 없음'}), 404

    key = f"{market}:{ticker}"
    entry = {
        "key": key, "market": market, "ticker": full_ticker,
        "display_ticker": ticker,
        "display_name": get_stock_name(market, full_ticker),
        "market_name": m.get('name', market),
        "currency": m.get('currency','USD'),
        "sector": get_sector(market, full_ticker),
        "period": period, "pct": pct,
        "added_at": datetime.now().strftime('%H:%M:%S'),
        "last_signal": snap, "prev_signal": snap['signal'],
        "history": [{"time": snap['updated_at'], "signal": snap['signal'],
                     "close": snap['close'], "pct_from_lower": snap['pct_from_lower']}],
        "alert_count": 0, "active": snap['signal'] != 'NEUTRAL',
        "signal_changed": False,
    }
    with wl_lock:
        watchlist[key] = entry
    return jsonify({'ok': True, 'data': entry})

@app.route('/api/watchlist/remove/<path:key>', methods=['DELETE'])
def wl_remove(key: str):
    with wl_lock:
        watchlist.pop(key, None)
    return jsonify({'ok': True})

@app.route('/api/watchlist/update', methods=['POST'])
def wl_update():
    snap_targets = {}
    with wl_lock:
        for k, v in watchlist.items():
            snap_targets[k] = (v['ticker'], v['period'], v['pct'])

    updated = []
    for key, (ticker, period, pct) in snap_targets.items():
        snap = fetch_snapshot(ticker, period, pct)
        if snap is None:
            continue
        with wl_lock:
            if key not in watchlist:
                continue
            item = watchlist[key]
            prev = item.get('prev_signal', snap['signal'])
            changed = prev != snap['signal']
            if changed:
                item['alert_count'] += 1
                item['history'].append({
                    "time": snap['updated_at'], "signal": snap['signal'],
                    "close": snap['close'], "pct_from_lower": snap['pct_from_lower'],
                })
                item['history'] = item['history'][-30:]
            item['last_signal']    = snap
            item['prev_signal']    = snap['signal']
            item['signal_changed'] = changed
            item['active']         = snap['signal'] != 'NEUTRAL'
            updated.append(dict(item))

    return jsonify({"updated": len(updated), "items": updated})


# ─── 계좌 & 운영 API ──────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _read_json(filename: str) -> dict:
    """로컬 JSON 파일을 읽어 dict 반환. 없거나 파싱 실패 시 {} 반환."""
    path = os.path.join(BASE_DIR, filename)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _mask_secret(s: str, show: int = 4) -> str:
    """민감한 문자열의 앞뒤 일부만 노출하고 나머지는 마스킹"""
    if not s or len(s) <= show * 2:
        return '*' * len(s)
    return s[:show] + '*' * (len(s) - show * 2) + s[-show:]

@app.route('/api/account')
def account_api():
    """dashboard_data.json + runtime_payload.json + config.json + 실제 계좌 요약 통합 반환"""
    dashboard = _read_json('dashboard_data.json')
    runtime   = _read_json('runtime_payload.json')
    cfg       = _read_json('config.json')

    try:
        client = BrokerClient(
            base_url=cfg.get('base_url'),
            api_key=cfg.get('api_key'),
            api_secret=cfg.get('api_secret'),
            account_seq=cfg.get('account_seq'),
        )
        live_account = client.get_account_summary()
    except Exception as e:
        live_account = {'mode': 'error', 'error': str(e)}

    return jsonify({
        "dashboard": dashboard,
        "runtime":   runtime,
        "config": {
            "base_url":    cfg.get('base_url', ''),
            "api_key":     _mask_secret(cfg.get('api_key', '')),
            "api_secret":  _mask_secret(cfg.get('api_secret', '')),
            "account_seq": cfg.get('account_seq', ''),
            "mock_mode":   cfg.get('mock_mode', False),
        },
        "live_account": live_account,
    })

@app.route('/api/save_config', methods=['POST'])
def save_config_api():
    """API 설정 저장 (config.json 갱신)"""
    data = request.get_json(force=True)
    path = os.path.join(BASE_DIR, 'config.json')
    try:
        existing = _read_json('config.json')
        existing.update({k: data[k] for k in ('base_url','api_key','api_secret','mock_mode','account_seq','account_no') if k in data})
        if 'mock_mode' not in data and existing.get('api_key') and existing.get('api_secret'):
            existing['mock_mode'] = False
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return jsonify({"ok": True, "message": "설정이 저장되었습니다."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


if __name__ == '__main__':
    print("🚀 엔벨로프 전략 통합 대시보드 시작 (포트 5050)")
    app.run(host='0.0.0.0', port=5050, debug=False)
