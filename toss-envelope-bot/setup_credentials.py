from __future__ import annotations

from src.config_store import save_config


if __name__ == '__main__':
    base_url = input('TOSS Base URL: ').strip()
    api_key = input('TOSS API Key: ').strip()
    api_secret = input('TOSS API Secret: ').strip()
    save_config(None, {
        'base_url': base_url,
        'api_key': api_key,
        'api_secret': api_secret,
    })
    print('Credentials saved to config.json')
