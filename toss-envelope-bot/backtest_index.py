"""
실시간 지수 구성종목 대상 엔벨로프 백테스트
- S&P500 (US): MA20 / 밴드±10% / 익절 15% / 손절 6.5%
- KOSPI200 + KOSDAQ150 (KR): MA20 / 밴드±20% / 익절 8% / 손절 7%

결과:
- 각 시장 상위 N종목 샘플 백테스트
- 평균 수익률 / 평균 승률 / 평균 거래수 / 평균 MDD 출력
"""

import sys, io, random, time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from bs4 import BeautifulSoup

# ── 파라미터 (이전 세션 백테스트 최적값) ──────────────────────────────
US_PARAMS = {'period': 20, 'pct': 10.0, 'tp': 15.0, 'sl': 6.5}
KR_PARAMS = {'period': 20, 'pct': 20.0, 'tp':  8.0, 'sl': 7.0}

BACKTEST_YEARS = 2      # 백테스트 기간
US_SAMPLE  = 30         # S&P500에서 샘플링할 종목수
KR_SAMPLE  = 30         # KOSPI200+KOSDAQ150에서 샘플링할 종목수

# ── 종목 수집 함수 ─────────────────────────────────────────────────────

def fetch_sp500() -> list:
    url = ('https://raw.githubusercontent.com/datasets/'
           's-and-p-500-companies/main/data/constituents.csv')
    r = requests.get(url, timeout=15)
    df = pd.read_csv(io.StringIO(r.text))
    symbols = df['Symbol'].str.replace('.', '-', regex=False).tolist()
    print(f"  S&P500: {len(symbols)}개 로드")
    return symbols

def fetch_naver_index(list_type: str, suffix: str, max_pages: int = 22) -> list:
    NAVER_URL = 'https://finance.naver.com/sise/entryJongmok.naver'
    HDRS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'}
    all_codes = []
    for page in range(1, max_pages + 1):
        url = f'{NAVER_URL}?kospiListType={list_type}&page={page}'
        r = requests.get(url, headers=HDRS, timeout=10)
        r.encoding = 'euc-kr'
        soup = BeautifulSoup(r.text, 'html.parser')
        found = []
        for a in soup.find_all('a', href=True):
            h = a['href']
            if 'code=' in h:
                c = h.split('code=')[-1][:6]
                if c.isdigit() and len(c) == 6:
                    found.append(c)
        if not found:
            break
        all_codes.extend(found)
    unique = list(dict.fromkeys(all_codes))
    tickers = [c + suffix for c in unique]
    print(f"  {list_type}: {len(tickers)}개 로드")
    return tickers

# ── 엔벨로프 백테스트 함수 ─────────────────────────────────────────────

def calc_envelope(df, period, pct):
    df = df.copy()
    df['MA']    = df['Close'].rolling(period).mean()
    df['Upper'] = df['MA'] * (1 + pct / 100)
    df['Lower'] = df['MA'] * (1 - pct / 100)
    return df

