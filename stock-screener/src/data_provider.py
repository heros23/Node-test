import os
import time
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import numpy as np
import yfinance as yf
from pykrx import stock as pykrx_stock

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
        self._executor = ThreadPoolExecutor(max_workers=8)
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
            logger.warning("pykrx 종목 리스트 로드 실패: %s", e)

        # NASDAQ 상위 500개 (yfinance symbol list approximation)
        nasdaq_symbols = self._get_nasdaq_symbols()
        for sym in nasdaq_symbols:
            universe[sym] = {"symbol": sym, "name": sym, "market": "NASDAQ", "sector": "NASDAQ"}

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(universe, f, ensure_ascii=False, indent=2)
        self.universe = universe
        return universe

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
            "XPEV", "LI", "PDD", "JD", "NTES", "BIDU", "TCEHY", "DADA",
            "ZM", "DOCU", "SQ", "SHOP", "SE", "MELI", "UBER", "LYFT",
            "ABNB", "DASH", "RKT", "HOOD", "AFRM", "BRK-B", "JPM", "JNJ",
            "V", "MA", "WMT", "HD", "PG", "KO", "DIS", "VZ",
            "NKE", "PFE", "MRK", "UNH", "BAC", "C", "GS", "MS",
        ]

    # ──────────────────────────────────────────────────────────────────────
    # 데이터 가져오기
    # ──────────────────────────────────────────────────────────────────────
    def fetch_krx_history(self, symbol: str, days: int = 240) -> pd.DataFrame:
        # 캐시 확인
        if not self.cache.should_refresh(symbol, max_age_hours=24):
            cached = self.cache.read(symbol)
            if cached is not None and len(cached) >= days * 0.5:
                return cached

        today = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        try:
            df = pykrx_stock.get_market_ohlcv_by_date(start, today, symbol)
            df = df.reset_index()
            df = df.rename(columns={
                "날짜": "date", "시가": "open", "고가": "high", "저가": "low",
                "종가": "close", "거래량": "volume"
            })
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            if not df.empty:
                self.cache.merge(symbol, df)
            return df
        except Exception as e:
            logger.warning("KRX %s history 실패: %s", symbol, e)
            cached = self.cache.read(symbol)
            return cached if cached is not None else pd.DataFrame()

    def fetch_yf_history(self, symbol: str, days: int = 240) -> pd.DataFrame:
        if not self.cache.should_refresh(symbol, max_age_hours=24):
            cached = self.cache.read(symbol)
            if cached is not None and len(cached) >= days * 0.5:
                return cached

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1y", interval="1d")
            if df.empty:
                cached = self.cache.read(symbol)
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
            cached = self.cache.read(symbol)
            return cached if cached is not None else pd.DataFrame()

    def fetch_stock_data(self, symbol: str, market: str) -> Optional[StockData]:
        if market in ("KOSPI", "KOSDAQ"):
            df = self.fetch_krx_history(symbol, days=5)
        else:
            df = self.fetch_yf_history(symbol, days=5)
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

    def enrich_history(self, data: StockData, days: int = 240) -> StockData:
        """data의 history를 days 만큼 확장하여 기술적 지표 계산용으로 보강."""
        if data.market in ("KOSPI", "KOSDAQ"):
            df = self.fetch_krx_history(data.symbol, days=days)
        else:
            df = self.fetch_yf_history(data.symbol, days=days)
        if not df.empty:
            data.history = df
        return data

    # ──────────────────────────────────────────────────────────────────────
    # 배치 폴링
    # ──────────────────────────────────────────────────────────────────────
    async def fetch_all_async(self, symbols: List[Tuple[str, str]], days: int = 240) -> List[StockData]:
        loop = asyncio.get_event_loop()
        results = []
        sem = asyncio.Semaphore(8)

        async def _fetch_one(sym, market):
            async with sem:
                try:
                    return await loop.run_in_executor(self._executor, self._fetch_with_history, sym, market, days)
                except Exception as e:
                    logger.debug("fetch %s error: %s", sym, e)
                    return None

        tasks = [asyncio.create_task(_fetch_one(s, m)) for s, m in symbols]
        for coro in asyncio.as_completed(tasks):
            res = await coro
            if res is not None:
                results.append(res)
        return results

    def _fetch_with_history(self, symbol: str, market: str, days: int = 240) -> Optional[StockData]:
        data = self.fetch_stock_data(symbol, market)
        if data is None:
            return None
        return self.enrich_history(data, days=days)

