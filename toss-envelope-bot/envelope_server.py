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
    m = MARKETS.get(market)
    if not m:
        return jsonify({"error": "unknown market"}), 404
    period  = int(request.args.get('period', 20))
    pct     = float(request.args.get('pct', 5.0))
    sig_filter = request.args.get('signal', 'ALL')
    limit   = int(request.args.get('limit', 50))

    tickers = get_all_tickers(market)[:60]
    end   = datetime.now()
    start = end - timedelta(days=120)

    results = []
    try:
        raw      = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
        close_df = raw['Close'] if isinstance(raw.columns, pd.MultiIndex) else raw
        for ticker in tickers:
            try:
                col = ticker if ticker in close_df.columns else None
                if col is None:
                    continue
                s = close_df[col].dropna()
                if len(s) < period+5:
                    continue
                df  = pd.DataFrame({'Close': s})
                df  = calc_envelope(df, period, pct)
                sig = get_signal(df, pct)
                if sig['signal'] == 'N/A':
                    continue

                w52_high = float(s.tail(252).max())
                w52_low  = float(s.tail(252).min())
                from_52h = (sig['close'] - w52_high) / w52_high * 100

                # 전일대비
                chg = 0.0
                if len(s) >= 2:
                    chg = (float(s.iloc[-1]) - float(s.iloc[-2])) / float(s.iloc[-2]) * 100

                results.append({
                    "ticker": ticker,
                    "display_ticker": ticker.replace(m['suffix'],'') if m['suffix'] else ticker,
                    "sector": get_sector(market, ticker),
                    "signal": sig['signal'],
                    "strength": sig['strength'],
                    "close":  sig['close'],
                    "ma":     sig['ma'],
                    "upper":  sig['upper'],
                    "lower":  sig['lower'],
                    "pct_from_ma":    sig['pct_from_ma'],
                    "pct_from_lower": sig['pct_from_lower'],
                    "pct_from_upper": sig['pct_from_upper'],
                    "week52_high": round(w52_high, 2),
                    "week52_low":  round(w52_low,  2),
                    "from_52w_high": round(from_52h, 2),
                    "change_1d": round(chg, 2),
                    "currency": m['currency'],
                })
            except Exception:
                continue
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if sig_filter == 'BUY':
        results = [r for r in results if 'BUY'  in r['signal']]
    elif sig_filter == 'SELL':
        results = [r for r in results if 'SELL' in r['signal']]

    results.sort(key=lambda x: x['pct_from_lower'])
    return jsonify({"stocks": results[:limit], "total": len(results), "scanned": len(tickers), "market": market})

# 차트 데이터
@app.route('/api/chart/<market>/<ticker>')
def chart_data(market: str, ticker: str):
    m = MARKETS.get(market)
    if not m:
        return jsonify({"error":"unknown market"}), 404
    days   = int(request.args.get('days', 180))
    period = int(request.args.get('period', 20))
    pct    = float(request.args.get('pct', 5.0))

    end   = datetime.now()
    start = end - timedelta(days=days + period*2)
    try:
        df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
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
        return jsonify({"ticker": ticker, "market": market,
                        "currency": m['currency'], "ohlc": ohlc, "signal": sig})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 백테스트
@app.route('/api/backtest/<market>/<ticker>')
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
    try:
        df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        if df.empty:
            return jsonify({"error":"No data"}), 404
        result = backtest_envelope(df[['Close']].copy(), period, pct, stop_loss, take_profit)
        result.update({"ticker": ticker, "market": market, "currency": m['currency'],
                       "params": {"period":period,"pct":pct,"stop_loss":stop_loss,
                                  "take_profit":take_profit,"days":days}})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

@app.route('/api/account')
def account_api():
    """dashboard_data.json + runtime_payload.json + config.json 통합 반환"""
    dashboard = _read_json('dashboard_data.json')
    runtime   = _read_json('runtime_payload.json')
    cfg       = _read_json('config.json')
    return jsonify({
        "dashboard": dashboard,
        "runtime":   runtime,
        "config": {
            "base_url":   cfg.get('base_url', ''),
            "api_key":    cfg.get('api_key', ''),
            "api_secret": cfg.get('api_secret', ''),
            "mock_mode":  cfg.get('mock_mode', False),
        }
    })

@app.route('/api/save_config', methods=['POST'])
def save_config_api():
    """API 설정 저장 (config.json 갱신)"""
    data = request.get_json(force=True)
    path = os.path.join(BASE_DIR, 'config.json')
    try:
        existing = _read_json('config.json')
        existing.update({k: data[k] for k in ('base_url','api_key','api_secret','mock_mode') if k in data})
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return jsonify({"ok": True, "message": "설정이 저장되었습니다."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


if __name__ == '__main__':
    print("🚀 엔벨로프 전략 통합 대시보드 시작 (포트 5050)")
    app.run(host='0.0.0.0', port=5050, debug=False)