def backtest(df, period, pct, tp, sl):
    df = calc_envelope(df, period, pct).dropna()
    capital = 10_000_000
    cash, shares, entry = capital, 0, None
    trades = []

    for i, row in df.iterrows():
        price = float(row['Close'])
        lower = float(row['Lower'])
        upper = float(row['Upper'])
        if pd.isna(lower) or pd.isna(upper) or price <= 0:
            continue

        if shares == 0 and price <= lower:
            shares = int(cash * 0.95 / price)
            if shares > 0:
                entry = price
                cash -= shares * price

        elif shares > 0 and entry is not None:
            pnl = (price - entry) / entry * 100
            if pnl >= tp or pnl <= -sl:
                cash += shares * price
                trades.append(pnl)
                shares = 0
                entry = None

    if shares > 0:
        cash += shares * float(df['Close'].iloc[-1])

    total_return = (cash - capital) / capital * 100
    wins = [t for t in trades if t > 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    trade_count = len(trades)

    # MDD 계산
    equity = [capital]
    c2, s2, e2 = capital, 0, None
    for _, row in df.iterrows():
        p = float(row['Close'])
        l = float(row['Lower'])
        u = float(row['Upper'])
        if pd.isna(l) or pd.isna(u) or p <= 0:
            equity.append(equity[-1])
            continue
        if s2 == 0 and p <= l:
            s2 = int(c2 * 0.95 / p)
            if s2 > 0:
                e2 = p
                c2 -= s2 * p
        elif s2 > 0 and e2:
            pnl = (p - e2) / e2 * 100
            if pnl >= tp or pnl <= -sl:
                c2 += s2 * p
                s2 = 0
                e2 = None
        val = c2 + s2 * p if s2 > 0 else c2
        equity.append(val)

    eq = np.array(equity)
    peak = np.maximum.accumulate(eq)
    drawdown = (eq - peak) / peak * 100
    mdd = abs(drawdown.min())

    return {
        'total_return': round(total_return, 2),
        'win_rate':     round(win_rate, 1),
        'trade_count':  trade_count,
        'mdd':          round(mdd, 2),
    }

def run_market_backtest(tickers, params, market_name, n_sample):
    """랜덤 샘플 n_sample개 백테스트 후 집계"""
    random.seed(42)
    if len(tickers) > n_sample:
        sample = random.sample(tickers, n_sample)
    else:
        sample = tickers

    results = []
    ok_count = 0
    fail_count = 0
    period_str = f"{BACKTEST_YEARS}y"

    print(f"\n{'='*55}")
    print(f"  {market_name}  —  {len(sample)}종목 샘플 백테스트")
    print(f"  기간: 최근 {BACKTEST_YEARS}년 | 밴드: ±{params['pct']}%"
          f" | 익절: {params['tp']}% | 손절: {params['sl']}%")
    print(f"{'='*55}")

    for i, ticker in enumerate(sample, 1):
        try:
            df = yf.download(ticker, period=period_str, interval='1d',
                             auto_adjust=True, progress=False)
            if df.empty or len(df) < 30:
                fail_count += 1
                continue
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df.rename(columns=str.title)
            df.index = pd.to_datetime(df.index)

            r = backtest(df, params['period'], params['pct'], params['tp'], params['sl'])
            results.append(r)
            ok_count += 1

            bar = '█' * int((r['total_return'] + 50) / 10) if r['total_return'] > -50 else ''
            sign = '+' if r['total_return'] >= 0 else ''
            print(f"  [{i:2d}] {ticker:<12} | "
                  f"수익: {sign}{r['total_return']:6.1f}% | "
                  f"승률: {r['win_rate']:4.1f}% | "
                  f"거래: {r['trade_count']:3d}회 | "
                  f"MDD: {r['mdd']:5.1f}%")
        except Exception as e:
            fail_count += 1
            print(f"  [{i:2d}] {ticker:<12} | 실패: {e}")
        time.sleep(0.2)

    if not results:
        print("  (결과 없음)")
        return None

    df_r = pd.DataFrame(results)
    avg = {
        'total_return': df_r['total_return'].mean(),
        'win_rate':     df_r['win_rate'].mean(),
        'trade_count':  df_r['trade_count'].mean(),
        'mdd':          df_r['mdd'].mean(),
        'positive_rate': (df_r['total_return'] > 0).mean() * 100,
        'ok_count':     ok_count,
        'fail_count':   fail_count,
    }

    print(f"\n  ─ 집계 결과 ({ok_count}종목) ─")
    sign = '+' if avg['total_return'] >= 0 else ''
    print(f"  평균 수익률:  {sign}{avg['total_return']:.2f}%")
    print(f"  수익 종목률: {avg['positive_rate']:.1f}%")
    print(f"  평균 승률:   {avg['win_rate']:.1f}%")
    print(f"  평균 거래수: {avg['trade_count']:.1f}회")
    print(f"  평균 MDD:    {avg['mdd']:.2f}%")
    print(f"  로드 실패:   {fail_count}종목")
    return avg


def main():
    print("=" * 55)
    print("  실시간 지수 구성종목 엔벨로프 백테스트")
    print("=" * 55)

    # ── 종목 수집 ──────────────────────────────────────────
    print("\n[1단계] 지수 구성종목 수집 중...")
    sp500   = fetch_sp500()
    kospi200  = fetch_naver_index('kospi200',  '.KS')
    kosdaq150 = fetch_naver_index('kosdaq150', '.KQ')
    kr_all  = kospi200 + kosdaq150
    kr_all  = list(dict.fromkeys(kr_all))
    print(f"\n  합산: US={len(sp500)}개 | KR={len(kr_all)}개"
          f" (KOSPI200:{len(kospi200)} + KOSDAQ150:{len(kosdaq150)})")

    # ── 백테스트 ───────────────────────────────────────────
    print("\n[2단계] 백테스트 실행...")

    us_avg = run_market_backtest(sp500,  US_PARAMS, "🇺🇸 S&P500",        US_SAMPLE)
    kr_avg = run_market_backtest(kr_all, KR_PARAMS, "🇰🇷 KOSPI200+KOSDAQ150", KR_SAMPLE)

    # ── 최종 요약 ──────────────────────────────────────────
    print()
    print("=" * 55)
    print("  최종 요약")
    print("=" * 55)

    for name, avg, params in [
        ("🇺🇸 S&P500 (US)",           us_avg, US_PARAMS),
        ("🇰🇷 KOSPI200+KOSDAQ150 (KR)", kr_avg, KR_PARAMS),
    ]:
        if avg is None:
            continue
        sign = '+' if avg['total_return'] >= 0 else ''
        print(f"\n  {name}")
        print(f"    파라미터  : MA{params['period']} / 밴드±{params['pct']}%"
              f" / 익절 {params['tp']}% / 손절 {params['sl']}%")
        print(f"    평균 수익 : {sign}{avg['total_return']:.2f}%")
        print(f"    수익 종목 : {avg['positive_rate']:.1f}%")
        print(f"    평균 승률 : {avg['win_rate']:.1f}%")
        print(f"    평균 거래 : {avg['trade_count']:.1f}회/종목")
        print(f"    평균 MDD  : {avg['mdd']:.2f}%")

    print()
    print("=" * 55)
    print("  ✅ 백테스트 완료")
    print("=" * 55)


if __name__ == '__main__':
    main()
