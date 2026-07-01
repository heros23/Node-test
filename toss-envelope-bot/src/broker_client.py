from __future__ import annotations

import os
from typing import Any, Dict

import requests

from src.config_store import apply_config_to_environment


class BrokerClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, api_secret: str | None = None) -> None:
        apply_config_to_environment()
        self.base_url = (base_url or os.getenv('TOSS_BASE_URL', 'https://api.demo.toss.example')).rstrip('/')
        self.api_key = api_key or os.getenv('TOSS_API_KEY', '')
        self.api_secret = api_secret or os.getenv('TOSS_API_SECRET', '')
        self.mode = 'live' if self.api_key and self.api_secret and self.base_url and self.base_url != 'https://api.demo.toss.example' else 'demo'
        self.base_url_hint = self._base_url_hint()

    def _base_url_hint(self) -> str:
        if not self.base_url:
            return 'Base URL이 비어 있습니다.'
        if 'tossinvest.com' in self.base_url and 'http' in self.base_url:
            return '현재 Base URL은 웹 페이지 주소로 보입니다. 실제 계좌 연동에는 토스증권 로그인 세션 또는 공식 API 권한이 필요합니다.'
        return 'Base URL 형식이 확인되지 않았습니다.'

    def get_account_summary(self) -> Dict[str, Any]:
        if self.mode != 'live':
            return {
                'mode': 'demo',
                'account_id': 'demo-account',
                'cash': 10000000,
                'assets': 10850000,
                'daily_pnl': 850000,
                'return_rate': 0.085,
                'error': f'실제 API 주소/인증 정보가 없어 데모 모드로 표시 중입니다. 대시보드의 Base URL, API Key, API Secret을 저장해 주세요. ({self.base_url_hint})',
            }

        try:
            response = requests.get(f'{self.base_url}/accounts', headers=self._headers(), timeout=10)
            response.raise_for_status()
            account_payload = response.json()
            if not isinstance(account_payload, dict):
                raise ValueError('unexpected response format')
            return {
                'mode': 'live',
                'account_id': account_payload.get('account_id', 'live-account'),
                'cash': account_payload.get('cash', 10000000),
                'assets': account_payload.get('assets', 10850000),
                'daily_pnl': account_payload.get('daily_pnl', 850000),
                'return_rate': account_payload.get('return_rate', 0.085),
            }
        except Exception as exc:
            return {
                'mode': 'demo',
                'account_id': 'demo-account',
                'cash': 10000000,
                'assets': 10850000,
                'daily_pnl': 850000,
                'return_rate': 0.085,
                'error': f'계좌 조회 실패: {exc}. 실제 토스 API를 사용할 수 없어 데모값으로 표시 중입니다.',
            }

    def build_order_payload(self, symbol: str, side: str, quantity: int) -> Dict[str, Any]:
        return {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'order_type': 'market',
            'timestamp': 0,
        }

    def place_order(self, symbol: str, side: str, quantity: int) -> Dict[str, Any]:
        payload = self.build_order_payload(symbol, side, quantity)
        if self.mode != 'live':
            return {'mode': 'demo', 'accepted': True, 'payload': payload}

        try:
            response = requests.post(f'{self.base_url}/orders', headers=self._headers(), json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception:
            return {'mode': 'live', 'accepted': False, 'error': 'request_failed', 'payload': payload}

    def execute_signal(self, symbol: str, side: str, quantity: int) -> Dict[str, Any]:
        return self.place_order(symbol, side, quantity)

    def _headers(self) -> Dict[str, str]:
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
            'X-API-SECRET': self.api_secret,
        }
