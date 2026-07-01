import pandas as pd


class EnvelopeStrategy:
    def __init__(self, window: int = 20, deviation: float = 0.02):
        self.window = window
        self.deviation = deviation

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        if "close" not in df.columns:
            raise ValueError("DataFrame must include 'close' column")

        close = df["close"].astype(float)
        middle = close.rolling(window=self.window, min_periods=self.window).mean()
        upper = middle * (1 + self.deviation)
        lower = middle * (1 - self.deviation)

        signals = pd.Series("HOLD", index=df.index)

        for i in range(self.window, len(df)):
            prev_close = close.iloc[i - 1]
            curr_close = close.iloc[i]
            prev_lower = lower.iloc[i - 1]
            curr_lower = lower.iloc[i]
            prev_upper = upper.iloc[i - 1]
            curr_upper = upper.iloc[i]

            if prev_close <= prev_lower and curr_close > curr_lower:
                signals.iloc[i] = "BUY"
            elif prev_close >= prev_upper and curr_close < curr_upper:
                signals.iloc[i] = "SELL"

        return signals
