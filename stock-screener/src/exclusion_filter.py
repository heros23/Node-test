import os
import json
import logging
from typing import List, Set, Dict
from datetime import datetime, timedelta
import re

import pandas as pd

logger = logging.getLogger(__name__)


class ExclusionFilter:
    """제외 종목 필터 (관리종목, 투자경고/위험, 우선주, ETF, ETN, 정리매매, SPAC, 초저유동성)."""

    def __init__(self, cache_dir: str = "data"):
        self.cache_dir = os.path.join(os.path.dirname(__file__), "..", cache_dir)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.excluded: Set[str] = set()
        self.etfs: Set[str] = set()
        self.etns: Set[str] = set()
        self.spacs: Set[str] = set()
        self.preferred: Set[str] = set()
        self.management: Set[str] = set()
        self.risky: Set[str] = set()
        self.low_liquidity: Set[str] = set()
        self._last_update: datetime = datetime.min

    def _cache_path(self, name: str) -> str:
        return os.path.join(self.cache_dir, f"exclusion_{name}.json")

    def _load_cache(self, name: str) -> Set[str]:
        path = self._cache_path(name)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return set(json.load(f))
        return set()

    def _save_cache(self, name: str, values: Set[str]):
        with open(self._cache_path(name), "w", encoding="utf-8") as f:
            json.dump(sorted(values), f, ensure_ascii=False, indent=2)

    def _is_fresh(self, hours: int = 24) -> bool:
        return datetime.now() - self._last_update < timedelta(hours=hours)

    def build_exclusion_list(self, universe: Dict[str, Dict], refresh: bool = False):
        """pykrx 및 휴리스틱을 활용해 제외 종목 리스트를 구성합니다."""
        if not refresh and self._is_fresh() and self.excluded:
            return self.excluded

        try:
            today = datetime.now().strftime("%Y%m%d")

            # 1. ETF/ETN: 종목명/코드로 추정 (Korea: ETF/ETN은 6자리, 특정 prefix 등)
            # pykrx는 ETF/ETN 별도 함수 제공이 없으므로 KRX 상장종목정보 CSV로 추정
            # 여기선 이름 기반 휴리스틱과 유동성 기준으로 보수적으로 제외
            for sym, info in universe.items():
                name = info.get("name", "")
                upper = name.upper()
                if "ETF" in upper or "INDEX" in upper or "TRADE" in upper or "KODEX" in upper or "TIGER" in upper or "KOSEF" in upper or "ARIRANG" in upper or "KINDEX" in upper or "HANARO" in upper or "SOL" in upper or "TIMEFOLIO" in upper:
                    self.etfs.add(sym)
                if "ETN" in upper or "ETN" in sym:
                    self.etns.add(sym)
                if "우" in name or "우선" in name or sym.endswith("PR") or re.search(r"[0-9]+[A-Z]$", sym):
                    self.preferred.add(sym)
                if "스팩" in name or "SPAC" in upper or "SPEC" in upper:
                    self.spacs.add(sym)
                if "관리" in name or "정리매매" in upper or "투자경고" in upper or "투자위험" in upper or "상장폐지" in upper:
                    self.management.add(sym)

            # 2. 초저유동성: pykrx API가 불안정하여 현재는 이름 휴리스틱만 사용.
            #    실제 운영 시에는 최근 20일 평균 거래대금 10억원 미만(KRX) / 50만 USD 미만(NASDAQ)으로 필터링 권장.

            # 3. 정리매매/관리종목: KRX 공시 데이터는 외부 API/CSV 필요. 여기선 휴리스틱으로 대체.
            # 실제 사용 시 DART 공시 OpenAPI 또는 KRX 상장폐지 현황 CSV 연동 권장.

            self.excluded = (
                self.etfs | self.etns | self.preferred | self.spacs |
                self.management | self.risky
            )

            self._save_cache("etfs", self.etfs)
            self._save_cache("etns", self.etns)
            self._save_cache("preferred", self.preferred)
            self._save_cache("spacs", self.spacs)
            self._save_cache("management", self.management)
            self._save_cache("risky", self.risky)
            self._last_update = datetime.now()
        except Exception as e:
            logger.warning("제외 리스트 구성 실패: %s", e)
        return self.excluded

    def is_excluded(self, symbol: str) -> bool:
        return symbol in self.excluded

    def filter_universe(self, universe: Dict[str, Dict]) -> Dict[str, Dict]:
        self.build_exclusion_list(universe)
        return {sym: info for sym, info in universe.items() if sym not in self.excluded}

    def get_exclusion_reasons(self, symbol: str) -> List[str]:
        reasons = []
        if symbol in self.etfs:
            reasons.append("ETF")
        if symbol in self.etns:
            reasons.append("ETN")
        if symbol in self.preferred:
            reasons.append("우선주")
        if symbol in self.spacs:
            reasons.append("SPAC")
        if symbol in self.management:
            reasons.append("관리종목/정리매매")
        if symbol in self.risky:
            reasons.append("투자경고/위험")
        return reasons
