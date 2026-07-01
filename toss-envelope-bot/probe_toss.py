import json
from pathlib import Path
import requests

conf = json.loads(Path('config.json').read_text(encoding='utf-8'))
base = conf.get('base_url', '')
key = conf.get('api_key', '')
secret = conf.get('api_secret', '')
headers = {'Authorization': f'Bearer {key}', 'X-API-SECRET': secret, 'Content-Type': 'application/json'}
urls = [
    base,
    base.rstrip('/') + '/accounts',
    base.rstrip('/') + '/account',
    'https://api.tossinvest.com/accounts',
    'https://api.tossinvest.com/account',
    'https://api.tossinvest.com/v1/accounts',
    'https://api.tossinvest.com/v1/account',
    'https://www.tossinvest.com/api/accounts',
    'https://www.tossinvest.com/api/account',
]
for url in urls:
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print('URL', url)
        print('STATUS', r.status_code)
        print(r.text[:300].replace('\n', ' ')[:300])
        print('---')
    except Exception as e:
        print('URL', url, 'ERR', e)
        print('---')
