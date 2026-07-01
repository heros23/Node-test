from __future__ import annotations

import os
from typing import Any, Dict

from src.broker_client import BrokerClient
from src.config_store import apply_config_to_environment


def build_api_config() -> Dict[str, Any]:
    apply_config_to_environment()
    api_key = os.getenv('TOSS_API_KEY') or ''
    api_secret = os.getenv('TOSS_API_SECRET') or ''
    base_url = os.getenv('TOSS_BASE_URL', 'https://api.demo.toss.example')
    mode = resolve_api_mode(api_key, api_secret)
    return {
        'mode': mode,
        'base_url': base_url,
        'api_key': api_key,
        'api_secret': api_secret,
        'headers': {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}' if api_key else 'Bearer demo',
        },
    }


def resolve_api_mode(api_key: str | None, api_secret: str | None) -> str:
    if api_key and api_secret:
        return 'live'
    return 'demo'


def get_account_summary() -> Dict[str, Any]:
    config = build_api_config()
    if config['mode'] != 'live':
        return {
            'mode': 'demo',
            'account_id': 'demo-account',
            'cash': 10000000,
            'assets': 10850000,
            'daily_pnl': 850000,
            'return_rate': 0.085,
            'error': '실제 인증 정보가 없거나 Base URL이 데모 주소라서 데모 모드로 표시 중입니다.',
        }
    broker = BrokerClient(config['base_url'], config['api_key'], config['api_secret'])
    return broker.get_account_summary()
