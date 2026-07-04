#!/usr/bin/env python3
"""
5개 전략 백테스트 매매빈도 측정 스크립트
- run_backtest() 반환 키: trade_count (num_trades 아님)
- 기간: 2년 (period='2y') → 거래 횟수 충분히 확보
- 종목: US 5개 + KOSPI 5개 + KOSDAQ 5개 = 15개
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from collections import defaultdict

# envelope_server에서 필요한 함수만 임포트
from envelope_server import run_backtest, MARKETS

# ── 테스트 종목 (시장별 5개) ─────────────────────────────────
TEST_TICKERS = {
    "US": ["AAPL", "MSFT", "NVDA", "GOOGL", "META"],
    "KOSPI": [
        ("005930", ".KS"),  # 삼성전자
        ("000660", ".KS"),  # SK하이닉스
        ("005380", ".KS"),  # 현대차
        ("035420", ".KS"),  # NAVER
        ("000270", ".KS"),  # 기아
    ],
    "KOSDAQ": [
        ("247540", ".KQ"),  # 에코프로비엠
        ("091990", ".KQ"),  # 셀트리온헬스케어
        ("035900", ".KQ"),  # JYP엔터
        ("028300", ".KQ"),  # HLB
        ("086520", ".KQ"),  # 에코프로
    ],
}

STRATEGIES = ["ENVELOPE", "TBV_SMC", "BB3SIGMA", "PIVOT_VA", "SSL_RSI"]
PERIOD = "2y"   # 2년치 일봉

# ── 데이터 수집 ───────────────────────────────────────────────
def download_df(ticker_str: str) -> pd.DataFrame | None:
    try:
        df = yf.download(ticker_str, period=PERIOD, interval="1d",
                         auto_adjust=True, progress=False)
        if df.empty:
            return None
        # MultiIndex 정리
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df.dropna(subset=['Close'], inplace=True)
        return df
    except Exception as e:
        print(f"  [download error] {ticker_str}: {e}")
        return None

# ── 메인 측정 ─────────────────────────────────────────────────
results: dict[str, list[int]] = defaultdict(list)   # strategy → [trade_count, ...]
errors: dict[str, int] = defaultdict(int)

print(f"\n{'='*60}")
print(f"  백테스트 매매빈도 측정  |  기간: {PERIOD}  |  종목: 15개")
print(f"{'='*60}\n")

total_tickers = 0

for market, tickers in TEST_TICKERS.items():
    suffix = MARKETS.get(market, {}).get("suffix", "")
    print(f"── {market} ({'US' if market=='US' else ('KS' if market=='KOSPI' else 'KQ')}) ──")

    for item in tickers:
        if isinstance(item, tuple):
            base, suf = item
            ticker_dl = base + suf
            label = base
        else:
            ticker_dl = item
            label = item

        df = download_df(ticker_dl)
        if df is None or len(df) < 30:
            print(f"  {label:10s} : 데이터 부족 ({len(df) if df is not None else 0}행) — 스킵")
            for s in STRATEGIES:
                errors[s] += 1
            continue

        total_tickers += 1
        row_info = f"  {label:10s} ({len(df)}행): "
        counts = []

        for strategy in STRATEGIES:
            try:
                res = run_backtest(df.copy(), strategy, {})
                tc = res.get("trade_count", res.get("num_trades", 0)) if isinstance(res, dict) else 0
                results[strategy].append(tc)
                counts.append(f"{strategy}={tc}")
            except Exception as e:
                errors[strategy] += 1
                results[strategy].append(0)
                counts.append(f"{strategy}=ERR({e.__class__.__name__})")

        print(row_info + " | ".join(counts))

# ── 집계 ──────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  집계 결과  (유효 종목 {total_tickers}개)")
print(f"{'='*60}")

summary = []
for strategy in STRATEGIES:
    vals = results[strategy]
    if not vals:
        avg, med = 0.0, 0.0
    else:
        avg = float(np.mean(vals))
        med = float(np.median(vals))
    summary.append({
        "strategy": strategy,
        "avg": avg,
        "median": med,
        "max": max(vals) if vals else 0,
        "min": min(vals) if vals else 0,
        "total": sum(vals),
        "samples": len(vals),
        "errors": errors[strategy],
    })

summary.sort(key=lambda x: x["avg"], reverse=True)

header = f"{'순위':<4} {'전략':<12} {'평균거래수':>9} {'중앙값':>7} {'최대':>5} {'최소':>5} {'합계':>6} {'샘플':>5}"
print(f"\n{header}")
print("-" * len(header))

medals = ["🥇", "🥈", "🥉", "  4", "  5"]
for i, row in enumerate(summary):
    print(
        f"{medals[i]} "
        f"{row['strategy']:<12} "
        f"{row['avg']:>8.1f}회 "
        f"{row['median']:>6.1f}회 "
        f"{row['max']:>5d} "
        f"{row['min']:>5d} "
        f"{row['total']:>6d} "
        f"({row['samples']}개)"
    )

print(f"\n{'='*60}")
print("  매매빈도 높은 순 (최종)")
print(f"{'='*60}")
for i, row in enumerate(summary, 1):
    bar = "█" * min(int(row['avg'] / max(summary[0]['avg'], 1) * 20), 20) if row['avg'] > 0 else "░"
    print(f"  {i}위  {row['strategy']:<12}  {bar:<20}  평균 {row['avg']:.1f}회/종목 (2년)")

print()
