from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd


def load_csv_price_data(folder: str | Path | None = None) -> Dict[str, pd.DataFrame]:
    folder = Path(folder or Path(__file__).resolve().parent.parent / 'data')
    if not folder.exists():
        return {}

    frames: Dict[str, pd.DataFrame] = {}
    for path in sorted(folder.glob('*.csv')):
        df = pd.read_csv(path, parse_dates=['Date'])
        if 'Close' in df.columns:
            df = df[['Date', 'Close']].rename(columns={'Date': 'date', 'Close': 'close'})
        elif 'close' in df.columns:
            df = df[['date', 'close']]
        else:
            continue
        df = df.sort_values('date')
        df.set_index('date', inplace=True)
        frames[path.stem] = df
    return frames
