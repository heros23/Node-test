import json
from pathlib import Path

from src.config_store import save_config
from src.dashboard_runner import write_dashboard_payload


def test_write_dashboard_payload_creates_runtime_payload(tmp_path: Path) -> None:
    dashboard_path = tmp_path / 'dashboard_data.json'
    runtime_path = tmp_path / 'runtime_payload.json'

    output = write_dashboard_payload(dashboard_path, runtime_path)

    assert output == str(dashboard_path)
    assert dashboard_path.exists()
    assert runtime_path.exists()

    dashboard_data = dashboard_path.read_text(encoding='utf-8')
    runtime_data = runtime_path.read_text(encoding='utf-8')

    assert 'backtest' in dashboard_data
    assert 'positions' in runtime_data


def test_write_dashboard_payload_uses_mock_mode_when_enabled(tmp_path: Path) -> None:
    dashboard_path = tmp_path / 'dashboard_data.json'
    runtime_path = tmp_path / 'runtime_payload.json'
    config_path = tmp_path / 'config.json'
    save_config(config_path, {'mock_mode': True})

    write_dashboard_payload(dashboard_path, runtime_path, config_path)

    runtime_data = json.loads(runtime_path.read_text(encoding='utf-8'))

    assert runtime_data['account']['mode'] == 'mock'
    assert runtime_data['order_result']['mode'] == 'mock'
    assert runtime_data['order_result']['accepted'] is True
