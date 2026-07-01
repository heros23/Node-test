from src.config_store import load_config, save_config


def test_save_and_load_config(tmp_path) -> None:
    path = tmp_path / 'config.json'
    save_config(path, {'base_url': 'https://example', 'api_key': 'k', 'api_secret': 's'})
    config = load_config(path)
    assert config['api_key'] == 'k'
    assert config['api_secret'] == 's'
