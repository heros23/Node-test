from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def load_dashboard_payload() -> Dict[str, Any]:
    return {
        "account": {
            "cash": 10000000,
            "assets": 10850000,
            "daily_pnl": 850000,
            "return_rate": 0.085,
        },
        "backtest": {
            "total_return": 0.243,
            "annualized_return": 0.187,
            "sharpe": 1.42,
            "max_drawdown": -0.121,
        },
        "strategies": [
            {
                "name": "엔벨로프 하단 반등 + 3% 익절",
                "total_return": 0.243,
                "win_rate": 0.62,
                "max_drawdown": -0.121,
                "trade_count": 18,
            },
            {
                "name": "엔벨로프 하단 반등 + 신호 청산",
                "total_return": 0.176,
                "win_rate": 0.58,
                "max_drawdown": -0.142,
                "trade_count": 22,
            },
            {
                "name": "엔벨로프 하단 반등 + 2% 손절",
                "total_return": -0.031,
                "win_rate": 0.41,
                "max_drawdown": -0.163,
                "trade_count": 27,
            },
        ],
    }


def write_dashboard_json(path: str | Path | None = None) -> str:
    target = Path(path or Path(__file__).resolve().parent.parent / "dashboard_data.json")
    target.write_text(json.dumps(load_dashboard_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)
