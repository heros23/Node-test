import pandas as pd

from src.backtest_local import LocalEnvelopeBacktester

if __name__ == '__main__':
    data = {
        'sample_stock': pd.DataFrame({
            'close': [100, 98, 96, 95, 97, 99, 101, 103, 105, 102, 100, 103, 106, 108, 110, 107, 104, 106, 109, 111]
        }, index=pd.date_range('2024-01-01', periods=20, freq='D'))
    }
    bt = LocalEnvelopeBacktester(data=data)
    results = bt.run(exit_rule='tp', take_profit=0.03, stop_loss=0.03)
    for r in results:
        print(r)
