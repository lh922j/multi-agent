FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 설치 → 소스 변경 시 pip 레이어 캐시 유지
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 패키지 소스 + 설치 (editable 아닌 일반 install)
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --no-deps .

# 런타임 파일
COPY app/ app/
COPY rag/ rag/

# 볼륨 마운트 포인트 (data/: ChromaDB·모델, logs/: 로그)
RUN mkdir -p /app/data /app/logs

CMD ["uvicorn", "src.multi_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
