from __future__ import annotations

from typing import Dict, List

from src.envelope_strategy import EnvelopeStrategy
from src.order_logger import OrderLogger
from src.toss_api_client import TossApiClient


class SignalRunner:
    def __init__(self):
        self.strategy = EnvelopeStrategy(window=20, deviation=0.02)
        self.client = TossApiClient()
        self.logger = OrderLogger()

    def run_once(self, prices: List[float], symbol: str = '005930') -> Dict[str, object]:
        if len(prices) < self.strategy.window + 1:
            return {'status': 'insufficient_data'}

        import pandas as pd
        df = pd.DataFrame({'close': prices})
        signals = self.strategy.generate_signals(df)
        latest_signal = signals.iloc[-1]
        if latest_signal == 'BUY':
            result = self.client.place_order(symbol, 'BUY', quantity=1)
            self.logger.append({'event': 'buy_signal', 'symbol': symbol, 'result': result})
            return {'status': 'ordered', 'signal': latest_signal, 'result': result}
        if latest_signal == 'SELL':
            result = self.client.place_order(symbol, 'SELL', quantity=1)
            self.logger.append({'event': 'sell_signal', 'symbol': symbol, 'result': result})
            return {'status': 'ordered', 'signal': latest_signal, 'result': result}
        self.logger.append({'event': 'hold_signal', 'symbol': symbol, 'signal': latest_signal})
        return {'status': 'hold', 'signal': latest_signal}
