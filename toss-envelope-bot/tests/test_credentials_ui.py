from src.config_store import load_config, save_config


def test_config_can_round_trip_credentials(tmp_path) -> None:
    path = tmp_path / 'config.json'
    save_config(path, {'base_url': 'https://example', 'api_key': 'key', 'api_secret': 'secret'})
    config = load_config(path)
    assert config['api_key'] == 'key'
    assert config['api_secret'] == 'secret'
