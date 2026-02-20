# 1. 파이썬 3.10 슬림 버전을 기반으로 시작 (가볍고 빠름)
FROM python:3.10-slim

# 2. 컨테이너 내 작업 디렉토리 설정
WORKDIR /app

# 3. 필요한 시스템 패키지 설치 (시간대 설정 등)
RUN apt-get update && apt-get install -y 
    tzdata 
    && rm -rf /var/lib/apt/lists/*

# 4. 한국 시간대 설정
ENV TZ=Asia/Seoul

# 5. 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. 소스 코드 전체 복사
COPY . .

# 7. 메인 프로그램 실행
CMD ["python", "main.py"]
