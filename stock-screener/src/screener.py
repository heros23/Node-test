import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import numpy as np

from src.data_provider import StockData

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    symbol: str
    market: str
    name: str
    strategy: str
    close: float
    change_pct: float
    volume: float
    score: float
    details: Dict
    timestamp: datetime


class TechnicalHelpers:
    """기술적 지표 계산 헬퍼."""

    @staticmethod
    def sma(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window=window, min_periods=window).mean()

    @staticmethod
    def ema(series: pd.Series, window: int) -> pd.Series:
        return series.ewm(span=window, adjust=False, min_periods=window).mean()

    @staticmethod
    def bollinger_bands(df: pd.DataFrame, window: int = 20, std: float = 2.0) -> pd.DataFrame:
        df = df.copy()
        df["bb_mid"] = TechnicalHelpers.sma(df["close"], window)
        df["bb_std"] = df["close"].rolling(window=window, min_periods=window).std()
        df["bb_upper"] = df["bb_mid"] + df["bb_std"] * std
        df["bb_lower"] = df["bb_mid"] - df["bb_std"] * std
        return df

    @staticmethod
    def ichimoku(df: pd.DataFrame) -> pd.DataFrame:
        """일목균형표 (기본)"""
        df = df.copy()
        high_9 = df["high"].rolling(window=9, min_periods=9).max()
        low_9 = df["low"].rolling(window=9, min_periods=9).min()
        df["tenkan_sen"] = (high_9 + low_9) / 2

        high_26 = df["high"].rolling(window=26, min_periods=26).max()
        low_26 = df["low"].rolling(window=26, min_periods=26).min()
        df["kijun_sen"] = (high_26 + low_26) / 2

        df["senkou_span_a"] = ((df["tenkan_sen"] + df["kijun_sen"]) / 2).shift(26)
        df["senkou_span_b"] = (
            (df["high"].rolling(window=52, min_periods=52).max() +
             df["low"].rolling(window=52, min_periods=52).min()) / 2
        ).shift(26)
        return df


