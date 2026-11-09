FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# 의존성을 먼저 깔아 두면 코드만 바뀌었을 때 이 층을 다시 쓰지 않는다.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev

# 회사 폴더, 결과, 모델 캐시는 바깥에서 붙인다(compose.yaml).
ENV PATH="/app/.venv/bin:$PATH" COMPANY_DIR=/company HF_HOME=/models
RUN useradd --uid 10001 --create-home app && mkdir -p jobs && chown app jobs
USER app

EXPOSE 8000
CMD ["uvicorn", "meeting_notes.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
