from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests


class TossApiClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.base_url = base_url or os.getenv('TOSS_BASE_URL', '').rstrip('/')
        self.api_key = api_key or os.getenv('TOSS_API_KEY', '')
        self.api_secret = api_secret or os.getenv('TOSS_API_SECRET', '')

    def _headers(self) -> Dict[str, str]:
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

    def get_account(self) -> Dict[str, Any]:
        if not self.base_url or not self.api_key:
            return {'status': 'demo', 'cash': 10000000, 'positions': []}
        response = requests.get(f'{self.base_url}/account', headers=self._headers(), timeout=10)
        response.raise_for_status()
        return response.json()

    def place_order(self, symbol: str, side: str, quantity: int, price: Optional[float] = None) -> Dict[str, Any]:
        if not self.base_url or not self.api_key:
            return {'status': 'demo', 'symbol': symbol, 'side': side, 'quantity': quantity, 'price': price}
        payload = {'symbol': symbol, 'side': side, 'quantity': quantity}
        if price is not None:
            payload['price'] = price
        response = requests.post(f'{self.base_url}/orders', json=payload, headers=self._headers(), timeout=10)
        response.raise_for_status()
        return response.json()
