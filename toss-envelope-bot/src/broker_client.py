from __future__ import annotations

import os
from typing import Any, Dict, List

import requests

from src.config_store import apply_config_to_environment


class BrokerClient:
    """토스증권 Open API 클라이언트 (OAuth2 Client Credentials)."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        account_seq: str | int | None = None,
    ) -> None:
        apply_config_to_environment()
        raw_url = base_url or os.getenv('TOSS_BASE_URL', 'https://openapi.tossinvest.com')
        # config.json 에 https://openapi.tossinvest.com/v1 형태로 저장될 수 있으므로
        # trailing /v1 과 trailing slash 를 제거하여 API 호스트 기준으로 정규화합니다.
        self.base_url = raw_url.rstrip('/').removesuffix('/v1')
        # config.json 의 api_key/api_secret 은 실제로 OAuth2 client_id/client_secret
        self.client_id = api_key or os.getenv('TOSS_API_KEY', '')
        self.client_secret = api_secret or os.getenv('TOSS_API_SECRET', '')
        self.account_seq = account_seq or os.getenv('TOSS_ACCOUNT_SEQ', '')
        self._access_token: str | None = None
        self.mode = 'live' if self.client_id and self.client_secret and self.base_url == 'https://openapi.tossinvest.com' else 'demo'
        self.base_url_hint = self._base_url_hint()

    def _base_url_hint(self) -> str:
        if not self.base_url:
            return 'Base URL이 비어 있습니다.'
        if self.base_url == 'https://openapi.tossinvest.com':
            return '토스증권 공식 Open API 서버입니다.'
        return 'Base URL 형식이 확인되지 않았습니다.'

    def _oauth_token(self) -> str:
        """OAuth2 Client Credentials Grant 으로 access_token 발급."""
        if self._access_token:
            return self._access_token
        resp = requests.post(
            f'{self.base_url}/oauth2/token',
            data={
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._access_token = payload['access_token']
        return self._access_token

    def _headers(self, account_seq: str | int | None = None) -> Dict[str, str]:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self._oauth_token()}',
        }
        acc = account_seq or self.account_seq
        if acc:
            headers['X-Tossinvest-Account'] = str(acc)
        return headers

    def _resolve_account_seq(self) -> str | None:
        """account_seq 가 없으면 /api/v1/accounts 목록에서 첫 번째 계좌의 accountSeq 사용."""
        if self.account_seq:
            return str(self.account_seq)
        accounts = self.list_accounts()
        result = accounts.get('result', []) if isinstance(accounts, dict) else []
        if result:
            return str(result[0].get('accountSeq', ''))
        return None

    def list_accounts(self) -> Dict[str, Any]:
        """GET /api/v1/accounts - 계좌 목록 조회."""
        if self.mode != 'live':
            return {'result': [{'accountSeq': 1, 'accountNo': 'demo', 'accountType': 'BROKERAGE'}]}
        resp = requests.get(f'{self.base_url}/api/v1/accounts', headers=self._headers(), timeout=20)
        resp.raise_for_status()
        return resp.json()

    def get_holdings(self, account_seq: str | int | None = None) -> Dict[str, Any]:
        """GET /api/v1/holdings - 보유 주식 조회."""
        acc = account_seq or self._resolve_account_seq()
        if self.mode != 'live':
            return {'result': {'marketValue': {'amount': {'krw': '0', 'usd': '0'}}, 'items': []}}
        resp = requests.get(
            f'{self.base_url}/api/v1/holdings',
            headers=self._headers(acc),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def get_account_summary(self) -> Dict[str, Any]:
        """계좌 목록 + 보유 종목을 요약하여 반환."""
        if self.mode != 'live':
            return {
                'mode': 'demo',
                'account_id': 'demo-account',
                'cash': 10000000,
                'assets': 10850000,
                'daily_pnl': 850000,
                'return_rate': 0.085,
                'error': f'실제 API 인증 정보가 없어 데모 모드로 표시 중입니다. ({self.base_url_hint})',
            }

        try:
            accounts = self.list_accounts()
            result_list = accounts.get('result', []) if isinstance(accounts, dict) else []
            if not result_list:
                raise ValueError('사용 가능한 계좌가 없습니다.')

            account = result_list[0]
            account_seq = account.get('accountSeq')
            account_no = account.get('accountNo', '')

            holdings = self.get_holdings(account_seq)
            h_result = holdings.get('result', {}) if isinstance(holdings, dict) else {}
            market_value = h_result.get('marketValue', {}).get('amount', {})
            profit_loss = h_result.get('profitLoss', {})
            daily_pl = h_result.get('dailyProfitLoss', {})

            # 통화별 자산 합산 (USD 기반)
            assets_usd = float(market_value.get('usd', 0) or 0)
            assets_krw = float(market_value.get('krw', 0) or 0)
            pl_amount = float(profit_loss.get('amount', {}).get('usd', 0) or 0)
            pl_rate = float(profit_loss.get('rate', 0) or 0)
            daily_pl_amount = float(daily_pl.get('amount', {}).get('usd', 0) or 0)
            daily_pl_rate = float(daily_pl.get('rate', 0) or 0)

            items = h_result.get('items', []) or []
            positions = [
                {
                    'symbol': item.get('symbol', ''),
                    'name': item.get('name', ''),
                    'quantity': float(item.get('quantity', 0) or 0),
                    'last_price': float(item.get('lastPrice', 0) or 0),
                    'avg_price': float(item.get('averagePurchasePrice', 0) or 0),
                    'average_price': float(item.get('averagePurchasePrice', 0) or 0),
                    'market_value': float(item.get('marketValue', {}).get('amount', 0) or 0),
                    'pnl': float(item.get('profitLoss', {}).get('amount', 0) or 0),
                    'pnl_rate': float(item.get('profitLoss', {}).get('rate', 0) or 0),
                    'daily_pnl': float(item.get('dailyProfitLoss', {}).get('amount', 0) or 0),
                    'daily_pnl_rate': float(item.get('dailyProfitLoss', {}).get('rate', 0) or 0),
                    'currency': item.get('currency', 'USD'),
                    'market_country': item.get('marketCountry', 'US'),
                }
                for item in items
            ]

            return {
                'mode': 'live',
                'account_id': account_no,
                'account_seq': account_seq,
                'account_type': account.get('accountType', ''),
                'assets': assets_usd,
                'assets_krw': assets_krw,
                'cash': 0,  # API 에 별도 현금 잔고 필드가 없음
                'daily_pnl': daily_pl_amount,
                'daily_pnl_rate': daily_pl_rate,
                'total_pnl': pl_amount,
                'return_rate': pl_rate,
                'positions': positions,
                'holdings_raw': h_result,
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
            'orderType': 'MARKET',
            'timestamp': 0,
        }

    def place_order(self, symbol: str, side: str, quantity: int) -> Dict[str, Any]:
        payload = self.build_order_payload(symbol, side, quantity)
        if self.mode != 'live':
            return {'mode': 'demo', 'accepted': True, 'payload': payload}

        try:
            acc = self._resolve_account_seq()
            response = requests.post(
                f'{self.base_url}/api/v1/orders',
                headers=self._headers(acc),
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            return {'mode': 'live', 'accepted': False, 'error': 'request_failed', 'payload': payload}

    def execute_signal(self, symbol: str, side: str, quantity: int) -> Dict[str, Any]:
        return self.place_order(symbol, side, quantity)
