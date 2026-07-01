# Toss Envelope Bot

이 프로젝트는 코스피 200 종목과 코스닥 150 종목만을 대상으로, 엔벨로프(20, 20) 전략으로 매매 신호를 생성하고 백테스트/대시보드 결과를 확인하는 기본 구조입니다.

## 생성된 파일
- [dashboard.html](dashboard.html): 계좌 요약과 백테스트 요약을 보여주는 대시보드 페이지
- [backtest_report.txt](backtest_report.txt): 백테스트 결과 요약 텍스트
- [dashboard_data.json](dashboard_data.json): 대시보드에 쓰는 JSON 데이터
- [learning_report.md](learning_report.md): 자동매매 학습 리포트와 개선 액션 요약

## 실행 방법
1. 터미널에서 프로젝트 루트로 이동합니다.
2. 다음 명령으로 대시보드를 실행합니다: `python -m http.server 8000 --directory .`
3. 브라우저에서 http://127.0.0.1:8000/dashboard.html 을 엽니다.
4. 백테스트 리포트 확인: [backtest_report.txt](backtest_report.txt)
5. 실제 데이터로 다시 돌리고 싶다면 [src/backtest.py](src/backtest.py)와 [src/dashboard_runner.py](src/dashboard_runner.py)를 확장하면 됩니다.
