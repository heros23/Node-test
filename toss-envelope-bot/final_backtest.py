"""
최종 통합 백테스트 — 실제 지수 구성종목 대상
- US  (S&P500)           : MA20 / 밴드±10% / 익절 15% / 손절 6.5%
- KR  (KOSPI200+KOSDAQ150): MA20 / 밴드± 5% / 익절  8% / 손절 7%
- 각 시장 20종목 고정 샘플 (seed=42)
"""
import io, random, time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from bs4 import BeautifulSoup

US_PARAMS = {'period': 20, 'pct': 10.0, 'tp': 15.0, 'sl': 6.5}
KR_PARAMS = {'period': 20, 'pct':  5.0, 'tp':  8.0, 'sl': 7.0}
SAMPLE_N  = 20

def fetch_sp500():
    url = ('https://raw.githubusercontent.com/datasets/'
           's-and-p-500-companies/main/data/constituents.csv')
    r = requests.get(url, timeout=15)
    df = pd.read_csv(io.StringIO(r.text))
    return df['Symbol'].str.replace('.', '-', regex=False).tolist()

def fetch_naver(list_type, suffix, max_pages=22):
    HDRS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'}
    codes = []
    for pg in range(1, max_pages+1):
        url = f'https://finance.naver.com/sise/entryJongmok.naver?kospiListType={list_type}&page={pg}'
        r = requests.get(url, headers=HDRS, timeout=10)
        r.encoding = 'euc-kr'
        soup = BeautifulSoup(r.text, 'html.parser')
        found = [a['href'].split('code=')[-1][:6]
                 for a in soup.find_all('a', href=True)
                 if 'code=' in a['href'] and a['href'].split('code=')[-1][:6].isdigit()]
        if not found: break
        codes.extend(found)
    return [c+suffix for c in list(dict.fromkeys(codes))]

def calc_envelope(df, period, pct):
    df = df.copy()
    df['MA'] = df['Close'].rolling(period).mean()
    df['Upper'] = df['MA'] * (1 + pct/100)
    df['Lower'] = df['MA'] * (1 - pct/100)
    return df

def backtest(df, p):
    df = calc_envelope(df, p['period'], p['pct']).dropna()
    capital = 10_000_000
    cash, shares, entry = capital, 0, None
    trades = []
    equity = [capital]

    for _, row in df.iterrows():
        price = float(row['Close'])
        lower, upper = float(row['Lower']), float(row['Upper'])
        if pd.isna(lower) or price <= 0:
            equity.append(equity[-1]); continue

        if shares == 0 and price <= lower:
            shares = int(cash * 0.95 / price)
            if shares > 0:
                entry = price
                cash -= shares * price
        elif shares > 0 and entry:
            pnl = (price - entry) / entry * 100
            if pnl >= p['tp'] or pnl <= -p['sl']:
                cash += shares * price
                trades.append(pnl)
                shares, entry = 0, None

        equity.append(cash + shares * price if shares > 0 else cash)

    if shares > 0:
        cash += shares * float(df['Close'].iloc[-1])

    total_ret = (cash - capital) / capital * 100
    wins = [t for t in trades if t > 0]
    win_rate = len(wins)/len(trades)*100 if trades else 0
    eq = np.array(equity)
    peak = np.maximum.accumulate(eq)
    mdd = abs(((eq-peak)/peak*100).min())
    return {'total_return': round(total_ret,2), 'win_rate': round(win_rate,1),
            'trade_count': len(trades), 'mdd': round(mdd,2)}

def run_bt(tickers, params, label):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  MA{params['period']} / 밴드±{params['pct']}% / 익절{params['tp']}% / 손절{params['sl']}%")
    print(f"{'='*60}")

    results = []
    fail = 0
    for i, tk in enumerate(tickers, 1):
        try:
            df = yf.download(tk, period='2y', interval='1d',
                             auto_adjust=True, progress=False)
            if df.empty or len(df) < 30:
                fail += 1; continue
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df.rename(columns=str.title)
            r = backtest(df, params)
            results.append(r)
            s = '+' if r['total_return'] >= 0 else ''
            print(f"  [{i:2d}] {tk:<14} | {s}{r['total_return']:6.1f}% | "
                  f"승률 {r['win_rate']:4.1f}% | {r['trade_count']:3d}회 | MDD {r['mdd']:5.1f}%")
        except Exception as e:
            fail += 1
            print(f"  [{i:2d}] {tk:<14} | 실패: {str(e)[:40]}")
        time.sleep(0.15)

    if not results:
        print("  (결과 없음)")
        return None
    dr = pd.DataFrame(results)
    avg = {k: round(dr[k].mean(), 2) for k in ['total_return','win_rate','trade_count','mdd']}
    pos_rate = round((dr['total_return'] > 0).mean() * 100, 1)
    print(f"\n  ─── 집계 ({len(results)}종목, 실패 {fail}종목) ───")
    s = '+' if avg['total_return'] >= 0 else ''
    print(f"  평균 수익:  {s}{avg['total_return']}%")
    print(f"  수익 종목: {pos_rate}%")
    print(f"  평균 승률: {avg['win_rate']}%")
    print(f"  평균 거래: {avg['trade_count']}회/종목")
    print(f"  평균 MDD:  {avg['mdd']}%")
    return {**avg, 'pos_rate': pos_rate, 'count': len(results)}

print("="*60)
print("  최종 통합 백테스트 — 실제 지수 구성종목")
print("="*60)

print("\n[1] 종목 수집...")
sp500   = fetch_sp500()
kospi   = fetch_naver('kospi200',  '.KS')
kosdaq  = fetch_naver('kosdaq150', '.KQ')
kr_all  = list(dict.fromkeys(kospi + kosdaq))
print(f"  S&P500: {len(sp500)} | KOSPI200: {len(kospi)} | KOSDAQ150: {len(kosdaq)} | KR합: {len(kr_all)}")

random.seed(42)
us_sample = random.sample(sp500,  min(SAMPLE_N, len(sp500)))
kr_sample = random.sample(kr_all, min(SAMPLE_N, len(kr_all)))

print(f"\n[2] 백테스트 (각 {SAMPLE_N}종목 샘플)...")
us_avg = run_bt(us_sample, US_PARAMS, "🇺🇸 S&P500 (US)")
kr_avg = run_bt(kr_sample, KR_PARAMS, "🇰🇷 KOSPI200 + KOSDAQ150 (KR)")

print()
print("="*60)
print("  ■ 최종 확정 파라미터 및 결과 요약")
print("="*60)

for name, avg, p, idx in [
    ("🇺🇸 S&P500 (US)",            us_avg, US_PARAMS, f"{len(sp500)}개"),
    ("🇰🇷 KOSPI200+KOSDAQ150 (KR)", kr_avg, KR_PARAMS, f"{len(kr_all)}개 ({len(kospi)}+{len(kosdaq)})"),
]:
    if avg is None: continue
    s = '+' if avg['total_return'] >= 0 else ''
    print(f"""
  {name}  [{idx}]
    전략 파라미터  : MA{p['period']} / 밴드 ±{p['pct']}% / 익절 {p['tp']}% / 손절 {p['sl']}%
    평균 수익률   : {s}{avg['total_return']:.2f}%
    수익 종목 비율: {avg['pos_rate']:.1f}%
    평균 승률     : {avg['win_rate']:.1f}%
    평균 거래 횟수: {avg['trade_count']:.1f}회/종목
    평균 MDD      : {avg['mdd']:.2f}%""")

print()
print("="*60)
print("  ✅ 백테스트 완료 — 위 파라미터가 envelope_server.py에 적용됨")
print("="*60)
