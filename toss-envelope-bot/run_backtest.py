from src.backtest import EnvelopeBacktester, get_symbols

if __name__ == '__main__':
    symbols = get_symbols()
    print(f'Loaded {len(symbols)} symbols')
    bt = EnvelopeBacktester(symbols=symbols, start='2024-01-01', end='2026-06-30')
    results = bt.run(exit_rule='tp', take_profit=0.03, stop_loss=0.03)
    print('Results count:', len(results))
    if results:
        results_sorted = sorted(results, key=lambda x: x.total_return, reverse=True)
        for r in results_sorted[:10]:
            print(r)
