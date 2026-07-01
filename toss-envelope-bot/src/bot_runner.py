from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.trading_bot import TradingBot


def build_runtime_payload() -> Dict[str, Any]:
    bot = TradingBot()
    account = bot.sync_account() if False else {'account_id': 'demo', 'cash': 10000000, 'positions': []}
    return {
        'status': 'ready',
        'account': account,
        'positions': bot.positions,
        'strategy': 'envelope-bottom-rebound',
    }


def write_runtime_payload(path: str | Path | None = None) -> str:
    target = Path(path or Path(__file__).resolve().parent.parent / 'runtime_payload.json')
    target.write_text(json.dumps(build_runtime_payload(), ensure_ascii=False, indent=2), encoding='utf-8')
    return str(target)


if __name__ == '__main__':
    print(write_runtime_payload())
