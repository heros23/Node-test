"""
실제 지수 구성종목 대상 KR 파라미터 재최적화
- 밴드 폭을 5~25% 범위에서 탐색
- 실제 KOSPI200+KOSDAQ150 샘플 사용
"""
import io, random, time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from bs4 import BeautifulSoup

KR_SAMPLE = 20      # 종목수

def fetch_naver_index(list_type, suffix, max_pages=22):
    NAVER_URL = 'https://finance.naver.com/sise/entryJongmok.naver'
    HDRS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'}
    all_codes = []
    for page in range(1, max_pages+1):
        url = f'{NAVER_URL}?kospiListType={list_type}&page={page}'
        r = requests.get(url, headers=HDRS, timeout=10)
        r.encoding = 'euc-kr'
        soup = BeautifulSoup(r.text, 'html.parser')
        found = []
        for a in soup.find_all('a', href=True):
            h = a['href']
            if 'code=' in h:
                c = h.split('code=')[-1][:6]
                if c.isdigit() and len(c)==6:
                    found.append(c)
        if not found:
            break
        all_codes.extend(found)
    return [c+suffix for c in list(dict.fromkeys(all_codes))]

def calc_envelope(df, period, pct):
    df = df.copy()
    df['MA']    = df['Close'].rolling(period).mean()
    df['Upper'] = df['MA'] * (1 + pct/100)
    df['Lower'] = df['MA'] * (1 - pct/100)
    return df

def backtest(df, period, pct, tp, sl):
    df = calc_envelope(df, period, pct).dropna()
    capital = 10_000_000
    cash, shares, entry = capital, 0, None
    trades = []
    equity = [capital]

    for _, row in df.iterrows():
        p = float(row['Close'])
        l, u = float(row['Lower']), float(row['Upper'])
        if pd.isna(l) or p <= 0:
            equity.append(equity[-1])
            continue
        if shares == 0 and p <= l:
            shares = int(cash*0.95/p)
            if shares > 0:
                entry = p
                cash -= shares*p
        elif shares > 0 and entry:
            pnl = (p-entry)/entry*100
            if pnl >= tp or pnl <= -sl:
                cash += shares*p
                trades.append(pnl)
                shares = 0; entry = None
        val = cash + shares*p if shares > 0 else cash
        equity.append(val)

    if shares > 0:
        cash += shares * float(df['Close'].iloc[-1])

    total_return = (cash - capital) / capital * 100
    wins = [t for t in trades if t > 0]
    win_rate = len(wins)/len(trades)*100 if trades else 0
    trade_count = len(trades)

    eq = np.array(equity)
    peak = np.maximum.accumulate(eq)
    mdd = abs(((eq - peak)/peak*100).min())

    score = total_return * (win_rate/100+0.01) * (1 + trade_count/10) - mdd*0.5
    return {'total_return': total_return, 'win_rate': win_rate,
            'trade_count': trade_count, 'mdd': mdd, 'score': score}

def avg_backtest(tickers, period, pct, tp, sl):
    results = []
    for tk in tickers:
        try:
            df = yf.download(tk, period='2y', interval='1d',
                             auto_adjust=True, progress=False)
            if df.empty or len(df) < 30:
                continue
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df.rename(columns=str.title)
            r = backtest(df, period, pct, tp, sl)
            if r['trade_count'] > 0:
                results.append(r)
        except:
            pass
        time.sleep(0.1)
    if not results:
        return None
    dfr = pd.DataFrame(results)
    return {
        'total_return': dfr['total_return'].mean(),
        'win_rate':     dfr['win_rate'].mean(),
        'trade_count':  dfr['trade_count'].mean(),
        'mdd':          dfr['mdd'].mean(),
        'score':        dfr['score'].mean(),
    }

def main():
    print("=" * 60)
    print("  KR 실제 구성종목 파라미터 최적화")
    print("=" * 60)

    print("\n[1] 종목 수집...")
    kospi = fetch_naver_index('kospi200',  '.KS')
    kosdaq = fetch_naver_index('kosdaq150', '.KQ')
    kr_all = list(dict.fromkeys(kospi + kosdaq))
    print(f"  KOSPI200: {len(kospi)}, KOSDAQ150: {len(kosdaq)}, 합: {len(kr_all)}")

    random.seed(42)
    sample = random.sample(kr_all, min(KR_SAMPLE, len(kr_all)))
    print(f"  샘플: {len(sample)}종목")

    print("\n[2] 1차 탐색 (밴드 5~25%, 1% 간격)...")
    print(f"  {'밴드':>5} {'익절':>5} {'손절':>5} | {'수익':>7} {'승률':>6} {'거래':>5} {'MDD':>6} {'점수':>8}")
    print("  " + "-"*57)

    pct_candidates  = [5, 8, 10, 12, 15, 18, 20]
    tp_sl_pairs = [(6,4),(8,5),(10,5),(12,6),(15,7),(8,7),(10,7)]
    best1 = None

    for pct in pct_candidates:
        for tp, sl in tp_sl_pairs:
            r = avg_backtest(sample, 20, pct, tp, sl)
            if r is None:
                continue
            mark = ' ◀' if (best1 is None or r['score'] > best1['score']) else ''
            if best1 is None or r['score'] > best1['score']:
                best1 = {'pct': pct, 'tp': tp, 'sl': sl, **r}
            sign = '+' if r['total_return'] >= 0 else ''
            print(f"  ±{pct:4.0f}% | tp={tp:2d}% sl={sl:2d}% | "
                  f"{sign}{r['total_return']:6.2f}% | "
                  f"{r['win_rate']:5.1f}% | {r['trade_count']:4.1f}회 | "
                  f"{r['mdd']:5.2f}% | {r['score']:7.2f}{mark}")

    if best1:
        print(f"\n  ★ 1차 최적: 밴드±{best1['pct']}% / 익절{best1['tp']}% / 손절{best1['sl']}%"
              f" (점수 {best1['score']:.2f})")

        print("\n[3] 2차 세밀 탐색 (±0.5% 간격)...")
        base_pct = best1['pct']
        base_tp  = best1['tp']
        base_sl  = best1['sl']
        best2 = best1.copy()

        for pct in [base_pct-1, base_pct-0.5, base_pct, base_pct+0.5, base_pct+1]:
            for tp in [base_tp-1, base_tp-0.5, base_tp, base_tp+0.5, base_tp+1]:
                for sl in [base_sl-1, base_sl-0.5, base_sl, base_sl+0.5, base_sl+1]:
                    if pct < 3 or tp < 3 or sl < 2:
                        continue
                    r = avg_backtest(sample, 20, pct, tp, sl)
                    if r is None:
                        continue
                    if r['score'] > best2['score']:
                        best2 = {'pct': pct, 'tp': tp, 'sl': sl, **r}

        print(f"\n  ★ 최종 최적값:")
        print(f"     밴드: ±{best2['pct']}%")
        print(f"     익절: {best2['tp']}%")
        print(f"     손절: {best2['sl']}%")
        sign = '+' if best2['total_return'] >= 0 else ''
        print(f"     수익: {sign}{best2['total_return']:.2f}%")
        print(f"     승률: {best2['win_rate']:.1f}%")
        print(f"     거래: {best2['trade_count']:.1f}회/종목")
        print(f"     MDD:  {best2['mdd']:.2f}%")
        print(f"     점수: {best2['score']:.2f}")

        return best2

if __name__ == '__main__':
    main()
