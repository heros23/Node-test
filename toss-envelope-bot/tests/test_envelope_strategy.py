import pandas as pd

from src.envelope_strategy import EnvelopeStrategy


def test_buy_and_sell_signals_on_envelope_bands():
    df = pd.DataFrame(
        {
            "close": [100, 95, 90, 92, 96, 100, 102, 105],
        }
    )

    strategy = EnvelopeStrategy(window=3, deviation=0.1)
    signals = strategy.generate_signals(df)

    assert signals.iloc[0] == "HOLD"
    assert signals.iloc[1] == "BUY"
    assert signals.iloc[3] == "SELL"
