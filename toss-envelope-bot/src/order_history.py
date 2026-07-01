from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def append_order_event(path: str | Path, event: Dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **event,
    }
    with target.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    return str(target)


def load_order_events(path: str | Path) -> List[Dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []

    events: List[Dict[str, Any]] = []
    with target.open('r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events
