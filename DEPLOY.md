# 🚀 코인 매매 시스템 서버 배포 가이드 (24시간 무중단)

이 가이드는 서버(Ubuntu 리눅스) 환경에서 24시간 프로그램을 돌리기 위한 핵심 명령어 모음입니다.

## 1. 서버 환경 구축 (최초 1회)
서버에 접속한 후 아래 명령어를 순서대로 입력하세요.

```bash
# 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# 도커(Docker) 설치
sudo apt install -y docker.io docker-compose

# 권한 설정 (입력 후 재접속 필요)
sudo usermod -aG docker $USER
exit
```

## 2. 프로그램 실행 및 업데이트
서버에 재접속한 후 아래 과정을 진행하세요.

```bash
# 코드 내려받기 (최초)
git clone https://github.com/tjsdnd489856-design/coin.git
cd coin

# 설정 파일 만들기 (API 키 입력)
# 아래 명령어를 치고 메모장처럼 뜨면 내용을 채우세요.
nano .env

# --- .env 파일에 들어갈 내용 예시 ---
# EXCHANGE_ID=upbit
# API_KEY=내_업비트_키
# SECRET_KEY=내_업비트_비밀키
# TELEGRAM_TOKEN=내_텔레그램_토큰
# TELEGRAM_CHAT_ID=내_채팅_아이디
# SYMBOL_LIST=BTC/KRW,ETH/KRW
# DRY_RUN=False  (실제 매매 시 False로 변경)
# -------------------------------

# 24시간 무중단 실행 시작!
docker-compose up -d --build

# 실행 상태(로그) 확인하기
docker-compose logs -f --tail=100
```

## 3. 관리 명령어
- **정지**: `docker-compose down`
- **재시작**: `docker-compose restart`
- **로그 확인 중지**: `Ctrl + C`
- **프로그램 업데이트 (내 컴퓨터의 최신 코드를 서버에 반영)**:
  ```bash
  git pull origin main
  docker-compose up -d --build
  ```

---
**주의**: `.env` 파일은 절대로 타인에게 노출하지 마세요.
