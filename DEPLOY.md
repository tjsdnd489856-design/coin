# ☁️ 구글 클라우드(GCP) 전용 서버 배포 가이드

이 가이드는 구글 클라우드 서울 리전(asia-northeast3) 환경에서 24시간 프로그램을 돌리기 위한 안내서입니다.

## 1. 구글 클라우드 서버 설정 (최초 1회)
구글 콘솔에서 **[SSH]** 버튼을 눌러 터미널 창을 연 뒤, 아래 명령어를 순서대로 입력하세요.

```bash
# 1-1. 시스템 최신화 및 도커(Docker) 설치
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose

# 1-2. 사용자 권한 설정 (명령어 입력 후 창을 닫았다가 다시 [SSH] 클릭)
sudo usermod -aG docker $USER
exit
```

## 2. 프로그램 설치 및 가동
다시 **[SSH]** 버튼으로 접속한 후 진행하세요.

```bash
# 2-1. 내 코드 가져오기
git clone https://github.com/tjsdnd489856-design/coin.git
cd coin

# 2-2. 환경 변수 설정 (API 키 입력)
# 아래 명령어를 입력한 뒤, 본인의 업비트 키와 텔레그램 정보를 입력하세요.
nano .env

# --- 편집 모드 (입력 후 Ctrl+O, Enter, Ctrl+X로 저장) ---
# EXCHANGE_ID=upbit
# API_KEY=본인의_업비트_액세스_키
# SECRET_KEY=본인의_업비트_시크릿_키
# TELEGRAM_TOKEN=본인의_텔레그램_봇_토큰
# TELEGRAM_CHAT_ID=본인의_채팅_ID
# SYMBOL_LIST=BTC/KRW,ETH/KRW,SOL/KRW,XRP/KRW
# DRY_RUN=False
# --------------------------------------------------

# 2-3. 24시간 무중단 실행 시작!
docker-compose up -d --build
```

## 3. 실시간 감시 및 관리
- **매매 현황(로그) 보기**: `docker-compose logs -f --tail=50`
- **프로그램 끄기**: `docker-compose down`
- **프로그램 다시 켜기**: `docker-compose up -d`
- **코드 업데이트 (새로운 전략 추가 시)**:
  ```bash
  git pull origin main
  docker-compose up -d --build
  ```

---
**💡 팁**: 구글 클라우드 무료 크레딧은 약 90일간 유효합니다. 기간이 끝나기 전에 오라클 클라우드(평생 무료)로 이전하는 것을 권장합니다.
