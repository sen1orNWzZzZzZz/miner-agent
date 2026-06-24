# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/packages/shared/src:/app/services/news-mcp/src" \
    PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10

# Allow override via build arg; default to Tsinghua mirror for faster CN builds
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

# Shared package first so dependent services see it as installed
COPY packages/shared /app/packages/shared
RUN pip install --no-cache-dir --index-url ${PIP_INDEX_URL} -e /app/packages/shared

# Service package
COPY services/news-mcp /app/services/news-mcp
RUN pip install --no-cache-dir --index-url ${PIP_INDEX_URL} -e /app/services/news-mcp

EXPOSE 8000

CMD ["python", "-m", "news_mcp.server"]
