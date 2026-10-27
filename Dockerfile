FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy TZ=America/Sao_Paulo
# util-linux traz o `unshare` usado para isolar a rede do sandbox
RUN apt-get update && apt-get install -y --no-install-recommends util-linux tzdata && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || uv sync --no-dev --no-install-project
COPY src ./src
COPY config ./config
COPY challenges ./challenges
COPY static ./static
COPY scripts ./scripts
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev
ENV PATH="/app/.venv/bin:$PATH" HOST=0.0.0.0 PORT=8080
RUN useradd -m -u 10001 arena && mkdir -p /app/data && chown -R arena:arena /app
USER arena
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3).status == 200 else 1)"
CMD ["llm-arena", "serve"]
