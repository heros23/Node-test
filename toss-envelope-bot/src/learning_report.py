from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def build_learning_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    backtest = payload.get('backtest', {})
    account = payload.get('account', {})
    strategies = payload.get('strategies', [])

    total_return = backtest.get('total_return', 0.0) or 0.0
    sharpe = backtest.get('sharpe', 0.0) or 0.0
    max_dd = backtest.get('max_drawdown', 0.0) or 0.0
    win_rate = backtest.get('win_rate', 0.0) or 0.0

    lessons: List[str] = []
    improvements: List[str] = []
    next_actions: List[str] = []

    if total_return > 0:
        lessons.append('최근 성과는 양의 수익 흐름을 보여 주므로, 현재 진입 조건을 유지하되 리스크 관리에 집중합니다.')
    else:
        lessons.append('현재 수익 흐름이 약하므로, 진입 타이밍과 익절 조건을 재검토해야 합니다.')

    if sharpe >= 1.0:
        lessons.append('샤프 지수가 양호하여, 전략의 안정성은 비교적 확보된 상태입니다.')
    else:
        lessons.append('샤프 지수가 낮아 변동성 완화가 필요합니다.')

    if max_dd < -0.1:
        improvements.append('최대 낙폭이 큰 구간은 손절/리스크 비중을 낮추는 방식으로 보완합니다.')
    else:
        improvements.append('낙폭 관리가 양호하므로 현재 리스크 비중을 유지합니다.')

    if win_rate >= 0.6:
        improvements.append('승률이 높으므로 진입 빈도는 유지하되, 익절 타이밍을 더 세밀하게 조정합니다.')
    else:
        improvements.append('승률이 낮으므로 진입 기준을 더 엄격하게 조정합니다.')

    if strategies:
        best = max(strategies, key=lambda s: s.get('total_return', 0.0), default={})
        improvements.append(f"가장 성과가 좋았던 전략 '{best.get('name', 'unknown')}'의 파라미터를 기준으로 실험을 확장합니다.")

    next_actions.append('다음 1주일 동안 진입/청산 조건을 기록하고, 손실이 큰 구간을 다시 검증합니다.')
    next_actions.append('모의투자에서 파라미터를 조정한 뒤, 실전 전 최종 승인합니다.')

    return {
        'summary': (
            f"현재 전략은 수익률 {total_return * 100:.1f}%, 샤프지수 {sharpe:.2f}, 최대낙폭 {max_dd * 100:.1f}%를 기록했습니다. "
            f"계좌 수익률은 {account.get('return_rate', 0.0) * 100:.1f}%입니다."
        ),
        'lessons': lessons,
        'improvements': improvements,
        'next_actions': next_actions,
    }


def write_learning_report_markdown(report: Dict[str, Any], path: str | Path | None = None) -> str:
    target = Path(path or Path(__file__).resolve().parent.parent / 'learning_report.md')
    lines = [
        '# 자동매매 학습 리포트',
        '',
        '## 요약',
        report.get('summary', ''),
        '',
        '## 배운 점',
    ]
    for item in report.get('lessons', []):
        lines.append(f'- {item}')
    lines.extend(['', '## 보완 방향'])
    for item in report.get('improvements', []):
        lines.append(f'- {item}')
    lines.extend(['', '## 다음 액션'])
    for item in report.get('next_actions', []):
        lines.append(f'- {item}')
    target.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(target)
