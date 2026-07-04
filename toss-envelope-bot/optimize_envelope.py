#!/usr/bin/env python3
"""
엔벨로프 최적 익절/손절 탐색 (고속 버전)
- US  : MA20, 밴드 ±10%
- KR  : MA20, 밴드 ±20%
- 탐색: take_profit 3~15%(1% 간격), stop_loss 2~7%(1% 간격) → 조합 수 축소
"""
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

import yfinance as yf
import pandas as pd
import numpy as np
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed
from envelope_server import calc_envelope, backtest_envelope

# ── 종목 ─────────────────────────────────────────────────────────────────
US_TICKERS = ["AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","JPM","V","UNH"]
KR_TICKERS = [
    "005930.KS","000660.KS","005380.KS","035420.KS","000270.KS",
    "068270.KS","247540.KQ","035900.KQ","028300.KQ","086520.KQ",
]

PERIOD = "3y"

# ── 탐색 범위 (1% 간격으로 축소) ─────────────────────────────────────────
TP_RANGE = list(range(3, 16, 1))    # 3~15%  (13개)
SL_RANGE = list(range(2,  8, 1))    # 2~7%   (6개)
# 유효 조합: tp > sl → 최대 13×6 = 78개 → 빠름

def download(ticker_str):
    try:
        df = yf.download(ticker_str, period=PERIOD, interval="1d",
                         auto_adjust=True, progress=False)
        if df.empty or len(df) < 60: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df.dropna(subset=['Close'], inplace=True)
        return df
    except: return None

def score(res):
    tr  = res.get('total_return', 0)
    wr  = res.get('win_rate', 0)
    tc  = res.get('trade_count', 0)
    mdd = abs(res.get('mdd', 0))
    if tc < 3: return -9999
    return tr * (wr / 100) * (1 + tc / 30) - mdd * 0.5

def run_combo(dfs, pct, tp, sl):
    if tp <= sl: return (tp, sl), None
    sc_list, tr_list, wr_list, tc_list, mdd_list = [], [], [], [], []
    for df in dfs:
        try:
            res = backtest_envelope(df.copy(), period=20, pct=pct,
                                    stop_loss=sl, take_profit=tp)
            sc_list.append(score(res))
            tr_list.append(res.get('total_return', 0))
            wr_list.append(res.get('win_rate', 0))
            tc_list.append(res.get('trade_count', 0))
            mdd_list.append(abs(res.get('mdd', 0)))
        except: pass
    if not sc_list: return (tp, sl), None
    return (tp, sl), {
        'score':      float(np.mean(sc_list)),
        'avg_return': round(float(np.mean(tr_list)), 2),
        'avg_wr':     round(float(np.mean(wr_list)), 1),
        'avg_tc':     round(float(np.mean(tc_list)), 1),
        'avg_mdd':    round(float(np.mean(mdd_list)), 2),
    }

def optimize(tickers, pct, market_name):
    print(f"\n{'='*62}")
    print(f"  [{market_name}]  MA20 / 밴드±{pct}%  |  종목 {len(tickers)}개")
    print(f"{'='*62}")

    # 병렬 데이터 다운로드
    dfs = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(download, t): t for t in tickers}
        for fut in as_completed(futs):
            df = fut.result()
            if df is not None:
                dfs.append(df)
                print(f"  ✓ {futs[fut]:15s} ({len(df)}행)")
            else:
                print(f"  ✗ {futs[fut]:15s} 데이터 없음")

    if not dfs:
        print("  데이터 없음"); return None

    combos = [(tp, sl) for tp, sl in product(TP_RANGE, SL_RANGE) if tp > sl]
    print(f"\n  유효 종목 {len(dfs)}개 × {len(combos)}조합 탐색 중...")

    results = {}
    # 백테스트는 순차 (GIL 때문에 threading 효과 없음)
    for i, (tp, sl) in enumerate(combos):
        key, val = run_combo(dfs, pct, tp, sl)
        if val: results[key] = val
        if (i+1) % 20 == 0:
            print(f"  ... {i+1}/{len(combos)} 완료")

    if not results: print("  결과 없음"); return None

    top10 = sorted(results.items(), key=lambda x: x[1]['score'], reverse=True)[:10]

    print(f"\n  ┌─ 상위 10개 조합 ──────────────────────────────────────────┐")
    print(f"  │ {'순위':>3}  {'익절':>5}  {'손절':>5}  {'수익률':>8}  {'승률':>6}  {'거래':>5}  {'MDD':>7} │")
    print(f"  ├───────────────────────────────────────────────────────────┤")
    for rank, ((tp, sl), d) in enumerate(top10, 1):
        print(f"  │ {rank:>3}위  {tp:>4d}%  {sl:>4d}%  "
              f"{d['avg_return']:>+7.2f}%  {d['avg_wr']:>5.1f}%  "
              f"{d['avg_tc']:>4.1f}회  {d['avg_mdd']:>6.2f}% │")
    print(f"  └───────────────────────────────────────────────────────────┘")

    best_tp, best_sl = top10[0][0]
    best_d = top10[0][1]
    print(f"\n  🏆 최적: 익절 {best_tp}% / 손절 {best_sl}%")
    print(f"     수익률 {best_d['avg_return']:+.2f}% | 승률 {best_d['avg_wr']:.1f}% "
          f"| 거래 {best_d['avg_tc']:.1f}회 | MDD {best_d['avg_mdd']:.2f}%")

    return {'tp': best_tp, 'sl': best_sl, 'pct': pct, **best_d}

if __name__ == '__main__':
    print("\n🔍 엔벨로프 최적 파라미터 탐색  (기간: 3년)")
    us = optimize(US_TICKERS, pct=10.0, market_name="US  밴드±10%")
    kr = optimize(KR_TICKERS, pct=20.0, market_name="KR  밴드±20%")

    print(f"\n{'='*62}")
    print("  📊 최종 결과")
    print(f"{'='*62}")
    if us: print(f"  🇺🇸 US  → MA20 / 밴드±10% / 익절 {us['tp']}% / 손절 {us['sl']}%")
    if kr: print(f"  🇰🇷 KR  → MA20 / 밴드±20% / 익절 {kr['tp']}% / 손절 {kr['sl']}%")
    print()
