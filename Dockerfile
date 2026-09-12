FROM python:3.11.13-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY app ./app
COPY interfaces ./interfaces
RUN python -m pip wheel --wheel-dir /wheels .

FROM python:3.11.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRADING_API_ENV=production \
    TRADING_API_HOST=0.0.0.0 \
    TRADING_API_PORT=8000 \
    TRADING_DB_PATH=/var/lib/trading-system/trading.db \
    TRADING_UNIVERSE_PATH=/etc/trading-system/universe.json

RUN apt-get update && \
    apt-get upgrade --yes && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system --gid 10001 trading && \
    useradd --system --uid 10001 --gid trading --home-dir /nonexistent --shell /usr/sbin/nologin trading && \
    mkdir -p /var/lib/trading-system /etc/trading-system && \
    chown -R trading:trading /var/lib/trading-system
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl && \
    python -m pip uninstall --yes setuptools wheel && \
    rm -rf /wheels /root/.cache
COPY --chown=root:root config/universe.json /etc/trading-system/universe.json
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
ENTRYPOINT ["trading-api"]
