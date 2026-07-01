from pathlib import Path

from src.dashboard_data import write_dashboard_json

if __name__ == '__main__':
    output = write_dashboard_json(Path(__file__).resolve().parent / 'dashboard_data.json')
    print(f'Wrote {output}')
