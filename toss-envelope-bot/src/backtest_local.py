from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    strategy_name: str
    total_return: float
    annualized_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    trade_count: int


class LocalEnvelopeBacktester:
    def __init__(self, data: Dict[str, pd.DataFrame], window: int = 20, deviation: float = 0.02):
        self.data = data
        self.window = window
        self.deviation = deviation

    def _calculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df['close'].astype(float)
        middle = close.rolling(window=self.window, min_periods=self.window).mean()
        upper = middle * (1 + self.deviation)
        lower = middle * (1 - self.deviation)

        signal = pd.Series(0, index=df.index)
        for i in range(self.window, len(df)):
            prev_close = close.iloc[i - 1]
            curr_close = close.iloc[i]
            prev_lower = lower.iloc[i - 1]
            curr_lower = lower.iloc[i]
            prev_upper = upper.iloc[i - 1]
            curr_upper = upper.iloc[i]

            if prev_close <= prev_lower and curr_close > curr_lower:
                signal.iloc[i] = 1
            elif prev_close >= prev_upper and curr_close < curr_upper:
                signal.iloc[i] = -1

        df = df.copy()
        df['signal'] = signal
        df['middle'] = middle
        df['upper'] = upper
        df['lower'] = lower
        return df

    def _run_strategy(self, df: pd.DataFrame, exit_rule: str, take_profit: float, stop_loss: float) -> Tuple[float, float, float, float, float, int]:
        cash = 1.0
        position = 0.0
        entry_price = 0.0
        trades = []
        equity = []

        for _, row in df.iterrows():
            if position == 0.0 and row['signal'] == 1:
                position = cash
                entry_price = row['close']
                continue

            if position > 0.0:
                price = row['close']
                if exit_rule == 'tp':
                    if price >= entry_price * (1 + take_profit):
                        cash = position * (1 + take_profit)
                        trades.append(('tp', entry_price, price))
                        position = 0.0
                        entry_price = 0.0
                    elif price <= entry_price * (1 - stop_loss):
                        cash = position * (1 - stop_loss)
                        trades.append(('sl', entry_price, price))
                        position = 0.0
                        entry_price = 0.0
                elif exit_rule == 'signal':
                    if row['signal'] == -1:
                        cash = position
                        trades.append(('signal', entry_price, price))
                        position = 0.0
                        entry_price = 0.0

            equity.append(cash if position == 0.0 else cash * (1 + (row['close'] / entry_price - 1)))

        if len(equity) == 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0

        equity_curve = pd.Series(equity, index=df.index)
        equity_curve = equity_curve / equity_curve.iloc[0]
        total_return = float(equity_curve.iloc[-1] - 1)
        annualized_return = float((1 + total_return) ** (252 / len(equity_curve)) - 1)
        daily_returns = np.diff(np.log(equity_curve + 1e-9))
        sharpe = float(daily_returns.mean() / (daily_returns.std() + 1e-9) * np.sqrt(252))
        max_drawdown = float((1 - equity_curve / equity_curve.cummax()).max())
        win_rate = float(sum(1 for t in trades if t[0] != 'sl') / len(trades)) if trades else 0.0
        return total_return, annualized_return, sharpe, max_drawdown, win_rate, len(trades)

    def run(self, exit_rule: str = 'tp', take_profit: float = 0.03, stop_loss: float = 0.03) -> List[BacktestResult]:
        results = []
        for name, df in self.data.items():
            df2 = self._calculate_signals(df)
            result = self._run_strategy(df2, exit_rule, take_profit, stop_loss)
            results.append(BacktestResult(name, *result))
        return results
