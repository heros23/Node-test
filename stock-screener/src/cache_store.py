import os
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict

import pandas as pd

logger = logging.getLogger(__name__)


class DataCache:
    """종목별 일봉 데이터 캐시. parquet 파일로 저장하고, 날짜 기준 증분 업데이트.
    스레드 안전을 위해 write/merge/read에 lock을 사용합니다.
    """

    def __init__(self, cache_dir: str = "data/cache"):
        self.cache_dir = os.path.join(os.path.dirname(__file__), "..", cache_dir)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.meta_path = os.path.join(self.cache_dir, "meta.json")
        self._lock = threading.Lock()
        self.meta = self._load_meta()

    def _load_meta(self) -> Dict:
        if os.path.exists(self.meta_path):
            with open(self.meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_meta(self):
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)

    def _load_or_refresh_meta(self):
        if not os.path.exists(self.meta_path):
            return
        try:
            mtime = os.path.getmtime(self.meta_path)
            if getattr(self, "_meta_mtime", None) != mtime:
                self.meta = self._load_meta()
                self._meta_mtime = mtime
        except Exception:
            pass

    def _path(self, symbol: str) -> str:
        return os.path.join(self.cache_dir, f"{symbol}.parquet")

    def read(self, symbol: str) -> Optional[pd.DataFrame]:
        with self._lock:
            self._load_or_refresh_meta()
            path = self._path(symbol)
            if not os.path.exists(path):
                return None
            try:
                df = pd.read_parquet(path)
                df["date"] = pd.to_datetime(df["date"])
                return df
            except Exception as e:
                logger.warning("캐시 읽기 실패 %s: %s", symbol, e)
                return None

    def write(self, symbol: str, df: pd.DataFrame):
        if df.empty:
            return
        with self._lock:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
            df.to_parquet(self._path(symbol), index=False)
            self.meta[symbol] = {
                "last_close": df.iloc[-1]["date"].strftime("%Y-%m-%d"),
                "rows": len(df),
                "updated": datetime.now().isoformat(),
            }
            self._save_meta()
            self._meta_mtime = os.path.getmtime(self.meta_path)

    def merge(self, symbol: str, new_df: pd.DataFrame) -> pd.DataFrame:
        with self._lock:
            old = self.read(symbol)
            if old is None or old.empty:
                merged = new_df
            else:
                merged = pd.concat([old, new_df], ignore_index=True)
            self.write(symbol, merged)
            return merged

    def should_refresh(self, symbol: str, max_age_hours: int = 24) -> bool:
        with self._lock:
            self._load_or_refresh_meta()
            info = self.meta.get(symbol)
            if not info:
                return True
            try:
                updated = datetime.fromisoformat(info.get("updated", "2000-01-01"))
                return datetime.now() - updated > timedelta(hours=max_age_hours)
            except Exception:
                return True

    def last_date(self, symbol: str) -> Optional[str]:
        with self._lock:
            self._load_or_refresh_meta()
            return self.meta.get(symbol, {}).get("last_close")
