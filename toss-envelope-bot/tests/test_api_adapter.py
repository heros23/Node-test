from src.api_adapter import build_api_config, resolve_api_mode


def test_default_api_config_is_demo_safe() -> None:
    config = build_api_config()
    assert config['mode'] in {'demo', 'live'}
    assert 'base_url' in config


def test_resolve_api_mode_returns_demo_without_credentials() -> None:
    mode = resolve_api_mode(None, None)
    assert mode == 'demo'
