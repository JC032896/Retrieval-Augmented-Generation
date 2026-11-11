# 앱 이미지: FastAPI + 검색 모델 실행 환경 (CPU). 모델 파일은 넣지 않는다 (/models 볼륨, deploy/README 참고)
#   docker build -t rag-service .
# 1단계: uv로 의존성 설치 (PyTorch는 pyproject의 pytorch-cpu 인덱스에서 CPU 빌드만 받는다)
FROM python:3.12-slim AS build
RUN pip install --no-cache-dir uv==0.13.7
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock .python-version ./
# 의존성만 먼저 설치해 두면, 코드만 바꿨을 때 이 층(수백 MB)을 다시 받지 않는다
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# 2단계: 실행 이미지 (빌드 도구 없이 가상 환경만 복사)
FROM python:3.12-slim
RUN useradd --create-home --uid 10001 rag && mkdir /models && chown rag /models
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts/replay.py ./scripts/replay.py
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models \
    HF_HUB_OFFLINE=1 \
    PRELOAD_MODELS=true
USER rag
EXPOSE 8000
# /ready: DB에 연결되고 모델을 다 읽었을 때만 200. 모델을 읽는 데 1~2분 걸려서 시작 유예를 둔다
HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=4)"]
# 모델이 프로세스마다 메모리에 올라가므로(약 3GB) 워커는 하나로 둔다. 늘리려면 컨테이너를 여러 개 띄운다
CMD ["uvicorn", "rag_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
