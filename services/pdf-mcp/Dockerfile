# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/packages/shared/src:/app/services/pdf-mcp/src" \
    PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

COPY packages/shared /app/packages/shared
RUN pip install --no-cache-dir --index-url ${PIP_INDEX_URL} -e /app/packages/shared

COPY services/pdf-mcp /app/services/pdf-mcp
RUN pip install --no-cache-dir --index-url ${PIP_INDEX_URL} -e /app/services/pdf-mcp

EXPOSE 8001

CMD ["python", "-m", "pdf_mcp.server"]
