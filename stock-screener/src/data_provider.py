import os
import time
import json
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from io import StringIO
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import numpy as np
import yfinance as yf
from pykrx import stock as pykrx_stock
import requests
from bs4 import BeautifulSoup

from src.cache_store import DataCache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class StockData:
    symbol: str
    market: str  # KOSPI, KOSDAQ, NASDAQ
    name: str
    close: float
    open: float
    high: float
    low: float
    volume: float
    prev_close: float
    prev_volume: float
    change_pct: float
    timestamp: datetime
    extra: Dict = field(default_factory=dict)
    # 기본/기술 데이터가 채워지면 history OHLCV DataFrame
    history: Optional[pd.DataFrame] = None


class MarketDataProvider:
    """KOSPI/KOSDAQ/NASDAQ 종목 데이터를 수집하는 provider.
    KOSPI/KOSDAQ: pykrx (지연 데이터, 무료)
    NASDAQ: yfinance (지연 데이터, 무료)
    실시간(실시간 효과)를 위해 일정 주기로 폴링합니다.
    """

    def __init__(self, cache_dir: str = "data"):
        self.cache_dir = os.path.join(os.path.dirname(__file__), "..", cache_dir)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.universe: Dict[str, Dict] = {}
        self._krx_last_update = None
        self._last_krx_symbols: List[str] = []
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.naver.com/",
        })
        self.cache = DataCache(cache_dir=os.path.join(cache_dir, "cache"))

    # ──────────────────────────────────────────────────────────────────────
    # 종목 유니버스
    # ──────────────────────────────────────────────────────────────────────
    def load_universe(self, refresh: bool = False) -> Dict[str, Dict]:
        """KOSPI/KOSDAQ/NASDAQ 유니버스 로드. 제외 대상을 필터링합니다."""
        cache_path = os.path.join(self.cache_dir, "universe.json")
        if not refresh and os.path.exists(cache_path) and self._is_fresh(cache_path, hours=24):
            with open(cache_path, "r", encoding="utf-8") as f:
                self.universe = json.load(f)
            return self.universe

        universe = {}
        try:
            kospi = pykrx_stock.get_market_ticker_list(market="KOSPI")
            kosdaq = pykrx_stock.get_market_ticker_list(market="KOSDAQ")
            for sym in kospi:
                name = pykrx_stock.get_market_ticker_name(sym)
                universe[sym] = {"symbol": sym, "name": name, "market": "KOSPI", "sector": "KOSPI"}
            for sym in kosdaq:
                name = pykrx_stock.get_market_ticker_name(sym)
                universe[sym] = {"symbol": sym, "name": name, "market": "KOSDAQ", "sector": "KOSDAQ"}
            self._last_krx_symbols = kospi + kosdaq
        except Exception as e:
            logger.warning("pykrx 종목 리스트 로드 실패, 네이버 금융 폴백 시도: %s", e)
            try:
                universe.update(self._fetch_naver_universe(0, "KOSPI", max_pages=10))
                universe.update(self._fetch_naver_universe(1, "KOSDAQ", max_pages=10))
            except Exception as e2:
                logger.warning("네이버 금융 폴백도 실패: %s", e2)

        # NASDAQ 상위 500개 (yfinance symbol list approximation)
        nasdaq_symbols = self._get_nasdaq_symbols()
        for sym in nasdaq_symbols:
            universe[sym] = {"symbol": sym, "name": sym, "market": "NASDAQ", "sector": "NASDAQ"}

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(universe, f, ensure_ascii=False, indent=2)
        self.universe = universe
        return universe

    def _fetch_naver_universe(self, sosok: int, market: str, max_pages: int = 10) -> Dict[str, Dict]:
        """네이버 금융 시가총액 페이지에서 종목 리스트를 가져옵니다.

        KRX API가 불안정할 때 폴백으로 사용합니다. 시가총액 상위 max_pages*50개를 수집합니다.
        """
        result = {}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "Referer": "https://finance.naver.com/",
        }
        for page in range(1, max_pages + 1):
            url = f"https://finance.naver.com/sise/sise_market_sum.nhn?sosok={sosok}&page={page}"
            try:
                resp = self._session.get(url, timeout=(3, 10))
                resp.encoding = "euc-kr"
                soup = BeautifulSoup(resp.text, "html.parser")
                table = soup.find("table", class_="type_2")
                if not table:
                    break
                tbody = table.find("tbody")
                rows = tbody.find_all("tr") if tbody else table.find_all("tr")
                found = 0
                for row in rows:
                    tds = row.find_all("td")
                    if len(tds) < 3:
                        continue
                    a = tds[1].find("a", href=True)
                    if not a or "code=" not in a.get("href", ""):
                        continue
                    code = a["href"].split("code=")[-1].split("&")[0].strip()
                    name = a.get_text(strip=True)
                    if not code or not name or len(code) != 6 or not code.isdigit():
                        continue
                    try:
                        vol_text = str(tds[9].get_text(strip=True)).replace(",", "")
                        volume = float(vol_text) if vol_text else 0.0
                    except Exception:
                        volume = 0.0
                    result[code] = {
                        "symbol": code,
                        "name": name,
                        "market": market,
                        "sector": market,
                        "volume": volume,
                    }
                    found += 1
                logger.info("네이버 %s page %d: %d 종목", market, page, found)
                if found == 0:
                    break
            except Exception as e:
                logger.warning("네이버 금융 %s page %d 실패: %s", market, page, e)
                break
        return result

    def _fetch_naver_chart_history(self, symbol: str, days: int = 240) -> pd.DataFrame:
        """네이버 차트 API로 KOSPI/KOSDAQ 일봉 데이터를 한 번에 가져옵니다."""
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={symbol}&timeframe=day&count={days}&requestType=0"
        try:
            resp = self._session.get(url, timeout=(3, 10))
            resp.raise_for_status()
            text = resp.content.decode("euc-kr", errors="replace")
            text = text.replace('encoding="EUC-KR"', 'encoding="UTF-8"')
            root = ET.fromstring(text)
            rows = []
            for item in root.iter("item"):
                data = item.get("data")
                if not data:
                    continue
                parts = data.split("|")
                if len(parts) != 6:
                    continue
                date_str, open_p, high_p, low_p, close_p, volume = parts
                rows.append({
                    "date": pd.to_datetime(date_str, format="%Y%m%d"),
                    "open": float(open_p),
                    "high": float(high_p),
                    "low": float(low_p),
                    "close": float(close_p),
                    "volume": float(volume),
                })
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
            self.cache.merge(symbol, df)
            return df
        except Exception as e:
            logger.warning("네이버 차트 %s history 실패: %s", symbol, e)
            return pd.DataFrame()

    def _is_fresh(self, path: str, hours: int = 1) -> bool:
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            return datetime.now() - mtime < timedelta(hours=hours)
        except Exception:
            return False

    def _get_nasdaq_symbols(self) -> List[str]:
        # 상위 거래대금 NASDAQ 종목 샘플 (실제 사용 시 외부 CSV나 API로 교체)
        return [
            "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "TSLA", "NVDA", "META",
            "BABA", "NFLX", "AMD", "INTC", "PYPL", "CSCO", "CMCSA", "PEP",
            "ADBE", "AMGN", "COST", "TMUS", "TXN", "AVGO", "QCOM", "HON",
            "SBUX", "INTU", "ISRG", "GILD", "AMAT", "ADI", "VRTX", "REGN",
            "FISV", "KLAC", "LRCX", "MRVL", "NXPI", "ASML", "SNPS", "CDNS",
            "MU", "PANW", "ADSK", "FTNT", "CRWD", "ZS", "OKTA", "DDOG",
            "PLTR", "RBLX", "COIN", "UPST", "SOFI", "LCID", "RIVN", "MRNA",
            "PENN", "DKNG", "CHPT", "RUN", "FSLR", "ENPH", "SEDG", "NIO",
            "XPEV", "LI", "PDD", "JD", "NTES", "BIDU", "TCEHY",
            "ZM", "DOCU", "SHOP", "SE", "MELI", "UBER", "LYFT",
            "ABNB", "DASH", "RKT", "HOOD", "AFRM", "BRK-B", "JPM", "JNJ",
            "V", "MA", "WMT", "HD", "PG", "KO", "DIS", "VZ",
            "NKE", "PFE", "MRK", "UNH", "BAC", "C", "GS", "MS",
        ]

    # ──────────────────────────────────────────────────────────────────────
    # 데이터 가져오기
    # ──────────────────────────────────────────────────────────────────────
    def fetch_krx_history(self, symbol: str, days: int = 240, max_age_hours: int = 24) -> pd.DataFrame:
        cached = self.cache.read(symbol)
        if cached is not None and len(cached) >= days * 0.5 and not self.cache.should_refresh(symbol, max_age_hours=max_age_hours):
            return cached

        try:
            df = self._fetch_naver_chart_history(symbol, days)
            if not df.empty:
                return df
        except Exception as e:
            logger.warning("네이버 차트 %s history 실패: %s", symbol, e)

        return cached if cached is not None else pd.DataFrame()

    def fetch_yf_history(self, symbol: str, days: int = 240, max_age_hours: int = 24) -> pd.DataFrame:
        cached = self.cache.read(symbol)
        if cached is not None and len(cached) >= days * 0.5 and not self.cache.should_refresh(symbol, max_age_hours=max_age_hours):
            return cached

        try:
            ticker = yf.Ticker(symbol, session=self._session)
            df = ticker.history(period="1y", interval="1d", timeout=10)
            if df.empty:
                return cached if cached is not None else pd.DataFrame()
            df = df.reset_index()
            df = df.rename(columns={
                "Date": "date", "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume"
            })
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            df = df.sort_values("date").reset_index(drop=True)
            self.cache.merge(symbol, df)
            return df
        except Exception as e:
            logger.warning("YF %s history 실패: %s", symbol, e)
            return cached if cached is not None else pd.DataFrame()

    def fetch_stock_data(self, symbol: str, market: str, days: int = 240, max_age_hours: int = 1) -> Optional[StockData]:
        """최신 OHLCV + 과거 history를 한 번에 가져와 StockData를 만듭니다."""
        if market in ("KOSPI", "KOSDAQ"):
            df = self.fetch_krx_history(symbol, days=days, max_age_hours=max_age_hours)
        else:
            df = self.fetch_yf_history(symbol, days=days, max_age_hours=max_age_hours)
        if df.empty or len(df) < 2:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        return StockData(
            symbol=symbol,
            market=market,
            name=self.universe.get(symbol, {}).get("name", symbol),
            close=float(latest["close"]),
            open=float(latest["open"]),
            high=float(latest["high"]),
            low=float(latest["low"]),
            volume=float(latest["volume"]),
            prev_close=float(prev["close"]),
            prev_volume=float(prev["volume"]),
            change_pct=(float(latest["close"]) / float(prev["close"]) - 1) * 100,
            timestamp=datetime.now(),
            history=df,
        )

    # ──────────────────────────────────────────────────────────────────────
    # 배치 폴링
    # ──────────────────────────────────────────────────────────────────────
    async def fetch_all_async(
        self,
        symbols: List[Tuple[str, str]],
        days: int = 240,
        max_age_hours: int = 1,
        max_workers: int = 20,
        per_symbol_timeout: float = 10.0,
    ) -> List[StockData]:
        loop = asyncio.get_event_loop()
        results = []
        sem = asyncio.Semaphore(max_workers)

        async def _fetch_one(sym, market):
            async with sem:
                try:
                    return await asyncio.wait_for(
                        loop.run_in_executor(None, self.fetch_stock_data, sym, market, days, max_age_hours),
                        timeout=per_symbol_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.debug("fetch %s timeout", sym)
                    return None
                except Exception as e:
                    logger.debug("fetch %s error: %s", sym, e)
                    return None

        tasks = [asyncio.create_task(_fetch_one(s, m)) for s, m in symbols]
        for coro in asyncio.as_completed(tasks):
            res = await coro
            if res is not None:
                results.append(res)
        return results

