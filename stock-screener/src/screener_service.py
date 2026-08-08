import os
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import asdict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.data_provider import MarketDataProvider, StockData
from src.screener import StrategyScreener, SignalResult
from src.exclusion_filter import ExclusionFilter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScreenerService:
    """실시간 조건 검색 서비스. 종목 데이터를 주기적으로 폴링하고 4대 기법 조건을 평가합니다."""

    def __init__(self, markets: Optional[List[str]] = None, poll_interval: int = 60):
        self.markets = markets or ["KOSPI", "KOSDAQ", "NASDAQ"]
        self.poll_interval = poll_interval
        self.provider = MarketDataProvider()
        self.filter = ExclusionFilter()
        self.screener = StrategyScreener(min_history=240)
        self.universe: Dict[str, Dict] = {}
        self.filtered_universe: Dict[str, Dict] = {}
        self.signals: List[SignalResult] = []
        self.last_run: Optional[datetime] = None
        self.is_running = False
        self.scheduler = AsyncIOScheduler()
        self._subscribers = set()
        self._lock = asyncio.Lock()

    async def initialize(self):
        logger.info("유니버스 로드 중...")
        universe = await asyncio.get_event_loop().run_in_executor(None, self.provider.load_universe, False)
        self.universe = universe
        logger.info("전체 종목 %d개", len(self.universe))

        # 제외 필터 적용
        self.filtered_universe = self.filter.filter_universe(self.universe)
        logger.info("필터링 후 종목 %d개", len(self.filtered_universe))

    def _target_symbols(self) -> List[tuple]:
        return [(sym, info["market"]) for sym, info in self.filtered_universe.items() if info["market"] in self.markets]

    async def run_screen(self):
        async with self._lock:
            self.last_run = datetime.now()
            symbols = self._target_symbols()
            logger.info("스크리닝 시작: %d 종목", len(symbols))
            data_list = await self.provider.fetch_all_async(symbols, days=240)
            all_signals: List[SignalResult] = []
            for data in data_list:
                try:
                    signals = self.screener.screen_all(data)
                    all_signals.extend(signals)
                except Exception as e:
                    logger.debug("스크리너 오류 %s: %s", data.symbol, e)
            self.signals = sorted(all_signals, key=lambda x: x.score, reverse=True)
            logger.info("신호 %d개 감지", len(self.signals))
            await self._broadcast()

    async def _broadcast(self):
        if not self._subscribers:
            return
        payload = self.to_dict()
        message = json.dumps(payload, ensure_ascii=False, default=str)
        dead = set()
        for ws in self._subscribers:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self._subscribers -= dead

    def subscribe(self, ws):
        self._subscribers.add(ws)

    def unsubscribe(self, ws):
        self._subscribers.discard(ws)

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.scheduler.add_job(
            self.run_screen,
            trigger=IntervalTrigger(seconds=self.poll_interval),
            id="screen",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("스크리너 폴링 시작: %d초", self.poll_interval)

    def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self.scheduler.shutdown()

    def to_dict(self) -> Dict:
        return {
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "universe_total": len(self.universe),
            "universe_filtered": len(self.filtered_universe),
            "signals": [
                {
                    "symbol": s.symbol,
                    "market": s.market,
                    "name": s.name,
                    "strategy": s.strategy,
                    "close": s.close,
                    "change_pct": s.change_pct,
                    "volume": s.volume,
                    "score": s.score,
                    "details": s.details,
                    "timestamp": s.timestamp.isoformat(),
                }
                for s in self.signals
            ],
        }
