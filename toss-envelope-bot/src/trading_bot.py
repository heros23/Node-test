from __future__ import annotations

from typing import Dict, List, Optional

from src.broker_adapter import TossBrokerAdapter
from src.envelope_strategy import EnvelopeStrategy


class TradingBot:
    def __init__(self, adapter: Optional[TossBrokerAdapter] = None):
        self.adapter = adapter or TossBrokerAdapter()
        self.strategy = EnvelopeStrategy(window=20, deviation=0.02)
        self.positions: List[Dict[str, object]] = []

    def sync_account(self) -> Dict[str, object]:
        account = self.adapter.get_account()
        self.positions = account.get('positions', [])
        return account

    def place_signal_order(self, symbol: str, signal: str, quantity: int = 1) -> Dict[str, object]:
        if signal == 'BUY':
            return self.adapter.place_order(symbol, 'BUY', quantity)
        if signal == 'SELL':
            return self.adapter.place_order(symbol, 'SELL', quantity)
        return {'status': 'ignored', 'signal': signal}
