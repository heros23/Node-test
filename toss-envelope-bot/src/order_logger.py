from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class OrderLogger:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or Path(__file__).resolve().parent.parent / 'order_log.jsonl')

    def append(self, payload: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            'timestamp': datetime.utcnow().isoformat(),
            **payload,
        }
        with self.path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
