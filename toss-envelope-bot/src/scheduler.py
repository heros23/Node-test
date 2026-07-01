from __future__ import annotations

from typing import Callable


class SimpleScheduler:
    def __init__(self, interval_seconds: int = 60):
        self.interval_seconds = interval_seconds
        self.running = False

    def run(self, callback: Callable[[], None]) -> None:
        self.running = True
        while self.running:
            callback()
            import time
            time.sleep(self.interval_seconds)

    def stop(self) -> None:
        self.running = False
