FROM python:3.12-slim-bookworm AS base

# media-types는 /etc/mime.types다. 없으면 m4a 녹음을 application/octet-stream으로 보내 Safari가 재생하지 못한다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg media-types \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# 의존성을 먼저 깔아 두면 코드만 바뀌었을 때 이 층을 다시 쓰지 않는다.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
# 배포 스크립트가 지난 이미지를 정리할 때 이 표시로 고른다.
LABEL app=meeting-notes-agent

# GitLab CI가 docker build --target test로 테스트만 돌린다. 앱 이미지에는 들어가지 않는다.
FROM base AS test
RUN uv sync --frozen && pytest -q

FROM base
# 회사 폴더, 결과, 모델 캐시는 바깥에서 붙인다(compose.yaml).
ENV COMPANY_DIR=/company HF_HOME=/models
RUN useradd --uid 10001 --create-home app && mkdir -p jobs && chown app jobs
USER app

EXPOSE 8000
CMD ["uvicorn", "meeting_notes.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
