# Toss Envelope Bot

이 프로젝트는 S&P500 / 코스피200 / 코스닥150 종목을 대상으로, 엔벨로프(20, 20) 전략으로 매매 신호를 생성하고 백테스트/대시보드 결과를 확인하는 Flask 기반 통합 대시보드입니다.

## 생성된 파일
- [envelope_dashboard.html](envelope_dashboard.html): 스캐너, 차트, 백테스트, 워치리스트, 계좌 탭을 제공하는 대시보드 페이지
- [envelope_server.py](envelope_server.py): Chart.js 대시보드와 `/api/...` REST API를 제공하는 Flask 백엔드 서버
- [backtest_report.txt](backtest_report.txt): 백테스트 결과 요약 텍스트
- [dashboard_data.json](dashboard_data.json): 대시보드에 쓰는 JSON 데이터
- [learning_report.md](learning_report.md): 자동매매 학습 리포트와 개선 액션 요약

## 실행 방법
1. 터미널에서 프로젝트 루트로 이동합니다.
2. 필요한 의존성을 설치합니다: `pip install -r requirements.txt`
3. Flask 백엔드 서버를 실행합니다: `python envelope_server.py`
4. 브라우저에서 http://127.0.0.1:5050/ 를 엽니다.
5. 백테스트 리포트 확인: [backtest_report.txt](backtest_report.txt)
6. 실제 데이터로 다시 돌리고 싶다면 [src/backtest.py](src/backtest.py)와 [src/dashboard_runner.py](src/dashboard_runner.py)를 확장하면 됩니다.

> ⚠️ `python -m http.server 8000`과 같은 정적 서버로는 `/api/...` 호출이 404 오류를 발생시킵니다. 반드시 Flask 서버를 실행하세요.

