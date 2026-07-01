from __future__ import annotations

import json
import os
from typing import Any, Dict


class LLMAnalyzer:
    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider or os.getenv('LLM_PROVIDER', 'openai')

    def analyze_trading_summary(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        api_key = os.getenv('OPENAI_API_KEY') or os.getenv('AZURE_OPENAI_API_KEY')
        if not api_key:
            return self._fallback_analysis(payload)

        try:
            import openai

            client = openai.OpenAI(api_key=api_key)
            prompt = self._build_prompt(payload)
            response = client.responses.create(
                model=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
                input=prompt,
            )
            text = getattr(response, 'output_text', None) or ''
            return {
                'mode': 'llm',
                'summary': text,
                'recommendations': [
                    'LLM 기반 전략 제안 결과를 확인하세요.',
                ],
            }
        except Exception:
            return self._fallback_analysis(payload)

    def _fallback_analysis(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'mode': 'fallback',
            'summary': self._summarize_payload(payload),
            'recommendations': [
                '손실 폭이 큰 구간은 리스크를 축소하고, 승률이 높은 구간의 파라미터를 유지하세요.',
                '실전 전에는 소액 모의투자에서 전략을 검증하세요.',
            ],
        }

    def _summarize_payload(self, payload: Dict[str, Any]) -> str:
        backtest = payload.get('backtest', {})
        account = payload.get('account', {})
        return (
            f"현재 성과 요약: 수익률 {account.get('return_rate', 0) * 100:.1f}%, "
            f"백테스트 총수익률 {backtest.get('total_return', 0) * 100:.1f}%, "
            f"샤프지수 {backtest.get('sharpe', 0):.2f}, "
            f"최대낙폭 {backtest.get('max_drawdown', 0) * 100:.1f}%"
        )

    def _build_prompt(self, payload: Dict[str, Any]) -> str:
        return (
            '당신은 주식 자동매매 전략 분석가입니다. '
            '아래 성과 데이터를 기반으로 전략 개선 제안을 5개 이내로 요약해 주세요.\n' +
            json.dumps(payload, ensure_ascii=False, indent=2)
        )
