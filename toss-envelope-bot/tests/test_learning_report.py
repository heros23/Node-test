from src.learning_report import build_learning_report


def test_build_learning_report_returns_sections() -> None:
    report = build_learning_report({
        'account': {'return_rate': 0.08},
        'backtest': {'total_return': 0.12, 'sharpe': 1.2, 'max_drawdown': -0.08},
        'strategies': [{'name': 'baseline', 'total_return': 0.12, 'win_rate': 0.6}],
    })

    assert report['summary']
    assert 'improvements' in report
    assert 'lessons' in report
    assert 'next_actions' in report
