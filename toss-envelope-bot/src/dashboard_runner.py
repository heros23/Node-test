from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.api_adapter import build_api_config, get_account_summary
from src.broker_client import BrokerClient
from src.config_store import apply_config_to_environment, load_config
from src.llm_adapter import LLMAnalyzer
from src.learning_report import build_learning_report, write_learning_report_markdown
from src.order_history import append_order_event, load_order_events


def build_dashboard_payload() -> Dict[str, Any]:
    payload = {
        'account': {
            'cash': 10000000,
            'assets': 10850000,
            'daily_pnl': 850000,
            'return_rate': 0.085,
        },
        'backtest': {
            'total_return': 0.243,
            'annualized_return': 0.187,
            'sharpe': 1.42,
            'max_drawdown': -0.121,
            'win_rate': 0.62,
            'trade_count': 18,
        },
        'strategies': [
            {
                'name': '엔벨로프 하단 반등 + 3% 익절',
                'total_return': 0.243,
                'win_rate': 0.62,
                'max_drawdown': -0.121,
                'trade_count': 18,
            },
            {
                'name': '엔벨로프 하단 반등 + 신호 청산',
                'total_return': 0.176,
                'win_rate': 0.58,
                'max_drawdown': -0.142,
                'trade_count': 22,
            },
            {
                'name': '엔벨로프 하단 반등 + 2% 손절',
                'total_return': -0.031,
                'win_rate': 0.41,
                'max_drawdown': -0.163,
                'trade_count': 27,
            },
        ],
    }
    analyzer = LLMAnalyzer()
    payload['llm'] = analyzer.analyze_trading_summary(payload)
    payload['learning_report'] = build_learning_report(payload)
    return payload


def build_runtime_payload(config_path: str | Path | None = None) -> Dict[str, Any]:
    apply_config_to_environment(config_path)
    config = load_config(config_path)
    api_config = build_api_config()
    account_summary = get_account_summary()
    broker = BrokerClient()
    order_preview = broker.build_order_payload('005930', 'buy', 1)
    mock_mode_enabled = bool(config.get('mock_mode', False))
    if mock_mode_enabled:
        order_result = {
            'mode': 'mock',
            'accepted': True,
            'payload': order_preview,
            'message': '모의투자 모드에서 자동매매 시뮬레이션이 실행되었습니다.',
        }
    else:
        order_result = broker.execute_signal('005930', 'buy', 1)
    history_path = Path(__file__).resolve().parent.parent / 'order_history.jsonl'
    append_order_event(history_path, {
        'symbol': order_preview['symbol'],
        'side': order_preview['side'],
        'quantity': order_preview['quantity'],
        'mode': order_result.get('mode', 'demo'),
        'accepted': order_result.get('accepted', True),
    })
    history = load_order_events(history_path)
    account_value = account_summary.get('cash', 10000000)
    asset_value = account_summary.get('assets', 10850000)
    pnl_value = account_summary.get('daily_pnl', 850000)
    rate_value = account_summary.get('return_rate', 0.085)
    status_text = '연동 완료'
    if mock_mode_enabled:
        account_value = 10000000
        asset_value = 10850000
        pnl_value = 850000
        rate_value = 0.085
        status_text = '모의투자 모드 · 시뮬레이션 실행 중'
    elif account_summary.get('error'):
        account_value = 10000000
        asset_value = 10850000
        pnl_value = 850000
        rate_value = 0.085
        status_text = '연동 실패 · 데모값 표시'
    elif account_summary.get('mode') != 'live':
        status_text = '연동 불가 · 데모 모드'
    return {
        'status': 'running',
        'strategy': '엔벨로프 하단 반등',
        'api_mode': api_config['mode'],
        'api_hint': '토스증권 API가 연결되면 예수금/보유자산/당월손익이 자동으로 채워집니다. 현재는 로그인 세션 또는 공식 API 권한이 필요하기 때문에 계좌 정보가 비어 있을 수 있습니다.',
        'account': {
            'account_id': account_summary.get('account_id', 'demo-account'),
            'mode': 'mock' if mock_mode_enabled else account_summary.get('mode', api_config['mode']),
            'cash': account_value,
            'assets': asset_value,
            'daily_pnl': pnl_value,
            'return_rate': rate_value,
            'error': account_summary.get('error'),
            'status_text': status_text,
        },
        'order_preview': order_preview,
        'order_result': order_result,
        'order_history': history,
        'positions': [
            {'symbol': '005930', 'side': 'BUY', 'quantity': 1, 'value': 980000},
            {'symbol': '000660', 'side': 'BUY', 'quantity': 2, 'value': 540000},
        ],
    }


def write_dashboard_payload(path: str | Path | None = None, runtime_path: str | Path | None = None, config_path: str | Path | None = None) -> str:
    dashboard_target = Path(path or Path(__file__).resolve().parent.parent / 'dashboard_data.json')
    runtime_target = Path(runtime_path or Path(__file__).resolve().parent.parent / 'runtime_payload.json')

    dashboard_payload = build_dashboard_payload()
    dashboard_target.write_text(json.dumps(dashboard_payload, ensure_ascii=False, indent=2), encoding='utf-8')
    runtime_target.write_text(json.dumps(build_runtime_payload(config_path), ensure_ascii=False, indent=2), encoding='utf-8')
    write_learning_report_markdown(dashboard_payload.get('learning_report', {}), dashboard_target.parent / 'learning_report.md')
    return str(dashboard_target)


if __name__ == '__main__':
    print(write_dashboard_payload())
