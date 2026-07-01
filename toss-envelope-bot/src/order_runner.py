from __future__ import annotations

from src.toss_api_client import TossApiClient


def run_demo_order(symbol: str = '005930', side: str = 'BUY', quantity: int = 1) -> dict:
    client = TossApiClient()
    return client.place_order(symbol=symbol, side=side, quantity=quantity)


if __name__ == '__main__':
    print(run_demo_order())
