import os
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.data_provider import MarketDataProvider, StockData
from src.screener import StrategyScreener, SignalResult
from src.exclusion_filter import ExclusionFilter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScreenerService:
    """실시간 조건 검색 서비스. 종목 데이터를 주기적으로 폴링하고 4대 기법 조건을 평가합니다.

    Dashboard를 빨리 활성화하기 위해 전체 종목을 chunk 단위로 순환 처리합니다.
    한 주기(poll)마다 하나의 chunk만 스크리닝하고, 완료 즉시 WebSocket으로 broadcast합니다.
    """

    def __init__(self, markets: Optional[List[str]] = None, poll_interval: int = 60, chunk_size: int = 50):
        self.markets = markets or ["KOSPI", "KOSDAQ", "NASDAQ"]
        self.poll_interval = poll_interval
        self.chunk_size = chunk_size
        self.provider = MarketDataProvider()
        self.filter = ExclusionFilter()
        self.screener = StrategyScreener(min_history=240)
        self.universe: Dict[str, Dict] = {}
        self.filtered_universe: Dict[str, Dict] = {}
        self.signals: List[SignalResult] = []
        self._signal_index: Dict[str, SignalResult] = {}
        self.last_run: Optional[datetime] = None
        self.is_running = False
        self.scheduler = AsyncIOScheduler()
        self._subscribers = set()
        self._lock = asyncio.Lock()
        self._target_symbols_list: List[Tuple[str, str]] = []
        self._chunk_index: int = 0
        self._screening_progress: Dict = {"current": 0, "total": 0, "chunk": 0, "total_chunks": 0}
        self._full_cycle_done: bool = False

    async def initialize(self):
        logger.info("유니버스 로드 중...")
        universe = await asyncio.get_event_loop().run_in_executor(None, self.provider.load_universe, False)
        self.universe = universe
        logger.info("전체 종목 %d개", len(self.universe))

        # 제외 필터 적용
        self.filtered_universe = self.filter.filter_universe(self.universe)
        logger.info("필터링 후 종목 %d개", len(self.filtered_universe))

        self._target_symbols_list = [
            (sym, info["market"]) for sym, info in self.filtered_universe.items() if info["market"] in self.markets
        ]
        total = len(self._target_symbols_list)
        self._screening_progress = {"current": 0, "total": total, "chunk": 0, "total_chunks": (total + self.chunk_size - 1) // self.chunk_size}

    def _next_chunk(self) -> List[Tuple[str, str]]:
        total = len(self._target_symbols_list)
        if total == 0:
            return []
        chunks = (total + self.chunk_size - 1) // self.chunk_size
        start = self._chunk_index * self.chunk_size
        end = min(start + self.chunk_size, total)
        chunk = self._target_symbols_list[start:end]
        self._chunk_index = (self._chunk_index + 1) % chunks
        if self._chunk_index == 0:
            self._full_cycle_done = True
        return chunk

    async def run_screen(self):
        async with self._lock:
            self.last_run = datetime.now()
            chunk = self._next_chunk()
            if not chunk:
                logger.warning("스크리닝 대상 종목이 없습니다.")
                await self._broadcast()
                return

            self._screening_progress["chunk"] = self._chunk_index + 1
            self._screening_progress["current"] = min(self._chunk_index * self.chunk_size + self.chunk_size, self._screening_progress["total"])
            logger.info(
                "스크리닝 chunk %d/%d: %d 종목",
                self._screening_progress["chunk"],
                self._screening_progress["total_chunks"],
                len(chunk),
            )

            data_list = await self.provider.fetch_all_async(chunk, days=240, max_age_hours=24, max_workers=10, per_symbol_timeout=8)
            for data in data_list:
                try:
                    for signal in self.screener.screen_all(data):
                        key = f"{data.symbol}_{signal.strategy}"
                        self._signal_index[key] = signal
                except Exception as e:
                    logger.debug("스크리너 오류 %s: %s", data.symbol, e)

            self.signals = sorted(self._signal_index.values(), key=lambda x: x.score, reverse=True)
            logger.info("누적 신호 %d개 감지", len(self.signals))
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
            max_instances=1,
        )
        self.scheduler.start()
        logger.info("스크리너 폴링 시작: %d초, chunk_size=%d", self.poll_interval, self.chunk_size)

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
            "signal_count": len(self.signals),
            "progress": self._screening_progress,
            "full_cycle_done": self._full_cycle_done,
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
