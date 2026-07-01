# 실행 가이드

## 1. 빠르게 시작하기
- Windows: start.bat 실행
- 또는 python run_dashboard.py 후 dashboard.html 열기

## 2. 환경 변수 설정
- .env.example를 참고해 실제 값으로 변경하세요.
- 필수 값: TOSS_BASE_URL, TOSS_API_KEY, TOSS_API_SECRET
- 값이 없으면 자동으로 demo 모드로 동작합니다.

## 3. 백테스트/대시보드
- python run_dashboard.py
- 대시보드 열기: dashboard.html

## 4. 신호 데모 실행
- python run_signal_demo.py

## 5. 실시간 실행
- python src/live_runner.py
- Ctrl+C로 종료

## 6. API 연동 확인
- 대시보드의 운영 상태에서 API 모드가 demo/live로 표시됩니다.
- 실제 거래를 연결하려면 .env에 실 API 자격 증명을 넣고 다시 실행하면 됩니다.

## 6. 주의사항
- 실제 주문은 소액/모의투자부터 시작하세요.
- API 키는 코드에 직접 넣지 말고 환경 변수로 관리하세요.
