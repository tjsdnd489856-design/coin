# Coin Project: AI Trading Learner

기존 자동 코인 매매 시스템에 **거래별 학습(온라인/오프라인) 모듈**을 통합한 프로젝트입니다.

## 학습 파이프라인 아키텍처
1. **Feature Store**: 실시간 시장 데이터와 거래 내역을 정규화하여 저장 (Redis/PostgreSQL).
2. **Online Learner**: 주문 발생 시 실시간으로 피처를 생성하고 최적의 집행 전략(분할, 호가 등)을 제안.
   - 체결 결과 피드백을 받아 경량 모델을 실시간 업데이트.
3. **Offline Trainer**: 누적 데이터를 배치로 학습하여 고성능 모델(XGBoost/LGBM)을 생성하고 배포.
4. **Model Registry**: 모델 버전 관리 및 A/B 테스트 지원.

## 환경 변수 설정

| 변수명 | 설명 | 기본값 |
|---|---|---|
| `DRY_RUN` | `True`일 경우 실제 주문 및 DB 쓰기 방지 | `True` |
| `FEATURE_STORE_DB_URL` | PostgreSQL 연결 문자열 | `postgresql://...` |
| `REDIS_URL` | Redis 연결 문자열 | `redis://...` |
| `LOG_LEVEL` | 로깅 레벨 (INFO, DEBUG 등) | `INFO` |
| `AUTO_APPLY_RECOMMENDATIONS` | AI 추천 전략 자동 적용 여부 | `False` |

## 운영 가이드
- **배포**: `src/learner` 패키지를 포함하여 배포. 초기 구동 시 `DRY_RUN=True` 권장.
- **모니터링**: 로그의 `trace_id`를 통해 주문 생성부터 체결, 학습 피드백까지 추적 가능.
- **테스트**: `pytest tests/` 명령어로 학습 모듈의 무결성 검증.

## 라이선스
MIT License
