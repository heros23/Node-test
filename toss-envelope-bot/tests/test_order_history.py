from src.order_history import append_order_event, load_order_events


def test_order_history_round_trip(tmp_path) -> None:
    path = tmp_path / 'orders.jsonl'
    append_order_event(path, {'symbol': '005930', 'side': 'buy', 'quantity': 1})
    events = load_order_events(path)
    assert len(events) == 1
    assert events[0]['symbol'] == '005930'
