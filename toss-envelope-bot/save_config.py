from __future__ import annotations

import json
import sys
from pathlib import Path

from src.config_store import save_config


if __name__ == '__main__':
    if len(sys.argv) > 1:
        payload = json.loads(sys.argv[1])
    else:
        payload = {
            'base_url': '',
            'api_key': '',
            'api_secret': '',
        }
    save_config(Path(__file__).resolve().parent / 'config.json', payload)
    print(json.dumps({'status': 'ok', 'message': 'Configured'}))
