from __future__ import annotations

import json
from pathlib import Path

from src.data_loader import load_csv_price_data
from src.backtest_local import LocalEnvelopeBacktester


def run_from_csv(folder: str | Path | None = None) -> dict:
    data = load_csv_price_data(folder)
    if not data:
        return {
            'status': 'no_data',
            'message': 'CSV data folder is empty or missing.',
        }

    tester = LocalEnvelopeBacktester(data=data)
    results = tester.run(exit_rule='tp', take_profit=0.03, stop_loss=0.03)
    summary = {
        'total_return': round(sum(r.total_return for r in results) / len(results), 4) if results else 0.0,
        'annualized_return': round(sum(r.annualized_return for r in results) / len(results), 4) if results else 0.0,
        'sharpe': round(sum(r.sharpe for r in results) / len(results), 4) if results else 0.0,
        'max_drawdown': round(sum(r.max_drawdown for r in results) / len(results), 4) if results else 0.0,
        'win_rate': round(sum(r.win_rate for r in results) / len(results), 4) if results else 0.0,
        'trade_count': int(sum(r.trade_count for r in results) / len(results)) if results else 0,
    }

    output_path = Path(__file__).resolve().parent.parent / 'dashboard_data.json'
    output_path.write_text(json.dumps({'account': {'cash': 10000000, 'assets': 10850000, 'daily_pnl': 850000, 'return_rate': 0.085}, 'backtest': summary, 'strategies': [{'name': '엔벨로프 하단 반등 + 3% 익절', 'total_return': summary['total_return'], 'win_rate': summary['win_rate'], 'max_drawdown': summary['max_drawdown'], 'trade_count': summary['trade_count']}]}, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'status': 'ok', 'summary': summary, 'output': str(output_path)}


if __name__ == '__main__':
    print(run_from_csv())
