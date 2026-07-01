from __future__ import annotations

from typing import List, Dict, Any

from src.backtest import EnvelopeBacktester, get_symbols


def compare_exit_rules() -> List[Dict[str, Any]]:
    symbols = get_symbols()[:30]
    backtester = EnvelopeBacktester(symbols=symbols, start='2024-01-01', end='2026-06-30')

    variants = [
        ('3% 익절', 'tp', 0.03, 0.02),
        ('신호 청산', 'hold', 0.0, 0.0),
        ('2% 손절', 'tp', 0.02, 0.02),
    ]

    results = []
    for name, exit_rule, take_profit, stop_loss in variants:
        run_results = backtester.run(exit_rule=exit_rule, take_profit=take_profit, stop_loss=stop_loss)
        summary = backtester.summarize(run_results)
        results.append({
            'name': name,
            'total_return': summary['total_return'],
            'win_rate': summary['win_rate'],
            'max_drawdown': summary['max_drawdown'],
            'trade_count': summary['trade_count'],
        })
    return results


if __name__ == '__main__':
    for row in compare_exit_rules():
        print(row)
