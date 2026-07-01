from src.broker_client import BrokerClient


def test_client_uses_demo_mode_without_credentials() -> None:
    client = BrokerClient()
    account = client.get_account_summary()
    assert account['mode'] == 'demo'
    assert 'account_id' in account
    assert 'error' in account


def test_client_can_prepare_order_payload() -> None:
    client = BrokerClient()
    payload = client.build_order_payload('005930', 'buy', 1)
    assert payload['symbol'] == '005930'
    assert payload['side'] == 'buy'
    assert payload['quantity'] == 1


def test_client_marks_web_page_url_as_incompatible() -> None:
    client = BrokerClient(base_url='https://www.tossinvest.com/account', api_key='key', api_secret='secret')
    account = client.get_account_summary()
    assert account['mode'] == 'demo'
    assert '실제 토스 계좌 연동에는 로그인 세션 또는 공식 API 권한이 필요합니다.' in account['error']
