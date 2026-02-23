# AI 지능형 매매 시스템 운영 및 인계 보고서

## 1. 시스템 개요
본 시스템은 업비트(Upbit) 거래소에서 BTC, ETH, XRP를 대상으로 하는 **AI 적응형 자동 매매 봇**입니다.

## 2. 주요 고도화 사항 (2026-02-21)
### 전략 로직
- **ATR 기반 동적 TP/SL:** 시장 변동성에 맞춘 익절/손절가 설정.
- **수수료 인지형 계산:** 왕복 수수료(0.1%) 차감 후 순수익 기준 판단.
- **버그 수정:** ReversalStrategy의 본절 방어 논리 오류 해결.

### AI 및 시장 분석
- **Profit Factor 튜닝:** 승률이 아닌 손익비와 기대값 중심의 파라미터 최적화.
- **시장 필터:** BTC EMA 정배열 및 변동성 필터를 통한 횡보장/하락장 회피.

## 3. 서버 운영 가이드 (GCP)
### 업데이트 및 재시작
```bash
cd ~/coin
git pull origin main
source venv/bin/activate
pip install pandas
pm2 delete all
pkill -9 python
pm2 start main.py --interpreter venv/bin/python3 --name "coin-bot"
pm2 save
pm2 logs coin-bot
```

### 주의사항
- **IP 화이트리스트:** 서버 IP가 업비트 API에 등록되어 있어야 함.
- **중복 실행:** 텔레그램 봇 토큰은 한 곳에서만 사용 가능 (409 에러 주의).
- **시장가 주문:** 업비트 특성에 맞게 '투자 금액' 기준 주문 로직 적용됨.
