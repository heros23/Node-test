from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Tuple

import FinanceDataReader as fdr
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


class EnvelopeBacktester:
    def __init__(self, symbols: List[str], start: str, end: str, window: int = 20, deviation: float = 0.02):
        self.symbols = symbols
        self.start = start
        self.end = end
        self.window = window
        self.deviation = deviation

    def _get_price_data(self, symbol: str) -> pd.DataFrame:
        df = fdr.DataReader(symbol, self.start, self.end)
        if df.empty:
            return df
        df = df[['Close']].rename(columns={'Close': 'close'})
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        return df

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
        entry_date = None
        equity = []
        trades = []

        for idx, row in df.iterrows():
            if position == 0.0 and row['signal'] == 1:
                position = cash
                entry_price = row['close']
                entry_date = idx
                continue

            if position > 0.0:
                price = row['close']
                if exit_rule == 'tp':
                    if price >= entry_price * (1 + take_profit):
                        cash = position * (1 + take_profit)
                        trades.append((entry_date, idx, entry_price, price, 'tp'))
                        position = 0.0
                        entry_price = 0.0
                        entry_date = None
                    elif price <= entry_price * (1 - stop_loss):
                        cash = position * (1 - stop_loss)
                        trades.append((entry_date, idx, entry_price, price, 'sl'))
                        position = 0.0
                        entry_price = 0.0
                        entry_date = None
                elif exit_rule == 'hold':
                    if row['signal'] == -1:
                        cash = position
                        trades.append((entry_date, idx, entry_price, price, 'signal'))
                        position = 0.0
                        entry_price = 0.0
                        entry_date = None

            equity.append(cash if position == 0.0 else cash * (1 + (row['close'] / entry_price - 1)))

        if position > 0.0:
            equity[-1] = cash * (1 + (df['close'].iloc[-1] / entry_price - 1))

        returns = np.array(equity)
        if len(returns) < 2:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0

        equity_curve = pd.Series(returns, index=df.index)
        equity_curve = equity_curve / equity_curve.iloc[0]
        total_return = float(equity_curve.iloc[-1] - 1)
        annualized_return = float((1 + total_return) ** (252 / len(equity_curve)) - 1)
        sharpe = float(np.mean(np.diff(np.log(equity_curve + 1e-9))) / (np.std(np.diff(np.log(equity_curve + 1e-9))) + 1e-9) * np.sqrt(252))
        max_drawdown = float((1 - equity_curve / equity_curve.cummax()).max())
        wins = sum(1 for t in trades if t[4] in {'tp', 'signal'})
        win_rate = wins / len(trades) if trades else 0.0
        return total_return, annualized_return, sharpe, max_drawdown, win_rate, len(trades)

    def run(self, exit_rule: str = 'tp', take_profit: float = 0.03, stop_loss: float = 0.03) -> List[BacktestResult]:
        results = []
        for symbol in self.symbols:
            try:
                df = self._get_price_data(symbol)
                if df.empty or len(df) < self.window + 10:
                    continue
                df = self._calculate_signals(df)
                result = self._run_strategy(df, exit_rule, take_profit, stop_loss)
                results.append(BacktestResult(
                    strategy_name=symbol,
                    total_return=result[0],
                    annualized_return=result[1],
                    sharpe=result[2],
                    max_drawdown=result[3],
                    win_rate=result[4],
                    trade_count=result[5],
                ))
            except Exception:
                continue

        return results

    def summarize(self, results: List[BacktestResult]) -> dict:
        if not results:
            return {
                'total_return': 0.0,
                'annualized_return': 0.0,
                'sharpe': 0.0,
                'max_drawdown': 0.0,
                'win_rate': 0.0,
                'trade_count': 0,
            }
        return {
            'total_return': round(float(np.mean([r.total_return for r in results])), 4),
            'annualized_return': round(float(np.mean([r.annualized_return for r in results])), 4),
            'sharpe': round(float(np.mean([r.sharpe for r in results])), 4),
            'max_drawdown': round(float(np.mean([r.max_drawdown for r in results])), 4),
            'win_rate': round(float(np.mean([r.win_rate for r in results])), 4),
            'trade_count': int(np.mean([r.trade_count for r in results])),
        }


def get_symbols() -> List[str]:
    kospi = fdr.StockListing('KOSPI')
    kosdaq = fdr.StockListing('KOSDAQ')
    symbols = []
    if not kospi.empty:
        symbols.extend(kospi['Symbol'].tolist()[:200])
    if not kosdaq.empty:
        symbols.extend(kosdaq['Symbol'].tolist()[:150])
    return symbols
