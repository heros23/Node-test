from pathlib import Path

from src.dashboard_runner import write_dashboard_payload

if __name__ == '__main__':
    output = write_dashboard_payload(
        Path(__file__).resolve().parent / 'dashboard_data.json',
        Path(__file__).resolve().parent / 'runtime_payload.json',
    )
    print(f'Wrote dashboard data to {output}')