class StrategyScreener:
    """4대 기법 검색기."""

    def __init__(self, min_history: int = 240):
        self.min_history = min_history

    def _validate(self, data: StockData) -> bool:
        if data.history is None or data.history.empty:
            return False
        if len(data.history) < self.min_history:
            return False
        return True

    # ──────────────────────────────────────────────────────────────────────
    # 1. 256 기법
    # 조합: A AND B AND C AND D
    # A: 5, 20, 60 이평이 3% 이내 밀집
    # B: 종가 5이평 > 종가 20이평
    # C: 종가 6이평 > 종가 20이평 (6일선은 5일과 유사, 종가 6이평으로 해석)
    # D: 당일 거래량이 전일 거래량 대비 200% 이상 증가
    # ──────────────────────────────────────────────────────────────────────
    def screen_256(self, data: StockData) -> Optional[SignalResult]:
        if not self._validate(data):
            return None
        df = data.history.copy()
        df["ma5"] = TechnicalHelpers.sma(df["close"], 5)
        df["ma6"] = TechnicalHelpers.sma(df["close"], 6)
        df["ma20"] = TechnicalHelpers.sma(df["close"], 20)
        df["ma60"] = TechnicalHelpers.sma(df["close"], 60)
        latest = df.iloc[-1]

        # A: 5/20/60 이평 3% 이내 밀집 (최대-최소 / 중간값)
        m1, m2, m3 = latest["ma5"], latest["ma20"], latest["ma60"]
        cluster_max = max(m1, m2, m3)
        cluster_min = min(m1, m2, m3)
        cluster_mid = (cluster_max + cluster_min) / 2
        cluster_pct = (cluster_max - cluster_min) / cluster_mid if cluster_mid else 999
        A = cluster_pct <= 0.03

        # B: 종가 5이평 > 종가 20이평 (문구상 종가기준 이평값으로 해석)
        B = latest["ma5"] > latest["ma20"]

        # C: 종가 6이평 > 종가 20이평
        C = latest["ma6"] > latest["ma20"]

        # D: 거래량 200% 이상 증가
        D = data.volume >= data.prev_volume * 2.0

        if A and B and C and D:
            return SignalResult(
                symbol=data.symbol,
                market=data.market,
                name=data.name,
                strategy="256 기법",
                close=data.close,
                change_pct=data.change_pct,
                volume=data.volume,
                score=100.0,
                details={
                    "cluster_pct": round(cluster_pct * 100, 2),
                    "ma5": round(latest["ma5"], 2),
                    "ma20": round(latest["ma20"], 2),
                    "ma60": round(latest["ma60"], 2),
                    "volume_ratio": round(data.volume / data.prev_volume, 2) if data.prev_volume else None,
                },
                timestamp=data.timestamp,
            )
        return None

    # ──────────────────────────────────────────────────────────────────────
    # 2. 밥그릇 3번 자리 (낙폭과대 반등)
    # 조합: A AND (B OR C) AND D
    # A: 100영업일 전 종가 > 당일 종가 (하락추세 확인)
    # B: 종가가 112일선 골든크로스
    # C: 종가가 224일선 골든크로스
    # D: 5 > 20 > 60 정배열
    # ──────────────────────────────────────────────────────────────────────
    def screen_babgeures(self, data: StockData) -> Optional[SignalResult]:
        if not self._validate(data) or len(data.history) < 224:
            return None
        df = data.history.copy()
        df["ma5"] = TechnicalHelpers.sma(df["close"], 5)
        df["ma20"] = TechnicalHelpers.sma(df["close"], 20)
        df["ma60"] = TechnicalHelpers.sma(df["close"], 60)
        df["ma112"] = TechnicalHelpers.sma(df["close"], 112)
        df["ma224"] = TechnicalHelpers.sma(df["close"], 224)
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # A: 100거래일 전 종가 > 당일 종가
        A = df.iloc[-100]["close"] > latest["close"] if len(df) >= 100 else False

        # B: 112일선 골든크로스 (전일 종가<=이평, 당일 종가>이평)
        B = prev["close"] <= prev["ma112"] and latest["close"] > latest["ma112"]

        # C: 224일선 골든크로스
        C = prev["close"] <= prev["ma224"] and latest["close"] > latest["ma224"]

        # D: 5 > 20 > 60 정배열
        D = latest["ma5"] > latest["ma20"] > latest["ma60"]

        if A and (B or C) and D:
            return SignalResult(
                symbol=data.symbol,
                market=data.market,
                name=data.name,
                strategy="밥그릇 3번",
                close=data.close,
                change_pct=data.change_pct,
                volume=data.volume,
                score=95.0,
                details={
                    "ma5": round(latest["ma5"], 2),
                    "ma20": round(latest["ma20"], 2),
                    "ma60": round(latest["ma60"], 2),
                    "cross_112": B,
                    "cross_224": C,
                },
                timestamp=data.timestamp,
            )
        return None

    # ──────────────────────────────────────────────────────────────────────
    # 3. 공구리 기법 (지지막 돌파)
    # 조합: A AND B AND C AND D
    # A: 최근 5봉 중 당일 종가가 가장 높음 (신고가)
    # B: 종가가 20일선 골든크로스
    # C: 종가가 볼린저 상한선 이상
    # D: 주가가 선행스팬1, 2 위에 위치
    # ──────────────────────────────────────────────────────────────────────
    def screen_gongguri(self, data: StockData) -> Optional[SignalResult]:
        if not self._validate(data) or len(data.history) < 60:
            return None
        df = data.history.copy()
        df["ma20"] = TechnicalHelpers.sma(df["close"], 20)
        df = TechnicalHelpers.bollinger_bands(df, window=20, std=2.0)
        df = TechnicalHelpers.ichimoku(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        recent5 = df.iloc[-5:]

        A = latest["close"] == recent5["close"].max()
        B = prev["close"] <= prev["ma20"] and latest["close"] > latest["ma20"]
        C = latest["close"] >= latest["bb_upper"]
        D = latest["close"] > latest["senkou_span_a"] and latest["close"] > latest["senkou_span_b"]

        if A and B and C and D:
            return SignalResult(
                symbol=data.symbol,
                market=data.market,
                name=data.name,
                strategy="공구리 기법",
                close=data.close,
                change_pct=data.change_pct,
                volume=data.volume,
                score=90.0,
                details={
                    "high_5d": round(recent5["close"].max(), 2),
                    "bb_upper": round(latest["bb_upper"], 2),
                    "senkou_a": round(latest["senkou_span_a"], 2),
                    "senkou_b": round(latest["senkou_span_b"], 2),
                },
                timestamp=data.timestamp,
            )
        return None

    # ──────────────────────────────────────────────────────────────────────
    # 4. 오돌이 기법 (키움 0150 기준)
    # 조합: A AND B AND C AND D AND E
    # A: 종가 20 > 60 > 112 (또는 224 위에 주가 위치)
    # B: 5봉 내 최고종가 대비 최저종가 하락률 -5% 이상
    # C: 5이평 1봉전 하락추세 지속 -> 0봉전 상승전환
    # D: 종가 1이평(당일 종가)이 종가 5이평을 골든크로스
    # E: 당일 거래량 > 전일 거래량 150% 이상
    # ──────────────────────────────────────────────────────────────────────
    def screen_odol(self, data: StockData) -> Optional[SignalResult]:
        if not self._validate(data) or len(data.history) < 120:
            return None
        df = data.history.copy()
        df["ma5"] = TechnicalHelpers.sma(df["close"], 5)
        df["ma20"] = TechnicalHelpers.sma(df["close"], 20)
        df["ma60"] = TechnicalHelpers.sma(df["close"], 60)
        df["ma112"] = TechnicalHelpers.sma(df["close"], 112)
        df["ma224"] = TechnicalHelpers.sma(df["close"], 224)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        recent5 = df.iloc[-5:]

        # A: 20 > 60 > 112
        A1 = latest["ma20"] > latest["ma60"] > latest["ma112"]
        # 또는 224 위에 주가 위치
        A2 = latest["close"] > latest["ma224"]
        A = A1 or A2

        # B: 5봉 내 최고 대비 최저 하락률 -5% 이상
        recent_high = recent5["close"].max()
        recent_low = recent5["close"].min()
        drop_pct = (recent_low / recent_high - 1) * 100 if recent_high else 0
        B = drop_pct <= -5.0

        # C: 5이평 방향 전환 (1봉전 하락, 0봉전 상승)
        ma5_today = latest["ma5"]
        ma5_prev = prev["ma5"]
        ma5_prev2 = df.iloc[-3]["ma5"] if len(df) >= 3 else ma5_prev
        C = (ma5_prev <= ma5_prev2) and (ma5_today > ma5_prev)

        # D: 당일 종가 > 5이평 (골든크로스: 전일종가<=5이평, 당일종가>5이평)
        D = prev["close"] <= prev["ma5"] and latest["close"] > latest["ma5"]

        # E: 거래량 150% 이상 증가
        E = data.volume >= data.prev_volume * 1.5

        if A and B and C and D and E:
            return SignalResult(
                symbol=data.symbol,
                market=data.market,
                name=data.name,
                strategy="오돌이 기법",
                close=data.close,
                change_pct=data.change_pct,
                volume=data.volume,
                score=92.0,
                details={
                    "drop_5d_pct": round(drop_pct, 2),
                    "ma5_trend_change": C,
                    "volume_ratio": round(data.volume / data.prev_volume, 2) if data.prev_volume else None,
                    "ma5": round(latest["ma5"], 2),
                    "ma20": round(latest["ma20"], 2),
                    "ma60": round(latest["ma60"], 2),
                },
                timestamp=data.timestamp,
            )
        return None

    def screen_all(self, data: StockData) -> List[SignalResult]:
        results = []
        for method in (self.screen_256, self.screen_babgeures, self.screen_gongguri, self.screen_odol):
            try:
                res = method(data)
                if res:
                    results.append(res)
            except Exception as e:
                logger.debug("%s %s error: %s", method.__name__, data.symbol, e)
        return results
