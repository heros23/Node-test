from src.broker_client import BrokerClient


def test_order_execution_returns_preview_in_demo_mode() -> None:
    client = BrokerClient()
    result = client.place_order('005930', 'buy', 1)
    assert result['mode'] == 'demo'
    assert result['accepted'] is True
