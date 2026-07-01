from src.llm_adapter import LLMAnalyzer


def test_analyzer_returns_fallback_when_no_credentials() -> None:
    analyzer = LLMAnalyzer()
    result = analyzer.analyze_trading_summary({
        'account': {'return_rate': 0.08},
        'backtest': {'total_return': 0.12, 'sharpe': 1.2, 'max_drawdown': -0.08},
        'strategies': [{'name': 'baseline', 'total_return': 0.12, 'win_rate': 0.6}],
    })

    assert result['mode'] == 'fallback'
    assert 'summary' in result
    assert 'recommendations' in result
