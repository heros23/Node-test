#!/usr/bin/env python3
import time, sys
import requests

url = "https://fchart.stock.naver.com/sise.nhn?symbol=005930&timeframe=day&count=5&requestType=0"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.naver.com/",
}
print("Start request", url, flush=True)
t0 = time.time()
try:
    resp = requests.get(url, headers=headers, timeout=(3, 10))
    elapsed = time.time() - t0
    print(f"Status: {resp.status_code}, elapsed: {elapsed:.2f}s, size: {len(resp.content)}", flush=True)
    print(resp.text[:200], flush=True)
except Exception as e:
    elapsed = time.time() - t0
    print(f"ERROR after {elapsed:.2f}s: {e}", flush=True)
    sys.exit(1)
