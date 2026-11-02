# 後端映像：uv 安裝鎖定版本的套件，uvicorn 啟動。金鑰不進映像，執行時由 compose 從 .env 注入。
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 先裝套件（只看 lock 檔，程式改動不會讓這層快取失效）
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY scripts/docker_init.sh ./scripts/docker_init.sh
COPY data ./data

EXPOSE 8000
CMD ["sh", "-c", "sh scripts/docker_init.sh && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
