from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


def get_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / 'config.json'


def save_config(path: str | Path | None = None, config: Dict[str, Any] | None = None) -> str:
    target = Path(path or get_config_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    data = config or {}
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(target)


def load_config(path: str | Path | None = None) -> Dict[str, Any]:
    target = Path(path or get_config_path())
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding='utf-8'))
    except Exception:
        return {}


def apply_config_to_environment(path: str | Path | None = None) -> Dict[str, Any]:
    config = load_config(path)
    resolved = {
        'TOSS_BASE_URL': config.get('base_url', ''),
        'TOSS_API_KEY': config.get('api_key', ''),
        'TOSS_API_SECRET': config.get('api_secret', ''),
    }
    for key, value in resolved.items():
        if value:
            os.environ[key] = str(value)
        else:
            os.environ.pop(key, None)
    return config
