from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests


class TossBrokerAdapter:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.base_url = base_url or os.getenv('TOSS_BASE_URL', 'https://example.test')
        self.api_key = api_key or os.getenv('TOSS_API_KEY', '')
        self.api_secret = api_secret or os.getenv('TOSS_API_SECRET', '')

    def get_account(self) -> Dict[str, Any]:
        headers = {'Authorization': f'Bearer {self.api_key}'}
        response = requests.get(f'{self.base_url}/account', headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def place_order(self, symbol: str, side: str, quantity: int, price: Optional[float] = None) -> Dict[str, Any]:
        payload = {'symbol': symbol, 'side': side, 'quantity': quantity}
        if price is not None:
            payload['price'] = price
        headers = {'Authorization': f'Bearer {self.api_key}'}
        response = requests.post(f'{self.base_url}/orders', json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
