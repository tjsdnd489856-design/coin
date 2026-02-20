FROM python:3.10-slim

WORKDIR /app

# 시스템 패키지 설치 및 시간대 설정 (에러 방지를 위해 한 줄로 합침)
RUN apt-get update && apt-get install -y tzdata && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Seoul
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
